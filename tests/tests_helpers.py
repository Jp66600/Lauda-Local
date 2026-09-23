"""Auxiliares compartilhados pelos testes e pelos processos filhos falsos.

Fica fora de `conftest.py` de propósito: os workers falsos são processos
separados e importam este módulo diretamente.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lauda.serialize import write_json
from lauda.types import (
    AudioDiagnostics,
    JobResult,
    LanguageInfo,
    ProbeResult,
    ProcessingInfo,
    SegmentInfo,
    SourceInfo,
)


def make_result(texto: str = "resultado de teste") -> JobResult:
    """Um JobResult mínimo, mas completo o bastante para ida e volta em JSON."""
    return JobResult(
        source=SourceInfo(
            name="entrada.wav",
            path="/tmp/entrada.wav",
            size_bytes=80,
            size_human="80 B",
            sha256="b" * 64,
            modified_at="2026-09-04T00:00:00-03:00",
        ),
        probe=ProbeResult(format_name="wav", duration=10.0),
        processing=ProcessingInfo(model="small", device="cpu", elapsed_seconds=1.0),
        language=LanguageInfo(code="pt", probability=0.99),
        diagnostics=AudioDiagnostics(analyzed=True),
        text=texto,
        segments=[SegmentInfo(id=0, start=0.0, end=1.0, text=texto)],
    )


def write_fake_result(path: str | Path, texto: str = "resultado de teste") -> Path:
    """Grava um resultado de mentira onde o supervisor vai procurar."""
    return write_json(Path(path), make_result(texto))
