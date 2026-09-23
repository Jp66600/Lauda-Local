"""Contabilidade de espaço em disco: onde os gigabytes estão e o que dá para liberar.

Motivação medida: numa instalação completa, o ambiente Python ocupa ~3,2 GB —
e **61% disso são as bibliotecas CUDA da NVIDIA**, que só existem para acelerar
a transcrição na placa de vídeo. Quem roda em CPU pode dispensar tudo isso.
Sem um lugar que mostre esse número, ninguém descobre.
"""

from __future__ import annotations

import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger("lauda.disk")

#: Pacotes por finalidade, para explicar o peso em vez de só somá-lo.
COMPONENTS: dict[str, tuple[str, ...]] = {
    "aceleração por GPU (CUDA)": ("nvidia",),
    "diarização (PyTorch)": ("torch", "torchaudio", "speechbrain", "sympy", "networkx",
                             "scipy", "sentencepiece", "hyperpyyaml", "soundfile"),
    "interface no navegador": ("gradio", "gradio_client", "fastapi", "starlette",
                               "uvicorn", "pydantic", "pandas", "orjson", "websockets"),
    "geração dos PDFs": ("reportlab", "pypdf", "pypdfium2", "PIL", "pillow"),
    "núcleo (transcrição)": ("ctranslate2", "faster_whisper", "onnxruntime", "av",
                             "tokenizers", "numpy", "huggingface_hub"),
}

#: O que cada componente significa se for removido.
REMOVABLE: dict[str, str] = {
    "aceleração por GPU (CUDA)": "sim — sem ela o app roda em CPU",
    "diarização (PyTorch)": "sim — sem ela não dá para separar falantes",
    "interface no navegador": "sim — o aplicativo em janela não precisa dela",
    "geração dos PDFs": "sim — só serve para regerar os manuais",
    "núcleo (transcrição)": "não — é o coração do programa",
}


def format_size(num_bytes: float) -> str:
    """Tamanho legível, no padrão brasileiro (vírgula decimal)."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            texto = f"{value:.0f}" if unit == "B" else f"{value:.1f}".replace(".", ",")
            return f"{texto} {unit}"
        value /= 1024
    return f"{value:.1f} TB"  # pragma: no cover - inalcançável


def tree_size(path: Path) -> int:
    """Soma o tamanho de tudo abaixo de `path`. 0 se não existir."""
    if not path or not path.exists():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:  # pragma: no cover - arquivo sumiu no meio
                    continue
    except OSError as exc:  # pragma: no cover - permissão
        log.debug("Não consegui medir %s: %s", path, exc)
    return total


def site_packages() -> Path | None:
    """Pasta de bibliotecas do ambiente atual."""
    for entry in sys.path:
        candidate = Path(entry)
        if candidate.name == "site-packages" and candidate.is_dir():
            return candidate
    return None


def component_sizes(
    models_dir: Path, checkpoint_root: Path
) -> list[tuple[str, int, str]]:
    """(nome, bytes, se dá para remover) de cada parte que ocupa espaço."""
    linhas: list[tuple[str, int, str]] = []

    packages = site_packages()
    if packages is not None:
        for nome, prefixos in COMPONENTS.items():
            total = 0
            for item in packages.iterdir():
                if item.name.endswith(".dist-info"):
                    continue
                base = item.name.lower().replace("-", "_")
                if any(base.startswith(p.lower()) for p in prefixos):
                    total += tree_size(item) if item.is_dir() else item.stat().st_size
            if total:
                linhas.append((nome, total, REMOVABLE.get(nome, "—")))

    modelos = tree_size(models_dir)
    if modelos:
        linhas.append(
            ("modelos de transcrição baixados", modelos, "sim — baixa de novo quando usar")
        )

    pontos = tree_size(checkpoint_root)
    if pontos:
        linhas.append(
            ("pontos de retomada", pontos, "sim — `lauda checkpoints --limpar`")
        )

    linhas.sort(key=lambda linha: -linha[1])
    return linhas


def installed_models(models_dir: Path) -> list[tuple[str, int]]:
    """Modelos presentes no cache local, do maior para o menor."""
    if not models_dir.exists():
        return []
    encontrados: list[tuple[str, int]] = []
    for item in models_dir.iterdir():
        if not item.is_dir():
            continue
        # O cache do Hugging Face usa "models--Organizacao--nome-do-modelo".
        nome = item.name
        if nome.startswith("models--"):
            nome = nome.split("--")[-1]
        encontrados.append((nome, tree_size(item)))
    return sorted(encontrados, key=lambda item: -item[1])


def remove_model(models_dir: Path, name: str) -> tuple[list[str], int]:
    """Apaga do cache os modelos cujo nome contenha `name`.

    Devolve (nomes apagados, bytes liberados). Combinação por substring de
    propósito: o usuário digita "small", não
    "models--Systran--faster-whisper-small".
    """
    if not models_dir.exists():
        return [], 0

    alvo = name.strip().lower()
    apagados: list[str] = []
    liberado = 0
    for item in sorted(models_dir.iterdir()):
        if not item.is_dir() or alvo not in item.name.lower():
            continue
        tamanho = tree_size(item)
        try:
            shutil.rmtree(item)
        except OSError as exc:  # pragma: no cover - arquivo em uso
            log.warning("Não consegui apagar %s: %s", item, exc)
            continue
        apagados.append(item.name)
        liberado += tamanho
    return apagados, liberado
