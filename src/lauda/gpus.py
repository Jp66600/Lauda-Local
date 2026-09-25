"""Quais placas de vídeo existem nesta máquina, e de quem elas são.

O motor de transcrição (CTranslate2) tem exatamente dois caminhos: `cpu` e
`cuda`. Não há ROCm, não há DirectML, não há Metal — dá para conferir com
``ctranslate2.get_supported_compute_types``. Isso significa que **uma Radeon ou
uma Intel não aceleram a transcrição**, por mais nova que seja a placa.

Esse fato não é o problema. O problema era o programa não saber diferenciar
"você não tem placa de vídeo" de "você tem uma placa que este motor não usa" —
e dizer a primeira coisa para quem está com uma RX 7800 XT na máquina. Quem lê
isso vai reinstalar driver atrás de um defeito que não existe.

Daí este módulo: ele enumera os adaptadores pelo identificador do fabricante no
barramento PCI, que é a única fonte que não depende de o driver certo estar
instalado. Com isso o resto do programa pode escolher o melhor caminho para
cada máquina **e dizer por que** escolheu.

Nada aqui abre subprocesso: é registro do Windows e `/sys` no Linux. A detecção
acontece na abertura do programa e em cada processo filho, e um `nvidia-smi`
que demora dois segundos apareceria como lentidão na partida.
"""

from __future__ import annotations

import logging
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("lauda.gpus")

#: Identificador do fabricante no barramento PCI. É o mesmo número em qualquer
#: sistema operacional, e continua certo quando o driver não está instalado.
PCI_VENDORS: dict[int, str] = {
    0x10DE: "nvidia",
    0x1002: "amd",     # placas (a ATI virou AMD; o identificador ficou)
    0x1022: "amd",     # alguns APUs se anunciam pelo identificador do processador
    0x8086: "intel",
    0x106B: "apple",
}

#: Nome de cada fabricante para aparecer na tela.
VENDOR_LABELS: dict[str, str] = {
    "nvidia": "NVIDIA",
    "amd": "AMD",
    "intel": "Intel",
    "apple": "Apple",
    "outro": "outro fabricante",
}

#: Adaptadores que existem no sistema mas não são placas de vídeo: área de
#: trabalho remota, máquina virtual, driver genérico. Contá-los faria o
#: programa anunciar uma "placa" que não desenha nada.
_VIRTUAL = re.compile(
    r"parsec|remote\s*(desktop|display)|virtual|basic display|basic render|"
    r"vmware|virtualbox|hyper-v|citrix|teamviewer|\bidd\b|mirror\s*driver",
    re.IGNORECASE,
)

#: Nome de GPU integrada da AMD: termina em "Graphics" sem número de modelo
#: ("AMD Radeon(TM) Graphics", "Radeon(TM) Vega 8 Graphics"). As dedicadas
#: trazem RX, Pro ou Instinct no nome.
_AMD_INTEGRATED = re.compile(r"graphics\s*$", re.IGNORECASE)
_AMD_DISCRETE = re.compile(r"\bRX\b|\bPro\s+W?\d|\bInstinct\b|\bFire\w*\b", re.IGNORECASE)


@dataclass(frozen=True)
class Gpu:
    """Um adaptador de vídeo, do jeito que o sistema o descreve."""

    vendor: str                    # nvidia | amd | intel | apple | outro
    name: str
    vram_gb: float | None = None
    integrated: bool | None = None

    @property
    def vendor_label(self) -> str:
        """O fabricante por extenso, omitido quando o nome já o traz.

        "NVIDIA NVIDIA GeForce RTX 4060" não é informação, é gagueira: os
        fabricantes já põem o próprio nome no `DriverDesc`.
        """
        rotulo = VENDOR_LABELS.get(self.vendor, self.vendor)
        return "" if rotulo.lower() in self.name.lower() else rotulo

    @property
    def label(self) -> str:
        """Como a placa aparece na tela, com a memória quando ela é conhecida."""
        partes = [self.name]
        # Abaixo de 1 GB a "memória" de uma integrada é só a fatia reservada da
        # RAM do sistema, que não diz nada sobre o que a placa aguenta — e
        # "0 GB" soa como defeito.
        if self.vram_gb and self.vram_gb >= 1:
            partes.append(f"{self.vram_gb:.0f} GB")
        if self.integrated:
            partes.append("integrada")
        return f"{partes[0]} ({', '.join(partes[1:])})" if len(partes) > 1 else partes[0]

    @property
    def accelerates_transcription(self) -> bool:
        """Só a NVIDIA: o CTranslate2 não tem outro caminho de GPU."""
        return self.vendor == "nvidia"


def _classify_amd(name: str) -> bool | None:
    if _AMD_DISCRETE.search(name):
        return False
    if _AMD_INTEGRATED.search(name):
        return True
    return None


def _classify(vendor: str, name: str) -> bool | None:
    """Integrada ou dedicada? `None` quando não dá para saber pelo nome."""
    if vendor == "nvidia":
        return False          # a NVIDIA não faz gráficos integrados em x86
    if vendor == "apple":
        return True           # no Apple Silicon a GPU é parte do chip
    if vendor == "intel":
        # A Arc é dedicada; todo o resto da Intel é integrado ao processador.
        return "arc" not in name.lower()
    if vendor == "amd":
        return _classify_amd(name)
    return None


# --------------------------------------------------------------------------- #
# Windows: registro
# --------------------------------------------------------------------------- #
#: Classe dos adaptadores de vídeo. Cada subchave numerada é uma placa.
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def _windows_gpus() -> list[Gpu]:
    # A guarda é de plataforma e de tipo: o `winreg` só existe no Windows, e
    # sem ela o mypy rodando no Linux (é o caso da integração contínua)
    # analisa este corpo e não encontra nenhuma das funções.
    if sys.platform != "win32":  # pragma: no cover - a chamada já é por plataforma
        return []

    import winreg

    achadas: list[Gpu] = []
    try:
        raiz = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS)
    except OSError as exc:  # pragma: no cover - registro inacessível
        log.debug("Não consegui ler a classe de vídeo no registro: %s", exc)
        return []

    with raiz:
        for indice in range(64):          # nenhuma máquina tem 64 adaptadores
            try:
                sub = winreg.EnumKey(raiz, indice)
            except OSError:
                break
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(raiz, sub) as chave:
                    gpu = _gpu_from_registry(winreg, chave)
            except OSError:  # pragma: no cover - chave sumiu no meio
                continue
            if gpu is not None:
                achadas.append(gpu)
    return achadas


def _read(winreg_mod, chave, nome: str):
    try:
        valor, _tipo = winreg_mod.QueryValueEx(chave, nome)
    except OSError:
        return None
    return valor


def _gpu_from_registry(winreg_mod, chave) -> Gpu | None:
    nome = _read(winreg_mod, chave, "DriverDesc")
    identificador = _read(winreg_mod, chave, "MatchingDeviceId") or ""
    if not isinstance(nome, str) or not nome.strip():
        return None
    if _VIRTUAL.search(nome):
        return None

    # Sem `ven_XXXX` não é um dispositivo PCI: é adaptador de software.
    casa = re.search(r"ven_([0-9a-f]{4})", str(identificador), re.IGNORECASE)
    if not casa:
        return None
    vendor = PCI_VENDORS.get(int(casa.group(1), 16), "outro")

    # `qwMemorySize` é de 64 bits e diz a verdade; `MemorySize`, de 32, satura
    # em 4 GB e faria uma placa de 8 GB parecer de 4.
    bytes_vram = _read(winreg_mod, chave, "HardwareInformation.qwMemorySize")
    vram = None
    if isinstance(bytes_vram, int) and bytes_vram > 0:
        vram = bytes_vram / (1024 ** 3)

    nome = nome.strip()
    return Gpu(vendor=vendor, name=nome, vram_gb=vram, integrated=_classify(vendor, nome))


# --------------------------------------------------------------------------- #
# Linux: /sys
# --------------------------------------------------------------------------- #
def _linux_gpus() -> list[Gpu]:
    achadas: list[Gpu] = []
    for cartao in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        if "-" in cartao.name:            # card0-HDMI-A-1 é uma saída, não a placa
            continue
        dispositivo = cartao / "device"
        try:
            bruto = (dispositivo / "vendor").read_text().strip()
        except OSError:
            continue
        try:
            vendor = PCI_VENDORS.get(int(bruto, 16), "outro")
        except ValueError:  # pragma: no cover - conteúdo inesperado
            continue

        nome = _linux_name(dispositivo, vendor)
        vram = None
        try:
            vram = int((dispositivo / "mem_info_vram_total").read_text().strip()) / (1024 ** 3)
        except (OSError, ValueError):
            pass
        achadas.append(Gpu(vendor=vendor, name=nome, vram_gb=vram,
                           integrated=_classify(vendor, nome)))
    return achadas


def _linux_name(dispositivo: Path, vendor: str) -> str:
    """O nome comercial raramente está no /sys; o modelo PCI sempre está."""
    try:
        for linha in (dispositivo / "uevent").read_text().splitlines():
            if linha.startswith("PCI_ID="):
                return f"{VENDOR_LABELS.get(vendor, vendor)} {linha.split('=', 1)[1]}"
    except OSError:
        pass
    return f"GPU {VENDOR_LABELS.get(vendor, vendor)}"


# --------------------------------------------------------------------------- #
# macOS
# --------------------------------------------------------------------------- #
def _macos_gpus() -> list[Gpu]:
    # No Apple Silicon a GPU é parte do chip e não tem memória própria: ela usa
    # a mesma RAM do sistema. Nos Intel antigos, a integrada é da Intel.
    if platform.machine() == "arm64":
        return [Gpu(vendor="apple", name=f"GPU do {platform.processor() or 'Apple Silicon'}",
                    integrated=True)]
    return [Gpu(vendor="intel", name="GPU integrada Intel", integrated=True)]


def detect_gpus() -> list[Gpu]:
    """Os adaptadores de vídeo desta máquina, sem abrir subprocesso.

    Devolve lista vazia quando não dá para saber — o que é diferente de "não
    tem placa", e quem chama precisa tratar assim.
    """
    try:
        if sys.platform == "win32":
            return _windows_gpus()
        if sys.platform == "darwin":
            return _macos_gpus()
        return _linux_gpus()
    except Exception as exc:  # pragma: no cover - sistema fora do previsto
        log.debug("Não consegui enumerar as placas de vídeo: %s", exc)
        return []


def describe(gpus: list[Gpu] | tuple[Gpu, ...]) -> str:
    """Uma linha com as placas encontradas, para log e diagnóstico."""
    if not gpus:
        return "nenhuma placa de vídeo identificada"
    return "; ".join(f"{g.vendor_label} {g.label}".strip() for g in gpus)
