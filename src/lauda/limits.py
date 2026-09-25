"""Limites de uso de máquina: CPU, RAM, GPU e VRAM.

Honestidade sobre o que cada controle realmente faz — porcentagem bonita na
tela que não corresponde a nada é pior do que não ter controle:

* **CPU**  — vira número de núcleos (CTranslate2, torch e ffmpeg) e prioridade
  do processo. É um limite de verdade: em 25% o app usa 1/4 dos núcleos. A
  conta é sobre núcleos **físicos**: usar as threads lógicas também deixa a
  transcrição mais lenta, não mais rápida (ver `hardware.physical_cores`).
* **RAM**  — vira o teto de memória considerado ao escolher o modelo em CPU.
  Não é um `ulimit`: impede o app de *escolher* um modelo grande demais.
* **VRAM** — mesma ideia na GPU. O CTranslate2 não expõe um teto rígido de
  alocação, então o controle age na escolha do modelo.
* **GPU**  — em 0% a GPU é ignorada (tudo em CPU). Acima disso, controla o
  paralelismo (`num_workers`): quanto menor, menos a placa é ocupada e mais
  sobra para o resto do sistema. Não existe "usar 50% da GPU" no CUDA; este é
  o controle mais próximo que dá para oferecer sem mentir.

As escolhas ficam salvas junto com a preferência de tema.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from . import theme as _theme

log = logging.getLogger("lauda.limits")


def _prefs_path() -> Path:
    """Lido na hora, não no import: assim os testes conseguem isolar o perfil
    (e uma futura troca de local do arquivo não deixa este módulo para trás)."""
    return _theme.PREFS_PATH

#: Nunca menos que isto, senão o app fica inutilizável.
MIN_PERCENT = 10
MAX_PERCENT = 100


def _default_cores() -> int:
    """Base da conta de CPU: núcleos físicos, com as threads lógicas de reserva.

    O import fica aqui dentro de propósito: `hardware` é um módulo pesado (ele
    toca no CTranslate2 e no driver de vídeo), e `limits` é carregado cedo, até
    pelo processo filho que só quer ler um número.
    """
    from .hardware import physical_cores

    return physical_cores() or os.cpu_count() or 1


@dataclass(frozen=True)
class ResourceLimits:
    """Quanto da máquina o aplicativo pode ocupar, em porcentagem."""

    cpu_percent: int = 100
    ram_percent: int = 50
    gpu_percent: int = 100
    vram_percent: int = 100

    def __post_init__(self) -> None:
        for field, value in asdict(self).items():
            low = 0 if field == "gpu_percent" else MIN_PERCENT
            if not isinstance(value, int) or not low <= value <= MAX_PERCENT:
                raise ValueError(
                    f"{field} deve ser um inteiro entre {low} e {MAX_PERCENT} "
                    f"(recebido: {value!r})"
                )

    # ------------------------------------------------------------------ CPU --
    @property
    def use_gpu(self) -> bool:
        """0% de GPU significa "nem tente": tudo na CPU."""
        return self.gpu_percent > 0

    def cpu_threads(self, total: int | None = None) -> int:
        """Quantas threads o motor pode usar. Sempre pelo menos 1.

        A conta é sobre os **núcleos físicos**, não sobre as threads lógicas.
        Isto não é economia: medido, usar todas as threads lógicas deixa a
        transcrição mais lenta, porque as duas threads de um mesmo núcleo
        disputam a unidade de cálculo que as multiplicações de matriz já
        saturam sozinhas. Ver `hardware.physical_cores`.
        """
        total = total or _default_cores()
        return max(1, round(total * self.cpu_percent / 100))

    def gpu_workers(self) -> int:
        """Paralelismo na GPU: 1 worker abaixo de 60%, 2 acima."""
        return 2 if self.gpu_percent >= 60 else 1

    # --------------------------------------------------------------- memória --
    def ram_budget_gb(self, total_gb: float | None) -> float | None:
        return None if not total_gb else total_gb * self.ram_percent / 100

    def vram_budget_gb(self, total_gb: float | None) -> float | None:
        return None if not total_gb else total_gb * self.vram_percent / 100

    # ---------------------------------------------------------------- resumo --
    def describe(self) -> str:
        gpu = "desligada" if not self.use_gpu else f"{self.gpu_percent}%"
        return (
            f"CPU {self.cpu_percent}% ({self.cpu_threads()} núcleos), "
            f"RAM {self.ram_percent}%, GPU {gpu}, VRAM {self.vram_percent}%"
        )

    @property
    def is_default(self) -> bool:
        return self == ResourceLimits()


DEFAULT = ResourceLimits()


@dataclass(frozen=True)
class Preset:
    """Um conjunto de limites com nome de gente (BACKLOG-028).

    Ninguém precisa saber o que é "1/4 dos núcleos" para escolher entre
    continuar usando o computador e terminar mais rápido.
    """

    key: str
    label: str
    limits: ResourceLimits
    blurb: str


PRESETS: tuple[Preset, ...] = (
    Preset(
        "leve", "Leve",
        ResourceLimits(cpu_percent=25, ram_percent=40, gpu_percent=0, vram_percent=50),
        "Mal dá para perceber que está rodando. Só o processador, devagar — bom "
        "para deixar trabalhando enquanto você usa o computador.",
    ),
    Preset(
        "equilibrado", "Equilibrado",
        ResourceLimits(cpu_percent=60, ram_percent=50, gpu_percent=60, vram_percent=80),
        "Rápido sem travar o resto. É o que eu escolheria para o dia a dia.",
    ),
    Preset(
        "rapido", "Rápido",
        ResourceLimits(),
        "Usa a máquina inteira. O computador fica pesado enquanto trabalha.",
    ),
    Preset(
        "maximo", "Máximo",
        ResourceLimits(cpu_percent=100, ram_percent=80, gpu_percent=100, vram_percent=100),
        "Tudo, inclusive memória para o modelo maior caber. Deixe rodando e vá "
        "fazer outra coisa.",
    ),
)


def preset_for(limits: ResourceLimits) -> Preset | None:
    """O preset equivalente a estes limites, se houver um exato."""
    for preset in PRESETS:
        if preset.limits == limits:
            return preset
    return None


def preset_by_key(key: str) -> Preset | None:
    for preset in PRESETS:
        if preset.key == key:
            return preset
    return None


def apply_process_priority(limits: ResourceLimits) -> None:
    """Rebaixa a prioridade do processo quando o usuário limitou a CPU.

    Abaixo de 60% a intenção é clara: "quero continuar usando o computador".
    Prioridade menor faz mais diferença prática que contar núcleos.
    """
    if limits.cpu_percent >= 60:
        return
    try:
        if sys.platform == "win32":
            import ctypes

            # BELOW_NORMAL_PRIORITY_CLASS
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000
            )
        else:
            os.nice(10)
    except Exception as exc:  # pragma: no cover - sem permissão
        log.debug("Não consegui ajustar a prioridade do processo: %s", exc)


def load() -> ResourceLimits:
    """Limites salvos. Padrão de fábrica quando não há nada guardado."""
    try:
        data = json.loads(_prefs_path().read_text(encoding="utf-8"))
        stored = data.get("limits") or {}
        return ResourceLimits(
            cpu_percent=int(stored.get("cpu_percent", DEFAULT.cpu_percent)),
            ram_percent=int(stored.get("ram_percent", DEFAULT.ram_percent)),
            gpu_percent=int(stored.get("gpu_percent", DEFAULT.gpu_percent)),
            vram_percent=int(stored.get("vram_percent", DEFAULT.vram_percent)),
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return DEFAULT


def save(limits: ResourceLimits) -> None:
    """Guarda os limites junto com as outras preferências da interface."""
    try:
        path = _prefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        data["limits"] = asdict(limits)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - disco cheio, permissão
        log.debug("Não consegui salvar os limites: %s", exc)


def from_dict(data: dict | None) -> ResourceLimits:
    """Constrói a partir de um dicionário (usado pelo processo filho)."""
    if not data:
        return DEFAULT
    return ResourceLimits(
        cpu_percent=int(data.get("cpu_percent", DEFAULT.cpu_percent)),
        ram_percent=int(data.get("ram_percent", DEFAULT.ram_percent)),
        gpu_percent=int(data.get("gpu_percent", DEFAULT.gpu_percent)),
        vram_percent=int(data.get("vram_percent", DEFAULT.vram_percent)),
    )
