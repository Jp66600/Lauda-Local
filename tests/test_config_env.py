"""Os prefixos de variável de ambiente, incluindo os dos nomes antigos.

O programa já se chamou MediaIntel Local e Vellum. Quem montou um `.env` naquela
época não pode ver suas escolhas deixarem de valer porque o produto mudou de
nome.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lauda.config import ENV_PREFIX, LEGACY_ENV_PREFIXES, _env


def test_o_prefixo_atual_e_lauda():
    assert ENV_PREFIX == "LAUDA_"


def test_le_o_prefixo_atual(monkeypatch):
    monkeypatch.setenv("LAUDA_MODEL", "medium")
    assert _env("MODEL", "small") == "medium"


def test_ainda_le_o_prefixo_do_vellum(monkeypatch):
    monkeypatch.delenv("LAUDA_MODEL", raising=False)
    monkeypatch.setenv("VELLUM_MODEL", "large-v3")
    assert _env("MODEL", "small") == "large-v3"


def test_ainda_le_o_prefixo_do_mediaintel(monkeypatch):
    monkeypatch.delenv("LAUDA_MODEL", raising=False)
    monkeypatch.delenv("VELLUM_MODEL", raising=False)
    monkeypatch.setenv("MEDIAINTEL_MODEL", "base")
    assert _env("MODEL", "small") == "base"


def test_o_nome_atual_ganha_do_antigo(monkeypatch):
    monkeypatch.setenv("LAUDA_MODEL", "medium")
    monkeypatch.setenv("VELLUM_MODEL", "tiny")
    monkeypatch.setenv("MEDIAINTEL_MODEL", "base")
    assert _env("MODEL", "small") == "medium"


def test_o_mais_recente_dos_antigos_ganha(monkeypatch):
    monkeypatch.delenv("LAUDA_MODEL", raising=False)
    monkeypatch.setenv("VELLUM_MODEL", "tiny")
    monkeypatch.setenv("MEDIAINTEL_MODEL", "base")
    assert _env("MODEL", "small") == "tiny"


def test_sem_nenhum_deles_vale_o_padrao(monkeypatch):
    for prefixo in (ENV_PREFIX, *LEGACY_ENV_PREFIXES):
        monkeypatch.delenv(prefixo + "MODEL", raising=False)
    assert _env("MODEL", "small") == "small"


def test_valor_vazio_e_respeitado_e_nao_cai_para_o_antigo(monkeypatch):
    """`LAUDA_X=` é uma escolha explícita de "vazio", não ausência."""
    monkeypatch.setenv("LAUDA_MODEL", "")
    monkeypatch.setenv("VELLUM_MODEL", "tiny")
    assert _env("MODEL", "small") == ""
