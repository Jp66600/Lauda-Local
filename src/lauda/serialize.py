"""Serialização do resultado para .data.json (machine-readable)."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .types import (
    AudioDiagnostics,
    AudioStreamInfo,
    ChapterInfo,
    DiarizationInfo,
    JobResult,
    LanguageInfo,
    ProbeResult,
    ProcessingInfo,
    SegmentInfo,
    SourceInfo,
    SpeakerStat,
    StageTiming,
    SubtitleStreamInfo,
    SummaryInfo,
    TextStats,
    VideoStreamInfo,
    VisualInfo,
    WordInfo,
)

#: Versão do schema. Suba quando remover/renomear campos.
SCHEMA_VERSION = 1


def to_json_dict(result: JobResult) -> dict[str, Any]:
    """Estrutura estável do JSON (ordem das chaves fixa)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "source": asdict(result.source),
        "probe": asdict(result.probe),
        "processing": asdict(result.processing),
        "language": asdict(result.language),
        "speakers": [asdict(speaker) for speaker in result.diarization.speakers],
        "diarization": {
            "available": result.diarization.available,
            "backend": result.diarization.backend,
            "speaker_count": result.diarization.speaker_count,
            "reason": result.diarization.reason,
        },
        "text": result.text,
        "segments": [
            {
                "id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "speaker": segment.speaker,
                "text": segment.text,
                "words": [asdict(word) for word in segment.words],
                "avg_logprob": segment.avg_logprob,
                "no_speech_prob": segment.no_speech_prob,
                "compression_ratio": segment.compression_ratio,
            }
            for segment in result.segments
        ],
        "stats": asdict(result.stats),
        "coverage": asdict(result.coverage),
        "summary": asdict(result.summary),
        "visual": asdict(result.visual),
        "diagnostics": asdict(result.diagnostics),
        "partial_failures": list(result.partial_failures),
        "outputs": dict(result.outputs),
    }


def write_json(path: Path, result: JobResult) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_json_dict(result)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


# --------------------------------------------------------------------------- #
# Leitura de volta (usada pelos pontos de retomada e pelo processo filho)
# --------------------------------------------------------------------------- #
def _build(cls, data: Any):
    """Reconstrói uma dataclass a partir do dicionário, ignorando campos extras."""
    if data is None:
        return None
    fields = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in fields})


def from_json_dict(payload: dict[str, Any]) -> JobResult:
    """Refaz o JobResult a partir do dicionário gerado por `to_json_dict`.

    A ida e volta precisa ser fiel: é ela que permite retomar um trabalho
    interrompido sem refazer a transcrição.
    """
    probe_data = dict(payload.get("probe") or {})
    probe = ProbeResult(
        format_name=probe_data.get("format_name"),
        format_long_name=probe_data.get("format_long_name"),
        duration=probe_data.get("duration"),
        bit_rate=probe_data.get("bit_rate"),
        nb_streams=probe_data.get("nb_streams", 0),
        tags=probe_data.get("tags") or {},
        video=[_build(VideoStreamInfo, item) for item in probe_data.get("video") or []],
        audio=[_build(AudioStreamInfo, item) for item in probe_data.get("audio") or []],
        subtitles=[_build(SubtitleStreamInfo, item) for item in probe_data.get("subtitles") or []],
        chapters=[_build(ChapterInfo, item) for item in probe_data.get("chapters") or []],
        raw=probe_data.get("raw") or {},
    )

    segments: list[SegmentInfo] = []
    for item in payload.get("segments") or []:
        segment = _build(SegmentInfo, item)
        segment.words = [_build(WordInfo, word) for word in item.get("words") or []]
        segments.append(segment)

    diarization_data = dict(payload.get("diarization") or {})
    diarization = DiarizationInfo(
        available=bool(diarization_data.get("available")),
        backend=diarization_data.get("backend"),
        speakers=[_build(SpeakerStat, item) for item in payload.get("speakers") or []],
        speaker_count=diarization_data.get("speaker_count"),
        reason=diarization_data.get("reason"),
    )

    stats = _build(TextStats, payload.get("stats") or {})
    stats.top_words = [tuple(item) for item in stats.top_words]

    processing = _build(ProcessingInfo, payload.get("processing") or {})
    processing.stages = [_build(StageTiming, item) for item in (processing.stages or [])]

    return JobResult(
        source=_build(SourceInfo, payload.get("source") or {}),
        probe=probe,
        processing=processing,
        language=_build(LanguageInfo, payload.get("language") or {}),
        diagnostics=_build(AudioDiagnostics, payload.get("diagnostics") or {}),
        text=payload.get("text", ""),
        segments=segments,
        diarization=diarization,
        stats=stats,
        summary=_build(SummaryInfo, payload.get("summary") or {}),
        visual=_build(VisualInfo, payload.get("visual") or {}),
        partial_failures=list(payload.get("partial_failures") or []),
        outputs=dict(payload.get("outputs") or {}),
    )


def read_json(path: Path) -> JobResult:
    """Lê um .data.json (ou um ponto de retomada) de volta para JobResult."""
    return from_json_dict(json.loads(Path(path).read_text(encoding="utf-8")))
