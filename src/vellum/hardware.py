"""Detecção de hardware e escolha automática de device/compute_type/modelo.

Objetivo: nunca falhar por falta de VRAM. Se a GPU não couber, cai para um
modelo menor; se ainda assim não couber (ou faltar cuDNN), cai para CPU.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from .ffmpeg_tools import resolve_tools

if TYPE_CHECKING:  # evita import circular em tempo de execução
    from .limits import ResourceLimits

log = logging.getLogger("vellum.hardware")

#: VRAM/RAM aproximada (GB) para carregar cada modelo em int8. Valores medidos
#: com folga: servem para decidir fallback, não para prometer desempenho.
MODEL_MEMORY_GB: dict[str, float] = {
    "tiny": 0.5,
    "base": 0.7,
    "small": 1.2,
    "medium": 2.4,
    "large-v3": 3.6,
    "large-v3-turbo": 2.2,
    "distil-large-v3": 2.2,
}

#: O que o próprio programa ocupa, fora o modelo de transcrição.
BASE_RAM_GB = 0.9

#: A diarização carrega um segundo modelo (ECAPA) e os embeddings.
DIARIZE_RAM_GB = 1.5

#: O `qwen3:14b` do Ollama, que roda num processo separado. Não sai do nosso
#: orçamento, mas sai da memória da máquina — e é o que faz o computador
#: engasgar em quem tem 8 GB.
OLLAMA_RAM_GB = 9.0

#: Ordem de rebaixamento quando falta memória.
DOWNGRADE_ORDER: tuple[str, ...] = (
    "large-v3",
    "large-v3-turbo",
    "distil-large-v3",
    "medium",
    "small",
    "base",
    "tiny",
)


@dataclass(frozen=True)
class HardwareInfo:
    has_cuda: bool
    cuda_device_count: int
    gpu_name: str | None
    gpu_vram_gb: float | None
    cpu_count: int
    ram_gb: float | None
    platform: str

    @property
    def summary(self) -> str:
        gpu = (
            f"{self.gpu_name} ({self.gpu_vram_gb:.1f} GB)"
            if self.gpu_name and self.gpu_vram_gb
            else (self.gpu_name or "nenhuma GPU CUDA")
        )
        ram = f"{self.ram_gb:.1f} GB" if self.ram_gb else "desconhecida"
        return f"{self.cpu_count} threads de CPU, RAM {ram}, GPU: {gpu}"


@dataclass(frozen=True)
class RuntimeChoice:
    device: str
    compute_type: str
    model: str
    device_name: str | None
    notes: list[str]


def _total_ram_gb() -> float | None:
    try:
        if sys.platform == "win32":
            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullTotalPhys / (1024 ** 3)
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return (pages * page_size) / (1024 ** 3)
    except Exception:  # pragma: no cover - plataformas exóticas
        return None


def _query_nvidia_smi() -> tuple[str | None, float | None]:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return None, None
    try:
        proc = subprocess.run(
            [binary, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception:  # pragma: no cover - driver travado
        return None, None
    line = (proc.stdout or "").strip().splitlines()
    if proc.returncode != 0 or not line:
        return None, None
    name, _, memory = line[0].partition(",")
    try:
        vram_gb = float(memory.strip()) / 1024.0
    except ValueError:
        vram_gb = None
    return name.strip() or None, vram_gb


@lru_cache(maxsize=1)
def prepare_cuda_libraries() -> tuple[str, ...]:
    """Torna visíveis as DLLs/SOs CUDA instalados via pip (pacotes `nvidia-*-cu12`).

    Sem isto, o CTranslate2 quebra com "Library cublas64_12.dll is not found"
    mesmo com as bibliotecas instaladas no venv — elas ficam em
    `site-packages/nvidia/*/bin`, que não está no PATH do processo.
    """
    try:
        import nvidia
    except Exception:
        return ()

    base = Path(next(iter(nvidia.__path__), ""))
    if not base.exists():
        return ()

    added: list[str] = []
    subdir = "bin" if sys.platform == "win32" else "lib"
    for directory in sorted(base.glob(f"*/{subdir}")):
        if not directory.is_dir():
            continue
        added.append(str(directory))
        if sys.platform == "win32":
            try:
                os.add_dll_directory(str(directory))
            except OSError:  # pragma: no cover - caminho inválido
                continue
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")

    if added:
        log.debug("Bibliotecas CUDA do pip registradas: %s", ", ".join(added))
    elif sys.platform != "win32":  # pragma: no cover - específico de Linux
        log.debug("No Linux, exporte LD_LIBRARY_PATH antes de iniciar o processo.")
    return tuple(added)


@lru_cache(maxsize=1)
def detect_hardware() -> HardwareInfo:
    """Inspeciona CPU/RAM/GPU uma única vez por processo."""
    prepare_cuda_libraries()
    cuda_count = 0
    try:
        import ctranslate2

        cuda_count = int(ctranslate2.get_cuda_device_count())
    except Exception as exc:  # pragma: no cover - ctranslate2 ausente
        log.debug("ctranslate2 indisponível para detecção de CUDA: %s", exc)

    gpu_name, vram = _query_nvidia_smi() if cuda_count > 0 else (None, None)
    return HardwareInfo(
        has_cuda=cuda_count > 0,
        cuda_device_count=cuda_count,
        gpu_name=gpu_name,
        gpu_vram_gb=vram,
        cpu_count=os.cpu_count() or 1,
        ram_gb=_total_ram_gb(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
    )


#: Reserva para o runtime CUDA/contexto antes de decidir se o modelo cabe.
_VRAM_RESERVE_GB = 0.8
#: Na CPU só contamos com metade da RAM: o resto é sistema, buffers e o próprio áudio.
_RAM_USABLE_FRACTION = 0.5


def memory_budget_gb(
    hardware: HardwareInfo, device: str, limits: ResourceLimits | None = None
) -> float | None:
    """Memória utilizável (GB) para o modelo no device escolhido.

    Sem limites explícitos vale o padrão histórico: VRAM menos a reserva do
    runtime CUDA, ou metade da RAM. Com limites, a porcentagem escolhida pelo
    usuário manda — é assim que os sliders da janela viram efeito real.
    """
    if device == "cuda":
        if not hardware.gpu_vram_gb:
            return None
        usable = hardware.gpu_vram_gb - _VRAM_RESERVE_GB
        if limits is not None:
            usable = min(usable, hardware.gpu_vram_gb * limits.vram_percent / 100)
        return usable
    if not hardware.ram_gb:
        return None
    fraction = (limits.ram_percent / 100) if limits is not None else _RAM_USABLE_FRACTION
    return hardware.ram_gb * fraction


@dataclass(frozen=True)
class Recommendation:
    """Quanta memória este trabalho pede (BACKLOG-029).

    Serve para comparar com o que os limites liberaram: número na tela que não
    conversa com o trabalho pedido é decoração.
    """

    ram_gb: float
    vram_gb: float
    notes: list[str]


def recommended_for(
    model: str, *, diarize: bool = False, summarize: bool = False
) -> Recommendation:
    """Memória recomendada para rodar este trabalho sem rebaixar nada."""
    modelo_gb = MODEL_MEMORY_GB.get(model, 3.6)
    ram = BASE_RAM_GB + modelo_gb
    notas = [f"modelo {model}: {modelo_gb:.1f} GB"]
    if diarize:
        ram += DIARIZE_RAM_GB
        notas.append(f"quem fala: +{DIARIZE_RAM_GB:.1f} GB")
    if summarize:
        notas.append(
            f"o resumo do Ollama pede mais ~{OLLAMA_RAM_GB:.0f} GB, "
            "num processo separado"
        )
    # Na GPU o modelo é carregado em meia precisão e ocupa mais que em int8.
    return Recommendation(ram_gb=ram, vram_gb=modelo_gb + _VRAM_RESERVE_GB, notes=notas)


def _fits(model: str, budget_gb: float | None) -> bool:
    if budget_gb is None:
        return True
    return MODEL_MEMORY_GB.get(model, 3.6) <= budget_gb


def _downgrade(model: str, budget_gb: float | None) -> str:
    """Devolve o maior modelo que cabe no orçamento de memória."""
    if _fits(model, budget_gb):
        return model
    start = DOWNGRADE_ORDER.index(model) if model in DOWNGRADE_ORDER else 0
    for candidate in DOWNGRADE_ORDER[start + 1 :]:
        if _fits(candidate, budget_gb):
            return candidate
    return "tiny"


def select_runtime(
    *,
    requested_device: str = "auto",
    requested_compute_type: str = "auto",
    requested_model: str = "small",
    hardware: HardwareInfo | None = None,
    limits: ResourceLimits | None = None,
) -> RuntimeChoice:
    """Resolve device/compute_type/modelo respeitando o pedido do usuário.

    Escolhas explícitas do usuário são mantidas; só o que estiver em "auto" é
    decidido aqui. Rebaixamento de modelo por falta de memória sempre gera nota.
    """
    hardware = hardware or detect_hardware()
    notes: list[str] = []

    if limits is not None and not limits.use_gpu:
        requested_device = "cpu"
        notes.append("GPU desligada nos limites de uso: processando na CPU.")

    if requested_device == "auto":
        device = "cuda" if hardware.has_cuda else "cpu"
        if not hardware.has_cuda:
            notes.append("Nenhuma GPU CUDA detectada: usando CPU.")
    else:
        device = requested_device
        if device == "cuda" and not hardware.has_cuda:
            notes.append("GPU pedida, mas o CTranslate2 não enxerga nenhum device CUDA.")

    if requested_compute_type != "auto":
        compute_type = requested_compute_type
    elif device == "cuda":
        # int8_float16 é o melhor custo/benefício em Turing+ com pouca VRAM.
        compute_type = "int8_float16"
    else:
        compute_type = "int8"

    budget = memory_budget_gb(hardware, device, limits)
    model = _downgrade(requested_model, budget)
    if model != requested_model:
        notes.append(
            f"Modelo rebaixado de '{requested_model}' para '{model}': "
            f"memória disponível estimada em {budget:.1f} GB."
            if budget is not None
            else f"Modelo rebaixado de '{requested_model}' para '{model}'."
        )

    return RuntimeChoice(
        device=device,
        compute_type=compute_type,
        model=model,
        device_name=hardware.gpu_name if device == "cuda" else platform.processor() or "CPU",
        notes=notes,
    )


def cpu_fallback(
    choice: RuntimeChoice, reason: str, limits: ResourceLimits | None = None
) -> RuntimeChoice:
    """Versão CPU de uma escolha que falhou na GPU (cuDNN ausente, OOM etc.)."""
    hardware = detect_hardware()
    budget = memory_budget_gb(hardware, "cpu", limits)
    return RuntimeChoice(
        device="cpu",
        compute_type="int8",
        model=_downgrade(choice.model, budget),
        device_name=platform.processor() or "CPU",
        notes=[*choice.notes, f"Fallback para CPU: {reason}"],
    )


# --------------------------------------------------------------------------- #
# Avaliação da máquina
# --------------------------------------------------------------------------- #
#: Do melhor para o pior. Serve para escolher o pior veredito de uma lista.
CHECK_LEVELS: tuple[str, ...] = ("boa", "ok", "apertada", "ruim")


@dataclass(frozen=True)
class Finding:
    """Uma linha do diagnóstico: o que foi medido e o que isso significa."""

    item: str
    value: str
    level: str
    note: str = ""


@dataclass(frozen=True)
class MachineCheck:
    level: str
    headline: str
    findings: list[Finding]
    advice: list[str]
    #: O que foi medido. A pagina Desempenho usa para dizer onde o trabalho vai
    #: rodar sem pagar uma segunda deteccao (que conversa com o driver).
    hardware: HardwareInfo | None = None

    @property
    def should_warn(self) -> bool:
        """Só interrompemos o usuário quando o quadro é realmente ruim."""
        return self.level == "ruim"


def _worst(levels: Iterable[str]) -> str:
    pior = "boa"
    for nivel in levels:
        if CHECK_LEVELS.index(nivel) > CHECK_LEVELS.index(pior):
            pior = nivel
    return pior


def _grade(value: float | None, boa: float, ok: float, apertada: float) -> str:
    """Nota de um número onde maior é melhor. `None` não penaliza nem premia."""
    if value is None:
        return "ok"
    if value >= boa:
        return "boa"
    if value >= ok:
        return "ok"
    if value >= apertada:
        return "apertada"
    return "ruim"


def _free_disk_gb(path: Path) -> float | None:
    """Espaço livre onde os modelos vão morar. Sobe até a primeira pasta que existe."""
    alvo = path
    while not alvo.exists() and alvo != alvo.parent:
        alvo = alvo.parent
    try:
        return shutil.disk_usage(alvo).free / (1024 ** 3)
    except OSError:  # pragma: no cover - caminho inacessível
        return None


def _ffmpeg_finding() -> Finding:
    try:
        resolve_tools()
    except Exception:
        return Finding(
            "ffmpeg", "não encontrado", "ruim",
            "Sem ele o aplicativo não consegue nem abrir o arquivo.",
        )
    return Finding("ffmpeg", "instalado", "boa")


def assess_machine(
    hardware: HardwareInfo | None = None, models_dir: Path | None = None
) -> MachineCheck:
    """Diz se vale a pena rodar o aplicativo nesta máquina, e por quê.

    Os cortes vêm do que a transcrição realmente exige: memória para carregar o
    modelo, núcleos para não levar horas e disco para baixar os modelos na
    primeira vez. Nenhum deles é chute de marketing — são os três motivos pelos
    quais o processamento falha ou demora demais.
    """
    hardware = hardware or detect_hardware()
    achados: list[Finding] = []

    nota_cpu = _grade(float(hardware.cpu_count), 8, 4, 2)
    achados.append(Finding(
        "Processador", f"{hardware.cpu_count} threads", nota_cpu,
        "" if nota_cpu in ("boa", "ok")
        else "Com poucos núcleos a transcrição na CPU fica várias vezes mais lenta "
             "que o tempo do áudio.",
    ))

    nota_ram = _grade(hardware.ram_gb, 16, 8, 4)
    achados.append(Finding(
        "Memória (RAM)",
        f"{hardware.ram_gb:.1f} GB" if hardware.ram_gb else "desconhecida",
        nota_ram,
        "" if nota_ram in ("boa", "ok")
        else "Abaixo de 4 GB só o modelo mais fraco cabe, e ainda com risco de "
             "faltar memória.",
    ))

    if hardware.has_cuda and hardware.gpu_vram_gb:
        nota_gpu = _grade(hardware.gpu_vram_gb, 6, 4, 2)
        achados.append(Finding(
            "Placa de vídeo", f"{hardware.gpu_name} ({hardware.gpu_vram_gb:.1f} GB)",
            nota_gpu,
        ))
    else:
        # Não ter GPU não é defeito: é o caso mais comum, só mais lento.
        achados.append(Finding(
            "Placa de vídeo", "nenhuma GPU CUDA", "ok",
            "Vai rodar na CPU. Funciona, mas demora mais.",
        ))

    livre = _free_disk_gb(models_dir or Path("./models"))
    nota_disco = _grade(livre, 5, 2, 1)
    achados.append(Finding(
        "Espaço em disco", f"{livre:.1f} GB livres" if livre else "desconhecido",
        nota_disco,
        "" if nota_disco in ("boa", "ok")
        else "Os modelos são baixados uma vez e ocupam de 0,5 a 3 GB.",
    ))

    achados.append(_ffmpeg_finding())

    nivel = _worst(achado.level for achado in achados)
    manchetes = {
        "boa": "Esta máquina dá conta com folga.",
        "ok": "Esta máquina dá conta.",
        "apertada": "Vai funcionar, mas devagar.",
        "ruim": "Esta máquina provavelmente não vai dar conta.",
    }

    conselhos: list[str] = []
    if nivel in ("apertada", "ruim"):
        conselhos.append(
            "Comece com arquivos curtos e com a qualidade em \"Rascunho\" ou "
            "\"Recomendado\" — os modelos maiores é que pesam."
        )
        conselhos.append(
            "Na página Desempenho existem controles de processador, memória, placa de "
            "vídeo e VRAM. Baixando-os o aplicativo fica mais lento, mas devolve a "
            "máquina para você usar enquanto ele trabalha."
        )
    if any(a.item == "ffmpeg" and a.level == "ruim" for a in achados):
        conselhos.insert(0, "Instale o ffmpeg antes de tentar: winget install Gyan.FFmpeg")
    if nivel == "ruim":
        conselhos.append(
            "Você pode continuar assim mesmo — nada quebra o computador. O risco é o "
            "trabalho demorar demais ou parar por falta de memória."
        )

    return MachineCheck(
        level=nivel, headline=manchetes[nivel], findings=achados, advice=conselhos,
        hardware=hardware,
    )
