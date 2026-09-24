"""Pontos de retomada — o "deu merda" do pipeline.

A ideia: depois de cada etapa cara, o estado parcial é gravado em disco. Se o
processo morrer no meio (travou, faltou VRAM, o usuário matou, acabou a luz),
a próxima tentativa **não refaz o que já estava pronto** — ela volta do último
ponto salvo. Na prática, o que se ganha é não transcrever duas vezes.

Onde ficam: `~/.lauda/checkpoints/<chave>/`. A chave junta o SHA-256 do
arquivo de entrada com uma impressão digital das opções que mudam o resultado
pesado (modelo, idioma, VAD...). Trocar a pasta de saída, pedir legenda ou mexer
em "quem fala" **não** invalida o ponto salvo; trocar o modelo, sim.

O WAV extraído é guardado junto, senão a retomada teria que reconverter o
áudio — que é justamente o segundo passo mais caro.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import JobOptions
from .serialize import from_json_dict, to_json_dict
from .theme import PREFS_PATH
from .types import JobResult

log = logging.getLogger("lauda.checkpoint")

CHECKPOINT_ROOT = PREFS_PATH.parent / "checkpoints"

#: Ordem das etapas. Retomar significa pular tudo até a etapa salva.
STAGE_ORDER: tuple[str, ...] = ("probe", "extract", "vad", "asr", "align", "diarize")

#: Pontos mais velhos que isto são lixo de execuções esquecidas.
MAX_AGE_SECONDS = 7 * 24 * 3600

#: Versão do formato: se mudar o que é salvo, invalida os pontos antigos.
FORMAT_VERSION = 1


def stage_index(stage: str) -> int:
    """Posição da etapa na ordem. -1 para etapa desconhecida."""
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def options_fingerprint(options: JobOptions) -> str:
    """Impressão digital das opções que afetam a **transcrição**.

    Só entra aqui o que muda o conteúdo do trabalho pesado. Pasta de saída,
    formatos de legenda e afins ficam de fora de propósito: mudá-los não
    justifica transcrever tudo de novo.

    As opções de **diarização ficam de fora** por um motivo prático: ela roda
    depois da transcrição, então mudar "quem fala" — ou desligá-la — não
    invalida uma transcrição pronta. Quando isso não era assim, uma falha na
    diarização fazia o supervisor transcrever o arquivo inteiro de novo a cada
    tentativa, e o usuário esperava horas para não receber nada. O que protege
    o caso em que o ponto salvo É da diarização está em `diarize_fingerprint`.
    """
    relevant = {
        "model": options.model,
        "language": options.language,
        "device": options.effective_device,
        "compute_type": options.compute_type,
        "beam_size": options.beam_size,
        "batch_size": options.batch_size,
        "temperature": options.temperature,
        "initial_prompt": options.initial_prompt,
        "vad": options.vad,
        "word_timestamps": options.word_timestamps,
        "condition_on_previous_text": options.condition_on_previous_text,
    }
    payload = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def diarize_fingerprint(options: JobOptions) -> str:
    """Impressão digital só das opções de quem fala.

    Guardada junto com o ponto salvo: se o ponto for **da** diarização e estas
    opções tiverem mudado, ele volta uma etapa em vez de valer como está.
    """
    relevant = {
        "diarize": options.diarize,
        "diarize_backend": options.diarize_backend,
        "num_speakers": options.num_speakers,
        "min_speakers": options.min_speakers,
        "max_speakers": options.max_speakers,
        "speaker_threshold": options.speaker_threshold,
    }
    payload = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def job_key(sha256: str, options: JobOptions) -> str:
    """Identidade do trabalho: arquivo + opções pesadas."""
    return f"{sha256[:16]}-{options_fingerprint(options)}"


@dataclass
class Checkpoint:
    """Estado salvo de um trabalho interrompido."""

    key: str
    stage: str
    result: JobResult
    wav_path: Path | None
    attempts: int
    saved_at: float
    #: Digital das opcoes de quem fala quando o ponto foi salvo.
    diarize_key: str = ""

    @property
    def stage_index(self) -> int:
        return stage_index(self.stage)

    def describe(self) -> str:
        idade = max(0, int(time.time() - self.saved_at))
        return (
            f"ponto de retomada na etapa '{self.stage}' "
            f"({len(self.result.segments)} trechos, salvo há {idade}s)"
        )


class CheckpointStore:
    """Leitura e escrita dos pontos de retomada de um trabalho."""

    def __init__(self, key: str, root: Path | None = None) -> None:
        self.key = key
        self.directory = (root or CHECKPOINT_ROOT) / key

    # ------------------------------------------------------------- caminhos --
    def prepare(self) -> Path:
        """Cria a pasta do ponto com permissao restrita e devolve o caminho.

        O que fica aqui e transcricao: conteudo sensivel. No POSIX limitamos a
        0700; no Windows a pasta ja herda a ACL do perfil do usuario.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":  # pragma: no cover - especifico de POSIX
            for alvo in (self.directory.parent, self.directory):
                try:
                    os.chmod(alvo, 0o700)
                except OSError as exc:
                    log.debug("Nao consegui restringir a permissao de %s: %s", alvo, exc)
        return self.directory

    @property
    def state_path(self) -> Path:
        return self.directory / "state.json"

    @property
    def wav_path(self) -> Path:
        return self.directory / "audio.wav"

    # ---------------------------------------------------------------- salvar --
    def save(
        self,
        stage: str,
        result: JobResult,
        *,
        wav: Path | None = None,
        attempts: int = 0,
        diarize_key: str = "",
    ) -> None:
        """Grava o estado depois de uma etapa. Nunca levanta para o pipeline."""
        try:
            self.prepare()
            # `wav == self.wav_path` quando o pipeline extraiu direto aqui:
            # nesse caso nao ha nada a copiar (e o WAV pode ter centenas de MB).
            if (
                wav is not None
                and wav != self.wav_path
                and wav.exists()
                and not self.wav_path.exists()
            ):
                shutil.copy2(wav, self.wav_path)

            payload: dict[str, Any] = {
                "format_version": FORMAT_VERSION,
                "key": self.key,
                "stage": stage,
                "attempts": attempts,
                "saved_at": time.time(),
                "wav": str(self.wav_path) if self.wav_path.exists() else None,
                "diarize_key": diarize_key,
                "result": to_json_dict(result),
            }
            # Escrita atômica: um ponto de retomada pela metade é pior que nenhum.
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(self.state_path)
            log.debug("Ponto de retomada salvo na etapa '%s'.", stage)
        except Exception as exc:  # pragma: no cover - disco cheio, permissão
            log.warning("Não consegui salvar o ponto de retomada: %s", exc)

    # ------------------------------------------------------------------ ler --
    def load(self) -> Checkpoint | None:
        """Ponto salvo, ou None se não houver (ou estiver inutilizável)."""
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Ponto de retomada ilegível (%s); começando do zero.", exc)
            self.clear()
            return None

        if payload.get("format_version") != FORMAT_VERSION:
            log.info("Ponto de retomada de uma versão antiga; começando do zero.")
            self.clear()
            return None

        saved_at = float(payload.get("saved_at", 0))
        if time.time() - saved_at > MAX_AGE_SECONDS:
            log.info("Ponto de retomada vencido; começando do zero.")
            self.clear()
            return None

        try:
            result = from_json_dict(payload["result"])
        except Exception as exc:
            log.warning("Ponto de retomada corrompido (%s); começando do zero.", exc)
            self.clear()
            return None

        wav = Path(payload["wav"]) if payload.get("wav") else None
        if wav is not None and not wav.exists():
            wav = None

        return Checkpoint(
            key=self.key,
            stage=str(payload.get("stage", "")),
            result=result,
            wav_path=wav,
            attempts=int(payload.get("attempts", 0)),
            saved_at=saved_at,
            diarize_key=str(payload.get("diarize_key", "")),
        )

    # --------------------------------------------------------------- limpeza --
    def bump_attempts(self) -> int:
        """Conta mais uma tentativa neste trabalho. Devolve o total."""
        checkpoint = self.load()
        attempts = (checkpoint.attempts if checkpoint else 0) + 1
        if checkpoint is not None:
            self.save(
                checkpoint.stage,
                checkpoint.result,
                wav=checkpoint.wav_path,
                attempts=attempts,
            )
        else:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                (self.directory / "attempts").write_text(str(attempts), encoding="utf-8")
            except OSError:  # pragma: no cover
                pass
        return attempts

    def clear(self) -> None:
        """Apaga o ponto de retomada — chamado quando o trabalho conclui."""
        try:
            if self.directory.exists():
                shutil.rmtree(self.directory, ignore_errors=True)
        except OSError as exc:  # pragma: no cover
            log.debug("Não consegui apagar o ponto de retomada: %s", exc)


def purge_old(root: Path | None = None, max_age: float = MAX_AGE_SECONDS) -> int:
    """Remove pontos de retomada esquecidos. Devolve quantos foram apagados."""
    base = root or CHECKPOINT_ROOT
    if not base.exists():
        return 0
    removed = 0
    now = time.time()
    for directory in base.iterdir():
        if not directory.is_dir():
            continue
        state = directory / "state.json"
        try:
            age = now - (state.stat().st_mtime if state.exists() else directory.stat().st_mtime)
            if age > max_age:
                shutil.rmtree(directory, ignore_errors=True)
                removed += 1
        except OSError:  # pragma: no cover
            continue
    return removed
