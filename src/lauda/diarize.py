"""Diarização de falantes (Fase 3) — best-effort, com dois backends.

1. **pyannote** (`pyannote/speaker-diarization-3.1`) — melhor qualidade, mas os
   pesos são *gated* no Hugging Face: exigem conta, aceite dos termos e
   `HF_TOKEN` (ou os pesos já baixados em `./models`).
2. **ecapa** (`speechbrain/spkrec-ecapa-voxceleb`) — **sem token**: embeddings
   de locutor por trecho + clusterização aglomerativa. Qualidade inferior à do
   pyannote, principalmente com fala sobreposta, mas roda sem burocracia.

Ambos são opcionais (`pip install -r requirements-diarize.txt`). Sem eles, a
função devolve `DiarizationInfo(available=False, reason=...)` e o relatório
imprime `[INDISPONÍVEL] Diarização: <motivo>`. Nada aqui levanta exceção.
"""

from __future__ import annotations

import logging
import math
import os
import wave
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .config import JobOptions
from .logging_setup import quiet_third_party
from .types import DiarizationInfo, SegmentInfo, SpeakerStat

#: callback(fracao 0..1, mensagem) — dá sinal de vida durante a etapa.
ProgressFn = Callable[[float, str], None]

#: De quantos em quantos trechos a etapa avisa que está viva. Vinte é o
#: bastante para o supervisor não confundir lentidão com travamento, e pouco
#: o suficiente para não inundar o log.
_PROGRESS_EVERY = 20

log = logging.getLogger("lauda.diarize")

PYANNOTE_PIPELINE = "pyannote/speaker-diarization-3.1"
ECAPA_MODEL = "speechbrain/spkrec-ecapa-voxceleb"

#: Trechos menores que isto não rendem embedding confiável.
_MIN_CHUNK_SECONDS = 0.6
#: Segmentos longos viram vários trechos para captar troca de falante.
_MAX_CHUNK_SECONDS = 4.0


@dataclass(frozen=True)
class SpeakerTurn:
    """Intervalo contínuo atribuído a um falante."""

    start: float
    end: float
    speaker: str


@dataclass(frozen=True)
class DiarizationReadiness:
    ready: bool
    reason: str
    backend: str | None = None


# --------------------------------------------------------------------------- #
# Disponibilidade
# --------------------------------------------------------------------------- #
def _has_torch() -> bool:
    return find_spec("torch") is not None


def _pyannote_local_path(options: JobOptions) -> Path:
    return options.models_dir / "pyannote" / "speaker-diarization-3.1"


def _hf_token(options: JobOptions) -> str:
    return (options.hf_token or os.environ.get("HF_TOKEN") or "").strip()


def check_readiness(options: JobOptions) -> DiarizationReadiness:
    """Diz, em português claro, qual backend dá para usar neste ambiente."""
    requested = options.diarize_backend

    if not _has_torch():
        return DiarizationReadiness(
            False,
            "PyTorch não instalado (rode: pip install -r requirements-diarize.txt).",
        )

    if requested in ("auto", "pyannote") and find_spec("pyannote") is not None:
        if _pyannote_local_path(options).exists():
            return DiarizationReadiness(True, "pyannote com pesos locais", backend="pyannote")
        if _hf_token(options):
            return DiarizationReadiness(True, "pyannote com HF_TOKEN", backend="pyannote")
        if requested == "pyannote":
            return DiarizationReadiness(
                False,
                f"{PYANNOTE_PIPELINE} é gated no Hugging Face e não há HF_TOKEN nem pesos "
                f"locais em {_pyannote_local_path(options)}.",
            )

    if requested in ("auto", "ecapa") and find_spec("speechbrain") is not None:
        return DiarizationReadiness(
            True, "speechbrain ECAPA (sem token)", backend="ecapa"
        )

    if requested == "ecapa":
        return DiarizationReadiness(
            False, "speechbrain não instalado (pip install speechbrain)."
        )

    return DiarizationReadiness(
        False,
        "nenhum backend disponível: instale pyannote.audio (com HF_TOKEN) ou speechbrain.",
    )


# --------------------------------------------------------------------------- #
# Backend 1: pyannote
# --------------------------------------------------------------------------- #
def _run_pyannote(wav_path: Path, options: JobOptions) -> list[SpeakerTurn]:
    import torch
    from pyannote.audio import Pipeline

    quiet_third_party(verbose=log.isEnabledFor(logging.DEBUG))

    local = _pyannote_local_path(options)
    source = str(local / "config.yaml") if (local / "config.yaml").exists() else PYANNOTE_PIPELINE
    token = _hf_token(options) or None

    pipeline = Pipeline.from_pretrained(source, use_auth_token=token)
    if pipeline is None:
        raise RuntimeError(
            "o Hugging Face devolveu None: normalmente significa que os termos do "
            f"{PYANNOTE_PIPELINE} não foram aceitos com a conta deste token."
        )
    if torch.cuda.is_available() and options.device != "cpu":
        pipeline.to(torch.device("cuda"))

    kwargs: dict[str, int] = {}
    if options.num_speakers:
        kwargs["num_speakers"] = options.num_speakers
    else:
        if options.min_speakers:
            kwargs["min_speakers"] = options.min_speakers
        if options.max_speakers:
            kwargs["max_speakers"] = options.max_speakers

    annotation = pipeline(str(wav_path), **kwargs)
    return [
        SpeakerTurn(start=float(turn.start), end=float(turn.end), speaker=str(speaker))
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


# --------------------------------------------------------------------------- #
# Backend 2: ECAPA + clusterização (sem token)
# --------------------------------------------------------------------------- #
def _read_wav_mono(path: Path) -> tuple[Any, int]:
    """Lê um WAV PCM 16-bit mono como float32 em [-1, 1]."""
    import numpy as np

    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise RuntimeError("o backend ECAPA espera WAV PCM 16 bits.")
        rate = handle.getframerate()
        channels = handle.getnchannels()
        raw = handle.readframes(handle.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:  # pragma: no cover - o pipeline já entrega mono
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, rate


def _chunks_from_segments(segments: list[SegmentInfo]) -> list[tuple[int, float, float]]:
    """Divide segmentos longos em trechos de até 4 s: (índice do segmento, ini, fim)."""
    chunks: list[tuple[int, float, float]] = []
    for position, segment in enumerate(segments):
        duration = segment.duration
        if duration < _MIN_CHUNK_SECONDS:
            continue
        pieces = max(1, math.ceil(duration / _MAX_CHUNK_SECONDS))
        step = duration / pieces
        for piece in range(pieces):
            start = segment.start + piece * step
            chunks.append((position, start, min(segment.end, start + step)))
    return chunks


def _cosine_distances(embeddings):
    import numpy as np

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / np.clip(norms, 1e-9, None)
    similarity = np.clip(normalized @ normalized.T, -1.0, 1.0)
    return 1.0 - similarity


def _agglomerative(
    embeddings,
    *,
    threshold: float,
    num_speakers: int | None,
    min_speakers: int,
    max_speakers: int,
) -> list[int]:
    """Clusterização aglomerativa (average linkage) sobre distância de cosseno.

    Implementada aqui para não arrastar scipy/sklearn só por isto. O número de
    trechos é da ordem de centenas, então O(n²) é irrelevante.
    """
    import numpy as np

    count = len(embeddings)
    if count == 0:
        return []
    if count == 1:
        return [0]

    distances = _cosine_distances(embeddings)
    clusters: list[list[int]] = [[index] for index in range(count)]

    def cluster_distance(left: list[int], right: list[int]) -> float:
        return float(distances[np.ix_(left, right)].mean())

    while len(clusters) > 1:
        best = (math.inf, -1, -1)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                distance = cluster_distance(clusters[i], clusters[j])
                if distance < best[0]:
                    best = (distance, i, j)

        distance, i, j = best
        target = num_speakers or 0
        if target:
            if len(clusters) <= target:
                break
        elif distance > threshold and len(clusters) <= max_speakers:
            break
        if len(clusters) <= min_speakers and not target:
            break
        clusters[i] = clusters[i] + clusters[j]
        del clusters[j]

    # Rótulo estável: ordena os clusters pelo primeiro trecho que aparece.
    clusters.sort(key=lambda members: min(members))
    labels = [0] * count
    for label, members in enumerate(clusters):
        for member in members:
            labels[member] = label
    return labels


def _limit_torch_threads(options: JobOptions) -> None:
    """Faz o limite de CPU valer também para o torch.

    Sem isto o controle de CPU da página Desempenho valia só para a
    transcrição: o torch abria uma thread por thread lógica e comia a máquina
    inteira na etapa de quem fala — justamente a etapa mais longa de quem não
    tem placa NVIDIA e roda tudo no processador.
    """
    import torch

    threads = options.limits.cpu_threads()
    try:
        torch.set_num_threads(threads)
    except Exception as exc:  # pragma: no cover - build de torch sem OpenMP
        log.debug("Não consegui limitar as threads do torch: %s", exc)
        return
    log.debug("torch limitado a %d thread(s) na diarização.", threads)


def _run_ecapa(
    wav_path: Path,
    options: JobOptions,
    segments: list[SegmentInfo],
    progress: ProgressFn | None = None,
) -> list[SpeakerTurn]:
    import numpy as np
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    # O speechbrain sobe o proprio logger para INFO no import; devolve ao lugar.
    quiet_third_party(verbose=log.isEnabledFor(logging.DEBUG))

    chunks = _chunks_from_segments(segments)
    if not chunks:
        return []

    audio, rate = _read_wav_mono(wav_path)
    device = "cuda" if (torch.cuda.is_available() and options.device != "cpu") else "cpu"
    if device == "cpu":
        _limit_torch_threads(options)
    savedir = options.models_dir / "speechbrain" / "spkrec-ecapa-voxceleb"
    savedir.mkdir(parents=True, exist_ok=True)

    # No Windows sem "modo desenvolvedor", criar symlink exige privilégio de
    # administrador; o padrão do speechbrain quebra com WinError 1314. COPY
    # resolve e custa alguns MB de disco.
    kwargs: dict[str, object] = {
        "source": ECAPA_MODEL,
        "savedir": str(savedir),
        "run_opts": {"device": device},
    }
    try:
        from speechbrain.utils.fetching import LocalStrategy

        kwargs["local_strategy"] = LocalStrategy.COPY
    except Exception as exc:  # pragma: no cover - speechbrain < 1.0
        log.debug("speechbrain sem LocalStrategy (%s); usando o padrao dele.", exc)

    encoder = EncoderClassifier.from_hparams(**kwargs)
    quiet_third_party(verbose=log.isEnabledFor(logging.DEBUG))

    embeddings: list[np.ndarray] = []
    kept: list[tuple[int, float, float]] = []
    total = len(chunks)
    for posicao, (segment_index, start, end) in enumerate(chunks):
        # Sinal de vida a cada punhado de trechos. Sem isto a etapa fica muda
        # por minutos numa reuniao longa, e o supervisor mata um processo que
        # so estava lento — foi exatamente o que aconteceu com um arquivo de
        # 1094 trechos.
        if progress is not None and posicao % _PROGRESS_EVERY == 0:
            progress(
                posicao / total,
                f"identificando falantes ({posicao}/{total})",
            )
        begin = int(start * rate)
        finish = min(len(audio), int(end * rate))
        piece = audio[begin:finish]
        if len(piece) < int(_MIN_CHUNK_SECONDS * rate):
            continue
        with torch.no_grad():
            tensor = torch.from_numpy(piece).unsqueeze(0).to(device)
            vector = encoder.encode_batch(tensor).squeeze().cpu().numpy()
        embeddings.append(np.asarray(vector, dtype=np.float32).reshape(-1))
        kept.append((segment_index, start, end))

    if not embeddings:
        return []

    labels = _agglomerative(
        np.vstack(embeddings),
        threshold=options.speaker_threshold,
        num_speakers=options.num_speakers,
        min_speakers=max(1, options.min_speakers or 1),
        max_speakers=max(1, options.max_speakers or 10),
    )

    # strict=True de proposito: um numero de rotulos diferente do numero de
    # trechos seria um bug de clusterizacao, e falhar alto e melhor que rotular
    # o falante errado silenciosamente.
    turns = [
        SpeakerTurn(start=start, end=end, speaker=f"SPEAKER_{label:02d}")
        for (_, start, end), label in zip(kept, labels, strict=True)
    ]
    return _merge_turns(turns)


def _merge_turns(turns: list[SpeakerTurn], gap: float = 0.4) -> list[SpeakerTurn]:
    """Junta trechos vizinhos do mesmo falante para um relatório legível."""
    ordered = sorted(turns, key=lambda turn: turn.start)
    merged: list[SpeakerTurn] = []
    for turn in ordered:
        if merged and merged[-1].speaker == turn.speaker and turn.start - merged[-1].end <= gap:
            previous = merged.pop()
            merged.append(
                SpeakerTurn(previous.start, max(previous.end, turn.end), turn.speaker)
            )
        else:
            merged.append(turn)
    return merged


# --------------------------------------------------------------------------- #
# Atribuição e estatísticas
# --------------------------------------------------------------------------- #
def assign_speakers(segments: list[SegmentInfo], turns: list[SpeakerTurn]) -> int:
    """Marca cada segmento com o falante de maior sobreposição temporal.

    Também propaga o falante para as palavras, quando existirem. Devolve
    quantos segmentos receberam falante.
    """
    if not turns:
        return 0

    assigned = 0
    for segment in segments:
        overlaps: dict[str, float] = {}
        for turn in turns:
            overlap = min(segment.end, turn.end) - max(segment.start, turn.start)
            if overlap > 0:
                overlaps[turn.speaker] = overlaps.get(turn.speaker, 0.0) + overlap
        if overlaps:
            # Desempate alfabético mantém a saída determinística.
            segment.speaker = max(sorted(overlaps), key=lambda name: overlaps[name])
            assigned += 1
    return assigned


def renumber_speakers(segments: list[SegmentInfo]) -> dict[str, str]:
    """Renumera os falantes na ordem em que aparecem: SPEAKER_00, SPEAKER_01, …

    O clusterizador pode produzir rótulos com buracos (um cluster que não venceu
    nenhum segmento), e "SPEAKER_00 e SPEAKER_02" confunde quem lê o laudo.
    """
    mapping: dict[str, str] = {}
    for segment in segments:
        if segment.speaker and segment.speaker not in mapping:
            mapping[segment.speaker] = f"SPEAKER_{len(mapping):02d}"
    for segment in segments:
        if segment.speaker:
            segment.speaker = mapping[segment.speaker]
    return mapping


def speaker_stats(segments: list[SegmentInfo], duration: float | None) -> list[SpeakerStat]:
    """Tempo de fala por falante, ordenado por tempo decrescente."""
    totals: dict[str, list[float]] = {}
    for segment in segments:
        if not segment.speaker:
            continue
        bucket = totals.setdefault(segment.speaker, [0.0, 0.0])
        bucket[0] += segment.duration
        bucket[1] += 1

    total_speech = sum(value[0] for value in totals.values()) or 1.0
    stats = [
        SpeakerStat(
            speaker=speaker,
            seconds=round(seconds, 3),
            ratio=round(seconds / total_speech, 4),
            segments=int(count),
        )
        for speaker, (seconds, count) in totals.items()
    ]
    return sorted(stats, key=lambda stat: (-stat.seconds, stat.speaker))


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def diarize(
    wav_path: Path,
    options: JobOptions,
    *,
    segments: list[SegmentInfo],
    progress: ProgressFn | None = None,
) -> DiarizationInfo:
    """Executa a diarização quando possível. Nunca levanta exceção para cima."""
    readiness = check_readiness(options)
    if not readiness.ready or readiness.backend is None:
        log.info("Diarização desligada: %s", readiness.reason)
        return DiarizationInfo(available=False, reason=readiness.reason)

    backend = readiness.backend
    try:
        if backend == "pyannote":
            # O pyannote e uma chamada unica e fechada: nao da para subdividir,
            # entao o aviso vai antes dela.
            if progress is not None:
                progress(0.0, "identificando falantes (pyannote)")
            turns = _run_pyannote(wav_path, options)
        else:
            turns = _run_ecapa(wav_path, options, segments, progress)
    except Exception as exc:
        reason = f"o backend '{backend}' falhou: {exc.__class__.__name__}: {exc}"
        log.warning("Diarização falhou: %s", reason)
        return DiarizationInfo(available=False, backend=backend, reason=reason[:400])

    if not turns:
        return DiarizationInfo(
            available=False,
            backend=backend,
            reason="nenhum trecho de fala com duração suficiente para identificar falantes.",
        )

    assigned = assign_speakers(segments, turns)
    renumber_speakers(segments)
    if assigned == 0:
        return DiarizationInfo(
            available=False,
            backend=backend,
            reason="os falantes detectados não se sobrepõem a nenhum segmento transcrito.",
        )

    stats = speaker_stats(segments, None)
    log.info("Diarização (%s): %d falante(s) em %d turnos.", backend, len(stats), len(turns))
    return DiarizationInfo(
        available=True,
        backend=f"{backend} ({PYANNOTE_PIPELINE if backend == 'pyannote' else ECAPA_MODEL})",
        speakers=stats,
        speaker_count=len(stats),
    )
