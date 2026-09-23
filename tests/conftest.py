"""Fixtures dos testes. As mídias são geradas na hora com o ffmpeg."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lauda.ffmpeg_tools import resolve_tools

MEDIA_DIR = Path(__file__).parent / "_media"


def _ffmpeg_binary() -> str | None:
    """Usa a mesma descoberta do app (PATH + diretórios comuns do Windows)."""
    try:
        return resolve_tools().ffmpeg
    except Exception:
        return None


ffmpeg_required = pytest.mark.skipif(
    _ffmpeg_binary() is None, reason="ffmpeg/ffprobe não encontrados"
)


def _ffmpeg(args: list[str]) -> None:
    binary = _ffmpeg_binary()
    assert binary, "ffmpeg ausente"
    subprocess.run(
        [binary, "-y", "-hide_banner", "-v", "error", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def media_dir() -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


@pytest.fixture(scope="session")
def tone_wav(media_dir: Path) -> Path:
    """Áudio sintético curto: tom, silêncio, tom. Não contém fala."""
    path = media_dir / "tone.wav"
    if not path.exists():
        _ffmpeg([
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1",
            "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
            "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map", "[out]", "-ar", "44100", "-ac", "1", str(path),
        ])
    return path


@pytest.fixture(scope="session")
def silent_video(media_dir: Path) -> Path:
    """Vídeo de 3 s sem trilha de áudio."""
    path = media_dir / "silent_video.mp4"
    if not path.exists():
        _ffmpeg([
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=3",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(path),
        ])
    return path


@pytest.fixture(scope="session")
def invalid_file(media_dir: Path) -> Path:
    """Bytes aleatórios com extensão de vídeo."""
    path = media_dir / "invalid.mp4"
    if not path.exists():
        path.write_bytes(os.urandom(4096))
    return path


@pytest.fixture(scope="session")
def dialogo_wav(media_dir: Path) -> Path:
    """Diálogo de dois locutores. Gerado por scripts/make_test_media.py."""
    path = media_dir / "dialogo.wav"
    if not path.exists():
        pytest.skip(
            "tests/_media/dialogo.wav não existe; rode: python scripts/make_test_media.py"
        )
    return path


@pytest.fixture(autouse=True)
def _isola_perfil_do_usuario(tmp_path_factory, monkeypatch):
    """Nenhum teste pode escrever no perfil real (~/.lauda).

    Vale para a preferência de tema/limites e para os pontos de retomada.
    """
    from lauda import checkpoint, history, profile, theme

    base = tmp_path_factory.mktemp("perfil")
    monkeypatch.setattr(profile, "DATA_DIR", base)
    monkeypatch.setattr(profile, "LEGACY_DIRS", ())
    monkeypatch.setattr(theme, "PREFS_PATH", base / "ui.json")
    monkeypatch.setattr(checkpoint, "CHECKPOINT_ROOT", base / "checkpoints")
    monkeypatch.setattr(history, "HISTORY_PATH", base / "history.json")
