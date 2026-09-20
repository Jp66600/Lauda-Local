"""Contratos de dados do Vellum (dataclasses -> schema do .data.json).

Regra: todo campo que aparece no TXT existe aqui. O TXT é uma renderização
destas estruturas, nunca um dump de JSON cru.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# --------------------------------------------------------------------------- #
# 1. Identidade do arquivo
# --------------------------------------------------------------------------- #
@dataclass
class SourceInfo:
    name: str
    path: str
    size_bytes: int
    size_human: str
    sha256: str
    modified_at: str


# --------------------------------------------------------------------------- #
# 2. Metadados técnicos (ffprobe)
# --------------------------------------------------------------------------- #
@dataclass
class VideoStreamInfo:
    index: int
    codec: str | None = None
    codec_long: str | None = None
    profile: str | None = None
    width: int | None = None
    height: int | None = None
    coded_width: int | None = None
    coded_height: int | None = None
    sample_aspect_ratio: str | None = None
    display_aspect_ratio: str | None = None
    fps: float | None = None
    avg_fps: float | None = None
    bit_rate: int | None = None
    pix_fmt: str | None = None
    color_space: str | None = None
    color_primaries: str | None = None
    color_transfer: str | None = None
    is_hdr: bool = False
    rotation: int | None = None
    nb_frames: int | None = None
    duration: float | None = None
    language: str | None = None


@dataclass
class AudioStreamInfo:
    index: int
    codec: str | None = None
    codec_long: str | None = None
    profile: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    bit_rate: int | None = None
    bits_per_sample: int | None = None
    duration: float | None = None
    language: str | None = None
    title: str | None = None


@dataclass
class SubtitleStreamInfo:
    index: int
    codec: str | None = None
    language: str | None = None
    title: str | None = None


@dataclass
class ChapterInfo:
    index: int
    start: float
    end: float
    title: str | None = None


@dataclass
class ProbeResult:
    format_name: str | None = None
    format_long_name: str | None = None
    duration: float | None = None
    bit_rate: int | None = None
    nb_streams: int = 0
    tags: dict[str, str] = field(default_factory=dict)
    video: list[VideoStreamInfo] = field(default_factory=list)
    audio: list[AudioStreamInfo] = field(default_factory=list)
    subtitles: list[SubtitleStreamInfo] = field(default_factory=list)
    chapters: list[ChapterInfo] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio)

    @property
    def has_video(self) -> bool:
        # Capa embutida (mp3 com imagem) tem 1 frame e não conta como vídeo real.
        return any(v.nb_frames is None or v.nb_frames > 1 for v in self.video)


# --------------------------------------------------------------------------- #
# 3. Qualidade e diagnóstico
# --------------------------------------------------------------------------- #
@dataclass
class CoverageInfo:
    """Quanto da linha do tempo virou texto, e o que ficou de fora.

    `gaps` só lista o que NÃO é silêncio: pausa entre frases é sucesso, não
    trecho perdido.
    """

    analyzed: bool = False
    reason: str = ""
    duration: float | None = None
    covered_seconds: float | None = None
    ratio: float | None = None
    silence_seconds: float | None = None
    gaps: list[tuple[float, float]] = field(default_factory=list)
    gap_seconds: float = 0.0


@dataclass
class AudioDiagnostics:
    analyzed: bool = False
    mean_volume_db: float | None = None
    max_volume_db: float | None = None
    clipping_samples: int | None = None
    clipping_suspected: bool = False
    silence_seconds: float = 0.0
    silence_ratio: float | None = None
    #: Intervalos (inicio, fim) de silencio, do `silencedetect`. Servem para
    #: separar buraco de verdade de pausa entre frases.
    silence_spans: list[tuple[float, float]] = field(default_factory=list)
    speech_seconds: float | None = None
    speech_ratio: float | None = None
    speech_detected: bool | None = None
    vad_segments: int | None = None
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# 4-6. Transcrição
# --------------------------------------------------------------------------- #
@dataclass
class WordInfo:
    start: float
    end: float
    word: str
    probability: float | None = None


@dataclass
class SegmentInfo:
    id: int
    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[WordInfo] = field(default_factory=list)
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    temperature: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class LanguageInfo:
    code: str | None = None
    probability: float | None = None
    source: str = "auto"  # "auto" (detectado) ou "manual" (forçado pelo usuário)


@dataclass
class SpeakerStat:
    speaker: str
    seconds: float
    ratio: float
    segments: int


# --------------------------------------------------------------------------- #
# 7. Estrutura / resumo local
# --------------------------------------------------------------------------- #
@dataclass
class TextStats:
    characters: int = 0
    characters_no_spaces: int = 0
    words: int = 0
    unique_words: int = 0
    segments: int = 0
    words_per_minute: float | None = None
    top_words: list[tuple[str, int]] = field(default_factory=list)
    stopwords_language: str | None = None


@dataclass
class SummaryInfo:
    available: bool = False
    provider: str | None = None
    model: str | None = None
    summary: str | None = None
    topics: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    reason: str | None = None


# --------------------------------------------------------------------------- #
# 8. Camada visual
# --------------------------------------------------------------------------- #
@dataclass
class VisualInfo:
    enabled: bool = False
    scene_cuts: int | None = None
    scene_threshold: float | None = None
    thumbnails: list[str] = field(default_factory=list)
    thumbnail_interval: float | None = None
    effective_resolution: str | None = None
    display_resolution: str | None = None
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Processamento
# --------------------------------------------------------------------------- #
@dataclass
class StageTiming:
    name: str
    seconds: float
    status: str = "ok"  # ok | pulado | erro


@dataclass
class ProcessingInfo:
    app_name: str = ""
    app_version: str = ""
    engine: str = ""
    engine_version: str = ""
    model: str = ""
    model_path: str | None = None
    device: str = ""
    device_name: str | None = None
    compute_type: str = ""
    beam_size: int = 5
    vad_enabled: bool = True
    word_timestamps: bool = False
    subtitle_density: str = ""
    batch_size: int = 0          # 0 = sequencial; >0 = modo rápido (lotes)
    started_at: str = ""
    finished_at: str = ""
    elapsed_seconds: float = 0.0
    realtime_factor: float | None = None
    stages: list[StageTiming] = field(default_factory=list)
    ffmpeg_version: str | None = None
    python_version: str = ""
    platform: str = ""


@dataclass
class DiarizationInfo:
    available: bool = False
    backend: str | None = None
    speakers: list[SpeakerStat] = field(default_factory=list)
    speaker_count: int | None = None
    reason: str | None = None


@dataclass
class JobResult:
    """Resultado completo de um processamento (raiz do .data.json)."""

    source: SourceInfo
    probe: ProbeResult
    processing: ProcessingInfo
    language: LanguageInfo
    diagnostics: AudioDiagnostics
    text: str = ""
    segments: list[SegmentInfo] = field(default_factory=list)
    diarization: DiarizationInfo = field(default_factory=DiarizationInfo)
    stats: TextStats = field(default_factory=TextStats)
    summary: SummaryInfo = field(default_factory=SummaryInfo)
    visual: VisualInfo = field(default_factory=VisualInfo)
    coverage: CoverageInfo = field(default_factory=CoverageInfo)
    partial_failures: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
