"""Gera o documento técnico (docs/Lauda-Local-Decisoes-Tecnicas.pdf).

    python scripts/make_decisions.py

É o "porquê" do projeto: arquitetura, decisões, medições e limites. Escrito
para quem vai manter o código — inclusive o próprio autor daqui a seis meses.
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
    MONO,
    PAGE_MARGIN,
    ROOT,
    RULE,
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

OUTPUT = ROOT / "docs" / "Lauda-Local-Decisoes-Tecnicas.pdf"
W = 170 * mm


class Doc(BaseDocTemplate):
    """Capa escura + miolo com rodapé e sumário navegável."""

    def __init__(self, path: str) -> None:
        super().__init__(
            path, pagesize=A4,
            title=f"{APP_NAME} {ARROW} Decisões técnicas",
            author=APP_NAME, subject="Arquitetura, decisões de projeto e medições",
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
        canvas.drawString(PAGE_MARGIN, 10 * mm, f"{APP_NAME} {APP_VERSION} — decisões técnicas")
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
        key = f"d{self._counter}"
        self.canv.bookmarkPage(key)
        level = 0 if flowable.style.name == "h1" else 1
        self.notify("TOCEntry", (level, text, self.page - 1, key))
        self.canv.addOutlineEntry(text, key, level=level, closed=False)


def h(text: str, level: str = "h1") -> Paragraph:
    return Paragraph(text, S[level])


def decision(titulo: str, escolha: str, porque: str, custo: str) -> list:
    """Bloco padronizado: o que foi decidido, por quê e o que custou."""
    return [
        h(titulo, "h2"),
        grid(
            ["", ""],
            [
                ["Escolha", escolha],
                ["Por quê", porque],
                ["O que custa", custo],
            ],
            widths=[28 * mm, W - 28 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 3 * mm),
    ]


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = Doc(str(OUTPUT))
    story: list = []

    # ------------------------------------------------------------------ capa --
    story += [
        Spacer(1, 80 * mm),
        para(APP_NAME, "cover_title"),
        para("Decisões técnicas", "cover_sub"),
        Spacer(1, 4 * mm),
        para(
            "Arquitetura, escolhas de projeto, medições<br/>"
            "e os limites que aceitamos de olhos abertos.",
            "cover_sub",
        ),
        Spacer(1, 45 * mm),
        para(
            f"Versão {APP_VERSION}  |  {date.today().strftime('%d/%m/%Y')}<br/>"
            "Documento para quem mantém o código",
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
        h("1. O problema e a forma da solução"),
        para(
            "O objetivo é transformar um arquivo de áudio ou vídeo em um laudo de texto "
            "com tudo o que dá para extrair <b>sem enviar nada para lugar nenhum</b>. "
            "Essa restrição — processamento local — não é um detalhe de implantação: "
            "ela determina praticamente todas as decisões deste documento.",
            "lead",
        ),
        h("O pipeline", "h2"),
        code([
            "arquivo",
            "   |",
            "   +-- probe      ffprobe -> metadados (container, streams, tags)",
            "   +-- extract    ffmpeg  -> WAV PCM 16 bits, 16 kHz, mono",
            "   +-- vad        volume, silencio, clipping",
            "   +-- asr        faster-whisper -> trechos + idioma",
            "   +-- align      encolhe bordas pelas palavras, remove sobreposicao",
            "   +-- diarize    embeddings de locutor + clusterizacao (opcional)",
            "   +-- render     TXT, TXT corrido, JSON, SRT, VTT",
        ]),
        Spacer(1, 3 * mm),
        para(
            "Cada etapa é um módulo com uma responsabilidade só, e o "
            f"<font face='{MONO}'>pipeline.py</font> apenas orquestra. Isso não é "
            "purismo: é o que permite salvar um ponto de retomada entre etapas e "
            "testar cada uma isoladamente."
        ),
        h("Regra que atravessa todo o código", "h2"),
        para(
            "<b>Etapa obrigatória falha alto; etapa opcional nunca derruba o trabalho.</b> "
            "Sem o ffprobe não há o que fazer — o programa para com uma mensagem clara. "
            "Já a diarização, o resumo e a camada visual, se falharem, viram uma linha "
            "<font face='" + MONO + "'>[INDISPONÍVEL] &lt;bloco&gt;: &lt;motivo&gt;</font> "
            "no relatório. O leitor sempre sabe o que faltou e por quê; nada some em "
            "silêncio."
        ),
        PageBreak(),
    ]

    # =================================================================== 2 ====
    story += [h("2. Decisões de plataforma")]
    story += decision(
        "Motor de transcrição: faster-whisper (CTranslate2)",
        "faster-whisper 1.2, com os pesos abertos do Whisper.",
        "É a implementação que roda o Whisper mais rápido em CPU e GPU sem exigir "
        "PyTorch. Os pesos são MIT. Alternativas: a API da OpenAI está fora por "
        "definição (nuvem); o whisper.cpp seria ótimo em Apple Silicon, mas exigiria "
        "compilar por plataforma e não traz VAD e timestamps por palavra prontos.",
        "Depende de bibliotecas CUDA separadas para usar a GPU — a origem do erro "
        "mais comum do projeto (ver seção 8).",
    )
    story += decision(
        "ffmpeg como dependência de sistema",
        "Chamar o binário `ffmpeg`/`ffprobe` instalado pelo usuário.",
        "Reimplementar leitura de container e decodificação seria absurdo, e "
        "empacotar o ffmpeg mudaria a licença do projeto (os builds completos são "
        "GPL). Chamando o binário instalado, a licença aplicável é a do build do "
        "usuário, e nós continuamos MIT.",
        "Uma dependência a instalar — mitigada com detecção automática em vários "
        "diretórios e mensagem de erro com o comando exato de instalação.",
    )
    story += decision(
        "Python 3.12",
        "Faixa suportada 3.11–3.13; 3.12 é a recomendada.",
        "O 3.14 ainda não tem wheels de `ctranslate2`. Fixar a faixa evita que "
        "alguém instale no interpretador errado e receba um erro de compilação "
        "incompreensível.",
        "Não roda no Python mais novo. É temporário e está documentado.",
    )
    story += decision(
        "Interface: janela nativa em Tkinter",
        "Tkinter, com a interface Gradio mantida como alternativa.",
        "O pedido foi explícito: um aplicativo, não uma página web local. O Tkinter "
        "vem com o Python — nenhuma dependência nova, nenhum servidor, nenhuma porta "
        "aberta — e dá acesso direto aos diálogos de arquivo do sistema. Electron ou "
        "PyQt trariam centenas de MB para resolver o mesmo problema.",
        "Visual menos moderno que o Gradio. Compensado usando o tema `clam` do ttk, "
        "que é o único totalmente recolorível — condição para o modo escuro.",
    )
    story.append(PageBreak())

    # =================================================================== 3 ====
    story += [
        h("3. Decisões de qualidade da transcrição"),
        para(
            "As três decisões abaixo existem por causa de um comportamento conhecido do "
            "Whisper: <b>em silêncio, ele inventa texto</b>. Não é bug, é como o modelo "
            "foi treinado."
        ),
    ]
    story += decision(
        "VAD ligado por padrão",
        "Filtro de voz (Silero) ativo, com 500 ms de silêncio mínimo.",
        "Sem ele, trechos mudos viram frases inventadas — normalmente repetições de "
        "algo dito antes. O VAD corta o silêncio antes de o modelo ver.",
        "Um trecho de fala muito baixa pode ser descartado. O relatório avisa quando "
        "o volume médio está abaixo de -38 dB.",
    )
    story += decision(
        "condition_on_previous_text desligado",
        "Cada janela é transcrita sem o texto anterior como contexto.",
        "Com o encadeamento ligado, <b>uma</b> alucinação contamina todas as janelas "
        "seguintes, e o resultado degringola até o fim do arquivo.",
        "Perde-se um pouco de coerência de pontuação entre janelas. Vale a troca.",
    )
    story += decision(
        "Modo sequencial como padrão, lote como opção",
        "`batch_size = 0` (sequencial) por padrão; o modo em lote é opt-in.",
        "Medimos o modo em lote: <b>2,0x mais rápido na GPU e 1,3x na CPU</b>. Mas os "
        "trechos saem <b>~6x mais longos</b> (média de 4,3 s contra 29,7 s). Um trecho "
        "de 30 segundos é inútil como legenda e atrapalha a diarização, que atribui um "
        "falante por trecho.",
        "Quem quer velocidade precisa ligar a opção e aceitar o texto menos "
        "granular — dito com essas palavras na própria tela.",
    )
    story += [
        h("A medição que decidiu isso", "h2"),
        grid(
            ["Cenário", "Tempo", "Trechos", "Trecho médio"],
            [
                ["GPU, sequencial", "12,54 s", "60", "4,3 s"],
                ["GPU, em lote (16)", "6,25 s", "10", "29,7 s"],
                ["CPU, sequencial", "30,83 s", "62", "4,9 s"],
                ["CPU, em lote (8)", "23,05 s", "10", "30,4 s"],
            ],
            widths=[54 * mm, 30 * mm, 26 * mm, W - 110 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 2 * mm),
        para(
            "<font color='#7C8496'>Áudio de 5 minutos, modelo small, GTX 1650 SUPER "
            "(int8_float16) e CPU de 12 threads (int8). O tempo mede a iteração "
            "completa do gerador — medir só a chamada daria números falsos, porque o "
            "trabalho acontece na iteração.</font>",
            "note",
        ),
        PageBreak(),
    ]

    # =================================================================== 4 ====
    story += [
        h("4. Escolha automática de hardware"),
        para(
            "O aplicativo nunca deve falhar por falta de memória, e nunca deve exigir "
            "que o usuário saiba o que é VRAM. A decisão é tomada em três camadas."
        ),
        *bullets([
            "<b>Antes de carregar</b> — calcula um orçamento de memória (VRAM menos "
            "0,8 GB de reserva do runtime CUDA, ou uma fração da RAM na CPU) e escolhe "
            "o maior modelo que cabe. Se o pedido não couber, rebaixa e escreve o "
            "motivo no relatório.",
            "<b>Ao carregar</b> — se a GPU falhar (falta de biblioteca, driver antigo), "
            "recarrega na CPU automaticamente.",
            "<b>Durante a inferência</b> — o erro mais traiçoeiro aparece só na primeira "
            "inferência, não no carregamento. Nesse caso a transcrição inteira é "
            "refeita na CPU em vez de devolver um relatório vazio.",
        ]),
        Spacer(1, 2 * mm),
        note(
            "Por que a terceira camada existe",
            "Na máquina de desenvolvimento, o modelo carregava na GPU sem erro e "
            "quebrava com <font face='" + MONO + "'>Library cublas64_12.dll is not "
            "found</font> na primeira inferência. A versão que só tratava falha no "
            "carregamento entregava um relatório sem transcrição nenhuma — e sem "
            "explicação decente.",
            AMBER,
        ),
        h("Bibliotecas CUDA instaladas via pip", "h2"),
        para(
            "O CTranslate2 procura cuBLAS e cuDNN no PATH do processo. Quando elas vêm "
            "dos pacotes <font face='" + MONO + "'>nvidia-*-cu12</font>, ficam em "
            "<font face='" + MONO + "'>site-packages/nvidia/*/bin</font>, que não está "
            "no PATH. O aplicativo registra esses diretórios com "
            "<font face='" + MONO + "'>os.add_dll_directory</font> antes do primeiro uso "
            "da GPU. Sem isso, a instalação por pip simplesmente não funciona — e o "
            "erro não diz o porquê."
        ),
        PageBreak(),
    ]

    # =================================================================== 5 ====
    story += [h("5. Confiabilidade: retomada e supervisão")]
    story += decision(
        "Processo separado, não thread",
        "O trabalho roda num processo filho supervisionado pelo pai.",
        "Uma thread travada dentro de uma chamada nativa do CTranslate2 <b>não pode ser "
        "morta</b> — não há sinal que a interrompa. Um processo, sim. Sem essa "
        "separação, o recurso de recuperação seria decorativo.",
        "Custo de arranque de um processo por trabalho e um protocolo simples "
        "(uma linha JSON por evento) entre pai e filho.",
    )
    story += decision(
        "Matar a árvore, não só o filho",
        "`taskkill /F /T` no Windows; grupo de processos no POSIX.",
        "O filho chama o ffmpeg. Encerrar só o filho deixava o ffmpeg vivo, comendo "
        "CPU e segurando o arquivo aberto — foi o que aconteceu no primeiro teste "
        "manual, e por isso existe um teste automatizado que cria um processo neto e "
        "confirma que ele morre junto.",
        "Nenhum relevante.",
    )
    story += decision(
        "Ponto de retomada por etapa",
        "Estado gravado depois de extract, vad, asr, align e diarize.",
        "A transcrição é 95% do tempo. Perdê-la porque a diarização quebrou seria "
        "inaceitável. Com o ponto salvo, a segunda tentativa aproveita tudo o que já "
        "estava pronto — medimos 28,3 s até a morte e 14,4 s na retomada.",
        "Ocupa espaço em disco (o WAV extraído). Mitigado extraindo direto para a "
        "pasta do ponto, sem cópia, e apagando tudo quando o trabalho conclui.",
    )
    story += [
        h("O que invalida um ponto salvo", "h2"),
        para(
            "A chave é o SHA-256 do arquivo mais uma impressão digital das opções que "
            "mudam o <b>conteúdo</b> do trabalho pesado:"
        ),
        grid(
            ["Muda o ponto salvo", "Não muda"],
            [
                ["modelo, idioma, device efetivo, compute_type, beam_size, batch_size, "
                 "VAD, timestamps por palavra, diarização e seus parâmetros",
                 "pasta de saída, formatos de legenda, JSON sim/não, camada visual, "
                 "resumo, número de palavras frequentes"],
            ],
            widths=[W / 2, W / 2],
            mono_columns=(),
        ),
        Spacer(1, 2 * mm),
        para(
            "Trocar a pasta de saída não justifica transcrever tudo de novo; trocar o "
            "modelo, sim. Essa distinção é o que torna a retomada útil na prática. "
            "E, entre tentativas, repetir a configuração que acabou de travar teria "
            "pouca chance: por isso a segunda desliga a GPU e a terceira reduz o "
            "modelo, anunciando cada degrau ao usuário."
        ),
        PageBreak(),
    ]

    # =================================================================== 6 ====
    story += [
        h("6. Limites de recurso: o que é real e o que não seria"),
        para(
            "Quatro controles deslizantes. A tentação era fazer os quatro parecerem "
            "iguais; a decisão foi mapear cada um em algo que <b>de fato existe</b> e "
            "dizer na tela o que ele faz.",
            "lead",
        ),
        grid(
            ["Controle", "Mecanismo real", "É um limite rígido?"],
            [
                ["CPU", "Número de threads do CTranslate2 e do ffmpeg; abaixo de 60% "
                 "também rebaixa a prioridade do processo.",
                 "Sim — é contagem de núcleos."],
                ["RAM", "Teto do orçamento usado para escolher o modelo em CPU.",
                 "Não — é um limite de escolha, não um `ulimit`."],
                ["VRAM", "Mesmo mecanismo, aplicado à memória da placa.",
                 "Não — o CTranslate2 não expõe teto de alocação."],
                ["GPU", "0% ignora a placa; acima disso ajusta o paralelismo "
                 "(`num_workers`).",
                 "Parcial — ligar/desligar é rígido; a porcentagem é grosseira."],
            ],
            widths=[24 * mm, 90 * mm, W - 114 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 3 * mm),
        note(
            "A alternativa que foi recusada",
            "Seria fácil mostrar um controle de 0 a 100% de GPU sugerindo que ele "
            "limita a ocupação da placa. Não existe essa API no CUDA. Um controle que "
            "não corresponde a nada é pior do que não ter controle: o usuário toma "
            "decisões erradas confiando nele.",
            AMBER,
        ),
        Spacer(1, 3 * mm),
        h("Os quatro controles viraram a segunda aba", "h2"),
        para(
            "A tabela acima é honesta e continua valendo — e era ilegível para quem "
            "não sabe o que é uma thread. A página Desempenho passou a ter três abas: "
            "<b>Resumo</b> (quatro opções prontas, em português comum), <b>Limites</b> "
            "(estes controles) e <b>Diagnóstico</b> (o que foi medido, sempre na tela). "
            "Os presets não são enfeite: cada um é um conjunto de valores destes mesmos "
            "quatro controles, e mexer num controle apaga o destaque do preset — porque "
            "aí a configuração deixou de ser aquela."
        ),
        para(
            "O Resumo também compara o trabalho pedido com o que os limites liberam, e "
            "avisa <b>antes</b> quando o modelo vai ser rebaixado por falta de memória. "
            "Era informação que só existia depois, dentro do laudo, quando já se tinha "
            "esperado a transcrição inteira."
        ),
        PageBreak(),
    ]

    # =================================================================== 7 ====
    story += [
        h("7. Segurança da informação"),
        h("Modelo de ameaça", "h2"),
        para(
            "O aplicativo roda com os privilégios do usuário, na máquina dele, sobre "
            "arquivos dele. Não há autenticação, multiusuário nem superfície de rede a "
            "defender. As ameaças que sobram são três: <b>vazamento por descuido</b> "
            "(dado sensível indo parar onde não devia), <b>entrada maliciosa</b> "
            "(um arquivo de mídia preparado) e <b>configuração hostil</b> (variáveis de "
            "ambiente apontando para lugares inesperados)."
        ),
        grid(
            ["Medida", "Contra o quê"],
            [
                ["Nenhum envio de mídia pela rede. O único acesso externo é o download "
                 "inicial dos modelos, e existe modo estritamente offline.",
                 "Vazamento do conteúdo processado."],
                ["O arquivo de mídia nunca é executado: é passado como argumento de "
                 "leitura para o ffmpeg, sempre por lista de argumentos, nunca por "
                 "shell.",
                 "Injeção de comando por nome de arquivo, execução de conteúdo."],
                ["O token do Hugging Face é removido antes de serializar as opções para "
                 "o processo filho; ele viaja pelo ambiente, que não deixa rastro em "
                 "disco.",
                 "Segredo em arquivo temporário legível por outros usuários."],
                ["Pontos de retomada guardam transcrições: a pasta é criada com 0700 no "
                 "POSIX e herda a ACL do perfil no Windows. São apagados ao concluir e "
                 "expiram em 7 dias.",
                 "Conteúdo sensível esquecido no disco."],
                ["O endereço do Ollama é validado: só `http` e `https` passam.",
                 "`OLLAMA_HOST=file:///...` fazendo o cliente ler arquivos locais."],
                ["Nomes de arquivo de saída passam por normalização que remove acentos, "
                 "separadores e caracteres de caminho.",
                 "Travessia de diretório a partir do nome do arquivo de entrada."],
                ["Toda saída do ffprobe é tratada como dado não confiável: conversões "
                 "numéricas defensivas, nada de `eval`.",
                 "Metadados manipulados quebrando o programa."],
            ],
            widths=[92 * mm, W - 92 * mm],
            mono_columns=(),
        ),
        h("O que o projeto NÃO protege", "h2"),
        *bullets([
            "Não há criptografia em repouso. Quem tem acesso ao perfil do usuário lê os "
            "relatórios e os pontos de retomada.",
            "Não há sandbox para o ffmpeg. Uma vulnerabilidade no ffmpeg é uma "
            "vulnerabilidade aqui — mantenha-o atualizado.",
            "A interface no navegador com <font face='" + MONO + "'>--share</font> "
            "escuta em todas as interfaces, sem autenticação. É intencional e serve "
            "para rede local confiável; a interface padrão (a janela nativa) não abre "
            "porta nenhuma.",
            "Os modelos baixados não têm verificação de assinatura além do que o "
            "Hugging Face já faz.",
        ]),
        PageBreak(),
    ]

    # =================================================================== 8 ====
    story += [
        h("8. Desempenho: onde o tempo realmente vai"),
        para(
            "Antes de otimizar qualquer coisa, medimos. O resultado desmontou a lista "
            "de otimizações que parecia óbvia.",
            "lead",
        ),
        grid(
            ["Operação", "Tempo (áudio de 5 min)", "Vale otimizar?"],
            [
                ["SHA-256 do arquivo", "6 ms", "só se for calculado duas vezes"],
                ["ffprobe", "44 ms", "não"],
                ["extração para WAV", "72 ms", "não"],
                ["análise de volume/silêncio", "80 ms", "não"],
                ["transcrição (GPU, small)", "12 540 ms", "<b>é aqui que está tudo</b>"],
            ],
            widths=[58 * mm, 44 * mm, W - 102 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 3 * mm),
        para(
            "Juntar as passagens do ffmpeg numa só economizaria dezenas de "
            "milissegundos num trabalho de dezenas de segundos. Foi descartado: "
            "complicaria o código para um ganho invisível."
        ),
        h("O que foi otimizado, então", "h2"),
        *bullets([
            "<b>SHA-256 calculado uma vez.</b> O supervisor precisa do hash para achar o "
            "ponto de retomada e o pipeline precisa dele para a identidade do arquivo. "
            "Eram duas leituras completas — num vídeo de 4 GB, alguns segundos por "
            "execução, à toa.",
            "<b>WAV extraído direto na pasta do ponto de retomada.</b> Antes ele era "
            "extraído no temporário e copiado; a cópia podia ter centenas de MB.",
            "<b>Modo em lote disponível</b> para quem prioriza velocidade, com o custo "
            "declarado (seção 3).",
        ]),
        h("Peso em disco", "h2"),
        para(
            "Uma instalação completa ocupa cerca de 3,2 GB de bibliotecas — e "
            "<b>61% disso são as bibliotecas CUDA</b>, que só existem para acelerar na "
            "placa de vídeo. Como ninguém descobre isso sozinho, o programa passou a "
            "mostrar a conta e a permitir liberar espaço:"
        ),
        code("lauda disco"),
        Spacer(1, 3 * mm),
        grid(
            ["Componente", "Tamanho", "Necessário?"],
            [
                ["aceleração por GPU (CUDA)", "1,9 GB", "não, se rodar em CPU"],
                ["diarização (PyTorch e cia.)", "726 MB", "não, se não separar falantes"],
                ["núcleo da transcrição", "236 MB", "sim"],
                ["interface no navegador", "148 MB", "não, o app nativo dispensa"],
                ["geração dos PDFs", "34 MB", "não, só para regerar os manuais"],
                ["modelos baixados", "varia", "baixa de novo quando precisar"],
            ],
            widths=[60 * mm, 26 * mm, W - 86 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 2 * mm),
        para(
            "Uma instalação só de CPU, sem diarização e sem interface web, fica em "
            "torno de <b>400 MB</b> — oito vezes menor."
        ),
        PageBreak(),
    ]

    # =================================================================== 9 ====
    story += [
        h("9. O que foi deixado de fora, de propósito"),
        grid(
            ["Recurso", "Por que não"],
            [
                ["Alinhamento forçado (wav2vec2, estilo WhisperX)",
                 "Mais ~1 GB de modelo <b>por idioma</b> para um ganho pequeno sobre os "
                 "timestamps por palavra que o Whisper já entrega. O que fazemos em "
                 "lugar disso: encolher as bordas do trecho até a primeira e a última "
                 "palavra, e remover sobreposições."],
                ["Descrição visual do vídeo com um modelo de visão",
                 "Custa GB de download e minutos por vídeo, para um app cujo produto é "
                 "texto falado. O gancho existe em `visual.py`, desligado."],
                ["Tradução",
                 "O Whisper traduz apenas para o inglês, e mal. Prometer tradução seria "
                 "prometer qualidade que o modelo não entrega."],
                ["Formatador automático de código (`ruff format`)",
                 "Reformataria as tabelas de dados do relatório e dos manuais para uma "
                 "linha por item, tornando-as bem menos legíveis. O lint está ativo e "
                 "limpo; a formatação é mantida à mão."],
                ["Cortar o áudio em janelas antes de transcrever",
                 "Pedido no backlog (janela deslizante de 10 a 60 s, chunk duplo). O "
                 "faster-whisper já percorre o arquivo inteiro em fluxo; fatiar o áudio "
                 "acrescentaria emendas — e é exatamente na emenda que texto some, que "
                 "foi o defeito relatado no BACKLOG-006. A parte aproveitável da ideia, "
                 "<b>cortar onde a fala respira</b>, foi aplicada à legenda "
                 "(`cues.py`), não ao áudio."],
                ["Empacotar um ffmpeg GPL",
                 "O que vai junto é uma compilação <b>LGPL</b> (BtbN). As builds "
                 "completas, com x264 e afins, são GPL e obrigariam o projeto inteiro a "
                 "virar GPL — por transcrever, que não usa nada disso."],
            ],
            widths=[52 * mm, W - 52 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        PageBreak(),
    ]

    # =================================================================== 10 ===
    story += [
        h("10. Qualidade: como sabemos que funciona"),
        grid(
            ["Ferramenta", "Estado", "O que cobre"],
            [
                ["pytest", "151 testes, todos passando",
                 "Do formato do timestamp ao ciclo completo de travar-matar-retomar."],
                ["ruff", "sem apontamentos",
                 "Erros prováveis, segurança (regras bandit), imports, modernização."],
                ["mypy", "sem apontamentos",
                 "30 arquivos, com `check_untyped_defs` e sem `type: ignore` sobrando."],
            ],
            widths=[26 * mm, 44 * mm, W - 70 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        h("Os testes que mais importam", "h2"),
        *bullets([
            "<b>Determinismo</b> — o mesmo arquivo com as mesmas opções produz um "
            "relatório com layout idêntico; só variam relógio e tempos medidos.",
            "<b>Blocos indisponíveis</b> — um vídeo mudo gera relatório completo com "
            "<font face='" + MONO + "'>[INDISPONÍVEL] Transcrição</font>, não uma "
            "exceção.",
            "<b>Retomada sem retrabalho</b> — com um ponto salvo na etapa `asr`, o teste "
            "substitui a função de transcrição por uma que falha se for chamada. Se a "
            "retomada não funcionasse, o teste quebraria.",
            "<b>Processo neto órfão</b> — o worker falso cria um neto que escreve num "
            "arquivo a cada 0,2 s. Depois do travamento e da matança, o arquivo tem de "
            "parar de crescer.",
            "<b>Segredo em disco</b> — verifica que o token não aparece no JSON que o "
            "supervisor grava para o processo filho.",
            "<b>Isolamento do perfil</b> — uma fixture obrigatória redireciona "
            "<font face='" + MONO + "'>~/.lauda</font> para uma pasta temporária. "
            "Ela foi criada depois que um teste de verdade escreveu no perfil real.",
        ]),
        Spacer(1, 3 * mm),
        note(
            "Sobre testes que não testam nada",
            "Vários dos testes acima existem porque um bug apareceu primeiro: o "
            "supervisor que nunca detectava travamento na transcrição, o ffmpeg órfão, "
            "o perfil real sendo sujo pelos testes. Teste que não nasce de um problema "
            "concreto costuma só repetir a implementação.",
        ),
        PageBreak(),
    ]

    # =================================================================== 11 ===
    story += [
        h("11. Empacotar para outra máquina"),
        para(
            "Sair do ambiente de desenvolvimento e virar um instalador que roda na "
            "máquina de outra pessoa levantou quatro decisões — nenhuma delas óbvia, "
            "todas com um custo escrito.",
            "lead",
        ),
        *decision(
            "Ambiente de build separado, sem CUDA e sem Gradio",
            "Um segundo venv (<font name='Mono' size='9'>.venv-build</font>) instala "
            "o torch pelo índice CPU do PyTorch e não instala o extra da interface web.",
            "As bibliotecas CUDA sozinhas somam 1,7 GB — 61% do venv de "
            "desenvolvimento — e o aplicativo de janela não usa Gradio. Empacotar o "
            "ambiente de desenvolvimento levaria o download de 227 MB para mais de 2 GB.",
            "Quem tem placa NVIDIA precisa instalar o extra `gpu` depois, à mão. O "
            "script de build recusa rodar se encontrar esses pacotes, para o engano "
            "não passar despercebido.",
        ),
        *decision(
            "ffmpeg embutido, numa compilação LGPL",
            "O pacote leva ffmpeg e ffprobe junto, de uma compilação LGPL v3.",
            "As compilações comuns do ffmpeg são GPL: distribuí-las junto obrigaria o "
            "projeto inteiro, hoje MIT, a virar GPL. A LGPL permite embutir ao lado de "
            "um aplicativo de outra licença, com aviso e ponteiro para o código-fonte. "
            "Em troca, o usuário deixa de precisar instalar o ffmpeg à parte — que era "
            "o passo onde mais gente travava.",
            "Uns 120 MB e a obrigação de manter o aviso de licença junto. Os codecs "
            "GPL (x264, x265) não vêm — o aplicativo não usa nenhum deles.",
        ),
        *decision(
            "Uma pasta, não um arquivo único",
            "O PyInstaller gera um diretório com o executável e as bibliotecas ao lado, "
            "não um <font name='Mono' size='9'>--onefile</font>.",
            "O modo de arquivo único descompacta ~900 MB num temporário a cada "
            "abertura: dezenas de segundos de espera e um alvo fácil para o antivírus. "
            "Em pasta, o programa abre na hora.",
            "A distribuição precisa de um instalador para não virar “descompacte isto "
            "em algum lugar”. Daí o Inno Setup.",
        ),
        *decision(
            "Podar o que o torch traz e não usa",
            "Os cabeçalhos C++ (<font name='Mono' size='9'>torch/include</font>), as "
            "bibliotecas de link e as licenças de terceiros saem do pacote.",
            "São ~90 MB que só servem para compilar extensões. E há um motivo mais "
            "concreto: eles criam caminhos como "
            "<font name='Mono' size='8'>predicated_tile_access_iterator_residual_last.h</font>, "
            "que estouram o limite de 260 caracteres do Windows e fazem a instalação "
            "falhar em máquina com nome de usuário comprido. Foi assim que o problema "
            "apareceu.",
            "Se um dia o projeto precisar compilar uma extensão do torch em tempo de "
            "execução, a poda tem de ser revista.",
        ),
        h("O que o usuário baixa", "h2"),
        grid(
            ["Item", "Tamanho", "Observação"],
            [
                ["Instalador", "~227 MB", "É o que você manda pela internet."],
                ["Instalado em disco", "~860 MB", "Programa, bibliotecas e ffmpeg."],
                ["Modelo de transcrição", "0,5 a 3 GB",
                 "Baixado na primeira execução, uma vez. Fica em "
                 "<font name='Mono' size='8'>~/.lauda</font> — desinstalar não apaga."],
            ],
            widths=[42 * mm, 28 * mm, W - 70 * mm],
            mono_columns=(),
            strong_columns=(0,),
        ),
        Spacer(1, 3 * mm),
        note(
            "O executável não é assinado",
            "Uma assinatura de código custa algumas centenas de dólares por ano. Sem "
            "ela, o Windows mostra a tela do SmartScreen na primeira execução. O texto "
            "de <b>ANTES-DE-INSTALAR.txt</b> explica isso ao usuário antes que ele se "
            "assuste — omitir o aviso é o caminho mais curto para alguém desistir da "
            "instalação achando que baixou um vírus.",
            AMBER,
        ),
        PageBreak(),
    ]

    # =================================================================== 12 ===
    story += [
        h("12. Limites conhecidos"),
        para(
            "Nenhum destes é um defeito a corrigir depois: são características "
            "assumidas, e o programa fala sobre elas onde o usuário vai encontrá-las."
        ),
        *bullets([
            "<b>O Whisper erra</b> com sotaque forte, ruído, música e falas sobrepostas. "
            "Números, siglas e nomes próprios são o que mais escapa. A opção de prompt "
            "inicial existe justamente para ancorar vocabulário.",
            "<b>Os timestamps por palavra são estimativas</b> do decodificador, não "
            "medição acústica. Servem para legendar, não para perícia.",
            "<b>A diarização só rotula o que foi transcrito.</b> Fala sobreposta vira um "
            "falante só; vozes parecidas podem ser fundidas.",
            "<b>A qualidade depende mais do áudio que do modelo.</b> Microfone perto e "
            "ambiente silencioso melhoram mais que trocar `small` por `large`.",
            "<b>Não substitui revisão humana</b> em uso jurídico, jornalístico, médico "
            "ou acadêmico.",
        ]),
        h("Se este projeto continuar", "h2"),
        para(
            "Na ordem em que fariam mais diferença: processamento de uma pasta inteira "
            "em fila; usar as probabilidades por palavra para marcar no relatório os "
            "trechos de baixa confiança (onde revisar primeiro); e o executor completo "
            "do pyannote, hoje disponível mas sem o mesmo cuidado de teste que o "
            "backend ECAPA recebeu."
        ),
    ]

    doc.multiBuild(story)
    return OUTPUT


def main() -> int:
    path = build()
    print(f"decisões técnicas: {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
