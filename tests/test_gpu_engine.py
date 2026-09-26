"""O segundo motor: quando ele entra, quando ele fica de fora, e por quê.

A decisão "placa ou processador" não tem resposta única — depende do silício de
cada máquina. Estes testes não medem velocidade (isso é trabalho do
`gpu_bench`); eles garantem que a escolha **obedece à medição** e que, sem
medição, o programa fica no caminho que sabidamente funciona.
"""

from __future__ import annotations

import pytest

from lauda import gpu_bench, onnx_engine
from lauda.gpus import Gpu
from lauda.hardware import HardwareInfo, select_runtime


@pytest.fixture
def com_directml(monkeypatch):
    """Finge que o DirectML está instalado.

    A escolha do motor precisa ser testável onde ele NÃO existe — a integração
    contínua roda no Linux, e o DirectML é do Windows. Sem isto, metade destes
    testes passaria aqui e seria pulada em silêncio lá, que é a pior das duas.
    """
    monkeypatch.setattr(onnx_engine, "available", lambda: (True, ""))


RADEON = Gpu("amd", "AMD Radeon RX 7800 XT", 16.0, False)
INTEL = Gpu("intel", "Intel(R) UHD Graphics 630", 1.0, True)
GEFORCE = Gpu("nvidia", "NVIDIA GeForce RTX 3060", 12.0, False)


def _maquina(placas, *, cuda=False):
    return HardwareInfo(
        has_cuda=cuda, cuda_device_count=1 if cuda else 0,
        gpu_name=placas[0].name if (cuda and placas) else None,
        gpu_vram_gb=placas[0].vram_gb if (cuda and placas) else None,
        cpu_count=12, ram_gb=16.0, platform="teste",
        gpus=tuple(placas), physical_cores=6,
    )


def _medicao(placa: Gpu, *, placa_ganha: bool, model="small"):
    gpu_bench.save(gpu_bench.BenchResult(
        gpu=placa.name, model=model,
        onnx_speed=9.0 if placa_ganha else 3.0,
        ctranslate2_speed=3.0 if placa_ganha else 9.0,
        measured_at="2026-09-25 21:00",
    ))


# --------------------------------------------------- o que tem build em ONNX --
def test_so_os_modelos_com_build_publicado_entram():
    """Trocar o modelo por um parecido seria mudar a qualidade sem avisar."""
    assert onnx_engine.supported_model("small")
    assert onnx_engine.supported_model("large-v3-turbo")
    assert onnx_engine.supported_model("large-v3") is None
    assert onnx_engine.supported_model("medium") is None


def test_a_indisponibilidade_vem_com_motivo():
    """"Não deu" sem motivo é o que transforma defeito simples em mistério."""
    pronto, motivo = onnx_engine.available()
    assert pronto or motivo, "quando não dá, tem de dizer por quê"
    if not pronto:
        assert motivo.endswith(".") or ")" in motivo


# ------------------------------------------------ quem decide é a medição --
def test_sem_medicao_o_trabalho_fica_no_processador(com_directml):
    """Ligar a placa no escuro pode deixar MAIS lento. Medido: 8,3x contra 5,1x."""
    escolha = select_runtime(requested_model="small", hardware=_maquina([RADEON]))

    assert escolha.engine == "ctranslate2"
    assert escolha.device == "cpu"


def test_com_a_placa_ganhando_o_trabalho_vai_para_ela(com_directml):
    _medicao(RADEON, placa_ganha=True)

    escolha = select_runtime(requested_model="small", hardware=_maquina([RADEON]))

    assert escolha.engine == "onnx"
    assert escolha.device == "dml"
    assert escolha.device_name == RADEON.name
    assert escolha.compute_type == "float16"
    assert escolha.on_gpu


def test_com_o_processador_ganhando_a_placa_fica_de_fora(com_directml):
    _medicao(RADEON, placa_ganha=False)

    escolha = select_runtime(requested_model="small", hardware=_maquina([RADEON]))

    assert escolha.engine == "ctranslate2"
    assert escolha.device == "cpu"


def test_a_medicao_e_por_placa_e_por_modelo(com_directml):
    """Trocar o modelo muda a conta: o que vale para o small não vale para o turbo."""
    _medicao(RADEON, placa_ganha=True, model="small")

    assert select_runtime(
        requested_model="small", hardware=_maquina([RADEON])
    ).engine == "onnx"
    assert select_runtime(
        requested_model="large-v3-turbo", hardware=_maquina([RADEON])
    ).engine == "ctranslate2", "modelo sem medição não herda a do outro"


# ------------------------------------------- as máquinas que nem chegam lá --
def test_nvidia_funcionando_continua_no_motor_principal(com_directml):
    """O CTranslate2 em CUDA é mais rápido que qualquer coisa via DirectML."""
    _medicao(GEFORCE, placa_ganha=True)

    escolha = select_runtime(requested_model="small", hardware=_maquina([GEFORCE], cuda=True))

    assert escolha.engine == "ctranslate2"
    assert escolha.device == "cuda"


def test_pedir_processador_explicitamente_manda_mais_que_a_medicao(com_directml):
    _medicao(RADEON, placa_ganha=True)

    escolha = select_runtime(
        requested_device="cpu", requested_model="small", hardware=_maquina([RADEON])
    )

    assert escolha.engine == "ctranslate2"


def test_gpu_desligada_nos_limites_desliga_tambem_a_placa_amd(com_directml):
    """"GPU em 0%" quer dizer "não use placa nenhuma", não "não use CUDA"."""
    from lauda.limits import ResourceLimits

    _medicao(RADEON, placa_ganha=True)

    escolha = select_runtime(
        requested_model="small", hardware=_maquina([RADEON]),
        limits=ResourceLimits(gpu_percent=0),
    )

    assert escolha.engine == "ctranslate2"
    assert escolha.device == "cpu"


def test_modelo_sem_build_onnx_fica_no_processador(com_directml):
    _medicao(RADEON, placa_ganha=True, model="large-v3")

    escolha = select_runtime(requested_model="large-v3", hardware=_maquina([RADEON]))

    assert escolha.engine == "ctranslate2"


def test_maquina_sem_placa_nenhuma_nao_tenta_o_segundo_motor(com_directml):
    escolha = select_runtime(requested_model="small", hardware=_maquina([]))

    assert escolha.engine == "ctranslate2"


# --------------------------------------------------------- o resultado medido --
def test_o_vencedor_sai_da_comparacao_e_nao_de_um_padrao():
    ganha_placa = gpu_bench.BenchResult("RX", "small", 9.0, 3.0, "hoje")
    ganha_cpu = gpu_bench.BenchResult("RX", "small", 3.0, 9.0, "hoje")

    assert ganha_placa.winner == "onnx"
    assert ganha_cpu.winner == "ctranslate2"
    assert ganha_placa.advantage == pytest.approx(3.0)
    assert ganha_cpu.advantage == pytest.approx(3.0)


def test_a_frase_do_resultado_diz_quem_ganhou_e_por_quanto():
    frase = gpu_bench.BenchResult("RX 7800", "small", 9.0, 3.0, "hoje").describe()
    assert "RX 7800" in frase and "3.0x mais rápida" in frase

    frase = gpu_bench.BenchResult("RX 7800", "small", 3.0, 9.0, "hoje").describe()
    assert "processador é 3.0x mais rápido" in frase
    assert "fica de fora" in frase


def test_a_medicao_sobrevive_a_gravacao_e_a_leitura():
    original = gpu_bench.BenchResult("RX 7800", "small", 9.25, 3.5, "2026-09-25 21:00")
    gpu_bench.save(original)

    relido = gpu_bench.load("RX 7800", "small")

    assert relido is not None
    assert relido.winner == original.winner
    assert relido.onnx_speed == pytest.approx(9.25)
    assert relido.measured_at == "2026-09-25 21:00"


def test_perfil_estragado_nao_derruba_a_leitura_da_medicao():
    from lauda import theme

    theme.save_value(gpu_bench.BENCH_KEY, "isto deveria ser um dicionário")
    assert gpu_bench.load("RX 7800", "small") is None

    theme.save_value(gpu_bench.BENCH_KEY, {"RX 7800|small": {"gpu": "RX 7800"}})
    assert gpu_bench.load("RX 7800", "small") is None, "faltando campo, vale nada"


# ------------------------------------------------- o que este motor não faz --
def test_as_limitacoes_estao_declaradas():
    """Elas viram aviso no laudo. Some em silêncio é o que não pode."""
    assert any("palavra" in item for item in onnx_engine.LIMITACOES)


def test_a_janela_do_whisper_nao_muda():
    """O encoder exige exatamente 30 s; mexer aqui quebra o modelo."""
    assert onnx_engine.WINDOW_SECONDS == 30
    assert onnx_engine.SAMPLE_RATE == 16000


def test_sem_directml_instalado_o_programa_segue_no_processador(monkeypatch):
    """É o caso de todo Linux e de todo macOS. Não é defeito, é ausência."""
    monkeypatch.setattr(
        onnx_engine, "available", lambda: (False, "onnxruntime sem DirectML.")
    )
    _medicao(RADEON, placa_ganha=True)

    escolha = select_runtime(requested_model="small", hardware=_maquina([RADEON]))

    assert escolha.engine == "ctranslate2"
    assert escolha.device == "cpu"
