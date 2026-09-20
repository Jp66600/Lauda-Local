"""Localização e execução dos binários ffmpeg/ffprobe.

O app nunca "executa" o arquivo de mídia: ele só é passado como argumento de
leitura para o ffmpeg, sempre via lista de argumentos (sem shell), o que elimina
injeção de comando por nome de arquivo malicioso.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import FFmpegNotFoundError

log = logging.getLogger("vellum.ffmpeg")

_INSTALL_HINT = (
    "Instale o ffmpeg e garanta que ffmpeg e ffprobe estejam no PATH.\n"
    "  Windows : winget install --id Gyan.FFmpeg -e\n"
    "  macOS   : brew install ffmpeg\n"
    "  Linux   : sudo apt install ffmpeg\n"
    "Ou aponte os caminhos em .env (VELLUM_FFMPEG / VELLUM_FFPROBE)."
)

# Locais comuns quando o usuário instalou sem colocar no PATH.
_WINDOWS_CANDIDATES = (
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"C:\ProgramData\chocolatey\bin",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
    os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
)
_POSIX_CANDIDATES = ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/snap/bin")

#: O winget instala o Gyan.FFmpeg aqui e só adiciona ao PATH no próximo shell.
#: Sem este glob, o app "não acha" o ffmpeg logo depois da instalação.
_WINDOWS_GLOBS = (
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\*\bin",
    r"%USERPROFILE%\scoop\apps\ffmpeg\current\bin",
)


@dataclass(frozen=True)
class FFmpegTools:
    ffmpeg: str
    ffprobe: str
    version: str | None = None


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def _bundled_dirs() -> list[Path]:
    """Pastas do aplicativo empacotado, onde o ffmpeg viaja junto.

    Só existem quando o programa roda congelado (PyInstaller). Rodando a partir
    do código, a lista é vazia e nada muda.
    """
    if not getattr(sys, "frozen", False):
        return []
    pastas = []
    interno = getattr(sys, "_MEIPASS", None)
    if interno:
        pastas.append(Path(interno))
    pastas.append(Path(sys.executable).parent)
    return pastas


def _locate(name: str, env_var: str) -> str | None:
    override = os.environ.get(env_var)
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return str(candidate)
        log.warning("%s aponta para um caminho inexistente: %s", env_var, override)

    # O binário que veio junto vem antes do que estiver instalado na máquina:
    # é a versão com que o aplicativo foi testado, e evita surpresa de versão.
    for pasta in _bundled_dirs():
        candidate = pasta / _exe(name)
        if candidate.is_file():
            return str(candidate)

    found = shutil.which(name)
    if found:
        return found

    candidates = _WINDOWS_CANDIDATES if sys.platform == "win32" else _POSIX_CANDIDATES
    for directory in candidates:
        if not directory:
            continue
        candidate = Path(directory) / _exe(name)
        if candidate.is_file():
            return str(candidate)

    if sys.platform == "win32":
        import glob

        for pattern in _WINDOWS_GLOBS:
            expanded = os.path.expandvars(pattern)
            for directory in sorted(glob.glob(expanded), reverse=True):  # versão mais nova
                candidate = Path(directory) / _exe(name)
                if candidate.is_file():
                    return str(candidate)
    return None


@lru_cache(maxsize=1)
def resolve_tools() -> FFmpegTools:
    """Encontra ffmpeg e ffprobe ou levanta FFmpegNotFoundError com instruções."""
    ffmpeg = _locate("ffmpeg", "VELLUM_FFMPEG")
    ffprobe = _locate("ffprobe", "VELLUM_FFPROBE")

    if ffmpeg and not ffprobe:
        # Alguns pacotes instalam os dois lado a lado; tenta o irmão do ffmpeg.
        sibling = Path(ffmpeg).with_name(_exe("ffprobe"))
        if sibling.is_file():
            ffprobe = str(sibling)

    missing = [n for n, p in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not p]
    if missing:
        raise FFmpegNotFoundError(
            f"Não encontrei {' e '.join(missing)} no sistema.",
            hint=_INSTALL_HINT,
        )

    if not ffmpeg or not ffprobe:  # pragma: no cover - `missing` ja cobriu
        raise FFmpegNotFoundError("Não encontrei o ffmpeg.", hint=_INSTALL_HINT)
    return FFmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe, version=_read_version(ffmpeg))


def _read_version(ffmpeg: str) -> str | None:
    try:
        proc = run([ffmpeg, "-hide_banner", "-version"], timeout=20)
    except Exception:  # pragma: no cover - ambiente quebrado
        return None
    match = re.search(r"ffmpeg version (\S+)", proc.stdout or "")
    return match.group(1) if match else None


def hidden_console() -> tuple[Any, int]:
    """(startupinfo, creationflags) que evitam piscar console no Windows.

    Devolvemos uma tupla, e não um `**kwargs`: um `dict[str, object]` destrói a
    resolução de sobrecarga do `subprocess` e obrigaria a silenciar o checador
    de tipos justo na função que executa processos.
    """
    if sys.platform != "win32":
        return None, 0
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo, subprocess.CREATE_NO_WINDOW


def run(
    args: list[str],
    *,
    timeout: float | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Executa um binário (sem shell) e devolve stdout/stderr como texto UTF-8."""
    log.debug("exec: %s", " ".join(args))
    startupinfo, creationflags = hidden_console()
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    if check and proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise RuntimeError(
            f"Comando falhou ({proc.returncode}): {Path(args[0]).name}\n" + "\n".join(tail)
        )
    return proc
