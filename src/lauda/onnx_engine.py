"""Transcrição em placa de vídeo que não é NVIDIA (AMD, Intel, integrada).

O motor principal do programa é o CTranslate2, e ele tem exatamente dois
caminhos: `cpu` e `cuda`. Não há ROCm, não há DirectML. Este módulo é o segundo
motor, e existe por um motivo só: uma Radeon ou uma Arc parada enquanto o
processador sua não é uma escolha de arquitetura, é uma falta.

O caminho aqui é ONNX Runtime com o **DirectML**, que fala com qualquer placa
DirectX 12 — AMD, Intel e integradas, do mesmo jeito. Em troca, três coisas são
piores que no motor principal e estão declaradas em `LIMITACOES`.

Três armadilhas do DirectML foram pagas em depuração e não se mexe nelas sem
repetir a medição:

1. **`use_io_binding=True` é obrigatório.** Sem ele o DirectML não erra um
   pouco: devolve lixo. O mesmo arquivo, o mesmo áudio, sai
   "further donuts 행 Unf eran praw" em vez de português. Medido por dois
   caminhos independentes.
2. **Tensor de comprimento zero não pode ser alocado na placa.** Criar um
   derruba o processo na hora, sem exceção e sem mensagem — o cache vazio do
   primeiro passo precisa nascer na CPU.
3. **O modelo é fp16.** Dá o mesmo texto que o fp32 (conferido trecho a trecho)
   e o download cai pela metade.

Os itens 1 e 2 estão dentro do `optimum`, que é justamente por que ele é usado
aqui em vez de um laço escrito à mão: a versão à mão funcionava na CPU e
morria com segfault na placa.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import JobOptions
from .hardware import RuntimeChoice
from .types import LanguageInfo, SegmentInfo

log = logging.getLogger("lauda.onnx")

ProgressCallback = Callable[[float, str], None]

#: Janela do Whisper. O encoder exige exatamente isto — nem mais, nem menos.
WINDOW_SECONDS = 30
SAMPLE_RATE = 16000

#: O que este motor **não** entrega, comparado ao principal. Vira aviso no
#: laudo em vez de sumir: é a mesma regra dos blocos indisponíveis.
LIMITACOES = (
    "o tempo de cada palavra (BLOCO C) não sai neste motor",
    "a legenda no tamanho \"curta\" fica menos precisa sem o tempo das palavras",
)

#: Os modelos que existem em ONNX. O resto da lista do programa não tem build
#: publicado, e inventar um substituto seria trocar a qualidade sem avisar.
ONNX_MODELS: dict[str, str] = {
    "tiny": "onnx-community/whisper-tiny",
    "base": "onnx-community/whisper-base",
    "small": "onnx-community/whisper-small",
    "large-v3-turbo": "onnx-community/whisper-large-v3-turbo",
}

#: Os arquivos que o motor precisa, e o nome com que eles ficam em disco. O
#: `optimum` procura os nomes padrão, então o fp16 é renomeado na chegada.
_ONNX_FILES = {
    "onnx/encoder_model_fp16.onnx": "onnx/encoder_model.onnx",
    "onnx/decoder_model_merged_fp16.onnx": "onnx/decoder_model_merged.onnx",
}
_CONFIG_FILES = (
    "config.json",
    "generation_config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "vocab.json",
    "merges.txt",
    "added_tokens.json",
    "normalizer.json",
)


def supported_model(model: str) -> str | None:
    """O repositório ONNX deste modelo, ou `None` se não existe build dele."""
    return ONNX_MODELS.get(model)


def available() -> tuple[bool, str]:
    """(dá para usar, motivo quando não dá). Nunca levanta exceção."""
    try:
        import onnxruntime
    except ImportError:
        return False, "o onnxruntime não está instalado nesta cópia do programa."
    if "DmlExecutionProvider" not in onnxruntime.get_available_providers():
        return False, (
            "este onnxruntime foi instalado sem DirectML "
            "(pacote 'onnxruntime' em vez de 'onnxruntime-directml')."
        )
    try:
        import optimum.onnxruntime  # noqa: F401
    except Exception as exc:
        return False, f"o optimum não está disponível: {exc}"
    return True, ""


def model_dir(options: JobOptions, model: str) -> Path:
    return options.models_dir / "onnx" / model


def ensure_model(options: JobOptions, model: str) -> Path:
    """Baixa o modelo ONNX se ele ainda não estiver em disco.

    Baixa só o fp16 e os arquivos de configuração — o repositório tem uma dúzia
    de precisões, e puxar tudo custaria alguns gigabytes à toa.
    """
    repo = supported_model(model)
    if repo is None:
        raise ValueError(f"não existe build ONNX publicado do modelo '{model}'")

    destino = model_dir(options, model)
    prontos = all((destino / alvo).exists() for alvo in _ONNX_FILES.values())
    if prontos and (destino / "config.json").exists():
        return destino

    if os.environ.get("LAUDA_OFFLINE", "").strip() in ("1", "true", "True"):
        raise FileNotFoundError(
            f"o modelo ONNX '{model}' não está em {destino} e o download está desligado"
        )

    from huggingface_hub import hf_hub_download

    destino.mkdir(parents=True, exist_ok=True)
    (destino / "onnx").mkdir(exist_ok=True)
    log.info("Baixando o modelo ONNX '%s' (%s)…", model, repo)

    for nome in _CONFIG_FILES:
        try:
            origem = hf_hub_download(repo, nome)
        except Exception as exc:  # arquivos opcionais faltam em alguns repos
            log.debug("%s não existe em %s (%s)", nome, repo, exc)
            continue
        (destino / nome).write_bytes(Path(origem).read_bytes())

    for nome, alvo in _ONNX_FILES.items():
        origem = hf_hub_download(repo, nome)
        (destino / alvo).write_bytes(Path(origem).read_bytes())
    return destino


def _windows(audio: Any, options: JobOptions) -> list[tuple[int, int]]:
    """Fatia o áudio em janelas de até 30 s, cortando onde há silêncio.

    O Whisper inventa texto em silêncio prolongado — é por isso que o VAD é
    ligado por padrão no motor principal, e é por isso que ele vem junto aqui.
    O Silero já vem com o faster-whisper; não é dependência nova.
    """
    limite = WINDOW_SECONDS * SAMPLE_RATE
    if not options.vad:
        return [(inicio, min(inicio + limite, len(audio)))
                for inicio in range(0, len(audio), limite)]

    from faster_whisper.vad import VadOptions, get_speech_timestamps

    fala = get_speech_timestamps(
        audio,
        VadOptions(min_silence_duration_ms=500, speech_pad_ms=200),
        sampling_rate=SAMPLE_RATE,
    )
    janelas: list[tuple[int, int]] = []
    for trecho in fala:
        inicio, fim = int(trecho["start"]), int(trecho["end"])
        while fim - inicio > limite:
            janelas.append((inicio, inicio + limite))
            inicio += limite
        if (
            janelas
            and inicio - janelas[-1][1] < SAMPLE_RATE
            and fim - janelas[-1][0] <= limite
        ):
            # Cabe junto da janela anterior: menos chamadas, mais contexto.
            janelas[-1] = (janelas[-1][0], fim)
        else:
            janelas.append((inicio, fim))
    return janelas


def _read_wav(path: Path) -> Any:
    """Lê o WAV de 16 kHz mono que o `extract.py` já deixou pronto."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as arquivo:
        quadros = arquivo.readframes(arquivo.getnframes())
        canais = arquivo.getnchannels()
    amostras = np.frombuffer(quadros, dtype=np.int16).astype(np.float32) / 32768.0
    if canais > 1:  # pragma: no cover - o pipeline já entrega mono
        amostras = amostras.reshape(-1, canais).mean(axis=1)
    return amostras


def load_pipeline(options: JobOptions, choice: RuntimeChoice) -> tuple[Any, Any]:
    """Carrega o modelo na placa. Devolve (modelo, processador)."""
    from optimum.onnxruntime import ORTModelForSpeechSeq2Seq
    from transformers import WhisperProcessor

    pasta = ensure_model(options, choice.model)
    log.info(
        "Carregando modelo ONNX '%s' na placa de vídeo (%s)…",
        choice.model, choice.device_name or "GPU",
    )
    modelo = ORTModelForSpeechSeq2Seq.from_pretrained(
        str(pasta),
        provider="DmlExecutionProvider",
        # NÃO TIRE ISTO. Sem io_binding o DirectML devolve lixo, não texto
        # ligeiramente diferente. Ver o cabeçalho do módulo.
        use_io_binding=True,
    )
    return modelo, WhisperProcessor.from_pretrained(str(pasta))


def transcribe(
    wav_path: Path,
    options: JobOptions,
    choice: RuntimeChoice,
    *,
    progress: ProgressCallback | None = None,
    media_duration: float | None = None,
    pipeline: tuple[Any, Any] | None = None,
) -> Any:
    """Transcreve na placa de vídeo. Mesma assinatura do motor principal.

    `pipeline` serve para a medição de desempenho, que precisa cronometrar a
    transcrição sem o tempo de carga do modelo no meio — carregar leva alguns
    segundos, e num trecho curto isso mascararia o que se quer comparar.
    """
    from .transcribe import TranscriptionOutput

    modelo, processor = pipeline or load_pipeline(options, choice)
    audio = _read_wav(wav_path)
    janelas = _windows(audio, options)
    duracao = media_duration or len(audio) / SAMPLE_RATE
    log.info("%d janela(s) de fala para transcrever.", len(janelas))

    idioma = options.language_code or "pt"
    segmentos: list[SegmentInfo] = []
    for posicao, (inicio, fim) in enumerate(janelas):
        entrada = processor(
            audio[inicio:fim], sampling_rate=SAMPLE_RATE, return_tensors="pt"
        ).input_features
        ids = modelo.generate(
            entrada,
            language=idioma,
            task="transcribe",
            num_beams=1,
            do_sample=False,
            return_timestamps=True,
            max_new_tokens=220,
        )
        decodificado = processor.batch_decode(
            ids, skip_special_tokens=True, output_offsets=True
        )[0]
        deslocamento = inicio / SAMPLE_RATE
        largura = (fim - inicio) / SAMPLE_RATE
        for offset in decodificado["offsets"]:
            comeco, termino = offset["timestamp"]
            texto = offset["text"].strip()
            if not texto:
                continue
            segmentos.append(SegmentInfo(
                id=len(segmentos),
                start=round(deslocamento + (comeco or 0.0), 3),
                end=round(deslocamento + (termino if termino is not None else largura), 3),
                text=texto,
            ))
        if progress and duracao:
            feito = min(1.0, (posicao + 1) / max(1, len(janelas)))
            progress(feito, f"transcrevendo {feito * 100:.0f}% (placa de vídeo)")

    return TranscriptionOutput(
        segments=segmentos,
        text=" ".join(s.text for s in segmentos).strip(),
        language=LanguageInfo(
            code=idioma,
            probability=None,
            source="manual" if options.language_code else "auto",
        ),
        duration=len(audio) / SAMPLE_RATE,
        duration_after_vad=sum(f - i for i, f in janelas) / SAMPLE_RATE,
        runtime=choice,
        engine_version=_engine_version(),
        model_path=str(model_dir(options, choice.model)),
    )


def _engine_version() -> str:
    try:
        import onnxruntime

        return f"onnxruntime {onnxruntime.__version__} (DirectML)"
    except Exception:  # pragma: no cover
        return "onnxruntime (DirectML)"
