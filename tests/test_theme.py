"""Testes das paletas e da preferência de tema (sem abrir janela)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lauda import theme as theme_module
from lauda.theme import DARK, LIGHT, THEME_CHOICES, load_choice, resolve, save_choice


@pytest.fixture(autouse=True)
def prefs_in_tmp(tmp_path: Path, monkeypatch):
    """Nunca escrever no perfil real do usuário durante os testes."""
    monkeypatch.setattr(theme_module, "PREFS_PATH", tmp_path / "ui.json")


def test_paletas_tem_os_mesmos_campos():
    assert set(vars(LIGHT)) == set(vars(DARK))
    assert LIGHT.dark is False and DARK.dark is True


def test_paletas_nao_compartilham_cores_de_fundo():
    """Se fundo e texto forem iguais nos dois temas, algo ficou sem trocar."""
    assert LIGHT.canvas != DARK.canvas
    assert LIGHT.paper != DARK.paper
    assert LIGHT.ink != DARK.ink
    assert LIGHT.preview_bg != DARK.preview_bg


def test_todas_as_cores_sao_hexadecimais_validas():
    for palette in (LIGHT, DARK):
        for field, value in vars(palette).items():
            if field in ("name", "dark"):
                continue
            assert isinstance(value, str) and value.startswith("#"), (palette.name, field)
            assert len(value) == 7, (palette.name, field, value)
            int(value[1:], 16)  # levanta se não for hexadecimal


def test_resolve_por_nome():
    assert resolve("claro") is LIGHT
    assert resolve("escuro") is DARK


def test_resolve_auto_devolve_uma_paleta_valida(monkeypatch):
    monkeypatch.setattr(theme_module, "detect_system_theme", lambda: "escuro")
    assert resolve("auto") is DARK
    monkeypatch.setattr(theme_module, "detect_system_theme", lambda: "claro")
    assert resolve("auto") is LIGHT


def test_detect_system_theme_responde_um_valor_conhecido():
    assert theme_module.detect_system_theme() in ("claro", "escuro")


def test_preferencia_ida_e_volta():
    assert load_choice() == "auto", "sem arquivo, o padrão é seguir o sistema"
    save_choice("escuro")
    assert load_choice() == "escuro"
    save_choice("claro")
    assert load_choice() == "claro"


def test_preferencia_invalida_e_ignorada():
    save_choice("escuro")
    save_choice("roxo")  # não é uma opção
    assert load_choice() == "escuro"


def test_arquivo_corrompido_nao_derruba(tmp_path: Path):
    theme_module.PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    theme_module.PREFS_PATH.write_text("{isto não é json", encoding="utf-8")
    assert load_choice() == "auto"


def test_salvar_preserva_outras_chaves():
    theme_module.PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    theme_module.PREFS_PATH.write_text(
        json.dumps({"outra_coisa": 42}), encoding="utf-8"
    )
    save_choice("escuro")
    data = json.loads(theme_module.PREFS_PATH.read_text(encoding="utf-8"))
    assert data["outra_coisa"] == 42
    assert data["theme"] == "escuro"


def test_choices_documentadas():
    assert THEME_CHOICES == ("auto", "claro", "escuro")
