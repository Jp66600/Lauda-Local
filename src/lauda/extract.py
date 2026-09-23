"""Extração/normalização do áudio para STT: WAV PCM 16-bit, 16 kHz, mono.

O ffmpeg trabalha em streaming: nem o vídeo nem o WAV completo passam pela RAM
do Python. O arquivo temporário é sempre removido no `finally`.
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import TARGET_CHANNELS, TARGET_SAMPLE_RATE
from .errors import ExtractionError, UnsupportedMediaError
from .ffmpeg_tools import resolve_tools, run
from .types import ProbeResult

log = logging.getLogger("lauda.extract")


@contextmanager
def temp_wav_path(prefix: str = "lauda_", keep: bool = False) -> Iterator[Path]:
    """Cria um caminho .wav temporário e garante a remoção ao sair do bloco."""
    handle, name = tempfile.mkstemp(prefix=prefix, suffix=".wav")
    os.close(handle)  # o ffmpeg escreve por cima; só queremos o nome reservado
    path = Path(name)
    try:
        yield path
    finally:
        if keep:
            log.info("Arquivo temporário mantido a pedido: %s", path)
        else:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - antivírus/lock no Windows
                log.warning("Não consegui remover o temporário %s: %s", path, exc)


def extract_audio(
    source: Path,
    destination: Path,
    *,
    probe: ProbeResult | None = None,
    stream_index: int | None = None,
    timeout: float | None = None,
    threads: int = 0,
) -> Path:
    """Converte a primeira trilha de áudio de `source` em WAV 16 kHz mono.

    `stream_index` é o índice absoluto do stream no container (o mesmo que o
    ffprobe reporta); quando None usa a primeira trilha de áudio.
    """
    source, destination = Path(source), Path(destination)
    if probe is not None and not probe.has_audio:
        raise UnsupportedMediaError(
            f"O arquivo {source.name} não possui trilha de áudio.",
            hint="Vídeos mudos geram relatório de metadados, mas não há o que transcrever.",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    mapping = f"0:{stream_index}" if stream_index is not None else "0:a:0"
    tools = resolve_tools()
    args = [
        tools.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel", "error",
        "-y",
    ]
    if threads > 0:
        args += ["-threads", str(threads)]
    args += [
        "-i", str(source),
        "-map", mapping,
        "-vn", "-sn", "-dn",
        "-ac", str(TARGET_CHANNELS),
        "-ar", str(TARGET_SAMPLE_RATE),
        "-acodec", "pcm_s16le",
        "-f", "wav",
        str(destination),
    ]
    proc = run(args, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()[-5:]
        raise ExtractionError(
            f"Falha ao extrair o áudio de {source.name}.",
            hint="\n".join(detail) or "O ffmpeg terminou com erro sem detalhar a causa.",
        )
    if not destination.exists() or destination.stat().st_size <= 44:  # 44 = header WAV vazio
        raise ExtractionError(
            f"O áudio extraído de {source.name} ficou vazio.",
            hint="A trilha pode estar corrompida ou ter duração zero.",
        )

    log.debug(
        "áudio extraído: %s (%.1f KB)", destination.name, destination.stat().st_size / 1024
    )
    return destination


def wav_duration_seconds(path: Path) -> float | None:
    """Duração de um WAV PCM lida do cabeçalho (sem depender do ffprobe)."""
    import wave

    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            return frames / float(rate) if rate else None
    except Exception:  # pragma: no cover - WAV não-PCM
        return None
