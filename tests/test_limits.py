"""Testes dos limites de uso de máquina."""

from __future__ import annotations

import pytest

from lauda.config import JobOptions
from lauda.hardware import HardwareInfo, memory_budget_gb, select_runtime
from lauda.limits import DEFAULT, ResourceLimits, from_dict, load, save

HARDWARE = HardwareInfo(
    has_cuda=True,
    cuda_device_count=1,
    gpu_name="GPU de teste",
    gpu_vram_gb=8.0,
    cpu_count=12,
    ram_gb=32.0,
    platform="teste",
)


# --------------------------------------------------------------------------- #
# Validação
# --------------------------------------------------------------------------- #
def test_padrao_e_maquina_inteira():
    assert DEFAULT.cpu_percent == 100
    assert DEFAULT.use_gpu is True
    assert DEFAULT.is_default


@pytest.mark.parametrize("campo", ["cpu_percent", "ram_percent", "vram_percent"])
def test_recusa_porcentagem_fora_da_faixa(campo):
    with pytest.raises(ValueError):
        ResourceLimits(**{campo: 5})
    with pytest.raises(ValueError):
        ResourceLimits(**{campo: 101})


def test_gpu_aceita_zero_porque_zero_significa_desligar():
    limites = ResourceLimits(gpu_percent=0)
    assert limites.use_gpu is False
    with pytest.raises(ValueError):
        ResourceLimits(gpu_percent=-1)


# --------------------------------------------------------------------------- #
# CPU
# --------------------------------------------------------------------------- #
def test_cpu_vira_numero_de_threads():
    assert ResourceLimits(cpu_percent=100).cpu_threads(12) == 12
    assert ResourceLimits(cpu_percent=50).cpu_threads(12) == 6
    assert ResourceLimits(cpu_percent=25).cpu_threads(12) == 3


def test_cpu_nunca_chega_a_zero_threads():
    assert ResourceLimits(cpu_percent=10).cpu_threads(2) == 1
    assert ResourceLimits(cpu_percent=10).cpu_threads(1) == 1


def test_paralelismo_da_gpu_diminui_com_o_limite():
    assert ResourceLimits(gpu_percent=100).gpu_workers() == 2
    assert ResourceLimits(gpu_percent=30).gpu_workers() == 1


# --------------------------------------------------------------------------- #
# Memória: o limite precisa mudar o modelo escolhido
# --------------------------------------------------------------------------- #
def test_vram_limitada_reduz_o_orcamento():
    cheio = memory_budget_gb(HARDWARE, "cuda", ResourceLimits(vram_percent=100))
    metade = memory_budget_gb(HARDWARE, "cuda", ResourceLimits(vram_percent=50))
    assert metade == pytest.approx(4.0)
    assert metade < cheio


def test_ram_limitada_reduz_o_orcamento():
    assert memory_budget_gb(HARDWARE, "cpu", ResourceLimits(ram_percent=25)) == pytest.approx(8.0)
    assert memory_budget_gb(HARDWARE, "cpu", ResourceLimits(ram_percent=75)) == pytest.approx(24.0)


def test_limite_de_vram_rebaixa_o_modelo():
    """É este o efeito prático do slider: um modelo que não cabe não é usado."""
    solto = select_runtime(
        requested_model="large-v3", hardware=HARDWARE, limits=ResourceLimits()
    )
    apertado = select_runtime(
        requested_model="large-v3", hardware=HARDWARE, limits=ResourceLimits(vram_percent=20)
    )
    assert solto.model == "large-v3", "com 8 GB livres o large cabe"
    assert apertado.model != "large-v3", "com 20% de 8 GB ele não cabe"
    assert any("rebaixado" in nota for nota in apertado.notes)


def test_gpu_em_zero_forca_cpu():
    escolha = select_runtime(
        requested_device="cuda", hardware=HARDWARE, limits=ResourceLimits(gpu_percent=0)
    )
    assert escolha.device == "cpu"
    assert any("GPU desligada" in nota for nota in escolha.notes)


# --------------------------------------------------------------------------- #
# Integração com as opções do job
# --------------------------------------------------------------------------- #
def test_opcoes_usam_os_limites(tmp_path):
    opcoes = JobOptions(
        input_path=tmp_path,
        output_dir=tmp_path,
        limits=ResourceLimits(cpu_percent=50, gpu_percent=0),
        device="cuda",
    )
    assert opcoes.effective_device == "cpu", "GPU em 0% vence o device pedido"
    assert opcoes.effective_cpu_threads == ResourceLimits(cpu_percent=50).cpu_threads()


def test_threads_explicitas_vencem_a_porcentagem(tmp_path):
    opcoes = JobOptions(
        input_path=tmp_path, output_dir=tmp_path, cpu_threads=2,
        limits=ResourceLimits(cpu_percent=100),
    )
    assert opcoes.effective_cpu_threads == 2


# --------------------------------------------------------------------------- #
# Persistência
# --------------------------------------------------------------------------- #
def test_limites_ficam_guardados():
    assert load().is_default
    save(ResourceLimits(cpu_percent=40, ram_percent=30, gpu_percent=0, vram_percent=60))
    lidos = load()
    assert (lidos.cpu_percent, lidos.ram_percent, lidos.gpu_percent, lidos.vram_percent) == (
        40, 30, 0, 60
    )


def test_arquivo_corrompido_volta_ao_padrao():
    from lauda import theme

    theme.PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    theme.PREFS_PATH.write_text("{quebrado", encoding="utf-8")
    assert load().is_default


def test_from_dict_ignora_lixo():
    limites = from_dict({"cpu_percent": 30, "campo_inexistente": 1})
    assert limites.cpu_percent == 30
    assert from_dict(None).is_default


def test_descricao_em_portugues():
    texto = ResourceLimits(cpu_percent=25, gpu_percent=0).describe()
    assert "CPU 25%" in texto
    assert "GPU desligada" in texto


# ------------------------------------------------------------- presets ----
def test_os_quatro_presets_existem_e_sao_distintos():
    from lauda.limits import PRESETS

    chaves = [p.key for p in PRESETS]
    assert chaves == ["leve", "equilibrado", "rapido", "maximo"]
    assert len({p.limits for p in PRESETS}) == 4, "preset que repete limite é decoração"


def test_preset_leve_desliga_a_gpu_e_segura_a_cpu():
    from lauda.limits import preset_by_key

    leve = preset_by_key("leve")
    assert leve is not None
    assert leve.limits.use_gpu is False, "leve tem de devolver a máquina ao usuário"
    assert leve.limits.cpu_percent <= 30


def test_preset_rapido_e_o_padrao_de_fabrica():
    from lauda.limits import DEFAULT, preset_by_key

    rapido = preset_by_key("rapido")
    assert rapido is not None and rapido.limits == DEFAULT


def test_reconhece_o_preset_em_vigor():
    from lauda.limits import PRESETS, preset_for

    for preset in PRESETS:
        achado = preset_for(preset.limits)
        assert achado is not None and achado.key == preset.key


def test_ajuste_manual_nao_casa_com_preset():
    from lauda.limits import ResourceLimits, preset_for

    assert preset_for(ResourceLimits(cpu_percent=37, ram_percent=41)) is None


def test_chave_desconhecida_devolve_nada():
    from lauda.limits import preset_by_key

    assert preset_by_key("turbo") is None


def test_cada_preset_explica_o_que_faz():
    from lauda.limits import PRESETS

    for preset in PRESETS:
        assert len(preset.blurb) > 30, f"{preset.key} sem explicação em português"
        assert "%" not in preset.blurb, "o resumo não pode falar em porcentagem"
