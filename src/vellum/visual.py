"""Camada visual leve para vídeo (Fase 5 — desligada por padrão).

Só ffmpeg: detecção de cortes de cena pelo filtro `select=gt(scene,T)` e
thumbnails a cada N segundos. Nenhum modelo de visão roda aqui.

Hook para o futuro: `describe_frames_hook` fica desligado e existe para plugar
um VLM local (LLaVA/Qwen-VL via Ollama) sem mexer no restante do pipeline.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .config import JobOptions
from .ffmpeg_tools import resolve_tools, run
from .types import ProbeResult, VisualInfo

log = logging.getLogger("vellum.visual")

_SCENE_SCORE_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def analyze_video(
    source: Path,
    probe: ProbeResult,
    options: JobOptions,
    *,
    output_dir: Path,
) -> VisualInfo:
    """Conta cortes de cena e extrai thumbnails. Nunca levanta exceção."""
    if not probe.has_video:
        return VisualInfo(enabled=False, reason="o arquivo não tem stream de vídeo real.")

    info = VisualInfo(
        enabled=True,
        scene_threshold=options.scene_threshold,
        thumbnail_interval=options.thumbnail_interval,
    )
    stream = probe.video[0]
    if stream.width and stream.height:
        info.effective_resolution = f"{stream.coded_width or stream.width}x{stream.coded_height or stream.height}"
        display_w, display_h = stream.width, stream.height
        if stream.rotation in (90, 270):
            display_w, display_h = display_h, display_w
        info.display_resolution = f"{display_w}x{display_h}"

    tools = resolve_tools()
    try:
        proc = run(
            [
                tools.ffmpeg, "-hide_banner", "-nostdin", "-v", "info",
                "-i", str(source),
                "-filter:v", f"select='gt(scene,{options.scene_threshold})',showinfo",
                "-an", "-f", "null", "-",
            ],
            timeout=None,
        )
        info.scene_cuts = len(_SCENE_SCORE_RE.findall((proc.stderr or "") + (proc.stdout or "")))
    except Exception as exc:  # pragma: no cover - vídeo exótico
        info.reason = f"detecção de cenas falhou: {exc}"

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        pattern = output_dir / "thumb_%04d.jpg"
        run(
            [
                tools.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-y",
                "-i", str(source),
                "-vf", f"fps=1/{max(1.0, options.thumbnail_interval)},scale=480:-2",
                "-qscale:v", "4",
                str(pattern),
            ],
            timeout=None,
        )
        info.thumbnails = sorted(path.name for path in output_dir.glob("thumb_*.jpg"))
    except Exception as exc:  # pragma: no cover
        info.reason = f"{info.reason + ' | ' if info.reason else ''}thumbnails falharam: {exc}"

    return info


def describe_frames_hook(thumbnails: list[Path], options: JobOptions) -> list[str]:
    """Hook desligado: descrição visual com VLM local (LLaVA/Qwen-VL via Ollama).

    Mantido vazio de propósito. Ligar isto custa GB de download e minutos por
    vídeo, então fica fora do MVP.
    """
    return []
