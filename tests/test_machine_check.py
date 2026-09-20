"""Avaliação da máquina na abertura.

O aviso só aparece quando o quadro é realmente ruim: interromper quem tem um
computador mediano seria só barulho. Estes testes prendem essa fronteira.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum.hardware import (
    Finding,
    HardwareInfo,
    MachineCheck,
    _worst,
    assess_machine,
)


def maquina(**kwargs) -> HardwareInfo:
    base = dict(
        has_cuda=False,
        cuda_device_count=0,
        gpu_name=None,
        gpu_vram_gb=None,
        cpu_count=8,
        ram_gb=16.0,
        platform="Windows 11 (AMD64)",
    )
    base.update(kwargs)
    return HardwareInfo(**base)  # type: ignore[arg-type]


@pytest.fixture()
def com_ffmpeg(monkeypatch):
    monkeypatch.setattr("vellum.hardware.resolve_tools", lambda: None)


@pytest.fixture()
def disco_cheio(monkeypatch):
    monkeypatch.setattr("vellum.hardware._free_disk_gb", lambda _p: 50.0)


# --------------------------------------------------------------------------- #
def test_o_pior_veredito_manda():
    assert _worst(["boa", "ok", "ruim", "boa"]) == "ruim"
    assert _worst(["boa", "boa"]) == "boa"
    assert _worst([]) == "boa"


def test_maquina_confortavel_nao_incomoda(com_ffmpeg, disco_cheio):
    check = assess_machine(maquina(cpu_count=12, ram_gb=32.0))

    assert check.level in ("boa", "ok")
    assert check.should_warn is False
    assert check.advice == [], "sem problema não há o que aconselhar"


def test_maquina_fraca_dispara_o_aviso(com_ffmpeg, disco_cheio):
    check = assess_machine(maquina(cpu_count=2, ram_gb=3.0))

    assert check.level == "ruim"
    assert check.should_warn is True
    assert "não vai dar conta" in check.headline


def test_o_aviso_aponta_os_controles_de_desempenho(com_ffmpeg, disco_cheio):
    """O usuário precisa saber que existe uma saída, não só que está ruim."""
    check = assess_machine(maquina(cpu_count=2, ram_gb=3.0))

    assert any("Desempenho" in conselho for conselho in check.advice)
    assert any("continuar assim mesmo" in conselho for conselho in check.advice)


def test_maquina_apertada_avisa_no_texto_mas_nao_interrompe(com_ffmpeg, disco_cheio):
    check = assess_machine(maquina(cpu_count=3, ram_gb=6.0))

    assert check.level == "apertada"
    assert check.should_warn is False, "lento não é motivo para parar o usuário"
    assert check.advice, "mesmo sem interromper, vale explicar o que fazer"


def test_sem_ffmpeg_o_veredito_e_ruim(monkeypatch, disco_cheio):
    def sem_ffmpeg():
        raise RuntimeError("nao achei")

    monkeypatch.setattr("vellum.hardware.resolve_tools", sem_ffmpeg)
    check = assess_machine(maquina(cpu_count=16, ram_gb=64.0))

    assert check.level == "ruim", "sem ffmpeg nada funciona, por melhor que seja a máquina"
    assert any("winget" in conselho for conselho in check.advice)


def test_pouco_disco_pesa_no_veredito(com_ffmpeg, monkeypatch):
    monkeypatch.setattr("vellum.hardware._free_disk_gb", lambda _p: 0.4)
    check = assess_machine(maquina(cpu_count=12, ram_gb=32.0))

    assert check.level == "ruim"
    assert any(a.item == "Espaço em disco" and a.level == "ruim" for a in check.findings)


def test_gpu_ausente_nao_e_defeito(com_ffmpeg, disco_cheio):
    """A maioria das máquinas não tem CUDA: isso é lentidão, não impedimento."""
    check = assess_machine(maquina(cpu_count=8, ram_gb=16.0))

    placa = next(a for a in check.findings if a.item == "Placa de vídeo")
    assert placa.level == "ok"
    assert check.should_warn is False


def test_gpu_boa_aparece_com_nome_e_memoria(com_ffmpeg, disco_cheio):
    check = assess_machine(
        maquina(has_cuda=True, cuda_device_count=1, gpu_name="RTX 4070", gpu_vram_gb=12.0)
    )

    placa = next(a for a in check.findings if a.item == "Placa de vídeo")
    assert "RTX 4070" in placa.value
    assert placa.level == "boa"


def test_disco_e_medido_na_pasta_que_existe(tmp_path: Path, com_ffmpeg):
    """A pasta de modelos pode ainda não existir na primeira execução."""
    check = assess_machine(maquina(), models_dir=tmp_path / "ainda" / "nao" / "existe")

    disco = next(a for a in check.findings if a.item == "Espaço em disco")
    assert "livres" in disco.value


def test_findings_e_check_sao_imutaveis():
    import dataclasses

    achado = Finding("CPU", "8 threads", "boa")
    check = MachineCheck(level="boa", headline="ok", findings=[achado], advice=[])
    with pytest.raises(dataclasses.FrozenInstanceError):
        achado.level = "ruim"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        check.level = "ruim"  # type: ignore[misc]


# ------------------------------------------ memória recomendada por job ----
def test_recomendacao_cresce_com_o_modelo():
    from vellum.hardware import recommended_for

    assert recommended_for("tiny").ram_gb < recommended_for("large-v3").ram_gb


def test_quem_fala_pesa_na_recomendacao():
    from vellum.hardware import DIARIZE_RAM_GB, recommended_for

    sem = recommended_for("small").ram_gb
    com = recommended_for("small", diarize=True).ram_gb
    assert com - sem == DIARIZE_RAM_GB


def test_o_ollama_vira_nota_e_nao_orcamento():
    from vellum.hardware import recommended_for

    pedido = recommended_for("small", summarize=True)
    assert pedido.ram_gb == recommended_for("small").ram_gb, "ele roda noutro processo"
    assert any("Ollama" in nota for nota in pedido.notes), "mas o usuário precisa saber"


def test_a_vram_pedida_inclui_a_reserva_do_cuda():
    from vellum.hardware import MODEL_MEMORY_GB, recommended_for

    pedido = recommended_for("medium")
    assert pedido.vram_gb > MODEL_MEMORY_GB["medium"]


def test_o_diagnostico_carrega_o_hardware_medido():
    from vellum.hardware import HardwareInfo, assess_machine

    hardware = HardwareInfo(
        has_cuda=False, cuda_device_count=0, gpu_name=None, gpu_vram_gb=None,
        cpu_count=8, ram_gb=16.0, platform="teste",
    )
    check = assess_machine(hardware=hardware)

    assert check.hardware is hardware, "a tela precisa disso sem redetectar"
