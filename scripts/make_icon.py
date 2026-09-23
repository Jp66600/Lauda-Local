"""Gera o ícone do aplicativo (assets/lauda.ico) com Pillow.

    python scripts/make_icon.py

Desenho: quadrado escuro arredondado com uma forma de onda em âmbar — a mesma
ideia do produto (áudio entra, laudo sai). Sem dependência nova: o Pillow já
vem junto com o Gradio.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND = (18, 21, 28, 255)
ACCENT = (255, 176, 46, 255)
ACCENT_DIM = (94, 205, 195, 255)


def draw_icon(size: int = 512) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    radius = int(size * 0.22)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BACKGROUND)

    # Forma de onda: barras verticais com alturas de uma senoide amortecida.
    bars = 11
    margin = size * 0.18
    usable = size - 2 * margin
    bar_width = usable / (bars * 2 - 1)
    center = size / 2

    for index in range(bars):
        phase = index / (bars - 1)
        envelope = math.sin(math.pi * phase) ** 0.7
        wobble = 0.55 + 0.45 * math.sin(phase * math.pi * 3.0)
        height = usable * 0.5 * envelope * wobble
        height = max(height, bar_width)

        x0 = margin + index * bar_width * 2
        color = ACCENT if index % 2 == 0 else ACCENT_DIM
        draw.rounded_rectangle(
            (x0, center - height / 2, x0 + bar_width, center + height / 2),
            radius=bar_width / 2,
            fill=color,
        )
    return image


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_icon(512)

    ico_path = ASSETS / "lauda.ico"
    master.save(ico_path, format="ICO", sizes=[(size, size) for size in SIZES])

    png_path = ASSETS / "lauda.png"
    master.resize((256, 256), Image.LANCZOS).save(png_path, format="PNG")

    print(f"ícone : {ico_path} ({ico_path.stat().st_size} bytes)")
    print(f"png   : {png_path} ({png_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
