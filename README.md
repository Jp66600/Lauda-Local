# Lauda Local

[![CI](https://github.com/Jp66600/Lauda-Local/actions/workflows/ci.yml/badge.svg)](https://github.com/Jp66600/Lauda-Local/actions/workflows/ci.yml)
[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Windows · Linux · macOS](https://img.shields.io/badge/windows%20%C2%B7%20linux%20%C2%B7%20macOS-lightgrey.svg)](#pré-requisitos)

**Transcrição e laudo de áudio e vídeo, 100% no seu computador.**

Você aponta um arquivo; ele devolve um **laudo em `.txt`** com metadados
técnicos, diagnóstico do áudio, idioma detectado e transcrição com marcação de
tempo — mais um **`.json`** estruturado e, se quiser, legendas **`.srt`/`.vtt`**.

Nenhum byte do seu arquivo sai da máquina. Nenhuma API paga, nenhuma conta,
nenhuma telemetria. Os modelos são baixados uma vez e reutilizados offline para
sempre.

```bash
lauda run entrevista.mp4 --diarize --srt -o saida
```

…ou abra a janela e arraste o arquivo para dentro:

```bash
lauda-app
```

---

## Por onde começar

| Você quer | Faça isto |
|---|---|
| **Só usar**, no Windows | Baixe o instalador em [Releases](https://github.com/Jp66600/Lauda-Local/releases). Ele traz tudo dentro, inclusive o ffmpeg, e não precisa de Python. |
| **Usar pelo terminal** | [Instalação](#instalação) → `lauda run arquivo.mp4 -o saida` |
| **Mexer no código** | [CONTRIBUTING.md](CONTRIBUTING.md) — ambiente, testes e as nove regras que não se quebram |
| **Entender como foi feito** | [ARCHITECTURE.md](ARCHITECTURE.md) — o mapa curto: onde fica cada coisa e como um trabalho corre |

### Os manuais

Todos gerados por script a partir do código, então não envelhecem sozinhos:

| Documento | Páginas | Para quem |
|---|---|---|
| [Guia rápido](docs/Lauda-Local-Guia-Rapido.pdf) | 3 | quem só quer transcrever um arquivo hoje |
| [Manual completo](docs/Lauda-Local-Manual.pdf) | 18 | cada tela, cada opção e o que fazer quando dá errado |
| [Decisões técnicas](docs/Lauda-Local-Decisoes-Tecnicas.pdf) | 16 | o porquê de cada escolha, as medições e os limites assumidos |
| [Front-end](docs/Lauda-Local-Front-End.pdf) | 16 | como a interface foi construída e como pedir mudanças nela |

---

## O que há de novo

A lista completa está no [CHANGELOG.md](CHANGELOG.md). Os destaques recentes:

**0.12.0-beta**
- **Pausar e retomar** um trabalho em andamento: o processo congela onde está
  (processador a zero) e volta do mesmo ponto. Nada é refeito.
- **As abas da Transcrição leem a pasta de saída**: tudo que está lá vira aba,
  inclusive o que foi transcrito em outro dia.

**0.11.0-beta**
- **Uma aba por arquivo na página Transcrição**, com o nome do arquivo de
  origem. Processou cinco de uma vez? As cinco transcrições ficam a um clique,
  em vez de só a última.
- **Botão "Abrir o local do arquivo"**: a pasta de saída abre com o `.txt` já
  selecionado, pronto para copiar.

**0.10.0-beta** — o projeto virou **Lauda Local**. Já se chamou *MediaIntel
Local* e *Vellum*; quem usava não perde nada, porque o perfil antigo é copiado
para o novo na primeira abertura e o instalador remove as versões anteriores
sozinho.

**0.9.0-beta**
- **Tamanho das legendas** virou escolha: curtas (1–2 s), equilibradas (5–8 s)
  ou blocos longos. Nenhum modo perde texto nem deixa legenda na tela durante
  uma pausa.
- **Página Desempenho em três abas**: quatro opções prontas (Leve, Equilibrado,
  Rápido, Máximo), os controles finos e o diagnóstico da máquina sempre visível.
  Ele avisa **antes** quando o trabalho vai exigir mais memória do que sobrou.

**0.8.0-beta**
- **Fila de arquivos**: solte vários de uma vez; rodam um por vez, e um arquivo
  com erro não para os outros.
- **Histórico** de tudo que já passou, com cobertura, velocidade e confiança.

**0.7.0-beta**
- **Cobertura da linha do tempo**: todo laudo mede quanto do arquivo virou texto
  e lista os trechos sem fala que **não** são silêncio. É a rede de segurança
  contra o pior defeito possível num transcritor — sumir com um pedaço sem
  avisar.
- Instalador para Windows, com ffmpeg embutido.

---

## O que ele faz

- Lê metadados completos com **ffprobe** (container, streams, tags, capítulos).
- Extrai e normaliza o áudio com **ffmpeg** (WAV PCM 16 bits, 16 kHz, mono).
- Diagnostica o áudio: volume médio/pico, clipping, silêncio, avisos de qualidade.
- Transcreve offline com **faster-whisper** (CTranslate2), com **VAD** ligado.
- Detecta o idioma (ou aceita o idioma forçado por você).
- Gera timestamps por segmento — e por palavra, se você pedir.
- Identifica quem fala (**diarização**), com backend que dispensa token do Hugging Face.
- Escreve `report.txt`, `transcript.txt`, `data.json` e, se quiser, `.srt`/`.vtt`.
- Escolhe sozinho device/modelo conforme sua GPU/RAM e **cai para CPU** se a GPU falhar.
- Tem CLI e **aplicativo em janela própria**, com modo claro e escuro.
- Deixa você **limitar quanto da máquina** ele pode usar (CPU, RAM, GPU, VRAM).
- **Retoma de onde parou** se travar ou for interrompido, sem transcrever de novo.
- Opcional: cortes de cena + thumbnails (vídeo) e resumo com **Ollama** local.

## O que ele NÃO faz

- Não é editor de áudio/vídeo: não corta, não converte, não exporta mídia.
- Não envia nada para a nuvem (nem para "melhorar o modelo").
- Não faz tradução automática.
- Não substitui revisão humana: Whisper erra, principalmente com sotaque
  carregado, música, ruído e falas sobrepostas.
- Não faz alinhamento forçado (wav2vec2): usa os timestamps por palavra do
  próprio Whisper e só refina as bordas dos segmentos.
- Não descreve o conteúdo visual do vídeo por padrão (o gancho para um VLM
  local existe, mas vem desligado).

---

## Pré-requisitos

| Item | Versão | Obrigatório |
|---|---|---|
| Python | 3.11 – 3.13 (**3.12 recomendado**) | sim |
| ffmpeg + ffprobe | 6 ou superior, no PATH | sim |
| GPU NVIDIA | CUDA 12 + cuDNN 9 | não (acelera muito) |

> **Python 3.14 ainda não funciona**: `ctranslate2` não publica wheels para essa
> versão. Use 3.12.

### Instalando o ffmpeg

```bash
winget install --id Gyan.FFmpeg -e
```

- **macOS**: `brew install ffmpeg`
- **Linux (Debian/Ubuntu)**: `sudo apt install ffmpeg`

Se preferir não mexer no PATH, aponte os binários no `.env`:

```
LAUDA_FFMPEG=C:\ffmpeg\bin\ffmpeg.exe
LAUDA_FFPROBE=C:\ffmpeg\bin\ffprobe.exe
```

---

## Instalação

### Baixar

Quem só quer **usar** no Windows: pegue o instalador em
[Releases](https://github.com/Jp66600/Lauda-Local/releases) — ele traz tudo dentro,
inclusive o ffmpeg, e não precisa de Python.

Quem quer **mexer no código**:

```bash
git clone https://github.com/Jp66600/Lauda-Local.git
cd Lauda-Local
```

### Windows (PowerShell)

```bash
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; pip install -e .
```

> **Atenção ao `&&`**: o Windows PowerShell 5.1 (o que vem no Windows) não
> aceita `&&` como separador — ele responde
> *"O token '&&' não é um separador de instruções válido nesta versão"*. Use
> `;` para encadear comandos, como nos exemplos deste README. O PowerShell 7+
> (`pwsh`) aceita os dois.

### macOS / Linux

```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && pip install -e .
```

### Com uv (opcional, mais rápido)

```bash
uv venv --python 3.12; uv pip install -r requirements.txt; uv pip install -e .
```

Copie o `.env.example` para `.env` se quiser mudar os padrões:

```bash
copy .env.example .env
```

---

## O aplicativo (janela própria, sem navegador)

Crie o atalho uma única vez:

```bash
powershell -ExecutionPolicy Bypass -File scripts\create_shortcut.ps1
```

Isso põe **Lauda Local** na Área de Trabalho, com ícone próprio, apontando
direto para `lauda-app.exe`. Dois cliques abrem uma **janela nativa** — não
é site, não abre navegador e não fica console preto atrás. Use `-StartMenu` para
criar também no Menu Iniciar, ou `-NoDesktop` para só lá.

A janela tem uma **barra lateral** com sete páginas — Novo trabalho, Relatório,
Transcrição, Arquivos, Desempenho, Ajuda e Configurações. Em "Novo trabalho" você
**arrasta o áudio ou vídeo** para a área tracejada (ou clica nela para abrir o
explorador de arquivos do sistema); à direita ficam idioma, qualidade, os
recursos opcionais e a pasta de saída; no rodapé, o botão Processar e uma
**trilha de cinco etapas** que acende conforme o trabalho anda. O relatório
aparece na página Relatório assim que termina.

Dá para soltar (ou escolher) **vários arquivos de uma vez**: o primeiro vai para
o cartão e o resto entra numa fila, processada **um por vez** — dois modelos
carregados ao mesmo tempo brigam pela mesma memória. Arquivo com erro no meio da
fila não interrompe os outros, e a fila inteira roda com as opções de quando
você clicou em Processar. O **tamanho das legendas** é escolha sua — curtas
(1–2 s), equilibradas (5–8 s, o padrão) ou blocos longos —, e não mais um
acidente de como o modelo cortou os trechos.

Terminada a fila, a página **Transcrição** tem **uma aba por arquivo**, com o
nome do arquivo de origem: clicar troca o texto na tela. Embaixo dele, um botão
**Abrir o local do arquivo** escancara a pasta de saída com o `.txt` já
selecionado — não precisa caçar nada. A página **Arquivos** guarda o
**histórico** de todos os trabalhos (duração, qualidade, CPU ou GPU, velocidade,
cobertura, avisos e confiança), em `~/.lauda/history.json`.

O arrastar-e-soltar precisa do extra `desktop`
(`pip install "lauda[desktop]"`). Sem ele a área continua funcionando
pelo clique, e o texto muda para não prometer o que não faz.

**Diagnóstico na abertura**: ao abrir, o aplicativo olha processador, memória,
placa de vídeo, espaço em disco e a presença do ffmpeg. O veredito fica na página
**Desempenho**; se a máquina for fraca demais, aparece um aviso com o que foi
medido, o caminho dos controles de desempenho e a escolha entre **fechar o
aplicativo** e **continuar mesmo assim**. Dá para marcar "não avisar de novo" —
fica guardado em `~/.lauda/ui.json`.

**As escolhas ficam guardadas**: idioma, qualidade, os interruptores de recurso
e a pasta de saída voltam como você deixou, em `~/.lauda/ui.json`. A página
**Configurações** resume o que está guardado e tem o botão **Restaurar padrões**;
o passo a passo mudou para a página **Ajuda**.

**Enquanto processa, a página Relatório mostra o registro ao vivo** — arquivo,
modelo, device e cada etapa, conforme acontecem. Ao terminar ela passa a mostrar
o laudo, e o botão **Ver o registro** volta para o que aconteceu. Tudo também vai
para `~/.lauda/logs/`; o processo que faz o trabalho pesado escreve num
arquivo separado (`lauda-worker.log`), porque dois processos girando o mesmo
arquivo rotativo dá erro no Windows.

**Tempo restante**: depois de 8% do trabalho o app passa a dizer quanto falta,
pelo ritmo medido — antes disso a conta seria dominada pelo carregamento do
modelo e daria um número ridículo. Aparece no status e sob a etapa atual.

**Cobertura da linha do tempo**: todo relatório mede quanto do arquivo virou
texto e lista os trechos que ficaram de fora **e não são silêncio** — pausa é
sucesso, não buraco. Abaixo de 95% o app avisa na tela e no log. É a resposta
para a pergunta que nenhum relatório respondia: *o arquivo inteiro foi lido?*

**Quando o trabalho termina**, em Configurações: abrir a pasta de saída e deixar
uma cópia da legenda ao lado do vídeo — é isso que faz o player achá-la sozinho.
As duas vêm ligadas; a cópia na pasta de saída continua onde estava.

**Modo escuro**: o botão na página **Configurações** alterna claro/escuro, e a
escolha fica guardada em `~/.lauda/ui.json`. Sem escolha salva, o app segue
o tema do Windows. Também dá para forçar na abertura:

```bash
.\.venv\Scripts\lauda.exe app --theme escuro
```

Pelo terminal, a mesma janela:

```bash
.\.venv\Scripts\lauda.exe app
```

A interface de navegador (Gradio) continua existindo como alternativa —
`lauda ui` — útil para acessar de outro computador da rede local.

---

## Primeiro uso

**1. Cheque o ambiente:**

```bash
lauda doctor
```

Ele mostra ffmpeg, GPU/VRAM, RAM, modelos em cache e por que a diarização está
desligada. Se o ffmpeg aparecer como `AUSENTE`, resolva isso antes de seguir.

**2. Gere um arquivo de exemplo** (áudio sintético + vídeo mudo + arquivo inválido):

```bash
python scripts/make_test_media.py
```

**3. Processe:**

```bash
lauda run tests/_media/tone.wav --model tiny --output ./saida
```

**4. Um caso real, com legendas e timestamps por palavra:**

```bash
lauda run "C:\videos\entrevista.mp4" -m small -l pt --srt --vtt --words -o .\saida
```

Saída em `./saida`:

```
entrevista.report.txt      laudo completo (o produto principal)
entrevista.transcript.txt  só o texto corrido
entrevista.data.json       estrutura machine-readable
entrevista.srt / .vtt      legendas (se pedidas)
```

---

## Comandos

```bash
lauda run <arquivo> [opções]
```

| Opção | Padrão | Para que serve |
|---|---|---|
| `-o, --output` | `./saida` | Pasta de saída |
| `-m, --model` | `small` | `tiny`…`large-v3-turbo` |
| `-l, --lang` | `auto` | `auto`, `pt`, `en`, `es`, … |
| `-d, --device` | `auto` | `auto`, `cpu`, `cuda` |
| `--compute-type` | `auto` | `int8`, `int8_float16`, `float16`, `float32` |
| `--beam-size` | `5` | 1 é mais rápido, 5 é mais preciso |
| `--vad / --no-vad` | ligado | Filtro de voz (evita alucinação em silêncio) |
| `--words` | desligado | Timestamps por palavra (Bloco C do TXT) |
| `--diarize` | desligado | Identificar falantes (ver *Diarização*) |
| `--diarize-backend` | `auto` | `auto`, `pyannote`, `ecapa` |
| `--num-speakers` | — | Número exato de falantes, se você souber |
| `--min-speakers`, `--max-speakers` | — | Faixa esperada de falantes |
| `--speaker-threshold` | `0.30` | Distância de cosseno no backend `ecapa` |
| `--srt`, `--vtt` | desligado | Também gerar legendas |
| `--legenda-tamanho` | `equilibrada` | Tamanho das legendas: `curta` (1–2 s), `equilibrada` (5–8 s) ou `longa` (blocos de até 1 min) |
| `--no-json` | — | Não gerar o `.data.json` |
| `--visual` | desligado | Cortes de cena + thumbnails (só vídeo) |
| `--summarize` | desligado | Bloco de resumo via Ollama local |
| `--batch-size` | `0` | Modo rápido: transcreve em lotes (0 = desligado) |
| `--cpu` | `100` | Limite de CPU em % (vira nº de threads) |
| `--ram` | `50` | Limite de RAM em % (teto para escolher o modelo) |
| `--gpu` | `100` | Limite de GPU em % (**0 desliga a placa**) |
| `--vram` | `100` | Limite de VRAM em % (teto para escolher o modelo) |
| `--recover / --no-recover` | ligado | Supervisiona: mata se travar e retoma |
| `--resume / --no-resume` | ligado | Usar pontos de retomada salvos |
| `--stall-timeout` | `300` | Segundos sem sinal antes de considerar travado |
| `--attempts` | `3` | Tentativas antes de desistir |
| `--prompt` | — | Prompt inicial: nomes próprios, jargão, siglas |
| `--keep-temp` | desligado | Não apagar o WAV temporário (debug) |
| `-v`, `-q` | — | Log detalhado / silencioso |

Outros comandos:

```bash
lauda app          # aplicativo em janela própria (o normal)
lauda doctor       # diagnóstico do ambiente
lauda models       # tabela de modelos e o que cabe na sua máquina
lauda checkpoints  # trabalhos interrompidos que dá para retomar
lauda disco        # quanto ocupa em disco e o que dá para liberar
lauda ui           # interface no navegador (alternativa, precisa do Gradio)
```

### Interface local

```bash
pip install "lauda[ui]"; lauda ui
```

A UI abre em `http://127.0.0.1:7860` e traz arrastar-e-soltar, seletor de
modelo e idioma, todos os toggles, barra de progresso por etapa
(`probe → extract → vad → asr → align → diarize → render`), escolha da pasta de
saída, download dos arquivos gerados e histórico da sessão. `--share` expõe a
porta na **rede local** (`0.0.0.0`); nunca cria túnel público.

---

## Limites de uso da máquina

A página **Desempenho** tem três abas. **Resumo** traz quatro opções prontas —
**Leve**, **Equilibrado**, **Rápido** e **Máximo** — e diz, em português, o que
elas significam agora: onde a transcrição vai rodar, com quantas threads e com
qual modelo. Ela também compara o trabalho pedido com o que os limites liberam e
**avisa antes** quando o modelo vai ser rebaixado por falta de memória.
**Diagnóstico** mostra o que foi medido no computador, item a item, sempre na
tela.

A aba **Limites** tem os quatro controles finos. Eles não são enfeite — cada um
mexe em algo concreto:

| Controle | O que realmente faz |
|---|---|
| **CPU** | Vira número de threads do motor e do ffmpeg. Em 25%, o app usa 1/4 dos núcleos. Abaixo de 60% também rebaixa a prioridade do processo. |
| **RAM** | Teto de memória considerado ao escolher o modelo em CPU. Modelo que não cabe é trocado por um menor, com aviso no relatório. |
| **GPU** | Em **0% a placa é ignorada** e tudo roda na CPU. Acima disso, controla o paralelismo (`num_workers`). |
| **VRAM** | Teto de VRAM para escolher o modelo. É o que impede um modelo grande demais de estourar a placa. |

**Honestidade sobre a GPU**: o CUDA não tem um botão de "usar 50% da placa".
O controle mais próximo que dá para oferecer sem mentir é ligar/desligar e
ajustar o paralelismo — e é isso que o slider faz. Já os limites de memória
mudam de verdade qual modelo é carregado.

Pela linha de comando:

```bash
lauda run entrevista.mp4 --cpu 50 --gpu 0
```

A escolha feita na janela fica salva em `~/.lauda/ui.json`.

---

## Modo rápido (opcional)

O faster-whisper sabe transcrever em lotes. Medimos, no mesmo áudio de 5 minutos:

| Cenário | Tempo | Trechos | Trecho médio |
|---|---|---|---|
| GPU, sequencial | 12,54 s | 60 | 4,3 s |
| **GPU, em lote (16)** | **6,25 s** | 10 | 29,7 s |
| CPU, sequencial | 30,83 s | 62 | 4,9 s |
| **CPU, em lote (8)** | **23,05 s** | 10 | 30,4 s |

**2x mais rápido na GPU — e trechos ~6x mais longos.** Um trecho de 30 segundos
é inútil como legenda e atrapalha a diarização, que atribui um falante por
trecho. Por isso o modo rápido é **opt-in** e nunca o padrão:

```bash
lauda run entrevista.mp4 --batch-size 16
```

Na janela, o interruptor **Modo rápido** fica na página Desempenho, com o custo escrito
ao lado.

---

## Quanto ocupa em disco

```bash
lauda disco
```

Uma instalação completa passa de 3 GB de bibliotecas — e **61% disso são as
bibliotecas CUDA**, que só existem para acelerar na placa de vídeo. O comando
mostra a conta por componente e diz o que dá para remover:

| Componente | Tamanho | Precisa? |
|---|---|---|
| aceleração por GPU (CUDA) | ~1,9 GB | não, se rodar em CPU |
| diarização (PyTorch e cia.) | ~726 MB | não, se não separar falantes |
| núcleo da transcrição | ~236 MB | **sim** |
| interface no navegador | ~148 MB | não, o app nativo dispensa |
| geração dos PDFs | ~34 MB | não, só para regerar os manuais |
| modelos baixados | varia | baixa de novo quando precisar |

Uma instalação só de CPU, sem diarização e sem interface web, fica em torno de
**400 MB**. Para liberar um modelo específico:

```bash
lauda disco --remover large-v3-turbo
```

---

## Se travar: pontos de retomada

Processar áudio longo é demorado, e coisas dão errado — a placa engasga, falta
memória, o computador desliga. O app trata isso em duas camadas.

**1. Pontos de retomada.** Depois de cada etapa cara, o estado parcial é
gravado em `~/.lauda/checkpoints/`. Se o processo morrer, a próxima
execução **do mesmo arquivo com as mesmas opções** continua de onde parou. Na
prática: a transcrição não é refeita. O áudio já extraído também fica guardado.

Trocar a pasta de saída ou pedir legenda **não** invalida o ponto salvo; trocar
o modelo, o idioma ou desligar a GPU, sim — porque aí o resultado seria outro.

**2. Supervisor.** O processamento roda num processo separado, vigiado. Se ele
parar de dar sinal de vida, o supervisor **mata o processo** (um travamento
dentro de código nativo não responde a nada mais suave), volta do último ponto
salvo e tenta de novo com o ambiente rebaixado: primeiro sem GPU, depois com um
modelo menor.

Ver e limpar o que ficou guardado:

```bash
lauda checkpoints
```

```bash
lauda checkpoints --limpar
```

Para desligar o supervisor (roda direto no processo atual):

```bash
lauda run entrevista.mp4 --no-recover
```

---

## Tabela de modelos

Memória aproximada com `int8`. As colunas de velocidade são **ordens de
grandeza esperadas, não benchmarks medidos neste projeto** — meça na sua
máquina com `-m tiny` antes de escolher. A unidade é *x tempo real*: 10x
significa "10 minutos de áudio em 1 minuto".

| Modelo | Memória | GPU 4 GB (int8_float16) | CPU 8–12 threads (int8) | Qualidade |
|---|---|---|---|---|
| `tiny` | 0,5 GB | muito rápida | ~5–10x | rascunho |
| `base` | 0,7 GB | muito rápida | ~3–6x | fraca |
| `small` | 1,2 GB | rápida | ~1,5–3x | **boa — padrão** |
| `medium` | 2,4 GB | média | abaixo de 1x | muito boa |
| `large-v3-turbo` | 2,2 GB | média | ~1x | **melhor custo/benefício** |
| `distil-large-v3` | 2,2 GB | média | ~1x | quase large, mais rápida |
| `large-v3` | 3,6 GB | não cabe em 4 GB | bem abaixo de 1x | melhor absoluta |

Regra prática para calibrar expectativa: **áudio de 10 minutos com `small` em
CPU moderna termina em minutos, não em horas**. O relatório sempre informa o
fator real (`Velocidade: 2,10x tempo real`) — use esse número, não a tabela.

O app não deixa você estourar a memória: se o modelo pedido não couber no
orçamento (VRAM − 0,8 GB, ou metade da RAM na CPU), ele **rebaixa
automaticamente** e escreve o motivo no relatório e no terminal.

---

## Modelos offline

Baixe uma vez:

```bash
python scripts/download_models.py --model small --model large-v3-turbo
```

Os pesos vão para `./models` (pasta ignorada pelo git). Para garantir que nada
seja baixado durante o processamento:

```bash
set LAUDA_OFFLINE=1
```

(no PowerShell: `$env:LAUDA_OFFLINE=1`; no bash: `export LAUDA_OFFLINE=1`)

---

## Diarização (identificar quem fala)

Instale as dependências (só uma vez):

```bash
pip install -r requirements-diarize.txt
```

Depois basta ligar a flag:

```bash
lauda run entrevista.mp4 -m small -l pt --diarize --srt
```

O relatório passa a trazer `SPEAKER_00`, `SPEAKER_01`… nos segmentos, o tempo
de fala por falante na seção 6 e os rótulos nas legendas.

### Dois backends

| Backend | Modelo | Token do Hugging Face | Quando usar |
|---|---|---|---|
| `ecapa` | `speechbrain/spkrec-ecapa-voxceleb` | **não precisa** | padrão prático; funciona sem burocracia |
| `pyannote` | `pyannote/speaker-diarization-3.1` | **obrigatório** (modelo *gated*) | melhor qualidade, sobretudo com fala sobreposta |

Com `--diarize-backend auto` (padrão) o app usa o pyannote quando há token ou
pesos locais e, caso contrário, cai para o ECAPA.

**Como o ECAPA funciona aqui**: cada segmento transcrito é dividido em trechos
de até 4 s, cada trecho vira um *embedding* de locutor, e os trechos são
agrupados por clusterização aglomerativa (distância de cosseno). Se você sabe
quantas pessoas falam, `--num-speakers 2` melhora bastante o resultado.
Se estiver juntando pessoas demais, baixe o `--speaker-threshold`; se estiver
inventando falantes, suba.

**Limite honesto**: a diarização só rotula o que o Whisper transcreveu. Fala
sobreposta vira um falante só, e vozes parecidas podem ser fundidas.

### Ligando o pyannote (opcional)

1. `pip install "pyannote.audio>=3.3,<4"`
2. Aceite os termos dos modelos *gated*, logado na sua conta do Hugging Face:
   - <https://hf.co/pyannote/segmentation-3.0>
   - <https://hf.co/pyannote/speaker-diarization-3.1>
3. Crie um token em <https://hf.co/settings/tokens> e coloque no `.env`:
   `HF_TOKEN=hf_...`
4. `lauda doctor` deve mostrar `Diarização: pronta`.

Sem token e sem pesos locais, o app usa o ECAPA — e, se nem ele estiver
instalado, desliga a diarização com aviso explícito em vez de quebrar.

---

## Resumo local com Ollama (opcional)

Se você já roda o [Ollama](https://ollama.com) na máquina, o relatório ganha um
bloco com resumo, tópicos, itens de ação e citações — sem sair do computador:

```bash
ollama pull qwen3:14b; lauda run entrevista.mp4 --summarize
```

Configure host e modelo no `.env` (`OLLAMA_HOST`, `OLLAMA_MODEL`).
Transcrições longas são resumidas em duas passadas (parciais → consolidação)
para caber na janela de contexto de modelos pequenos. Se o Ollama não estiver
no ar, ou o modelo não estiver baixado, o bloco sai como `[INDISPONÍVEL]` com o
motivo e **o pipeline continua normalmente**.

---

## Camada visual (vídeo)

```bash
lauda run video.mp4 --visual
```

Só ffmpeg, sem modelo de visão: conta cortes de cena, extrai uma thumbnail a
cada 30 s numa pasta `{nome}.assets/` e compara resolução codificada vs.
exibida (considerando rotação). O gancho `describe_frames_hook` em
`visual.py` existe para plugar um VLM local (LLaVA/Qwen-VL via Ollama) no
futuro e vem **desligado de propósito**.

---

## Docker (opcional)

O MVP não exige Docker. Se quiser isolar o ambiente:

```bash
docker build -t lauda .
```

```bash
docker run --rm -v "$PWD/midia:/data:ro" -v "$PWD/saida:/saida" -v "$PWD/models:/app/models" lauda run /data/entrevista.mp4 -m small -o /saida
```

A imagem é CPU-only e já traz o ffmpeg. Os modelos ficam num volume, então a
imagem não carrega pesos. Para GPU, troque a base por
`nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04` e rode com `--gpus all`.

---

## Troubleshooting

**`ffmpeg AUSENTE` / "Não encontrei ffmpeg"**
Instale (seção acima) e abra um terminal novo, ou aponte `LAUDA_FFMPEG` /
`LAUDA_FFPROBE` no `.env`. O app procura no PATH e nos diretórios comuns
(`C:\ffmpeg\bin`, WinGet Links, scoop, Homebrew, `/usr/bin`).

**`Could not locate cudnn_ops64_9.dll` (ou erro de cuBLAS)**
O CTranslate2 4.x precisa de CUDA 12 + cuDNN 9. Caminho mais simples:

```bash
pip install -r requirements-gpu.txt
```

Se ainda falhar, o app cai sozinho para CPU e registra
`Fallback para CPU: ...` no relatório. Para forçar: `--device cpu`.

**GPU sem VRAM / `out of memory`**
Use um modelo menor (`-m small`), ou `--compute-type int8`, ou `--device cpu`.
Com 4 GB de VRAM, `large-v3` não cabe — use `large-v3-turbo`.

**pyannote "gated" / 401 no Hugging Face**
Você não aceitou os termos do modelo com a mesma conta do token. Veja a seção
*Diarização* — ou simplesmente use `--diarize-backend ecapa`, que não pede token.

**`WinError 1314` ao carregar o modelo de diarização**
O speechbrain tenta criar links simbólicos, e o Windows exige privilégio para
isso. O app já força cópia em vez de symlink; se você viu esse erro, atualize o
projeto ou ative o Modo de Desenvolvedor do Windows.

**Diarização junta ou inventa falantes**
Passe `--num-speakers N` se souber quantas pessoas falam. Sem isso, ajuste
`--speaker-threshold` (padrão 0,30): menor separa mais, maior junta mais.

**O processamento travou**
O supervisor detecta sozinho (300 s sem sinal, por padrão), encerra e retoma do
último ponto salvo, tentando de novo sem GPU e depois com um modelo menor.
Se ainda assim não concluir, o ponto salvo continua no disco: rodar de novo
aproveita o que já deu certo. Veja com `lauda checkpoints`.

**Quero que ele pare de comer a máquina inteira**
Baixe os sliders na página Desempenho, ou use `--cpu 40 --gpu 0`. Abaixo de 60% de
CPU o app também roda em prioridade menor, então o computador continua usável.

**Ollama: "não respondeu" ou "modelo não está baixado"**
O padrão é **`qwen3:14b`**. Se ele não estiver baixado e o **`qwen3:8b`**
estiver, o resumo sai com o menor e o relatório registra a troca — baixar 9 GB
no meio de um trabalho não é opção, e desistir do resumo também não.

Suba o servidor (`ollama serve`) e baixe o modelo (`ollama pull qwen3:14b`),
ou ajuste `OLLAMA_HOST`/`OLLAMA_MODEL` no `.env`.

**Áudio sem fala / transcrição vazia**
Normal em música, ruído e tons puros: o VAD descarta o que não é voz. O
relatório informa `Fala detectada: não` e lista os avisos na seção 3.

**Texto repetido ou inventado**
Clássico do Whisper em silêncio ou áudio muito baixo. Mantenha o VAD ligado
(padrão), suba o volume da gravação, ou use um modelo maior. `--no-vad` só
para depurar.

**PowerShell: "O token '&&' não é um separador de instruções válido"**
Você está no Windows PowerShell 5.1. Troque `&&` por `;`, ou rode os comandos
em linhas separadas. Isso não tem nada a ver com o app.

**Windows: acentos quebrados no terminal**
O app já força UTF-8 na saída. Se ainda ver `Mem�ria`, rode
`chcp 65001` antes ou use o Windows Terminal.

**Arquivo grande demora muito**
Meça primeiro com `-m tiny`. Depois escolha o modelo pela tabela acima. O
processamento é streaming: um vídeo de 4 GB não é carregado na RAM.

---

## Limites honestos do Whisper

- **Sotaque e fala rápida** derrubam a acurácia, principalmente nos modelos
  pequenos.
- **Música e ruído de fundo** produzem texto inventado. Use o VAD.
- **Falas sobrepostas** viram uma linha só — e sem diarização não dá para saber
  de quem é.
- **Silêncio prolongado** é a maior fonte de alucinação: o modelo "preenche" o
  vazio. Por isso o VAD vem ligado por padrão.
- **Números, siglas e nomes próprios** erram muito. Use `--prompt "Fulano,
  ACME, SUS, CNPJ"` para ancorar o vocabulário.
- Os timestamps por palavra são **estimativas** do decoder, não alinhamento
  forçado. Alinhamento fino chega na Fase 3.

---

## Formatos aceitos

Qualquer coisa que o ffmpeg abra. Testados:

- **Áudio**: wav, mp3, m4a, aac, flac, ogg, opus, wma
- **Vídeo**: mp4, mkv, webm, mov, avi, m4v

Arquivo que o ffmpeg não abre é recusado com mensagem clara e código de saída 2.

---

## Estrutura do projeto

```
src/lauda/
  probe.py        ffprobe -> metadados
  extract.py      ffmpeg  -> WAV 16 kHz mono (temporário, sempre removido)
  audio_stats.py  volume, clipping, silêncio
  hardware.py     CUDA/VRAM/RAM -> device, compute_type, modelo
  transcribe.py   faster-whisper + VAD + fallback para CPU
  align.py        refino dos limites de segmento pelas palavras
  diarize.py      diarização (ECAPA sem token, ou pyannote)
  textstats.py    contagens e palavras frequentes sem stopwords
  subtitles.py    SRT/VTT
  summarize.py    resumo com Ollama local (opcional)
  visual.py       cortes de cena + thumbnails (opcional)
  report.py       renderização do laudo TXT
  serialize.py    .data.json
  pipeline.py     orquestração + progresso por etapa
  limits.py       limites de CPU/RAM/GPU/VRAM
  disk.py         contabilidade de espaço em disco
  checkpoint.py   pontos de retomada
  worker.py       processo filho que executa um trabalho
  runner.py       supervisor: mata se travar e retoma
  cli.py          interface de linha de comando
  desktop.py      aplicativo em janela própria (Tkinter)
  ui.py           interface Gradio local (alternativa)

scripts/
  download_models.py   baixa modelos para uso offline
  make_test_media.py   gera as mídias de exemplo dos testes
  make_icon.py         gera assets/lauda.ico
  _pdf_common.py       estilo compartilhado dos PDFs
  make_manual.py       gera o manual completo
  make_quickstart.py   gera o guia rápido
  make_decisions.py    gera o documento de decisões técnicas
  make_frontend.py     gera o guia do front-end
  create_shortcut.ps1  cria o atalho na Área de Trabalho

Lauda Local.bat   lançador alternativo (duplo clique na pasta)
```

Para regenerar os PDFs depois de mexer nas opções ou na tela:

```bash
.\.venv\Scripts\python.exe scripts\make_manual.py; .\.venv\Scripts\python.exe scripts\make_quickstart.py; .\.venv\Scripts\python.exe scripts\make_decisions.py; .\.venv\Scripts\python.exe scripts\make_frontend.py
```

(precisa de `pip install "lauda[docs]"` uma vez)

## Empacotar para distribuir

Para gerar o instalador que vai para outra pessoa — executável sem Python,
ffmpeg embutido e atalhos:

```bash
py -3.12 -m venv .venv-build; .\.venv-build\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu; .\.venv-build\Scripts\python.exe -m pip install ".[desktop,diarize]" pyinstaller -e .
```

```bash
.\.venv-build\Scripts\python.exe scripts\build_release.py
```

Sai em `dist/`: a pasta portátil **Lauda Local** (~600 MB) e o instalador
**Lauda Local-<versão>-setup.exe**.

O ambiente de build é separado de propósito. Ele **não** tem as bibliotecas
CUDA (1,7 GB) nem o Gradio: o aplicativo de janela não usa nenhum dos dois, e
eles triplicariam o download. Quem tiver placa NVIDIA instala o extra `gpu`
depois. O `build_release.py` recusa rodar se encontrar esses pacotes.

O **ffmpeg vai junto**, numa compilação **LGPL** (`build-tools/`, baixada de
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds)). Foi essa a
escolha porque as compilações comuns são GPL: distribuí-las obrigaria o projeto
inteiro a virar GPL. A LGPL permite embutir ao lado de um aplicativo MIT, com o
aviso que está em `packaging/LICENCAS.txt`. Rodando a partir do código nada
muda — o ffmpeg do sistema continua valendo.

O instalador precisa do [Inno Setup](https://jrsoftware.org/isinfo.php)
(`winget install --id JRSoftware.InnoSetup`). Sem ele o script gera só a pasta
portátil.

## Testes

```bash
pytest -q
```

São **151 testes**. `ruff` e `mypy` passam sem apontamentos:

```bash
ruff check src tests scripts; mypy src/lauda
```

Os testes de mídia exigem ffmpeg (senão são pulados) e usam arquivos gerados
por `python scripts/make_test_media.py`. Para exercitar transcrição e
diarização de verdade (baixa os modelos na primeira vez):

```bash
LAUDA_TEST_ASR=1 LAUDA_TEST_DIARIZE=1 pytest -q
```

O bloco do Ollama é testado contra um servidor HTTP simulado — nenhum teste
depende de rede externa.

---

## Roadmap

- [x] **Fase 1** — ffprobe + extração + faster-whisper + TXT + JSON
- [x] **Fase 2** — VAD, idioma, SRT/VTT, progresso real, escolha de modelo
- [x] **Fase 3** — refino de limites por palavra + diarização (ECAPA e pyannote)
- [x] **Fase 4** — UI local com Gradio (drag-and-drop, toggles, histórico)
- [x] **Fase 5** — camada visual, resumo com Ollama, Dockerfile

Ideias para depois: alinhamento forçado com wav2vec2, descrição visual com VLM
local, processamento em lote de uma pasta inteira.

## Contribuindo

Contribuição não precisa ser código: relatar um arquivo que transcreveu mal, ou
dizer que uma tela ficou confusa, vale tanto quanto um *pull request*.

- [CONTRIBUTING.md](CONTRIBUTING.md) — como preparar o ambiente, o que rodar
  antes de abrir um PR e **as nove regras que não se quebram**.
- [ARCHITECTURE.md](ARCHITECTURE.md) — o mapa do código, para quem chega agora.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — como se conversa por aqui.
- [SECURITY.md](SECURITY.md) — relatar falha de segurança (nunca em issue
  pública).
- [CHANGELOG.md](CHANGELOG.md) — o que mudou em cada versão.

Três coisas que o projeto **não** vai fazer, para poupar seu tempo: mandar seu
arquivo para a nuvem, virar aplicação web, ou coletar telemetria. O porquê de
cada uma está em `docs/Lauda-Local-Decisoes-Tecnicas.pdf`.

## Licenças

O código deste projeto é **MIT** — veja [LICENSE](LICENSE).

As dependências e a compilação do ffmpeg que vai embutida no instalador (LGPL,
do BtbN) estão listadas em [LICENSES.md](LICENSES.md).
