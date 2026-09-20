"""A pasta de dados do usuário — e a migração do nome antigo (BACKLOG-044).

Tudo que é do usuário mora em `~/.vellum`: preferências, histórico, pontos de
retomada e logs. Fica fora da pasta do programa de propósito, para sobreviver a
desinstalar, reinstalar ou mover o aplicativo.

O programa já se chamou **MediaIntel Local**, e quem testou aquela versão tem um
`~/.mediaintel` cheio de escolhas. Trocar o nome não pode significar começar do
zero, então na primeira abertura o perfil antigo é **copiado** para o novo.

Copiado, não movido: se a pessoa voltar para a versão antiga, ela continua
funcionando. Apagar a pasta velha é decisão dela, não nossa.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger("vellum.profile")

#: Onde ficam preferências, histórico, pontos de retomada e logs.
DATA_DIR = Path.home() / ".vellum"

#: Nomes anteriores do produto, do mais recente para o mais antigo.
LEGACY_DIRS: tuple[Path, ...] = (Path.home() / ".mediaintel",)

#: O que vale a pena trazer. Log do nome antigo não serve para nada daqui em
#: diante, e é o que mais ocupa espaço.
MIGRATED = ("ui.json", "history.json", "checkpoints")


def models_dir() -> Path:
    """Onde os modelos de transcrição ficam.

    No aplicativo empacotado eles vão para o perfil do usuário, não para a
    pasta do programa: assim desinstalar, reinstalar ou atualizar não obriga a
    baixar de novo os 500 MB. Rodando do código-fonte, continuam na pasta
    `models` do projeto, que é onde já estão.
    """
    if getattr(sys, "frozen", False):
        return DATA_DIR / "models"
    return Path(__file__).resolve().parents[2] / "models"


def icon_path() -> Path:
    """O `.ico` da janela, no código-fonte e dentro do executável.

    Sem ele o Windows desenha a pena do Tk na barra de título e na barra de
    tarefas — o programa fica com a cara de "script solto", que foi exatamente
    o que o QA viu. No pacote os dados vão para `_internal`, não para a pasta
    do projeto, que lá não existe.
    """
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else None
    raiz = base or Path(__file__).resolve().parents[2]
    return raiz / "assets" / "vellum.ico"


def _has_content(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:  # pragma: no cover - pasta sem permissão
        return False


def migrate_legacy_profile(
    data_dir: Path | None = None, legacy_dirs: tuple[Path, ...] | None = None
) -> Path | None:
    """Traz do nome antigo o que ainda não existe no novo.

    A decisão é **item a item**, não "a pasta nova está vazia?". A pasta nova
    quase nunca está: o log é aberto antes disto, e o processo de trabalho cria
    `logs/` e `checkpoints/` sozinho. Olhar só para a pasta faria a migração
    parecer feita e o usuário perder tema, limites e histórico em silêncio —
    que é exatamente o que ela existe para evitar.

    Devolve a pasta de onde veio, ou `None` se não havia nada a trazer. Nunca
    levanta exceção: falhar a migração é ruim, não abrir é pior.
    """
    destino = data_dir or DATA_DIR

    for antiga in legacy_dirs or LEGACY_DIRS:
        if not _has_content(antiga):
            continue
        try:
            trazidos = [
                nome for nome in MIGRATED
                if (antiga / nome).exists() and _copiar(antiga / nome, destino / nome)
            ]
        except OSError as exc:
            log.warning("Não consegui trazer o perfil de %s: %s", antiga, exc)
            return None
        if trazidos:
            log.info(
                "Perfil trazido de %s para %s (%s). A pasta antiga foi mantida.",
                antiga, destino, ", ".join(trazidos),
            )
            return antiga
    return None


def _copiar(origem: Path, alvo: Path) -> bool:
    """Copia o que falta, sem sobrescrever nada. Diz se trouxe alguma coisa.

    Pasta é mesclada filho a filho: `checkpoints` já existe no destino (o
    processo de trabalho a cria), e sobrescrevê-la inteira jogaria fora as
    retomadas — que são justamente os trabalhos interrompidos que a migração
    deveria preservar.
    """
    if origem.is_dir():
        trouxe = False
        for filho in sorted(origem.iterdir()):
            destino_filho = alvo / filho.name
            if destino_filho.exists():
                continue
            alvo.mkdir(parents=True, exist_ok=True)
            if filho.is_dir():
                shutil.copytree(filho, destino_filho)
            else:
                shutil.copy2(filho, destino_filho)
            trouxe = True
        return trouxe
    if alvo.exists():
        return False
    alvo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, alvo)
    return True
