"""Log em arquivo.

O aplicativo de janela roda sem console. Se o log não chegar ao disco, um erro
na máquina de outra pessoa não deixa rastro nenhum — que é justamente o caso em
que a informação faz falta.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest


@pytest.fixture()
def logging_isolado(tmp_path: Path, monkeypatch):
    """Recarrega o módulo apontando o log para uma pasta descartável."""
    monkeypatch.setenv("LAUDA_LOG_DIR", str(tmp_path / "logs"))
    from lauda import logging_setup

    modulo = importlib.reload(logging_setup)
    raiz = logging.getLogger()
    handlers_antes = list(raiz.handlers)
    nivel_antes = raiz.level
    raiz.handlers = []
    try:
        yield modulo
    finally:
        for handler in list(raiz.handlers):
            handler.close()
        raiz.handlers = handlers_antes
        raiz.setLevel(nivel_antes)
        importlib.reload(logging_setup)


def _configurar(modulo, **kwargs):
    """Chama o setup com a raiz limpa.

    O `basicConfig` do Python só age quando o logger raiz ainda não tem
    handler — e o pytest instala o dele a cada teste. Em produção a raiz está
    vazia, então limpar aqui reproduz a situação real.
    """
    logging.getLogger().handlers = []
    return modulo.setup_logging(**kwargs)


def test_o_log_vai_para_o_arquivo(logging_isolado):
    log = _configurar(logging_isolado, quiet=True)
    log.info("mensagem de teste")

    conteudo = logging_isolado.LOG_PATH.read_text(encoding="utf-8")
    assert "mensagem de teste" in conteudo


def test_o_arquivo_guarda_debug_mesmo_no_modo_silencioso(logging_isolado):
    """Na tela o modo silencioso esconde; no arquivo tem de ficar tudo."""
    log = _configurar(logging_isolado, quiet=True)
    log.debug("detalhe que só interessa depois do problema")

    conteudo = logging_isolado.LOG_PATH.read_text(encoding="utf-8")
    assert "detalhe que só interessa" in conteudo


def test_falha_ao_criar_a_pasta_nao_derruba_o_app(logging_isolado, monkeypatch):
    def sem_permissao(*_args, **_kwargs):
        raise OSError("acesso negado")

    monkeypatch.setattr(Path, "mkdir", sem_permissao)
    assert logging_isolado._file_handler() is None

    log = _configurar(logging_isolado, quiet=True)
    log.info("continua funcionando sem arquivo")


def test_o_arquivo_gira_e_nao_cresce_sem_limite(logging_isolado, monkeypatch):
    monkeypatch.setattr(logging_isolado, "_LOG_BYTES", 2_000)
    log = _configurar(logging_isolado, quiet=True)
    for indice in range(400):
        log.info("linha de enchimento numero %d com algum texto junto", indice)

    pasta = logging_isolado.LOG_DIR
    arquivos = sorted(pasta.glob("lauda.log*"))
    assert len(arquivos) > 1, "com o limite estourado tem de haver arquivo de reserva"
    assert len(arquivos) <= logging_isolado._LOG_BACKUPS + 1, "e não pode passar disso"


def test_erro_nao_tratado_chega_ao_log(logging_isolado):
    _configurar(logging_isolado, quiet=True)
    logging_isolado.log_uncaught()

    import sys

    try:
        raise ValueError("estourou sem ninguém pegar")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    conteudo = logging_isolado.LOG_PATH.read_text(encoding="utf-8")
    assert "Erro nao tratado" in conteudo
    assert "estourou sem ninguém pegar" in conteudo


def test_erro_em_outra_thread_tambem_chega(logging_isolado):
    import threading

    _configurar(logging_isolado, quiet=True)
    logging_isolado.log_uncaught()

    def explode() -> None:
        raise RuntimeError("quebrou na thread de trabalho")

    t = threading.Thread(target=explode, name="thread-de-teste")
    t.start()
    t.join()

    conteudo = logging_isolado.LOG_PATH.read_text(encoding="utf-8")
    assert "thread-de-teste" in conteudo
    assert "quebrou na thread de trabalho" in conteudo


def test_o_barulho_de_terceiros_nao_entope_o_arquivo(logging_isolado):
    """Com o arquivo em DEBUG, uma biblioteca falante apagaria o que importa."""
    _configurar(logging_isolado, quiet=True)
    logging.getLogger("PIL.PngImagePlugin").debug("STREAM b'IHDR' 16 13")
    logging.getLogger("lauda.pipeline").debug("etapa que interessa")

    conteudo = logging_isolado.LOG_PATH.read_text(encoding="utf-8")
    assert "etapa que interessa" in conteudo
    assert "IHDR" not in conteudo, "ruído do Pillow não pode entrar"


def test_cada_processo_tem_o_seu_arquivo(logging_isolado):
    """O processamento roda num processo filho.

    Dois processos girando o mesmo arquivo rotativo dá erro no Windows — e o
    erro do filho iria para um stderr que só é lido no fim, com risco de encher
    o pipe e travar o trabalho.
    """
    app = logging_isolado.log_path_for(logging_isolado.APP_LOG_NAME)
    worker = logging_isolado.log_path_for(logging_isolado.WORKER_LOG_NAME)

    assert app != worker
    assert app == logging_isolado.LOG_PATH


def test_o_worker_escreve_no_arquivo_dele(logging_isolado):
    log = _configurar(logging_isolado, quiet=True,
                      log_name=logging_isolado.WORKER_LOG_NAME)
    log.info("linha do processo filho")

    worker = logging_isolado.log_path_for(logging_isolado.WORKER_LOG_NAME)
    assert "linha do processo filho" in worker.read_text(encoding="utf-8")
    assert not logging_isolado.LOG_PATH.exists(), "não pode encostar no log do app"
