"""Processo filho que executa um trabalho e reporta progresso por stdout.

Existe para que o supervisor (`runner.py`) possa **matar** um processamento
travado. Uma thread não dá para matar: se o CTranslate2 empacar dentro de uma
chamada nativa, o processo inteiro fica preso. Um processo separado, sim.

Protocolo: uma linha JSON por evento em stdout.

    {"t": "progress", "stage": "asr", "fraction": 0.4, "message": "..."}
    {"t": "done", "result": "C:\\...\\result.json"}
    {"t": "error", "message": "...", "kind": "TranscriptionError"}

Uso (interno):

    python -m lauda.worker caminho/do/job.json
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

EVENT_PROGRESS = "progress"
EVENT_DONE = "done"
EVENT_ERROR = "error"


def emit(event: dict) -> None:
    """Uma linha JSON, sempre com flush: o pai lê isto em tempo real."""
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        emit({"t": EVENT_ERROR, "message": "uso: python -m lauda.worker job.json"})
        return 2

    # O protocolo com o pai e JSON ASCII-safe; a troca de codificacao e so
    # conveniencia para mensagens acentuadas.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception as exc:  # pragma: no cover - stream sem reconfigure
        logging.getLogger("lauda.worker").debug("stdout sem UTF-8 (%s).", exc)

    job_path = Path(argv[0])
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        emit({"t": EVENT_ERROR, "message": f"não consegui ler o job: {exc}"})
        return 2

    # Importar aqui e não no topo: o pai só paga esse custo no filho.
    from .config import JobOptions
    from .errors import LaudaError
    from .logging_setup import WORKER_LOG_NAME, setup_logging
    from .pipeline import process_media
    from .serialize import write_json

    setup_logging(quiet=True, log_name=WORKER_LOG_NAME)

    try:
        options = JobOptions.from_dict(job["options"])
    except Exception as exc:
        emit({"t": EVENT_ERROR, "message": f"opções inválidas: {exc}"})
        return 2

    checkpoint_root = Path(job["checkpoint_root"]) if job.get("checkpoint_root") else None
    result_path = Path(job["result_path"])

    def report(stage: str, fraction: float, message: str) -> None:
        emit({"t": EVENT_PROGRESS, "stage": stage, "fraction": fraction, "message": message})

    try:
        result = process_media(
            options,
            progress=report,
            resume=bool(job.get("resume", True)),
            checkpoint_root=checkpoint_root,
            known_sha256=job.get("sha256"),
        )
    except LaudaError as exc:
        emit({"t": EVENT_ERROR, "message": str(exc), "kind": type(exc).__name__})
        return 1
    except KeyboardInterrupt:  # pragma: no cover - morto pelo supervisor
        return 130
    except Exception as exc:  # pragma: no cover - bug real
        import traceback

        emit({
            "t": EVENT_ERROR,
            "message": f"{exc}\n\n{traceback.format_exc(limit=4)}",
            "kind": type(exc).__name__,
        })
        return 1

    # O pai lê o resultado daqui: stdout é para eventos, não para dados grandes.
    write_json(result_path, result)
    emit({"t": EVENT_DONE, "result": str(result_path)})
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
