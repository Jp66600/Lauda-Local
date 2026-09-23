"""Configuração de um job: o que entra, o que sai, quais etapas rodam."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .cues import DEFAULT_DENSITY
from .limits import ResourceLimits

MODEL_CHOICES: tuple[str, ...] = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3",
    "large-v3-turbo",
    "distil-large-v3",
)

DEVICE_CHOICES: tuple[str, ...] = ("auto", "cpu", "cuda")

DIARIZE_BACKEND_CHOICES: tuple[str, ...] = ("auto", "pyannote", "ecapa")

COMPUTE_TYPE_CHOICES: tuple[str, ...] = (
    "auto",
    "int8",
    "int8_float16",
    "int8_float32",
    "float16",
    "float32",
)

#: Idiomas com lista de stopwords embarcada (para o bloco de palavras frequentes).
SUPPORTED_STOPWORD_LANGS: tuple[str, ...] = ("pt", "en", "es")

#: Extensões conhecidas. Não é uma lista branca rígida: qualquer coisa que o
#: ffmpeg abrir é aceita; isto serve apenas para avisos e para a UI.
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".ts"}

#: Áudio normalizado para STT (Whisper trabalha nativamente neste formato).
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

ENV_PREFIX = "LAUDA_"

#: Prefixos dos nomes anteriores (Vellum e MediaIntel Local), do mais recente
#: para o mais antigo. Continuam sendo lidos para não invalidar o `.env` de
#: quem já tinha um.
LEGACY_ENV_PREFIXES = ("VELLUM_", "MEDIAINTEL_")


def _env(name: str, default: str) -> str:
    for prefixo in (ENV_PREFIX, *LEGACY_ENV_PREFIXES):
        valor = os.environ.get(prefixo + name)
        if valor is not None:
            return valor
    return default


@dataclass
class JobOptions:
    """Tudo que a CLI/UI pode controlar em um processamento."""

    input_path: Path
    output_dir: Path

    # STT
    model: str = "small"
    language: str = "auto"           # "auto" ou código ISO (pt, en, es, ...)
    device: str = "auto"             # auto | cpu | cuda
    compute_type: str = "auto"
    beam_size: int = 5
    temperature: float = 0.0
    initial_prompt: str | None = None
    cpu_threads: int = 0             # 0 = derivado de `limits`
    batch_size: int = 0              # 0 = sequencial; >0 liga a inferência em lote
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    condition_on_previous_text: bool = False  # False reduz alucinação em cadeia

    # Etapas opcionais
    vad: bool = True
    word_timestamps: bool = False
    diarize: bool = False
    visual: bool = False
    summarize: bool = False

    # Diarização
    diarize_backend: str = "auto"     # auto | pyannote | ecapa
    num_speakers: int | None = None   # quando você sabe quantos são
    min_speakers: int | None = None
    max_speakers: int | None = None
    speaker_threshold: float = 0.30   # distância de cosseno (backend ecapa)

    # Saídas
    write_txt: bool = True
    write_transcript: bool = True
    write_json: bool = True
    write_srt: bool = False
    write_vtt: bool = False
    #: Tamanho das legendas: "curta", "equilibrada" ou "longa" (ver cues.py).
    subtitle_density: str = DEFAULT_DENSITY

    # Diversos
    top_words: int = 25
    keep_temp: bool = False
    models_dir: Path = field(default_factory=lambda: Path(_env("MODELS_DIR", "./models")))
    hf_token: str | None = None
    thumbnail_interval: float = 30.0
    scene_threshold: float = 0.35
    ollama_host: str = field(default_factory=lambda: os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", "qwen3:14b"))
    #: Usado quando o modelo pedido nao esta baixado. O 8B cabe em placas de
    #: 8 GB e resume bem; o 14B e melhor, mas sao ~9 GB de download.
    ollama_fallback_model: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_FALLBACK_MODEL", "qwen3:8b")
    )

    def __post_init__(self) -> None:
        self.input_path = Path(self.input_path).expanduser().resolve()
        self.output_dir = Path(self.output_dir).expanduser().resolve()
        self.models_dir = Path(self.models_dir).expanduser().resolve()
        # Aceita caminho local para um modelo CTranslate2 já convertido.
        if self.model not in MODEL_CHOICES and not Path(self.model).exists():
            raise ValueError(
                    f"Modelo desconhecido: {self.model!r}. "
                    f"Use um de {', '.join(MODEL_CHOICES)} ou um caminho local."
                )
        if self.device not in DEVICE_CHOICES:
            raise ValueError(f"Device inválido: {self.device!r}. Use: {', '.join(DEVICE_CHOICES)}")
        if self.compute_type not in COMPUTE_TYPE_CHOICES:
            raise ValueError(
                f"compute_type inválido: {self.compute_type!r}. "
                f"Use: {', '.join(COMPUTE_TYPE_CHOICES)}"
            )
        if self.diarize_backend not in DIARIZE_BACKEND_CHOICES:
            raise ValueError(
                f"Backend de diarização inválido: {self.diarize_backend!r}. "
                f"Use: {', '.join(DIARIZE_BACKEND_CHOICES)}"
            )
        if self.num_speakers is not None and self.num_speakers < 1:
            raise ValueError("--num-speakers precisa ser 1 ou mais.")
        if not 0 <= self.batch_size <= 32:
            raise ValueError("--batch-size precisa estar entre 0 (desligado) e 32.")

    # ------------------------------------------------------------ serialização --
    def to_dict(self) -> dict:
        """Forma serializável, para atravessar até o processo filho.

        O `hf_token` é removido de propósito: este dicionário vira um arquivo
        temporário em disco, e segredo não se escreve em disco. O processo
        filho herda o token pelo ambiente, que não deixa rastro.
        """
        from dataclasses import asdict

        data = asdict(self)
        data["input_path"] = str(self.input_path)
        data["output_dir"] = str(self.output_dir)
        data["models_dir"] = str(self.models_dir)
        data.pop("hf_token", None)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> JobOptions:
        """Reconstrói a partir de `to_dict`, ignorando campos desconhecidos."""
        from dataclasses import fields

        from .limits import from_dict as limits_from_dict

        known = {f.name for f in fields(cls)}
        payload = {k: v for k, v in data.items() if k in known}
        payload["limits"] = limits_from_dict(payload.get("limits"))
        # O token vem do ambiente, nunca do arquivo (ver `to_dict`).
        payload.setdefault("hf_token", os.environ.get("HF_TOKEN") or None)
        return cls(**payload)

    @property
    def effective_cpu_threads(self) -> int:
        """Threads para o motor: o valor explícito vence o limite percentual."""
        return self.cpu_threads or self.limits.cpu_threads()

    @property
    def effective_device(self) -> str:
        """GPU em 0% significa CPU, mesmo que o device peça cuda."""
        return "cpu" if not self.limits.use_gpu else self.device

    @property
    def is_probably_video(self) -> bool:
        return self.input_path.suffix.lower() in VIDEO_EXTENSIONS

    @property
    def language_code(self) -> str | None:
        """None quando o idioma deve ser detectado automaticamente."""
        return None if self.language in ("auto", "", None) else self.language


@dataclass(frozen=True)
class OutputPaths:
    """Caminhos derivados do arquivo de entrada, dentro da pasta de saída."""

    base_dir: Path
    stem: str

    @property
    def report_txt(self) -> Path:
        return self.base_dir / f"{self.stem}.report.txt"

    @property
    def transcript_txt(self) -> Path:
        return self.base_dir / f"{self.stem}.transcript.txt"

    @property
    def data_json(self) -> Path:
        return self.base_dir / f"{self.stem}.data.json"

    @property
    def srt(self) -> Path:
        return self.base_dir / f"{self.stem}.srt"

    @property
    def vtt(self) -> Path:
        return self.base_dir / f"{self.stem}.vtt"

    @property
    def sidecar_dir(self) -> Path:
        """Pasta para artefatos auxiliares (thumbnails da camada visual)."""
        return self.base_dir / f"{self.stem}.assets"


def defaults_from_env() -> dict[str, str]:
    """Defaults vindos do .env (a CLI/UI sempre tem prioridade sobre eles)."""
    return {
        "model": _env("MODEL", "small"),
        "device": _env("DEVICE", "auto"),
        "language": _env("LANGUAGE", "auto"),
    }
