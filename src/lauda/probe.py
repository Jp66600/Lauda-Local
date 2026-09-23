"""Leitura de metadados técnicos via ffprobe (JSON -> ProbeResult)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .errors import ProbeError
from .ffmpeg_tools import resolve_tools, run
from .types import (
    AudioStreamInfo,
    ChapterInfo,
    ProbeResult,
    SubtitleStreamInfo,
    VideoStreamInfo,
)

log = logging.getLogger("lauda.probe")

_HDR_TRANSFERS = {"smpte2084", "arib-std-b67", "smpte428", "bt2020-10", "bt2020-12"}


def _to_int(value: Any) -> int | None:
    try:
        if value in (None, "", "N/A"):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "N/A"):
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result  # descarta NaN


def _parse_rate(value: Any) -> float | None:
    """Converte '30000/1001' ou '25/1' em float. Devolve None para '0/0'."""
    if not value or not isinstance(value, str) or "/" not in value:
        return _to_float(value)
    num, _, den = value.partition("/")
    numerator, denominator = _to_float(num), _to_float(den)
    if not numerator or not denominator:
        return None
    return round(numerator / denominator, 6)


def _rotation(stream: dict[str, Any]) -> int | None:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = _to_int(side["rotation"])
            if rotation is not None:
                return int(rotation) % 360
    tag = (stream.get("tags") or {}).get("rotate")
    rotation = _to_int(tag)
    return int(rotation) % 360 if rotation is not None else None


def _is_cover_art(stream: dict[str, Any]) -> bool:
    disposition = stream.get("disposition") or {}
    return bool(disposition.get("attached_pic"))


def _video_stream(stream: dict[str, Any]) -> VideoStreamInfo:
    tags = stream.get("tags") or {}
    transfer = (stream.get("color_transfer") or "").lower()
    return VideoStreamInfo(
        index=_to_int(stream.get("index")) or 0,
        codec=stream.get("codec_name"),
        codec_long=stream.get("codec_long_name"),
        profile=stream.get("profile"),
        width=_to_int(stream.get("width")),
        height=_to_int(stream.get("height")),
        coded_width=_to_int(stream.get("coded_width")),
        coded_height=_to_int(stream.get("coded_height")),
        sample_aspect_ratio=stream.get("sample_aspect_ratio"),
        display_aspect_ratio=stream.get("display_aspect_ratio"),
        fps=_parse_rate(stream.get("r_frame_rate")),
        avg_fps=_parse_rate(stream.get("avg_frame_rate")),
        bit_rate=_to_int(stream.get("bit_rate")),
        pix_fmt=stream.get("pix_fmt"),
        color_space=stream.get("color_space"),
        color_primaries=stream.get("color_primaries"),
        color_transfer=stream.get("color_transfer"),
        is_hdr=transfer in _HDR_TRANSFERS,
        rotation=_rotation(stream),
        nb_frames=_to_int(stream.get("nb_frames")) or (1 if _is_cover_art(stream) else None),
        duration=_to_float(stream.get("duration")),
        language=tags.get("language"),
    )


def _audio_stream(stream: dict[str, Any]) -> AudioStreamInfo:
    tags = stream.get("tags") or {}
    bits = _to_int(stream.get("bits_per_raw_sample")) or _to_int(stream.get("bits_per_sample"))
    return AudioStreamInfo(
        index=_to_int(stream.get("index")) or 0,
        codec=stream.get("codec_name"),
        codec_long=stream.get("codec_long_name"),
        profile=stream.get("profile"),
        sample_rate=_to_int(stream.get("sample_rate")),
        channels=_to_int(stream.get("channels")),
        channel_layout=stream.get("channel_layout"),
        bit_rate=_to_int(stream.get("bit_rate")),
        bits_per_sample=bits or None,
        duration=_to_float(stream.get("duration")),
        language=tags.get("language"),
        title=tags.get("title"),
    )


def probe_media(path: Path) -> ProbeResult:
    """Roda ffprobe e devolve a estrutura já normalizada.

    Levanta ProbeError se o arquivo não existir, estiver vazio ou não for
    reconhecido pelo ffmpeg.
    """
    path = Path(path)
    if not path.exists():
        raise ProbeError(f"Arquivo não encontrado: {path}")
    if not path.is_file():
        raise ProbeError(f"O caminho não é um arquivo: {path}")
    if path.stat().st_size == 0:
        raise ProbeError(f"Arquivo vazio (0 bytes): {path.name}")

    tools = resolve_tools()
    args = [
        tools.ffprobe,
        "-v", "error",
        "-hide_banner",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        str(path),
    ]
    proc = run(args, timeout=180)
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        detail = (proc.stderr or "").strip().splitlines()
        raise ProbeError(
            f"O ffprobe não conseguiu ler o arquivo: {path.name}",
            hint="\n".join(detail[-4:]) or "Arquivo possivelmente corrompido ou não suportado.",
        )

    try:
        raw: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - saída inesperada do ffprobe
        raise ProbeError(f"Saída do ffprobe ilegível para {path.name}: {exc}") from exc

    fmt = raw.get("format") or {}
    result = ProbeResult(
        format_name=fmt.get("format_name"),
        format_long_name=fmt.get("format_long_name"),
        duration=_to_float(fmt.get("duration")),
        bit_rate=_to_int(fmt.get("bit_rate")),
        nb_streams=_to_int(fmt.get("nb_streams")) or 0,
        tags={str(k): str(v) for k, v in (fmt.get("tags") or {}).items()},
        raw=raw,
    )

    for stream in raw.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video":
            result.video.append(_video_stream(stream))
        elif kind == "audio":
            result.audio.append(_audio_stream(stream))
        elif kind == "subtitle":
            tags = stream.get("tags") or {}
            result.subtitles.append(
                SubtitleStreamInfo(
                    index=_to_int(stream.get("index")) or 0,
                    codec=stream.get("codec_name"),
                    language=tags.get("language"),
                    title=tags.get("title"),
                )
            )

    for position, chapter in enumerate(raw.get("chapters") or []):
        # Capítulo sem id (ou com id ilegível) recebe a posição na lista: o
        # campo é obrigatório e um None aqui quebraria a serialização.
        chapter_id = _to_int(chapter.get("id"))
        result.chapters.append(
            ChapterInfo(
                index=position if chapter_id is None else chapter_id,
                start=_to_float(chapter.get("start_time")) or 0.0,
                end=_to_float(chapter.get("end_time")) or 0.0,
                title=(chapter.get("tags") or {}).get("title"),
            )
        )

    if result.duration is None:
        # Alguns containers (MPEG-TS, WebM em stream) não trazem duração no format.
        streams: list[VideoStreamInfo | AudioStreamInfo] = [*result.video, *result.audio]
        durations = [s.duration for s in streams if s.duration]
        result.duration = max(durations) if durations else None

    log.debug(
        "probe ok: %s | %s | %.2fs | v=%d a=%d",
        path.name,
        result.format_name,
        result.duration or 0.0,
        len(result.video),
        len(result.audio),
    )
    return result
