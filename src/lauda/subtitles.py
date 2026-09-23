"""Geração de legendas SRT e WebVTT.

O agrupamento em legendas do tamanho pedido fica em `cues.py`; aqui só se
formata o que ele decidiu.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from .cues import MAX_LINES, Cue, build_cues, resolve_density
from .types import SegmentInfo
from .utils import format_srt_time, format_timestamp

#: Convenção de legendagem: até 2 linhas de ~42 caracteres.
_MAX_LINE = 42
_MAX_LINES = 2


def _cue_text(cue: Cue, *, with_speaker: bool, max_lines: int = _MAX_LINES) -> str:
    text = cue.text.strip()
    if with_speaker and cue.speaker:
        text = f"[{cue.speaker}] {text}"
    lines = textwrap.wrap(text, width=_MAX_LINE, break_long_words=False) or [text]
    if len(lines) > max_lines:
        # Junta o excedente na última linha em vez de descartar texto.
        lines = [*lines[: max_lines - 1], " ".join(lines[max_lines - 1 :])]
    return "\n".join(lines)


def render_srt(
    segments: list[SegmentInfo], *, with_speaker: bool = True, density: str | None = None
) -> str:
    linhas = MAX_LINES[resolve_density(density)]
    blocks: list[str] = []
    for number, cue in enumerate(build_cues(segments, density), start=1):
        blocks.append(
            f"{number}\n"
            f"{format_srt_time(cue.start)} --> {format_srt_time(cue.end)}\n"
            f"{_cue_text(cue, with_speaker=with_speaker, max_lines=linhas)}\n"
        )
    return "\n".join(blocks)


def render_vtt(
    segments: list[SegmentInfo], *, with_speaker: bool = True, density: str | None = None
) -> str:
    linhas = MAX_LINES[resolve_density(density)]
    blocks: list[str] = ["WEBVTT\n"]
    for number, cue in enumerate(build_cues(segments, density), start=1):
        blocks.append(
            f"{number}\n"
            f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n"
            f"{_cue_text(cue, with_speaker=with_speaker, max_lines=linhas)}\n"
        )
    return "\n".join(blocks)


def write_srt(
    path: Path, segments: list[SegmentInfo], *, with_speaker: bool = True,
    density: str | None = None,
) -> Path:
    path.write_text(
        render_srt(segments, with_speaker=with_speaker, density=density), encoding="utf-8"
    )
    return path


def write_vtt(
    path: Path, segments: list[SegmentInfo], *, with_speaker: bool = True,
    density: str | None = None,
) -> Path:
    path.write_text(
        render_vtt(segments, with_speaker=with_speaker, density=density), encoding="utf-8"
    )
    return path
