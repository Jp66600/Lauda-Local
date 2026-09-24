"""Gera o guia rápido em PDF (docs/Lauda-Local-Guia-Rapido.pdf).

    python scripts/make_quickstart.py

É o passo a passo curto, para quem nunca abriu o aplicativo. O manual completo
fica em `make_manual.py`.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _pdf_common import (
    AMBER,
    FONT,
    ICON,
    INK,
    INK_SOFT,
    PAGE_MARGIN,
    ROOT,
    RULE,
    TEAL,
    bullets,
    grid,
    note,
    para,
)
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from lauda import APP_NAME, APP_VERSION

OUTPUT = ROOT / "docs" / "Lauda-Local-Guia-Rapido.pdf"

STEP_NUMBER = ParagraphStyle(
    "step_number", fontName=f"{FONT}-Bold", fontSize=30, leading=34,
    textColor=colors.white, alignment=TA_CENTER,
)
STEP_TITLE = ParagraphStyle(
    "step_title", fontName=f"{FONT}-Bold", fontSize=14.5, leading=19, textColor=INK,
    spaceAfter=4,
)
STEP_BODY = ParagraphStyle(
    "step_body", fontName=FONT, fontSize=10.5, leading=16, textColor=INK_SOFT,
)
BIG_TITLE = ParagraphStyle(
    "big_title", fontName=f"{FONT}-Bold", fontSize=26, leading=31, textColor=INK,
)
SUB = ParagraphStyle(
    "sub", fontName=FONT, fontSize=12, leading=18, textColor=INK_SOFT, spaceAfter=4,
)
SECTION = ParagraphStyle(
    "section", fontName=f"{FONT}-Bold", fontSize=14, leading=19, textColor=AMBER,
    spaceBefore=14, spaceAfter=6,
)

CONTENT_WIDTH = A4[0] - 2 * PAGE_MARGIN


def step(number: int, title: str, body: str, colour=TEAL) -> KeepTogether:
    """Passo grande, com o número num quadrado colorido."""
    cell_number = Paragraph(str(number), STEP_NUMBER)
    cell_text = [Paragraph(title, STEP_TITLE), Paragraph(body, STEP_BODY)]

    table = Table(
        [[cell_number, cell_text]],
        colWidths=[20 * mm, CONTENT_WIDTH - 20 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colour),
            ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
            ("VALIGN", (1, 0), (1, 0), "TOP"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
            ("RIGHTPADDING", (0, 0), (0, 0), 0),
            ("TOPPADDING", (0, 0), (0, 0), 10),
            ("BOTTOMPADDING", (0, 0), (0, 0), 10),
            ("LEFTPADDING", (1, 0), (1, 0), 14),
            ("TOPPADDING", (1, 0), (1, 0), 6),
            ("BOTTOMPADDING", (1, 0), (1, 0), 10),
        ])
    )
    return KeepTogether([table, Spacer(1, 5 * mm)])


def _footer(canvas, doc) -> None:
    width, _ = A4
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(PAGE_MARGIN, 14 * mm, width - PAGE_MARGIN, 14 * mm)
    canvas.setFont(FONT, 8)
    canvas.setFillColor(INK_SOFT)
    canvas.drawString(PAGE_MARGIN, 10 * mm, f"{APP_NAME} {APP_VERSION} — guia rápido")
    canvas.drawRightString(width - PAGE_MARGIN, 10 * mm, str(canvas.getPageNumber()))
    canvas.restoreState()


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        title=f"{APP_NAME} — Guia rápido",
        author=APP_NAME,
        subject="Passo a passo para transcrever um áudio ou vídeo",
        leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
        topMargin=18 * mm, bottomMargin=20 * mm,
    )

    story: list = []

    # ------------------------------------------------------------- cabeçalho --
    head_cells = [[]]
    if ICON.exists():
        logo = Image(str(ICON), width=17 * mm, height=17 * mm)
        head_cells = [[logo, [Paragraph(APP_NAME, BIG_TITLE),
                              Paragraph("Como usar e pra que serve", SUB)]]]
        header = Table(head_cells, colWidths=[22 * mm, CONTENT_WIDTH - 22 * mm], hAlign="LEFT")
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (0, 0), 0),
        ]))
        story.append(header)
    else:  # pragma: no cover - sem o ícone gerado
        story += [Paragraph(APP_NAME, BIG_TITLE), Paragraph("Guia rápido", SUB)]

    story.append(Spacer(1, 7 * mm))

    # -------------------------------------------------------- pra que serve --
    story.append(Paragraph("Pra que serve", SECTION))
    story.append(
        para(
            "Você tem uma gravação — uma entrevista, uma reunião, uma aula, um vídeo — "
            "e precisa do que foi <b>dito</b>, em texto. O Lauda Local transforma o "
            "arquivo num relatório: a transcrição completa com a marcação de tempo, "
            "quem falou cada trecho, o idioma, a qualidade do áudio e os dados "
            "técnicos do arquivo."
        )
    )
    story += bullets([
        "<b>Entrevistas e reuniões</b> — texto com marcação de tempo e separação de "
        "quem fala, para citar e localizar no áudio.",
        "<b>Vídeos para publicar</b> — a legenda .srt sai sozinha; o .vtt, se pedir.",
        "<b>Aulas e podcasts</b> — texto corrido para ler, buscar e resumir.",
        "<b>Arquivo e conferência</b> — dados técnicos e um código de integridade "
        "(SHA-256) que muda se o arquivo for alterado.",
    ])
    story.append(Spacer(1, 3 * mm))
    story.append(note(
        "E o que ele não é",
        "Não é editor de vídeo, não traduz e não substitui revisão humana. E, "
        "principalmente: <b>não envia nada para a internet</b>. Tudo acontece no seu "
        "computador.",
    ))
    story.append(Spacer(1, 5 * mm))

    # ------------------------------------------------------------- abrir ------
    story.append(Paragraph("Abrir o aplicativo", SECTION))
    story.append(
        para(
            "Dê <b>dois cliques</b> no atalho <b>Lauda Local</b> que está na sua "
            "Área de Trabalho. Abre uma janela própria do programa — não é site, não "
            "abre navegador, não precisa de internet."
        )
    )
    story.append(
        para(
            "Prefere trabalhar no escuro? O botão <b>Modo escuro</b> fica no canto "
            "superior direito da janela. O aplicativo já abre no tema do Windows."
        )
    )
    story.append(Spacer(1, 5 * mm))

    # ------------------------------------------------------------- 4 passos ---
    story.append(Paragraph("Depois, quatro passos", SECTION))
    story.append(step(
        1, "Coloque o arquivo na tela",
        "Na página <b>Novo trabalho</b>, arraste o áudio ou vídeo para a área "
        "pontilhada — ou clique nela para procurar no computador. Serve mp4, mkv, "
        "mov, avi, mp3, wav, m4a e praticamente qualquer outro formato.",
    ))
    story.append(step(
        2, "Confira onde vai salvar",
        "No painel da direita, embaixo, está a <b>pasta de saída</b> — é onde o "
        "<b>.txt</b> vai ficar. Já vem preenchida com a pasta <b>saida</b>; se "
        "estiver bom, nem precisa mexer. O botão <b>Alterar</b> abre o explorador "
        "de arquivos do Windows.",
    ))
    story.append(step(
        3, "Ligue o que quiser, se quiser",
        "Se você <b>sabe o idioma</b> do áudio, selecione — melhora bastante o "
        "resultado. Se for entrevista ou reunião, ligue a chavinha "
        "<b>Diarização de falantes</b>. Todo o resto pode ficar como está.",
        AMBER,
    ))
    story.append(step(
        4, "Clique em Processar",
        "A trilha no rodapé mostra em que etapa ele está. Quando terminar, "
        "<b>o relatório aparece na própria janela</b>, na página Relatório — e os "
        "arquivos já estão salvos na pasta que você escolheu.",
    ))


    # ------------------------------------------------------------- resultado --
    story.append(Paragraph("O que você recebe", SECTION))
    story.append(
        para(
            "Para um arquivo chamado <b>entrevista.mp4</b>, a pasta de saída "
            "recebe:"
        )
    )
    story.append(grid(
        ["Arquivo", "O que é"],
        [
            ["entrevista.report.txt",
             "<b>O principal.</b> O laudo completo: dados do arquivo, qualidade do "
             "áudio, idioma e a transcrição com a marcação de tempo."],
            ["entrevista.transcript.txt",
             "Só o texto corrido, em parágrafos — para copiar e colar."],
            ["entrevista.data.json", "Os mesmos dados em formato de programa."],
            ["entrevista.srt", "A legenda, com os tempos de entrada e saída."],
            ["entrevista.vtt", "A mesma legenda para vídeo na web, se marcada."],
        ],
        widths=[52 * mm, CONTENT_WIDTH - 52 * mm],
    ))

    story.append(Spacer(1, 4 * mm))
    story.append(note(
        "Você não precisa abrir arquivo nenhum para ler",
        "O relatório aparece na própria janela do aplicativo. Os botões de baixo abrem "
        "a pasta, abrem o arquivo no bloco de notas ou copiam o texto inteiro.",
    ))

    # ------------------------------------------------------------- opções -----
    story.append(Paragraph("As opções, em português claro", SECTION))
    story.append(grid(
        ["Opção", "Marque quando..."],
        [
            ["Diarização de falantes",
             "for entrevista, reunião, podcast — qualquer coisa com mais de uma pessoa. "
             "O relatório passa a dizer SPEAKER_00, SPEAKER_01 e quanto tempo cada um falou."],
            ["Marcar o tempo das palavras",
             "você for editar legenda com precisão. Deixa o arquivo bem maior."],
            ["Gerar legenda .vtt",
             "você for publicar o vídeo numa página web. A legenda .srt, que "
             "serve para todo o resto, já vem ligada."],
            ["Extrair miniaturas",
             "quiser uma noção rápida do ritmo de edição do vídeo."],
            ["Integrar com Ollama",
             "você já tiver o Ollama instalado. Sem ele, essa opção simplesmente não faz "
             "nada — não quebra nada."],
        ],
        widths=[48 * mm, CONTENT_WIDTH - 48 * mm],
        mono_columns=(),
        strong_columns=(0,),
    ))

    story.append(Paragraph("Qualidade: qual escolher", SECTION))
    story.append(grid(
        ["Opção", "Use quando"],
        [
            ["Rascunho (tiny)", "só quiser conferir rapidamente se o arquivo funciona."],
            ["Recomendado (small)", "for o dia a dia. <b>É o padrão e serve para quase tudo.</b>"],
            ["Alta qualidade (large-v3-turbo)",
             "o material for importante e você puder esperar um pouco mais."],
            ["Máxima (large-v3)",
             "precisar do melhor possível. Pode não caber na memória da placa de vídeo — "
             "nesse caso o programa desce sozinho para uma opção menor e avisa."],
        ],
        widths=[56 * mm, CONTENT_WIDTH - 56 * mm],
        mono_columns=(),
        strong_columns=(0,),
    ))


    # ------------------------------------------------------------- problemas --
    story.append(Paragraph("Se algo não sair como esperado", SECTION))
    story.append(grid(
        ["Situação", "O que fazer"],
        [
            ["A primeira vez está demorando muito",
             "É normal: o modelo está sendo baixado (uma vez só). Deixe terminar. Da "
             "próxima vez funciona até sem internet."],
            ["A transcrição saiu vazia",
             "Talvez não haja fala no arquivo. Veja no relatório, na seção 3, se "
             "<b>Fala detectada</b> está como <b>não</b>. Música e ruído são descartados "
             "de propósito."],
            ["Apareceu texto repetido ou sem sentido",
             "Costuma ser áudio muito baixo ou muito silêncio. Tente um modelo melhor, "
             "ou regrave com o microfone mais perto."],
            ["Errou nomes próprios e siglas",
             "Isso é esperado. O manual completo mostra como passar uma lista de nomes "
             "para o programa acertar mais."],
            ["Escreveu [INDISPONÍVEL] em alguma parte",
             "Não é erro: é o programa avisando que aquele bloco não pôde ser feito, e "
             "dizendo o motivo na mesma linha. O resto do relatório continua válido."],
            ["Quero conferir se está tudo instalado",
             "Existe um comando de diagnóstico. Ele está explicado no manual completo, "
             "no capítulo 9."],
        ],
        widths=[56 * mm, CONTENT_WIDTH - 56 * mm],
        mono_columns=(),
        strong_columns=(0,),
    ))

    story.append(Paragraph("A página Desempenho", SECTION))
    story += bullets([
        "<b>Ele confere o seu computador ao abrir.</b> Processador, memória, placa de "
        "vídeo, espaço em disco e ffmpeg. O resultado fica nesta página. Se a máquina "
        "for fraca demais, ele avisa antes de você perder tempo e deixa você escolher "
        "entre fechar e continuar assim mesmo.",
        "<b>Limitar o quanto ele usa da máquina.</b> Controles de processador, memória "
        "e placa de vídeo. Baixe-os se quiser continuar trabalhando enquanto ele "
        "processa; o resumo embaixo diz na hora o efeito da escolha.",
        "<b>Modo rápido.</b> Transcreve em lotes: medimos cerca de <b>2x mais rápido</b> "
        "na placa de vídeo. Em troca, os trechos saem bem mais longos — o que piora a "
        "legenda e a separação de quem fala. Deixe desligado se for legendar.",
        "<b>Se travar, ele se recupera sozinho.</b> O progresso é salvo a cada etapa. "
        "Se o processamento morrer no meio, o programa encerra, volta do último ponto "
        "salvo e tenta de novo — sem transcrever tudo outra vez.",
    ])

    story.append(Paragraph("Está ocupando muito espaço?", SECTION))
    story.append(
        para(
            "Os modelos de transcrição e as bibliotecas de aceleração ocupam vários "
            "gigabytes. Para ver a conta detalhada e liberar o que não usa, existe um "
            "comando — está explicado no manual completo, no capítulo de desempenho."
        )
    )

    story.append(Paragraph("Três dicas que melhoram muito o resultado", SECTION))
    story += bullets([
        "<b>Diga o idioma</b> em vez de deixar no automático. É o ajuste que mais ajuda, "
        "principalmente em áudios curtos ou com ruído.",
        "<b>Áudio bom vale mais que modelo grande.</b> Microfone perto da boca e ambiente "
        "silencioso melhoram mais a transcrição do que trocar de modelo.",
        "<b>Revise sempre.</b> A transcrição é um rascunho muito adiantado, não um "
        "documento final. Números, nomes e siglas são o que mais escapa.",
    ])

    story.append(Spacer(1, 3 * mm))
    story.append(note(
        "Nada sai do seu computador",
        "O arquivo não é enviado para lugar nenhum — nem para servidor, nem para nuvem, "
        "nem para “treinar o modelo”. O único momento em que o programa usa a "
        "internet é no download inicial dos modelos.",
    ))

    story.append(Spacer(1, 4 * mm))
    story.append(
        para(
            f"<font color='#7C8496'>Manual completo: docs/Lauda-Local-Manual.pdf "
            f"&nbsp;|&nbsp; decisões técnicas: "
            f"docs/Lauda-Local-Decisoes-Tecnicas.pdf &nbsp;|&nbsp; "
            f"{APP_NAME} {APP_VERSION}, {date.today().strftime('%d/%m/%Y')}</font>",
            "note",
        )
    )

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return OUTPUT


def main() -> int:
    path = build()
    print(f"guia rápido: {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
