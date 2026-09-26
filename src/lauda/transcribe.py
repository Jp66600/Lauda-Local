"""Transcrição offline com faster-whisper (CTranslate2).

Decisões que importam:
* VAD ligado por padrão — o Whisper alucina texto em silêncio prolongado.
* `condition_on_previous_text=False` por padrão — evita que uma alucinação
  contamine todos os segmentos seguintes.
* Se a GPU falhar (cuDNN ausente, VRAM insuficiente), cai para CPU sozinho.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import JobOptions
from .errors import ModelNotAvailableError, TranscriptionError
from .hardware import RuntimeChoice, cpu_fallback, detect_hardware, select_runtime
from .types import LanguageInfo, SegmentInfo, WordInfo

log = logging.getLogger("lauda.transcribe")

ProgressCallback = Callable[[float, str], None]

#: Sinais típicos de GPU sem as bibliotecas CUDA/cuDNN corretas.
_GPU_FAILURE_MARKERS = (
    "cudnn",
    "cublas",
    "cuda",
    "libcudnn",
    "out of memory",
    "no kernel image",
    "invalid device",
)


@dataclass
class TranscriptionOutput:
    segments: list[SegmentInfo] = field(default_factory=list)
    text: str = ""
    language: LanguageInfo = field(default_factory=LanguageInfo)
    duration: float | None = None
    duration_after_vad: float | None = None
    runtime: RuntimeChoice | None = None
    engine_version: str = ""
    model_path: str | None = None
    batch_size: int = 0


def _engine_version() -> str:
    try:
        import faster_whisper

        return getattr(faster_whisper, "__version__", "desconhecida")
    except Exception:  # pragma: no cover
        return "desconhecida"


def _looks_like_gpu_failure(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _GPU_FAILURE_MARKERS)


def _load_model(choice: RuntimeChoice, options: JobOptions) -> Any:
    from faster_whisper import WhisperModel

    options.models_dir.mkdir(parents=True, exist_ok=True)
    offline = os.environ.get("LAUDA_OFFLINE", "").strip() in ("1", "true", "True")
    log.info(
        "Carregando modelo '%s' (device=%s, compute_type=%s, %d threads)…",
        choice.model,
        choice.device,
        choice.compute_type,
        options.effective_cpu_threads,
    )
    return WhisperModel(
        choice.model,
        device=choice.device,
        compute_type=choice.compute_type,
        download_root=str(options.models_dir),
        local_files_only=offline,
        cpu_threads=options.effective_cpu_threads,
        num_workers=options.limits.gpu_workers() if choice.device == "cuda" else 1,
    )


def load_model_with_fallback(options: JobOptions) -> tuple[Any, RuntimeChoice]:
    """Carrega o modelo, rebaixando para CPU se a GPU não colaborar."""
    choice = select_runtime(
        requested_device=options.effective_device,
        requested_compute_type=options.compute_type,
        requested_model=options.model,
        hardware=detect_hardware(),
        limits=options.limits,
    )
    try:
        return _load_model(choice, options), choice
    except Exception as exc:
        if choice.device == "cuda" and _looks_like_gpu_failure(exc):
            log.warning("Falha ao usar a GPU (%s). Tentando CPU…", exc.__class__.__name__)
            fallback = cpu_fallback(
                choice, f"{exc.__class__.__name__}: {exc}"[:200], options.limits
            )
            try:
                return _load_model(fallback, options), fallback
            except Exception as cpu_exc:  # pragma: no cover - ambiente muito quebrado
                raise TranscriptionError(
                    "Não consegui carregar o modelo nem na GPU nem na CPU.",
                    hint=str(cpu_exc)[:400],
                ) from cpu_exc
        if "local_files_only" in str(exc) or "not found" in str(exc).lower():
            raise ModelNotAvailableError(
                f"O modelo '{choice.model}' não está em {options.models_dir} e o download "
                "está desabilitado (LAUDA_OFFLINE).",
                hint="Rode: python scripts/download_models.py --model " + choice.model,
            ) from exc
        raise TranscriptionError(
            f"Falha ao carregar o modelo '{choice.model}'.", hint=str(exc)[:400]
        ) from exc


class _GpuRuntimeFailure(RuntimeError):
    """A GPU carregou o modelo mas falhou ao inferir (cuBLAS/cuDNN/VRAM)."""


def _run_onnx(
    wav_path: Path,
    options: JobOptions,
    choice: RuntimeChoice,
    progress: ProgressCallback | None,
    media_duration: float | None,
) -> TranscriptionOutput:
    """Transcreve pelo segundo motor, na placa que não é NVIDIA."""
    from . import onnx_engine

    saida = onnx_engine.transcribe(
        wav_path, options, choice, progress=progress, media_duration=media_duration
    )
    if not saida.segments:
        raise TranscriptionError("A placa de vídeo não devolveu nenhum trecho.")
    return saida


def transcribe_audio(
    wav_path: Path,
    options: JobOptions,
    *,
    progress: ProgressCallback | None = None,
    media_duration: float | None = None,
) -> TranscriptionOutput:
    """Transcreve o WAV normalizado e devolve segmentos + idioma detectado.

    Se a GPU falhar no meio do caminho — o caso clássico é `cublas64_12.dll`
    ausente, que só aparece na primeira inferência — refaz tudo na CPU em vez
    de devolver um relatório vazio.
    """
    escolha = select_runtime(
        requested_device=options.effective_device,
        requested_compute_type=options.compute_type,
        requested_model=options.model,
        hardware=detect_hardware(),
        limits=options.limits,
    )
    if escolha.engine == "onnx":
        try:
            return _run_onnx(wav_path, options, escolha, progress, media_duration)
        except Exception as exc:
            # A placa não-NVIDIA é um ganho, não um requisito: se ela falhar, o
            # trabalho continua no processador em vez de morrer. O motivo vai
            # para o registro inteiro, porque é assim que ele chega até mim.
            log.warning(
                "O segundo motor (placa de vídeo) falhou: %s. Refazendo no processador.",
                exc, exc_info=log.isEnabledFor(logging.DEBUG),
            )

    model, choice = load_model_with_fallback(options)
    try:
        return _run_transcription(
            model, choice, wav_path, options, progress=progress, media_duration=media_duration
        )
    except _GpuRuntimeFailure as exc:
        log.warning("GPU falhou durante a transcrição (%s). Refazendo na CPU…", exc)
        fallback = cpu_fallback(choice, str(exc)[:200], options.limits)
        cpu_model = _load_model(fallback, options)
        return _run_transcription(
            cpu_model,
            fallback,
            wav_path,
            options,
            progress=progress,
            media_duration=media_duration,
        )


def _make_engine(model: Any, options: JobOptions) -> tuple[Any, dict[str, Any]]:
    """Escolhe entre transcrição sequencial e em lote.

    O modo em lote (`batch_size > 0`) é bem mais rápido, mas produz trechos
    muito mais longos — medimos ~6x mais grossos. Isso estraga legenda e
    piora a diarização, então ele é opt-in e nunca o padrão.
    """
    if options.batch_size <= 0:
        return model, {}

    try:
        from faster_whisper import BatchedInferencePipeline
    except ImportError:  # pragma: no cover - faster-whisper antigo
        log.warning("Esta versão do faster-whisper não tem inferência em lote.")
        return model, {}

    log.info("Modo rápido ligado (lotes de %d).", options.batch_size)
    return BatchedInferencePipeline(model=model), {"batch_size": options.batch_size}


def _run_transcription(
    model: Any,
    choice: RuntimeChoice,
    wav_path: Path,
    options: JobOptions,
    *,
    progress: ProgressCallback | None,
    media_duration: float | None,
) -> TranscriptionOutput:
    vad_parameters = {"min_silence_duration_ms": 500, "speech_pad_ms": 200}
    engine, extra = _make_engine(model, options)
    try:
        segments_iter, info = engine.transcribe(
            str(wav_path),
            language=options.language_code,
            beam_size=options.beam_size,
            temperature=options.temperature,
            initial_prompt=options.initial_prompt,
            word_timestamps=options.word_timestamps,
            vad_filter=options.vad,
            vad_parameters=vad_parameters if options.vad else None,
            condition_on_previous_text=options.condition_on_previous_text,
            **extra,
        )
    except Exception as exc:
        if choice.device == "cuda" and _looks_like_gpu_failure(exc):
            raise _GpuRuntimeFailure(str(exc)[:300]) from exc
        raise TranscriptionError("A engine de STT falhou ao iniciar.", hint=str(exc)[:400]) from exc

    total = media_duration or getattr(info, "duration", None) or 0.0
    collected: list[SegmentInfo] = []

    try:
        for index, segment in enumerate(segments_iter):
            words: list[WordInfo] = []
            for word in getattr(segment, "words", None) or []:
                words.append(
                    WordInfo(
                        start=round(float(word.start), 3),
                        end=round(float(word.end), 3),
                        word=word.word,
                        probability=round(float(word.probability), 4)
                        if word.probability is not None
                        else None,
                    )
                )
            collected.append(
                SegmentInfo(
                    id=index,
                    start=round(float(segment.start), 3),
                    end=round(float(segment.end), 3),
                    text=segment.text.strip(),
                    words=words,
                    avg_logprob=round(float(segment.avg_logprob), 4)
                    if segment.avg_logprob is not None
                    else None,
                    no_speech_prob=round(float(segment.no_speech_prob), 4)
                    if segment.no_speech_prob is not None
                    else None,
                    compression_ratio=round(float(segment.compression_ratio), 4)
                    if segment.compression_ratio is not None
                    else None,
                    temperature=getattr(segment, "temperature", None),
                )
            )
            if progress and total:
                done = min(1.0, float(segment.end) / total)
                progress(done, f"transcrevendo {done * 100:.0f}%")
    except Exception as exc:
        if choice.device == "cuda" and _looks_like_gpu_failure(exc):
            raise _GpuRuntimeFailure(str(exc)[:300]) from exc
        raise TranscriptionError("Erro durante a transcrição.", hint=str(exc)[:400]) from exc
    finally:
        # Libera VRAM assim que possível; o GC do Python demoraria demais.
        del model

    language = LanguageInfo(
        code=getattr(info, "language", None) or options.language_code,
        probability=round(float(info.language_probability), 4)
        if getattr(info, "language_probability", None) is not None
        else None,
        source="manual" if options.language_code else "auto",
    )

    return TranscriptionOutput(
        segments=collected,
        text=" ".join(seg.text for seg in collected).strip(),
        language=language,
        duration=getattr(info, "duration", None),
        duration_after_vad=getattr(info, "duration_after_vad", None),
        runtime=choice,
        engine_version=_engine_version(),
        model_path=str(options.models_dir),
        batch_size=options.batch_size,
    )
