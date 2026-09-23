"""Gera o guia do front-end (docs/Lauda-Local-Front-End.pdf).

    python scripts/make_frontend.py

Duas metades: como a interface foi construída (para entender o que existe) e
como pedir mudanças nela (para escrever um prompt que produza a alteração certa
sem quebrar o resto).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from _pdf_common import (
    AMBER,
    AMBER_LIGHT,
    ARROW,
    FONT,
    INK,
    INK_SOFT,
    PAGE_MARGIN,
    ROOT,
    RULE,
    TEAL,
    S,
    bullets,
    code,
    grid,
    note,
    para,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents

from lauda import APP_NAME, APP_VERSION

OUTPUT = ROOT / "docs" / "Lauda-Local-Front-End.pdf"
W = 170 * mm


class Doc(BaseDocTemplate):
    """Capa escura + miolo com rodapé e sumário navegável."""

    def __init__(self, path: str) -> None:
        super().__init__(
            path, pagesize=A4,
            title=f"{APP_NAME} {ARROW} Front-end",
            author=APP_NAME,
            subject="Como a interface foi feita e como pedir mudanças nela",
            creator=f"{APP_NAME} {APP_VERSION}",
            leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
            topMargin=18 * mm, bottomMargin=18 * mm,
        )
        width, height = A4
        self.addPageTemplates([
            PageTemplate(
                id="cover",
                frames=[Frame(0, 0, width, height, id="c", leftPadding=0,
                              rightPadding=0, topPadding=0, bottomPadding=0)],
                onPage=self._cover,
            ),
            PageTemplate(
                id="body",
                frames=[Frame(self.leftMargin, self.bottomMargin,
                              width - 2 * PAGE_MARGIN, height - 36 * mm, id="b")],
                onPage=self._body,
            ),
        ])
        self._counter = 0

    def _cover(self, canvas, doc) -> None:
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setFillColor(AMBER_LIGHT)
        canvas.rect(0, height - 6 * mm, width, 6 * mm, stroke=0, fill=1)
        canvas.restoreState()

    def _body(self, canvas, doc) -> None:
        width, _ = A4
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(PAGE_MARGIN, 14 * mm, width - PAGE_MARGIN, 14 * mm)
        canvas.setFont(FONT, 8)
        canvas.setFillColor(INK_SOFT)
        canvas.drawString(PAGE_MARGIN, 10 * mm, f"{APP_NAME} {APP_VERSION} — front-end")
        canvas.drawRightString(width - PAGE_MARGIN, 10 * mm, str(canvas.getPageNumber() - 1))
        canvas.restoreState()

    def beforeDocument(self) -> None:
        self._counter = 0

    def afterFlowable(self, flowable) -> None:
        if not isinstance(flowable, Paragraph) or flowable.style.name not in ("h1", "h2"):
            return
        text = flowable.getPlainText()
        if text == "Sumário":
            return
        self._counter += 1
        key = f"f{self._counter}"
        self.canv.bookmarkPage(key)
        level = 0 if flowable.style.name == "h1" else 1
        self.notify("TOCEntry", (level, text, self.page - 1, key))
        self.canv.addOutlineEntry(text, key, level=level, closed=False)


def h(text: str, level: str = "h1") -> Paragraph:
    return Paragraph(text, S[level])


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = Doc(str(OUTPUT))
    story: list = []

    # ------------------------------------------------------------------ capa --
    story += [
        Spacer(1, 80 * mm),
        para(APP_NAME, "cover_title"),
        para("Front-end", "cover_sub"),
        Spacer(1, 4 * mm),
        para(
            "Como a interface foi construída<br/>"
            "e como escrever um prompt para mudá-la.",
            "cover_sub",
        ),
        Spacer(1, 45 * mm),
        para(
            f"Versão {APP_VERSION}  |  {date.today().strftime('%d/%m/%Y')}<br/>"
            "Documento para quem vai alterar a tela",
            "cover_meta",
        ),
        NextPageTemplate("body"),
        PageBreak(),
    ]

    toc = TableOfContents()
    toc.levelStyles = [S["toc1"], S["toc2"]]
    toc.dotsMinLevel = 0
    story += [h("Sumário"), Spacer(1, 3 * mm), toc, PageBreak()]

    # =================================================================== 1 ====
    story += [
        h("1. O que é o front-end deste projeto"),
        para(
            "A interface do Lauda Local é uma <b>janela nativa do Windows</b>, "
            "desenhada com Tkinter. Não existe navegador, não existe servidor local, "
            "não existe HTML, CSS ou JavaScript em lugar nenhum. Isso foi um requisito "
            "explícito: o aplicativo tinha de abrir uma janela própria, não uma página "
            "web em localhost.",
            "lead",
        ),
        para(
            "A consequência prática é que <b>tudo o que você veria como CSS aqui é "
            "código Python</b>. Não há folha de estilo para editar: cores moram em um "
            "dataclass, formas são desenhadas em um Canvas, e o layout é declarado com "
            "os gerenciadores de geometria do Tk (<font name='Mono' size='9'>grid</font> "
            "e <font name='Mono' size='9'>pack</font>). Quem for pedir uma mudança "
            "precisa falar nesses termos — é disso que trata a segunda metade deste "
            "documento."
        ),
        h("Os três arquivos que formam a interface", "h2"),
        grid(
            ["Arquivo", "Linhas", "Responsabilidade"],
            [
                ["theme.py", "215",
                 "As duas paletas (clara e escura), a detecção do tema do Windows e a "
                 "preferência salva do usuário. <b>Nenhuma cor deve existir fora daqui.</b>"],
                ["widgets.py", "1750",
                 "Os widgets arredondados desenhados em Canvas: cartão, botão, "
                 "navegação lateral, zona de soltar, interruptor, trilha de etapas, "
                 "barra de progresso, controle deslizante, barra de rolagem, moldura "
                 "de campo — e os ícones de traço."],
                ["desktop.py", "1480",
                 "A janela: monta o layout, aplica o tema, lê o que o usuário escolheu, "
                 "dispara o processamento em outra thread e mostra o resultado."],
            ],
            widths=[30 * mm, 16 * mm, W - 46 * mm],
        ),
        Spacer(1, 3 * mm),
        note(
            "Só esses três",
            "Qualquer mudança visual acontece dentro deles. Se um pedido de alteração de "
            "tela levar você a mexer em <b>pipeline.py</b>, <b>runner.py</b> ou "
            "<b>report.py</b>, o pedido provavelmente misturou aparência com "
            "comportamento — vale separar em dois.",
            AMBER,
        ),
        h("A árvore da janela", "h2"),
        para(
            "É útil ter esse desenho na cabeça antes de pedir qualquer coisa, porque "
            "quase todo pedido é, no fundo, “mexa neste galho”:"
        ),
        code([
            "root (Tk)",
            " +-- outer",
            "      +-- nav (SideNav, 158 px)  7 paginas + versao e estado no pe",
            "      +-- content   mostra a pagina escolhida na barra lateral",
            "           +-- tab_job        Novo trabalho",
            "           |    +-- cartao esquerdo   DropZone + linha do arquivo",
            "           |    +-- cartao direito    idioma, qualidade, recursos, saida",
            "           |    +-- rodape   botao Processar + Stepper + progresso",
            "           +-- tab_report     Relatorio  (+ abrir pasta / abrir / copiar)",
            "           +-- tab_plain      Transcricao (uma aba por arquivo)",
            "           +-- tab_files      Arquivos   (ultimo trabalho + historico)",
            "           +-- tab_limits     Desempenho (Resumo/Limites/Diagnostico)",
            "           +-- tab_help       Ajuda          (o passo a passo)",
            "           +-- tab_settings   Configuracoes  (tema, preferencias, Ollama)",
        ]),
        PageBreak(),
    ]

    # =================================================================== 2 ====
    story += [
        h("2. A camada de tema"),
        para(
            "<font name='Mono' size='9'>Theme</font> é um dataclass congelado com 21 "
            "cores nomeadas <b>pela função, não pela cor</b>. Existem duas instâncias "
            "prontas: <font name='Mono' size='9'>LIGHT</font> e "
            "<font name='Mono' size='9'>DARK</font>. Trocar de tema é trocar a instância "
            "e repintar — não há um segundo conjunto de estilos.",
            "lead",
        ),
        grid(
            ["Token", "Para que serve", "Claro", "Escuro"],
            [
                ["canvas", "Fundo da janela", "#F4F6FA", "#0F1218"],
                ["paper", "Fundo dos painéis e cartões", "#FFFFFF", "#171B23"],
                ["surface", "Áreas internas (zona de soltar)", "#F7F9FC", "#1C222C"],
                ["sidebar", "Fundo da barra lateral", "#EDF0F5", "#12161D"],
                ["nav_active", "Item de navegação atual", "#FFFFFF", "#232A36"],
                ["field", "Fundo de campos de entrada", "#FFFFFF", "#1F242E"],
                ["ink", "Texto principal", "#12151C", "#E8EAF0"],
                ["ink_soft", "Texto secundário e dicas", "#4A5163", "#9AA3B4"],
                ["line", "Bordas e divisórias", "#D9DEE7", "#2B313D"],
                ["muted", "Interruptor desligado, etapa pendente", "#BFC7D4", "#3B4351"],
                ["accent", "Títulos de passo, aba ativa", "#1F7A73", "#5ECDC3"],
                ["accent_warm", "Avisos", "#B26A00", "#FFB02E"],
                ["danger", "Erros", "#B3261E", "#FF6B60"],
                ["success", "Conclusão", "#1F7A73", "#5ECDC3"],
                ["button / _active / _text", "Botão comum", "#EDF0F5", "#242A35"],
                ["primary / _active / _text", "Botão Processar", "#1F7A73", "#2A8C84"],
                ["preview_bg / preview_fg", "Área de pré-visualização", "#FFFFFF", "#12151C"],
                ["selection / selection_text", "Texto selecionado", "#CDE7E4", "#2A4C4A"],
            ],
            widths=[40 * mm, W - 40 * mm - 46 * mm, 23 * mm, 23 * mm],
        ),
        PageBreak(),
        h("O que mais mora em theme.py", "h2"),
        *bullets([
            "<font name='Mono' size='9'>detect_system_theme()</font> — lê a chave "
            "<font name='Mono' size='9'>AppsUseLightTheme</font> do registro do Windows "
            "para o modo <b>auto</b>.",
            "<font name='Mono' size='9'>load_choice()</font> / "
            "<font name='Mono' size='9'>save_choice()</font> — a preferência vai para "
            "<font name='Mono' size='9'>~/.lauda/ui.json</font>, junto dos limites "
            "de máquina. Gravação preserva as outras chaves do arquivo.",
            "<font name='Mono' size='9'>apply_titlebar()</font> — pinta a barra de "
            "título de escuro via <font name='Mono' size='9'>DwmSetWindowAttribute</font>. "
            "É a única parte da janela que o Tk não desenha.",
        ]),
        Spacer(1, 3 * mm),
        note(
            "A regra que sustenta o modo escuro",
            "Nenhum arquivo além de <b>theme.py</b> pode conter um código hexadecimal de "
            "cor. Se um widget novo precisar de um tom que não existe na paleta, o "
            "caminho é criar um token novo nos dois temas — nunca escrever a cor no "
            "lugar onde ela é usada. Um teste verifica que as duas paletas têm "
            "exatamente os mesmos campos.",
            TEAL,
        ),
        PageBreak(),
    ]

    # =================================================================== 3 ====
    story += [
        h("3. Os widgets arredondados"),
        para(
            "O ttk não desenha cantos arredondados. Não é questão de configuração: "
            "o desenho de cada widget vem do tema nativo, e nenhum dos temas disponíveis "
            "arredonda nada. Para conseguir o visual pedido, os widgets foram "
            "<b>redesenhados sobre <font name='Mono' size='9'>tk.Canvas</font></b>, que "
            "aceita qualquer forma.",
            "lead",
        ),
        h("Como as bordas ficam lisas", "h2"),
        para(
            "O Canvas do Tk não faz antialiasing — um canto arredondado feito de "
            "polígono sai serrilhado. A solução foi desenhar a superfície como imagem "
            "com o <b>Pillow em 4x</b> e reduzir: o resultado fica liso. Sem Pillow "
            "instalado, o código cai para o polígono suavizado do próprio Tk, mais feio "
            "mas funcional. Nenhuma dependência nova virou obrigatória por causa disso."
        ),
        h("Catálogo", "h2"),
        grid(
            ["Classe", "Substitui", "O que ganha", "API relevante"],
            [
                ["RoundedSurface", "—",
                 "Base de todos: desenha a superfície e se repinta ao redimensionar",
                 "set_surface(), redraw()"],
                ["RoundedCard", "ttk.Frame",
                 "Painel com canto redondo e borda fina; o conteúdo vai em "
                 "<font name='Mono' size='8'>.body</font>",
                 "apply_theme()"],
                ["RoundedButton", "ttk.Button",
                 "Botão com hover, estado pressionado e variante principal",
                 "configure(state=), cget(), invoke por clique"],
                ["RoundedProgress", "ttk.Progressbar",
                 "Barra com trilha e preenchimento arredondados",
                 "configure(value=, maximum=)"],
                ["NavItem / SideNav", "ttk.Notebook",
                 "Barra lateral com ícone e rótulo; troca a página mostrada",
                 "add(frame, text, icon), select(frame)"],
                ["DropZone", "—",
                 "Área de soltar/escolher arquivo, com moldura tracejada e nuvem",
                 "command, set_active(), set_texts()"],
                ["ToggleSwitch", "ttk.Checkbutton",
                 "Interruptor deslizante com o rótulo à esquerda",
                 "variable, text, command"],
                ["Stepper", "—",
                 "Trilha das cinco etapas do processamento, no rodapé",
                 "set_current(index), current"],
                ["tinted_icon", "—",
                 "Carrega um PNG e o repinta com a cor do tema; o arquivo entra só "
                 "como forma (é a nuvem da zona de soltar)",
                 "tinted_icon(caminho, tam, cor)"],
                ["draw_icon", "—",
                 "Os ícones de traço (nuvem, pasta, engrenagem, play…) desenhados em "
                 "linhas, para acompanharem a cor do tema",
                 "draw_icon(canvas, nome, x, y, tam, cor)"],
                ["RoundedSlider", "ttk.Scale",
                 "Trilha arredondada com botão circular",
                 "get(), set(), command"],
                ["RoundedField", "—",
                 "Moldura arredondada para hospedar Entry e Combobox do ttk, que ficam "
                 "sem borda própria",
                 "attach(widget)"],
                ["RoundedScrollbar", "ttk.Scrollbar",
                 "Barra fina, sem setas, com cursor em pílula; some quando não há o que "
                 "rolar",
                 "set(first, last) e “moveto” no command"],
            ],
            widths=[30 * mm, 26 * mm, W - 30 * mm - 26 * mm - 40 * mm, 40 * mm],
        ),
        Spacer(1, 3 * mm),
        h("Os dois contratos que todo widget novo precisa honrar", "h2"),
        para(
            "<b>1. Um método <font name='Mono' size='9'>apply_theme(...)</font>.</b> "
            "Como o widget é pintado no Canvas, o ttk não alcança as cores dele: quem "
            "repinta é a própria janela, chamando esse método na troca de tema. Sem ele, "
            "o widget fica com a cor do tema anterior — o defeito clássico dessa "
            "abordagem."
        ),
        para(
            "<b>2. A fatia da API do ttk que o aplicativo usa.</b> "
            "<font name='Mono' size='9'>RoundedButton</font> aceita "
            "<font name='Mono' size='9'>configure(state=...)</font>, "
            "<font name='Mono' size='9'>cget()</font> e indexação; "
            "<font name='Mono' size='9'>RoundedScrollbar</font> fala o protocolo de "
            "rolagem do Tk. Isso é o que permitiu trocar os widgets sem reescrever quem "
            "os usa — nem os testes."
        ),
        code([
            "def apply_theme(self, *, fill, outline, parent_bg) -> None:",
            "    self.set_surface(fill=fill, outline=outline, parent_bg=parent_bg)",
            "",
            "# parent_bg existe porque o Canvas nao e transparente: o widget precisa",
            "# saber a cor de quem esta atras dele para o canto redondo nao aparecer",
            "# recortado sobre um retangulo de cor errada.",
        ]),
        PageBreak(),
    ]

    # =================================================================== 4 ====
    story += [
        h("4. A janela"),
        para(
            "<font name='Mono' size='9'>LaudaApp</font> concentra a montagem e o "
            "estado da tela. A ordem de construção importa e é sempre a mesma:",
            "lead",
        ),
        code([
            "__init__",
            "   +-- colecoes de repintura vazias   (_cards, _buttons, _checks, ...)",
            "   +-- carrega tema e limites salvos  (~/.lauda/ui.json)",
            "   +-- _build_window   titulo, tamanho 1200x800, icone",
            "   +-- _build_fonts    Segoe UI 9/10/11/21 e Consolas 10",
            "   +-- _build_layout   header + cartao esquerdo + cartao direito",
            "   +-- _apply_theme    pinta tudo pela primeira vez",
        ]),
        Spacer(1, 3 * mm),
        h("As coleções de repintura", "h2"),
        para(
            "Este é o detalhe mais importante para quem vai mexer na tela. Como os "
            "widgets arredondados são invisíveis para o ttk, a janela guarda listas de "
            "tudo o que precisa repintar à mão:"
        ),
        code([
            "self._cards       RoundedCard        self._switches    interruptores",
            "self._buttons     RoundedButton      self._scrollbars  barras de rolagem",
            "self._fields      Entry e Combobox   self._texts       areas de previa",
            "self._dividers    linhas divisorias  self._primary_buttons  cor primaria",
            "self._panels / self._shells / self._sidebar_panels   frames, por cor",
            "",
            "Fora das listas, repintados um a um: self.nav, self.stepper e self.drop.",
        ]),
        Spacer(1, 3 * mm),
        note(
            "A regra de ouro ao adicionar um widget",
            "Todo widget desenhado em Canvas que entrar na tela precisa ser "
            "<b>acrescentado à coleção correspondente</b> e repintado dentro de "
            "<b>_apply_theme</b>. Esquecer disso não quebra nenhum teste hoje — só "
            "aparece quando alguém troca de tema e um pedaço da tela fica com a cor "
            "errada. É o erro mais fácil de cometer neste código.",
            AMBER,
        ),
        h("A ponte entre o processamento e a tela", "h2"),
        para(
            "O Tk é de thread única: só a thread da interface pode tocar em um widget. "
            "O processamento roda em outra thread (e, por baixo, em outro processo), "
            "então a comunicação passa por uma fila:"
        ),
        code([
            "worker (thread)  --->  queue.Queue  --->  _drain_queue (a cada 80 ms)",
            "                                            +-- _on_progress",
            "                                            +-- _on_recovery",
            "                                            +-- _on_done / _on_error",
        ]),
        Spacer(1, 3 * mm),
        para(
            "Todo pedido que envolva mostrar algo <b>durante</b> o processamento passa "
            "por aqui: a mensagem entra na fila e o desenho acontece do lado da "
            "interface. Tocar num widget direto da thread de trabalho trava a janela de "
            "forma intermitente."
        ),
        PageBreak(),
    ]

    # =================================================================== 5 ====
    story += [
        h("5. O que trava mudanças"),
        para(
            "São as regras que o código já segue. Um prompt que não as mencione tende a "
            "produzir uma alteração que funciona na tela e quebra em outro lugar.",
            "lead",
        ),
        grid(
            ["Regra", "Por quê", "Como é verificada"],
            [
                ["Interface, logs e textos em português do Brasil; identificadores de "
                 "código em inglês",
                 "Foi definido no início do projeto e vale para tudo",
                 "Revisão; o texto da tela está todo em desktop.py"],
                ["Nenhuma cor fora de theme.py",
                 "É o que faz o modo escuro funcionar por inteiro",
                 "test_paletas_tem_os_mesmos_campos, "
                 "test_todas_as_cores_sao_hexadecimais_validas"],
                ["Nenhum widget retangular do ttk na tela",
                 "Checkbutton, Scrollbar, Notebook, Scale e Progressbar do ttk não "
                 "arredondam",
                 "test_nenhum_widget_retangular_do_ttk_sobrou varre a árvore da janela"],
                ["Todo widget em Canvas entra numa coleção e é repintado",
                 "Senão fica com a cor do tema anterior",
                 "test_alterna_para_o_modo_escuro, test_o_modo_escuro_repinta_a_previa"],
                ["A troca de tema não pode apagar o que está na tela",
                 "O usuário troca de tema depois de processar",
                 "test_troca_de_tema_nao_apaga_o_relatorio"],
                ["ruff e mypy limpos",
                 "É a barra de qualidade do projeto inteiro",
                 "ruff check src tests scripts; mypy src"],
            ],
            widths=[46 * mm, 44 * mm, W - 90 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 3 * mm),
        note(
            "Os testes de interface não abrem janela",
            "A raiz é criada e escondida com <b>withdraw()</b>, e o laço de eventos é "
            "bombeado à mão. Isso tem uma consequência: o Tk não entrega eventos de "
            "mouse a widget não mapeado, e a geometria devolve 1x1. Por isso os testes "
            "de clique chamam o tratador com um evento montado à mão, depois de "
            "verificar que o vínculo existe. Vale saber disso antes de pedir “um teste "
            "que clique no botão”.",
            TEAL,
        ),
        PageBreak(),
    ]

    # =================================================================== 6 ====
    story += [
        h("6. Como montar um prompt para alterar o front-end"),
        para(
            "Um bom prompt de front-end aqui responde cinco perguntas. Faltando "
            "qualquer uma delas, o resultado costuma ser uma mudança que <i>parece</i> "
            "certa na captura de tela e erra em outro estado — no tema oposto, com a "
            "janela menor, durante o processamento, ou no arquivo de preferências.",
            "lead",
        ),
        grid(
            ["Parte", "O que dizer", "Exemplo de frase"],
            [
                ["1. Alvo",
                 "Onde na tela, com o nome que o código usa",
                 "“no cartão da esquerda, no passo 3”"],
                ["2. Comportamento",
                 "O que deve acontecer, incluindo os estados",
                 "“desabilitado enquanto processa; volta ao normal ao terminar”"],
                ["3. Restrições",
                 "As regras do projeto que valem para esse pedido",
                 "“usando token do theme.py, sem widget retangular do ttk”"],
                ["4. Prova",
                 "Como você quer confirmar que funcionou",
                 "“teste novo e captura nos dois temas”"],
                ["5. Escopo",
                 "O que não é para mexer",
                 "“não mude o pipeline nem o formato do relatório”"],
            ],
            widths=[34 * mm, 50 * mm, W - 84 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        PageBreak(),
        h("6.1  O bloco de contexto para colar", "h2"),
        para(
            "Quando a conversa começa do zero — sessão nova, outra ferramenta, outra "
            "pessoa — cole isto antes do pedido. Ele economiza a rodada de perguntas e "
            "evita as três suposições erradas mais comuns (que é web, que dá para usar "
            "ttk normalmente, e que cor se escreve onde é usada):"
        ),
        code([
            "Contexto do projeto (Lauda Local, front-end):",
            "",
            "- Aplicativo de janela nativa em Python + Tkinter. Nao e web: nao existe",
            "  HTML, CSS, JS, navegador nem servidor local. Nao proponha nenhum.",
            "- A interface vive em 3 arquivos, dentro de src/lauda/:",
            "    theme.py     paletas clara e escura (21 tokens de cor) + preferencia",
            "    widgets.py   widgets arredondados desenhados em tk.Canvas",
            "    desktop.py   a janela: layout, tema, eventos, resultado",
            "- A tela e uma barra lateral (SideNav) com 6 paginas. A primeira,",
            "  'Novo trabalho', tem a zona de soltar (DropZone), o painel de recursos",
            "  com interruptores (ToggleSwitch) e o rodape com o botao Processar mais",
            "  a trilha de etapas (Stepper).",
            "- O ttk nao arredonda canto, entao Card, Button, Nav, Progress, Slider,",
            "  Switch e Scrollbar sao classes proprias em widgets.py. Nao volte a usar",
            "  ttk.Checkbutton, ttk.Scrollbar, ttk.Notebook, ttk.Scale nem",
            "  ttk.Progressbar: existe um teste que falha se algum aparecer na tela.",
            "- Nenhuma cor hexadecimal fora de theme.py. Precisando de um tom novo,",
            "  crie um token nos dois temas.",
            "- Todo widget desenhado em Canvas precisa de apply_theme() e precisa ser",
            "  adicionado a colecao correspondente (self._cards, self._buttons,",
            "  self._switches, self._fields, self._scrollbars, ...) para ser repintado",
            "  em _apply_theme.",
            "- Textos da interface em portugues do Brasil; identificadores em ingles.",
            "- Nenhum PNG colorido na interface: icone entra como forma e recebe a cor",
            "  do tema (widgets.tinted_icon), senao fica errado num dos dois modos.",
            "- O Tk e de thread unica: o que vem do processamento chega pela fila e e",
            "  desenhado em _drain_queue, nunca direto da thread de trabalho.",
            "- Barra de qualidade: ruff check src tests scripts e mypy src limpos,",
            "  e pytest tests passando.",
        ]),
        PageBreak(),
    ]

    # ------------------------------------------------------------------------ #
    story += [
        h("6.2  O vocabulário que faz diferença", "h2"),
        para(
            "Pedidos de interface falham por ambiguidade de nome mais do que por "
            "ambiguidade de intenção. À esquerda, como a vontade costuma sair; à "
            "direita, o termo que o código entende."
        ),
        grid(
            ["Se você quer dizer", "Diga assim", "Onde isso mexe"],
            [
                ["“o menu do lado”", "a barra lateral (SideNav)",
                 "desktop.py, _build_layout"],
                ["“a área pontilhada”", "a zona de soltar (DropZone)",
                 "desktop.py, _build_file_card"],
                ["“as chavinhas”", "os interruptores (ToggleSwitch) do painel Recursos",
                 "desktop.py, _build_options_card"],
                ["“as bolinhas do rodapé”", "a trilha de etapas (Stepper)",
                 "desktop.py, _build_action_bar"],
                ["“a bolinha que arrasta”", "o controle deslizante (RoundedSlider) da "
                 "aba Desempenho", "desktop.py, _build_limits_tab"],
                ["“a caixa de texto grande”", "a pré-visualização (tk.Text de "
                 "_text_tab)", "desktop.py, _text_tab"],
                ["“a cor do fundo”", "o token canvas (janela) ou paper (painéis)",
                 "theme.py"],
                ["“a cor do texto apagado”", "o token ink_soft", "theme.py"],
                ["“mais arredondado”", "aumentar o radius do widget", "widgets.py"],
                ["“mais espaçado”", "aumentar padding/pady no grid", "desktop.py"],
                ["“o botão verde”", "o botão principal (primary), o Processar",
                 "desktop.py + theme.py"],
            ],
            widths=[48 * mm, 62 * mm, W - 110 * mm],
            mono_columns=(),
            strong_columns=(1,),
        ),
        PageBreak(),
        h("6.3  Receitas por tipo de mudança", "h2"),
        para(
            "O que citar no prompt, de acordo com o que se quer. A coluna da direita é "
            "o que evita a resposta incompleta."
        ),
        grid(
            ["Você quer", "Arquivos", "Não esqueça de pedir"],
            [
                ["Mudar uma cor",
                 "theme.py",
                 "o valor nos <b>dois</b> temas, claro e escuro"],
                ["Mudar o arredondamento ou a espessura de um widget",
                 "widgets.py",
                 "que o padrão continue valendo para todas as instâncias, ou que vire "
                 "parâmetro"],
                ["Acrescentar um campo, botão ou opção",
                 "desktop.py",
                 "entrar na coleção de repintura, aparecer em _apply_theme e, se for "
                 "opção de processamento, chegar em JobOptions"],
                ["Reorganizar o layout",
                 "desktop.py",
                 "que continue legível em 1200x800 e que nada seja cortado — a coluna "
                 "esquerda já ficou apertada uma vez"],
                ["Criar um widget arredondado novo",
                 "widgets.py + desktop.py",
                 "apply_theme(), coleção, teste, e a fatia da API do ttk que ele "
                 "substitui"],
                ["Mudar um texto da tela",
                 "desktop.py",
                 "conferir se o mesmo texto aparece no README ou nos PDFs"],
                ["Acrescentar uma página",
                 "desktop.py",
                 "nav.add(frame, texto, ícone) e o fundo do frame no token paper"],
                ["Mudar o comportamento em tempo de processamento",
                 "desktop.py",
                 "passar pela fila e por _drain_queue, nunca direto da thread"],
            ],
            widths=[46 * mm, 34 * mm, W - 80 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        PageBreak(),
    ]

    # ------------------------------------------------------------------------ #
    story += [
        h("6.4  Três pedidos, do vago ao acionável", "h2"),
        para(
            "O mesmo desejo, escrito de três formas. A diferença entre eles é "
            "exatamente o que sobra de trabalho de adivinhação."
        ),
        h("Vago", "h3"),
        code([
            "deixa a tela mais bonita",
        ]),
        para(
            "Não diz onde, não diz o que incomoda, não diz como conferir. A resposta "
            "provável é uma mudança grande em lugar nenhum específico — e é preciso "
            "desfazer boa parte dela.",
            "note",
        ),
        h("Melhor", "h3"),
        code([
            "deixa os cantos mais arredondados na parte de dentro do painel direito",
        ]),
        para(
            "Já dá para agir: identifica a região. Ainda falta dizer quais elementos "
            "incomodam e como saber que terminou.",
            "note",
        ),
        h("Acionável", "h3"),
        code([
            "No cartao da direita, as caixas de selecao e a barra de rolagem ainda",
            "aparecem quadradas.",
            "",
            "Troque as duas por widgets desenhados em Canvas, no mesmo estilo dos que",
            "ja existem em widgets.py:",
            "  - a caixinha com canto arredondado e um 'v', no lugar do quadrado com",
            "    'x' do tema clam;",
            "  - a barra de rolagem fina, sem setas, cursor em pilula, sumindo quando",
            "    nao ha o que rolar.",
            "",
            "Restricoes: cores so por token do theme.py, nos dois temas; as duas",
            "classes precisam de apply_theme() e de entrar nas colecoes de repintura;",
            "a barra de rolagem tem de falar o protocolo do Tk para entrar no lugar da",
            "ttk.Scrollbar sem mudar o tk.Text.",
            "",
            "Prova: um teste para cada comportamento novo, mais um teste que falhe se",
            "algum widget retangular do ttk voltar para a arvore da janela. Rode ruff,",
            "mypy e a suite inteira, e me mostre uma captura nos dois temas.",
            "",
            "Nao mexa no pipeline nem no formato do relatorio.",
        ]),
        Spacer(1, 2 * mm),
        para(
            "Esse último é, quase literalmente, o pedido que originou o trabalho "
            "descrito neste documento. Ele cabe em vinte linhas e não deixa decisão "
            "importante em aberto.",
            "note",
        ),
        PageBreak(),
    ]

    # ------------------------------------------------------------------------ #
    story += [
        h("6.5  Padrões de pedido que costumam dar errado", "h2"),
        grid(
            ["Pedido", "O que acontece", "Como reescrever"],
            [
                ["“usa a cor #2E86AB no botão”",
                 "A cor entra escrita no desktop.py e o modo escuro fica com um botão "
                 "fora da paleta",
                 "“crie um token para essa cor no theme.py, com uma variante escura, e "
                 "use no botão”"],
                ["“coloca um Notebook com mais abas”",
                 "Volta o widget retangular do ttk e um teste falha",
                 "“acrescente abas ao RoundedTabs que já existe”"],
                ["“atualiza a barra de progresso dentro do processamento”",
                 "Toca em widget de outra thread; a janela trava de forma intermitente",
                 "“emita um evento de progresso na fila e desenhe em _drain_queue”"],
                ["“faz igual ao aplicativo X”",
                 "Sem referência concreta, cada elemento é reinterpretado",
                 "Descreva o elemento e o comportamento; se tiver imagem, anexe e diga "
                 "o que dela importa"],
                ["“arruma o CSS”",
                 "Não existe CSS; o tempo vai embora explicando isso",
                 "“ajuste o estilo em theme.py / widgets.py”"],
                ["“deixa responsivo”",
                 "Termo de web; aqui não há breakpoint",
                 "“garanta que nada seja cortado com a janela em 1200x800 e ao "
                 "maximizar”"],
            ],
            widths=[46 * mm, 50 * mm, W - 96 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 4 * mm),
        h("6.6  Antes de enviar e depois de receber", "h2"),
        h("No pedido", "h3"),
        *bullets([
            "Nomeei o lugar com o nome que o código usa?",
            "Descrevi o comportamento nos estados — normal, desabilitado, processando, "
            "erro?",
            "Disse que vale nos <b>dois</b> temas?",
            "Pedi teste e captura de tela?",
            "Disse o que <b>não</b> é para mexer?",
        ]),
        h("Na entrega", "h3"),
        *bullets([
            "A suíte inteira passou, não só os testes de interface.",
            "<font name='Mono' size='9'>ruff check src tests scripts</font> e "
            "<font name='Mono' size='9'>mypy src</font> limpos.",
            "Nenhum hexadecimal novo fora do <b>theme.py</b>.",
            "Alternar o tema com a tela cheia de conteúdo não deixa nada com a cor "
            "antiga nem apaga o relatório.",
            "A janela em 1200x800 não corta o botão Processar.",
            "As capturas em <b>docs/</b> ainda correspondem ao que a tela mostra.",
        ]),
        PageBreak(),
    ]

    # =================================================================== 7 ====
    story += [
        h("7. Anexo: mapa rápido"),
        h("Onde fica o quê", "h2"),
        grid(
            ["Quero mexer em", "Vá para"],
            [
                ["A barra lateral e as páginas", "desktop.py — _build_layout"],
                ["Diagnóstico da máquina", "hardware.py — assess_machine"],
                ["O aviso de máquina fraca", "desktop.py — show_machine_dialog"],
                ["A zona de soltar e o arquivo", "desktop.py — _build_file_card"],
                ["Recursos, idioma, qualidade, pasta", "desktop.py — _build_options_card"],
                ["Processar e a trilha de etapas", "desktop.py — _build_action_bar"],
                ["Idioma e qualidade (as listas)", "desktop.py — LANGUAGES, MODEL_LABELS"],
                ["Texto de “Como usar”", "desktop.py — STEPS_TEXT"],
                ["Páginas de texto e pré-visualização", "desktop.py — _text_page"],
                ["Sliders de CPU, RAM, GPU e VRAM", "desktop.py — _build_limits_page"],
                ["Nomes das etapas", "desktop.py — STAGE_LABELS, PIPELINE_STEPS"],
                ["Fontes", "desktop.py — _build_fonts"],
                ["Toda a repintura de tema", "desktop.py — _apply_theme"],
                ["Formas e desenho", "widgets.py"],
                ["Cores", "theme.py — LIGHT e DARK"],
            ],
            widths=[70 * mm, W - 70 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 4 * mm),
        h("Comandos", "h2"),
        code([
            "python -m lauda.desktop        abre a janela",
            "pytest tests/test_desktop.py -q     so os testes de interface",
            "pytest tests -q                     a suite inteira",
            "ruff check src tests scripts        estilo",
            "mypy src                            tipos",
            "python scripts/make_frontend.py     regera este PDF",
        ]),
        Spacer(1, 4 * mm),
        note(
            "Os outros documentos",
            "<b>Como usar e pra que serve</b> é o guia do usuário; <b>Manual</b> cobre "
            "a operação em detalhe; <b>Decisões técnicas</b> explica o porquê da "
            "arquitetura inteira, incluindo transcrição, diarização e desempenho. Este "
            "aqui trata só da tela.",
            TEAL,
        ),
    ]

    doc.multiBuild(story)
    return OUTPUT


def main() -> int:
    path = build()
    print(f"guia do front-end: {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
