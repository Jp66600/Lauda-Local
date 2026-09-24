"""Aplicativo de janela própria (Tkinter) — sem navegador, sem servidor.

Diferente do `lauda ui` (que abre uma página no navegador), aqui a
interface é uma janela nativa do Windows/macOS/Linux:

* seleção de arquivo e de pasta pelo **explorador de arquivos do sistema**;
* pré-visualização do relatório dentro do próprio aplicativo;
* barra de progresso real, etapa por etapa.

Tkinter vem junto com o Python, então isto não acrescenta nenhuma dependência.

Regra de ouro do Tkinter: só a thread principal pode tocar em widget. O
processamento roda numa thread separada e conversa com a interface por uma
fila, drenada por `after()`.
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from tkinter import Tk, filedialog, messagebox, ttk
from tkinter import font as tkfont
from typing import Any

from . import APP_NAME, APP_VERSION, history
from .config import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, JobOptions
from .cues import DENSITY_LABELS
from .errors import LaudaError
from .ffmpeg_tools import resolve_tools, run
from .hardware import (
    MachineCheck,
    assess_machine,
    detect_hardware,
    recommended_for,
    select_runtime,
)
from .limits import DEFAULT as LIMITS_DEFAULT
from .limits import MAX_PERCENT, MIN_PERCENT, PRESETS, ResourceLimits, preset_by_key, preset_for
from .limits import load as load_limits
from .limits import save as save_limits
from .logging_setup import LOG_DIR, LOG_PATH, log_uncaught, setup_logging
from .pages import FileTabsPage, PageSpec
from .profile import icon_path, migrate_legacy_profile, models_dir
from .summarize import list_models, pick_model, pull_model
from .theme import (
    PREFS_PATH,
    THEME_CHOICES,
    Theme,
    apply_titlebar,
    load_choice,
    load_flag,
    load_value,
    resolve,
    save_choice,
    save_flag,
    save_value,
)
from .types import JobResult
from .utils import human_size
from .widgets import (
    DropZone,
    RoundedButton,
    RoundedCard,
    RoundedField,
    RoundedProgress,
    RoundedScrollbar,
    RoundedSlider,
    RoundedTabs,
    SideNav,
    Stepper,
    ToggleSwitch,
    draw_icon,
    mix,
)

try:  # pragma: no cover - depende do ambiente
    from PIL import Image, ImageTk

    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False

try:  # pragma: no cover - extra opcional `ui`
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _HAS_DND = True
except Exception:  # pragma: no cover
    _HAS_DND = False

log = logging.getLogger("lauda.desktop")


def _num(value: float, decimals: int = 1) -> str:
    """Número no padrão brasileiro: vírgula decimal."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _duration_pt(seconds: float | None) -> str:
    """Duração em linguagem de gente: "2 min", "1 h 20 min", "40 s"."""
    if seconds is None:
        return "—"
    total = round(seconds)
    if total < 60:
        return f"{max(total, 1)} s"
    if total < 3600:
        return f"{total // 60} min"
    horas, resto = divmod(total, 3600)
    minutos = resto // 60
    return f"{horas} h" if minutos == 0 else f"{horas} h {minutos} min"


def _clock(seconds: float) -> str:
    """Duração em hh:mm:ss, como aparece no cartão do arquivo."""
    total = round(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LANGUAGES: list[tuple[str, str]] = [
    ("Detectar automaticamente", "auto"),
    ("Português", "pt"),
    ("Inglês", "en"),
    ("Espanhol", "es"),
    ("Francês", "fr"),
    ("Alemão", "de"),
    ("Italiano", "it"),
    ("Japonês", "ja"),
]

MODEL_LABELS: list[tuple[str, str]] = [
    ("Rascunho — bem rápido (tiny)", "tiny"),
    ("Básico (base)", "base"),
    ("Recomendado — equilibrado (small)", "small"),
    ("Melhor qualidade (medium)", "medium"),
    ("Alta qualidade, ainda rápido (large-v3-turbo)", "large-v3-turbo"),
    ("Alta qualidade alternativa (distil-large-v3)", "distil-large-v3"),
    ("Máxima qualidade — lento (large-v3)", "large-v3"),
]

#: Tamanho do lote quando o "modo rápido" está ligado. 16 foi o melhor ponto
#: medido em GPU de 4 GB; acima disso o ganho some e a VRAM aperta.
#: So para a copy do interruptor. O valor de verdade vem de JobOptions;
#: aqui e apenas o que a tela mostra quando ninguem mexeu em nada.
DEFAULT_OLLAMA_MODEL = JobOptions(
    input_path=Path("-"), output_dir=Path("-")
).ollama_model


BATCH_SIZE = 16

STAGE_LABELS = {
    "probe": "Lendo o arquivo",
    "extract": "Separando o áudio",
    "vad": "Analisando o áudio",
    "asr": "Transcrevendo",
    "align": "Ajustando os tempos",
    "diarize": "Identificando quem fala",
    "render": "Escrevendo os arquivos",
}

#: Chave do `ui.json` onde ficam as escolhas da tela de trabalho.
#: O tema e os limites de máquina têm guarda própria; aqui ficam idioma,
#: qualidade, os interruptores de recurso e a pasta de saída.
JOB_PREFS_KEY = "job"

#: Sobe quando um padrão muda e a preferência **já gravada** precisa ceder.
#: Serve para uma coisa só, e raramente: sem ela, um padrão novo nunca chega a
#: quem já usava o programa. A 2 ligou a legenda .srt.
PREFS_VERSION = 2

#: Quanto esperar antes de gravar. Digitar um caminho dispara um evento por
#: tecla — sem isto, seriam dezenas de escritas em disco para uma escolha só.
PREFS_SAVE_DELAY_MS = 500

#: As cinco etapas mostradas na trilha do rodapé, e em qual delas cada estágio
#: real do processamento cai.
PIPELINE_STEPS = [
    "Arquivo",
    "Pré-processamento",
    "Transcrição",
    "Pós-processamento",
    "Conclusão",
]
STAGE_STEP = {
    "probe": 1, "extract": 1, "vad": 1,
    "asr": 2,
    "align": 3, "diarize": 3,
    "render": 4,
}

STEPS_TEXT = """COMO USAR — 4 PASSOS

  1.  ESCOLHER O ARQUIVO
      Em "Novo trabalho", arraste o áudio ou vídeo para a área tracejada —
      ou clique nela para abrir o explorador de arquivos.
      Serve qualquer formato comum: mp4, mkv, mov, avi, mp3, wav, m4a...

  2.  CONFERIR A PASTA DE SAÍDA
      No painel da direita, embaixo, está a pasta onde o .txt vai ficar.
      Já vem preenchida com a pasta "saida"; pode deixar assim.

  3.  (OPCIONAL) LIGAR OS RECURSOS
      Se souber o idioma do áudio, selecione-o: melhora o resultado.
      Ligue "Diarização de falantes" em entrevistas e reuniões.
      O resto pode ficar como está.

  4.  CLICAR EM "PROCESSAR"
      Acompanhe a trilha de etapas no rodapé. Ao terminar, o relatório
      aparece na página "Relatório" e os arquivos ficam salvos na pasta.

      Suas escolhas ficam guardadas: na próxima vez a tela abre do jeito
      que você deixou. Para zerar, use "Restaurar padrões" em Configurações.


O QUE VOCÊ RECEBE

  relatorio (.report.txt)     o laudo completo: dados do arquivo,
                             qualidade do áudio, idioma e a transcrição
                             com marcação de tempo
  transcricao (.transcript)   só o texto corrido, para copiar e colar
  dados (.data.json)          os mesmos dados em formato de programa
  legenda (.srt)              a mesma fala do laudo com tempo de entrada
                             e de saída, pronta para o player
  legenda (.vtt)              o mesmo, no formato de vídeo na web, se você
                             ligar a opção


BOM SABER

  -  A primeira vez demora mais: o modelo está sendo baixado.
     Da segunda em diante, tudo funciona sem internet.

  -  Nada do seu arquivo sai do computador. Nunca.

  -  Se algo não puder ser feito, o relatório escreve o motivo em vez
     de simplesmente omitir. Procure por [INDISPONÍVEL].
"""


#: Quantas linhas do registro ficam guardadas para a tela. O arquivo em disco
#: guarda tudo; aqui é só o que a pessoa consegue rolar sem a janela engasgar.
LOG_VIEW_LINES = 2000

#: As tres paginas que leem a pasta de saida. O que muda entre elas e o
#: sufixo do arquivo — o resto do comportamento vive em `pages.py`.
PAGE_REPORT = PageSpec(
    key="report",
    title="Relatório",
    icon="doc",
    suffixes=(".report.txt",),
    empty="O laudo aparece aqui depois de processar.\n\n"
          "Cada arquivo processado vira uma aba acima, com o nome dele.",
    third_button="Abrir este laudo",
    third_opens="self",
)
PAGE_TRANSCRIPT = PageSpec(
    key="transcript",
    title="Transcrição",
    icon="transcript",
    suffixes=(".transcript.txt",),
    empty="O texto corrido aparece aqui depois de processar.\n\n"
          "Cada arquivo transcrito vira uma aba acima, com o nome dele.",
)
PAGE_SUBTITLES = PageSpec(
    key="subtitles",
    title="Legendas",
    icon="film",
    suffixes=(".srt", ".vtt"),
    empty="Nenhuma legenda nesta pasta ainda.\n\n"
          "A legenda sai junto com o laudo em todo trabalho novo. Para os que "
          "já foram feitos, o botão \"Gerar as que faltam\" cria a legenda a "
          "partir do .data.json do trabalho — os mesmos trechos que o laudo "
          "imprime no [BLOCO B], sem transcrever nada de novo.",
    label_suffix=True,
    backfill=True,
)


class QueueLogHandler(logging.Handler):
    """Leva as linhas de log para a fila da interface.

    `emit` pode ser chamado de qualquer thread — inclusive das que fazem o
    trabalho pesado. A fila é o único caminho seguro até um widget do Tk.
    """

    def __init__(self, fila: queue.Queue) -> None:
        super().__init__(level=logging.INFO)
        self._fila = fila
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._fila.put(("log", self.format(record)))
        except Exception:  # pragma: no cover - fila fechada durante o encerramento
            self.handleError(record)


@dataclass
class Progress:
    stage: str
    fraction: float
    message: str


# --------------------------------------------------------------------------- #
# Aplicativo
# --------------------------------------------------------------------------- #
class LaudaApp:
    def __init__(self, root: Tk, theme_choice: str | None = None) -> None:
        self.root = root
        self.queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.result: JobResult | None = None

        self.input_path: Path | None = None
        self.output_dir = PROJECT_ROOT / "saida"
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()
        self._paused_at: float | None = None
        self._paused_seconds = 0.0
        self._snapping = False
        self.recovery_messages: list[str] = []

        self._after_id: str | None = None

        # Os widgets arredondados sao desenhados em Canvas: o tema precisa
        # alcancar cada um deles na hora de repintar.
        self._cards: list[RoundedCard] = []
        self._buttons: list[RoundedButton] = []
        self._primary_buttons: set[RoundedButton] = set()
        self._panels: list[tk.Frame] = []        # fundo "paper"
        self._shells: list[tk.Frame] = []        # fundo "canvas"
        self._sidebar_panels: list[tk.Frame] = []
        self._dividers: list[tk.Frame] = []
        self._fields: list[RoundedField] = []
        self._switches: list[ToggleSwitch] = []
        self._scrollbars: list[RoundedScrollbar] = []
        self._thumbnail: Any = None  # a referência precisa sobreviver ao coletor
        self.machine: MachineCheck | None = None
        self._machine_dialog: tk.Toplevel | None = None
        self._prefs_after: str | None = None
        self._prefs_vars: dict[str, tk.Variable] = {}
        self._log_lines: list[str] = []
        self._pulling = False
        self._extra_outputs: list[str] = []
        self._last_stage: str | None = None
        self._job_started: float | None = None
        self._eta_seconds: float | None = None
        self._last_job_block = ""
        self._transcript_current: str | None = None
        self._last_output_dir = ""

        # Fila serial: o que espera a vez. Um trabalho por vez, sempre — dois
        # modelos de transcrição ao mesmo tempo brigam pela mesma memória.
        self.pending: list[Path] = []
        self._batch_done = 0
        self._queue_wait = 0
        self._batch_options: dict[str, Any] | None = None

        self.theme_choice = theme_choice or load_choice()
        self.limits: ResourceLimits = load_limits()
        self.theme: Theme = resolve(self.theme_choice)
        self._texts: list[tk.Text] = []

        self.log_handler = QueueLogHandler(self.queue)
        app_logger = logging.getLogger("lauda")
        # O registro ao vivo depende do INFO chegar até o handler. Quem abre a
        # janela pelo `main` já passou por `setup_logging`; quem a monta de
        # outro jeito (testes, script) não — e aí o nível herdado da raiz
        # engoliria tudo antes de sair da fila.
        if app_logger.level == logging.NOTSET or app_logger.level > logging.INFO:
            app_logger.setLevel(logging.INFO)
        app_logger.addHandler(self.log_handler)

        self._build_window()
        self._build_fonts()
        self._build_layout()
        self._apply_theme()
        self._after_id = self.root.after(80, self._drain_queue)

    # ---------------------------------------------------------------- janela --
    def _build_window(self) -> None:
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1200x800")
        self.root.minsize(1060, 720)

        icon = icon_path()
        if icon.exists():
            try:
                self.root.iconbitmap(default=str(icon))
            except tk.TclError:  # pragma: no cover - fora do Windows
                pass
        else:  # pragma: no cover - só acontece em instalação quebrada
            log.debug("Ícone da janela não encontrado em %s.", icon)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Erro dentro de um callback do Tk morreria em silêncio: aqui ele vai
        # para o log e o usuário fica sabendo que algo falhou.
        self.root.report_callback_exception = self._on_tk_error
    def _build_fonts(self) -> None:
        family = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
        self.font_body = tkfont.Font(family=family, size=10)
        self.font_bold = tkfont.Font(family=family, size=10, weight="bold")
        self.font_title = tkfont.Font(family=family, size=21, weight="bold")
        self.font_small = tkfont.Font(family=family, size=9)
        self.font_step = tkfont.Font(family=family, size=11, weight="bold")
        self.font_badge = tkfont.Font(family=family, size=11, weight="bold")
        self.font_nav = tkfont.Font(family=family, size=9)
        self.font_drop = tkfont.Font(family=family, size=17, weight="bold")
        self.font_file = tkfont.Font(family=family, size=11, weight="bold")
        self.font_title_small = tkfont.Font(family=family, size=13, weight="bold")
        mono_family = "Consolas" if sys.platform == "win32" else "Courier"
        self.font_mono = tkfont.Font(family=mono_family, size=10)

    # ----------------------------------------------------------------- tema --
    def _apply_theme(self) -> None:
        """Repinta a janela inteira com a paleta atual.

        Os widgets arredondados são desenhados em Canvas, então precisam ser
        repintados um a um — o ttk não alcança nenhum deles.
        """
        theme = self.theme
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.root.configure(background=theme.canvas)

        style.configure("TFrame", background=theme.canvas)
        style.configure("Card.TFrame", background=theme.paper, relief="flat")
        style.configure("TSeparator", background=theme.line)

        style.configure("TLabel", background=theme.paper, foreground=theme.ink,
                        font=self.font_body)
        style.configure("Card.TLabel", background=theme.paper, foreground=theme.ink,
                        font=self.font_body)
        style.configure("Step.TLabel", background=theme.paper, foreground=theme.ink,
                        font=self.font_step)
        style.configure("Hint.TLabel", background=theme.paper, foreground=theme.ink_soft,
                        font=self.font_small)
        style.configure("Title.TLabel", background=theme.canvas, foreground=theme.ink,
                        font=self.font_title)
        style.configure("Subtitle.TLabel", background=theme.canvas,
                        foreground=theme.ink_soft, font=self.font_small)
        style.configure("Sidebar.TLabel", background=theme.sidebar,
                        foreground=theme.ink_soft, font=self.font_small)
        style.configure("Section.TLabel", background=theme.paper, foreground=theme.ink,
                        font=self.font_step)
        style.configure("File.TLabel", background=theme.paper, foreground=theme.ink,
                        font=self.font_file)

        # Sem borda própria: quem desenha o contorno arredondado é a RoundedField.
        style.configure("TEntry", fieldbackground=theme.field, foreground=theme.ink,
                        insertcolor=theme.ink, bordercolor=theme.field,
                        lightcolor=theme.field, darkcolor=theme.field,
                        borderwidth=0, relief="flat")
        style.configure("TCombobox", fieldbackground=theme.field, background=theme.field,
                        foreground=theme.ink, arrowcolor=theme.ink_soft,
                        bordercolor=theme.field, lightcolor=theme.field,
                        darkcolor=theme.field, borderwidth=0, relief="flat")
        style.map("TCombobox",
                  fieldbackground=[("readonly", theme.field)],
                  foreground=[("readonly", theme.ink)],
                  selectbackground=[("readonly", theme.field)],
                  selectforeground=[("readonly", theme.ink)])
        for option, value in (
            ("*TCombobox*Listbox.background", theme.field),
            ("*TCombobox*Listbox.foreground", theme.ink),
            ("*TCombobox*Listbox.selectBackground", theme.accent),
            ("*TCombobox*Listbox.selectForeground", theme.primary_text),
        ):
            self.root.option_add(option, value)

        # ------------------------------------------- superfícies arredondadas --
        for switch in self._switches:
            switch.apply_theme(
                background=theme.paper,
                on_color=theme.accent,
                off_color=theme.muted,
                knob=theme.primary_text,
                foreground=theme.ink,
            )

        for shell in self._shells:
            shell.configure(background=theme.canvas)
        for barra in self._sidebar_panels:
            barra.configure(background=theme.sidebar)

        self.nav.apply_theme(
            background=theme.sidebar,
            fill_on=theme.nav_active,
            fg_on=theme.accent,
            fg_off=theme.ink_soft,
        )
        self.stepper.apply_theme(
            background=theme.canvas,
            accent=theme.accent,
            muted=theme.muted,
            ink=theme.ink,
            ink_soft=theme.ink_soft,
            on_check=theme.primary_text,
        )
        self.drop.apply_theme(
            fill=theme.surface,
            outline=None,
            parent_bg=theme.paper,
            accent=theme.accent,
            ink=theme.ink,
            ink_soft=theme.ink_soft,
        )
        self._paint_thumb()
        self._paint_state_dot()
        self._refresh_machine_summary()

        for scrollbar in self._scrollbars:
            scrollbar.apply_theme(
                thumb=mix(theme.preview_bg, theme.ink_soft, 0.55),
                background=theme.preview_bg,
            )

        for card in self._cards:
            card.apply_theme(fill=theme.paper, outline=theme.line, parent_bg=theme.canvas)

        for button in self._buttons:
            primario = button in self._primary_buttons
            button.apply_theme(
                fill=theme.primary if primario else theme.button,
                hover=theme.primary_active if primario else theme.button_active,
                foreground=theme.primary_text if primario else theme.button_text,
                disabled_fg=theme.ink_soft,
                parent_bg=theme.paper,
            )

        for abas in (getattr(self, "notebook", None), getattr(self, "perf_tabs", None)):
            if abas is not None:
                abas.apply_theme(
                    background=theme.paper,
                    fill_on=mix(theme.paper, theme.accent, 0.16),
                    fg_on=theme.accent,
                    fg_off=theme.ink_soft,
                )

        # Os presets são pintados por conta própria: o destaque não é do tema,
        # é de qual deles está em vigor.
        if hasattr(self, "preset_buttons"):
            self._paint_presets()
        self._refresh_diagnostics()

        for slider in getattr(self, "limit_scales", {}).values():
            slider.apply_theme(
                track=theme.field, fill_color=theme.accent,
                knob=theme.paper, parent_bg=theme.paper,
            )

        if hasattr(self, "progress"):
            self.progress.apply_theme(
                track=theme.field, bar=theme.accent, parent_bg=theme.paper
            )

        for field in self._fields:
            field.apply_theme(fill=theme.field, outline=theme.line, parent_bg=theme.paper)

        for panel in self._panels:
            panel.configure(background=theme.paper)
        for divider in self._dividers:
            divider.configure(background=theme.line)

        for widget in self._texts:
            widget.configure(
                background=theme.preview_bg,
                foreground=theme.preview_fg,
                selectbackground=theme.selection,
                selectforeground=theme.selection_text,
            )

        if hasattr(self, "theme_button"):
            self.theme_button.configure(text="Modo claro" if theme.dark else "Modo escuro")
        if hasattr(self, "file_label") and self.input_path:
            self.file_label.configure(foreground=theme.ink)
        if hasattr(self, "status_label"):
            self.status_label.configure(foreground=theme.ink_soft)

        apply_titlebar(self.root, theme.dark)

    def toggle_theme(self) -> None:
        """Alterna claro/escuro e guarda a escolha para a próxima abertura."""
        self.theme_choice = "claro" if self.theme.dark else "escuro"
        self.theme = resolve(self.theme_choice)
        save_choice(self.theme_choice)
        self._apply_theme()

    def set_theme(self, choice: str) -> None:
        """Define o tema por nome: auto, claro ou escuro."""
        if choice not in THEME_CHOICES:
            raise ValueError(f"tema inválido: {choice!r}")
        self.theme_choice = choice
        self.theme = resolve(choice)
        save_choice(choice)
        self._apply_theme()

    # ---------------------------------------------------------------- layout --
    def _build_layout(self) -> None:
        """Barra lateral de navegação à esquerda, página escolhida à direita."""
        outer = tk.Frame(self.root, background=self.theme.canvas)
        outer.pack(fill="both", expand=True)
        self._shells.append(outer)

        self.nav = SideNav(
            outer, font=self.font_nav, background=self.theme.sidebar, width=158
        )
        self.nav.pack(side="left", fill="y")

        self.content = tk.Frame(outer, background=self.theme.canvas, padx=16, pady=14)
        self.content.pack(side="left", fill="both", expand=True)
        self._shells.append(self.content)

        self._build_sidebar_footer()

        self._build_job_page()

        # Relatório, Transcrição e Legendas são a mesma página com outro
        # sufixo: uma aba por arquivo da pasta de saída.
        self.page_report = FileTabsPage(self, PAGE_REPORT)
        self.page_report.build()
        self._build_log_page()
        self.page_transcript = FileTabsPage(self, PAGE_TRANSCRIPT)
        self.page_transcript.build()
        self.page_subtitles = FileTabsPage(self, PAGE_SUBTITLES)
        self.page_subtitles.build()

        self._build_files_page()
        self._build_limits_page()
        self._build_help_page()
        self._build_settings_page()

        self.nav.on_change = self._on_page_changed
        self._register_prefs()
        self._refresh_prefs_summary()
        self._set_text(self.text_help, STEPS_TEXT)
        for pagina in self.file_pages:
            pagina.rebuild()
        self._refresh_files_page()
        self.nav.select(self.tab_job)

    @property
    def file_pages(self) -> tuple[FileTabsPage, ...]:
        """As três páginas que leem a pasta de saída."""
        return (self.page_report, self.page_transcript, self.page_subtitles)

    # ------------------------------------------------------- preferências --
    def _register_prefs(self) -> None:
        """Liga as escolhas da tela ao `ui.json` e restaura as da última vez.

        Sem isto o usuário reescolhia idioma, qualidade, os seis interruptores e
        a pasta de saída a cada abertura — a reclamação mais repetida de quem
        testou.
        """
        self._prefs_vars = {
            "language": self.language_var,
            "quality": self.model_var,
            "subtitle_density": self.density_var,
            "output_dir": self.folder_var,
            "diarize": self.var_diarize,
            "words": self.var_words,
            "srt": self.var_srt,
            "vtt": self.var_vtt,
            "visual": self.var_visual,
            "summarize": self.var_summarize,
            "fast": self.var_fast,
            "open_folder": self.var_open_folder,
            "subs_beside": self.var_subs_beside,
        }
        self._restore_prefs()
        for variavel in self._prefs_vars.values():
            variavel.trace_add("write", lambda *_a: self._on_pref_changed())

    def _on_pref_changed(self) -> None:
        """Guarda a escolha e reavalia o que ela custa de máquina.

        Trocar a qualidade ou ligar "quem fala" muda quanta memória o trabalho
        pede — e é a página Desempenho que responde se ela cabe.
        """
        self._schedule_save_prefs()
        self._refresh_perf()

        # As abas da Transcrição são a pasta de saída: trocou a pasta, trocam
        # as abas. Só quando ela muda de verdade — refazer a cada tecla
        # digitada no campo jogaria fora a aba que o usuário estava lendo.
        pasta = self.folder_var.get().strip()
        if pasta != self._last_output_dir:
            self._last_output_dir = pasta
            for pagina in self.file_pages:
                pagina.rebuild()

    def _restore_prefs(self) -> None:
        """Aplica o que estava salvo, descartando valor que não existe mais."""
        guardado = load_value(JOB_PREFS_KEY, {})
        if not isinstance(guardado, dict):
            log.debug("Preferencias da tela em formato inesperado; usando padroes.")
            return

        idiomas = [rotulo for rotulo, _ in LANGUAGES]
        qualidades = [rotulo for rotulo, _ in MODEL_LABELS]
        for chave, validos in (("language", idiomas), ("quality", qualidades)):
            valor = guardado.get(chave)
            # Um rótulo pode sumir entre versões: aí vale o padrão, não um
            # combobox mostrando texto que não existe mais na lista.
            if isinstance(valor, str) and valor in validos:
                self._prefs_vars[chave].set(valor)

        pasta = guardado.get("output_dir")
        if isinstance(pasta, str) and pasta.strip():
            self.folder_var.set(pasta)

        # Quem usou a versão anterior tem "srt": false gravado — o padrão de
        # então. Restaurar esse valor manteria a legenda desligada justamente
        # para quem já é usuário, que é quem sente falta dela. A virada vale
        # uma vez só: depois disso a escolha volta a ser de quem usa.
        interruptores = [
            "diarize", "words", "srt", "vtt", "visual", "summarize", "fast",
            "open_folder", "subs_beside",
        ]
        if int(guardado.get("prefs_version") or 0) < PREFS_VERSION:
            interruptores.remove("srt")

        for chave in interruptores:
            if chave in guardado:
                self._prefs_vars[chave].set(bool(guardado[chave]))

    def _schedule_save_prefs(self) -> None:
        if self._prefs_after is not None:
            try:
                self.root.after_cancel(self._prefs_after)
            except tk.TclError:  # pragma: no cover - janela já destruída
                pass
        self._prefs_after = self.root.after(PREFS_SAVE_DELAY_MS, self._save_prefs)

    def _save_prefs(self) -> None:
        """Grava as escolhas atuais. Chamado pelo temporizador e ao fechar."""
        self._prefs_after = None
        self._refresh_prefs_summary()
        if not self._prefs_vars:  # pragma: no cover - antes do layout
            return
        save_value(
            JOB_PREFS_KEY,
            {
                "prefs_version": PREFS_VERSION,
                **{chave: variavel.get() for chave, variavel in self._prefs_vars.items()},
            },
        )

    # ------------------------------------------------- registro ao vivo --
    def _append_log(self, linha: str) -> None:
        """Acrescenta uma linha ao registro, sem roubar a rolagem do usuário."""
        self._log_lines.append(linha)
        if len(self._log_lines) > LOG_VIEW_LINES:
            del self._log_lines[: len(self._log_lines) - LOG_VIEW_LINES]
        if not hasattr(self, "text_log"):
            return

        # Só acompanha o fim se a pessoa já estava no fim. Quem rolou para cima
        # está lendo alguma coisa; puxar a tela seria hostil.
        no_fim = self.text_log.yview()[1] > 0.999
        self.text_log.configure(state="normal")
        self.text_log.insert("end", linha + "\n")
        self.text_log.configure(state="disabled")
        if no_fim:
            self.text_log.see("end")

    def check_ollama(self) -> None:
        """Pergunta ao Ollama o que ele tem, sem travar a janela."""
        self.ollama_status.configure(text="Verificando…")
        self.button_ollama_pull.configure(state="disabled")

        def trabalho() -> None:
            opcoes = JobOptions(input_path=Path("-"), output_dir=Path("-"))
            nomes, motivo = list_models(opcoes)
            self.queue.put(("ollama", (nomes, motivo)))

        threading.Thread(target=trabalho, name="lauda-ollama", daemon=True).start()

    def _on_ollama(self, payload: tuple[list[str] | None, str]) -> None:
        nomes, motivo = payload
        if nomes is None:
            self.ollama_status.configure(
                text=f"{motivo}\nSem Ollama o aplicativo funciona igual — só não "
                "acrescenta resumo ao relatório."
            )
            self.button_ollama_pull.configure(state="disabled")
            return

        opcoes = JobOptions(input_path=Path("-"), output_dir=Path("-"))
        escolhido, detalhe = pick_model(opcoes, nomes)
        if escolhido == DEFAULT_OLLAMA_MODEL:
            texto = f"Tudo pronto: o servidor está no ar e '{escolhido}' está baixado."
        elif escolhido:
            texto = f"O servidor está no ar. {detalhe[0].upper()}{detalhe[1:]}"
        else:
            texto = (
                f"O servidor está no ar, mas nenhum modelo compatível está baixado.\n"
                f"Baixados: {', '.join(nomes) or 'nenhum'}."
            )
        self.ollama_status.configure(text=texto)
        self.button_ollama_pull.configure(
            state="disabled" if escolhido == DEFAULT_OLLAMA_MODEL else "normal"
        )

    def download_ollama_model(self) -> None:
        """Baixa o modelo padrão mostrando o andamento — são ~9 GB."""
        if self._pulling:
            return
        self._pulling = True
        self.button_ollama_pull.configure(state="disabled", text="Baixando…")
        self.ollama_progress.grid()
        self.ollama_progress.configure(value=0)
        log.info("Baixando o modelo %s do Ollama.", DEFAULT_OLLAMA_MODEL)

        def trabalho() -> None:
            opcoes = JobOptions(input_path=Path("-"), output_dir=Path("-"))

            def andamento(fracao: float | None, texto: str) -> None:
                self.queue.put(("pull", (fracao, texto)))

            ok, mensagem = pull_model(opcoes, DEFAULT_OLLAMA_MODEL, andamento)
            self.queue.put(("pull_done", (ok, mensagem)))

        threading.Thread(target=trabalho, name="lauda-pull", daemon=True).start()

    def _on_pull(self, payload: tuple[float | None, str]) -> None:
        fracao, texto = payload
        if fracao is not None:
            self.ollama_progress.configure(value=fracao * 100)
        self.ollama_status.configure(text=f"Baixando {DEFAULT_OLLAMA_MODEL} — {texto}")

    def _on_pull_done(self, payload: tuple[bool, str]) -> None:
        ok, mensagem = payload
        self._pulling = False
        self.ollama_progress.grid_remove()
        self.button_ollama_pull.configure(
            state="normal", text=f"Baixar {DEFAULT_OLLAMA_MODEL}"
        )
        log.info("Download do modelo: %s", mensagem)
        if ok:
            self.check_ollama()
        else:
            self.ollama_status.configure(text=f"Não deu certo: {mensagem}")

    def _build_sidebar_footer(self) -> None:
        """Versão e estado atual, no pé da barra lateral."""
        ttk.Label(
            self.nav.bottom, text=f"v{APP_VERSION}", style="Sidebar.TLabel"
        ).pack(anchor="w")

        linha = tk.Frame(self.nav.bottom, background=self.theme.sidebar)
        linha.pack(anchor="w", pady=(3, 0))
        self._sidebar_panels.append(linha)
        self.state_dot = tk.Canvas(
            linha, width=10, height=10, highlightthickness=0, borderwidth=0,
            background=self.theme.sidebar,
        )
        self.state_dot.pack(side="left")
        self.state_label = ttk.Label(linha, text="Pronto", style="Sidebar.TLabel")
        self.state_label.pack(side="left", padx=(6, 0))
        self._state_color = self.theme.success

    def _paint_state_dot(self, color: str | None = None) -> None:
        if color is not None:
            self._state_color = color
        self.state_dot.configure(background=self.theme.sidebar)
        self.state_dot.delete("all")
        self.state_dot.create_oval(
            1, 1, 9, 9, fill=self._state_color, outline=self._state_color
        )

    def _set_state(self, text: str, color: str) -> None:
        """Atualiza o indicador do rodapé da barra lateral."""
        self.state_label.configure(text=text)
        self._paint_state_dot(color)

    # ------------------------------------------------------ página do trabalho --
    def _build_job_page(self) -> None:
        page = tk.Frame(self.content, background=self.theme.canvas)
        self._shells.append(page)
        self.tab_job = page
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=0, minsize=352)
        page.rowconfigure(0, weight=1)

        self._build_file_card(page)
        self._build_options_card(page)
        self._build_action_bar(page)
        self.nav.add(page, "Novo trabalho", "plus")

    def _build_file_card(self, page: tk.Misc) -> None:
        """Cartão da esquerda: a zona de soltar e o arquivo escolhido."""
        card = RoundedCard(page, padding=14, radius=16)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self._cards.append(card)
        card.body.rowconfigure(0, weight=1)
        card.body.columnconfigure(0, weight=1)

        soltar = _HAS_DND
        self.drop = DropZone(
            card.body,
            command=self.pick_file,
            title="Solte seu arquivo de mídia aqui" if soltar
            else "Clique para escolher seu arquivo",
            subtitle="ou clique para escolher." if soltar else "áudio ou vídeo.",
            hint="MP4, MKV, MOV, AVI, MP3, WAV, M4A e outros",
            font_title=self.font_drop,
            font_body=self.font_body,
            font_small=self.font_small,
            fill=self.theme.surface,
            parent_bg=self.theme.paper,
            accent=self.theme.accent,
            ink=self.theme.ink,
            ink_soft=self.theme.ink_soft,
        )
        self.drop.grid(row=0, column=0, sticky="nsew")
        self._enable_drop(self.drop)

        self.file_divider = tk.Frame(card.body, height=1, background=self.theme.line)
        self._dividers.append(self.file_divider)

        self.file_row = tk.Frame(card.body, background=self.theme.paper)
        self._panels.append(self.file_row)
        self.file_row.columnconfigure(1, weight=1)

        self.thumb = tk.Canvas(
            self.file_row, width=104, height=58, highlightthickness=0, borderwidth=0,
            background=self.theme.surface,
        )
        self.thumb.grid(row=0, column=0, rowspan=2, sticky="w")

        self.file_label = ttk.Label(self.file_row, text="", style="File.TLabel")
        self.file_label.grid(row=0, column=1, sticky="sw", padx=(14, 0))
        self.file_meta = ttk.Label(self.file_row, text="", style="Hint.TLabel")
        self.file_meta.grid(row=1, column=1, sticky="nw", padx=(14, 0), pady=(2, 0))

        self.button_clear = RoundedButton(
            self.file_row, text="✕", command=self.clear_file, font=self.font_body,
            width=42, radius=11,
        )
        self.button_clear.grid(row=0, column=2, rowspan=2, padx=(10, 0))
        self._buttons.append(self.button_clear)

        # Fila: aparece só quando há mais de um arquivo esperando.
        self.queue_row = tk.Frame(card.body, background=self.theme.paper)
        self._panels.append(self.queue_row)
        self.queue_row.columnconfigure(0, weight=1)
        self.queue_label = ttk.Label(self.queue_row, text="", style="Hint.TLabel")
        self.queue_label.grid(row=0, column=0, sticky="w")
        self.button_queue_clear = RoundedButton(
            self.queue_row, text="Esvaziar a fila", command=self.clear_queue,
            font=self.font_small, radius=11,
        )
        self.button_queue_clear.grid(row=0, column=1, padx=(10, 0))
        self._buttons.append(self.button_queue_clear)

    def _build_options_card(self, page: tk.Misc) -> None:
        """Cartão da direita: idioma, qualidade, recursos e pasta de saída."""
        card = RoundedCard(page, padding=18, radius=16)
        card.grid(row=0, column=1, sticky="nsew")
        self._cards.append(card)
        body = card.body
        body.columnconfigure(0, weight=1)
        row = 0

        ttk.Label(body, text="Idioma", style="Card.TLabel").grid(
            row=row, column=0, sticky="w"
        )
        row += 1
        self.language_var = tk.StringVar(value=LANGUAGES[0][0])
        campo_idioma = RoundedField(
            body, height=38, parent_bg=self.theme.paper, icon="globe",
            icon_color=self.theme.ink_soft,
        )
        campo_idioma.grid(row=row, column=0, sticky="ew", pady=(4, 12))
        campo_idioma.attach(
            ttk.Combobox(
                campo_idioma, textvariable=self.language_var, state="readonly",
                values=[label for label, _ in LANGUAGES], font=self.font_body,
            )
        )
        self._fields.append(campo_idioma)
        row += 1

        ttk.Label(body, text="Qualidade", style="Card.TLabel").grid(
            row=row, column=0, sticky="w"
        )
        row += 1
        self.model_var = tk.StringVar(value=MODEL_LABELS[2][0])
        campo_modelo = RoundedField(
            body, height=38, parent_bg=self.theme.paper, icon="sliders",
            icon_color=self.theme.ink_soft,
        )
        campo_modelo.grid(row=row, column=0, sticky="ew", pady=(4, 14))
        campo_modelo.attach(
            ttk.Combobox(
                campo_modelo, textvariable=self.model_var, state="readonly",
                values=[label for label, _ in MODEL_LABELS], font=self.font_body,
            )
        )
        self._fields.append(campo_modelo)
        row += 1

        ttk.Label(body, text="Recursos", style="Section.TLabel").grid(
            row=row, column=0, sticky="w", pady=(0, 4)
        )
        row += 1

        self.var_diarize = tk.BooleanVar(value=False)
        self.var_words = tk.BooleanVar(value=False)
        self.var_srt = tk.BooleanVar(value=True)
        self.var_vtt = tk.BooleanVar(value=False)
        self.var_visual = tk.BooleanVar(value=False)
        self.var_summarize = tk.BooleanVar(value=False)
        # Preferências de depois do trabalho. Ficam em Configurações, não aqui:
        # não mudam o que é processado, só o que acontece quando termina.
        self.var_open_folder = tk.BooleanVar(value=True)
        self.var_subs_beside = tk.BooleanVar(value=True)

        for texto, variavel in (
            ("Diarização de falantes", self.var_diarize),
            ("Marcar o tempo das palavras", self.var_words),
            ("Gerar legenda .srt", self.var_srt),
            ("Gerar legenda .vtt", self.var_vtt),
            ("Extrair miniaturas (só vídeo)", self.var_visual),
        ):
            self._switch(body, row, texto, variavel)
            row += 1

        # O tamanho da legenda era acidente de como o modelo cortou os trechos:
        # em qualidade baixa saía uma legenda para o vídeo inteiro. Agora é
        # escolha, e ela fica junto das legendas, não numa aba distante.
        ttk.Label(body, text="Tamanho das legendas", style="Card.TLabel").grid(
            row=row, column=0, sticky="w", pady=(8, 0)
        )
        row += 1
        self.density_var = tk.StringVar(value=DENSITY_LABELS[1][0])
        campo_densidade = RoundedField(
            body, height=38, parent_bg=self.theme.paper, icon="transcript",
            icon_color=self.theme.ink_soft,
        )
        campo_densidade.grid(row=row, column=0, sticky="ew", pady=(4, 2))
        campo_densidade.attach(
            ttk.Combobox(
                campo_densidade, textvariable=self.density_var, state="readonly",
                values=[label for label, _ in DENSITY_LABELS], font=self.font_body,
            )
        )
        self._fields.append(campo_densidade)
        row += 1
        ttk.Label(
            body,
            text="Vale para .srt e .vtt. As curtas ficam bem sincronizadas com "
            "\"marcar o tempo das palavras\" ligado.",
            style="Hint.TLabel", wraplength=300, justify="left",
        ).grid(row=row, column=0, sticky="w", pady=(0, 4))
        row += 1

        row = self._divider(body, row)
        self._switch(body, row, "Integrar com Ollama", self.var_summarize)
        row += 1
        # A pergunta que ninguém conseguia responder olhando o interruptor:
        # "quando eu desligo isso?". A resposta é curta e cabe aqui embaixo.
        ttk.Label(
            body,
            text=(
                "Ollama é a IA de texto: acrescenta resumo, tópicos e itens de ação.\n"
                "A transcrição da fala NÃO usa Ollama — desligar não atrapalha a\n"
                f"legenda. Modelo padrão: {DEFAULT_OLLAMA_MODEL}."
            ),
            style="Hint.TLabel",
            justify="left",
        ).grid(row=row, column=0, sticky="w", pady=(2, 0))
        row += 1
        row = self._divider(body, row)

        ttk.Label(body, text="Pasta de saída", style="Card.TLabel").grid(
            row=row, column=0, sticky="w"
        )
        row += 1
        self.folder_var = tk.StringVar(value=str(self.output_dir))
        pasta = tk.Frame(body, background=self.theme.paper)
        pasta.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        pasta.columnconfigure(0, weight=1)
        self._panels.append(pasta)

        campo_pasta = RoundedField(
            pasta, height=38, parent_bg=self.theme.paper, icon="folder",
            icon_color=self.theme.ink_soft,
        )
        campo_pasta.grid(row=0, column=0, sticky="ew")
        campo_pasta.attach(
            ttk.Entry(campo_pasta, textvariable=self.folder_var, font=self.font_small)
        )
        self._fields.append(campo_pasta)
        botao_pasta = RoundedButton(
            pasta, text="Alterar", command=self.pick_folder, font=self.font_body
        )
        botao_pasta.grid(row=0, column=1, padx=(8, 0))
        self._buttons.append(botao_pasta)

    def _switch(
        self, parent: tk.Misc, row: int, text: str, variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
    ) -> ToggleSwitch:
        """Uma linha de interruptor, já registrada para a repintura do tema."""
        switch = ToggleSwitch(
            parent, text=text, variable=variable, command=command,
            font=self.font_body, background=self.theme.paper,
            on_color=self.theme.accent, off_color=self.theme.muted,
            knob=self.theme.primary_text, foreground=self.theme.ink,
        )
        switch.grid(row=row, column=0, sticky="ew")
        self._switches.append(switch)
        return switch

    def _build_action_bar(self, page: tk.Misc) -> None:
        """Rodapé: o botão Processar e a trilha de etapas."""
        divisor = tk.Frame(page, height=1, background=self.theme.line)
        divisor.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self._dividers.append(divisor)

        bar = tk.Frame(page, background=self.theme.canvas)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        bar.columnconfigure(2, weight=1)
        self._shells.append(bar)

        self.go_button = RoundedButton(
            bar, text="Processar", command=self.start, font=self.font_bold,
            radius=13, padding=(22, 12), icon="play",
        )
        self.go_button.grid(row=0, column=0, sticky="w")
        self._buttons.append(self.go_button)
        self._primary_buttons.add(self.go_button)

        # So aparece com trabalho em andamento: botao morto na tela e ruido.
        self.pause_button = RoundedButton(
            bar, text="Pausar", command=self.toggle_pause, font=self.font_body,
            radius=13, padding=(16, 12), state="disabled",
        )
        self.pause_button.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._buttons.append(self.pause_button)

        self.stepper = Stepper(
            bar, steps=PIPELINE_STEPS, font=self.font_small, height=62,
            background=self.theme.canvas, accent=self.theme.accent,
            muted=self.theme.muted, ink=self.theme.ink, ink_soft=self.theme.ink_soft,
            on_check=self.theme.primary_text,
        )
        self.stepper.grid(row=0, column=2, sticky="ew", padx=(24, 0))

        self.progress = RoundedProgress(bar, height=5, maximum=100)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 5))

        self.status_label = ttk.Label(
            bar, text="Pronto para começar.", style="Subtitle.TLabel"
        )
        self.status_label.grid(row=2, column=0, columnspan=3, sticky="w")

    # ------------------------------------------------------- arrastar e soltar --
    def _enable_drop(self, widget: tk.Widget) -> bool:
        """Liga o arrastar-e-soltar, se o extra `ui` estiver instalado."""
        if not _HAS_DND:
            return False
        try:
            TkinterDnD._require(self.root)
            widget.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            widget.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            widget.dnd_bind(  # type: ignore[attr-defined]
                "<<DragEnter>>", lambda _e: self.drop.set_active(True)
            )
            widget.dnd_bind(  # type: ignore[attr-defined]
                "<<DragLeave>>", lambda _e: self.drop.set_active(False)
            )
        except Exception as exc:  # pragma: no cover - depende do ambiente gráfico
            log.info("Arrastar-e-soltar indisponivel: %s", exc)
            return False
        return True

    def _on_drop(self, event: Any) -> None:
        """Recebe os arquivos arrastados. Os caminhos vêm como lista do Tcl."""
        self.drop.set_active(False)
        try:
            caminhos = self.root.tk.splitlist(event.data)
        except tk.TclError:  # pragma: no cover - dado estranho do gerenciador
            return
        self._accept_files([Path(str(bruto)) for bruto in caminhos])

    # --------------------------------------------------------- páginas de texto --
    def _text_page(self, title: str, icon: str) -> tuple[tk.Frame, tk.Text]:
        card = RoundedCard(self.content, padding=12, radius=16)
        self._cards.append(card)
        _, texto = self._text_area(card.body)
        self.nav.add(card, title, icon)
        return card, texto  # type: ignore[return-value]

    # ------------------------------------------------------------ Registro --
    def _build_log_page(self) -> None:
        """Página "Registro": o que o programa está fazendo, ao vivo.

        Antes isto era um modo escondido da página Relatório, acessível por um
        botão que alternava as duas coisas no mesmo lugar. Separar resolve a
        pergunta "onde foi parar o meu laudo?" enquanto o trabalho roda.
        """
        card = RoundedCard(self.content, padding=12, radius=16)
        self._cards.append(card)
        self.tab_log = card

        ttk.Label(
            card.body,
            text="O que está acontecendo agora. Durante um trabalho, cada etapa "
                 "aparece aqui na hora em que acontece.",
            style="Hint.TLabel", justify="left", wraplength=760,
        ).pack(fill="x", pady=(0, 8))

        _, self.text_log = self._text_area(card.body)

        fileira = tk.Frame(card.body, background=self.theme.paper)
        fileira.pack(fill="x", pady=(10, 2))
        self._panels.append(fileira)

        self.button_log_folder = RoundedButton(
            fileira, text="Abrir a pasta dos logs", command=self.open_log_folder,
            font=self.font_body, icon="folder",
        )
        self.button_log_folder.pack(side="left")
        self.button_log_copy = RoundedButton(
            fileira, text="Copiar o registro", command=self.copy_log,
            font=self.font_body,
        )
        self.button_log_copy.pack(side="left", padx=(10, 0))
        self._buttons += [self.button_log_folder, self.button_log_copy]

        self.nav.add(card, "Registro", "sliders")

    def open_log_folder(self) -> None:
        """A pasta dos logs é o que eu peço quando alguém relata um problema."""
        if LOG_DIR.exists():
            self._reveal(LOG_DIR)
        else:  # pragma: no cover - só antes da primeira execução
            messagebox.showinfo(APP_NAME, f"Ainda não há logs em:\n{LOG_DIR}")

    def copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text_log.get("1.0", "end-1c"))
        self.status_label.configure(text="Registro copiado para a área de transferência.")

    def _on_page_changed(self, page: tk.Widget) -> None:
        """Abrir uma página a atualiza. Tela velha é tela errada."""
        for pagina in self.file_pages:
            if page is pagina.card:
                pagina.refresh()
                return
        if page is getattr(self, "tab_files", None):
            self._refresh_files_page()

    def _build_files_page(self) -> None:
        """Página "Arquivos": o trabalho recém-terminado e o histórico de todos.

        Era um aviso parado ("a lista aparece depois de processar") que sumia ao
        fechar a janela. Agora guarda o que dá para comparar entre trabalhos:
        velocidade, cobertura, avisos e confiança.
        """
        card = RoundedCard(self.content, padding=12, radius=16)
        self._cards.append(card)
        _, self.text_files = self._text_area(card.body)

        fileira = tk.Frame(card.body, background=self.theme.paper)
        fileira.pack(fill="x", pady=(10, 2))
        self._panels.append(fileira)

        self.button_history_open = RoundedButton(
            fileira, text="Abrir o laudo", command=self.open_history_report,
            font=self.font_body, icon="doc",
        )
        self.button_history_open.pack(side="left")
        self.button_history_clear = RoundedButton(
            fileira, text="Limpar o histórico", command=self.clear_history,
            font=self.font_body,
        )
        self.button_history_clear.pack(side="left", padx=(10, 0))
        self._buttons += [self.button_history_open, self.button_history_clear]

        self.tab_files = card
        self.nav.add(card, "Arquivos", "folder")

    def _refresh_files_page(self) -> None:
        """Redesenha a página: bloco do último trabalho + tabela do histórico."""
        partes = [parte for parte in (self._last_job_block, history.format_history(history.load()))
                  if parte]
        self._set_text(self.text_files, "\n\n\n".join(partes))

    def clear_history(self) -> None:
        if not messagebox.askokcancel(
            APP_NAME,
            "Apagar o histórico de trabalhos?\n\n"
            "Os relatórios e as legendas já gerados continuam onde estão — some "
            "só a lista desta página.",
        ):
            return
        history.clear()
        self._last_job_block = ""
        self._refresh_files_page()
        log.info("Histórico apagado a pedido do usuário.")

    def open_history_report(self) -> None:
        """Abre o laudo do trabalho mais recente que ainda existe em disco."""
        for entrada in reversed(history.load()):
            if entrada.report_path and Path(entrada.report_path).exists():
                self._reveal(Path(entrada.report_path))
                return
        messagebox.showinfo(
            APP_NAME,
            "Nenhum laudo do histórico foi encontrado em disco. Talvez a pasta de "
            "saída tenha sido movida ou apagada.",
        )

    def _text_area(self, parent: tk.Misc) -> tuple[tk.Frame, tk.Text]:
        frame = tk.Frame(parent, background=self.theme.paper, highlightthickness=0)
        frame.pack(fill="both", expand=True)
        self._panels.append(frame)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        text = tk.Text(
            frame,
            wrap="none",
            font=self.font_mono,
            background=self.theme.preview_bg,
            foreground=self.theme.preview_fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,   # sem o anel claro em volta no modo escuro
            padx=14,
            pady=12,
            insertwidth=0,
            spacing1=1,
        )
        text.grid(row=0, column=0, sticky="nsew")
        self._texts.append(text)

        vertical = RoundedScrollbar(
            frame, orient="vertical", command=text.yview,
            background=self.theme.preview_bg,
        )
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = RoundedScrollbar(
            frame, orient="horizontal", command=text.xview,
            background=self.theme.preview_bg,
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self._scrollbars.extend((vertical, horizontal))
        text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return frame, text

    # ------------------------------------------------------------ configurações --
    def _build_settings_page(self) -> None:
        card = RoundedCard(self.content, padding=20, radius=16)
        self._cards.append(card)
        body = card.body
        body.columnconfigure(0, weight=1)
        self.tab_settings = card

        ttk.Label(body, text="Aparência", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        linha = tk.Frame(body, background=self.theme.paper)
        linha.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._panels.append(linha)
        self.theme_button = RoundedButton(
            linha, text="Modo escuro", command=self.toggle_theme,
            font=self.font_body, radius=11, width=140,
        )
        self.theme_button.pack(side="left")
        self._buttons.append(self.theme_button)
        ttk.Label(
            linha,
            text="A escolha fica salva para as próximas vezes.",
            style="Hint.TLabel",
        ).pack(side="left", padx=(12, 0))

        self._divider(body, 2)

        ttk.Label(body, text="Quando o trabalho termina", style="Section.TLabel").grid(
            row=3, column=0, sticky="w"
        )
        depois = tk.Frame(body, background=self.theme.paper)
        depois.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        depois.columnconfigure(0, weight=1)
        self._panels.append(depois)
        self._switch(depois, 0, "Abrir a pasta de saída", self.var_open_folder)
        self._switch(
            depois, 1, "Deixar a legenda junto do vídeo", self.var_subs_beside
        )
        ttk.Label(
            depois,
            text="A legenda ao lado do arquivo é o que faz o player achá-la sozinho. "
            "A cópia na pasta de saída continua lá.",
            style="Hint.TLabel",
            justify="left",
            wraplength=620,
        ).grid(row=2, column=0, sticky="w", pady=(2, 0))

        self._divider(body, 5)

        ttk.Label(body, text="Ollama (a IA de texto)", style="Section.TLabel").grid(
            row=6, column=0, sticky="w"
        )
        ollama = tk.Frame(body, background=self.theme.paper)
        ollama.grid(row=7, column=0, sticky="ew", pady=(4, 0))
        ollama.columnconfigure(0, weight=1)
        self._panels.append(ollama)
        self.ollama_status = ttk.Label(
            ollama, text="Verificando…", style="Hint.TLabel", justify="left",
            wraplength=620,
        )
        self.ollama_status.grid(row=0, column=0, sticky="w")
        botoes_ollama = tk.Frame(ollama, background=self.theme.paper)
        botoes_ollama.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._panels.append(botoes_ollama)
        self.button_ollama_check = RoundedButton(
            botoes_ollama, text="Verificar", command=self.check_ollama,
            font=self.font_body,
        )
        self.button_ollama_check.pack(side="left")
        self.button_ollama_pull = RoundedButton(
            botoes_ollama, text=f"Baixar {DEFAULT_OLLAMA_MODEL}",
            command=self.download_ollama_model, font=self.font_body, state="disabled",
        )
        self.button_ollama_pull.pack(side="left", padx=(10, 0))
        self._buttons += [self.button_ollama_check, self.button_ollama_pull]
        self.ollama_progress = RoundedProgress(ollama, height=5, maximum=100)
        self.ollama_progress.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.ollama_progress.grid_remove()

        self._divider(body, 8)

        ttk.Label(body, text="Opções de processamento", style="Section.TLabel").grid(
            row=9, column=0, sticky="w"
        )
        self.prefs_summary = ttk.Label(
            body, text="", style="Hint.TLabel", justify="left", wraplength=620
        )
        self.prefs_summary.grid(row=10, column=0, sticky="w", pady=(4, 0))

        acoes = tk.Frame(body, background=self.theme.paper)
        acoes.grid(row=11, column=0, sticky="w", pady=(10, 0))
        self._panels.append(acoes)
        botao_reset = RoundedButton(
            acoes, text="Restaurar padrões", command=self.reset_job_prefs,
            font=self.font_body,
        )
        botao_reset.pack(side="left")
        self._buttons.append(botao_reset)

        self.nav.add(card, "Configurações", "gear")

    def _build_help_page(self) -> None:
        """O passo a passo, que antes morava dentro de Configurações.

        Manual de uso não é preferência: quem abre Configurações quer mudar
        alguma coisa, não ler um tutorial.
        """
        card = RoundedCard(self.content, padding=12, radius=16)
        self._cards.append(card)
        self.tab_help = card
        _, self.text_help = self._text_area(card.body)
        self.nav.add(card, "Ajuda", "help")

    def reset_job_prefs(self) -> None:
        """Devolve as opções de processamento ao estado de fábrica.

        Existe porque agora elas são lembradas: sem um caminho de volta, um
        interruptor esquecido ligado vira um mistério na execução seguinte.
        """
        self.language_var.set(LANGUAGES[0][0])
        self.model_var.set(MODEL_LABELS[2][0])
        self.folder_var.set(str(self.output_dir))
        for variavel in (
            self.var_diarize, self.var_words,
            self.var_vtt, self.var_visual, self.var_summarize, self.var_fast,
        ):
            variavel.set(False)
        self.var_srt.set(True)   # o padrão da legenda é sair, não faltar
        self._save_prefs()
        self._refresh_prefs_summary()

    def _refresh_prefs_summary(self) -> None:
        """Uma linha dizendo o que está guardado, para não precisar caçar."""
        if not hasattr(self, "prefs_summary"):  # pragma: no cover - antes do layout
            return
        ligados = [
            rotulo
            for rotulo, variavel in (
                ("identificar quem fala", self.var_diarize),
                ("tempo das palavras", self.var_words),
                (".srt", self.var_srt),
                (".vtt", self.var_vtt),
                ("miniaturas", self.var_visual),
                ("Ollama", self.var_summarize),
                ("lotes", self.var_fast),
            )
            if variavel.get()
        ]
        self.prefs_summary.configure(
            text=(
                f"Idioma: {self.language_var.get()}   |   "
                f"Qualidade: {self.model_var.get()}\n"
                f"Recursos ligados: {', '.join(ligados) if ligados else 'nenhum'}\n"
                f"Pasta de saída: {self.folder_var.get()}\n"
                f"Ficam guardadas em {PREFS_PATH}."
            )
        )

    def _divider(self, parent: tk.Misc, row: int) -> int:
        divisor = tk.Frame(parent, height=1, background=self.theme.line)
        divisor.grid(row=row, column=0, sticky="ew", pady=10)
        self._dividers.append(divisor)
        return row + 1


    @staticmethod
    def _set_text(widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # ------------------------------------------------------------ desempenho --
    def _build_limits_page(self) -> None:
        """Página Desempenho: Resumo, Limites e Diagnóstico (BACKLOG-028).

        Era uma tela só, com quatro sliders e vocabulário de máquina ("em 25% o
        app usa 1/4 dos núcleos"). Quem só quer continuar usando o computador
        enquanto transcreve não deveria precisar traduzir isso — daí o Resumo,
        com quatro opções de nome comum. Os sliders continuam existindo, na aba
        do lado, para quem quiser afinar.
        """
        card = RoundedCard(self.content, padding=18, radius=16)
        self._cards.append(card)
        self.tab_limits = card

        self.perf_tabs = RoundedTabs(
            card.body, font=self.font_body, background=self.theme.paper
        )
        self.perf_tabs.pack(fill="both", expand=True)

        resumo = tk.Frame(card.body, background=self.theme.paper)
        limites = tk.Frame(card.body, background=self.theme.paper)
        diagnostico = tk.Frame(card.body, background=self.theme.paper)
        self._panels += [resumo, limites, diagnostico]

        self._build_perf_summary(resumo)
        self._build_perf_limits(limites)
        self._build_perf_diagnostics(diagnostico)

        self.perf_tabs.add(resumo, "Resumo")
        self.perf_tabs.add(limites, "Limites")
        self.perf_tabs.add(diagnostico, "Diagnóstico")
        self.perf_tabs.select(resumo)

        self._refresh_limits_summary()
        self.nav.add(card, "Desempenho", "chart")

    # ---------------------------------------------------------- Desempenho --
    def _build_perf_summary(self, page: tk.Frame) -> None:
        """A aba que responde "isso vai travar meu computador?"."""
        page.columnconfigure(0, weight=1)
        ttk.Label(
            page, text="Como o Lauda Local vai usar este computador", style="Section.TLabel"
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            page,
            text="Escolha um jeito de trabalhar. Cada controle continua ajustável na "
            "aba Limites.",
            style="Hint.TLabel", justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        fileira = tk.Frame(page, background=self.theme.paper)
        fileira.grid(row=2, column=0, sticky="w")
        self._panels.append(fileira)
        self.preset_buttons: dict[str, RoundedButton] = {}
        for preset in PRESETS:
            botao = RoundedButton(
                fileira, text=preset.label, font=self.font_body,
                command=self._preset_command(preset.key),
            )
            botao.pack(side="left", padx=(0, 8))
            self._buttons.append(botao)
            self.preset_buttons[preset.key] = botao

        self.preset_blurb = ttk.Label(
            page, text="", style="Hint.TLabel", wraplength=560, justify="left"
        )
        self.preset_blurb.grid(row=3, column=0, sticky="w", pady=(12, 0))

        row = self._divider(page, 4)
        ttk.Label(page, text="O que isso quer dizer agora", style="Section.TLabel").grid(
            row=row, column=0, sticky="w"
        )
        row += 1
        self.perf_plan = ttk.Label(
            page, text="", style="Hint.TLabel", wraplength=560, justify="left"
        )
        self.perf_plan.grid(row=row, column=0, sticky="w", pady=(4, 0))
        row += 1
        self.perf_need = ttk.Label(
            page, text="", style="Hint.TLabel", wraplength=560, justify="left"
        )
        self.perf_need.grid(row=row, column=0, sticky="w", pady=(8, 0))

    def _preset_command(self, key: str) -> Callable[[], None]:
        return lambda: self.apply_preset(key)

    def apply_preset(self, key: str) -> None:
        """Aplica um preset aos quatro controles de uma vez."""
        preset = preset_by_key(key)
        if preset is None:  # pragma: no cover - chave sempre vem da própria tela
            return
        for campo, valor in asdict(preset.limits).items():
            if campo in self.limit_vars:
                self.limit_vars[campo].set(valor)
                self.limit_scales[campo].set(valor)
                self._update_limit_label(campo)
        self._commit_limits()
        self._refresh_limits_summary()
        log.info("Desempenho: preset '%s' (%s).", preset.label, preset.limits.describe())

    def _build_perf_limits(self, page: tk.Frame) -> None:
        """A aba dos quatro controles finos. Mesma tela de sempre."""
        frame = page
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text="Quanto da máquina o aplicativo pode usar",
            style="Section.TLabel",
        ).grid(row=1, column=0, sticky="w")
        ttk.Label(
            frame,
            text="Diminua se quiser continuar trabalhando no computador enquanto ele "
            "processa.\nAs escolhas ficam salvas para as próximas vezes.",
            style="Hint.TLabel",
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(2, 14))

        self.limit_vars: dict[str, tk.IntVar] = {}
        self.limit_value_labels: dict[str, ttk.Label] = {}
        self.limit_scales: dict[str, RoundedSlider] = {}

        specs = [
            ("cpu_percent", "Processador (CPU)", 10,
             "Vira número de threads. Em 25%, o app usa 1/4 dos núcleos e cede "
             "prioridade para o resto do sistema."),
            ("ram_percent", "Memória (RAM)", 10,
             "Teto de memória considerado ao escolher o modelo quando roda na CPU. "
             "Modelo que não cabe é trocado por um menor."),
            ("gpu_percent", "Placa de vídeo (GPU)", 0,
             "Em 0% a placa é ignorada e tudo roda na CPU. Acima disso, controla o "
             "paralelismo na placa."),
            ("vram_percent", "Memória da placa (VRAM)", 10,
             "Teto de VRAM para escolher o modelo. É o que impede um modelo grande "
             "demais de estourar a placa."),
        ]

        row = 3
        for key, title, minimum, explanation in specs:
            holder = tk.Frame(frame, background=self.theme.paper)
            self._panels.append(holder)
            holder.grid(row=row, column=0, sticky="ew", pady=(0, 12))
            holder.columnconfigure(1, weight=1)

            ttk.Label(holder, text=title, style="Card.TLabel").grid(
                row=0, column=0, sticky="w"
            )
            value = tk.IntVar(value=getattr(self.limits, key))
            self.limit_vars[key] = value

            label = ttk.Label(holder, text="", style="Card.TLabel", width=10, anchor="e")
            label.grid(row=0, column=2, sticky="e")
            self.limit_value_labels[key] = label

            scale = RoundedSlider(
                holder, from_=minimum, to=100, command=self._slider_command(key),
                parent_bg=self.theme.paper,
            )
            scale.set(getattr(self.limits, key))
            scale.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 2))
            self.limit_scales[key] = scale

            ttk.Label(
                holder, text=explanation, style="Hint.TLabel", wraplength=520,
                justify="left",
            ).grid(row=2, column=0, columnspan=3, sticky="w")
            self._update_limit_label(key)
            row += 1

        row = self._divider(frame, row)

        ttk.Label(frame, text="Modo rápido", style="Section.TLabel").grid(
            row=row, column=0, sticky="w"
        )
        row += 1
        self.var_fast = tk.BooleanVar(value=False)
        self._switch(
            frame, row, "Transcrever em lotes (mais rápido)", self.var_fast,
            command=self._refresh_limits_summary,
        )
        row += 1
        ttk.Label(
            frame,
            text=(
                "Medimos ~2x mais rápido na placa de vídeo e ~1,3x no processador.\n"
                "Em troca, os trechos saem cerca de 6x mais longos — o que piora a\n"
                "legenda e a separação de quem fala. Deixe desligado se for legendar.\n"
                "Isto é lote de áudio dentro de UM arquivo; não tem relação com a fila\n"
                "de vários arquivos, que roda sempre um trabalho por vez."
            ),
            style="Hint.TLabel",
            justify="left",
        ).grid(row=row, column=0, sticky="w", pady=(0, 6))
        row += 1

        row = self._divider(frame, row)

        self.limits_summary = ttk.Label(
            frame, text="", style="Hint.TLabel", wraplength=520, justify="left"
        )
        self.limits_summary.grid(row=row, column=0, sticky="w")
        row += 1

        buttons = tk.Frame(frame, background=self.theme.paper)
        buttons.grid(row=row, column=0, sticky="w", pady=(12, 0))
        self._panels.append(buttons)
        botao_padrao = RoundedButton(
            buttons, text="Voltar ao padrão", command=self.reset_limits, font=self.font_body
        )
        botao_padrao.pack(side="left")
        self._buttons.append(botao_padrao)

    def _build_perf_diagnostics(self, page: tk.Frame) -> None:
        """O diagnóstico fica na tela, não escondido atrás de um botão.

        Era um diálogo que só aparecia se a máquina fosse ruim — ou seja, a
        informação existia e ninguém via. É ela que explica por que o trabalho
        está lento, e é o que eu peço quando alguém reclama.
        """
        page.columnconfigure(0, weight=1)
        ttk.Label(page, text="Este computador", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.machine_label = ttk.Label(
            page, text="Verificando…", style="Hint.TLabel", justify="left",
            wraplength=600,
        )
        self.machine_label.grid(row=1, column=0, sticky="w", pady=(4, 10))

        self.diag_rows = tk.Frame(page, background=self.theme.paper)
        self.diag_rows.grid(row=2, column=0, sticky="ew")
        self.diag_rows.columnconfigure(2, weight=1)
        self._panels.append(self.diag_rows)

        self.diag_device = ttk.Label(
            page, text="", style="Hint.TLabel", wraplength=600, justify="left"
        )
        self.diag_device.grid(row=3, column=0, sticky="w", pady=(12, 0))

        self.diag_advice = ttk.Label(
            page, text="", style="Hint.TLabel", wraplength=600, justify="left"
        )
        self.diag_advice.grid(row=4, column=0, sticky="w", pady=(8, 0))

        acoes = tk.Frame(page, background=self.theme.paper)
        acoes.grid(row=5, column=0, sticky="w", pady=(14, 0))
        self._panels.append(acoes)
        botao_reavaliar = RoundedButton(
            acoes, text="Reavaliar", command=self.check_machine, font=self.font_body
        )
        botao_reavaliar.pack(side="left")
        botao_dialogo = RoundedButton(
            acoes, text="Ver como aviso", command=self._open_machine_dialog,
            font=self.font_body,
        )
        botao_dialogo.pack(side="left", padx=(10, 0))
        self._buttons += [botao_reavaliar, botao_dialogo]

    def _refresh_diagnostics(self) -> None:
        """Redesenha a lista de achados. Chamada quando o veredito chega."""
        if not hasattr(self, "diag_rows"):
            return
        for filho in self.diag_rows.winfo_children():
            filho.destroy()
        if self.machine is None:
            return

        cores = {
            "boa": self.theme.success,
            "ok": self.theme.ink_soft,
            "apertada": self.theme.accent_warm,
            "ruim": self.theme.danger,
        }
        for linha, achado in enumerate(self.machine.findings):
            ttk.Label(
                self.diag_rows, text="●", style="Hint.TLabel",
                foreground=cores.get(achado.level, self.theme.ink_soft),
            ).grid(row=linha, column=0, sticky="w", padx=(0, 8))
            ttk.Label(self.diag_rows, text=achado.item, style="Card.TLabel").grid(
                row=linha, column=1, sticky="w", padx=(0, 14)
            )
            texto = achado.value if not achado.note else f"{achado.value} — {achado.note}"
            ttk.Label(
                self.diag_rows, text=texto, style="Hint.TLabel", wraplength=420,
                justify="left",
            ).grid(row=linha, column=2, sticky="w", pady=(0, 4))

        conselhos = "\n".join(f"• {texto}" for texto in self.machine.advice)
        self.diag_advice.configure(text=conselhos)

    def _refresh_perf(self) -> None:
        """Atualiza as três abas de Desempenho a partir do estado atual."""
        if not hasattr(self, "preset_buttons"):
            return
        self._paint_presets()

        preset = preset_for(self.limits)
        self.preset_blurb.configure(
            text=preset.blurb if preset else
            "Ajuste manual: os controles da aba Limites não batem com nenhuma das "
            "quatro opções acima."
        )

        plano, alerta = self._perf_plan_text()
        self.perf_plan.configure(text=plano)
        necessidade, aviso = self._perf_need_text()
        self.perf_need.configure(
            text=necessidade,
            foreground=self.theme.accent_warm if aviso else self.theme.ink_soft,
        )
        if hasattr(self, "diag_device"):
            self.diag_device.configure(text=alerta)

    def _paint_presets(self) -> None:
        """Destaca o preset em vigor. Nenhum aceso significa ajuste manual."""
        atual = preset_for(self.limits)
        for chave, botao in self.preset_buttons.items():
            ativo = atual is not None and atual.key == chave
            if ativo:
                self._primary_buttons.add(botao)
            else:
                self._primary_buttons.discard(botao)
            botao.apply_theme(
                fill=self.theme.primary if ativo else self.theme.button,
                hover=self.theme.primary_active if ativo else self.theme.button_active,
                foreground=self.theme.primary_text if ativo else self.theme.button_text,
                disabled_fg=self.theme.ink_soft,
                parent_bg=self.theme.paper,
            )

    def _perf_plan_text(self) -> tuple[str, str]:
        """Onde o trabalho vai rodar, em português. Devolve (resumo, detalhe)."""
        hardware = self.machine.hardware if self.machine else None
        modelo = self._selected(self.model_var, MODEL_LABELS)
        nucleos = hardware.cpu_count if hardware else (os.cpu_count() or 1)
        threads = self.limits.cpu_threads(nucleos)

        if hardware is None:
            return (
                f"Processador: {threads} de {nucleos} threads liberadas. "
                "O diagnóstico ainda está rodando.",
                "",
            )

        escolha = select_runtime(
            requested_model=modelo, hardware=hardware, limits=self.limits
        )
        if escolha.device == "cuda":
            resumo = (
                f"A transcrição vai rodar na placa de vídeo "
                f"({escolha.device_name or 'GPU'}), com o modelo {escolha.model}.\n"
                "Na placa, o medidor do processador fica quase parado — isso é o "
                "esperado, não é defeito."
            )
        else:
            resumo = (
                f"A transcrição vai rodar no processador, com {threads} de {nucleos} "
                f"threads e o modelo {escolha.model}."
            )
            if hardware.has_cuda and not self.limits.use_gpu:
                resumo += "\nA placa de vídeo está desligada nos Limites (GPU em 0%)."
            elif not hardware.has_cuda:
                resumo += "\nNenhuma placa NVIDIA compatível foi encontrada."
        detalhe = "\n".join(escolha.notes)
        return resumo, detalhe

    def _perf_need_text(self) -> tuple[str, bool]:
        """Quanto este trabalho pede e quanto os limites liberam (BACKLOG-029)."""
        hardware = self.machine.hardware if self.machine else None
        modelo = self._selected(self.model_var, MODEL_LABELS)
        pedido = recommended_for(
            modelo,
            diarize=self.var_diarize.get(),
            summarize=self.var_summarize.get(),
        )
        extras = [nota for nota in pedido.notes if "Ollama" in nota]
        rodape = ("\n" + extras[0][0].upper() + extras[0][1:] + ".") if extras else ""

        if hardware is None:
            return (
                f"Este trabalho pede cerca de {_num(pedido.ram_gb)} GB de memória."
                + rodape,
                False,
            )

        na_gpu = select_runtime(
            requested_model=modelo, hardware=hardware, limits=self.limits
        ).device == "cuda"
        if na_gpu:
            precisa, orcamento, onde = (
                pedido.vram_gb, self.limits.vram_budget_gb(hardware.gpu_vram_gb),
                "da placa de vídeo",
            )
        else:
            precisa, orcamento, onde = (
                pedido.ram_gb, self.limits.ram_budget_gb(hardware.ram_gb), "de memória"
            )

        if orcamento is None:
            return (f"Este trabalho pede cerca de {_num(precisa)} GB {onde}." + rodape,
                    False)
        if orcamento < precisa:
            return (
                f"Atenção: este trabalho pede cerca de {_num(precisa)} GB {onde} e "
                f"seus limites liberam {_num(orcamento)} GB. O modelo vai ser "
                f"rebaixado para caber — suba o controle correspondente na aba "
                f"Limites se quiser a qualidade pedida." + rodape,
                True,
            )
        return (
            f"Este trabalho pede cerca de {_num(precisa)} GB {onde}; seus limites "
            f"liberam {_num(orcamento)} GB." + rodape,
            False,
        )

    def _slider_command(self, key: str) -> Callable[[str], None]:
        """Prende o `key` no fechamento — sem isso todos os sliders usariam a
        última chave do laço."""

        def handler(raw: str) -> None:
            self._on_slider(key, raw)

        return handler

    def _on_slider(self, key: str, raw: str) -> None:
        """Arredonda para múltiplos de 5: 37% não significa nada para ninguém."""
        if self._snapping:
            return
        try:
            value = int(round(float(raw) / 5.0) * 5)
        except (TypeError, ValueError):  # pragma: no cover - Tcl manda string
            return
        minimum = 0 if key == "gpu_percent" else MIN_PERCENT
        value = max(minimum, min(MAX_PERCENT, value))
        if self.limit_vars[key].get() != value:
            self.limit_vars[key].set(value)

        # Encaixa o cursor no valor arredondado, senão o desenho diz 37 e o
        # rótulo diz 35. A trava evita que o `set` chame este método de novo.
        scale = self.limit_scales.get(key)
        if scale is not None and abs(scale.get() - value) > 0.01:
            self._snapping = True
            try:
                scale.set(value)
            finally:
                self._snapping = False

        self._update_limit_label(key)
        self._commit_limits()

    def _update_limit_label(self, key: str) -> None:
        value = self.limit_vars[key].get()
        text = "desligada" if key == "gpu_percent" and value == 0 else f"{value}%"
        self.limit_value_labels[key].configure(text=text)

    def _commit_limits(self) -> None:
        try:
            novos = ResourceLimits(**{k: v.get() for k, v in self.limit_vars.items()})
        except ValueError:  # pragma: no cover - slider já limita a faixa
            return
        if novos == self.limits:
            return
        self.limits = novos
        save_limits(novos)
        self._refresh_limits_summary()

    def _refresh_limits_summary(self) -> None:
        if not hasattr(self, "limits_summary"):
            return
        hardware = detect_hardware()
        escolha = select_runtime(
            requested_device="auto",
            requested_model=self._selected(self.model_var, MODEL_LABELS),
            hardware=hardware,
            limits=self.limits,
        )
        modo = "em lotes (rápido)" if getattr(self, "var_fast", None) and             self.var_fast.get() else "sequencial (trechos curtos)"
        linhas = [
            f"Com estes limites: {self.limits.describe()}.",
            f"O trabalho rodaria em {escolha.device} com o modelo '{escolha.model}', "
            f"transcrevendo {modo}.",
        ]
        linhas += [f"• {nota}" for nota in escolha.notes]
        self.limits_summary.configure(text="\n".join(linhas))
        self._refresh_perf()

    def reset_limits(self) -> None:
        """Volta os quatro controles ao padrão de fábrica."""
        self.limits = LIMITS_DEFAULT
        for key, variable in self.limit_vars.items():
            padrao = getattr(LIMITS_DEFAULT, key)
            variable.set(padrao)
            self.limit_scales[key].set(padrao)
            self._update_limit_label(key)
        save_limits(LIMITS_DEFAULT)
        self._refresh_limits_summary()

    # ------------------------------------------------------------- interação --
    def pick_file(self) -> None:
        audio = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
        video = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="Escolha o áudio ou vídeo (pode marcar vários)",
            filetypes=[
                ("Áudio e vídeo", f"{audio} {video}"),
                ("Vídeo", video),
                ("Áudio", audio),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not paths:
            return
        self._accept_files([Path(p) for p in paths])

    def _accept_files(self, paths: list[Path]) -> None:
        """Vários arquivos: o primeiro vai para o cartão, o resto para a fila.

        Soltar arquivo com trabalho rodando não interrompe nada — tudo entra na
        fila e espera a vez. Nunca dois processamentos ao mesmo tempo: dois
        modelos carregados brigam pela mesma memória e o resultado é a máquina
        travando, não o dobro de velocidade.
        """
        arquivos = [caminho for caminho in paths if caminho.is_file()]
        if not arquivos:
            messagebox.showwarning(APP_NAME, "Solte um arquivo de áudio ou vídeo.")
            return
        if self.worker and self.worker.is_alive():
            self.pending.extend(arquivos)
        else:
            self._accept_file(arquivos[0])
            self.pending.extend(arquivos[1:])
        self._refresh_queue_label()

    def _refresh_queue_label(self) -> None:
        """Mostra (ou esconde) a linha da fila embaixo do arquivo escolhido."""
        if not self.pending:
            self.queue_row.grid_remove()
            return
        nomes = ", ".join(caminho.name for caminho in self.pending[:3])
        if len(self.pending) > 3:
            nomes += f" e mais {len(self.pending) - 3}"
        self.queue_label.configure(
            text=f"Na fila: {len(self.pending)} arquivo(s) — {nomes}"
        )
        self.queue_row.grid(row=3, column=0, sticky="ew", pady=(10, 0))

    def clear_queue(self) -> None:
        """Descarta quem ainda não começou. O trabalho em curso continua."""
        quantos = len(self.pending)
        self.pending.clear()
        self._refresh_queue_label()
        if quantos:
            log.info("Fila esvaziada: %d arquivo(s) descartado(s).", quantos)

    def _advance_queue(self) -> None:
        """Chama o próximo da fila, se houver. Roda no fim de cada trabalho."""
        if not self.pending:
            self._batch_options = None   # a próxima rodada lê a tela de novo
            if self._batch_done:
                self.status_label.configure(
                    text=f"Fila concluída: {self._batch_done + 1} arquivos processados.",
                    foreground=self.theme.success,
                )
                log.info("Fila concluída: %d arquivos.", self._batch_done + 1)
            self._batch_done = 0
            return

        proximo = self.pending.pop(0)
        self._refresh_queue_label()
        if not proximo.exists():
            log.warning("Arquivo da fila não existe mais: %s", proximo)
            self._advance_queue()
            return

        self._batch_done += 1
        self._accept_file(proximo)
        self._queue_wait = 0
        self._start_next()

    def _start_next(self) -> None:
        """Só começa quando a thread anterior encerrar de vez."""
        if self.worker and self.worker.is_alive():
            self._queue_wait += 1
            if self._queue_wait > 40:  # 8 s: algo travou, não insistir calado
                log.warning("A thread anterior não encerrou; a fila parou aqui.")
                self.status_label.configure(
                    text="O trabalho anterior não encerrou. A fila foi interrompida.",
                    foreground=self.theme.accent_warm,
                )
                return
            self.root.after(200, self._start_next)
            return
        self.start()

    def _accept_file(self, path: Path) -> None:
        """Mostra o arquivo escolhido no cartão, com miniatura e duração."""
        self.input_path = path
        try:
            tamanho = human_size(path.stat().st_size)
        except OSError:  # pragma: no cover - arquivo sumiu entre a escolha e aqui
            tamanho = "?"

        duracao = self._probe_duration(path)
        detalhe = tamanho if duracao is None else f"{tamanho}  •  {_clock(duracao)}"
        self.file_label.configure(text=path.name)
        self.file_meta.configure(text=detalhe)
        self._thumbnail = self._grab_thumbnail(path)
        self._paint_thumb()

        self.file_divider.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        self.file_row.grid(row=2, column=0, sticky="ew")
        self.stepper.set_current(1)
        self.status_label.configure(
            text="Arquivo escolhido. Confira a pasta de saída e clique em Processar.",
            foreground=self.theme.ink_soft,
        )
        self._set_state("Pronto", self.theme.success)

    def clear_file(self) -> None:
        """Tira o arquivo escolhido e devolve a zona de soltar ao estado inicial."""
        if self.worker and self.worker.is_alive():
            return
        self.input_path = None
        self._thumbnail = None
        self.file_row.grid_remove()
        self.file_divider.grid_remove()
        self.pending.clear()
        self._refresh_queue_label()
        self.stepper.set_current(0)
        self.progress.configure(value=0)
        self.status_label.configure(
            text="Pronto para começar.", foreground=self.theme.ink_soft
        )

    def _probe_duration(self, path: Path) -> float | None:
        """Duração em segundos, pelo ffprobe. Nunca levanta exceção."""
        try:
            tools = resolve_tools()
            proc = run(
                [
                    tools.ffprobe, "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=nw=1:nk=1", str(path),
                ],
                timeout=15,
            )
            return float((proc.stdout or "").strip())
        except Exception:
            return None

    def _grab_thumbnail(self, path: Path) -> Any:
        """Um quadro do vídeo, reduzido, para o cartão do arquivo.

        Só lê o arquivo pelo ffmpeg — nada é executado. Se der qualquer
        problema (áudio puro, formato estranho, ffmpeg ausente), devolve None e
        o cartão mostra o ícone de filme.
        """
        if not _HAS_PIL:
            return None
        try:
            tools = resolve_tools()
            with tempfile.TemporaryDirectory(prefix="lauda-capa-") as tmp:
                destino = Path(tmp) / "capa.png"
                run(
                    [
                        tools.ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
                        "-ss", "1", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=104:58:force_original_aspect_ratio=increase,"
                               "crop=104:58",
                        "-y", str(destino),
                    ],
                    timeout=20,
                )
                if not destino.exists() or destino.stat().st_size == 0:
                    return None
                with Image.open(destino) as imagem:
                    return ImageTk.PhotoImage(imagem.convert("RGB"))
        except Exception as exc:
            log.debug("Sem miniatura para %s: %s", path.name, exc)
            return None

    def _paint_thumb(self) -> None:
        """Desenha a miniatura, ou o ícone de filme quando não há imagem."""
        if not hasattr(self, "thumb"):  # pragma: no cover - antes do layout
            return
        self.thumb.configure(background=self.theme.surface)
        self.thumb.delete("all")
        if self._thumbnail is not None:
            self.thumb.create_image(0, 0, image=self._thumbnail, anchor="nw")
        else:
            draw_icon(self.thumb, "film", 52, 29, 26, self.theme.ink_soft)

    def pick_folder(self) -> None:
        initial = self.folder_var.get() or str(PROJECT_ROOT)
        path = filedialog.askdirectory(
            title="Escolha a pasta onde salvar o .txt", initialdir=initial, mustexist=False
        )
        if path:
            self.folder_var.set(str(Path(path)))

    def _selected(self, variable: tk.StringVar, pairs: list[tuple[str, str]]) -> str:
        label = variable.get()
        for text, value in pairs:
            if text == label:
                return value
        return pairs[0][1]

    def _options_snapshot(self) -> dict[str, Any]:
        """Congela as escolhas da tela para este trabalho e para a fila dele."""
        return {
            "output_dir": self.folder_var.get().strip(),
            "model": self._selected(self.model_var, MODEL_LABELS),
            "language": self._selected(self.language_var, LANGUAGES),
            "diarize": self.var_diarize.get(),
            "word_timestamps": self.var_words.get(),
            "write_srt": self.var_srt.get(),
            "write_vtt": self.var_vtt.get(),
            "subtitle_density": self._selected(self.density_var, DENSITY_LABELS),
            "visual": self.var_visual.get(),
            "summarize": self.var_summarize.get(),
            "limits": self.limits,
            "batch_size": BATCH_SIZE if self.var_fast.get() else 0,
        }

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.input_path or not self.input_path.exists():
            messagebox.showwarning(
                APP_NAME, "Escolha primeiro um arquivo de áudio ou vídeo."
            )
            return

        # A fila inteira roda com as escolhas de quando o usuário clicou em
        # Processar. Sem isso, mexer num interruptor no meio de dez arquivos
        # mudaria os que ainda não começaram — e ele só descobriria no fim,
        # comparando laudos.
        if self._batch_options is None:
            self._batch_options = self._options_snapshot()
        escolhas = dict(self._batch_options)

        destination = Path(str(escolhas.pop("output_dir")) or str(PROJECT_ROOT / "saida"))
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                APP_NAME, f"Não consegui usar essa pasta:\n{destination}\n\n{exc}"
            )
            self._batch_options = None
            return

        try:
            options = JobOptions(
                input_path=self.input_path,
                output_dir=destination,
                models_dir=models_dir(),
                **escolhas,
            )
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            self._batch_options = None
            return

        self.cancel_event.clear()
        self.recovery_messages.clear()
        self.go_button.configure(state="disabled", text="Processando...")
        self.pause_event.clear()
        self._paused_at = None
        self._paused_seconds = 0.0
        self.pause_button.configure(state="normal", text="Pausar")
        self.stepper.set_current(1)
        self._set_state("Trabalhando", self.theme.accent)
        self._last_stage = None
        self._job_started = time.monotonic()
        self._eta_seconds = None
        self.nav.select(self.tab_log)
        log.info("=" * 60)
        log.info("Arquivo   : %s", options.input_path.name)
        log.info("Saída     : %s", options.output_dir)
        log.info("Modelo    : %s | idioma: %s | device: %s",
                 options.model, options.language, options.device)
        log.info("Recursos  : %s", self._enabled_features() or "nenhum")
        self.progress.configure(value=0)
        self.status_label.configure(text="Começando...", foreground=self.theme.ink_soft)

        self.worker = threading.Thread(target=self._work, args=(options,), daemon=True)
        self.worker.start()

    # ------------------------------------------------------------ thread ---- #
    def _enabled_features(self) -> str:
        """Os recursos ligados, em uma linha, para abrir o registro."""
        return ", ".join(
            rotulo
            for rotulo, variavel in (
                ("quem fala", self.var_diarize),
                ("tempo das palavras", self.var_words),
                (".srt", self.var_srt),
                (".vtt", self.var_vtt),
                ("miniaturas", self.var_visual),
                ("Ollama", self.var_summarize),
                ("lotes", self.var_fast),
            )
            if variavel.get()
        )

    def _work(self, options: JobOptions) -> None:
        """Roda no worker: nada aqui pode tocar em widget.

        O processamento em si acontece num PROCESSO separado, supervisionado:
        se ele travar, o supervisor mata e retoma do ultimo ponto salvo.
        """
        from .runner import run_with_recovery

        def report(stage: str, fraction: float, message: str) -> None:
            self.queue.put(("progress", Progress(stage, fraction, message)))

        def event(kind: str, message: str) -> None:
            self.queue.put(("recovery", (kind, message)))

        try:
            result, attempts = run_with_recovery(
                options, progress=report, on_event=event,
                cancel=self.cancel_event, pause=self.pause_event,
            )
            if len(attempts) > 1:
                result.partial_failures.append(
                    f"O processamento precisou de {len(attempts)} tentativas; "
                    "a ultima concluiu a partir do ponto salvo."
                )
            self.queue.put(("done", result))
        except LaudaError as exc:
            self.queue.put(("error", str(exc)))
        except Exception as exc:  # pragma: no cover - bug real
            self.queue.put(("error", f"{exc}\n\n{traceback.format_exc(limit=3)}"))

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self._on_progress(payload)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "recovery":
                    self._on_recovery(*payload)
                elif kind == "error":
                    self._on_error(payload)
                elif kind == "machine":
                    self._on_machine(payload)
                elif kind == "log":
                    self._append_log(payload)
                elif kind == "ollama":
                    self._on_ollama(payload)
                elif kind == "pull":
                    self._on_pull(payload)
                elif kind == "pull_done":
                    self._on_pull_done(payload)
        except queue.Empty:
            pass
        self._after_id = self.root.after(80, self._drain_queue)

    # ------------------------------------------------------------ resultados --
    def _on_progress(self, progress: Progress) -> None:
        self.progress.configure(value=progress.fraction * 100)
        label = STAGE_LABELS.get(progress.stage, progress.stage)
        if progress.stage != self._last_stage:
            # Uma linha por etapa, não por evento: o ASR reporta a cada segmento.
            self._last_stage = progress.stage
            log.info("%s...", label)
        self.stepper.set_current(STAGE_STEP.get(progress.stage, self.stepper.current))

        self._eta_seconds = self._estimate_remaining(progress.fraction)
        restante = (
            f"  ·  faltam ~{_duration_pt(self._eta_seconds)}"
            if self._eta_seconds is not None else ""
        )
        self.status_label.configure(
            text=f"{label}...  ({progress.fraction * 100:.0f}%){restante}",
            foreground=self.theme.ink_soft,
        )
        self.stepper.set_note(f"{progress.fraction * 100:.0f}%{restante}")
        self._set_state(f"{label}  {progress.fraction * 100:.0f}%", self.theme.accent)

    def _estimate_remaining(self, fraction: float) -> float | None:
        """Quanto ainda falta, em segundos, pelo ritmo medido até agora.

        Só começa a responder depois de 8% do trabalho: antes disso a conta é
        dominada pelo tempo de carregar o modelo e daria um número ridículo,
        que é pior do que não dar número nenhum.
        """
        if self._job_started is None or fraction < 0.08 or fraction >= 1.0:
            return None
        # O tempo parado nao conta: senao, pausar dez minutos faria a
        # estimativa prometer o dobro do que falta.
        decorrido = time.monotonic() - self._job_started - self._paused_seconds
        if self._paused_at is not None:
            decorrido -= time.monotonic() - self._paused_at
        if decorrido <= 0:
            return None
        return max(0.0, decorrido / fraction - decorrido)

    def _on_recovery(self, kind: str, message: str) -> None:
        """Avisos do supervisor: travou, reiniciando, desistiu, pausa_falhou."""
        if kind == "pausa_falhou":
            # A tela dizia "Pausado" e a máquina continuava a todo vapor. O
            # botão volta atrás em vez de sustentar a mentira.
            self.pause_event.clear()
            self._paused_at = None
            self.pause_button.configure(text="Pausar")
            self._set_state("Trabalhando", self.theme.accent)
            self.stepper.set_note("")
            self.status_label.configure(text=message, foreground=self.theme.accent_warm)
            log.warning("Pausa indisponivel: %s", message)
            return

        cor = self.theme.danger if kind == "desistiu" else self.theme.accent_warm
        self.status_label.configure(text=message, foreground=cor)
        self._set_state("Recuperando", cor)
        self.recovery_messages.append(message)
        log.warning("Recuperacao (%s): %s", kind, message)

    # ------------------------------------------------- avaliação da máquina --
    def check_machine(self) -> None:
        """Inspeciona o computador numa thread e devolve o veredito pela fila.

        Fora da thread da interface porque a detecção conversa com o driver de
        vídeo e com o ffmpeg — em máquina fria isso passa de um segundo, e a
        janela ficaria congelada logo ao abrir.
        """
        self._set_state("Verificando", self.theme.accent)

        def trabalho() -> None:
            try:
                resultado = assess_machine(models_dir=Path(self.folder_var.get()).parent)
            except Exception as exc:  # pragma: no cover - detecção nunca deve derrubar
                log.warning("Nao consegui avaliar a maquina: %s", exc)
                return
            self.queue.put(("machine", resultado))

        threading.Thread(target=trabalho, name="lauda-hardware", daemon=True).start()

    def _on_machine(self, check: MachineCheck) -> None:
        self.machine = check
        self._refresh_machine_summary()
        self._set_state("Pronto", self.theme.success)
        log.info("Avaliacao da maquina: %s (%s)", check.level, check.headline)
        if check.should_warn and not load_flag("skip_machine_warning"):
            self.show_machine_dialog(allow_quit=True)

    def _refresh_machine_summary(self) -> None:
        """Escreve o veredito na página Desempenho."""
        if self.machine is None or not hasattr(self, "machine_label"):
            return
        cores = {
            "boa": self.theme.success,
            "ok": self.theme.ink_soft,
            "apertada": self.theme.accent_warm,
            "ruim": self.theme.danger,
        }
        linhas = "  |  ".join(f"{a.item}: {a.value}" for a in self.machine.findings)
        self.machine_label.configure(
            text=f"{self.machine.headline}\n{linhas}",
            foreground=cores.get(self.machine.level, self.theme.ink_soft),
        )
        self._refresh_diagnostics()
        self._refresh_perf()

    def _open_machine_dialog(self) -> None:
        """Botão da página Desempenho. Existe para o callback não devolver valor."""
        self.show_machine_dialog()

    def show_machine_dialog(self, allow_quit: bool = False) -> tk.Toplevel | None:
        """Janela com o diagnóstico do computador.

        Na abertura ela oferece fechar o aplicativo; chamada pelo botão da
        página Desempenho, só informa.
        """
        if self.machine is None or self._machine_dialog is not None:
            return None
        check = self.machine
        theme = self.theme

        janela = tk.Toplevel(self.root, background=theme.canvas)
        self._machine_dialog = janela
        janela.title(f"{APP_NAME} — seu computador")
        janela.transient(self.root)
        janela.resizable(False, False)
        apply_titlebar(janela, theme.dark)

        cartao = RoundedCard(janela, padding=22, radius=16, fill=theme.paper,
                             outline=theme.line, parent_bg=theme.canvas)
        cartao.pack(fill="both", expand=True, padx=16, pady=16)
        corpo = cartao.body
        corpo.columnconfigure(0, weight=1)

        cores = {
            "boa": theme.success, "ok": theme.ink_soft,
            "apertada": theme.accent_warm, "ruim": theme.danger,
        }
        cor = cores.get(check.level, theme.ink_soft)
        linha = 0
        tk.Label(
            corpo, text=check.headline, font=self.font_title_small, wraplength=470,
            background=theme.paper, foreground=cor, anchor="w", justify="left",
        ).grid(row=linha, column=0, sticky="w")
        linha += 1

        tabela = tk.Frame(corpo, background=theme.paper)
        tabela.grid(row=linha, column=0, sticky="ew", pady=(14, 4))
        tabela.columnconfigure(1, weight=1)
        linha += 1
        for indice, achado in enumerate(check.findings):
            ponto = tk.Canvas(
                tabela, width=10, height=10, highlightthickness=0, borderwidth=0,
                background=theme.paper,
            )
            ponto.grid(row=indice * 2, column=0, sticky="w", pady=(4, 0))
            cor_item = cores.get(achado.level, theme.ink_soft)
            ponto.create_oval(1, 1, 9, 9, fill=cor_item, outline=cor_item)
            tk.Label(
                tabela, text=f"{achado.item}: {achado.value}", font=self.font_body,
                background=theme.paper, foreground=theme.ink, anchor="w",
            ).grid(row=indice * 2, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
            if achado.note:
                tk.Label(
                    tabela, text=achado.note, font=self.font_small, wraplength=440,
                    background=theme.paper, foreground=theme.ink_soft, anchor="w",
                    justify="left",
                ).grid(row=indice * 2 + 1, column=1, sticky="w", padx=(8, 0))

        for conselho in check.advice:
            tk.Label(
                corpo, text=f"•  {conselho}", font=self.font_body, wraplength=470,
                background=theme.paper, foreground=theme.ink_soft, anchor="w",
                justify="left",
            ).grid(row=linha, column=0, sticky="w", pady=(8, 0))
            linha += 1

        self.var_skip_warning = tk.BooleanVar(value=False)
        if allow_quit:
            silenciar = ToggleSwitch(
                corpo, text="Não avisar de novo neste computador",
                variable=self.var_skip_warning, font=self.font_body,
                background=theme.paper, on_color=theme.accent, off_color=theme.muted,
                knob=theme.primary_text, foreground=theme.ink,
            )
            silenciar.grid(row=linha, column=0, sticky="ew", pady=(16, 0))
            linha += 1

        botoes = tk.Frame(corpo, background=theme.paper)
        botoes.grid(row=linha, column=0, sticky="e", pady=(18, 0))

        def fechar_dialogo(sair: bool) -> None:
            if allow_quit:
                save_flag("skip_machine_warning", bool(self.var_skip_warning.get()))
            self._machine_dialog = None
            janela.grab_release()
            janela.destroy()
            if sair:
                self._on_close()

        if allow_quit:
            sair_btn = RoundedButton(
                botoes, text="Fechar o aplicativo", command=lambda: fechar_dialogo(True),
                font=self.font_body, fill=theme.button, hover=theme.button_active,
                foreground=theme.button_text, parent_bg=theme.paper,
            )
            sair_btn.pack(side="left", padx=(0, 10))

        seguir = RoundedButton(
            botoes,
            text="Continuar mesmo assim" if allow_quit else "Entendi",
            command=lambda: fechar_dialogo(False), font=self.font_bold,
            fill=theme.primary, hover=theme.primary_active,
            foreground=theme.primary_text, parent_bg=theme.paper,
        )
        seguir.pack(side="left")

        janela.protocol("WM_DELETE_WINDOW", lambda: fechar_dialogo(False))

        # O cartão é um Canvas, e Canvas não herda o tamanho do que está dentro:
        # sem medir o conteúdo, a janela abriria minúscula e cortaria o texto.
        janela.update_idletasks()
        margem_cartao, margem_janela = 22, 16
        largura = max(470, corpo.winfo_reqwidth()) + 2 * margem_cartao
        altura = corpo.winfo_reqheight() + 2 * margem_cartao
        cartao.configure(width=largura, height=altura)
        janela.geometry(f"{largura + 2 * margem_janela}x{altura + 2 * margem_janela}")
        janela.update_idletasks()
        self._center_over_root(janela)
        try:  # pragma: no cover - falha só em ambiente sem gerenciador de janelas
            janela.grab_set()
        except tk.TclError:
            pass
        return janela

    def _center_over_root(self, janela: tk.Toplevel) -> None:
        largura, altura = janela.winfo_width(), janela.winfo_height()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - largura) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - altura) // 3
        janela.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _on_tk_error(self, tipo: type, valor: BaseException, traco: Any) -> None:
        """Último anteparo: qualquer exceção solta num callback da interface."""
        log.critical("Erro na interface", exc_info=(tipo, valor, traco))
        try:
            self.status_label.configure(
                text=f"Algo falhou na tela. O detalhe foi para {LOG_PATH}.",
                foreground=self.theme.danger,
            )
            self._set_state("Erro", self.theme.danger)
        except tk.TclError:  # pragma: no cover - janela já destruída
            pass

    def _restore_if_minimized(self) -> None:
        """Traz a janela de volta se ela tiver sido minimizada durante o trabalho.

        Em algumas máquinas o Windows minimiza a janela enquanto a transcrição
        roda (o evento vem do gerenciador de janelas, não do aplicativo). Sem
        isto, o usuário volta e não encontra o resultado. Restauramos sem roubar
        o foco de quem estiver trabalhando em outra coisa.
        """
        try:
            if self.root.wm_state() == "iconic":
                self.root.deiconify()
        except tk.TclError:  # pragma: no cover - janela já destruída
            pass

    def _on_done(self, result: JobResult) -> None:
        self.result = result
        self._restore_if_minimized()
        self.progress.configure(value=100)
        self.stepper.set_current(len(PIPELINE_STEPS))
        self.stepper.set_note("")
        self._eta_seconds = None
        self.go_button.configure(state="normal", text="Processar")
        self._clear_pause()

        # Antes do bloco da página "Arquivos": é aqui que a cópia da legenda
        # ao lado do vídeo acontece, e ela precisa aparecer na lista deste
        # trabalho — não na do próximo.
        self._after_job(result)

        self._last_job_block = self._job_block(result)
        history.record(history.entry_from_result(result, self.folder_var.get()))
        self._refresh_files_page()

        # A aba deste arquivo entra e já fica selecionada em cada página; as
        # dos anteriores continuam na tela, que é o ponto de ter uma fila.
        self.page_report.rebuild(result.outputs.get("report.txt"))
        self.page_transcript.rebuild(result.outputs.get("transcript.txt"))
        self.page_subtitles.rebuild(
            result.outputs.get("srt") or result.outputs.get("vtt")
        )

        self.nav.select(self.page_report.card)
        self._set_state("Concluído", self.theme.success)

        speed = result.processing.realtime_factor or 0
        self.status_label.configure(
            text=f"Pronto! {result.stats.words} palavras em "
            f"{result.processing.elapsed_seconds:.0f} s ({_num(speed)}x tempo real).",
            foreground=self.theme.success,
        )
        if result.partial_failures:
            self.status_label.configure(
                text=self.status_label.cget("text") + "  Veja os avisos na página "
                '"Arquivos".',
                foreground=self.theme.accent_warm,
            )
        # Cobertura baixa é a única coisa que muda o que o usuário deveria fazer
        # a seguir: o texto pode estar certo e ainda faltar metade do arquivo.
        if result.coverage.gaps and (result.coverage.ratio or 1.0) < 0.95:
            faltou = result.coverage.gap_seconds
            self.status_label.configure(
                text=f"Atenção: {faltou:.0f} s do arquivo não viraram texto e não são "
                f"silêncio. Veja a cobertura no relatório.",
                foreground=self.theme.accent_warm,
            )
            log.warning("Cobertura de %.1f%% — %d trecho(s) sem texto.",
                        (result.coverage.ratio or 0) * 100, len(result.coverage.gaps))
        self._advance_queue()

    def _job_block(self, result: JobResult) -> str:
        """O resumo do trabalho recém-terminado, no topo da página "Arquivos"."""
        lines = ["ARQUIVOS GERADOS", ""]
        for kind in sorted(result.outputs):
            lines.append(f"  {kind:<16} {result.outputs[kind]}")
        for extra in self._extra_outputs:
            lines.append(f"  {'cópia':<16} {extra}")
        lines += ["", "RESUMO DO PROCESSAMENTO", ""]
        lines += [
            f"  Duração do arquivo   {_num(result.probe.duration or 0)} s",
            f"  Tempo de trabalho    {_num(result.processing.elapsed_seconds)} s "
            f"({_num(result.processing.realtime_factor or 0, 2)}x tempo real)",
            f"  Modelo               {result.processing.model} em {result.processing.device}",
            f"  Idioma               {result.language.code or '-'}",
            f"  Palavras             {result.stats.words}",
            f"  Trechos              {len(result.segments)}",
        ]
        if result.diarization.available:
            lines.append(f"  Falantes             {result.diarization.speaker_count}")
        if result.coverage.analyzed and result.coverage.ratio is not None:
            buracos = len(result.coverage.gaps)
            detalhe = (
                "nenhum trecho fora do silêncio" if not buracos
                else f"{buracos} trecho(s) sem texto, {result.coverage.gap_seconds:.0f} s"
            )
            lines.append(
                f"  Cobertura            {result.coverage.ratio * 100:.1f}%  ({detalhe})"
            )
        if result.partial_failures:
            lines += ["", "AVISOS", ""]
            lines += [f"  - {failure}" for failure in result.partial_failures]
        if self.recovery_messages:
            lines += ["", "RECUPERACAO", ""]
            lines += [f"  - {message}" for message in self.recovery_messages]
        return "\n".join(lines)

    def _copy_subtitles_beside_source(self, result: JobResult) -> list[str]:
        """Copia .srt/.vtt para a pasta do arquivo de origem.

        Copia, não move: a pasta de saída continua com o conjunto completo. Se
        a origem não aceitar escrita (pendrive protegido, pasta de rede), o
        trabalho não falha — o motivo vai para o registro e segue a vida.
        """
        if self.input_path is None:
            return []
        destino_base = self.input_path.parent
        copiados: list[str] = []
        for tipo in ("srt", "vtt"):
            origem = result.outputs.get(tipo)
            if not origem:
                continue
            caminho = Path(origem)
            alvo = destino_base / caminho.name
            if not caminho.exists() or alvo == caminho:
                continue
            try:
                shutil.copy2(caminho, alvo)
            except OSError as exc:
                log.warning("Não consegui deixar a legenda em %s: %s", destino_base, exc)
                continue
            copiados.append(str(alvo))
            log.info("Legenda também em %s", alvo)
        return copiados

    def _after_job(self, result: JobResult) -> None:
        """As preferências de pós-trabalho, todas em um lugar só."""
        if self.var_subs_beside.get():
            self._extra_outputs = self._copy_subtitles_beside_source(result)
        else:
            self._extra_outputs = []

        # Com fila, abrir a pasta a cada arquivo encheria a tela de janelas do
        # Explorador. Abre uma vez, quando o último termina.
        if self.var_open_folder.get() and not self.pending:
            destino = Path(self.folder_var.get().strip() or str(PROJECT_ROOT / "saida"))
            if destino.exists():
                self._reveal(destino)

    def _on_error(self, message: str) -> None:
        self._restore_if_minimized()
        self.progress.configure(value=0)
        self.stepper.set_note("")
        self._eta_seconds = None
        self.go_button.configure(state="normal", text="Processar")
        self._clear_pause()
        self._set_state("Erro", self.theme.danger)
        self.status_label.configure(
            text="Não deu certo. Veja a mensagem.", foreground=self.theme.danger
        )
        if self.input_path is not None:
            history.record(history.entry_from_failure(self.input_path, message))
            self._refresh_files_page()
        messagebox.showerror(APP_NAME, message)
        # Um arquivo ruim no meio de dez não pode parar os outros nove.
        self._advance_queue()

    # ----------------------------------------------------------------- ações --
    def _reveal(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:  # pragma: no cover - ambiente sem shell gráfico
            messagebox.showerror(APP_NAME, f"Não consegui abrir:\n{path}\n\n{exc}")

    # ------------------------------------------------------------- pausar --
    def _clear_pause(self) -> None:
        """Devolve o botão ao repouso quando o trabalho acaba (ou falha)."""
        self.pause_event.clear()
        self._paused_at = None
        self.pause_button.configure(state="disabled", text="Pausar")

    def toggle_pause(self) -> None:
        """Congela ou descongela o processamento em andamento.

        Pausar não é cancelar nem salvar: o processo filho fica parado onde
        está, com o modelo carregado, e volta exatamente do mesmo ponto. O
        preço é a memória, que continua ocupada. Para devolver a máquina de
        verdade, o caminho é fechar — e aí o ponto de retomada assume.
        """
        if not (self.worker and self.worker.is_alive()):
            return

        if self.pause_event.is_set():
            self.pause_event.clear()
            if self._paused_at is not None:
                self._paused_seconds += time.monotonic() - self._paused_at
                self._paused_at = None
            self.pause_button.configure(text="Pausar")
            self._set_state("Trabalhando", self.theme.accent)
            self.stepper.set_note("")
            self.status_label.configure(
                text="Retomado de onde parou.", foreground=self.theme.ink_soft
            )
            log.info("Processamento retomado pelo usuário.")
        else:
            self.pause_event.set()
            self._paused_at = time.monotonic()
            self.pause_button.configure(text="Retomar")
            self._set_state("Pausado", self.theme.accent_warm)
            self.stepper.set_note("pausado")
            self.status_label.configure(
                text="Pausado. O trabalho continua na memória e retoma do mesmo "
                "ponto — fechar o aplicativo agora perde a etapa em andamento.",
                foreground=self.theme.accent_warm,
            )
            log.info("Processamento pausado pelo usuário.")

    def _reveal_in_folder(self, path: Path) -> None:
        """Abre a pasta com o arquivo **selecionado**, pronto para copiar.

        Diferente de `_reveal`: aquele abre o arquivo no bloco de notas, este
        mostra onde ele está. É o que se quer quando o objetivo é levar o .txt
        para outro lugar.
        """
        try:
            if sys.platform == "win32":
                # O `/select,` e o caminho são UM argumento só, mas as aspas
                # ficam por dentro: `/select,"C:\\a b\\c.txt"`. Mandar a lista
                # ["explorer", "/select,C:\\a b\\c.txt"] faz o Python envolver o
                # argumento inteiro — vira `"/select,C:\\a b\\c.txt"` —, o
                # explorer não reconhece a opção, ignora o caminho e abre a
                # pasta padrão dele, Documentos. Era esse o defeito: só
                # aparecia quando a pasta de saída tinha espaço no nome, como
                # em "Lauda Local".
                #
                # Por isso a linha de comando vai montada. Não é shell: no
                # Windows uma string vai direto para o CreateProcess, sem
                # interpretar `&` ou `|`, e nome de arquivo não pode conter
                # aspas — não há o que escapar.
                # No Windows o `os.environ` põe as chaves em maiúsculas.
                raiz = os.environ.get("SYSTEMROOT", r"C:\Windows")
                explorer = Path(raiz) / "explorer.exe"
                subprocess.Popen(f'"{explorer}" /select,"{path}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                # Nem todo gerenciador de arquivos do Linux sabe selecionar.
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception as exc:  # pragma: no cover - ambiente sem shell gráfico
            messagebox.showerror(
                APP_NAME, f"Não consegui abrir a pasta de:\n{path}\n\n{exc}"
            )

    def open_folder(self) -> None:
        self._reveal(Path(self.folder_var.get()))

    def shutdown(self) -> None:
        logging.getLogger("lauda").removeHandler(self.log_handler)

        # Fechar logo depois de mexer numa opção não pode perder a escolha.
        if self._prefs_after is not None:
            try:
                self.root.after_cancel(self._prefs_after)
            except tk.TclError:  # pragma: no cover - janela já destruída
                pass
            self._save_prefs()

        """Cancela o timer da fila. Sem isso, fechar a janela deixa um
        callback pendente que estoura no interpretador Tcl."""
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:  # pragma: no cover - janela ja destruida
                pass
            self._after_id = None

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askokcancel(
                APP_NAME, "O processamento ainda está rodando. Fechar mesmo assim?"
            ):
                return
            # Avisa o supervisor para encerrar o processo filho antes de sair.
            self.cancel_event.set()
        self.shutdown()
        self.root.destroy()


def main(theme: str | None = None) -> int:
    """Ponto de entrada do aplicativo de janela (`lauda-app`).

    `theme` aceita "auto", "claro" ou "escuro"; None usa a preferência salva.
    """
    setup_logging(quiet=True)
    log_uncaught()
    log.info("Abrindo o %s %s; log em %s", APP_NAME, APP_VERSION, LOG_PATH)

    # Quem testou o programa com o nome antigo não pode perder as escolhas dele
    # só porque o produto mudou de nome.
    migrate_legacy_profile()

    if sys.platform == "win32":  # texto nítido em telas com escala
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception as exc:
            log.debug("Sem consciencia de DPI (%s); o texto pode ficar borrado.", exc)

    root = Tk()
    app = LaudaApp(root, theme_choice=theme)
    # Depois da janela aparecer: o diagnóstico não pode atrasar a abertura.
    root.after(300, app.check_machine)
    root.after(600, app.check_ollama)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
