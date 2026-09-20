"""Ponto de entrada do executável empacotado.

Existe separado do `vellum.desktop:main` por dois motivos:

* `multiprocessing.freeze_support()` precisa ser a primeira coisa a rodar num
  executável congelado, senão qualquer subprocesso reabre a janela em laço;
* o supervisor do processamento chama `python -m vellum.worker`, que não
  existe quando não há Python instalado — aqui o próprio executável assume esse
  papel quando recebe o argumento `--worker`.
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> int:
    multiprocessing.freeze_support()

    # O torch despeja estatísticas internas no stderr quando a diarização roda.
    # No pacote isso só sujaria o arquivo de log, que é o que vamos ler quando
    # algo der errado na máquina de outra pessoa.
    os.environ.setdefault("TORCH_CPP_LOG_LEVEL", "ERROR")

    if "--worker" in sys.argv[1:]:
        from vellum.worker import main as worker_main

        sys.argv = [sys.argv[0], *[a for a in sys.argv[1:] if a != "--worker"]]
        return int(worker_main() or 0)

    from vellum.desktop import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
