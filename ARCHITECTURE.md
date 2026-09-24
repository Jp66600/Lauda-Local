# Arquitetura — Lauda Local

Mapa para quem chega agora (pessoa ou agente). Responde três perguntas: **onde
está cada coisa**, **como um trabalho corre do começo ao fim** e **o que não se
mexe sem pensar duas vezes**.

Documentos irmãos, todos em `docs/`: o **Manual** (uso), o **Guia rápido**, as
**Decisões técnicas** (o porquê da arquitetura) e o **Front-end** (a interface e
como pedir mudanças nela). Este aqui é o índice.

---

## 1. O que o programa é

Python 3.12 puro, sem servidor e sem nuvem. Um arquivo de áudio ou vídeo entra;
saem um laudo `.txt`, o texto corrido, um `.json` e, se pedido, legendas.

**Não é uma aplicação web.** A interface é uma janela nativa em Tkinter. Não há
HTML, CSS, JavaScript, Electron nem React em lugar nenhum — quem chegar supondo
o contrário vai propor a solução errada.

| | |
|---|---|
| Transcrição | faster-whisper (CTranslate2) |
| Leitura de mídia | ffmpeg / ffprobe, sempre por lista de argumentos, nunca por shell |
| Quem fala | SpeechBrain ECAPA (sem token) ou pyannote (com token) |
| Resumo opcional | Ollama local, `qwen3:14b` |
| Interface | Tkinter, com widgets próprios desenhados em Canvas |

---

## 2. Onde fica cada coisa

```
src/lauda/
  cli.py          os comandos de terminal (run, doctor, disco, models, app, ui)
  desktop.py      a janela nativa: layout, tema, eventos, resultado
  widgets.py      os widgets arredondados (o ttk nao arredonda nada)
  pages.py        Relatorio/Transcricao/Legendas: uma aba por arquivo
  theme.py        as duas paletas + o arquivo de preferencias ui.json

  pipeline.py     a orquestracao: e aqui que se le a ordem das etapas
  probe.py        metadados via ffprobe
  extract.py      audio -> WAV 16 kHz mono
  audio_stats.py  volume, clipping, silencio (e ONDE esta o silencio)
  transcribe.py   faster-whisper
  align.py        encolhe bordas de segmento pelas palavras
  diarize.py      quem fala
  coverage.py     quanto da linha do tempo virou texto
  textstats.py    contagens do laudo
  history.py      o historico de trabalhos (pagina Arquivos)
  summarize.py    Ollama (resumo, escolha e download de modelo)
  visual.py       cortes de cena e miniaturas (so video)
  report.py       o laudo .txt — NOVE secoes, ordem fixa
  cues.py         de que tamanho cada legenda deve ser
  subtitles.py    .srt e .vtt (formata o que o cues.py agrupou)
  serialize.py    o .data.json

  runner.py       supervisiona o processo filho: mata se travar, retoma
  worker.py       o processo filho; fala JSON por linha com o pai
  checkpoint.py   pontos de retomada por sha256 + opcoes
  hardware.py     detecta CPU/RAM/GPU e avalia se a maquina da conta
  limits.py       os limites de uso (sliders e os quatro presets)
  profile.py      a pasta ~/.lauda e a migracao do nome antigo
  logging_setup.py  log em tela e em arquivo, um por processo
```

Fora de `src/`: `tests/` (a suíte), `scripts/` (geradores de PDF, ícone, mídia
de teste, build do instalador), `packaging/` (PyInstaller + Inno Setup),
`docs/` (os PDFs e as capturas).

---

## 3. Como um trabalho corre

```
arquivo
  |
  +-- probe        ffprobe -> container, streams, duracao
  +-- extract      ffmpeg  -> WAV PCM 16 bits, 16 kHz, mono
  +-- vad          volume, silencio, clipping (e os intervalos de silencio)
  +-- asr          faster-whisper -> segmentos + idioma
  +-- align        encolhe bordas pelas palavras, remove sobreposicao
  +-- diarize      embeddings de locutor + clusterizacao (opcional)
  +-- coverage     quanto da linha do tempo virou texto
  +-- render       TXT, texto corrido, JSON, SRT, VTT
```

Cada etapa reporta progresso por callback, e o `pipeline` grava um ponto de
retomada ao fim de cada uma.

**A janela não roda isso no próprio processo.** `runner.run_with_recovery`
levanta um processo filho (`worker.py`), lê dele um fluxo de linhas JSON e o
mata se ele travar — retomando do último ponto salvo, com o modelo rebaixado se
for o caso. É por isso que existem dois arquivos de log.

---

## 4. As regras que não se quebram

Vieram do pedido original ou de defeitos já pagos. Quebrar qualquer uma é
regressão, não escolha de estilo.

1. **Nada sai da máquina.** Sem API paga, sem upload. O Ollama escuta em
   `127.0.0.1` e o esquema da URL é validado.
2. **O arquivo de mídia nunca é executado** — só lido pelo ffmpeg, sempre por
   lista de argumentos.
3. **Bloco que falha vira `[INDISPONÍVEL] <bloco>: <motivo>`** no laudo. Nunca
   some em silêncio.
4. **O laudo tem nove seções, nessa ordem.** Conteúdo novo entra dentro de uma
   delas (foi o que a cobertura fez, no BLOCO A2 da seção 5).
5. **Interface, logs, README e TXT em português do Brasil; código em inglês.**
6. **Nenhuma cor fora de `theme.py`.** É o que faz o modo escuro funcionar
   inteiro.
7. **Nenhum widget retangular do ttk na tela** — Checkbutton, Scrollbar,
   Notebook, Scale e Progressbar não arredondam. Um teste varre a árvore da
   janela e falha se algum voltar.
8. **Só a thread da interface toca em widget.** O que vem do trabalho chega pela
   fila e é desenhado em `_drain_queue`.
9. **`ruff check src tests scripts` e `mypy src` limpos**, e a suíte passando.
   `ruff format` **não** é usado: ele explodiria as tabelas de dados do laudo.
10. **Um processamento por vez.** A fila da página "Novo trabalho" é serial de
    propósito: dois modelos carregados ao mesmo tempo disputam a mesma memória
    e travam a máquina em vez de dobrar a velocidade.

---

## 5. Onde as coisas do usuário ficam

```
~/.lauda/
  ui.json                  tema, limites de maquina, opcoes da tela
  history.json             o historico de trabalhos
  checkpoints/             pontos de retomada
  logs/lauda.log      o aplicativo
  logs/lauda-worker.log  o processamento
```

Os modelos ficam em `LAUDA_MODELS_DIR` (padrão `./models`), baixados uma
vez e reutilizados sem internet.

**Nos testes, esse perfil é isolado por uma fixture autouse no `conftest.py`.**
Script de verificação rodado fora do pytest escreve no perfil real — foi motivo
de sujeira mais de uma vez.

---

## 6. Como rodar

```bash
.\.venv\Scripts\python.exe -m lauda run entrada.mp4 -o saida
```

```bash
.\.venv\Scripts\python.exe -m lauda.desktop
```

```bash
.\.venv\Scripts\python.exe -m pytest tests -q
```

O build do instalador usa um **segundo** ambiente, `.venv-build`, sem CUDA e sem
Gradio de propósito — com eles o download passaria de 2 GB. Detalhes no README,
seção "Empacotar para distribuir".

---

## 7. Se você veio do backlog do Vellum

O arquivo `VELLUM_BACKLOG.md` (o nome é de uma versão anterior do produto) foi escrito sem leitura deste repositório e supõe
Electron/React, `%APPDATA%` e `Promise.all` no STT. Nada disso existe aqui.
Antes de implementar qualquer item de lá, confira a premissa contra este
documento — vários já estavam resolvidos e outros descrevem uma aplicação
diferente.

O produto já teve três nomes: **MediaIntel Local** até a 0.8.0-beta, **Vellum**
na 0.9.0-beta e **Lauda Local** a partir da 0.10.0-beta. Cada troca seguiu o
mesmo roteiro, e ele vale para a próxima se houver: `AppId` novo no instalador,
com um bloco `[Code]` que desinstala as versões anteriores em silêncio;
`profile.py` copiando o perfil antigo para o novo na primeira abertura
(`LEGACY_DIRS`, do mais recente para o mais antigo); e o prefixo de ambiente
anterior continuando a ser lido (`LEGACY_ENV_PREFIXES`).

O que **não** muda de nome é a pasta do código-fonte, que segue
`mediaintel-local`: renomeá-la quebraria os atalhos dos dois ambientes virtuais,
que guardam caminhos absolutos.

O projeto foi publicado como open source (MIT) em 2026-09-19.

### O que não se aplica a este desenho

**BACKLOG-033 (janela deslizante, chunk duplo, N configurável de 10 a 60 s).**
Pressupõe que o áudio seja cortado em pedaços antes da transcrição. Aqui não é:
o faster-whisper recebe o arquivo inteiro e devolve os trechos em fluxo. Cortar
o áudio em janelas acrescentaria exatamente o risco que o BACKLOG-006 relatou —
texto sumindo no meio, na emenda entre pedaços — em troca de nada, já que a
`coverage.py` mostra que hoje não se perde linha do tempo.

O que aquele item tem de aproveitável — **cortar onde a fala respira** — está
implementado em `cues.py`, mas aplicado à legenda, não ao áudio: as legendas
juntam e partem nos limites das palavras e nunca atravessam uma pausa longa.
Se algum dia a transcrição em pedaços virar necessidade (arquivos de horas,
memória curta), este é o item para reabrir — com a cobertura como rede.
