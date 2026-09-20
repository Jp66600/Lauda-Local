"""Baixa os modelos para ./models e deixa a máquina pronta para uso offline.

Uso:
    python scripts/download_models.py --model small
    python scripts/download_models.py --model large-v3-turbo --model small
    python scripts/download_models.py --all

Depois disso, defina VELLUM_OFFLINE=1 para garantir que nada seja baixado
durante o processamento.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permite rodar sem instalar o pacote.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vellum.config import MODEL_CHOICES
from vellum.hardware import MODEL_MEMORY_GB


def download(model: str, models_dir: Path) -> bool:
    from faster_whisper import WhisperModel

    print(f"→ baixando '{model}' (aprox. {MODEL_MEMORY_GB.get(model, 3.6):.1f} GB em memória)…")
    try:
        # Instanciar já dispara o download e valida a integridade dos arquivos.
        WhisperModel(model, device="cpu", compute_type="int8", download_root=str(models_dir))
    except Exception as exc:
        print(f"  [ERRO] {model}: {exc}", file=sys.stderr)
        return False
    print(f"  [OK] {model}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Baixa modelos Whisper para uso offline.")
    parser.add_argument(
        "--model",
        action="append",
        choices=list(MODEL_CHOICES),
        help="Modelo a baixar (pode repetir).",
    )
    parser.add_argument("--all", action="store_true", help="Baixa todos os modelos suportados.")
    parser.add_argument(
        "--models-dir", default="./models", help="Pasta de destino (padrão: ./models)."
    )
    args = parser.parse_args()

    models = list(MODEL_CHOICES) if args.all else (args.model or ["small"])
    models_dir = Path(args.models_dir).expanduser().resolve()
    models_dir.mkdir(parents=True, exist_ok=True)
    print(f"Pasta de modelos: {models_dir}\n")

    failures = [model for model in models if not download(model, models_dir)]
    if failures:
        print(f"\nFalharam: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nTudo pronto. Para forçar uso offline: set VELLUM_OFFLINE=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
