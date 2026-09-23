"""Estilo e blocos compartilhados pelos PDFs do projeto.

Usado por `make_manual.py` (manual completo) e `make_quickstart.py` (guia
rápido), para que os dois documentos tenham exatamente a mesma identidade
visual e a mesma tipografia.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "lauda.png"

# --------------------------------------------------------------------------- #
# Identidade visual (mesma paleta do ícone)
# --------------------------------------------------------------------------- #
INK = colors.HexColor("#12151C")
INK_SOFT = colors.HexColor("#3A4152")
AMBER = colors.HexColor("#B26A00")
AMBER_LIGHT = colors.HexColor("#FFB02E")
TEAL = colors.HexColor("#2A8C84")
RULE = colors.HexColor("#D6DAE3")
BAND = colors.HexColor("#F2F4F8")
CODE_BG = colors.HexColor("#12151C")
CODE_FG = colors.HexColor("#E8EAF0")

PAGE_MARGIN = 20 * mm


# --------------------------------------------------------------------------- #
# Fontes
# --------------------------------------------------------------------------- #
def _register_fonts() -> tuple[str, str, bool]:
    """Devolve (fonte de texto, fonte monoespaçada, unicode_ok)."""
    candidates = [
        # (família, regular, negrito, itálico, negrito-itálico)
        ("UI", "segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
        ("UI", "calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
        ("UI", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf",
         "DejaVuSans-BoldOblique.ttf"),
    ]
    search = [
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/Library/Fonts"),
    ]

    def find(name: str) -> Path | None:
        for directory in search:
            path = directory / name
            if path.exists():
                return path
        return None

    for family, regular, bold, italic, bold_italic in candidates:
        files = [find(name) for name in (regular, bold, italic, bold_italic)]
        if not all(files):
            continue
        pdfmetrics.registerFont(TTFont(family, str(files[0])))
        pdfmetrics.registerFont(TTFont(f"{family}-Bold", str(files[1])))
        pdfmetrics.registerFont(TTFont(f"{family}-Italic", str(files[2])))
        pdfmetrics.registerFont(TTFont(f"{family}-BoldItalic", str(files[3])))
        pdfmetrics.registerFontFamily(
            family,
            normal=family,
            bold=f"{family}-Bold",
            italic=f"{family}-Italic",
            boldItalic=f"{family}-BoldItalic",
        )
        mono = "Courier"
        for mono_regular, mono_bold in (
            ("consola.ttf", "consolab.ttf"),
            ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
        ):
            found = find(mono_regular)
            found_bold = find(mono_bold)
            if found and found_bold:
                pdfmetrics.registerFont(TTFont("Mono", str(found)))
                pdfmetrics.registerFont(TTFont("Mono-Bold", str(found_bold)))
                pdfmetrics.registerFontFamily(
                    "Mono", normal="Mono", bold="Mono-Bold", italic="Mono",
                    boldItalic="Mono-Bold",
                )
                mono = "Mono"
                break
        return family, mono, True

    return "Helvetica", "Courier", False


FONT, MONO, UNICODE_OK = _register_fonts()

ARROW = "\u2192" if UNICODE_OK else "->"
BULLET = "\u2022" if UNICODE_OK else "-"


# --------------------------------------------------------------------------- #
# Estilos
# --------------------------------------------------------------------------- #
def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}

    styles["body"] = ParagraphStyle(
        "body", parent=base["Normal"], fontName=FONT, fontSize=10, leading=15.5,
        textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7,
    )
    styles["lead"] = ParagraphStyle(
        "lead", parent=styles["body"], fontSize=11.5, leading=18, textColor=INK_SOFT,
        spaceAfter=12, alignment=TA_JUSTIFY,
    )
    styles["h1"] = ParagraphStyle(
        "h1", parent=base["Heading1"], fontName=f"{FONT}-Bold", fontSize=19, leading=24,
        textColor=INK, spaceBefore=0, spaceAfter=10,
    )
    styles["h2"] = ParagraphStyle(
        "h2", parent=base["Heading2"], fontName=f"{FONT}-Bold", fontSize=12.5, leading=17,
        textColor=AMBER, spaceBefore=14, spaceAfter=5,
    )
    styles["h3"] = ParagraphStyle(
        "h3", parent=base["Heading3"], fontName=f"{FONT}-Bold", fontSize=10.5, leading=14,
        textColor=TEAL, spaceBefore=10, spaceAfter=3,
    )
    styles["bullet"] = ParagraphStyle(
        "bullet", parent=styles["body"], leftIndent=12, bulletIndent=2,
        spaceAfter=3, alignment=TA_JUSTIFY,
    )
    styles["code"] = ParagraphStyle(
        "code", parent=base["Normal"], fontName=MONO, fontSize=8.6, leading=12.6,
        textColor=CODE_FG, leftIndent=0, spaceAfter=0, spaceBefore=0,
    )
    styles["cell"] = ParagraphStyle(
        "cell", parent=base["Normal"], fontName=FONT, fontSize=8.8, leading=12.4,
        textColor=INK,
    )
    styles["cellhead"] = ParagraphStyle(
        "cellhead", parent=styles["cell"], fontName=f"{FONT}-Bold", textColor=colors.white,
    )
    styles["cellmono"] = ParagraphStyle(
        "cellmono", parent=styles["cell"], fontName=MONO, fontSize=8.2, textColor=AMBER,
    )
    styles["cellstrong"] = ParagraphStyle(
        "cellstrong", parent=styles["cell"], fontName=f"{FONT}-Bold", textColor=INK,
    )
    styles["note"] = ParagraphStyle(
        "note", parent=styles["body"], fontSize=9.3, leading=13.6, textColor=INK_SOFT,
        leftIndent=8, rightIndent=8, spaceBefore=2, spaceAfter=2,
    )
    styles["cover_title"] = ParagraphStyle(
        "cover_title", parent=base["Title"], fontName=f"{FONT}-Bold", fontSize=34,
        leading=40, textColor=colors.white, alignment=TA_CENTER, spaceAfter=6,
    )
    styles["cover_sub"] = ParagraphStyle(
        "cover_sub", parent=base["Normal"], fontName=FONT, fontSize=13, leading=19,
        textColor=colors.HexColor("#A8B0C0"), alignment=TA_CENTER,
    )
    styles["cover_meta"] = ParagraphStyle(
        "cover_meta", parent=styles["cover_sub"], fontSize=9.5, leading=15,
        textColor=colors.HexColor("#7C8496"),
    )
    styles["toc1"] = ParagraphStyle(
        "toc1", fontName=f"{FONT}-Bold", fontSize=10.5, leading=20, textColor=INK,
    )
    styles["toc2"] = ParagraphStyle(
        "toc2", fontName=FONT, fontSize=9.5, leading=15, leftIndent=14, textColor=INK_SOFT,
    )
    return styles


S = _styles()


# --------------------------------------------------------------------------- #
# Blocos reutilizáveis
# --------------------------------------------------------------------------- #
def para(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, S[style])


def bullets(items: list[str]) -> list[Paragraph]:
    return [Paragraph(item, S["bullet"], bulletText=BULLET) for item in items]


def code(lines: str | list[str]) -> Table:
    """Bloco de código com fundo escuro."""
    if isinstance(lines, str):
        lines = lines.strip("\n").split("\n")
    body = [[Paragraph(line.replace(" ", "&nbsp;") or "&nbsp;", S["code"])] for line in lines]
    table = Table(body, colWidths=[None])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
        ])
    )
    return table


def note(title: str, text: str, accent=TEAL) -> Table:
    """Caixa de destaque com barra colorida à esquerda."""
    content = [[Paragraph(f"<b>{title}</b><br/>{text}", S["note"])]]
    table = Table(content, colWidths=[None])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BAND),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, accent),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    return table


def grid(headers: list[str], rows: list[list[str]], widths: list[float],
         mono_columns: tuple[int, ...] = (0,),
         strong_columns: tuple[int, ...] = ()) -> Table:
    """Tabela com cabecalho escuro e zebrado.

    `mono_columns` para nomes tecnicos (comandos, arquivos, flags);
    `strong_columns` para rotulos em linguagem natural, que ficam estranhos em
    fonte monoespacada.
    """
    head = [Paragraph(text, S["cellhead"]) for text in headers]
    body = [head]
    for row in rows:
        cells = []
        for index, cell in enumerate(row):
            if index in mono_columns:
                style = "cellmono"
            elif index in strong_columns:
                style = "cellstrong"
            else:
                style = "cell"
            cells.append(Paragraph(cell, S[style]))
        body.append(cells)

    table = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("LINEBELOW", (0, 0), (-1, 0), 0, INK),
    ]
    for index in range(1, len(body)):
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), BAND))
    table.setStyle(TableStyle(style))
    return table


