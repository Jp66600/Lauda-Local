# -*- mode: python ; coding: utf-8 -*-
"""Receita do PyInstaller para o aplicativo de janela.

    .venv-build\\Scripts\\pyinstaller.exe packaging\\lauda.spec --noconfirm

Gera `dist/Lauda Local/` — uma pasta que roda em qualquer Windows 64 bits,
sem Python instalado. O instalador (`packaging/installer.iss`) empacota essa
pasta.

Duas decisões que valem registro:

* **Um diretório, não um arquivo só.** O modo `--onefile` descompacta tudo num
  temporário a cada abertura: com ~600 MB isso custa dezenas de segundos e
  atrapalha o antivírus. Em pasta, abre na hora.
* **ffmpeg entra junto.** É um build **LGPL** (sem os componentes GPL), o que
  permite distribuí-lo ao lado de um aplicativo MIT. O usuário não precisa
  instalar nada à parte.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

RAIZ = Path(SPECPATH).parent
FFMPEG_BIN = RAIZ / "build-tools" / "ffmpeg-n9.0-latest-win64-lgpl-shared-9.0" / "bin"

# --------------------------------------------------------------------------- #
# O que o PyInstaller não descobre sozinho
# --------------------------------------------------------------------------- #
binarios = []
dados = []
ocultos = []

# Pacotes que carregam módulos por nome, em tempo de execução: o analisador
# estático não os enxerga.
for pacote in (
    "ctranslate2",
    "faster_whisper",      # traz os modelos ONNX do VAD Silero em `assets/`
    "onnxruntime",
    "av",
    "speechbrain",
    "torchaudio",
    "tkinterdnd2",         # a extensão tkdnd é Tcl, não Python
):
    extra_bin, extra_dados, extra_ocultos = collect_all(pacote)
    binarios += extra_bin
    dados += extra_dados
    ocultos += extra_ocultos

# O torch inteiro pesa 300 MB; só os binários e o que ele importa dinamicamente.
torch_bin, torch_dados, torch_ocultos = collect_all("torch")
binarios += torch_bin
dados += torch_dados
ocultos += torch_ocultos

# Recursos do próprio aplicativo: stopwords do resumo e o ícone da nuvem.
dados += collect_data_files("lauda", includes=["resources/**"])

# ffmpeg e ffprobe ao lado do executável. `resolve_tools()` procura na pasta do
# aplicativo antes de olhar o PATH do sistema.
for arquivo in sorted(FFMPEG_BIN.glob("*.dll")):
    binarios.append((str(arquivo), "."))
for nome in ("ffmpeg.exe", "ffprobe.exe"):
    binarios.append((str(FFMPEG_BIN / nome), "."))

# O icone da janela: sem ele o Tk desenha a pena dele na barra de titulo.
dados.append((str(RAIZ / "assets" / "lauda.ico"), "assets"))

dados.append((str(RAIZ / "packaging" / "LICENCAS.txt"), "."))

# --------------------------------------------------------------------------- #
analise = Analysis(
    [str(RAIZ / "packaging" / "entrada.py")],
    pathex=[str(RAIZ / "src")],
    binaries=binarios,
    datas=dados,
    hiddenimports=ocultos + ["lauda.desktop"],
    hookspath=[],
    runtime_hooks=[],
    # Peso morto para este aplicativo: a interface web, as ferramentas de
    # documentação e o conjunto de testes.
    excludes=[
        "gradio",
        "gradio_client",
        "reportlab",
        "pypdf",
        "pypdfium2",
        "pytest",
        "mypy",
        "ruff",
        "matplotlib",
        "IPython",
        "notebook",
        "torch.distributed",
        "torch.testing",
    ],
    noarchive=False,
)


# --------------------------------------------------------------------------- #
# Poda: o que o torch traz e nunca é usado em tempo de execução
# --------------------------------------------------------------------------- #
# São os cabeçalhos C++ e as bibliotecas de link, necessários apenas para quem
# vai COMPILAR uma extensão do torch. Além dos ~90 MB, eles trazem os caminhos
# mais longos do pacote — e caminho longo demais faz o instalador falhar em
# máquina com nome de usuário grande (limite de 260 caracteres do Windows).
def _descartavel(destino: str) -> bool:
    caminho = destino.replace("\\", "/")
    if caminho.startswith(("torch/include/", "torch/test/", "torch/utils/benchmark/")):
        return True
    if caminho.startswith("torch/") and caminho.endswith((".lib", ".h", ".hpp", ".cuh")):
        return True
    # Licenças de dependências de terceiros do torch: caminho fundo e sem uso
    # (as licenças que importam estão em LICENCAS.txt).
    return "dist-info/licenses/third_party/" in caminho


analise.datas = [item for item in analise.datas if not _descartavel(item[0])]
analise.binaries = [item for item in analise.binaries if not _descartavel(item[0])]

pyz = PYZ(analise.pure)

exe = EXE(
    pyz,
    analise.scripts,
    [],
    exclude_binaries=True,
    name="Lauda Local",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX faz antivírus reclamar sem economizar quase nada
    console=False,      # aplicativo de janela: nada de console preto atrás
    icon=str(RAIZ / "assets" / "lauda.ico"),
)

coll = COLLECT(
    exe,
    analise.binaries,
    analise.datas,
    strip=False,
    upx=False,
    name="Lauda Local",
)
