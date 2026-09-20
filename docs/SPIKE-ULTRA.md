# Spike: "o Ultra só lê os primeiros e os últimos 10 s"

**Item:** BACKLOG-006 · **Veredito:** `cannot-repro` neste repositório
**Data:** 2026-09-07

---

## O relato

Do QA: em qualidade **Ultra**, a transcrição sai com texto no começo e no fim do
vídeo e nada no meio. Hipótese registrada no backlog: algum ramo de qualidade
altera `seek`, duração ou amostragem do áudio.

## O que o código diz

**A qualidade só troca o nome do modelo.** Em `desktop.py`, `MODEL_LABELS` mapeia
cada rótulo para um identificador do Whisper — `tiny`, `base`, `small`,
`medium`, `large-v3-turbo`, `distil-large-v3`, `large-v3`. Nenhum ramo desses
valores toca em extração ou em janela de áudio.

**A extração não corta nada.** `extract.py` não usa `-ss`, `-t` nem `-to`: o
arquivo inteiro vira um WAV de 16 kHz mono, e a duração desse WAV é conferida
depois (`wav_duration_seconds`).

**Não há divisão em pedaços.** O faster-whisper percorre o arquivo em fluxo,
emitindo segmento a segmento. Não existe código que escolha "as pontas".

Conclusão: **a hipótese de `seek` por qualidade não sobrevive à leitura do
código deste repositório.**

## A hipótese que sobra

Se o comportamento existe em algum build, o candidato mais provável é o **VAD**
(Silero, ligado por padrão): ele descarta trechos que julga sem voz. Em áudio
com música, ruído de fundo constante ou fala baixa, isso pode remover minutos
inteiros — e o sintoma seria exatamente o descrito. Não é ramo de qualidade; é
sensibilidade do detector de voz, e independe do modelo escolhido.

Para confirmar seria preciso o arquivo do QA e uma rodada com `--no-vad`.

## O que foi feito em vez de esperar

Reproduzir dependia de material que não temos. Em vez de deixar o item parado,
entrou o **guardrail** que o backlog pedia no BACKLOG-007 — e que teria pegado o
problema sozinho:

`coverage.py` mede, em **todo** trabalho, quanto da duração virou texto e lista
os intervalos que ficaram de fora e **não são silêncio**. Silêncio medido é
sucesso; o resto é buraco, com início e fim, no laudo (seção 5, BLOCO A2), no
`.json`, na janela e no log. Abaixo de 95% o aplicativo avisa.

Ou seja: **se o sintoma existir em qualquer máquina, o próprio relatório passa a
denunciá-lo** — sem depender de alguém desconfiar e comparar o texto com o
vídeo.

## O que ainda falta para fechar de verdade

1. O arquivo que o QA usou, e a versão do aplicativo.
2. Uma rodada com `--no-vad` no mesmo arquivo. Se a cobertura saltar, a causa é
   o VAD e o caminho é ajustar o limiar ou expor a opção na janela.
3. Se a cobertura continuar baixa **com** `--no-vad`, aí sim há um defeito de
   percurso, e este documento estava errado.
