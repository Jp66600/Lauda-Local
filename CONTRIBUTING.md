# Como contribuir com o Lauda Local

Obrigado por aparecer. Este é um projeto pequeno e opinativo: um aplicativo que
transforma áudio e vídeo em laudo de texto **sem que um byte saia da máquina**.
Quase todas as regras abaixo existem por causa dessa frase.

Contribuição não precisa ser código. Relatar um arquivo que transcreveu mal,
mandar o log de um erro ou dizer que uma tela ficou confusa vale tanto quanto um
*pull request*.

---

## Preparar o ambiente

Precisa de **Python 3.12** (3.11 a 3.13 funcionam; 3.14 não — ainda não há
*wheels* do CTranslate2) e do **ffmpeg** no PATH.

```bash
git clone https://github.com/Jp66600/lauda-local.git
cd lauda-local
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1        # no Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev,desktop,docs]"
```

A mídia de teste não vem no repositório (são megabytes de áudio gerado). Crie-a
uma vez:

```bash
python scripts/make_test_media.py
```

Rodar o aplicativo e a suíte:

```bash
python -m lauda.desktop          # a janela
python -m lauda run entrada.mp4 -o saida
python -m pytest tests -q
```

---

## Antes de abrir um pull request

```bash
ruff check src tests scripts
mypy src
python -m pytest tests -q
```

Os três precisam passar. É o mesmo que a integração contínua roda.

**`ruff format` não é usado**, de propósito: ele reformata as tabelas de dados do
laudo e dos manuais para uma linha por item e as torna ilegíveis. A formatação é
mantida à mão.

Se você mexeu na interface ou nas opções, regenere os manuais — três deles
descrevem a tela passo a passo e ficam errados sozinhos:

```bash
python scripts/make_quickstart.py
python scripts/make_manual.py
python scripts/make_decisions.py
python scripts/make_frontend.py
```

---

## As regras que não se quebram

Vieram do pedido original ou de defeitos já pagos. Quebrar qualquer uma é
regressão, não escolha de estilo. A versão longa está em
[ARCHITECTURE.md](ARCHITECTURE.md).

1. **Nada sai da máquina.** Sem API paga, sem upload, sem telemetria. O Ollama
   é opcional, escuta em `127.0.0.1` e o esquema da URL é validado.
2. **O arquivo de mídia nunca é executado** — só lido pelo ffmpeg, sempre por
   lista de argumentos, nunca por shell.
3. **Bloco que falha vira `[INDISPONÍVEL] <bloco>: <motivo>`** no laudo. Nunca
   some em silêncio.
4. **O laudo tem nove seções, nessa ordem.** Conteúdo novo entra dentro de uma
   delas.
5. **Interface, logs, README e TXT em português do Brasil; código em inglês.**
   Nomes de variável, função e classe em inglês; texto que o usuário lê, em
   português.
6. **Nenhuma cor fora de `theme.py`.** É o que faz o modo escuro funcionar
   inteiro.
7. **Nenhum widget retangular do ttk na tela** — `Checkbutton`, `Scrollbar`,
   `Notebook`, `Scale` e `Progressbar` não arredondam. Um teste varre a árvore
   da janela e falha se algum voltar; use os equivalentes de `widgets.py`.
8. **Só a thread da interface toca em widget.** O que vem do trabalho chega pela
   fila e é desenhado em `_drain_queue`.
9. **Um processamento por vez.** A fila é serial de propósito: dois modelos
   carregados disputam a mesma memória e travam a máquina.

---

## Estilo de código e de commit

- Comentário explica **por que**, não o que a linha faz. Se o comentário só
  reescreve o código, ele some.
- Teste novo acompanha comportamento novo — e o nome do teste diz o que se
  espera, em português (`test_gpu_em_zero_manda_para_a_cpu`).
- Mensagem de commit no imperativo e em português: `corrige a cobertura quando
  o VAD descarta o fim do arquivo`.
- Pull request pequeno passa; pull request que mistura refatoração com recurso
  novo trava.

---

## Onde começar

- **`ARCHITECTURE.md`** — o mapa: onde fica cada coisa e como um trabalho corre
  do começo ao fim. Leia antes de propor mudança grande.
- **`docs/Lauda-Local-Front-End.pdf`** — a interface por dentro (é Tkinter, não
  existe HTML/CSS/React em lugar nenhum).
- **`docs/Lauda-Local-Decisoes-Tecnicas.pdf`** — o porquê de cada escolha, incluindo
  as que foram recusadas e por quê.

Issues marcadas com `bom primeiro item` são as de escopo pequeno e contido.

---

## Relatar um problema de transcrição

O que mais ajuda, nesta ordem:

1. O **laudo** (`*.report.txt`) — ele traz modelo, device, cobertura e avisos.
2. Os **logs**, em `~/.lauda/logs/` (`lauda.log` e `lauda-worker.log`).
3. O **diagnóstico da máquina** (página Desempenho → aba Diagnóstico).
4. O arquivo de mídia, **se você puder compartilhá-lo**. Se não puder, diga
   apenas a duração, o idioma e se tem música ou ruído de fundo — já ajuda.

Não mande nada que você não queira público: uma issue é aberta ao mundo.
