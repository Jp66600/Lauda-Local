"""Testes da contabilidade de disco."""

from __future__ import annotations

from pathlib import Path

from vellum.disk import (
    component_sizes,
    format_size,
    installed_models,
    remove_model,
    site_packages,
    tree_size,
)


def _modelo(models_dir: Path, nome: str, tamanho: int) -> Path:
    pasta = models_dir / nome / "snapshots" / "abc"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "model.bin").write_bytes(b"\0" * tamanho)
    return pasta


# --------------------------------------------------------------------------- #
# Formatação
# --------------------------------------------------------------------------- #
def test_tamanho_em_portugues():
    assert format_size(512) == "512 B"
    assert format_size(1536) == "1,5 KB"
    assert format_size(5 * 1024**3) == "5,0 GB"


def test_pasta_inexistente_vale_zero(tmp_path: Path):
    assert tree_size(tmp_path / "nao-existe") == 0


def test_soma_recursiva(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.bin").write_bytes(b"\0" * 1000)
    (tmp_path / "y.bin").write_bytes(b"\0" * 500)
    assert tree_size(tmp_path) == 1500


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
def test_lista_modelos_do_maior_para_o_menor(tmp_path: Path):
    _modelo(tmp_path, "models--Systran--faster-whisper-small", 3000)
    _modelo(tmp_path, "models--Systran--faster-whisper-tiny", 1000)

    modelos = installed_models(tmp_path)

    assert [nome for nome, _ in modelos] == [
        "faster-whisper-small",
        "faster-whisper-tiny",
    ]
    assert modelos[0][1] > modelos[1][1]


def test_remover_por_apelido(tmp_path: Path):
    """O usuário digita "small", não o nome completo do cache."""
    _modelo(tmp_path, "models--Systran--faster-whisper-small", 3000)
    _modelo(tmp_path, "models--Systran--faster-whisper-tiny", 1000)

    apagados, liberado = remove_model(tmp_path, "small")

    assert apagados == ["models--Systran--faster-whisper-small"]
    assert liberado == 3000
    assert [nome for nome, _ in installed_models(tmp_path)] == ["faster-whisper-tiny"]


def test_remover_o_que_nao_existe_nao_quebra(tmp_path: Path):
    _modelo(tmp_path, "models--Systran--faster-whisper-tiny", 1000)
    apagados, liberado = remove_model(tmp_path, "medium")
    assert apagados == [] and liberado == 0
    assert installed_models(tmp_path), "não pode ter apagado o que estava lá"


def test_remover_de_pasta_inexistente(tmp_path: Path):
    assert remove_model(tmp_path / "vazio", "small") == ([], 0)


# --------------------------------------------------------------------------- #
# Componentes
# --------------------------------------------------------------------------- #
def test_componentes_incluem_modelos_e_pontos(tmp_path: Path):
    modelos = tmp_path / "models"
    pontos = tmp_path / "checkpoints"
    _modelo(modelos, "models--Systran--faster-whisper-small", 2000)
    (pontos / "abc").mkdir(parents=True)
    (pontos / "abc" / "state.json").write_bytes(b"\0" * 700)

    linhas = component_sizes(modelos, pontos)
    nomes = [nome for nome, _, _ in linhas]

    assert "modelos de transcrição baixados" in nomes
    assert "pontos de retomada" in nomes
    tamanhos = [tamanho for _, tamanho, _ in linhas]
    assert tamanhos == sorted(tamanhos, reverse=True), "maiores primeiro"


def test_componentes_dizem_o_que_da_para_remover(tmp_path: Path):
    linhas = component_sizes(tmp_path / "models", tmp_path / "cp")
    for nome, _, nota in linhas:
        assert nota, f"{nome} sem explicação de remoção"
        if "núcleo" in nome:
            assert nota.startswith("não"), "o núcleo não pode ser anunciado como removível"


def test_encontra_o_site_packages_do_ambiente():
    pasta = site_packages()
    assert pasta is None or pasta.name == "site-packages"
