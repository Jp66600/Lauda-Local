"""Gera o manual do usuário em PDF (docs/Lauda-Local-Manual.pdf).

    python scripts/make_manual.py

O estilo (fontes, cores, tabelas, caixas) vive em `_pdf_common.py`, compartilhado
com o guia rápido.
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
    ICON,
    INK,
    INK_SOFT,
    MONO,
    PAGE_MARGIN,
    ROOT,
    RULE,
    TEAL,
    UNICODE_OK,
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
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents

from lauda import APP_NAME, APP_VERSION

OUTPUT = ROOT / "docs" / "Lauda-Local-Manual.pdf"


# --------------------------------------------------------------------------- #
# Documento (capa sem rodapé, miolo com rodapé + sumário navegável)
# --------------------------------------------------------------------------- #
class Manual(BaseDocTemplate):
    def __init__(self, path: str) -> None:
        super().__init__(
            path,
            pagesize=A4,
            title=f"{APP_NAME} {ARROW} Manual do usuário",
            author=APP_NAME,
            subject="Manual de uso do Lauda Local",
            creator=f"{APP_NAME} {APP_VERSION}",
            leftMargin=PAGE_MARGIN, rightMargin=PAGE_MARGIN,
            topMargin=18 * mm, bottomMargin=18 * mm,
        )
        width, height = A4
        cover_frame = Frame(0, 0, width, height, id="cover",
                            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        body_frame = Frame(
            self.leftMargin, self.bottomMargin,
            width - 2 * PAGE_MARGIN, height - 18 * mm - 18 * mm, id="body",
        )
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[cover_frame], onPage=self._cover_page),
            PageTemplate(id="body", frames=[body_frame], onPage=self._body_page),
        ])
        self._counter = 0

    def _cover_page(self, canvas, doc) -> None:
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(INK)
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setFillColor(AMBER_LIGHT)
        canvas.rect(0, height - 6 * mm, width, 6 * mm, stroke=0, fill=1)
        canvas.restoreState()

    def _body_page(self, canvas, doc) -> None:
        width, _ = A4
        canvas.saveState()
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(PAGE_MARGIN, 14 * mm, width - PAGE_MARGIN, 14 * mm)
        canvas.setFont(FONT, 8)
        canvas.setFillColor(INK_SOFT)
        canvas.drawString(PAGE_MARGIN, 10 * mm, f"{APP_NAME} {APP_VERSION}")
        canvas.drawRightString(width - PAGE_MARGIN, 10 * mm, str(canvas.getPageNumber() - 1))
        canvas.restoreState()

    def beforeDocument(self) -> None:
        # multiBuild roda o documento mais de uma vez; sem zerar o contador, as
        # chaves dos marcadores mudam a cada passada e o sumario nunca converge.
        self._counter = 0

    def afterFlowable(self, flowable) -> None:
        """Alimenta o sumário com os títulos marcados."""
        if not isinstance(flowable, Paragraph):
            return
        style = flowable.style.name
        if style not in ("h1", "h2"):
            return
        text = flowable.getPlainText()
        if text == "Sumário":  # o sumario nao se lista
            return
        level = 0 if style == "h1" else 1
        self._counter += 1
        key = f"toc-{self._counter}"
        self.canv.bookmarkPage(key)
        self.notify("TOCEntry", (level, text, self.page - 1, key))
        self.canv.addOutlineEntry(text, key, level=level, closed=False)


def heading(text: str, level: str = "h1") -> Paragraph:
    return Paragraph(text, S[level])


# --------------------------------------------------------------------------- #
# Conteúdo
# --------------------------------------------------------------------------- #
def cover() -> list:
    story: list = [Spacer(1, 58 * mm)]
    if ICON.exists():
        logo = Image(str(ICON), width=32 * mm, height=32 * mm)
        logo.hAlign = "CENTER"
        story += [logo, Spacer(1, 12 * mm)]
    story += [
        para(APP_NAME, "cover_title"),
        para("Manual do usuário", "cover_sub"),
        Spacer(1, 4 * mm),
        para(
            "Transcrição e análise de áudio e vídeo<br/>"
            "100% no seu computador, sem nuvem e sem mensalidade.",
            "cover_sub",
        ),
        Spacer(1, 40 * mm),
        para(
            f"Versão {APP_VERSION}  |  {date.today().strftime('%d/%m/%Y')}<br/>"
            "Windows, macOS e Linux",
            "cover_meta",
        ),
    ]
    return story


def toc_page() -> list:
    toc = TableOfContents()
    toc.levelStyles = [S["toc1"], S["toc2"]]
    toc.dotsMinLevel = 0
    return [heading("Sumário"), Spacer(1, 3 * mm), toc, PageBreak()]


def section_intro() -> list:
    return [
        heading("1. O que é o Lauda Local"),
        para(
            "Você aponta um arquivo de áudio ou vídeo. O aplicativo devolve um "
            "<b>laudo em texto</b> com tudo o que dá para extrair localmente: metadados "
            "técnicos do arquivo, diagnóstico da qualidade do áudio, idioma detectado, "
            "a transcrição completa com marcação de tempo e, quando você pedir, quem "
            "falou cada trecho.",
            "lead",
        ),
        para(
            "Nenhum byte do seu arquivo sai da máquina. Os modelos de inteligência "
            "artificial são baixados uma única vez e, a partir daí, funcionam offline "
            "para sempre. Não há API paga, conta, cota nem envio para servidor nenhum."
        ),
        heading("O que ele faz", "h2"),
        *bullets([
            "Lê os metadados completos do arquivo (formato, codecs, resolução, tags, capítulos).",
            "Extrai e normaliza o áudio automaticamente, mesmo que a entrada seja vídeo.",
            "Avalia a qualidade: volume médio, picos, saturação, quanto é silêncio, quanto é fala.",
            "Transcreve offline com o Whisper, com filtro de voz para reduzir invenção de texto.",
            "Detecta o idioma sozinho, ou usa o que você mandar.",
            "Marca o tempo de cada trecho e, opcionalmente, de cada palavra.",
            "Identifica quem fala (SPEAKER_00, SPEAKER_01...) quando você liga a diarização.",
            "Gera a legenda .srt de todo trabalho, e o .vtt se você pedir.",
            "Escolhe sozinho GPU ou CPU e reduz o modelo se faltar memória.",
        ]),
        heading("O que ele não faz", "h2"),
        *bullets([
            "Não é editor: não corta, não converte nem exporta mídia.",
            "Não traduz.",
            "Não envia nada para a nuvem, nem para \u201cmelhorar o modelo\u201d.",
            "Não substitui revisão humana: o Whisper erra com sotaque forte, ruído, "
            "música e falas sobrepostas.",
        ]),
        Spacer(1, 4 * mm),
        note(
            "A regra de ouro do relatório",
            "Se alguma etapa não puder rodar, o bloco correspondente não some do laudo: "
            "ele aparece como <b>[INDISPONÍVEL] Bloco: motivo</b>. Você sempre sabe o que "
            "faltou e por quê.",
        ),
        PageBreak(),
    ]

def section_open() -> list:
    return [
        heading("2. Como abrir"),
        para(
            "Há quatro formas de usar. Se você só quer transcrever um arquivo, use a "
            "primeira e pule o resto deste capítulo."
        ),
        heading("Forma 1 — atalho na Área de Trabalho (a normal)", "h2"),
        para(
            "Dê dois cliques no atalho <b>Lauda Local</b>. Abre uma <b>janela "
            "própria do programa</b>: não é site, não abre navegador, e não fica nenhuma "
            "janela preta de console atrás. Para encerrar, feche a janela."
        ),
        para(
            "Se o atalho ainda não existir, crie-o uma única vez, dentro da pasta do "
            "projeto:"
        ),
        code("powershell -ExecutionPolicy Bypass -File scripts\\create_shortcut.ps1"),
        heading("Forma 2 — a mesma janela, pelo terminal", "h2"),
        code(
            "cd C:\\Users\\PC\\Desktop\\projetos\\mediaintel-local\n"
            ".\\.venv\\Scripts\\lauda.exe app"
        ),
        heading("Forma 3 — interface no navegador (alternativa)", "h2"),
        para(
            "Existe também uma interface que roda no navegador, útil quando você quer "
            "acessar o aplicativo de outro computador da mesma rede. Ela exige o Gradio "
            "instalado e sobe um servidor local em 127.0.0.1:"
        ),
        code(".\\.venv\\Scripts\\lauda.exe ui"),
        heading("Forma 4 — linha de comando (para repetir e automatizar)", "h2"),
        para(
            "É a forma mais rápida quando você já sabe o que quer, e a única que dá para "
            "colocar em um script:"
        ),
        code(
            '.\\.venv\\Scripts\\lauda.exe run "C:\\videos\\entrevista.mp4" '
            "-m small -l pt --diarize -o .\\saida"
        ),
        Spacer(1, 4 * mm),
        note(
            "Atenção ao encadear comandos no Windows",
            "O PowerShell que vem no Windows (versão 5.1) <b>não aceita <font face='"
            + MONO
            + "'>&amp;&amp;</font></b> — ele responde \u201cO token '&amp;&amp;' não é um "
            "separador de instruções válido nesta versão\u201d. Use <font face='"
            + MONO
            + "'>;</font> para separar comandos.",
            AMBER,
        ),
        heading("A primeira execução é mais lenta", "h2"),
        para(
            "Na primeira vez que você usa um modelo, ele é baixado (de 75 MB a 1,5 GB, "
            "conforme o tamanho) e guardado na pasta <b>models</b>. Da segunda vez em "
            "diante, tudo roda offline e a espera some. O mesmo vale para o modelo de "
            "identificação de falantes."
        ),
        heading("Conferindo se está tudo certo", "h2"),
        para(
            "O comando abaixo faz um diagnóstico completo do ambiente: ffmpeg, placa de "
            "vídeo, memória, modelos já baixados, diarização e resumo local."
        ),
        code(".\\.venv\\Scripts\\lauda.exe doctor"),
        PageBreak(),
    ]


def section_interface() -> list:
    return [
        heading("3. A janela, campo a campo"),
        para(
            "A janela tem uma <b>barra lateral</b> com nove páginas. A primeira, "
            "<b>Novo trabalho</b>, é onde tudo acontece; as outras mostram o resultado "
            "e as preferências. Nada é enviado para lugar nenhum ao clicar em "
            "Processar — todo o trabalho acontece na sua máquina."
        ),
        heading("As nove páginas da barra lateral", "h2"),
        grid(
            ["Página", "Para que serve"],
            [
                ["Novo trabalho",
                 "Escolher o arquivo, ligar os recursos e processar."],
                ["Relatório",
                 "O laudo completo, com uma aba por arquivo processado."],
                ["Registro",
                 "O que o programa está fazendo agora, linha a linha."],
                ["Transcrição",
                 "O texto corrido, com uma aba por arquivo transcrito."],
                ["Legendas",
                 "As legendas geradas, com os tempos de entrada e saída."],
                ["Arquivos",
                 "O que foi gerado agora e o histórico de todos os trabalhos."],
                ["Desempenho", "Quanto da máquina o aplicativo pode usar."],
                ["Ajuda", "Este passo a passo, sempre à mão."],
                ["Configurações", "Tema, resumo das opções guardadas e "
                 "“Restaurar padrões”."],
            ],
            widths=[40 * mm, 130 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        heading("A página Novo trabalho, parte por parte", "h2"),
        grid(
            ["Onde", "O que fazer", "Detalhes"],
            [
                ["Área pontilhada",
                 "<b>Arraste</b> o áudio ou vídeo para dentro dela, ou <b>clique</b> "
                 "para abrir o explorador de arquivos do sistema.",
                 "Aceita qualquer áudio ou vídeo que o ffmpeg leia: mp4, mkv, mov, avi, "
                 "webm, mp3, wav, m4a, flac, ogg, opus e outros. Escolhido o arquivo, "
                 "aparece embaixo uma linha com miniatura, nome, tamanho e duração — e "
                 "um X para trocar."],
                ["Painel da direita",
                 "Idioma, qualidade e as chavinhas dos recursos.",
                 "Pode deixar tudo como está. O único ajuste que quase sempre compensa é "
                 "informar o idioma em vez de deixar no automático."],
                ["Pasta de saída",
                 "No pé do painel da direita. O botão <b>Alterar</b> abre o explorador.",
                 "É onde o .txt vai ficar. Já vem preenchida com a pasta <b>saida</b> do "
                 "projeto; você também pode digitar o caminho direto no campo."],
                ["Vários de uma vez",
                 "Solte (ou marque no explorador) quantos arquivos quiser.",
                 "O primeiro vai para o cartão e o resto entra numa <b>fila</b>, "
                 "mostrada logo abaixo. Eles rodam <b>um por vez</b>: dois modelos "
                 "carregados ao mesmo tempo brigam pela mesma memória e travam a "
                 "máquina. Pode soltar mais arquivos com o trabalho em andamento — vão "
                 "para o fim da fila. O botão <b>Esvaziar a fila</b> descarta quem ainda "
                 "não começou, sem interromper o que está rodando. A fila inteira "
                 "roda com as opções de quando você clicou em Processar: mexer num "
                 "interruptor no meio não muda os arquivos que ainda estão esperando."],
                ["Pausar",
                 "Com o trabalho em andamento, aparece ao lado de Processar.",
                 "Congela o processamento onde está: o uso de processador cai a zero e "
                 "o trabalho volta do mesmo ponto quando você clicar em <b>Retomar</b>. "
                 "A memória continua ocupada — pausar devolve o processador, não a RAM. "
                 "Fechar o aplicativo pausado perde a etapa em andamento, mas não o que "
                 "já foi transcrito."],
                ["Rodapé",
                 "O botão <b>Processar</b> e a trilha de cinco etapas.",
                 "A trilha acende conforme o trabalho anda: Arquivo, Pré-processamento, "
                 "Transcrição, Pós-processamento e Conclusão. O nome exato da etapa e a "
                 "porcentagem aparecem embaixo e no pé da barra lateral."],
            ],
            widths=[32 * mm, 62 * mm, 76 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        note(
            "O que você escolhe fica guardado",
            "Idioma, qualidade, os interruptores de recurso e a pasta de saída voltam "
            "como você deixou na última vez — ficam em "
            "<b>~/.lauda/ui.json</b>, junto do tema e dos limites de máquina. "
            "A página Configurações mostra o que está guardado e tem o botão "
            "<b>Restaurar padrões</b> para zerar tudo de uma vez.",
            TEAL,
        ),
        heading("Os recursos do painel da direita", "h2"),
        grid(
            ["Campo", "O que faz", "Quando mexer"],
            [
                ["Idioma",
                 "Deixe em <b>Detectar automaticamente</b> ou force um idioma.",
                 "Force sempre que souber qual é. Evita o erro clássico de o modelo "
                 "escolher o idioma errado em áudio curto ou com ruído."],
                ["Qualidade",
                 "Tamanho do modelo de transcrição, em linguagem simples. Maior significa "
                 "mais preciso e mais lento.",
                 "Deixe em Recomendado para o dia a dia. Suba em material importante."],
                ["Diarização de falantes",
                 "Cada trecho passa a vir com um rótulo (SPEAKER_00, SPEAKER_01...) e o "
                 "relatório ganha o tempo de fala de cada pessoa.",
                 "Entrevistas, reuniões, podcasts."],
                ["Marcar o tempo das palavras",
                 "Acrescenta ao laudo o Bloco C, com início, fim e confiança de cada "
                 "palavra.",
                 "Edição fina de legenda. Deixa o arquivo bem maior."],
                ["Gerar legenda .srt",
                 "<b>Já vem ligado.</b> A legenda é o Bloco B do laudo noutro "
                 "formato, e sai junto com ele.",
                 "Deixe ligado. Desligar só economiza algumas dezenas de KB."],
                ["Gerar legenda .vtt",
                 "A mesma legenda no formato que o vídeo em página web usa.",
                 "Quando for publicar o vídeo num site."],
                ["Tamanho das legendas",
                 "<b>Curtas</b> (1 a 2 s), <b>Equilibrada</b> (5 a 8 s, o padrão) ou "
                 "<b>Blocos longos</b> (até 1 min). Vale para .srt e .vtt.",
                 "Curtas para edição fina e karaokê — ficam bem melhores com “marcar "
                 "o tempo das palavras” ligado. Blocos longos quando você quer o "
                 "texto corrido dentro do player, não legenda de verdade."],
                ["Extrair miniaturas",
                 "Só para vídeo: conta as trocas de cena e salva uma miniatura a cada 30 "
                 "segundos numa pasta ao lado do relatório.",
                 "Para ter noção do ritmo de edição. Custa uma varredura extra do vídeo."],
                ["Integrar com Ollama",
                 "Se o Ollama estiver rodando na máquina, acrescenta resumo, tópicos, "
                 "itens de ação e citações.",
                 "Só faz efeito se você já usa o Ollama. Sem ele, o bloco fica marcado "
                 "como indisponível e nada quebra."],
            ],
            widths=[40 * mm, 66 * mm, 64 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        heading("As páginas de resultado", "h2"),
        para(
            "<b>Relatório</b>, <b>Transcrição</b> e <b>Legendas</b> são a mesma "
            "página com outro arquivo: uma faixa de abas no alto, uma para cada "
            "arquivo daquele tipo <b>que existe na pasta de saída</b> — inclusive "
            "os de outro dia. Clicar na aba troca o conteúdo; acima dele ficam o "
            "nome do arquivo de origem, a duração, o modelo e o caminho completo. "
            "A lista se atualiza ao abrir a página e ao terminar um trabalho, e o "
            "botão <b>Atualizar</b> serve para quando você mexer na pasta por fora."
        ),
        Spacer(1, 2 * mm),
        para(
            "Embaixo do texto, os mesmos três botões em todas: <b>Abrir o local do "
            "arquivo</b> (a pasta abre com o arquivo já selecionado, pronto para "
            "copiar), <b>Copiar o texto</b> e um terceiro que abre o laudo daquele "
            "trabalho — na própria página Relatório, ele abre o laudo que está na "
            "tela."
        ),
        Spacer(1, 2 * mm),
        para(
            "Na página <b>Legendas</b> há um botão a mais: <b>Gerar as que "
            "faltam</b>. Ele escreve a legenda dos trabalhos que você já "
            "processou, lendo os trechos do arquivo .data.json de cada um — os "
            "mesmos que o laudo imprime no Bloco B. Nada é transcrito de novo, e "
            "leva menos de um segundo para uma pasta inteira. Serve para o que foi "
            "processado antes de a legenda sair por padrão, e para trocar o tamanho "
            "das legendas sem refazer o trabalho: apague a legenda antiga, escolha "
            "o tamanho novo e clique. O que já existe nunca é sobrescrito."
        ),
        Spacer(1, 2 * mm),
        para(
            "<b>Registro</b> é página separada, e mostra o que está acontecendo "
            "agora: cada etapa aparece na hora em que acontece. Os dois botões dela "
            "abrem a pasta dos logs e copiam o registro — é o que eu peço quando "
            "alguém relata um problema."
        ),
        Spacer(1, 3 * mm),
        *bullets([
            "<b>Relatório</b> — o laudo completo de cada arquivo processado.",
            "<b>Registro</b> — o que está acontecendo agora, etapa por etapa.",
            "<b>Transcrição</b> — só o texto corrido, para ler ou copiar.",
            "<b>Legendas</b> — os arquivos .srt e .vtt, com os tempos como estão "
            "no arquivo, e o botão que cria as que faltam.",
            "<b>Arquivos</b> — em cima, a lista dos arquivos salvos e o resumo do "
            "processamento (tempo, velocidade, modelo, idioma, palavras, cobertura) com "
            "os avisos; embaixo, o <b>histórico</b> de todos os trabalhos já feitos.",
        ]),
        Spacer(1, 2 * mm),
        para(
            "O histórico tem uma linha por trabalho, do mais recente para o mais antigo, "
            "com quando, arquivo, duração, qualidade, onde rodou (CPU ou GPU), "
            "velocidade, cobertura, buracos, avisos, se teve resumo do Ollama e a "
            "<b>confiança</b> da transcrição. No fim vem “O que merece um olhar”: os "
            "trabalhos que falharam, os que tiveram bloco indisponível e os que "
            "cobriram menos de 95% do arquivo. Os dois botões do rodapé abrem o laudo "
            "mais recente e limpam a lista — limpar apaga só a lista, nunca os arquivos "
            "já gerados."
        ),
        note(
            "A confiança em uma palavra",
            "Vem do <b>avg_logprob</b> que o próprio modelo informa: quanto ele "
            "“acreditou” no que escreveu. O número sozinho engana (-0,28 parece "
            "ruim e é ótimo), então a coluna mostra primeiro a palavra — <b>alta</b>, "
            "<b>média</b> ou <b>baixa</b> — e o número depois. Confiança baixa costuma "
            "ser áudio ruim, idioma errado ou modelo pequeno demais, nessa ordem.",
            TEAL,
        ),
        Spacer(1, 2 * mm),
        heading("Ollama: verificar e baixar pela janela", "h2"),
        para(
            "A página Configurações mostra se o servidor do Ollama está no ar e se o "
            "modelo está baixado. Se não estiver, o botão <b>Baixar</b> faz o download "
            "ali mesmo, com a porcentagem e os gigabytes na tela — são cerca de 9 GB, "
            "e uma barra parada por vinte minutos seria indistinguível de travamento."
        ),
        heading("Quanto tempo ainda falta", "h2"),
        para(
            "A partir de 8% do trabalho, o aplicativo passa a estimar o que falta pelo "
            "ritmo já medido — e mostra isso no rodapé e embaixo da etapa atual. "
            "Antes desse ponto ele não arrisca: os primeiros segundos são gastos "
            "carregando o modelo, e uma conta feita ali diria algo como “faltam 3 "
            "horas” para um vídeo de cinco minutos."
        ),
        heading("Cobertura: o arquivo inteiro foi lido?", "h2"),
        para(
            "Todo relatório traz, na seção 5, quanto da duração do arquivo virou "
            "texto. É a única forma de saber que nada foi pulado: um relatório com "
            "texto correto pode, ainda assim, ter deixado dez minutos para trás — e "
            "não há como desconfiar só lendo o que está lá."
        ),
        para(
            "Trecho sem texto que é <b>silêncio</b> não conta como buraco: não há o "
            "que transcrever numa pausa. O aplicativo já mede onde estão os silêncios "
            "durante o diagnóstico de áudio e usa essa medida para separar as duas "
            "coisas. Sobra listado só o que tem som e mesmo assim não virou texto — "
            "com o horário de início e fim, para você conferir no vídeo."
        ),
        note(
            "Abaixo de 95% ele avisa",
            "A janela mostra quantos segundos ficaram de fora, e o aviso vai também "
            "para o log. Não é motivo para o trabalho falhar: vídeo com música longa "
            "ou trecho sem fala cai aí legitimamente. É informação para você decidir "
            "se vale reprocessar.",
            TEAL,
        ),
        heading("O diagnóstico da máquina", "h2"),
        para(
            "Ao abrir, o aplicativo mede cinco coisas e dá um veredito: "
            "<b>processador</b> (número de threads), <b>memória</b>, <b>placa de "
            "vídeo</b>, <b>espaço livre em disco</b> na pasta dos modelos e a presença "
            "do <b>ffmpeg</b>. O resultado fica na aba <b>Diagnóstico</b> da página "
            "Desempenho, item a item, sempre visível."
        ),
        grid(
            ["Veredito", "O que significa", "O que acontece"],
            [
                ["Boa / Dá conta", "Nada preocupa.", "Nada. O aviso não aparece."],
                ["Vai funcionar, mas devagar",
                 "Algum item está no limite — poucos núcleos, pouca RAM ou pouco disco.",
                 "Nada interrompe; o diagnóstico registra o motivo."],
                ["Não vai dar conta",
                 "Algum item está abaixo do mínimo, ou falta o ffmpeg.",
                 "Abre um aviso com o que foi medido e a escolha entre <b>fechar o "
                 "aplicativo</b> e <b>continuar mesmo assim</b>. Dá para marcar "
                 "\u201cnão avisar de novo neste computador\u201d."],
            ],
            widths=[36 * mm, 64 * mm, 70 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        para(
            "O aviso não é uma trava: nada quebra o computador. O que ele evita é você "
            "descobrir depois de meia hora de espera que faltava memória — e o texto "
            "aponta os controles desta mesma página como a saída para tornar o trabalho "
            "suportável."
        ),
        heading("A página Desempenho: quanto da máquina ele pode usar", "h2"),
        para(
            "A página tem três abas: <b>Resumo</b>, <b>Limites</b> e "
            "<b>Diagnóstico</b>."
        ),
        grid(
            ["Aba", "Para que serve"],
            [
                ["Resumo",
                 "Quatro opções prontas — <b>Leve</b>, <b>Equilibrado</b>, "
                 "<b>Rápido</b> e <b>Máximo</b> — e, embaixo, o que elas significam "
                 "agora: onde a transcrição vai rodar, com quantas threads e com qual "
                 "modelo. É a aba para quem não quer pensar em porcentagem."],
                ["Limites",
                 "Os quatro controles deslizantes, para quem quer afinar. Mexer em "
                 "qualquer um apaga o destaque das opções prontas: passa a ser "
                 "“ajuste manual”."],
                ["Diagnóstico",
                 "O que foi medido no seu computador, item a item, sempre na tela — "
                 "não escondido atrás de um botão. É a aba para mandar junto quando "
                 "algo der errado."],
            ],
            widths=[36 * mm, 134 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 3 * mm),
        note(
            "Ele avisa quando o limite não cabe no trabalho",
            "O Resumo compara o que você pediu (qualidade, quem fala, Ollama) com o "
            "que os limites liberam. Se o trabalho pedir mais memória do que sobrou, "
            "aparece um aviso dizendo que o modelo será rebaixado — antes de você "
            "esperar meia hora para descobrir. E quando a transcrição roda na placa "
            "de vídeo, o Resumo lembra que o medidor do processador fica quase "
            "parado: isso é o esperado, não é o programa travado.",
            TEAL,
        ),
        Spacer(1, 3 * mm),
        para(
            "Os quatro controles da aba Limites decidem o quanto o aplicativo pode "
            "ocupar. Diminua se quiser continuar trabalhando no computador enquanto "
            "ele processa. A escolha fica salva para as próximas vezes, e o resumo "
            "abaixo dos controles mostra na hora o efeito: onde vai rodar e com qual "
            "modelo."
        ),
        grid(
            ["Controle", "O que realmente faz"],
            [
                ["Processador (CPU)",
                 "Vira número de threads do motor e do ffmpeg. Em 25%, o aplicativo usa "
                 "um quarto dos núcleos. Abaixo de 60% ele também passa a rodar em "
                 "prioridade menor, para o computador continuar respondendo."],
                ["Memória (RAM)",
                 "Teto de memória considerado ao escolher o modelo quando o trabalho roda "
                 "na CPU. Um modelo que não caiba nesse teto é trocado por um menor, e o "
                 "relatório registra a troca."],
                ["Placa de vídeo (GPU)",
                 "Em <b>0% a placa é ignorada</b> e tudo roda na CPU. Acima disso, "
                 "controla o paralelismo do motor na placa."],
                ["Memória da placa (VRAM)",
                 "Teto de VRAM para escolher o modelo. É o que impede um modelo grande "
                 "demais de estourar a placa."],
            ],
            widths=[40 * mm, 130 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 3 * mm),
        note(
            "Uma ressalva honesta sobre a GPU",
            "O CUDA não tem um botão de \u201cusar 50% da placa\u201d. O controle mais "
            "próximo que dá para oferecer sem enganar é ligar/desligar e ajustar o "
            "paralelismo — e é isso que o controle faz. Já os limites de memória mudam "
            "de verdade qual modelo é carregado.",
            AMBER,
        ),
        heading("Se travar: o aplicativo volta do ponto salvo", "h2"),
        para(
            "Processar áudio longo demora, e coisas dão errado: a placa engasga, falta "
            "memória, o computador desliga. O aplicativo trata isso em duas camadas, "
            "sem você precisar fazer nada."
        ),
        *bullets([
            "<b>Pontos de retomada</b> — depois de cada etapa cara, o progresso é gravado "
            "no disco. Se o processamento morrer, rodar o mesmo arquivo com as mesmas "
            "opções continua de onde parou. Na prática: <b>a transcrição não é feita duas "
            "vezes</b>. O áudio já extraído também fica guardado.",
            "<b>Supervisor</b> — o trabalho roda num processo separado, vigiado. Se ele "
            "parar de dar sinal de vida, o supervisor encerra esse processo, volta do "
            "último ponto salvo e tenta de novo com o ambiente rebaixado: primeiro sem "
            "GPU, depois com um modelo menor.",
        ]),
        Spacer(1, 2 * mm),
        para(
            "Enquanto isso acontece, a janela avisa em amarelo o que está sendo feito, e "
            "a página <b>Arquivos</b> guarda o histórico da recuperação. Trocar a "
            "pasta de saída ou pedir legenda não invalida um ponto salvo; trocar o "
            "modelo, o idioma ou desligar a GPU, sim — nesses casos o resultado seria "
            "outro."
        ),
        heading("Modo claro e modo escuro", "h2"),
        para(
            "O botão na página <b>Configurações</b> alterna entre os dois. A escolha fica "
            "guardada no seu perfil e vale para as próximas vezes que você abrir o "
            "programa. <b>Sem nenhuma escolha salva, o aplicativo segue o tema do "
            "Windows</b> — quem já usa o sistema no escuro abre no escuro."
        ),
        para(
            "Para forçar um tema na abertura, sem mexer no que está salvo, use "
            "<b>--theme</b> com auto, claro ou escuro."
        ),
        code(r".\.venv\Scripts\lauda.exe app --theme escuro"),
        Spacer(1, 3 * mm),
        note(
            "A janela não trava enquanto processa",
            "O trabalho pesado roda em segundo plano. Você pode mover a janela, trocar de "
            "página e ler o passo a passo enquanto a transcrição acontece.",
        ),
        PageBreak(),
    ]


def section_outputs() -> list:
    return [
        heading("4. Os arquivos gerados"),
        para(
            "Para um arquivo de entrada chamado <b>entrevista.mp4</b>, a pasta de saída "
            "recebe:"
        ),
        grid(
            ["Arquivo", "Conteúdo", "Para quê"],
            [
                ["entrevista.report.txt",
                 "O laudo completo, em nove seções, pronto para ler ou imprimir.",
                 "É o produto principal. Abre em qualquer editor de texto."],
                ["entrevista.transcript.txt",
                 "Só o texto corrido, em parágrafos, sem cabeçalho nem marcação de tempo.",
                 "Para copiar e colar em um documento."],
                ["entrevista.data.json",
                 "Todos os dados estruturados: segmentos, palavras, falantes, métricas.",
                 "Para reaproveitar em outro programa ou script."],
                ["entrevista.srt",
                 "Legenda no formato SubRip, com no máximo duas linhas por trecho.",
                 "Players de vídeo, YouTube, editores."],
                ["entrevista.vtt",
                 "Legenda no formato WebVTT.",
                 "Players em navegador (HTML5)."],
                ["entrevista.assets/",
                 "Pasta com as miniaturas extraídas do vídeo.",
                 "Só existe quando a camada visual está ligada."],
            ],
            widths=[44 * mm, 68 * mm, 58 * mm],
        ),
        Spacer(1, 4 * mm),
        note(
            "Mesma entrada, mesma saída",
            "Processar o mesmo arquivo com as mesmas opções gera um relatório com layout "
            "idêntico. Só mudam a data e os tempos medidos. Isso permite comparar duas "
            "execuções com qualquer ferramenta de diferença.",
        ),
        heading("Onde ficam", "h2"),
        para(
            "Por padrão, na pasta <b>saida</b> dentro da pasta do aplicativo. Para abrir "
            "direto no Explorer:"
        ),
        code("explorer C:\\Users\\PC\\Desktop\\projetos\\mediaintel-local\\saida"),
        PageBreak(),
    ]


def section_report() -> list:
    return [
        heading("5. O relatório, seção por seção"),
        para(
            "O laudo tem sempre as mesmas nove seções, sempre na mesma ordem. Isso é "
            "proposital: você aprende onde olhar uma vez e vale para todo arquivo."
        ),
        grid(
            ["Seção", "O que traz", "Para que serve na prática"],
            [
                ["1. Identidade do arquivo",
                 "Nome, caminho, tamanho, hash SHA-256, data de modificação e de "
                 "processamento, versão do app, modelo, device.",
                 "Prova de integridade: o hash muda se o arquivo for alterado em um único "
                 "byte."],
                ["2. Metadados técnicos",
                 "Container, duração, taxa de bits; para cada trilha de vídeo e de áudio: "
                 "codec, resolução, quadros por segundo, canais, taxa de amostragem. Mais "
                 "tags e capítulos.",
                 "Descobrir por que um arquivo está pesado, tremido ou com áudio ruim."],
                ["3. Qualidade e diagnóstico",
                 "Volume médio e de pico, saturação, quanto é silêncio, quanto é fala, "
                 "tempo gasto em cada etapa e a lista de avisos.",
                 "Entender antes de reclamar do resultado: áudio baixo demais transcreve "
                 "mal, e o relatório avisa."],
                ["4. Idioma",
                 "Idioma detectado, se foi automático ou imposto por você, e a confiança.",
                 "Confiança baixa costuma explicar transcrição estranha."],
                ["5. Transcrição completa",
                 "Bloco A: texto corrido em parágrafos. Bloco B: trechos com hora de "
                 "início e fim. Bloco C (opcional): cada palavra com seu tempo.",
                 "O Bloco A é para ler; o B é para localizar no vídeo; o C é para edição "
                 "fina de legenda."],
                ["6. Diarização",
                 "Quantas pessoas falaram, quanto tempo cada uma falou e em quantos "
                 "trechos.",
                 "Reuniões e entrevistas: saber quem dominou a conversa."],
                ["7. Estrutura e resumo local",
                 "Contagem de palavras e caracteres, ritmo de fala, palavras mais "
                 "frequentes sem as palavras vazias, e o resumo do Ollama quando "
                 "disponível.",
                 "Uma leitura rápida do assunto antes de ler tudo."],
                ["8. Camada visual",
                 "Resolução real e exibida, número de cortes de cena e as miniaturas "
                 "salvas.",
                 "Achar rapidamente o ritmo de edição de um vídeo."],
                ["9. Rodapé",
                 "Lista dos arquivos gerados, pasta de saída, pasta dos modelos e os "
                 "erros parciais.",
                 "É onde você confere o que ficou de fora."],
            ],
            widths=[34 * mm, 68 * mm, 68 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        heading("Como ler o Bloco B", "h2"),
        code([
            f"[00:00:00.000 {ARROW} 00:00:07.530] SPEAKER_00: Boa noite, obrigada por vir",
            "                                        ao estudio hoje.",
            f"[00:00:07.530 {ARROW} 00:00:14.580] SPEAKER_01: Boa noite. E um prazer estar",
            "                                        aqui.",
        ]),
        Spacer(1, 3 * mm),
        para(
            "O formato do tempo é sempre <b>HH:MM:SS.mmm</b> (horas, minutos, segundos e "
            "milésimos). O rótulo do falante só aparece quando a diarização rodou."
        ),
        PageBreak(),
    ]


def section_cli() -> list:
    return [
        heading("6. Todas as opções da linha de comando"),
        para(
            "Tudo o que a interface oferece existe também como opção de comando — e "
            "algumas coisas só existem aqui."
        ),
        heading("Comandos", "h2"),
        grid(
            ["Comando", "O que faz"],
            [
                ["lauda run ARQUIVO", "Processa um arquivo e gera os relatórios."],
                ["lauda app [--theme]",
                 "Abre o aplicativo em janela própria. --theme aceita auto, claro ou escuro."],
                ["lauda ui", "Abre a interface no navegador."],
                ["lauda doctor",
                 "Diagnóstico do ambiente: ffmpeg, GPU, memória, modelos, diarização, Ollama."],
                ["lauda models",
                 "Lista os modelos e diz quais cabem na memória da sua máquina."],
                ["lauda checkpoints",
                 "Lista os trabalhos interrompidos que dá para retomar. Com --limpar, "
                 "apaga todos."],
            ],
            widths=[52 * mm, 118 * mm],
        ),
        heading("Opções de lauda run", "h2"),
        grid(
            ["Opção", "Padrão", "O que faz"],
            [
                ["-o, --output", "./saida", "Pasta onde gravar os resultados."],
                ["-m, --model", "small",
                 "tiny, base, small, medium, large-v3, large-v3-turbo ou distil-large-v3."],
                ["-l, --lang", "auto", "auto, pt, en, es e outros códigos de idioma."],
                ["-d, --device", "auto", "auto, cpu ou cuda."],
                ["--compute-type", "auto",
                 "Precisão numérica: int8, int8_float16, float16 ou float32. Mexer aqui "
                 "só se souber o que está fazendo."],
                ["--beam-size", "5",
                 "Quantos caminhos o modelo considera. 1 é mais rápido e menos preciso."],
                ["--vad / --no-vad", "ligado",
                 "Filtro de voz. Desligado, o modelo tende a inventar texto no silêncio."],
                ["--words", "desligado", "Gera os tempos por palavra (Bloco C)."],
                ["--diarize", "desligado", "Liga a identificação de falantes."],
                ["--diarize-backend", "auto", "auto, pyannote ou ecapa."],
                ["--num-speakers", "-",
                 "Número exato de pessoas falando. Melhora bastante o resultado quando "
                 "você sabe."],
                ["--min-speakers / --max-speakers", "-",
                 "Faixa esperada, quando você não sabe o número exato."],
                ["--speaker-threshold", "0.30",
                 "Sensibilidade da separação de vozes no backend ecapa. Menor separa "
                 "mais; maior junta mais."],
                ["--srt / --no-srt", "<b>ligado</b>", "Gera a legenda .srt."],
                ["--vtt", "desligado", "Gera também a legenda .vtt (vídeo na web)."],
                ["--no-json", "-", "Não gera o arquivo de dados."],
                ["--visual", "desligado", "Cortes de cena e miniaturas (só vídeo)."],
                ["--summarize", "desligado", "Bloco de resumo via Ollama local."],
                ["--cpu", "100", "Limite de CPU em % — vira número de threads."],
                ["--ram", "50", "Limite de RAM em % — teto para escolher o modelo."],
                ["--gpu", "100", "Limite de GPU em %. <b>0 desliga a placa</b>."],
                ["--vram", "100", "Limite de VRAM em % — teto para escolher o modelo."],
                ["--recover / --no-recover", "ligado",
                 "Supervisiona o processamento: encerra se travar e retoma do ponto salvo."],
                ["--resume / --no-resume", "ligado", "Usar os pontos de retomada salvos."],
                ["--stall-timeout", "300",
                 "Segundos sem sinal antes de considerar travado."],
                ["--attempts", "3", "Quantas tentativas antes de desistir."],
                ["--top-words", "25", "Quantas palavras frequentes listar no relatório."],
                ["--prompt", "-",
                 "Texto para ancorar o vocabulário: nomes próprios, siglas, jargão. Ex.: "
                 '--prompt "Fulano, ACME, CNPJ".'],
                ["--keep-temp", "desligado",
                 "Mantém o áudio temporário para depuração. Normalmente ele é apagado."],
                ["-v / -q", "-", "Log detalhado / apenas avisos e erros."],
            ],
            widths=[44 * mm, 20 * mm, 106 * mm],
        ),
        PageBreak(),
    ]


def section_models() -> list:
    return [
        heading("7. Qual modelo escolher"),
        para(
            "Esta é a decisão que mais afeta o resultado. A regra é simples: use o maior "
            "modelo que caiba na sua memória e cujo tempo de espera você tolere."
        ),
        grid(
            ["Modelo", "Memória", "Velocidade", "Quando usar"],
            [
                ["tiny", "0,5 GB", "muito rápida",
                 "Só para testar se o arquivo abre. A qualidade é de rascunho."],
                ["base", "0,7 GB", "muito rápida", "Pouco melhor que tiny. Raramente vale."],
                ["small", "1,2 GB", "rápida",
                 "O padrão. Bom equilíbrio para o dia a dia em português."],
                ["medium", "2,4 GB", "média", "Quando small erra nomes e termos técnicos."],
                ["large-v3-turbo", "2,2 GB", "média",
                 "O melhor custo-benefício: quase a qualidade do large pela metade do "
                 "tempo."],
                ["distil-large-v3", "2,2 GB", "média", "Alternativa ao turbo."],
                ["large-v3", "3,6 GB", "lenta",
                 "Máxima qualidade. Não cabe em placas de 4 GB."],
            ],
            widths=[32 * mm, 20 * mm, 24 * mm, 94 * mm],
        ),
        Spacer(1, 4 * mm),
        note(
            "Você não consegue estourar a memória",
            "Se o modelo pedido não couber, o aplicativo desce sozinho para o maior que "
            "couber e escreve o motivo no relatório. Se a placa de vídeo falhar no meio "
            "do caminho, ele refaz tudo no processador em vez de devolver um relatório "
            "vazio.",
        ),
        heading("Quanto tempo vai demorar?", "h2"),
        para(
            "Depende demais de máquina e modelo para prometer número. Meça o seu caso: "
            "rode uma vez com <b>-m tiny</b> e olhe a linha <b>Velocidade</b> na seção 3 "
            "do relatório. Ela diz, por exemplo, <b>3,88x tempo real</b> — ou seja, um "
            "áudio de 10 minutos levou pouco menos de 3 minutos."
        ),
        heading("Baixar modelos para uso offline", "h2"),
        para(
            "Se você vai trabalhar sem internet, baixe antes o que for usar. Os arquivos "
            "vão para a pasta <b>models</b>:"
        ),
        code(
            ".\\.venv\\Scripts\\python.exe scripts\\download_models.py "
            "--model small --model large-v3-turbo"
        ),
        PageBreak(),
    ]


def section_extras() -> list:
    return [
        heading("8. Diarização, resumo e camada visual"),
        heading("Identificando quem fala", "h2"),
        para(
            "A diarização separa as vozes e rotula cada trecho. São dois motores "
            "possíveis, e o aplicativo escolhe sozinho o que estiver disponível:"
        ),
        grid(
            ["Motor", "Precisa de cadastro?", "Qualidade", "Observação"],
            [
                ["ecapa", "Não", "Boa",
                 "É o padrão prático. Funciona sem conta, sem token e sem burocracia."],
                ["pyannote", "Sim: conta e token no Hugging Face", "Melhor",
                 "Lida melhor com falas sobrepostas. Exige aceitar os termos do modelo."],
            ],
            widths=[26 * mm, 44 * mm, 22 * mm, 78 * mm],
            mono_columns=(0,),
        ),
        Spacer(1, 3 * mm),
        para(
            "Se o resultado juntar duas pessoas em uma só, ou inventar gente demais, você "
            "tem dois ajustes. O primeiro é dizer o número de pessoas, quando souber:"
        ),
        code(
            '.\\.venv\\Scripts\\lauda.exe run "reuniao.mp4" --diarize --num-speakers 3'
        ),
        Spacer(1, 3 * mm),
        para(
            "O segundo é a sensibilidade. O valor padrão é 0,30: abaixe para separar mais "
            "vozes, aumente para juntar."
        ),
        code(
            '.\\.venv\\Scripts\\lauda.exe run "reuniao.mp4" --diarize '
            "--speaker-threshold 0.22"
        ),
        Spacer(1, 3 * mm),
        note(
            "Limite honesto da diarização",
            "Ela só rotula o que foi transcrito. Duas pessoas falando ao mesmo tempo viram "
            "um falante só, e vozes parecidas podem ser fundidas. É uma ajuda, não uma "
            "prova pericial.",
            AMBER,
        ),
        heading("Resumo automático com Ollama", "h2"),
        para(
            "Se você já usa o <b>Ollama</b> na máquina, o relatório ganha resumo, tópicos, "
            "itens de ação e citações — e continua tudo local, porque o Ollama roda no seu "
            "computador. Basta ter o servidor no ar e o modelo baixado:"
        ),
        code("ollama pull qwen3:14b"),
        Spacer(1, 3 * mm),
        para(
            "Depois use a opção <b>--summarize</b>, ou marque a caixa correspondente na "
            "interface. Transcrições longas são resumidas em duas passadas para caber na "
            "memória de modelos pequenos. Sem Ollama, o bloco simplesmente aparece como "
            "indisponível e o resto do relatório continua normal."
        ),
        heading("Camada visual (só para vídeo)", "h2"),
        para(
            "Com <b>--visual</b>, o aplicativo conta as trocas de cena e salva uma "
            "miniatura a cada 30 segundos numa pasta ao lado do relatório. Não há modelo "
            "de visão envolvido: é só ffmpeg, rápido e barato. Serve para ter uma noção do "
            "ritmo de edição e para localizar visualmente um trecho."
        ),
        PageBreak(),
    ]


def section_trouble() -> list:
    return [
        heading("9. Quando algo dá errado"),
        para(
            "O aplicativo foi feito para nunca falhar em silêncio. Quase todo problema "
            "aparece escrito no relatório ou no terminal. Os mais comuns:"
        ),
        grid(
            ["Sintoma", "Causa provável e solução"],
            [
                ["O token '&&' não é um separador válido",
                 "Você usou &amp;&amp; no PowerShell 5.1, que não aceita. Troque por ; ou "
                 "rode um comando por linha. Não tem relação com o aplicativo."],
                ["Não encontrei ffmpeg",
                 "O ffmpeg não está instalado ou o terminal foi aberto antes da "
                 "instalação. Instale com winget install --id Gyan.FFmpeg -e e abra um "
                 "terminal novo."],
                ["Library cublas64_12.dll is not found",
                 "Faltam as bibliotecas CUDA. Rode pip install -r requirements-gpu.txt. "
                 "Enquanto isso o aplicativo continua funcionando no processador."],
                ["A transcrição saiu vazia",
                 "O arquivo pode não ter fala. Confira na seção 3 do relatório se Fala "
                 "detectada está como não; música e ruído são descartados de propósito."],
                ["Texto repetido ou inventado",
                 "Clássico do Whisper em silêncio ou volume muito baixo. Mantenha o VAD "
                 "ligado (é o padrão), aumente o volume da gravação ou use modelo maior."],
                ["Nomes próprios e siglas errados",
                 'Use --prompt "Nome, SIGLA, jargão" para ancorar o vocabulário.'],
                ["Diarização indisponível",
                 "Falta o pacote: pip install -r requirements-diarize.txt. Se aparecer "
                 "erro de modelo gated, use --diarize-backend ecapa, que não pede token."],
                ["O processamento travou",
                 "O supervisor percebe sozinho, encerra e retoma do último ponto salvo, "
                 "tentando de novo sem GPU e depois com um modelo menor. Se ainda assim "
                 "não concluir, o ponto salvo continua no disco: rodar de novo aproveita "
                 "o que já deu certo."],
                ["Ele está comendo a máquina inteira",
                 "Baixe os controles na página Desempenho. Abaixo de 60% de CPU o aplicativo "
                 "também passa a rodar em prioridade menor."],
                ["Está muito lento",
                 "Confira na seção 3 qual device foi usado. Se apareceu cpu com GPU "
                 "disponível, veja o erro de CUDA acima. Ou baixe o modelo."],
                ["Acentos quebrados no terminal",
                 "Console legado do Windows. Rode chcp 65001 antes, ou use o Windows "
                 "Terminal."],
            ],
            widths=[52 * mm, 118 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        heading("O comando que responde quase tudo", "h2"),
        code(".\\.venv\\Scripts\\lauda.exe doctor"),
        Spacer(1, 3 * mm),
        para(
            "Ele mostra, em uma tela só: se o ffmpeg foi encontrado e onde, qual placa de "
            "vídeo e quanta memória existem, qual modelo o aplicativo escolheria sozinho, "
            "quais modelos já estão baixados, se a diarização está pronta e se o Ollama "
            "está no ar."
        ),
        PageBreak(),
    ]


def section_limits() -> list:
    return [
        heading("10. Limites honestos e privacidade"),
        heading("O que esperar da transcrição", "h2"),
        *bullets([
            "<b>Sotaque forte e fala rápida</b> derrubam a precisão, principalmente nos "
            "modelos menores.",
            "<b>Música e ruído de fundo</b> produzem texto inventado. O filtro de voz "
            "reduz o problema, mas não elimina.",
            "<b>Falas sobrepostas</b> viram uma linha só, e a diarização não consegue "
            "separar direito.",
            "<b>Silêncio prolongado</b> é a maior fonte de invenção: o modelo tenta "
            "preencher o vazio. Por isso o filtro de voz vem ligado.",
            "<b>Números, siglas e nomes próprios</b> erram com frequência. É onde a opção "
            "de prompt inicial mais ajuda.",
            "<b>Os tempos por palavra são estimativas</b> do próprio modelo, não medição "
            "acústica. Servem para legendar, não para perícia.",
        ]),
        Spacer(1, 2 * mm),
        note(
            "Revisão humana continua necessária",
            "Para uso jurídico, jornalístico, médico ou acadêmico, trate a transcrição "
            "como um rascunho muito adiantado — nunca como documento final sem conferir.",
            AMBER,
        ),
        heading("Privacidade", "h2"),
        para(
            "O aplicativo não envia o seu arquivo para lugar nenhum. O único acesso à rede "
            "acontece no <b>download inicial dos modelos</b>, e depois disso nem isso é "
            "necessário — você pode inclusive bloquear o acesso à internet do processo, ou "
            "ligar o modo offline explícito, que impede qualquer download durante o "
            "processamento."
        ),
        para(
            "O servidor da interface escuta apenas em 127.0.0.1, ou seja, só a sua própria "
            "máquina consegue acessar. Ele nunca cria endereço público na internet."
        ),
        heading("Licenças", "h2"),
        para(
            "O código do aplicativo é MIT. As bibliotecas usadas são MIT, BSD ou "
            "Apache-2.0, e os pesos do Whisper são abertos, publicados pela OpenAI sob "
            "licença MIT. O ffmpeg não é redistribuído: o aplicativo apenas chama o que "
            "você instalou. O arquivo LICENSES.md, na pasta do projeto, traz a lista "
            "completa e as ressalvas de cada modelo."
        ),
        heading("Onde ficam as coisas", "h2"),
        grid(
            ["Pasta", "Conteúdo"],
            [
                ["saida\\", "Os relatórios, transcrições, legendas e miniaturas."],
                ["models\\", "Os modelos baixados. Apagar libera espaço, mas força novo download."],
                [".venv\\", "O ambiente Python do aplicativo. Não mexa."],
                ["src\\lauda\\", "O código-fonte."],
                ["docs\\", "Este manual e o documento de desenho."],
                ["tests\\", "Os testes automatizados e as mídias de exemplo."],
            ],
            widths=[42 * mm, 128 * mm],
        ),
    ]


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = Manual(str(OUTPUT))

    story: list = []
    story += cover()
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())
    story += toc_page()
    story += section_intro()
    story += section_open()
    story += section_interface()
    story += section_outputs()
    story += section_report()
    story += section_cli()
    story += section_models()
    story += section_extras()
    story += section_trouble()
    story += section_limits()

    # multiBuild: a primeira passada descobre as páginas, a segunda escreve o sumário.
    doc.multiBuild(story)
    return OUTPUT


def main() -> int:
    path = build()
    size_kb = path.stat().st_size / 1024
    print(f"manual: {path} ({size_kb:.0f} KB)")
    print(f"fontes: texto={FONT}, mono={MONO}, unicode={'sim' if UNICODE_OK else 'nao'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
