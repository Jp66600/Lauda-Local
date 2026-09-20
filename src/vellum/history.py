"""Histórico dos trabalhos já processados (a página "Arquivos").

Antes disto a página mostrava só o trabalho recém-terminado e esquecia tudo ao
fechar a janela. Quem processa dez arquivos precisa comparar: qual saiu com
cobertura baixa, qual ficou lento, qual caiu na CPU quando devia ter usado a
GPU. Sem isso, "o programa está mais lento hoje" é impossível de verificar.

Fica em `~/.vellum/history.json`, ao lado das preferências. Nada de banco de
dados: são dezenas de linhas, e um arquivo de texto o usuário consegue abrir,
inspecionar e apagar sozinho.

Trabalho que falhou também entra. O histórico serve para ver o que aconteceu,
e um erro é exatamente o que se quer rever depois.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import JobResult, SegmentInfo

log = logging.getLogger("vellum.history")

#: Onde o histórico mora. Os testes trocam este valor (fixture do conftest).
HISTORY_PATH = Path.home() / ".vellum" / "history.json"

#: Quantos trabalhos ficam guardados. Passou disso, o mais antigo sai.
MAX_ENTRIES = 60

#: Acima deste `avg_logprob` médio a transcrição é considerada confiável.
CONFIDENCE_HIGH = -0.35
CONFIDENCE_LOW = -0.60


@dataclass
class HistoryEntry:
    """Uma linha do histórico. Tudo opcional: entrada velha não quebra a tela."""

    finished_at: str = ""
    file_name: str = ""
    input_path: str = ""
    output_dir: str = ""
    report_path: str = ""
    status: str = "ok"            # ok | erro
    detail: str = ""              # motivo, quando status == "erro"
    duration: float | None = None
    model: str = ""
    device: str = ""
    realtime_factor: float | None = None
    coverage: float | None = None
    gaps: int = 0
    gap_seconds: float = 0.0
    failures: int = 0
    summarized: bool = False
    confidence: float | None = None   # média de avg_logprob; None = desconhecida

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HistoryEntry:
        """Aceita o que reconhece e ignora o resto.

        O formato pode ganhar campos com o tempo; um histórico gravado por uma
        versão mais nova não pode derrubar a janela de uma versão mais velha.
        """
        conhecidos = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in raw.items() if k in conhecidos})


def mean_confidence(segments: list[SegmentInfo]) -> float | None:
    """Média do `avg_logprob` dos trechos. `None` se o motor não informou."""
    valores = [s.avg_logprob for s in segments if s.avg_logprob is not None]
    if not valores:
        return None
    return sum(valores) / len(valores)


def confidence_label(value: float | None) -> str:
    """Traduz o `avg_logprob` para uma palavra.

    O número sozinho não diz nada a quem não conhece o Whisper: -0.28 parece
    ruim e é ótimo. A palavra vem primeiro; o número fica para quem sabe ler.
    """
    if value is None:
        return "desconhec."
    if value >= CONFIDENCE_HIGH:
        return f"alta {value:.2f}"
    if value >= CONFIDENCE_LOW:
        return f"média {value:.2f}"
    return f"baixa {value:.2f}"


def entry_from_result(result: JobResult, output_dir: Path | str = "") -> HistoryEntry:
    """Extrai do resultado só o que a página "Arquivos" mostra."""
    return HistoryEntry(
        finished_at=datetime.now().isoformat(timespec="seconds"),
        file_name=Path(result.source.path).name if result.source.path else "",
        input_path=str(result.source.path or ""),
        output_dir=str(output_dir),
        report_path=result.outputs.get("report.txt", ""),
        status="ok",
        duration=result.probe.duration,
        model=result.processing.model,
        device=result.processing.device,
        realtime_factor=result.processing.realtime_factor,
        coverage=result.coverage.ratio if result.coverage.analyzed else None,
        gaps=len(result.coverage.gaps),
        gap_seconds=result.coverage.gap_seconds,
        failures=len(result.partial_failures),
        summarized=result.summary.available,
        confidence=mean_confidence(result.segments),
    )


def entry_from_failure(path: Path | str, detail: str) -> HistoryEntry:
    """O trabalho que não chegou ao fim também vira linha."""
    return HistoryEntry(
        finished_at=datetime.now().isoformat(timespec="seconds"),
        file_name=Path(path).name if path else "",
        input_path=str(path or ""),
        status="erro",
        detail=detail.strip().splitlines()[0] if detail.strip() else "motivo não informado",
    )


def load() -> list[HistoryEntry]:
    """Lê o histórico. Arquivo ausente, vazio ou corrompido devolve lista vazia."""
    try:
        bruto = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Histórico ilegível (%s); começando um novo.", exc)
        return []
    if not isinstance(bruto, list):
        return []
    entradas: list[HistoryEntry] = []
    for item in bruto:
        if isinstance(item, dict):
            try:
                entradas.append(HistoryEntry.from_dict(item))
            except TypeError:  # pragma: no cover - dado muito estranho
                continue
    return entradas


def save(entries: list[HistoryEntry]) -> None:
    """Grava o histórico. Falha de escrita não pode derrubar o trabalho."""
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_PATH.write_text(
            json.dumps([e.to_dict() for e in entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        log.warning("Não consegui gravar o histórico em %s: %s", HISTORY_PATH, exc)


def record(entry: HistoryEntry) -> list[HistoryEntry]:
    """Acrescenta uma linha e devolve o histórico já cortado no limite."""
    entradas = load()
    entradas.append(entry)
    if len(entradas) > MAX_ENTRIES:
        entradas = entradas[-MAX_ENTRIES:]
    save(entradas)
    return entradas


def clear() -> None:
    """Apaga o histórico inteiro (botão da página "Arquivos")."""
    try:
        HISTORY_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - arquivo travado
        log.warning("Não consegui apagar o histórico: %s", exc)


# --------------------------------------------------------------------------- #
# Apresentação
# --------------------------------------------------------------------------- #
_COLUNAS = (
    ("QUANDO", 12),
    ("ARQUIVO", 30),
    ("DURAÇÃO", 9),
    ("QUALIDADE", 16),
    ("ONDE", 6),
    ("VELOC", 7),
    ("COBERT", 7),
    ("BURACOS", 8),
    ("AVISOS", 7),
    ("RESUMO", 7),
    ("CONFIANÇA", 11),
)


def _cut(text: str, width: int) -> str:
    """Corta pelo meio, não pelo fim: o final do nome costuma distinguir."""
    if len(text) <= width:
        return text
    metade = (width - 1) // 2
    return f"{text[:metade]}…{text[-(width - metade - 1):]}"


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return "-"


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    total = round(seconds)
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segundos:02d}"
    return f"{minutos}:{segundos:02d}"


def _row(entry: HistoryEntry) -> list[str]:
    if entry.status == "erro":
        return [
            _when(entry.finished_at), _cut(entry.file_name, 30),
            "-", "-", "-", "-", "-", "-", "ERRO", "-", "-",
        ]
    return [
        _when(entry.finished_at),
        _cut(entry.file_name, 30),
        _clock(entry.duration),
        _cut(entry.model or "-", 16),
        (entry.device or "-")[:6],
        "-" if entry.realtime_factor is None else f"{entry.realtime_factor:.1f}x",
        "-" if entry.coverage is None else f"{entry.coverage * 100:.1f}%",
        "-" if entry.coverage is None
        else ("nenhum" if not entry.gaps else f"{entry.gaps} ({entry.gap_seconds:.0f}s)"),
        "-" if not entry.failures else str(entry.failures),
        "sim" if entry.summarized else "não",
        confidence_label(entry.confidence),
    ]


def _totals(entries: list[HistoryEntry]) -> str:
    concluidos = [e for e in entries if e.status == "ok"]
    erros = len(entries) - len(concluidos)
    partes = [f"{len(entries)} trabalho(s)"]
    if erros:
        partes.append(f"{erros} com erro")
    coberturas = [e.coverage for e in concluidos if e.coverage is not None]
    if coberturas:
        partes.append(f"cobertura média {sum(coberturas) / len(coberturas) * 100:.1f}%")
    velocidades = [e.realtime_factor for e in concluidos if e.realtime_factor]
    if velocidades:
        partes.append(f"velocidade média {sum(velocidades) / len(velocidades):.1f}x")
    return "  •  ".join(partes)


def format_history(entries: list[HistoryEntry]) -> str:
    """A tabela do histórico, do mais recente para o mais antigo."""
    if not entries:
        return (
            "HISTÓRICO\n\n"
            "  Nenhum trabalho ainda. Assim que o primeiro terminar, ele aparece\n"
            "  aqui — com duração, qualidade, velocidade, cobertura e confiança."
        )

    recentes = list(reversed(entries))
    linhas = ["HISTÓRICO", "", f"  {_totals(entries)}", ""]
    linhas.append(
        ("  " + "  ".join(nome.ljust(largura) for nome, largura in _COLUNAS)).rstrip()
    )
    linhas.append("  " + "  ".join("-" * largura for _nome, largura in _COLUNAS))
    for entrada in recentes:
        celulas = _row(entrada)
        linhas.append(
            "  " + "  ".join(
                valor.ljust(largura)
                for valor, (_nome, largura) in zip(celulas, _COLUNAS, strict=True)
            ).rstrip()
        )

    problemas = [e for e in recentes if e.status == "erro" or e.failures or (
        e.coverage is not None and e.coverage < 0.95
    )]
    if problemas:
        linhas += ["", "O QUE MERECE UM OLHAR", ""]
        for entrada in problemas:
            if entrada.status == "erro":
                linhas.append(f"  {entrada.file_name}: {entrada.detail}")
            elif entrada.coverage is not None and entrada.coverage < 0.95:
                linhas.append(
                    f"  {entrada.file_name}: só {entrada.coverage * 100:.1f}% do arquivo "
                    f"virou texto ({entrada.gap_seconds:.0f} s fora do silêncio)."
                )
            else:
                linhas.append(
                    f"  {entrada.file_name}: {entrada.failures} bloco(s) indisponível(is) "
                    "no laudo."
                )
    return "\n".join(linhas)
