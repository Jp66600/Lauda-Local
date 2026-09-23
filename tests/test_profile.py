"""Migração do perfil do nome antigo (BACKLOG-044).

O programa se chamava MediaIntel Local. Quem testou aquela versão não pode
perder tema, limites, opções e histórico só porque o produto virou Lauda Local.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lauda.profile import migrate_legacy_profile


def _perfil_antigo(base: Path) -> Path:
    antiga = base / ".mediaintel"
    (antiga / "checkpoints" / "abc123").mkdir(parents=True)
    (antiga / "logs").mkdir()
    (antiga / "ui.json").write_text(json.dumps({"theme": "escuro"}), encoding="utf-8")
    (antiga / "history.json").write_text(json.dumps([{"file_name": "a.wav"}]), encoding="utf-8")
    (antiga / "checkpoints" / "abc123" / "estado.json").write_text("{}", encoding="utf-8")
    (antiga / "logs" / "mediaintel.log").write_text("linha velha", encoding="utf-8")
    return antiga


def test_traz_preferencias_historico_e_pontos_de_retomada(tmp_path: Path):
    antiga = _perfil_antigo(tmp_path)
    nova = tmp_path / ".lauda"

    veio_de = migrate_legacy_profile(nova, (antiga,))

    assert veio_de == antiga
    assert json.loads((nova / "ui.json").read_text(encoding="utf-8")) == {"theme": "escuro"}
    assert (nova / "history.json").exists()
    assert (nova / "checkpoints" / "abc123" / "estado.json").exists()


def test_nao_traz_o_log_do_nome_antigo(tmp_path: Path):
    """Log velho não serve para diante e é o que mais ocupa espaço."""
    antiga = _perfil_antigo(tmp_path)
    nova = tmp_path / ".lauda"

    migrate_legacy_profile(nova, (antiga,))

    assert not (nova / "logs").exists()


def test_a_pasta_antiga_continua_intacta(tmp_path: Path):
    antiga = _perfil_antigo(tmp_path)

    migrate_legacy_profile(tmp_path / ".lauda", (antiga,))

    assert (antiga / "ui.json").exists(), "copiar, não mover: a versão antiga ainda roda"


def test_nao_sobrescreve_o_que_ja_existe_no_perfil_novo(tmp_path: Path):
    antiga = _perfil_antigo(tmp_path)
    nova = tmp_path / ".lauda"
    nova.mkdir()
    (nova / "ui.json").write_text(json.dumps({"theme": "claro"}), encoding="utf-8")

    migrate_legacy_profile(nova, (antiga,))

    assert json.loads((nova / "ui.json").read_text(encoding="utf-8")) == {"theme": "claro"}
    assert (nova / "history.json").exists(), "o que faltava ainda vem"


def test_pasta_nova_criada_pelo_log_nao_bloqueia_a_migracao(tmp_path: Path):
    """O log e os pontos de retomada nascem antes; a pasta nunca esta vazia.

    Foi assim que a migracao deixou de rodar de verdade: olhando so para "a
    pasta nova existe?", o usuario perdia tema, limites e historico calado.
    """
    antiga = _perfil_antigo(tmp_path)
    nova = tmp_path / ".lauda"
    (nova / "logs").mkdir(parents=True)
    (nova / "logs" / "lauda.log").write_text("linha", encoding="utf-8")
    (nova / "checkpoints").mkdir()

    assert migrate_legacy_profile(nova, (antiga,)) == antiga
    assert (nova / "ui.json").exists(), "o perfil tem de vir mesmo assim"
    assert (nova / "history.json").exists()


def test_nada_pendente_nao_faz_nada(tmp_path: Path):
    antiga = _perfil_antigo(tmp_path)
    nova = tmp_path / ".lauda"
    migrate_legacy_profile(nova, (antiga,))

    assert migrate_legacy_profile(nova, (antiga,)) is None, "a segunda vez e sem efeito"


def test_sem_perfil_antigo_nao_faz_nada(tmp_path: Path):
    assert migrate_legacy_profile(tmp_path / ".lauda", (tmp_path / ".mediaintel",)) is None
    assert not (tmp_path / ".lauda").exists()


def test_pasta_antiga_vazia_nao_conta(tmp_path: Path):
    (tmp_path / ".mediaintel").mkdir()

    assert migrate_legacy_profile(tmp_path / ".lauda", (tmp_path / ".mediaintel",)) is None


def test_falha_de_escrita_nao_derruba_a_abertura(tmp_path: Path, monkeypatch):
    antiga = _perfil_antigo(tmp_path)

    def explode(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr("lauda.profile.shutil.copy2", explode)

    assert migrate_legacy_profile(tmp_path / ".lauda", (antiga,)) is None


def test_pontos_de_retomada_antigos_sao_mesclados(tmp_path: Path):
    """Trabalho interrompido na versão antiga continua retomável na nova."""
    antiga = _perfil_antigo(tmp_path)
    nova = tmp_path / ".lauda"
    (nova / "checkpoints" / "novo").mkdir(parents=True)

    migrate_legacy_profile(nova, (antiga,))

    assert (nova / "checkpoints" / "abc123" / "estado.json").exists(), "veio o antigo"
    assert (nova / "checkpoints" / "novo").exists(), "e o novo continua lá"


# ------------------------------------------------------- ícone da janela ---
def test_o_icone_e_achado_no_codigo_fonte():
    from lauda.profile import icon_path

    assert icon_path().exists(), "sem o .ico a janela fica com a pena do Tk"
    assert icon_path().name == "lauda.ico"


def test_no_pacote_o_icone_vem_de_dentro_do_executavel(monkeypatch, tmp_path: Path):
    import sys as _sys

    from lauda import profile

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "_MEIPASS", str(tmp_path), raising=False)

    assert profile.icon_path() == tmp_path / "assets" / "lauda.ico"


def test_no_pacote_os_modelos_ficam_no_perfil(monkeypatch, tmp_path: Path):
    """Desinstalar e reinstalar não pode obrigar a baixar 500 MB de novo."""
    import sys as _sys

    from lauda import profile

    monkeypatch.setattr(profile, "DATA_DIR", tmp_path / ".lauda")
    monkeypatch.setattr(_sys, "frozen", True, raising=False)

    assert profile.models_dir() == tmp_path / ".lauda" / "models"


def test_no_codigo_fonte_os_modelos_ficam_no_projeto(monkeypatch):
    import sys as _sys

    from lauda import profile

    monkeypatch.delattr(_sys, "frozen", raising=False)

    assert profile.models_dir().name == "models"
    assert (profile.models_dir().parent / "pyproject.toml").exists()


# ------------------------------------------------ os dois nomes anteriores --
def test_prefere_o_perfil_mais_recente_quando_ha_dois(tmp_path: Path):
    """Quem passou por MediaIntel Local e por Vellum tem duas pastas antigas.

    A escolha certa é a mais recente: é nela que estão as últimas preferências.
    """
    velha = _perfil_antigo(tmp_path)                     # .mediaintel
    media = tmp_path / ".vellum"
    media.mkdir()
    (media / "ui.json").write_text(json.dumps({"theme": "claro"}), encoding="utf-8")
    nova = tmp_path / ".lauda"

    veio_de = migrate_legacy_profile(nova, (media, velha))

    assert veio_de == media
    assert json.loads((nova / "ui.json").read_text(encoding="utf-8")) == {"theme": "claro"}


def test_cai_para_o_nome_mais_antigo_se_o_do_meio_nao_existe(tmp_path: Path):
    velha = _perfil_antigo(tmp_path)                     # .mediaintel
    nova = tmp_path / ".lauda"

    veio_de = migrate_legacy_profile(nova, (tmp_path / ".vellum", velha))

    assert veio_de == velha
    assert (nova / "ui.json").exists()

