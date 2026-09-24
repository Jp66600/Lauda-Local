"""Orquestração do processamento: probe → extract → diag → asr → align →
diarize → stats → visual → render.

Regras:
* Etapas obrigatórias (probe) falham alto, com mensagem em PT-BR.
* Etapas opcionais nunca derrubam o job: viram `partial_failures` no relatório.
* O arquivo temporário de áudio é sempre removido, inclusive em exceção.
"""

from __future__ import annotations

import logging
import platform
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from . import APP_NAME, APP_VERSION
from .align import refine_segment_boundaries
from .audio_stats import analyze_audio, apply_speech_stats, build_warnings
from .checkpoint import (
    CheckpointStore,
    diarize_fingerprint,
    job_key,
    purge_old,
    stage_index,
)
from .config import JobOptions, OutputPaths
from .coverage import analyze_coverage
from .diarize import diarize as run_diarization
from .errors import LaudaError, UnsupportedMediaError
from .extract import extract_audio, temp_wav_path
from .ffmpeg_tools import resolve_tools
from .limits import apply_process_priority
from .probe import probe_media
from .report import write_plain_transcript, write_report
from .serialize import write_json
from .subtitles import write_srt, write_vtt
from .summarize import summarize_transcript
from .textstats import compute_stats
from .transcribe import transcribe_audio
from .types import (
    AudioDiagnostics,
    DiarizationInfo,
    JobResult,
    LanguageInfo,
    ProcessingInfo,
    SourceInfo,
    StageTiming,
    SummaryInfo,
    VisualInfo,
)
from .utils import human_size, iso_from_epoch, iso_now_local, safe_stem, sha256_file
from .visual import analyze_video

log = logging.getLogger("lauda.pipeline")

#: callback(stage_key, fraction_0_a_1, mensagem)
ProgressFn = Callable[[str, float, str], None]

STAGES: tuple[tuple[str, str], ...] = (
    ("probe", "Lendo metadados"),
    ("extract", "Extraindo áudio"),
    ("vad", "Analisando o áudio"),
    ("asr", "Transcrevendo"),
    ("align", "Alinhando"),
    ("diarize", "Identificando falantes"),
    ("render", "Gerando relatório"),
)


def _noop_progress(stage: str, fraction: float, message: str) -> None:
    log.debug("[%s] %.0f%% %s", stage, fraction * 100, message)


class _StageClock:
    """Cronômetro por etapa, preservando a ordem de execução."""

    def __init__(self) -> None:
        self.timings: list[StageTiming] = []

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        status = "ok"
        try:
            yield
        except Exception:
            status = "erro"
            raise
        finally:
            self.timings.append(
                StageTiming(name=name, seconds=round(time.perf_counter() - started, 3), status=status)
            )

    def skip(self, name: str, reason: str = "") -> None:
        self.timings.append(StageTiming(name=name, seconds=0.0, status="pulado"))
        if reason:
            log.info("Etapa '%s' pulada: %s", name, reason)


def build_source_info(path: Path, known_sha256: str | None = None) -> SourceInfo:
    """Identidade do arquivo. `known_sha256` evita reler um arquivo grande.

    O supervisor ja precisa do hash para achar o ponto de retomada; sem este
    parametro, um video de 4 GB seria lido duas vezes por execucao.
    """
    stat = path.stat()
    return SourceInfo(
        name=path.name,
        path=str(path),
        size_bytes=stat.st_size,
        size_human=human_size(stat.st_size),
        sha256=known_sha256 or sha256_file(path),
        modified_at=iso_from_epoch(stat.st_mtime),
    )

def process_media(
    options: JobOptions,
    progress: ProgressFn | None = None,
    *,
    resume: bool = True,
    checkpoint_root: Path | None = None,
    known_sha256: str | None = None,
) -> JobResult:
    """Executa o pipeline completo e escreve os arquivos de saída.

    Com `resume=True` (padrão), o estado é gravado depois de cada etapa cara.
    Se uma execução anterior do MESMO arquivo com as MESMAS opções morreu no
    meio, esta continua de onde parou em vez de transcrever tudo de novo.
    """
    report_progress = progress or _noop_progress
    started_at = iso_now_local()
    started_perf = time.perf_counter()
    clock = _StageClock()
    partial_failures: list[str] = []

    apply_process_priority(options.limits)

    # ---------------------------------------------------------------- probe --
    report_progress("probe", 0.02, "lendo metadados com ffprobe")
    with clock.measure("probe"):
        probe = probe_media(options.input_path)
        source = build_source_info(options.input_path, known_sha256)

    tools = resolve_tools()
    processing = ProcessingInfo(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        engine="faster-whisper",
        model=options.model,
        device=options.effective_device,
        compute_type=options.compute_type,
        beam_size=options.beam_size,
        vad_enabled=options.vad,
        word_timestamps=options.word_timestamps,
        subtitle_density=options.subtitle_density,
        batch_size=options.batch_size,
        started_at=started_at,
        ffmpeg_version=tools.version,
        python_version=sys.version.split()[0],
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        model_path=str(options.models_dir),
    )

    result = JobResult(
        source=source,
        probe=probe,
        processing=processing,
        language=LanguageInfo(source="manual" if options.language_code else "auto"),
        diagnostics=AudioDiagnostics(),
    )

    # ------------------------------------------------------ ponto de retomada --
    store: CheckpointStore | None = None
    done_through = -1
    saved_wav: Path | None = None
    if resume:
        # Varre o lixo de execucoes esquecidas antes de criar mais um ponto.
        # Sem isto, transcricoes antigas ficariam no perfil indefinidamente.
        purge_old(root=checkpoint_root)
        store = CheckpointStore(job_key(source.sha256, options), root=checkpoint_root)
        saved = store.load()
        if saved is not None and saved.stage_index >= 0:
            done_through = saved.stage_index
            # O ponto é DA diarização e as opções de quem fala mudaram: ele
            # vale até a etapa anterior. A transcrição continua boa; só a
            # separação de falantes precisa ser refeita.
            if (
                saved.stage == "diarize"
                and saved.diarize_key
                and saved.diarize_key != diarize_fingerprint(options)
            ):
                done_through = stage_index("align")
                log.info("Opções de quem fala mudaram: refazendo só a diarização.")
            saved_wav = saved.wav_path
            # Só herdamos o conteúdo; identidade e ambiente são desta execução.
            result.segments = saved.result.segments
            result.text = saved.result.text
            result.language = saved.result.language
            result.diagnostics = saved.result.diagnostics
            result.diarization = saved.result.diarization
            partial_failures.append(
                f"Retomado de um ponto salvo: {saved.describe()}."
            )
            log.info("Retomando o trabalho: %s", saved.describe())
            if saved.result.processing.model:
                processing.model = saved.result.processing.model
                processing.device = saved.result.processing.device
                processing.device_name = saved.result.processing.device_name
                processing.compute_type = saved.result.processing.compute_type
                processing.engine_version = saved.result.processing.engine_version

    def already_done(stage: str) -> bool:
        return stage_index(stage) <= done_through

    paths = OutputPaths(base_dir=options.output_dir, stem=safe_stem(options.input_path.stem))

    with temp_wav_path(keep=options.keep_temp) as temp_path:
        if saved_wav is not None:
            wav_path = saved_wav
        elif store is not None:
            # Extrai DIRETO na pasta do ponto de retomada. Guardar o audio
            # depois significaria copiar centenas de MB sem necessidade.
            store.prepare()
            wav_path = store.wav_path
        else:
            wav_path = temp_path

        # ------------------------------------------------------------ extract --
        audio_ready = False
        if saved_wav is not None:
            clock.skip("extract", "áudio já extraído no ponto de retomada")
            audio_ready = True
        elif probe.has_audio:
            report_progress("extract", 0.08, "extraindo áudio em 16 kHz mono")
            try:
                with clock.measure("extract"):
                    extract_audio(
                        options.input_path,
                        wav_path,
                        probe=probe,
                        threads=options.effective_cpu_threads,
                    )
                audio_ready = True
                if store is not None:
                    store.save("extract", result, wav=wav_path)
            except LaudaError as exc:
                partial_failures.append(f"Extração de áudio: {exc.message}")
                log.error("Extração falhou: %s", exc)
        else:
            clock.skip("extract", "arquivo sem trilha de áudio")
            partial_failures.append(
                "Extração de áudio: o arquivo não possui trilha de áudio."
            )

        # ---------------------------------------------------------------- vad --
        if audio_ready and not already_done("vad"):
            report_progress("vad", 0.15, "medindo volume e silêncio")
            try:
                with clock.measure("vad"):
                    result.diagnostics = analyze_audio(wav_path, duration=probe.duration)
                if store is not None:
                    store.save("vad", result, wav=wav_path)
            except Exception as exc:  # etapa opcional
                partial_failures.append(f"Diagnóstico de áudio: {exc}")
                log.warning("Diagnóstico de áudio falhou: %s", exc)
        else:
            clock.skip("vad")

        # ---------------------------------------------------------------- asr --
        if audio_ready and not already_done("asr"):
            report_progress("asr", 0.20, "carregando modelo de transcrição")
            try:
                with clock.measure("asr"):
                    output = transcribe_audio(
                        wav_path,
                        options,
                        media_duration=probe.duration,
                        progress=lambda fraction, message: report_progress(
                            "asr", 0.20 + fraction * 0.6, message
                        ),
                    )
                result.segments = output.segments
                result.text = output.text
                result.language = output.language
                if output.runtime:
                    processing.model = output.runtime.model
                    processing.device = output.runtime.device
                    processing.device_name = output.runtime.device_name
                    processing.compute_type = output.runtime.compute_type
                    partial_failures.extend(output.runtime.notes)
                processing.engine_version = output.engine_version
                processing.model_path = output.model_path
                # O ponto mais importante de todos: daqui em diante, uma queda
                # não custa mais a transcrição inteira.
                if store is not None:
                    store.save("asr", result, wav=wav_path)
            except LaudaError as exc:
                partial_failures.append(f"Transcrição: {exc.message}")
                log.error("Transcrição falhou: %s", exc)
        else:
            clock.skip("asr")

        # -------------------------------------------------------------- align --
        if result.segments and not already_done("align"):
            report_progress("align", 0.82, "ajustando limites dos segmentos")
            with clock.measure("align"):
                refine_segment_boundaries(result.segments)
            if store is not None:
                store.save("align", result, wav=wav_path)
        else:
            clock.skip("align")
        if options.word_timestamps and not any(seg.words for seg in result.segments):
            partial_failures.append(
                "Alinhamento por palavra: a engine não retornou marcação em nível de palavra."
            )

        # ------------------------------------------------------------ diarize --
        if options.diarize and audio_ready and result.segments and not already_done("diarize"):
            report_progress("diarize", 0.85, "identificando falantes")

            def diarize_progress(fraction: float, message: str) -> None:
                # A etapa ocupa a faixa de 85% a 91%; o resto é a gravação.
                report_progress("diarize", 0.85 + fraction * 0.06, message)

            with clock.measure("diarize"):
                diarization = run_diarization(
                    wav_path, options, segments=result.segments,
                    progress=diarize_progress,
                )
            result.diarization = diarization
            if not diarization.available:
                partial_failures.append(f"Diarização: {diarization.reason}")
            if store is not None:
                store.save(
                    "diarize", result, wav=wav_path,
                    diarize_key=diarize_fingerprint(options),
                )
        elif already_done("diarize"):
            clock.skip("diarize", "falantes já identificados no ponto de retomada")
        else:
            clock.skip("diarize")
            result.diarization = DiarizationInfo(
                available=False,
                reason=(
                    "desligada (use --diarize)"
                    if not options.diarize
                    else "não havia transcrição para atribuir falantes."
                ),
            )

    # A partir daqui o WAV temporário já foi removido.

    # ------------------------------------------------------------- diagnósticos --
    apply_speech_stats(result.diagnostics, result.segments, probe.duration)
    result.diagnostics.warnings = build_warnings(
        result.diagnostics, probe, vad_enabled=options.vad
    )

    # ------------------------------------------------------------------ stats --
    result.stats = compute_stats(
        result.text,
        result.segments,
        language=result.language.code,
        duration=probe.duration,
        top_n=options.top_words,
    )

    # ----------------------------------------------------------------- visual --
    if options.visual:
        try:
            result.visual = analyze_video(
                options.input_path, probe, options, output_dir=paths.sidecar_dir
            )
        except Exception as exc:  # etapa opcional
            result.visual = VisualInfo(enabled=False, reason=f"falhou: {exc}")
            partial_failures.append(f"Camada visual: {exc}")
    else:
        result.visual = VisualInfo(enabled=False, reason="desligada (use --visual).")

    # --------------------------------------------------------------- resumo --
    if options.summarize:
        result.summary = summarize_transcript(result.text, options)
        if not result.summary.available and result.summary.reason:
            partial_failures.append(f"Resumo local: {result.summary.reason}")
    else:
        result.summary = SummaryInfo(available=False, reason="desligado (use --summarize).")

    # ----------------------------------------------------------------- render --
    # A conta da cobertura vem depois de tudo que mexe em segmento (align e
    # diarização) e antes de escrever: é ela que responde se o arquivo inteiro
    # foi percorrido, e a resposta precisa entrar no relatório.
    result.coverage = analyze_coverage(
        result.segments,
        probe.duration,
        result.diagnostics.silence_spans,
    )

    report_progress("render", 0.92, "gravando arquivos de saída")
    finished_perf = time.perf_counter()
    processing.finished_at = iso_now_local()
    processing.elapsed_seconds = round(finished_perf - started_perf, 3)
    if probe.duration and processing.elapsed_seconds > 0:
        processing.realtime_factor = round(probe.duration / processing.elapsed_seconds, 2)
    processing.stages = clock.timings
    result.partial_failures = partial_failures

    with clock.measure("render"):
        options.output_dir.mkdir(parents=True, exist_ok=True)
        outputs: dict[str, str] = {}
        if options.write_txt:
            outputs["report.txt"] = str(write_report(paths.report_txt, result))
        if options.write_transcript:
            outputs["transcript.txt"] = str(write_plain_transcript(paths.transcript_txt, result))
        if options.write_srt and result.segments:
            outputs["srt"] = str(write_srt(
                paths.srt, result.segments, density=options.subtitle_density
            ))
        if options.write_vtt and result.segments:
            outputs["vtt"] = str(write_vtt(
                paths.vtt, result.segments, density=options.subtitle_density
            ))
        result.outputs = outputs
        if options.write_json:
            outputs["data.json"] = str(paths.data_json)
            result.outputs = outputs
            write_json(paths.data_json, result)

    # Regrava o TXT fora do cronômetro para que o rodapé traga a lista final de
    # arquivos E a seção 3 traga o tempo da própria etapa de render.
    if options.write_txt:
        write_report(paths.report_txt, result)

    # Concluiu: o ponto de retomada vira lixo e sai do disco.
    if store is not None:
        store.clear()

    report_progress("render", 1.0, "concluído")
    log.info(
        "Concluído em %.1f s (%.2fx tempo real).",
        processing.elapsed_seconds,
        processing.realtime_factor or 0.0,
    )
    return result


def ensure_processable(options: JobOptions) -> None:
    """Validação rápida antes de gastar tempo (arquivo existe, ffmpeg existe)."""
    if not options.input_path.exists():
        raise UnsupportedMediaError(f"Arquivo não encontrado: {options.input_path}")
    resolve_tools()
