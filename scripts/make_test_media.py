"""Gera os arquivos de mídia usados nos testes (precisa do ffmpeg).

    python scripts/make_test_media.py

Cria em tests/_media:
    tone.wav          áudio sintético curto (tom + silêncio) — sem fala
    silent_video.mp4  vídeo colorido de 3 s, sem trilha de áudio
    invalid.mp4       bytes aleatórios com extensão de vídeo (deve ser recusado)
    speech.wav        fala sintética em pt-BR, se houver TTS local
    dialogo.wav       diálogo de dois locutores, para testar diarização
    entrevista.mp4    vídeo com a trilha de speech.wav e metadados embutidos

O TTS usado é o do próprio sistema: SAPI no Windows, `say` no macOS,
`espeak-ng` no Linux. Sem TTS, os dois últimos arquivos são pulados e os
testes que dependem deles se auto-desabilitam.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vellum.ffmpeg_tools import resolve_tools

MEDIA_DIR = Path(__file__).resolve().parents[1] / "tests" / "_media"

FALAS = [
    "Boa noite, obrigada por vir ao estudio hoje. Vamos falar sobre o projeto local.",
    "Boa noite. E um prazer estar aqui para conversar sobre este projeto.",
    "Conte para nos como surgiu a ideia de processar tudo offline, sem depender da nuvem.",
    "Tudo comecou por causa da privacidade. Tudo roda na maquina local, sempre.",
]


def _run(args: list[str]) -> bool:
    proc = subprocess.run(args, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        print(f"  [ERRO] {Path(args[0]).name}\n{proc.stderr.strip()[-400:]}", file=sys.stderr)
        return False
    return True


def _tts(text: str, destination: Path) -> bool:
    """Sintetiza `text` em WAV usando o TTS do sistema operacional."""
    if sys.platform == "win32":
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture -like 'pt*' } |"
            " Select-Object -First 1;"
            "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) };"
            f"$s.SetOutputToWaveFile('{destination}');"
            f"$s.Speak('{text}');"
            "$s.Dispose()"
        )
        return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])

    if sys.platform == "darwin" and shutil.which("say"):
        aiff = destination.with_suffix(".aiff")
        ok = _run(["say", "-o", str(aiff), text])
        if ok:
            ok = _run([
                resolve_tools().ffmpeg, "-y", "-hide_banner", "-v", "error",
                "-i", str(aiff), "-ar", "16000", "-ac", "1", str(destination),
            ])
        aiff.unlink(missing_ok=True)
        return ok

    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        return _run([espeak, "-v", "pt-br", "-w", str(destination), text])

    return False


def _pitch_shift(ffmpeg: str, path: Path, factor: float = 0.78) -> bool:
    """Muda o timbre mantendo a velocidade — simula um segundo locutor."""
    shifted = path.with_name(path.stem + "_shift.wav")
    ok = _run([
        ffmpeg, "-y", "-hide_banner", "-v", "error", "-i", str(path),
        "-af", f"asetrate=16000*{factor},aresample=16000,atempo={1 / factor:.4f}",
        "-ar", "16000", "-ac", "1", str(shifted),
    ])
    if ok:
        shifted.replace(path)
    return ok


def _concat(ffmpeg: str, parts: list[Path], destination: Path) -> bool:
    listing = destination.with_suffix(".txt")
    listing.write_text(
        "\n".join(f"file '{part.name}'" for part in parts) + "\n", encoding="ascii"
    )
    ok = _run([
        ffmpeg, "-y", "-hide_banner", "-v", "error",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-ar", "16000", "-ac", "1", str(destination),
    ])
    listing.unlink(missing_ok=True)
    return ok


def main() -> int:
    try:
        ffmpeg = resolve_tools().ffmpeg
    except Exception as exc:
        print(f"ffmpeg não encontrado: {exc}")
        return 1

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Gerando mídia de teste em {MEDIA_DIR}\n")

    tone = MEDIA_DIR / "tone.wav"
    _run([
        ffmpeg, "-y", "-hide_banner", "-v", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
        "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
        "-map", "[out]", "-ar", "44100", "-ac", "1", str(tone),
    ])
    print(f"  tone.wav          {tone.stat().st_size:>9} bytes")

    silent = MEDIA_DIR / "silent_video.mp4"
    _run([
        ffmpeg, "-y", "-hide_banner", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=3",
        "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(silent),
    ])
    print(f"  silent_video.mp4  {silent.stat().st_size:>9} bytes")

    invalid = MEDIA_DIR / "invalid.mp4"
    invalid.write_bytes(os.urandom(4096))
    print(f"  invalid.mp4       {invalid.stat().st_size:>9} bytes")

    speech = MEDIA_DIR / "speech.wav"
    if not _tts(" ".join(FALAS[:2]), speech) or not speech.exists():
        print("  speech.wav        (pulado: nenhum TTS local encontrado)")
        print("  dialogo.wav       (pulado)")
        print("  entrevista.mp4    (pulado)")
        return 0
    print(f"  speech.wav        {speech.stat().st_size:>9} bytes")

    # Diálogo: locutor A nas falas ímpares, locutor B (timbre alterado) nas pares.
    parts: list[Path] = []
    for index, fala in enumerate(FALAS):
        part = MEDIA_DIR / f"_turn{index}.wav"
        if not _tts(fala, part):
            break
        if index % 2 == 1:
            _pitch_shift(ffmpeg, part)
        parts.append(part)

    dialogo = MEDIA_DIR / "dialogo.wav"
    if len(parts) == len(FALAS) and _concat(ffmpeg, parts, dialogo):
        print(f"  dialogo.wav       {dialogo.stat().st_size:>9} bytes  (2 locutores)")
    for part in parts:
        part.unlink(missing_ok=True)

    entrevista = MEDIA_DIR / "entrevista.mp4"
    _run([
        ffmpeg, "-y", "-hide_banner", "-v", "error",
        "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
        "-i", str(speech), "-shortest",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-metadata", "title=Entrevista de teste",
        "-metadata", "artist=Vellum",
        str(entrevista),
    ])
    print(f"  entrevista.mp4    {entrevista.stat().st_size:>9} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
