"""Identificação da placa de vídeo e o que o programa decide com ela.

Nenhuma destas máquinas existe aqui: o teste monta o `HardwareInfo` na mão. É
de propósito — o ponto do módulo é justamente atender placas que quem escreve
o código não tem, e um teste que só rodasse na máquina certa não serviria para
nada.
"""

from __future__ import annotations

import pytest

from lauda.gpus import Gpu, describe
from lauda.hardware import HardwareInfo, assess_machine, gpu_explanation, select_runtime


def _maquina(placas: list[Gpu], *, cuda: bool = False, nucleos=8, threads=16):
    return HardwareInfo(
        has_cuda=cuda, cuda_device_count=1 if cuda else 0,
        gpu_name=placas[0].name if (cuda and placas) else None,
        gpu_vram_gb=placas[0].vram_gb if (cuda and placas) else None,
        cpu_count=threads, ram_gb=16.0, platform="teste",
        gpus=tuple(placas), physical_cores=nucleos,
    )


RADEON = Gpu("amd", "AMD Radeon RX 7800 XT", 16.0, False)
APU = Gpu("amd", "AMD Radeon(TM) Graphics", 0.5, True)
INTEL = Gpu("intel", "Intel(R) UHD Graphics 630", 1.0, True)
ARC = Gpu("intel", "Intel(R) Arc(TM) A770 Graphics", 16.0, False)
GEFORCE = Gpu("nvidia", "NVIDIA GeForce RTX 3060", 12.0, False)


# ------------------------------------------------- de quem é a placa, e o quê --
@pytest.mark.parametrize("placa, acelera", [
    (GEFORCE, True), (RADEON, False), (APU, False), (INTEL, False), (ARC, False),
    (Gpu("apple", "GPU do Apple M2", None, True), False),
])
def test_so_a_nvidia_acelera_a_transcricao(placa: Gpu, acelera: bool):
    """O CTranslate2 tem dois devices: cpu e cuda. Não há ROCm nem DirectML."""
    assert placa.accelerates_transcription is acelera


def test_o_fabricante_nao_e_repetido_no_rotulo():
    """Os fabricantes já põem o próprio nome no driver."""
    assert GEFORCE.vendor_label == ""
    assert describe([GEFORCE]) == "NVIDIA GeForce RTX 3060 (12 GB)"
    assert Gpu("amd", "Radeon RX 6600", 8.0).vendor_label == "AMD"


def test_memoria_de_integrada_nao_vira_zero_gb():
    """Meio GB reservado da RAM não é a memória da placa — e "0 GB" soa defeito."""
    assert "GB" not in APU.label
    assert "integrada" in APU.label
    assert "16 GB" in RADEON.label


# ----------------------------------------------------- qual caminho é tomado --
@pytest.mark.parametrize("placa", [RADEON, APU, INTEL, ARC])
def test_placa_de_outro_fabricante_vai_para_o_processador(placa: Gpu):
    hardware = _maquina([placa])
    escolha = select_runtime(requested_model="small", hardware=hardware)

    assert escolha.device == "cpu"
    assert hardware.gpu_situation == "outro_fabricante"


def test_nvidia_vista_pelo_ctranslate2_usa_a_placa():
    hardware = _maquina([GEFORCE], cuda=True)
    escolha = select_runtime(requested_model="small", hardware=hardware)

    assert escolha.device == "cuda"
    assert escolha.notes == [], "usar a placa é o esperado; não gera aviso"


def test_a_dedicada_manda_na_frente_da_integrada():
    """Notebook com duas: a decisão é da que realmente desenha."""
    hardware = _maquina([INTEL, RADEON])

    assert hardware.graphics == RADEON


# ------------------------------------- a frase que o usuário lê, por situação --
def test_amd_nao_e_confundida_com_ausencia_de_placa():
    """O defeito de origem: uma RX 7800 XT era anunciada como "nenhuma GPU"."""
    frase = gpu_explanation(_maquina([RADEON]))

    assert "AMD" in frase and "Radeon RX 7800 XT" in frase
    assert "só acelera em NVIDIA" in frase
    assert "não é defeito" in frase.lower()
    assert "nenhuma" not in frase.lower()


def test_integrada_e_chamada_de_integrada():
    assert gpu_explanation(_maquina([INTEL])).startswith("A GPU integrada")
    assert gpu_explanation(_maquina([RADEON])).startswith("A placa de vídeo")


def test_nvidia_sem_cuda_e_tratada_como_conserto_possivel():
    """Placa certa e driver pela metade é a única situação acionável."""
    hardware = _maquina([GEFORCE])           # NVIDIA presente, CUDA não enxerga
    assert hardware.gpu_situation == "cuda_quebrado"

    frase = gpu_explanation(hardware)
    assert "driver" in frase and "cuDNN" in frase

    check = assess_machine(hardware)
    assert any("Atualize o driver" in c for c in check.advice)


def test_maquina_sem_placa_nenhuma_nao_ganha_conselho_de_driver():
    check = assess_machine(_maquina([]))

    assert not any("driver" in c for c in check.advice)
    assert _maquina([]).gpu_situation == "sem_placa"


def test_o_diagnostico_nomeia_a_placa_que_existe():
    linha = next(
        f for f in assess_machine(_maquina([RADEON])).findings
        if f.item == "Placa de vídeo"
    )

    assert "Radeon RX 7800 XT" in linha.value
    assert linha.level == "ok", "ter uma AMD não é defeito da máquina"


def test_a_nvidia_parada_nao_rebaixa_o_veredito_da_maquina():
    """Se rebaixasse, o diagnóstico mandaria DIMINUIR os limites — o oposto."""
    check = assess_machine(_maquina([GEFORCE]))

    assert check.level == "ok"
    assert not any("Comece com arquivos curtos" in c for c in check.advice)


# ------------------------------------------------------------ o resumo de uma linha --
def test_o_resumo_diz_nucleos_e_threads_separados():
    resumo = _maquina([RADEON], nucleos=8, threads=16).summary

    assert "8 núcleos / 16 threads" in resumo
    assert "não acelera a transcrição" in resumo


# ------------------------------------------- a detecção na máquina de verdade --
def test_a_deteccao_nao_quebra_nesta_maquina():
    """Roda de verdade: registro no Windows, /sys no Linux. Sem subprocesso."""
    from lauda.gpus import PCI_VENDORS, detect_gpus

    for gpu in detect_gpus():
        assert gpu.name.strip()
        assert gpu.vendor in set(PCI_VENDORS.values()) | {"outro"}
        assert gpu.vram_gb is None or gpu.vram_gb > 0


def test_adaptador_virtual_nao_conta_como_placa():
    """Área de trabalho remota e máquina virtual instalam adaptadores de vídeo."""
    from lauda.gpus import _VIRTUAL

    for nome in ("Parsec Virtual Display Adapter", "Microsoft Basic Display Adapter",
                 "VMware SVGA 3D", "Microsoft Remote Display Adapter",
                 "Oracle VirtualBox Graphics Adapter"):
        assert _VIRTUAL.search(nome), nome

    for nome in ("NVIDIA GeForce RTX 4060", "AMD Radeon RX 7800 XT",
                 "Intel(R) UHD Graphics 630"):
        assert not _VIRTUAL.search(nome), nome


def test_os_nucleos_fisicos_nunca_passam_das_threads():
    import os

    from lauda.hardware import physical_cores

    nucleos = physical_cores()
    if nucleos is None:
        pytest.skip("este sistema não conta núcleos físicos")
    assert 1 <= nucleos <= (os.cpu_count() or 1)


def test_o_nome_do_processador_nao_e_o_codigo_da_familia():
    """"AMD64 Family 25 Model 33" não diz a ninguém qual processador é."""
    from lauda.hardware import cpu_name

    nome = cpu_name()
    assert nome.strip()
    assert "Family" not in nome or nome == "CPU"
