"""Diagnóstico barato do áudio usando filtros do próprio ffmpeg.

Nada de numpy/librosa: `volumedetect` e `silencedetect` rodam em streaming e
custam poucos segundos mesmo em arquivos longos.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .ffmpeg_tools import resolve_tools, run
from .types import AudioDiagnostics, ProbeResult, SegmentInfo

log = logging.getLogger("lauda.audio_stats")

_MEAN_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB")
_MAX_RE = re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?) dB")
_HIST0_RE = re.compile(r"histogram_0db:\s*(\d+)")
_SILENCE_DUR_RE = re.compile(r"silence_duration:\s*(\d+(?:\.\d+)?)")
#: O mesmo `silencedetect` tambem diz ONDE o silencio esta. Sem estes dois,
#: so sabemos quanto silencio existe — nao daria para separar um buraco de
#: verdade de uma pausa entre frases.
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")

#: Abaixo disso o Whisper começa a inventar texto; vale avisar o usuário.
_LOW_VOLUME_DB = -38.0
#: Sample rates que não causam estranheza em pipelines de fala.
_COMMON_RATES = {8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000}
_SILENCE_NOISE_DB = -35
_SILENCE_MIN_DUR = 0.6


def analyze_audio(
    wav_path: Path,
    *,
    duration: float | None,
    timeout: float | None = None,
) -> AudioDiagnostics:
    """Mede volume médio/máximo, clipping e tempo total de silêncio."""
    diagnostics = AudioDiagnostics()
    tools = resolve_tools()
    args = [
        tools.ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v", "info",
        "-i", str(wav_path),
        "-af", f"volumedetect,silencedetect=noise={_SILENCE_NOISE_DB}dB:d={_SILENCE_MIN_DUR}",
        "-f", "null",
        "-",
    ]
    proc = run(args, timeout=timeout)
    output = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0:
        log.warning("Diagnóstico de áudio falhou (rc=%s); seguindo sem ele.", proc.returncode)
        return diagnostics

    diagnostics.analyzed = True
    if (match := _MEAN_RE.search(output)):
        diagnostics.mean_volume_db = float(match.group(1))
    if (match := _MAX_RE.search(output)):
        diagnostics.max_volume_db = float(match.group(1))
    if (match := _HIST0_RE.search(output)):
        diagnostics.clipping_samples = int(match.group(1))

    silence_total = sum(float(value) for value in _SILENCE_DUR_RE.findall(output))
    diagnostics.silence_seconds = round(silence_total, 3)
    diagnostics.silence_spans = _silence_spans(output, duration)
    if duration and duration > 0:
        diagnostics.silence_ratio = round(min(1.0, silence_total / duration), 4)

    # Clipping: muitas amostras coladas em 0 dBFS é sinal de saturação.
    samples_at_full = diagnostics.clipping_samples or 0
    diagnostics.clipping_suspected = samples_at_full > 100 or (
        diagnostics.max_volume_db is not None and diagnostics.max_volume_db >= -0.1
        and samples_at_full > 0
    )
    return diagnostics


def _silence_spans(output: str, duration: float | None) -> list[tuple[float, float]]:
    """Pareia os `silence_start` com os `silence_end` do ffmpeg.

    O ultimo silencio pode nao ter fim: quando o arquivo termina em silencio,
    o ffmpeg fecha o intervalo sozinho e nao imprime `silence_end`. Nesse caso
    o fim e a duracao do arquivo.
    """
    inicios = [float(valor) for valor in _SILENCE_START_RE.findall(output)]
    fins = [float(valor) for valor in _SILENCE_END_RE.findall(output)]
    if len(fins) < len(inicios) and duration:
        fins.append(duration)

    intervalos = []
    for inicio, fim in zip(inicios, fins, strict=False):
        inicio = max(0.0, inicio)
        if duration:
            fim = min(fim, duration)
        if fim > inicio:
            intervalos.append((round(inicio, 3), round(fim, 3)))
    return intervalos


def apply_speech_stats(
    diagnostics: AudioDiagnostics,
    segments: list[SegmentInfo],
    duration: float | None,
) -> AudioDiagnostics:
    """Preenche tempo/proporção de fala a partir dos segmentos transcritos."""
    speech = sum(seg.duration for seg in segments)
    diagnostics.speech_seconds = round(speech, 3)
    diagnostics.vad_segments = len(segments)
    diagnostics.speech_detected = bool(segments) and speech > 0.2
    if duration and duration > 0:
        diagnostics.speech_ratio = round(min(1.0, speech / duration), 4)
    return diagnostics


def build_warnings(
    diagnostics: AudioDiagnostics,
    probe: ProbeResult,
    *,
    vad_enabled: bool,
) -> list[str]:
    """Lista determinística de avisos para a seção 3 do relatório."""
    warnings: list[str] = []

    if not probe.has_audio:
        warnings.append("O arquivo não possui trilha de áudio: nada a transcrever.")
        return warnings

    duration = probe.duration
    if duration is None:
        warnings.append("Duração não declarada no container; valores relativos podem variar.")
    elif duration <= 0.05:
        warnings.append("Duração praticamente zero: o arquivo pode estar truncado.")

    for stream in probe.audio:
        if stream.channels == 1:
            warnings.append(f"Trilha #{stream.index}: áudio mono (normal em gravações de voz).")
        elif stream.channels and stream.channels > 2:
            warnings.append(
                f"Trilha #{stream.index}: {stream.channels} canais "
                f"({stream.channel_layout or 'layout desconhecido'}); "
                "a mixagem para mono pode reduzir a inteligibilidade."
            )
        if stream.sample_rate and stream.sample_rate not in _COMMON_RATES:
            warnings.append(
                f"Trilha #{stream.index}: sample rate incomum ({stream.sample_rate} Hz)."
            )
        if stream.sample_rate and stream.sample_rate < 16000:
            warnings.append(
                f"Trilha #{stream.index}: sample rate baixo ({stream.sample_rate} Hz); "
                "a qualidade da transcrição tende a cair."
            )

    if diagnostics.mean_volume_db is not None and diagnostics.mean_volume_db < _LOW_VOLUME_DB:
        warnings.append(
            f"Volume médio muito baixo ({diagnostics.mean_volume_db:.1f} dB): "
            "risco de trechos não reconhecidos."
        )
    if diagnostics.clipping_suspected:
        warnings.append(
            f"Possível clipping (pico {diagnostics.max_volume_db:.1f} dB, "
            f"{diagnostics.clipping_samples} amostras em 0 dBFS)."
            if diagnostics.max_volume_db is not None
            else "Possível clipping detectado no áudio."
        )
    if diagnostics.silence_ratio is not None and diagnostics.silence_ratio > 0.9:
        warnings.append(
            f"Mais de {diagnostics.silence_ratio * 100:.0f}% do áudio é silêncio."
        )
    if diagnostics.speech_detected is False:
        warnings.append("O VAD não encontrou fala: o relatório traz apenas metadados.")
    if not vad_enabled:
        warnings.append(
            "VAD desligado: em trechos de silêncio o Whisper pode alucinar texto."
        )
    if probe.has_video and not probe.has_audio:
        warnings.append("Vídeo sem áudio.")

    return warnings
