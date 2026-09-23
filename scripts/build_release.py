"""Monta o pacote de distribuição: executável + instalador.

    .venv-build\\Scripts\\python.exe scripts\\build_release.py

Faz, na ordem:

1. confere que o ambiente de build está limpo (sem CUDA, sem Gradio — eles
   triplicariam o tamanho e não são usados pelo aplicativo de janela);
2. roda o PyInstaller com `packaging/lauda.spec`;
3. confere que os binários do ffmpeg entraram;
4. chama o Inno Setup, se ele estiver instalado, e devolve o caminho do
   instalador pronto.

Rode-o com o Python do `.venv-build`, não com o de desenvolvimento: é o que
define quais bibliotecas entram no pacote.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SPEC = RAIZ / "packaging" / "lauda.spec"
ISS = RAIZ / "packaging" / "installer.iss"
DIST = RAIZ / "dist"
PASTA_APP = DIST / "Lauda Local"

#: Pacotes que não podem entrar: peso morto para o aplicativo de janela.
PROIBIDOS = ("nvidia", "gradio", "gradio_client")

#: Onde o Inno Setup costuma ficar depois do `winget install JRSoftware.InnoSetup`.
ISCC_CANDIDATOS = (
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
)


def formatar(tamanho: float) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if tamanho < 1024 or unidade == "GB":
            return f"{tamanho:.0f} {unidade}" if unidade == "B" else f"{tamanho:.1f} {unidade}"
        tamanho /= 1024
    return f"{tamanho:.1f} GB"  # pragma: no cover - inalcançável


def tamanho_da_pasta(pasta: Path) -> int:
    return sum(f.stat().st_size for f in pasta.rglob("*") if f.is_file())


def conferir_ambiente() -> None:
    """O venv de build define o pacote: um engano aqui vira 2 GB a mais."""
    site = Path(sys.prefix) / "Lib" / "site-packages"
    achados = [nome for nome in PROIBIDOS if (site / nome).exists()]
    if achados:
        raise SystemExit(
            f"O ambiente de build tem {', '.join(achados)} instalado.\n"
            "Use o .venv-build (CPU, sem Gradio) — veja o cabeçalho deste arquivo."
        )
    try:
        import torch

        if "+cpu" not in torch.__version__ and torch.cuda.is_available():
            print("  aviso: o torch instalado parece ser o de GPU (pacote muito maior).")
    except ImportError:
        raise SystemExit("torch ausente: instale o extra `diarize` no ambiente de build.") from None


def limpar(pasta: Path) -> None:
    """Apaga a pasta, com uma mensagem util quando o Windows nao deixa.

    O caso comum: algum terminal (ou o Explorador) esta com a pasta aberta. O
    Windows nao apaga um diretorio que e a pasta de trabalho de um processo, e
    a mensagem crua do Python nao diz isso.
    """
    if not pasta.exists():
        return
    try:
        shutil.rmtree(pasta)
    except OSError as exc:
        raise SystemExit(
            f"Nao consegui apagar {pasta}: {exc}\n"
            "Feche janelas de terminal ou do Explorador que estejam dentro dessa "
            "pasta e rode de novo."
        ) from exc


def rodar_pyinstaller() -> None:
    print("-- PyInstaller...")
    limpar(DIST)
    subprocess.run(
        [
            str(Path(sys.prefix) / "Scripts" / "pyinstaller.exe"),
            str(SPEC), "--noconfirm",
            "--distpath", str(DIST),
            "--workpath", str(RAIZ / "build"),
        ],
        check=True,
        cwd=RAIZ,
    )


def conferir_pacote() -> None:
    """O que costuma faltar num pacote do PyInstaller, verificado uma a uma."""
    exigidos = [
        PASTA_APP / "Lauda Local.exe",
        PASTA_APP / "_internal" / "ffmpeg.exe",
        PASTA_APP / "_internal" / "ffprobe.exe",
        PASTA_APP / "_internal" / "LICENCAS.txt",
    ]
    faltando = [caminho for caminho in exigidos if not caminho.exists()]
    if faltando:
        raise SystemExit(
            "O pacote saiu incompleto:\n"
            + "\n".join(f"  - falta {c.relative_to(PASTA_APP)}" for c in faltando)
        )
    print(f"  pasta do aplicativo: {formatar(tamanho_da_pasta(PASTA_APP))}")


def rodar_inno() -> Path | None:
    iscc = next((c for c in ISCC_CANDIDATOS if c.exists()), None)
    if iscc is None:
        print(
            "-- Inno Setup nao encontrado; o instalador não foi gerado.\n"
            "  winget install --id JRSoftware.InnoSetup"
        )
        return None
    print("-- Inno Setup...")
    subprocess.run([str(iscc), str(ISS)], check=True, cwd=RAIZ)
    setups = sorted(DIST.glob("Lauda Local-*-setup.exe"))
    return setups[-1] if setups else None


def main() -> int:
    conferir_ambiente()
    rodar_pyinstaller()
    conferir_pacote()
    instalador = rodar_inno()

    print("\nPronto.")
    print(f"  pasta portátil : {PASTA_APP}")
    if instalador:
        print(f"  instalador     : {instalador} ({formatar(instalador.stat().st_size)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
