"""Qual motor é mais rápido NESTA máquina: a placa ou o processador?

A pergunta não tem resposta única, e é por isso que este arquivo existe em vez
de uma regra fixa no código.

O CTranslate2 no processador é muito bem otimizado. O ONNX na placa depende do
DirectML, que é uma camada de compatibilidade. Numa máquina medida aqui — um
Ryzen 5 5600X de 6 núcleos com uma RTX 4060 — o processador ganhou de longe:
10,4x contra 5,5x tempo real. Numa máquina com processador fraco e uma Radeon
boa, a conta se inverte, porque um lado escala com o processador e o outro com
a placa.

Eu não tenho as duas máquinas. O programa tem a que está na frente dele, então
quem decide é a medição, não o palpite — e ela fica guardada, para acontecer
uma vez só.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from . import theme
from .config import JobOptions
from .hardware import RuntimeChoice, detect_hardware

log = logging.getLogger("lauda.gpu_bench")

#: Onde o resultado mora, dentro do ui.json.
BENCH_KEY = "gpu_bench"

#: Quanto de áudio basta para decidir. Curto o bastante para ninguém esperar,
#: longo o bastante para o tempo de carga do modelo não dominar a conta.
SAMPLE_SECONDS = 20


@dataclass(frozen=True)
class BenchResult:
    """O que foi medido, e em quê. Guardado para não medir de novo."""

    gpu: str
    model: str
    onnx_speed: float          # x tempo real na placa
    ctranslate2_speed: float   # x tempo real no processador
    measured_at: str

    @property
    def winner(self) -> str:
        return "onnx" if self.onnx_speed > self.ctranslate2_speed else "ctranslate2"

    @property
    def advantage(self) -> float:
        """Quantas vezes o vencedor é mais rápido que o perdedor."""
        rapido = max(self.onnx_speed, self.ctranslate2_speed)
        lento = min(self.onnx_speed, self.ctranslate2_speed)
        return rapido / lento if lento > 0 else 1.0

    def describe(self) -> str:
        if self.winner == "onnx":
            return (
                f"A placa ({self.gpu}) é {self.advantage:.1f}x mais rápida que o "
                f"processador neste computador — {self.onnx_speed:.1f}x contra "
                f"{self.ctranslate2_speed:.1f}x tempo real."
            )
        return (
            f"O processador é {self.advantage:.1f}x mais rápido que a placa neste "
            f"computador — {self.ctranslate2_speed:.1f}x contra "
            f"{self.onnx_speed:.1f}x tempo real. A placa fica de fora."
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "gpu": self.gpu, "model": self.model,
            "onnx_speed": round(self.onnx_speed, 3),
            "ctranslate2_speed": round(self.ctranslate2_speed, 3),
            "measured_at": self.measured_at,
        }


def _key(gpu: str, model: str) -> str:
    return f"{gpu}|{model}"


def load(gpu: str, model: str) -> BenchResult | None:
    """A medição guardada para esta placa e este modelo, se houver."""
    guardado = theme.load_value(BENCH_KEY, {})
    if not isinstance(guardado, dict):
        return None
    dados = guardado.get(_key(gpu, model))
    if not isinstance(dados, dict):
        return None
    try:
        return BenchResult(
            gpu=str(dados["gpu"]), model=str(dados["model"]),
            onnx_speed=float(dados["onnx_speed"]),
            ctranslate2_speed=float(dados["ctranslate2_speed"]),
            measured_at=str(dados.get("measured_at", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save(resultado: BenchResult) -> None:
    guardado = theme.load_value(BENCH_KEY, {})
    if not isinstance(guardado, dict):
        guardado = {}
    guardado[_key(resultado.gpu, resultado.model)] = resultado.as_dict()
    theme.save_value(BENCH_KEY, guardado)


def preferred_engine(model: str) -> str | None:
    """O motor que a medição escolheu para esta máquina, ou `None` sem medição."""
    hardware = detect_hardware()
    placa = hardware.graphics
    if placa is None:
        return None
    resultado = load(placa.name, model)
    return resultado.winner if resultado else None


def run(wav_path: Path, options: JobOptions, gpu_name: str) -> BenchResult:
    """Mede os dois motores no mesmo trecho e guarda o resultado.

    Usa o áudio de verdade do usuário: sotaque, ruído e ritmo mudam o tempo, e
    um trecho sintético mediria outra coisa.
    """
    import dataclasses

    from . import onnx_engine
    from .transcribe import _run_transcription, load_model_with_fallback

    recorte = _cut(wav_path, options)
    try:
        escolha = RuntimeChoice(
            device="dml", compute_type="float16", model=options.model,
            device_name=gpu_name, notes=[], engine="onnx",
        )
        # Os dois modelos carregam ANTES do cronômetro. Carregar leva alguns
        # segundos, e num trecho de 20 s isso enterraria a diferença que se
        # quer medir — e sempre contra a placa, que demora mais para subir.
        na_placa_pipeline = onnx_engine.load_pipeline(options, escolha)
        no_cpu = dataclasses.replace(options, device="cpu")
        modelo_cpu, escolha_cpu = load_model_with_fallback(no_cpu)

        inicio = time.perf_counter()
        na_placa = onnx_engine.transcribe(
            recorte, options, escolha, pipeline=na_placa_pipeline
        )
        tempo_placa = time.perf_counter() - inicio

        # O motor principal, forçado no processador: é com ele que a placa
        # compete, e não com a versão CUDA (que esta máquina não tem).
        inicio = time.perf_counter()
        _run_transcription(
            modelo_cpu, escolha_cpu, recorte, no_cpu, progress=None, media_duration=None
        )
        tempo_cpu = time.perf_counter() - inicio

        duracao = na_placa.duration or SAMPLE_SECONDS
        resultado = BenchResult(
            gpu=gpu_name, model=options.model,
            onnx_speed=duracao / max(tempo_placa, 1e-6),
            ctranslate2_speed=duracao / max(tempo_cpu, 1e-6),
            measured_at=time.strftime("%Y-%m-%d %H:%M"),
        )
    finally:
        recorte.unlink(missing_ok=True)

    log.info("Medição de desempenho: %s", resultado.describe())
    save(resultado)
    return resultado


def _cut(wav_path: Path, options: JobOptions) -> Path:
    """Os primeiros segundos do WAV, num arquivo temporário."""
    import wave

    destino = wav_path.with_name(wav_path.stem + ".bench.wav")
    with wave.open(str(wav_path), "rb") as origem:
        taxa = origem.getframerate()
        quadros = origem.readframes(min(origem.getnframes(), taxa * SAMPLE_SECONDS))
        with wave.open(str(destino), "wb") as saida:
            saida.setnchannels(origem.getnchannels())
            saida.setsampwidth(origem.getsampwidth())
            saida.setframerate(taxa)
            saida.writeframes(quadros)
    return destino
