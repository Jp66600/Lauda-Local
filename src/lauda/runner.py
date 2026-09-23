"""Supervisor com recuperação — o "deu merda" visto de fora.

Roda o processamento num processo separado e fica de olho no progresso. Se o
filho **travar** (nenhum sinal de vida por um tempo) ou **morrer**, o supervisor:

1. mata o processo (um travamento dentro de código nativo não responde a nada
   mais suave que isso);
2. volta do último ponto de retomada salvo — a transcrição já feita não se
   perde;
3. tenta de novo com o ambiente rebaixado, para não repetir exatamente a mesma
   condição que travou: primeiro sem GPU, depois com um modelo menor.

Se todas as tentativas falharem, levanta o erro da última — mas o ponto de
retomada continua no disco, então mesmo assim a próxima execução aproveita o
que deu certo.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .checkpoint import CheckpointStore, job_key
from .config import JobOptions
from .errors import LaudaError
from .ffmpeg_tools import hidden_console
from .serialize import read_json
from .types import JobResult
from .utils import sha256_file

log = logging.getLogger("lauda.runner")

ProgressFn = Callable[[str, float, str], None]
#: callback(tipo, mensagem) — "travou", "reiniciando", "desistiu"
EventFn = Callable[[str, str], None]

#: Sem nenhum sinal por este tempo, consideramos travado.
DEFAULT_STALL_TIMEOUT = 300.0
#: A etapa `asr` fica muda enquanto baixa e carrega o modelo, então ganha
#: folga — como MULTIPLICADOR do tempo pedido, não como valor absoluto: um teto
#: fixo aqui faria o supervisor ignorar o limite escolhido por quem chamou.
ASR_STALL_FACTOR = 3.0
DEFAULT_MAX_ATTEMPTS = 3

_SMALLER_MODEL = {
    "large-v3": "large-v3-turbo",
    "large-v3-turbo": "medium",
    "distil-large-v3": "medium",
    "medium": "small",
    "small": "base",
    "base": "tiny",
    "tiny": "tiny",
}


@dataclass
class Attempt:
    """Registro de uma tentativa, para o relatório e para os testes."""

    number: int
    reason: str = ""
    stalled: bool = False
    stage: str = ""
    exit_code: int | None = None


class RecoveryFailed(LaudaError):
    """Todas as tentativas falharam."""


def _degrade(options: JobOptions, attempt: int) -> tuple[JobOptions, str]:
    """Rebaixa o ambiente entre tentativas, do menos ao mais drástico."""
    if attempt == 2 and options.limits.use_gpu:
        return (
            replace(options, limits=replace(options.limits, gpu_percent=0)),
            "desligando a GPU",
        )
    smaller = _SMALLER_MODEL.get(options.model, options.model)
    if smaller != options.model:
        return replace(options, model=smaller), f"trocando o modelo para '{smaller}'"
    # Nada mais a rebaixar: pelo menos garante CPU.
    if options.limits.use_gpu:
        return (
            replace(options, limits=replace(options.limits, gpu_percent=0)),
            "desligando a GPU",
        )
    return options, "repetindo com as mesmas opções"


def _worker_command(job_path: Path) -> list[str]:
    """Como chamar o processo filho — funciona no venv e no .exe do app."""
    if getattr(sys, "frozen", False):
        # No aplicativo empacotado não existe Python para chamar: o próprio
        # executável vira worker quando recebe --worker (packaging/entrada.py).
        return [sys.executable, "--worker", str(job_path)]

    executable = sys.executable
    if Path(executable).stem.lower() in ("lauda-app", "lauda"):
        # Rodando pelo lançador: procura o python do mesmo ambiente.
        candidate = Path(executable).with_name("python.exe")
        if candidate.exists():
            executable = str(candidate)
    return [executable, "-m", "lauda.worker", str(job_path)]


def run_with_recovery(
    options: JobOptions,
    progress: ProgressFn | None = None,
    *,
    on_event: EventFn | None = None,
    stall_timeout: float = DEFAULT_STALL_TIMEOUT,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    checkpoint_root: Path | None = None,
    cancel: threading.Event | None = None,
) -> tuple[JobResult, list[Attempt]]:
    """Processa com supervisão. Devolve o resultado e o histórico de tentativas."""
    report = progress or (lambda stage, fraction, message: None)
    notify = on_event or (lambda kind, message: None)

    # Calculado UMA vez e repassado ao filho: reler um arquivo de 4 GB duas
    # vezes por execucao era desperdicio puro.
    digest = sha256_file(options.input_path)
    store = CheckpointStore(job_key(digest, options), root=checkpoint_root)
    attempts: list[Attempt] = []
    current = options
    last_error = "sem detalhes"

    with tempfile.TemporaryDirectory(prefix="lauda_run_") as workdir:
        work = Path(workdir)
        for number in range(1, max_attempts + 1):
            if number > 1:
                current, how = _degrade(current, number)
                notify(
                    "reiniciando",
                    f"Tentativa {number} de {max_attempts}, {how}. "
                    "O que já foi transcrito está guardado.",
                )
                log.warning("Reiniciando (tentativa %d): %s", number, how)

            attempt = Attempt(number=number)
            attempts.append(attempt)

            job_path = work / f"job{number}.json"
            result_path = work / f"result{number}.json"
            job_path.write_text(
                json.dumps({
                    "options": current.to_dict(),
                    "checkpoint_root": str(checkpoint_root) if checkpoint_root else None,
                    "result_path": str(result_path),
                    "resume": True,
                    "sha256": digest,
                }, ensure_ascii=False),
                encoding="utf-8",
            )

            outcome = _run_once(
                job_path, report, attempt, stall_timeout=stall_timeout, cancel=cancel
            )
            if outcome == "cancelado":
                raise RecoveryFailed("Processamento cancelado.")
            if outcome == "ok" and result_path.exists():
                return read_json(result_path), attempts

            last_error = attempt.reason or "o processo terminou sem resultado"
            if attempt.stalled:
                notify(
                    "travou",
                    f"O processamento parou de responder na etapa '{attempt.stage or '?'}'. "
                    "Encerrei e vou retomar do último ponto salvo.",
                )

    saved = store.load()
    detalhe = f" O ponto salvo ({saved.describe()}) continua no disco." if saved else ""
    notify("desistiu", f"Não consegui concluir após {max_attempts} tentativas.{detalhe}")
    raise RecoveryFailed(
        f"Não consegui concluir após {max_attempts} tentativas: {last_error}",
        hint=(
            "O progresso salvo foi mantido: rodar de novo continua de onde parou."
            if saved
            else "Tente um modelo menor, ou desligue a GPU nos limites de uso."
        ),
    )


def _run_once(
    job_path: Path,
    report: ProgressFn,
    attempt: Attempt,
    *,
    stall_timeout: float,
    cancel: threading.Event | None,
) -> str:
    """Uma tentativa. Devolve "ok", "travou", "falhou" ou "cancelado"."""
    command = _worker_command(job_path)
    log.debug("Iniciando processo filho: %s", " ".join(command))

    environment = dict(os.environ)
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    environment.setdefault("PYTHONUNBUFFERED", "1")

    startupinfo, creationflags = hidden_console()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
        startupinfo=startupinfo,
        creationflags=creationflags,
        # No POSIX o filho vira lider de um grupo proprio: e assim que da para
        # matar ele e os netos (ffmpeg) de uma vez so.
        start_new_session=sys.platform != "win32",
    )

    events: list[dict] = []
    last_signal = time.monotonic()
    lock = threading.Lock()

    def pump() -> None:
        if process.stdout is None:  # pragma: no cover - sempre criamos com PIPE
            return
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            with lock:
                events.append(event)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()

    outcome = "falhou"
    done = False
    while True:
        if cancel is not None and cancel.is_set():
            _kill(process)
            return "cancelado"

        with lock:
            pending, events[:] = list(events), []

        for event in pending:
            kind = event.get("t")
            if kind == "progress":
                last_signal = time.monotonic()
                attempt.stage = str(event.get("stage", attempt.stage))
                report(
                    attempt.stage,
                    float(event.get("fraction", 0.0)),
                    str(event.get("message", "")),
                )
            elif kind == "done":
                outcome, done = "ok", True
            elif kind == "error":
                attempt.reason = str(event.get("message", ""))[:500]
                outcome, done = "falhou", True

        if done:
            break

        if process.poll() is not None:
            break

        # A transcrição pode ficar muda por muito tempo na primeira execução
        # (download do modelo); por isso a etapa `asr` ganha um teto maior.
        limit = stall_timeout * (ASR_STALL_FACTOR if attempt.stage == "asr" else 1.0)
        if time.monotonic() - last_signal > limit:
            attempt.stalled = True
            attempt.reason = (
                f"nenhum sinal por {limit:.0f}s na etapa '{attempt.stage or '?'}'"
            )
            _kill(process)
            return "travou"

        time.sleep(0.1)

    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:  # pragma: no cover - filho preso no fim
        _kill(process)

    attempt.exit_code = process.returncode
    if outcome != "ok" and not attempt.reason:
        stderr = (process.stderr.read() if process.stderr else "") or ""
        attempt.reason = (
            stderr.strip().splitlines()[-1][:500]
            if stderr.strip()
            else f"o processo terminou com código {process.returncode}"
        )
    return outcome


def _kill(process: subprocess.Popen) -> None:
    """Encerra o filho E os netos.

    O worker chama o ffmpeg. Matar so o worker deixaria o ffmpeg rodando,
    comendo CPU e segurando o arquivo — foi exatamente o que aconteceu ao
    testar isto a mao. No Windows a arvore inteira precisa do `taskkill /T`;
    no POSIX, do grupo de processos.
    """
    if process.poll() is not None:
        return

    if sys.platform == "win32":
        startupinfo, creationflags = hidden_console()
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=15, check=False,
                startupinfo=startupinfo, creationflags=creationflags,
            )
        except Exception as exc:  # pragma: no cover - taskkill ausente
            log.debug("taskkill falhou (%s); caindo para terminate().", exc)
    else:  # pragma: no cover - especifico de POSIX
        import signal

        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception as exc:
            log.debug("killpg falhou (%s); caindo para terminate().", exc)

    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:  # pragma: no cover - processo zumbi
            log.warning("Não consegui encerrar o processo filho %s.", process.pid)
