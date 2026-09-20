"""Hierarquia de erros do Vellum.

Toda falha previsivel vira uma destas excecoes com mensagem em PT-BR pronta para
o usuario final. Falhas de etapas opcionais NAO devem subir: viram avisos no
relatorio (ver `PartialFailure`).
"""

from __future__ import annotations

from dataclasses import dataclass


class VellumError(Exception):
    """Erro base. A mensagem ja e voltada ao usuario final."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message if not self.hint else f"{self.message}\nDica: {self.hint}"


class FFmpegNotFoundError(VellumError):
    """ffmpeg/ffprobe ausentes no PATH e nas variaveis de ambiente."""


class ProbeError(VellumError):
    """ffprobe nao conseguiu ler o arquivo (corrompido ou formato desconhecido)."""


class UnsupportedMediaError(VellumError):
    """Arquivo aberto pelo ffmpeg, mas sem conteudo utilizavel (ex.: sem trilha de audio)."""


class ExtractionError(VellumError):
    """Falha ao converter o audio para WAV 16 kHz mono."""


class TranscriptionError(VellumError):
    """Falha na engine de STT (modelo, device, memoria)."""


class ModelNotAvailableError(TranscriptionError):
    """Modelo nao encontrado localmente e download impossivel (offline)."""


@dataclass(frozen=True)
class PartialFailure:
    """Falha de uma etapa OPCIONAL. Nao interrompe o pipeline; vai para o relatorio."""

    stage: str
    reason: str

    def as_line(self) -> str:
        return f"[INDISPONIVEL] {self.stage}: {self.reason}"
