"""Páginas com uma aba por arquivo da pasta de saída.

Transcrição, Relatório e Legendas são a mesma página com outro sufixo: uma
faixa de abas com o nome do arquivo de origem, o conteúdo do arquivo escolhido
e três botões embaixo. Fazer três cópias disso era garantir que uma correção
fosse aplicada em duas.

A fonte é sempre **a pasta de saída**, nunca o histórico: a pasta é o que a
pessoa enxerga no Explorador, e é com ela que as abas têm de bater. O histórico
entra só para enfeitar — dele vêm o nome do arquivo de origem, a duração e o
modelo, quando aquele trabalho passou por aqui.
"""

from __future__ import annotations

import logging
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from . import APP_NAME, history, serialize
from .cues import DENSITY_LABELS
from .subtitles import write_srt, write_vtt
from .widgets import RoundedButton, RoundedCard, RoundedScrollbar, TabButton, mix

log = logging.getLogger("lauda.pages")

#: Abas por linha, altura de cada linha e quantas linhas ficam visíveis antes
#: de a área começar a rolar. Nenhum arquivo é escondido: a pasta pode ter
#: dezenas, e todos viram aba.
COLUMNS = 3
ROW_HEIGHT = 40
MAX_ROWS = 3

#: Quanto do nome cabe numa aba antes de ser cortado pelo meio.
LABEL_WIDTH = 26


@dataclass(frozen=True)
class PageSpec:
    """O que muda de uma página para outra."""

    key: str
    title: str
    icon: str
    #: Sufixos que a página procura, na ordem em que devem aparecer.
    suffixes: tuple[str, ...]
    empty: str
    #: Rótulo do terceiro botão e o que ele abre: o laudo do trabalho, ou o
    #: próprio arquivo mostrado (na página que já É o laudo).
    third_button: str = "Abrir o laudo deste arquivo"
    third_opens: str = "report"          # "report" | "self"
    #: Acrescentar o formato ao rótulo da aba **quando ele for necessário para
    #: distinguir** — o mesmo trabalho com .srt e .vtt daria duas abas de nome
    #: igual. Quando só há um formato, o sufixo é repetição que rouba sete
    #: caracteres do nome do arquivo, que é o que a pessoa procura.
    label_suffix: bool = False
    #: Oferecer o botão que refaz o arquivo a partir do `.data.json`. Só a
    #: página de legendas: o laudo e o texto corrido sempre saem, mas a legenda
    #: pode faltar em trabalhos feitos quando ela ainda era opcional.
    backfill: bool = False


@dataclass
class FileEntry:
    """Um arquivo da pasta, já casado com o histórico quando dá."""

    path: Path
    suffix: str
    label: str
    report_path: str = ""
    details: list[str] = field(default_factory=list)


class FileTabsPage:
    """Monta e mantém uma dessas páginas. O `app` é a janela dona dela."""

    def __init__(self, app: Any, spec: PageSpec) -> None:
        self.app = app
        self.spec = spec
        self.buttons: dict[str, TabButton] = {}
        self.current: str | None = None
        self.card: RoundedCard | None = None

    # ------------------------------------------------------------- montagem --
    def build(self) -> None:
        app, spec = self.app, self.spec
        card = RoundedCard(app.content, padding=12, radius=16)
        app._cards.append(card)
        self.card = card

        moldura = tk.Frame(card.body, background=app.theme.paper)
        moldura.pack(fill="x", pady=(0, 8))
        moldura.columnconfigure(0, weight=1)
        app._panels.append(moldura)

        self.canvas = tk.Canvas(
            moldura, height=ROW_HEIGHT, highlightthickness=0, borderwidth=0,
            background=app.theme.paper,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.strip = tk.Frame(self.canvas, background=app.theme.paper)
        self.canvas.create_window((0, 0), window=self.strip, anchor="nw", tags="abas")
        self.strip.bind("<Configure>", self._on_resized)
        app._panels.append(self.strip)

        self.scroll = RoundedScrollbar(
            moldura, orient="vertical", command=self.canvas.yview,
            background=app.theme.paper,
        )
        self.scroll.grid(row=0, column=1, sticky="ns")
        app._scrollbars.append(self.scroll)
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.button_refresh = RoundedButton(
            moldura, text="Atualizar", command=self.refresh,
            font=app.font_small, radius=11,
        )
        self.button_refresh.grid(row=0, column=2, sticky="n", padx=(8, 0))
        app._buttons.append(self.button_refresh)

        self.button_backfill: RoundedButton | None = None
        if spec.backfill:
            self.button_backfill = RoundedButton(
                moldura, text="Gerar as que faltam", command=self.backfill,
                font=app.font_small, radius=11,
            )
            self.button_backfill.grid(row=0, column=3, sticky="n", padx=(6, 0))
            app._buttons.append(self.button_backfill)

        self.label = ttk.Label(
            card.body, text="", style="Hint.TLabel", justify="left", wraplength=760
        )
        self.label.pack(fill="x", pady=(0, 8))

        _, self.text = app._text_area(card.body)

        fileira = tk.Frame(card.body, background=app.theme.paper)
        fileira.pack(fill="x", pady=(10, 2))
        app._panels.append(fileira)

        self.button_folder = RoundedButton(
            fileira, text="Abrir o local do arquivo", command=self.open_folder,
            font=app.font_body, icon="folder",
        )
        self.button_folder.pack(side="left")
        self.button_copy = RoundedButton(
            fileira, text="Copiar o texto", command=self.copy, font=app.font_body,
        )
        self.button_copy.pack(side="left", padx=(10, 0))
        self.button_third = RoundedButton(
            fileira, text=spec.third_button, command=self.open_third,
            font=app.font_body, icon="doc",
        )
        self.button_third.pack(side="left", padx=(10, 0))
        app._buttons += [self.button_folder, self.button_copy, self.button_third]

        app.nav.add(card, spec.title, spec.icon)

    # ---------------------------------------------------------------- dados --
    def entries(self) -> list[FileEntry]:
        """Os arquivos desta página na pasta de saída, do mais novo ao mais velho."""
        pasta = Path(self.app.folder_var.get().strip() or ".")
        achados: list[tuple[float, Path, str]] = []
        try:
            for sufixo in self.spec.suffixes:
                for arquivo in pasta.glob(f"*{sufixo}"):
                    achados.append((arquivo.stat().st_mtime, arquivo, sufixo))
        except OSError:  # pragma: no cover - pasta some entre o glob e o stat
            return []
        achados.sort(key=lambda item: item[0], reverse=True)

        # Duas abas do mesmo trabalho (o .srt e o .vtt) precisam do formato no
        # rótulo; uma sozinha, não.
        formatos: dict[str, int] = {}
        for _quando, arquivo, sufixo in achados:
            base = str(arquivo)[: -len(sufixo)]
            formatos[base] = formatos.get(base, 0) + 1

        por_base = self._history_index()
        entradas: list[FileEntry] = []
        for _quando, arquivo, sufixo in achados:
            base = str(arquivo)[: -len(sufixo)]
            conhecido = por_base.get(base)
            nome = (conhecido.file_name if conhecido else "") or Path(base).name
            rotulo = history._cut(nome, LABEL_WIDTH)
            if self.spec.label_suffix and formatos[base] > 1:
                rotulo = history._cut(nome, LABEL_WIDTH - len(sufixo) - 3) + f" ({sufixo})"

            detalhes = [nome]
            if conhecido is not None:
                if conhecido.duration:
                    detalhes.append(_clock(conhecido.duration))
                if conhecido.model:
                    detalhes.append(conhecido.model)
            laudo = base + ".report.txt"
            entradas.append(FileEntry(
                path=arquivo,
                suffix=sufixo,
                label=rotulo,
                report_path=laudo if Path(laudo).exists() else "",
                details=detalhes,
            ))
        return entradas

    def _history_index(self) -> dict[str, history.HistoryEntry]:
        """Casa arquivo com trabalho pela **base** do caminho de saída."""
        indice: dict[str, history.HistoryEntry] = {}
        for entrada in history.load():
            for caminho, sufixo in (
                (entrada.transcript_path, ".transcript.txt"),
                (entrada.report_path, ".report.txt"),
            ):
                if caminho and caminho.endswith(sufixo):
                    indice[caminho[: -len(sufixo)]] = entrada
        return indice

    # ------------------------------------------------------------- desenho --
    def rebuild(self, select: str | None = None) -> None:
        """Redesenha as abas. `select` é o caminho a mostrar."""
        for filho in self.strip.winfo_children():
            filho.destroy()
        self.buttons.clear()

        entradas = self.entries()
        if not entradas:
            self.current = None
            self.app._set_text(self.text, self.spec.empty)
            self.label.configure(text="")
            self._set_buttons("disabled")
            return

        atual = select or self.current
        if atual not in {str(e.path) for e in entradas}:
            atual = str(entradas[0].path)

        for indice, entrada in enumerate(entradas):
            botao = TabButton(
                self.strip, text=entrada.label, font=self.app.font_body,
                command=self._command(str(entrada.path)),
                parent_bg=self.app.theme.paper,
            )
            botao.grid(
                row=indice // COLUMNS, column=indice % COLUMNS,
                sticky="w", padx=(0, 6), pady=(0, 4),
            )
            botao.apply_theme(
                fill_on=mix(self.app.theme.paper, self.app.theme.accent, 0.16),
                fill_off=self.app.theme.paper,
                fg_on=self.app.theme.accent,
                fg_off=self.app.theme.ink_soft,
                parent_bg=self.app.theme.paper,
            )
            botao.set_selected(str(entrada.path) == atual)
            self.buttons[str(entrada.path)] = botao

        self.show(atual)

    def _command(self, caminho: str) -> Any:
        return lambda: self.show(caminho)

    def _on_resized(self, _event: tk.Event) -> None:
        """A área cresce até `MAX_ROWS` linhas; daí em diante ela rola."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        pedido = self.strip.winfo_reqheight()
        altura = max(ROW_HEIGHT, min(pedido, ROW_HEIGHT * MAX_ROWS))
        self.canvas.configure(height=altura)
        # Cabe tudo? A barra sai da frente em vez de ficar de enfeite.
        if pedido <= altura:
            self.scroll.grid_remove()
        else:
            self.scroll.grid()

    def show(self, caminho: str) -> None:
        """Carrega na tela o conteúdo de um dos arquivos."""
        entrada = next((e for e in self.entries() if str(e.path) == caminho), None)
        if entrada is None:
            self.rebuild()
            return

        self.current = caminho
        for alvo, botao in self.buttons.items():
            botao.set_selected(alvo == caminho)

        try:
            conteudo = entrada.path.read_text(encoding="utf-8")
        except OSError as exc:
            conteudo = f"Não consegui ler o arquivo:\n{caminho}\n\n{exc}"
        self.app._set_text(self.text, conteudo or "(arquivo vazio)")
        self.label.configure(text="  •  ".join(entrada.details) + f"\n{caminho}")
        self._set_buttons("normal")

    def _set_buttons(self, state: str) -> None:
        for botao in (self.button_folder, self.button_copy, self.button_third):
            botao.configure(state=state)

    # ---------------------------------------------------------------- ações --
    def refresh(self, select: str | None = None) -> None:
        """Relê a pasta: entra o que apareceu, sai o que foi apagado."""
        antes = set(self.buttons)
        self.rebuild(select)
        depois = set(self.buttons)

        novos, sumiram = len(depois - antes), len(antes - depois)
        if novos or sumiram:
            partes = []
            if novos:
                partes.append(f"{novos} arquivo(s) novo(s)")
            if sumiram:
                partes.append(f"{sumiram} sumiu(ram) da pasta")
            self._say(f"{self.spec.title}: " + " e ".join(partes) + ".")

    def backfill(self) -> None:
        """Escreve as legendas dos trabalhos que já estão feitos.

        A legenda é o `[BLOCO B]` do laudo noutro formato: os mesmos trechos,
        os mesmos tempos, o mesmo falante — só que num arquivo que o player
        entende. Esses trechos ficam guardados no `.data.json` de cada
        trabalho, então não há nada para transcrever de novo: é ler o que já
        está em disco e escrever o arquivo que faltou.

        Vale para quem processou antes de a legenda sair por padrão, e para
        quem quiser trocar o tamanho das legendas sem refazer o trabalho — para
        isso, apague a legenda antiga primeiro; o que existe não é sobrescrito.
        """
        pasta = Path(self.app.folder_var.get().strip() or ".")
        formatos = [(".srt", write_srt)]
        if bool(self.app.var_vtt.get()):
            formatos.append((".vtt", write_vtt))
        densidade = self.app._selected(self.app.density_var, DENSITY_LABELS)

        feitos = 0
        sem_trechos: list[str] = []
        falharam: list[str] = []
        ultimo: str | None = None

        try:
            dados = sorted(pasta.glob("*.data.json"))
        except OSError as exc:
            self._say(f"Não consegui ler a pasta {pasta}: {exc}", aviso=True)
            return

        for arquivo in dados:
            base = str(arquivo)[: -len(".data.json")]
            faltando = [par for par in formatos if not Path(base + par[0]).exists()]
            if not faltando:
                continue
            try:
                resultado = serialize.read_json(arquivo)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                log.warning("Não consegui ler %s: %s", arquivo.name, exc)
                falharam.append(f"{arquivo.name}: {exc}")
                continue
            if not resultado.segments:
                # Trabalho que falhou antes de transcrever: tem .data.json, não
                # tem fala. Não é erro, e dizer isso é melhor que nada mudar.
                sem_trechos.append(Path(base).name)
                continue
            for sufixo, escrever in faltando:
                try:
                    ultimo = str(escrever(
                        Path(base + sufixo), resultado.segments, density=densidade
                    ))
                except OSError as exc:
                    log.warning("Não consegui escrever %s%s: %s", base, sufixo, exc)
                    falharam.append(f"{Path(base).name}{sufixo}: {exc}")
                    continue
                feitos += 1
                log.info("Legenda gerada de %s", arquivo.name)

        partes: list[str] = []
        if feitos:
            partes.append(f"{feitos} legenda(s) criada(s) do que já estava processado")
        if sem_trechos:
            partes.append(f"{len(sem_trechos)} trabalho(s) sem fala guardada")
        if falharam:
            partes.append(f"{len(falharam)} não deu(deram) certo — veja o Registro")
        if not partes:
            partes.append("nada a fazer: todas as legendas já estão na pasta")
        self._say(f"{self.spec.title}: " + "; ".join(partes) + ".", aviso=bool(falharam))

        self.rebuild(ultimo)

    def _say(self, texto: str, *, aviso: bool = False) -> None:
        self.app.status_label.configure(
            text=texto,
            foreground=self.app.theme.accent_warm if aviso else self.app.theme.ink_soft,
        )

    def open_folder(self) -> None:
        if self.current:
            self.app._reveal_in_folder(Path(self.current))

    def copy(self) -> None:
        conteudo = self.text.get("1.0", "end-1c")
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(conteudo)
        self.app.status_label.configure(
            text=f"{self.spec.title} copiada para a área de transferência."
        )

    def open_third(self) -> None:
        """Abre o laudo do trabalho — ou o próprio arquivo, conforme a página."""
        if not self.current:
            return
        if self.spec.third_opens == "self":
            self.app._reveal(Path(self.current))
            return
        entrada = next((e for e in self.entries() if str(e.path) == self.current), None)
        if entrada is not None and entrada.report_path:
            self.app._reveal(Path(entrada.report_path))
        else:
            messagebox.showinfo(
                APP_NAME, "O laudo deste trabalho não está na pasta de saída."
            )


def _clock(seconds: float) -> str:
    total = round(seconds)
    horas, resto = divmod(total, 3600)
    minutos, segundos = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segundos:02d}"
    return f"{minutos}:{segundos:02d}"
