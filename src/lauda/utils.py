"""Utilidades puras: hashing, formatacao de tempo/tamanho, texto.

Tudo aqui e deterministico: mesma entrada -> mesma saida. O relatorio depende
disso para que dois processamentos do mesmo arquivo gerem TXT identico.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

_HASH_CHUNK = 1024 * 1024  # 1 MiB: streaming, nunca carrega o arquivo na RAM


def sha256_file(path: Path, chunk_size: int = _HASH_CHUNK) -> str:
    """SHA-256 do arquivo lido em streaming."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def human_size(num_bytes: int) -> str:
    """Tamanho legivel (base 1024), sempre com 2 casas a partir de KB."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    units = ["KB", "MB", "GB", "TB", "PB"]
    value = float(num_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}".replace(".", ",")
    return f"{value:.2f} PB".replace(".", ",")  # pragma: no cover - inalcancavel


def format_timestamp(seconds: float | None, *, always_hours: bool = True) -> str:
    """Formata segundos como HH:MM:SS.mmm (padrao do relatorio)."""
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return "--:--:--.---"
    seconds = max(0.0, float(seconds))
    # Arredonda em milissegundos ANTES de dividir, para evitar 00:00:59.9996 -> 00:00:59.1000
    total_ms = round(seconds * 1000.0)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    if hours == 0 and not always_hours:
        return f"{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_srt_time(seconds: float) -> str:
    """HH:MM:SS,mmm (SubRip usa virgula)."""
    return format_timestamp(seconds).replace(".", ",")


def format_duration_human(seconds: float | None) -> str:
    """Duracao curta para leitura humana: '1h 02min 03s' / '45,2 s'."""
    if seconds is None:
        return "desconhecida"
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.1f} s".replace(".", ",")
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}min {secs:02d}s"
    return f"{minutes}min {secs:02d}s"


def iso_now_local() -> str:
    """Data/hora atual em ISO-8601 com offset do fuso local."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def iso_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).astimezone().replace(
        microsecond=0
    ).isoformat()


_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_stem(name: str, max_len: int = 80) -> str:
    """Nome de arquivo seguro derivado do original (sem acentos nem separadores)."""
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_RE.sub("_", ascii_only).strip("._-")
    return (slug or "midia")[:max_len]


def wrap_text(text: str, width: int = 78, indent: str = "") -> list[str]:
    """Quebra de linha simples por palavras (nao quebra palavras longas)."""
    import textwrap

    if not text.strip():
        return []
    return textwrap.wrap(
        text.strip(),
        width=width,
        initial_indent=indent,
        subsequent_indent=indent,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [indent + text.strip()]


def wrap_bullet(text: str, *, width: int = 78, indent: str = "    ", bullet: str = "- ") -> list[str]:
    """Item de lista com recuo pendurado: a continuacao alinha sob o texto."""
    import textwrap

    return textwrap.wrap(
        text.strip(),
        width=width,
        initial_indent=indent + bullet,
        subsequent_indent=indent + " " * len(bullet),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [indent + bullet + text.strip()]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def chunked(items: Iterable[str], size: int) -> Iterator[list[str]]:
    buffer: list[str] = []
    for item in items:
        buffer.append(item)
        if len(buffer) >= size:
            yield buffer
            buffer = []
    if buffer:
        yield buffer
