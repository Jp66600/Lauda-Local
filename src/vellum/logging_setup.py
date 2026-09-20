"""Configuracao de logging (mensagens em PT-BR, saida via rich quando disponivel).

Alem da saida na tela, tudo vai para um arquivo em `~/.vellum/logs`. O
aplicativo de janela roda como gui-script, sem console: sem esse arquivo, um
erro na maquina de outra pessoa nao deixaria rastro nenhum.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

_CONFIGURED = False

#: Nivel minimo aceito das bibliotecas de terceiros (ajustado por setup_logging).
_THIRD_PARTY_LEVEL = logging.WARNING

#: Onde os arquivos de log ficam. Mesma pasta das preferencias do usuario.
LOG_DIR = Path(os.environ.get("VELLUM_LOG_DIR", Path.home() / ".vellum" / "logs"))

#: Nome base do log do aplicativo. O processamento roda num processo FILHO, e
#: ele escreve noutro arquivo de proposito: no Windows a rotacao renomeia o
#: arquivo, o que falha enquanto outro processo o mantem aberto — e o erro de
#: logging do filho iria para um stderr que so e lido no fim, com risco de
#: encher o pipe e travar o trabalho.
APP_LOG_NAME = "vellum"
WORKER_LOG_NAME = "vellum-worker"

LOG_PATH = LOG_DIR / f"{APP_LOG_NAME}.log"

#: Cinco arquivos de 1 MB: cobre varias execucoes sem crescer sem limite.
_LOG_BYTES = 1_000_000
_LOG_BACKUPS = 4


def log_path_for(name: str) -> Path:
    """Caminho do log de um dos processos."""
    return LOG_DIR / f"{name}.log"


def _file_handler(name: str = APP_LOG_NAME) -> logging.Handler | None:
    """Handler de arquivo com rotacao. Devolve None se o disco nao deixar.

    Falha ao escrever log nunca pode impedir o aplicativo de abrir.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_path_for(name), maxBytes=_LOG_BYTES, backupCount=_LOG_BACKUPS,
            encoding="utf-8",
        )
    except OSError:  # pragma: no cover - disco cheio, permissao, caminho invalido
        return None
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
    )
    # No arquivo vale sempre DEBUG: e ele que sera lido depois de algo dar errado.
    handler.setLevel(logging.DEBUG)
    handler.addFilter(_ThirdPartyFilter())
    return handler


def setup_logging(
    verbose: bool = False, quiet: bool = False, log_name: str = APP_LOG_NAME
) -> logging.Logger:
    """Configura o logger raiz uma unica vez e devolve o logger do app.

    `log_name` separa o arquivo de cada processo — veja WORKER_LOG_NAME.
    """
    global _CONFIGURED
    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)

    if not _CONFIGURED:
        handler: logging.Handler
        try:
            from rich.logging import RichHandler

            handler = RichHandler(
                rich_tracebacks=True, show_path=False, omit_repeated_times=False
            )
            fmt = "%(message)s"
        except Exception:  # pragma: no cover - fallback sem rich
            handler = logging.StreamHandler(stream=sys.stderr)
            fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

        # O filtro no handler e a unica defesa que sobrevive ao dictConfig que
        # speechbrain/pyannote aplicam quando sao importados (eles fixam INFO
        # em loggers filhos que nem existiam quando configuramos o logging).
        handler.addFilter(_ThirdPartyFilter())
        handler.setLevel(level)

        handlers: list[logging.Handler] = [handler]
        arquivo = _file_handler(log_name)
        if arquivo is not None:
            handlers.append(arquivo)

        # O nivel do logger raiz precisa ser o mais baixo entre os handlers,
        # senao o arquivo nunca receberia o DEBUG que ele pede.
        logging.basicConfig(
            level=min(level, logging.DEBUG) if arquivo else level,
            format=fmt,
            datefmt="%H:%M:%S",
            handlers=handlers,
        )
        _CONFIGURED = True

    logging.getLogger("vellum").setLevel(min(level, logging.DEBUG))
    quiet_third_party(verbose=verbose)
    return logging.getLogger("vellum")


def log_uncaught(logger: logging.Logger | None = None) -> None:
    """Manda para o log tudo que ninguem tratou, inclusive nas threads.

    Sem isto, um erro inesperado no aplicativo de janela morre em silencio: nao
    ha console para onde o traceback pudesse ir.
    """
    log = logger or logging.getLogger("vellum")

    def na_thread_principal(tipo, valor, traco) -> None:
        if issubclass(tipo, KeyboardInterrupt):  # pragma: no cover - Ctrl+C
            sys.__excepthook__(tipo, valor, traco)
            return
        log.critical("Erro nao tratado", exc_info=(tipo, valor, traco))

    def na_outra_thread(args) -> None:
        log.critical(
            "Erro nao tratado na thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = na_thread_principal
    threading.excepthook = na_outra_thread


#: Bibliotecas que ajustam o proprio nivel de log ao serem importadas.
class _ThirdPartyFilter(logging.Filter):
    """Deixa passar so WARNING+ das bibliotecas de terceiros (tudo com -v)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= _THIRD_PARTY_LEVEL:
            return True
        name = record.name
        return not any(
            name == prefix or name.startswith(prefix + ".") for prefix in _NOISY_LOGGERS
        )


_NOISY_LOGGERS = (
    "faster_whisper",
    "huggingface_hub",
    "urllib3",
    "filelock",
    "speechbrain",
    "pyannote",
    "torch",
    "numba",
    "matplotlib",
    "httpx",
    "asyncio",
    # O Pillow registra cada pedaço de PNG que lê. Com o log em arquivo no
    # nivel DEBUG, isso soterrava as linhas que interessam.
    "PIL",
    "fsspec",
    "requests",
    "charset_normalizer",
    "transformers",
)


def quiet_third_party(verbose: bool = False) -> None:
    """Cala bibliotecas de terceiros: elas so falam quando algo quebra.

    Precisa ser chamada DE NOVO depois de importar speechbrain/pyannote: elas
    aplicam um dictConfig no import e fixam o nivel INFO em cada logger FILHO
    (`speechbrain.utils.fetching`, etc.). Por isso nao basta ajustar o logger
    pai — e preciso varrer os filhos ja registrados.
    """
    global _THIRD_PARTY_LEVEL
    level = logging.INFO if verbose else logging.WARNING
    _THIRD_PARTY_LEVEL = level
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)

    for name in list(logging.root.manager.loggerDict):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _NOISY_LOGGERS):
            logging.getLogger(name).setLevel(level)
