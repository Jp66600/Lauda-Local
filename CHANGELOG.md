# Histórico de versões

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [0.15.0-beta] — 2026-09-24

### Corrigido

- **"Abrir o local do arquivo" abria Documentos.** O `explorer` não lê os
  argumentos pelo caminho normal: ele pega a linha de comando inteira e procura
  o texto `/select,` logo depois do nome do programa. Mandando a lista
  `["explorer", "/select,<caminho>"]`, o Python envolve o argumento todo em
  aspas assim que o caminho tem espaço — a linha passa a começar com `"`, o
  `/select,` deixa de estar onde o explorer procura, e ele abre a pasta padrão
  dele. Só aparecia com espaço no caminho, que é o caso da pasta de saída
  padrão, dentro de "Lauda Local". Agora as aspas vão por dentro:
  `/select,"<caminho>"`.

### Mudado

- **A legenda `.srt` passou a sair por padrão.** Ela é o `[BLOCO B]` do laudo
  noutro formato — os mesmos trechos, os mesmos tempos, o mesmo falante —, e
  tudo de que precisa já está na memória quando o laudo é escrito: custa
  milissegundos e algumas dezenas de KB. Deixá-la desligada por padrão só
  produzia a pergunta "cadê a legenda?". O `.vtt`, que é o mesmo conteúdo para
  vídeo em página web, continua sendo escolha.
- Quem já usava recebe a virada **uma vez**: a preferência `srt: false` gravada
  pela versão anterior é ignorada nesta abertura, e não nas seguintes. Sem
  isso, um padrão novo nunca chega a quem já é usuário — que é justamente quem
  sentiu falta da legenda.
- Na página Legendas, o formato só entra no rótulo da aba **quando é preciso
  para distinguir** (o mesmo trabalho com `.srt` e `.vtt`). Com um formato só,
  o `(.srt)` era repetição comendo sete caracteres do nome do arquivo.

### Adicionado

- **"Gerar as que faltam"**, na página Legendas: escreve a legenda dos
  trabalhos que já foram processados, lendo os trechos do `.data.json` de cada
  um. Nada é transcrito de novo — nos oito trabalhos da máquina de teste, 2.291
  legendas em 0,2 s. O que já existe não é sobrescrito; `.data.json` ilegível
  ou trabalho sem fala guardada aparecem na contagem em vez de sumirem.

## [0.14.0-beta] — 2026-09-24

### Adicionado

- **Página Legendas**, com uma aba por arquivo `.srt` e `.vtt` da pasta de
  saída — os tempos de entrada e saída exatamente como estão no arquivo.
- **Página Registro**, separada da Relatório. Antes o registro ao vivo era um
  modo escondido dela, com um botão alternando as duas coisas no mesmo lugar;
  achar o laudo enquanto o trabalho rodava virava caça ao tesouro. A página tem
  botões para abrir a pasta dos logs e copiar o registro — que é o que se pede
  quando alguém relata um problema.

### Mudado

- **Relatório ganhou as mesmas abas da Transcrição**: uma por arquivo
  processado, com o nome do arquivo de origem, Atualizar, e os três botões
  embaixo. Na página do laudo, o terceiro botão abre o próprio arquivo.
- As três páginas de arquivo (Relatório, Transcrição, Legendas) passaram a ser
  **o mesmo componente** (`pages.py`) com outro sufixo. Eram três cópias em
  potencial — e três cópias garantem que uma correção seja aplicada em duas.
- A barra lateral tem nove páginas.

## [0.13.1-beta] — 2026-09-24

### Corrigido

- **A área das abas da Transcrição tinha um vão acima e abaixo.** A barra de
  rolagem é um `tk.Canvas`, e um Canvas sem tamanho pede ~265 px de altura por
  padrão: esse pedido esticava a linha do grid, e as abas ficavam boiando no
  meio dela. Agora a barra pede 1 px no sentido em que ela se estica, e a área
  tem exatamente a altura das abas.
- A barra de rolagem **some** quando todas as abas cabem, em vez de ficar de
  enfeite.

## [0.13.0-beta] — 2026-09-24

### Corrigido — uma transcrição pronta deixou de ser jogada fora

Três trabalhos de um usuário morreram assim: a transcrição terminava, a
**diarização** demorava, o vigia de travamento matava o processo por silêncio,
o supervisor tentava de novo com o ambiente rebaixado — e o rebaixamento
**invalidava o ponto de retomada**, obrigando a transcrever o arquivo inteiro
outra vez. Três rodadas de horas, e no fim nada foi entregue, com o texto
completo guardado no disco o tempo todo.

Três mudanças fecham esse buraco:

- **A diarização dá sinal de vida.** Ela percorria 1094 trechos em silêncio
  absoluto; agora avisa a cada 20 e o progresso anda na tela. O supervisor
  deixa de confundir lentidão com travamento — que era a causa raiz.
- **O rebaixamento é da etapa que falhou.** Travou identificando quem fala?
  Desliga **a diarização**, não o modelo de transcrição. Antes, trocar o modelo
  invalidava tudo que já estava pronto.
- **As opções de quem fala saíram da identidade do ponto de retomada.** A
  diarização roda depois da transcrição, então mudá-la (ou desligá-la) não
  invalida um texto pronto. Mexer em "quem fala" deixou de custar uma
  transcrição inteira. Quando o ponto salvo é **da** diarização e essas opções
  mudam, ele volta uma etapa — e só a diarização é refeita.

### Adicionado

- **Botão "Atualizar"** na página Transcrição, e a página passa a reler a pasta
  **sempre que é aberta**. Transcrição que chega depois aparece; arquivo que foi
  apagado some. A aba que estava aberta é mantida.

## [0.12.0-beta] — 2026-09-24

### Adicionado

- **Pausar e retomar.** Com um trabalho em andamento, o botão fica ao lado de
  "Processar": ele **congela o processo** onde está — uso de processador a zero
  — e devolve do mesmo ponto ao retomar. Nada é refeito, porque nada é perdido.
  O vigia de travamento tira folga junto: sem isso, pausar por mais de cinco
  minutos seria o mesmo que matar o trabalho.
- O tempo parado **não entra na estimativa** do que falta.

### Mudado

- **As abas da Transcrição agora vêm da pasta de saída**, não do histórico.
  Quem já tinha cinco transcrições na pasta não via nenhuma delas: o histórico
  só conhece o que o aplicativo processou, e só desde a versão que passou a
  guardar o caminho do texto. A pasta é o que a pessoa enxerga no Explorador, e
  é com ela que as abas têm de bater.
- Trocar a pasta de saída troca as abas.
- A área das abas **rola** depois de três linhas: nenhuma transcrição fica
  escondida, e o texto não é empurrado para fora da tela.

### Ressalvas

- Pausar não devolve memória: o modelo continua carregado. Para liberar a
  máquina de verdade, feche — o ponto de retomada assume a partir daí.
- Fechar o aplicativo pausado perde a etapa em andamento (não o que já foi
  transcrito).

## [0.11.0-beta] — 2026-09-23

### Adicionado

- **A página Transcrição virou uma aba por arquivo.** Com uma fila de cinco
  arquivos, ela mostrava só o último — os outros quatro existiam apenas na
  pasta de saída. Agora cada trabalho vira uma aba com o **nome do arquivo de
  origem**, e trocar de aba troca o texto na tela.
- **Botão "Abrir o local do arquivo"**: abre a pasta de saída com o `.txt`
  **já selecionado**, pronto para copiar ou arrastar. Diferente de "abrir o
  laudo", que escancara o arquivo no bloco de notas.
- A página também diz de qual arquivo é o texto na tela — nome, duração,
  modelo e o caminho completo —, além de botões para copiar a transcrição e
  abrir o laudo daquele mesmo trabalho.

### Mudado

- O histórico passou a guardar o caminho do texto corrido
  (`transcript_path`), que é o que alimenta as abas. Entradas gravadas por
  versões anteriores continuam sendo lidas; elas só não aparecem como aba.
- Aba de arquivo que saiu do disco (apagado, pasta movida) some da página:
  aba que abre o vazio é pior que aba nenhuma.

## [0.10.0-beta] — 2026-09-23

### Mudado

- **O projeto passou a se chamar Lauda Local.** *Lauda* é a página padrão de
  texto — o que o programa entrega — e *Local* é a promessa que ele cumpre. O
  pacote Python virou `lauda`, o executável `Lauda Local.exe`, os comandos
  `lauda` e `lauda-app`, e o perfil do usuário `~/.lauda`.
- **A migração de perfil agora conhece os dois nomes anteriores**: na primeira
  abertura, `~/.vellum` ou `~/.mediaintel` (preferências, histórico e pontos de
  retomada) é **copiado** para `~/.lauda`, sem apagar a pasta antiga.
- **O instalador remove sozinho as duas versões anteriores** — Vellum e
  MediaIntel Local —, para não sobrar programa repetido na lista.
- O prefixo de variáveis de ambiente é `LAUDA_`; os antigos `VELLUM_` e
  `MEDIAINTEL_` continuam sendo lidos.

## [0.9.0-beta] — 2026-09-08

### Mudado

- **O projeto passou a se chamar Vellum.** Antes era MediaIntel Local. O pacote
  Python virou `vellum`, o executável `Vellum.exe` e o perfil do usuário
  `~/.vellum`.
- **Migração automática do perfil antigo**: na primeira abertura, `~/.mediaintel`
  (preferências, histórico e pontos de retomada) é **copiado** para o perfil
  novo, sem apagar a pasta antiga. O instalador remove a versão anterior
  sozinho.
- No aplicativo empacotado, os modelos passaram a ficar no perfil do usuário:
  desinstalar e reinstalar não obriga mais a baixar tudo de novo.
- **A página Desempenho virou três abas**: Resumo (quatro presets com nome
  comum), Limites (os quatro controles finos) e Diagnóstico (o que foi medido,
  sempre visível). O Resumo avisa **antes** quando o modelo será rebaixado por
  falta de memória, e explica que na GPU o medidor do processador fica parado de
  propósito.

### Adicionado

- **Tamanho das legendas** como escolha: curtas (1–2 s), equilibrada (5–8 s,
  padrão) ou blocos longos. Com "marcar o tempo das palavras" ligado, o corte
  cai na palavra. Nenhum modo perde texto, atravessa pausa longa ou mistura
  falantes.

### Corrigido

- A janela do aplicativo empacotado mostrava o ícone padrão do Tk.
- Legenda estourava a largura de duas linhas porque o rótulo do falante não
  entrava no orçamento de caracteres.

### Recusado, com justificativa

- Janela deslizante / transcrição em pedaços: o motor já percorre o arquivo
  inteiro em fluxo, e fatiar criaria a emenda onde o texto some. Ver
  "O que não se aplica a este desenho" no `ARCHITECTURE.md`.

## [0.8.0-beta] — 2026-09-07

### Adicionado

- **Fila de arquivos serial**: solte vários de uma vez; eles rodam um por vez.
  Soltar durante um trabalho põe no fim da fila, e um arquivo com erro não para
  os outros. A fila inteira usa as opções de quando você clicou em Processar.
- **Histórico** na página Arquivos, em `~/.lauda/history.json`: quando,
  duração, qualidade, CPU ou GPU, velocidade, cobertura, avisos e a confiança da
  transcrição, com destaque para o que merece um olhar.
- Seção Ollama em Configurações: status, verificação e download do modelo com
  porcentagem.

### Corrigido

- O pedido de um modelo com tag (`qwen3:14b`) era atendido por outro da mesma
  família (`qwen3:8b`) **e relatado como o pedido**.
- Os dois processos giravam o mesmo arquivo de log, o que falha no Windows.

## [0.7.0-beta] — 2026-09-06

### Adicionado

- **Primeira versão distribuível**: instalador para Windows (PyInstaller + Inno
  Setup), com ffmpeg LGPL embutido.
- **Cobertura da linha do tempo**: todo laudo mede quanto do arquivo virou texto
  e lista os trechos sem fala que **não** são silêncio.
- Diagnóstico da máquina ao abrir, com aviso e escolha entre fechar e continuar.
- Registro ao vivo durante o trabalho e estimativa de tempo restante.

## [0.6.0] — 2026-09-05

### Adicionado

- Janela nativa redesenhada: barra lateral com sete páginas, arrastar-e-soltar,
  interruptores arredondados e trilha de cinco etapas.
- Tema claro/escuro seguindo o Windows.

## [0.5.0] — 2026-09-04

### Adicionado

- Primeira versão completa: CLI, VAD, legendas SRT/VTT, diarização, camada
  visual, resumo opcional via Ollama e recuperação por pontos de retomada.
