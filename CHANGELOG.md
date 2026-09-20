# Histórico de versões

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/).

## [0.9.0-beta] — 2026-09-08

### Mudado

- **O projeto passou a se chamar Vellum.** Antes era MediaIntel Local. O pacote
  Python virou `vellum`, o executável `Vellum.exe`, os comandos `vellum` e
  `vellum-app`, e o perfil do usuário `~/.vellum`.
- **Migração automática do perfil antigo**: na primeira abertura, `~/.mediaintel`
  (preferências, histórico e pontos de retomada) é **copiado** para `~/.vellum`,
  sem apagar a pasta antiga. O instalador remove a versão anterior sozinho.
- O prefixo de variáveis de ambiente é `VELLUM_`; o antigo `MEDIAINTEL_`
  continua sendo lido.
- No aplicativo empacotado, os modelos passaram a ficar em `~/.vellum/models`:
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
- **Histórico** na página Arquivos, em `~/.vellum/history.json`: quando,
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
