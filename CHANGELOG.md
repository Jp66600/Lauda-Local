# Histórico de versões

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

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
