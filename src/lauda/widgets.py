"""Widgets arredondados para a janela do aplicativo.

O ttk não desenha cantos arredondados: `Frame`, `Button` e `Progressbar` são
retangulares em qualquer tema. Aqui eles são redesenhados sobre `tk.Canvas`,
que permite qualquer forma.

Sobre a suavização das bordas: o Canvas do Tk não faz antialiasing, então um
canto arredondado desenhado por polígono fica levemente serrilhado. Quando o
**Pillow** está disponível (ele vem junto com os extras `ui` e `docs`), as
superfícies são renderizadas como imagem em 4x e reduzidas — o resultado é liso.
Sem Pillow, cai para o polígono suavizado do próprio Tk: menos bonito, mas
funcional. Nenhuma dependência nova é obrigatória por causa disto.

Os widgets aceitam `configure(state=...)`, `cget("state")` e indexação
(`widget["state"]`) como os do ttk, para não exigir tratamento especial de quem
os usa — nem dos testes.
"""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

try:  # pragma: no cover - depende do ambiente
    from PIL import Image, ImageDraw, ImageTk

    _LANCZOS = Image.Resampling.LANCZOS
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False

#: Fator de superamostragem ao desenhar com Pillow.
_SUPERSAMPLE = 4

#: A nuvem da zona de soltar é um PNG; o resto dos ícones é desenhado a traço.
CLOUD_PNG = Path(__file__).parent / "resources" / "icons" / "upload-cloud.png"


@lru_cache(maxsize=8)
def tinted_icon(path: str, size: int, color: str) -> Any:
    """Carrega um PNG e o repinta com a cor pedida, preservando a transparência.

    O arquivo entra só como forma: a cor vem sempre do tema, senão o ícone
    ficaria com o tom errado num dos dois modos. O cache guarda uma imagem por
    (tamanho, cor) — são duas na prática, uma para cada tema.
    """
    if not _HAS_PIL:  # pragma: no cover - sem Pillow
        return None
    try:
        with Image.open(path) as arquivo:
            origem = arquivo.convert("RGBA")
        origem = origem.resize((size, size), _LANCZOS)
        pintada = Image.new("RGBA", origem.size, (*_hex_to_rgb(color), 0))
        pintada.putalpha(origem.getchannel("A"))
        return ImageTk.PhotoImage(pintada)
    except Exception:  # pragma: no cover - arquivo ausente ou corrompido
        return None


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    red, green, blue = (int(color[i : i + 2], 16) for i in (0, 2, 4))
    return red, green, blue


def mix(color_a: str, color_b: str, amount: float) -> str:
    """Mistura duas cores. `amount=0` devolve a primeira, `1` a segunda."""
    red_a, green_a, blue_a = _hex_to_rgb(color_a)
    red_b, green_b, blue_b = _hex_to_rgb(color_b)
    def blend(a: int, b: int) -> int:
        return round(a + (b - a) * amount)

    return f"#{blend(red_a, red_b):02x}{blend(green_a, green_b):02x}{blend(blue_a, blue_b):02x}"


def _draw_polygon_surface(
    canvas: tk.Canvas,
    width: int,
    height: int,
    radius: int,
    fill: str,
    outline: str | None,
) -> None:
    """Desenho de emergência, sem Pillow: polígono suavizado do próprio Tk."""
    r = max(1, min(radius, width // 2, height // 2))
    points = [
        r, 0, width - r, 0, width, 0, width, r,
        width, height - r, width, height, width - r, height,
        r, height, 0, height, 0, height - r, 0, r, 0, 0,
    ]
    canvas.create_polygon(
        points,
        smooth=True,
        splinesteps=32,
        fill=fill,
        outline=outline or fill,
        width=1 if outline else 0,
        tags="surface",
    )


class RoundedSurface(tk.Canvas):
    """Base dos widgets: uma superfície arredondada que se redesenha sozinha."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        radius: int = 14,
        fill: str = "#FFFFFF",
        outline: str | None = None,
        parent_bg: str = "#FFFFFF",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            master,
            highlightthickness=0,
            borderwidth=0,
            background=parent_bg,
            **kwargs,
        )
        self._radius = radius
        self._fill = fill
        self._outline = outline
        self._parent_bg = parent_bg
        self._photo: Any = None  # a referência precisa sobreviver ao garbage collector
        self.bind("<Configure>", self._on_resize, add="+")

    # ------------------------------------------------------------- desenho --
    def _on_resize(self, _event: tk.Event) -> None:
        self.redraw()

    def set_surface(
        self, *, fill: str | None = None, outline: str | None = None,
        parent_bg: str | None = None, radius: int | None = None,
    ) -> None:
        if fill is not None:
            self._fill = fill
        if outline is not None or fill is not None:
            self._outline = outline
        if parent_bg is not None:
            self._parent_bg = parent_bg
            self.configure(background=parent_bg)
        if radius is not None:
            self._radius = radius
        self.redraw()

    def redraw(self) -> None:
        self.delete("surface")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        if width <= 1 or height <= 1:
            return

        if not _HAS_PIL:
            _draw_polygon_surface(self, width, height, self._radius, self._fill, self._outline)
            self.tag_lower("surface")
            return

        scale = _SUPERSAMPLE
        image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        drawer = ImageDraw.Draw(image)
        drawer.rounded_rectangle(
            (0, 0, width * scale - 1, height * scale - 1),
            radius=self._radius * scale,
            fill=_hex_to_rgb(self._fill),
            outline=_hex_to_rgb(self._outline) if self._outline else None,
            width=scale if self._outline else 0,
        )
        image = image.resize((width, height), _LANCZOS)

        # O Canvas não tem transparência: compomos sobre a cor do pai.
        base = Image.new("RGBA", (width, height), (*_hex_to_rgb(self._parent_bg), 255))
        base.alpha_composite(image)

        self._photo = ImageTk.PhotoImage(base.convert("RGB"))
        self.create_image(0, 0, image=self._photo, anchor="nw", tags="surface")
        self.tag_lower("surface")


class RoundedCard(RoundedSurface):
    """Painel arredondado. Coloque o conteúdo em `card.body`."""

    def __init__(
        self, master: tk.Misc, *, padding: int = 20, radius: int = 16, **kwargs: Any
    ) -> None:
        super().__init__(master, radius=radius, **kwargs)
        self._padding = padding
        self.body = tk.Frame(self, background=self._fill, highlightthickness=0, bd=0)
        self._window = self.create_window(
            padding, padding, window=self.body, anchor="nw", tags="body"
        )
        self.bind("<Configure>", self._resize_body, add="+")

    def _resize_body(self, event: tk.Event) -> None:
        self.itemconfigure(
            self._window,
            width=max(1, event.width - 2 * self._padding),
            height=max(1, event.height - 2 * self._padding),
        )

    def apply_theme(self, fill: str, outline: str | None, parent_bg: str) -> None:
        self.set_surface(fill=fill, outline=outline, parent_bg=parent_bg)
        self.body.configure(background=fill)


class RoundedButton(RoundedSurface):
    """Botão arredondado com estados de repouso, foco do mouse, clique e desabilitado."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str = "",
        command: Callable[[], None] | None = None,
        font: Any = None,
        padding: tuple[int, int] = (16, 9),
        radius: int = 11,
        fill: str = "#EDF0F5",
        hover: str = "#DFE4EC",
        foreground: str = "#12151C",
        disabled_fg: str = "#9AA3B4",
        parent_bg: str = "#FFFFFF",
        width: int | None = None,
        state: str = "normal",
        icon: str | None = None,
        **kwargs: Any,
    ) -> None:
        # `state` precisa ser NOSSO estado, não o do Canvas: o Canvas também tem
        # uma opção com esse nome, e deixar passar fazia um botão criado como
        # "disabled" nascer clicável.
        self._icon = icon
        self._text = text
        self._command = command
        self._font = font
        self._pad = padding
        self._fill_rest = fill
        self._fill_hover = hover
        self._foreground = foreground
        self._disabled_fg = disabled_fg
        self._state = state
        self._hovering = False
        self._label_id: int | None = None

        super().__init__(master, radius=radius, fill=fill, parent_bg=parent_bg, **kwargs)
        self._measure(width)

        for sequence, handler in (
            ("<Enter>", self._on_enter),
            ("<Leave>", self._on_leave),
            ("<ButtonPress-1>", self._on_press),
            ("<ButtonRelease-1>", self._on_release),
        ):
            self.bind(sequence, handler, add="+")

    # ------------------------------------------------------------ tamanho --
    def _measure(self, width: int | None = None) -> None:
        if self._font is None:
            self.configure(width=width or 120, height=34)
            return
        text_width = self._font.measure(self._text) + (22 if self._icon else 0)
        text_height = self._font.metrics("linespace")
        self.configure(
            width=width or text_width + 2 * self._pad[0],
            height=text_height + 2 * self._pad[1],
        )

    # -------------------------------------------------------------- estado --
    def _current_fill(self) -> str:
        if self._state == "disabled":
            return mix(self._fill_rest, self._parent_bg, 0.55)
        return self._fill_hover if self._hovering else self._fill_rest

    def redraw(self) -> None:
        self._fill = self._current_fill()
        super().redraw()
        self.delete("label")
        self.delete("icon")
        cor = self._disabled_fg if self._state == "disabled" else self._foreground
        largura, altura = self.winfo_width(), self.winfo_height()
        deslocamento = 11 if self._icon else 0
        self._label_id = self.create_text(
            largura / 2 + deslocamento,
            altura / 2,
            text=self._text,
            font=self._font,
            fill=cor,
            tags="label",
        )
        if self._icon:
            fim = self.bbox("label")
            esquerda = fim[0] if fim else largura / 2
            draw_icon(self, self._icon, esquerda - 13, altura / 2, 13, cor, width=1.6)

    def _on_enter(self, _event: tk.Event) -> None:
        if self._state == "normal":
            self._hovering = True
            self.configure(cursor="hand2")
            self.redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovering = False
        self.configure(cursor="")
        self.redraw()

    def _on_press(self, _event: tk.Event) -> None:
        if self._state != "normal":
            return
        self._fill = mix(self._fill_rest, "#000000", 0.12)
        RoundedSurface.redraw(self)
        self.delete("label")
        self.create_text(
            self.winfo_width() / 2, self.winfo_height() / 2 + 1,
            text=self._text, font=self._font, fill=self._foreground, tags="label",
        )

    def _on_release(self, event: tk.Event) -> None:
        if self._state != "normal":
            return
        self.redraw()
        dentro = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        if dentro and self._command is not None:
            self._command()

    # ------------------------------------------ compatibilidade com o ttk --
    def configure(self, **kwargs: Any) -> Any:  # type: ignore[override]
        redraw = False
        if "text" in kwargs:
            self._text = kwargs.pop("text")
            self._measure()
            redraw = True
        if "state" in kwargs:
            self._state = str(kwargs.pop("state"))
            self._hovering = False
            redraw = True
        if "command" in kwargs:
            self._command = kwargs.pop("command")
        result = super().configure(**kwargs) if kwargs else None
        if redraw:
            self.redraw()
        return result


    def cget(self, key: str) -> Any:
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        return super().cget(key)

    def __getitem__(self, key: str) -> Any:
        return self.cget(key)

    def apply_theme(
        self, *, fill: str, hover: str, foreground: str, disabled_fg: str, parent_bg: str
    ) -> None:
        self._fill_rest = fill
        self._fill_hover = hover
        self._foreground = foreground
        self._disabled_fg = disabled_fg
        self._parent_bg = parent_bg
        super().configure(background=parent_bg)
        self.redraw()


class RoundedProgress(RoundedSurface):
    """Barra de progresso com trilha e preenchimento arredondados."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 10,
        track: str = "#E7EAF0",
        bar: str = "#1F7A73",
        parent_bg: str = "#FFFFFF",
        maximum: float = 100.0,
        **kwargs: Any,
    ) -> None:
        self._track = track
        self._bar = bar
        self._value = 0.0
        self._maximum = maximum
        super().__init__(
            master, radius=height // 2, fill=track, parent_bg=parent_bg,
            height=height, **kwargs,
        )

    def redraw(self) -> None:
        self._fill = self._track
        super().redraw()
        self.delete("bar")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        fraction = 0.0 if self._maximum <= 0 else min(1.0, self._value / self._maximum)
        if fraction <= 0:
            return

        # Abaixo de uma bolinha o arredondamento não cabe: desenha o mínimo.
        largura = max(height, int(width * fraction))
        radius = height // 2
        if _HAS_PIL:
            scale = _SUPERSAMPLE
            image = Image.new("RGBA", (largura * scale, height * scale), (0, 0, 0, 0))
            ImageDraw.Draw(image).rounded_rectangle(
                (0, 0, largura * scale - 1, height * scale - 1),
                radius=radius * scale, fill=_hex_to_rgb(self._bar),
            )
            image = image.resize((largura, height), _LANCZOS)
            base = Image.new("RGBA", (largura, height), (*_hex_to_rgb(self._track), 255))
            base.alpha_composite(image)
            self._bar_photo = ImageTk.PhotoImage(base.convert("RGB"))
            self.create_image(0, 0, image=self._bar_photo, anchor="nw", tags="bar")
        else:  # pragma: no cover - sem Pillow
            self.create_oval(0, 0, height, height, fill=self._bar, outline=self._bar, tags="bar")
            self.create_oval(
                largura - height, 0, largura, height,
                fill=self._bar, outline=self._bar, tags="bar",
            )
            self.create_rectangle(
                radius, 0, largura - radius, height,
                fill=self._bar, outline=self._bar, tags="bar",
            )

    # ------------------------------------------ compatibilidade com o ttk --
    def configure(self, **kwargs: Any) -> Any:  # type: ignore[override]
        redraw = False
        if "value" in kwargs:
            self._value = float(kwargs.pop("value"))
            redraw = True
        if "maximum" in kwargs:
            self._maximum = float(kwargs.pop("maximum"))
            redraw = True
        result = super().configure(**kwargs) if kwargs else None
        if redraw:
            self.redraw()
        return result


    def cget(self, key: str) -> Any:
        if key == "value":
            return self._value
        if key == "maximum":
            return self._maximum
        return super().cget(key)

    def __getitem__(self, key: str) -> Any:
        return self.cget(key)

    def apply_theme(self, *, track: str, bar: str, parent_bg: str) -> None:
        self._track = track
        self._bar = bar
        self._parent_bg = parent_bg
        super().configure(background=parent_bg)
        self.redraw()


class StepBadge(RoundedSurface):
    """Selo redondo com o número do passo — o marcador visual da coluna esquerda."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        number: int,
        size: int = 26,
        fill: str = "#1F7A73",
        foreground: str = "#FFFFFF",
        parent_bg: str = "#FFFFFF",
        font: Any = None,
    ) -> None:
        self._number = number
        self._foreground = foreground
        self._font = font
        super().__init__(
            master, radius=size // 2, fill=fill, parent_bg=parent_bg,
            width=size, height=size,
        )

    def redraw(self) -> None:
        super().redraw()
        self.delete("number")
        self.create_text(
            self.winfo_width() / 2,
            self.winfo_height() / 2,
            text=str(self._number),
            fill=self._foreground,
            font=self._font,
            tags="number",
        )

    def apply_theme(self, *, fill: str, foreground: str, parent_bg: str) -> None:
        self._foreground = foreground
        self.set_surface(fill=fill, parent_bg=parent_bg)


class TabButton(RoundedSurface):
    """Aba em forma de pílula. A selecionada ganha fundo de destaque."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        command: Callable[[], None],
        font: Any = None,
        padding: tuple[int, int] = (16, 8),
        **kwargs: Any,
    ) -> None:
        self._text = text
        self._command = command
        self._font = font
        self._pad = padding
        self._selected = False
        self._hovering = False
        self._fill_on = "#E3F0EE"
        self._fill_off = "#FFFFFF"
        self._fg_on = "#1F7A73"
        self._fg_off = "#4A5163"
        super().__init__(master, radius=999, fill=self._fill_off, **kwargs)
        self._measure()
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")
        self.bind("<Button-1>", lambda _e: self._command(), add="+")

    def _measure(self) -> None:
        if self._font is None:
            self.configure(width=110, height=32)
            return
        self.configure(
            width=self._font.measure(self._text) + 2 * self._pad[0],
            height=self._font.metrics("linespace") + 2 * self._pad[1],
        )

    def _enter(self, _event: tk.Event) -> None:
        self._hovering = True
        self.configure(cursor="hand2")
        self.redraw()

    def _leave(self, _event: tk.Event) -> None:
        self._hovering = False
        self.configure(cursor="")
        self.redraw()

    def redraw(self) -> None:
        if self._selected:
            self._fill = self._fill_on
        elif self._hovering:
            self._fill = mix(self._fill_off, self._fill_on, 0.45)
        else:
            self._fill = self._fill_off
        # Raio igual à metade da altura: pílula perfeita em qualquer tamanho.
        self._radius = max(1, self.winfo_height() // 2)
        super().redraw()
        self.delete("label")
        self.create_text(
            self.winfo_width() / 2,
            self.winfo_height() / 2,
            text=self._text,
            font=self._font,
            fill=self._fg_on if self._selected else self._fg_off,
            tags="label",
        )

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.redraw()

    def apply_theme(
        self, *, fill_on: str, fill_off: str, fg_on: str, fg_off: str, parent_bg: str
    ) -> None:
        self._fill_on, self._fill_off = fill_on, fill_off
        self._fg_on, self._fg_off = fg_on, fg_off
        self._parent_bg = parent_bg
        RoundedSurface.configure(self, background=parent_bg)
        self.redraw()


class RoundedTabs(tk.Frame):
    """Abas em pílula — substitui o `ttk.Notebook`, que é sempre retangular.

    Reproduz a fatia da API do Notebook que o aplicativo usa: `add(frame, text)`
    e `select(frame)` / `select()`.
    """

    def __init__(
        self, master: tk.Misc, *, font: Any = None, background: str = "#FFFFFF"
    ) -> None:
        super().__init__(master, background=background, highlightthickness=0, bd=0)
        self._font = font
        self._background = background
        self._tabs: list[tuple[TabButton, tk.Widget]] = []
        self._current: tk.Widget | None = None

        self.bar = tk.Frame(self, background=background, highlightthickness=0)
        self.bar.pack(fill="x", padx=2, pady=(2, 10))
        self.container = tk.Frame(self, background=background, highlightthickness=0)
        self.container.pack(fill="both", expand=True)

    def add(self, frame: tk.Widget, text: str) -> None:
        botao = TabButton(
            self.bar,
            text=text.strip(),
            font=self._font,
            command=lambda: self._activate(frame),
            parent_bg=self._background,
        )
        botao.pack(side="left", padx=(0, 6))
        self._tabs.append((botao, frame))
        if self._current is None:
            self.select(frame)

    def _activate(self, frame: tk.Widget) -> None:
        """Clique numa aba. Existe para o callback não devolver valor."""
        self.select(frame)

    def select(self, frame: tk.Widget | None = None) -> str | None:
        """Sem argumento devolve o id da aba atual, como faz o Notebook."""
        if frame is None:
            return str(self._current) if self._current is not None else None
        for botao, alvo in self._tabs:
            selecionada = alvo is frame
            botao.set_selected(selecionada)
            if selecionada:
                alvo.pack(in_=self.container, fill="both", expand=True)
            else:
                alvo.pack_forget()
        self._current = frame
        return None

    def apply_theme(self, *, background: str, fill_on: str, fg_on: str, fg_off: str) -> None:
        self._background = background
        for widget in (self, self.bar, self.container):
            widget.configure(background=background)
        for botao, _ in self._tabs:
            botao.apply_theme(
                fill_on=fill_on,
                fill_off=background,
                fg_on=fg_on,
                fg_off=fg_off,
                parent_bg=background,
            )


class RoundedSlider(RoundedSurface):
    """Controle deslizante com trilha arredondada e botão redondo.

    Mantém `get()`, `set()` e o callback `command` do `ttk.Scale`, para poder
    substituí-lo sem mudar quem o usa — nem os testes.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        from_: float = 0.0,
        to: float = 100.0,
        command: Callable[[str], None] | None = None,
        track: str = "#E7EAF0",
        fill_color: str = "#1F7A73",
        knob: str = "#FFFFFF",
        parent_bg: str = "#FFFFFF",
        height: int = 22,
        **kwargs: Any,
    ) -> None:
        self._from = float(from_)
        self._to = float(to)
        self._value = self._from
        self._command = command
        self._track = track
        self._fill_color = fill_color
        self._knob = knob
        self._bar_height = 6
        self._knob_radius = 8
        super().__init__(
            master, radius=0, fill=parent_bg, parent_bg=parent_bg, height=height, **kwargs
        )
        for sequence in ("<Button-1>", "<B1-Motion>"):
            self.bind(sequence, self._on_pointer, add="+")
        self.bind("<Enter>", lambda _e: self.configure(cursor="hand2"), add="+")
        self.bind("<Leave>", lambda _e: self.configure(cursor=""), add="+")

    # ------------------------------------------------------------- desenho --
    def redraw(self) -> None:
        self.delete("all")
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        if width <= 1:
            return

        margem = self._knob_radius
        util = max(1, width - 2 * margem)
        fracao = 0.0
        if self._to > self._from:
            fracao = (self._value - self._from) / (self._to - self._from)
        fracao = min(1.0, max(0.0, fracao))

        centro = height / 2
        topo, base = centro - self._bar_height / 2, centro + self._bar_height / 2
        raio = self._bar_height / 2

        self._pill(margem, topo, width - margem, base, raio, self._track)
        if fracao > 0:
            self._pill(margem, topo, margem + util * fracao, base, raio, self._fill_color)

        x = margem + util * fracao
        self.create_oval(
            x - self._knob_radius,
            centro - self._knob_radius,
            x + self._knob_radius,
            centro + self._knob_radius,
            fill=self._knob,
            outline=self._fill_color,
            width=2,
        )

    def _pill(self, x1: float, y1: float, x2: float, y2: float, raio: float, cor: str) -> None:
        """Retângulo de pontas redondas: dois círculos e um corpo."""
        if x2 - x1 <= 2 * raio:
            self.create_oval(x1, y1, x1 + 2 * raio, y2, fill=cor, outline=cor)
            return
        self.create_oval(x1, y1, x1 + 2 * raio, y2, fill=cor, outline=cor)
        self.create_oval(x2 - 2 * raio, y1, x2, y2, fill=cor, outline=cor)
        self.create_rectangle(x1 + raio, y1, x2 - raio, y2, fill=cor, outline=cor)

    # ------------------------------------------------------------ interação --
    def _value_from_x(self, x: float) -> float:
        margem = self._knob_radius
        util = max(1, self.winfo_width() - 2 * margem)
        fracao = min(1.0, max(0.0, (x - margem) / util))
        return self._from + fracao * (self._to - self._from)

    def _on_pointer(self, event: tk.Event) -> None:
        self.set(self._value_from_x(event.x))
        if self._command is not None:
            self._command(str(self._value))

    # ------------------------------------------ compatibilidade com o ttk --
    def get(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        self._value = min(self._to, max(self._from, float(value)))
        self.redraw()

    def apply_theme(self, *, track: str, fill_color: str, knob: str, parent_bg: str) -> None:
        self._track = track
        self._fill_color = fill_color
        self._knob = knob
        self._parent_bg = parent_bg
        self._fill = parent_bg
        RoundedSurface.configure(self, background=parent_bg)
        self.redraw()


class RoundedField(RoundedSurface):
    """Moldura arredondada para campos do ttk (Entry, Combobox).

    Reimplementar um combobox — com lista suspensa, teclado e rolagem — só para
    arredondar a borda seria caro e frágil. Em vez disso, o campo do ttk fica
    sem borda dentro desta moldura, que é quem desenha o canto redondo.

    O widget hospedado é criado pelo chamador e passado em `attach`.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 32,
        radius: int = 10,
        padding: tuple[int, int] = (10, 4),
        fill: str = "#FFFFFF",
        outline: str | None = None,
        parent_bg: str = "#FFFFFF",
        icon: str | None = None,
        icon_color: str = "#4A5163",
        **kwargs: Any,
    ) -> None:
        self._pad = padding
        self._icon = icon
        self._icon_color = icon_color
        super().__init__(
            master, radius=radius, fill=fill, outline=outline,
            parent_bg=parent_bg, height=height, **kwargs,
        )
        self._inner: tk.Widget | None = None
        self._window: int | None = None
        self.bind("<Configure>", self._resize_inner, add="+")

    def attach(self, widget: tk.Widget) -> tk.Widget:
        """Coloca o campo dentro da moldura."""
        self._inner = widget
        self._window = self.create_window(
            self._pad[0] + self._icon_space(), self._pad[1], window=widget, anchor="nw"
        )
        return widget

    def _icon_space(self) -> int:
        return 26 if self._icon else 0

    def _resize_inner(self, event: tk.Event) -> None:
        if self._window is None:
            return
        self.itemconfigure(
            self._window,
            width=max(1, event.width - 2 * self._pad[0] - self._icon_space()),
            height=max(1, event.height - 2 * self._pad[1]),
        )

    def redraw(self) -> None:
        super().redraw()
        self.delete("icon")
        if self._icon:
            draw_icon(
                self, self._icon, self._pad[0] + 8, max(1, self.winfo_height()) / 2,
                15, self._icon_color, width=1.5,
            )

    def apply_theme(
        self, *, fill: str, outline: str | None, parent_bg: str,
        icon_color: str | None = None,
    ) -> None:
        if icon_color is not None:
            self._icon_color = icon_color
        self.set_surface(fill=fill, outline=outline, parent_bg=parent_bg)


class RoundedCheck(tk.Canvas):
    """Caixa de seleção com a caixinha arredondada.

    O indicador do `ttk.Checkbutton` é desenhado pelo tema e sai sempre
    quadrado — no `clam` ele vira um "x" dentro de um quadrado. Aqui a caixinha
    e o "v" são desenhados no Canvas, junto do texto.

    Mantém a fatia da API do ttk que o aplicativo usa: `variable`, `text` e
    `command`.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
        font: Any = None,
        box: int = 16,
        gap: int = 9,
        background: str = "#FFFFFF",
        fill_on: str = "#1F7A73",
        fill_off: str = "#FFFFFF",
        outline: str = "#D7DBE3",
        foreground: str = "#1B1F27",
        check: str = "#FFFFFF",
        **kwargs: Any,
    ) -> None:
        self._text = text
        self._variable = variable
        self._command = command
        self._font = font
        self._box = box
        self._gap = gap
        self._background = background
        self._fill_on = fill_on
        self._fill_off = fill_off
        self._outline = outline
        self._foreground = foreground
        self._check = check
        self._hovering = False
        self._photo: Any = None
        super().__init__(
            master,
            highlightthickness=0,
            borderwidth=0,
            background=background,
            **kwargs,
        )
        self._measure()
        self.bind("<Configure>", lambda _e: self.redraw(), add="+")
        self.bind("<Button-1>", self._toggle, add="+")
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")
        # Marcar por código repinta do mesmo jeito que o clique.
        variable.trace_add("write", lambda *_a: self.redraw())

    # ------------------------------------------------------------- desenho --
    def _measure(self) -> None:
        if self._font is None:
            self.configure(width=260, height=self._box + 6)
            return
        self.configure(
            width=self._box + self._gap + self._font.measure(self._text) + 4,
            height=max(self._box, self._font.metrics("linespace")) + 6,
        )

    def redraw(self) -> None:
        self.delete("all")
        height = max(1, self.winfo_height())
        if height <= 1:
            return
        topo = (height - self._box) / 2
        marcada = bool(self._variable.get())
        fill = self._fill_on if marcada else self._fill_off
        outline = self._fill_on if marcada else self._outline
        if self._hovering and not marcada:
            outline = mix(self._outline, self._fill_on, 0.6)

        self._draw_box(topo, fill, outline)
        if marcada:
            # Um "v" simples: duas linhas, mais leve que uma fonte de ícones.
            self.create_line(
                [
                    (self._box * 0.26, topo + self._box * 0.52),
                    (self._box * 0.44, topo + self._box * 0.70),
                    (self._box * 0.76, topo + self._box * 0.30),
                ],
                fill=self._check, width=2, capstyle="round", joinstyle="round",
            )
        self.create_text(
            self._box + self._gap,
            height / 2,
            text=self._text,
            font=self._font,
            fill=self._foreground,
            anchor="w",
        )

    def _draw_box(self, topo: float, fill: str, outline: str) -> None:
        radius = 5
        if not _HAS_PIL:  # pragma: no cover - sem Pillow
            self.create_rectangle(
                0, topo, self._box, topo + self._box,
                fill=fill, outline=outline, width=1,
            )
            return
        scale = _SUPERSAMPLE
        lado = self._box * scale
        image = Image.new("RGBA", (lado, lado), (*_hex_to_rgb(self._background), 255))
        ImageDraw.Draw(image).rounded_rectangle(
            (0, 0, lado - 1, lado - 1),
            radius=radius * scale,
            fill=_hex_to_rgb(fill),
            outline=_hex_to_rgb(outline),
            width=scale,
        )
        self._photo = ImageTk.PhotoImage(
            image.resize((self._box, self._box), _LANCZOS).convert("RGB")
        )
        self.create_image(0, topo, image=self._photo, anchor="nw")

    # ----------------------------------------------------------- interação --
    def _toggle(self, _event: tk.Event) -> None:
        self._variable.set(not self._variable.get())
        if self._command is not None:
            self._command()

    def _enter(self, _event: tk.Event) -> None:
        self._hovering = True
        self.configure(cursor="hand2")
        self.redraw()

    def _leave(self, _event: tk.Event) -> None:
        self._hovering = False
        self.configure(cursor="")
        self.redraw()

    def apply_theme(
        self, *, background: str, fill_on: str, fill_off: str, outline: str,
        foreground: str, check: str,
    ) -> None:
        self._background = background
        self._fill_on, self._fill_off = fill_on, fill_off
        self._outline, self._foreground, self._check = outline, foreground, check
        tk.Canvas.configure(self, background=background)
        self.redraw()


class RoundedScrollbar(tk.Canvas):
    """Barra de rolagem fina, com o cursor arredondado e sem setas.

    A `ttk.Scrollbar` traz setas e um cursor quadrado que o tema `clam` não
    arredonda. Esta versão implementa o protocolo do Tk (`set` como
    `yscrollcommand` e chamadas `moveto` no `command`), então entra no lugar da
    original sem mudar o `Text`.

    Quando tudo já cabe na tela o cursor some, e a barra fica invisível.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        orient: str = "vertical",
        command: Callable[..., Any] | None = None,
        thickness: int = 10,
        thumb: str = "#C6CCD8",
        background: str = "#FFFFFF",
        **kwargs: Any,
    ) -> None:
        self._orient = orient
        self._command = command
        self._thumb_color = thumb
        self._background = background
        self._first, self._last = 0.0, 1.0
        self._hovering = False
        self._drag_offset: float | None = None
        super().__init__(
            master,
            highlightthickness=0,
            borderwidth=0,
            background=background,
            **kwargs,
        )
        # A espessura é fixa; o comprimento vem do `grid`.
        if orient == "vertical":
            tk.Canvas.configure(self, width=thickness)
        else:
            tk.Canvas.configure(self, height=thickness)
        self.bind("<Configure>", lambda _e: self.redraw(), add="+")
        self.bind("<Button-1>", self._press, add="+")
        self.bind("<B1-Motion>", self._drag, add="+")
        self.bind("<ButtonRelease-1>", self._release, add="+")
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")

    # ------------------------------------------------ protocolo do scroll --
    def set(self, first: float | str, last: float | str) -> None:
        self._first, self._last = float(first), float(last)
        self.redraw()

    def get(self) -> tuple[float, float]:
        return self._first, self._last

    # ------------------------------------------------------------- desenho --
    def _extent(self) -> int:
        return max(1, self.winfo_height() if self._orient == "vertical" else self.winfo_width())

    def redraw(self) -> None:
        self.delete("all")
        comprimento = self._extent()
        if comprimento <= 1 or self._last - self._first >= 1.0:
            return

        espessura = max(
            1, self.winfo_width() if self._orient == "vertical" else self.winfo_height()
        )
        margem = 2.0
        raio = max(1.0, (espessura - 2 * margem) / 2)
        inicio = self._first * comprimento
        fim = max(inicio + 2 * raio + 1, self._last * comprimento)
        cor = mix(self._thumb_color, self._background, 0.0 if self._hovering else 0.35)

        if self._orient == "vertical":
            self._pill(margem, inicio, espessura - margem, fim, raio)
        else:
            self._pill(inicio, margem, fim, espessura - margem, raio)
        self.itemconfigure("thumb", fill=cor, outline=cor)

    def _pill(self, x1: float, y1: float, x2: float, y2: float, raio: float) -> None:
        """Retângulo de pontas redondas, no sentido da barra."""
        if self._orient == "vertical":
            self.create_oval(x1, y1, x2, y1 + 2 * raio, tags="thumb")
            self.create_oval(x1, y2 - 2 * raio, x2, y2, tags="thumb")
            self.create_rectangle(x1, y1 + raio, x2, y2 - raio, tags="thumb")
        else:
            self.create_oval(x1, y1, x1 + 2 * raio, y2, tags="thumb")
            self.create_oval(x2 - 2 * raio, y1, x2, y2, tags="thumb")
            self.create_rectangle(x1 + raio, y1, x2 - raio, y2, tags="thumb")

    # ----------------------------------------------------------- interação --
    def _position(self, event: tk.Event) -> float:
        return float(event.y if self._orient == "vertical" else event.x)

    def _moveto(self, fracao: float) -> None:
        if self._command is None:
            return
        janela = self._last - self._first
        limite = max(0.0, 1.0 - janela)
        self._command("moveto", min(limite, max(0.0, fracao)))

    def _press(self, event: tk.Event) -> None:
        posicao = self._position(event) / self._extent()
        if self._first <= posicao <= self._last:
            # Clique sobre o cursor: arrasta mantendo o ponto onde pegou.
            self._drag_offset = posicao - self._first
            return
        # Clique na trilha: leva o centro do cursor até ali.
        self._drag_offset = (self._last - self._first) / 2
        self._moveto(posicao - self._drag_offset)

    def _drag(self, event: tk.Event) -> None:
        if self._drag_offset is None:
            return
        self._moveto(self._position(event) / self._extent() - self._drag_offset)

    def _release(self, _event: tk.Event) -> None:
        self._drag_offset = None

    def _enter(self, _event: tk.Event) -> None:
        self._hovering = True
        self.redraw()

    def _leave(self, _event: tk.Event) -> None:
        self._hovering = False
        self.redraw()

    def apply_theme(self, *, thumb: str, background: str) -> None:
        self._thumb_color = thumb
        self._background = background
        tk.Canvas.configure(self, background=background)
        self.redraw()


# --------------------------------------------------------------------------- #
# Ícones
# --------------------------------------------------------------------------- #
def draw_icon(
    canvas: tk.Canvas,
    name: str,
    cx: float,
    cy: float,
    size: float,
    color: str,
    *,
    width: float = 1.8,
    tags: str = "icon",
) -> None:
    """Desenha um ícone de traço centrado em (cx, cy), dentro de um quadrado `size`.

    São desenhados à mão, com linhas e arcos, em vez de virem de uma fonte de
    ícones ou de arquivos PNG: assim acompanham a cor do tema sem precisar de
    duas cópias de cada imagem, e não entra nenhum arquivo novo no pacote.
    """
    r = size / 2
    left, top, right, bottom = cx - r, cy - r, cx + r, cy + r

    def line(*points: tuple[float, float], **kwargs: Any) -> None:
        kwargs.setdefault("width", width)
        canvas.create_line(
            list(points), fill=color, capstyle="round",
            joinstyle="round", tags=tags, **kwargs,
        )

    def oval(x1: float, y1: float, x2: float, y2: float, **kwargs: Any) -> None:
        canvas.create_oval(
            x1, y1, x2, y2, outline=color, width=width, tags=tags, **kwargs
        )

    if name == "plus":
        line((cx, top), (cx, bottom))
        line((left, cy), (right, cy))

    elif name == "doc":
        dobra = size * 0.34
        line(
            (left + r * 0.15, top), (right - r * 0.15 - dobra, top),
            (right - r * 0.15, top + dobra), (right - r * 0.15, bottom),
            (left + r * 0.15, bottom), (left + r * 0.15, top),
        )
        line((right - r * 0.15 - dobra, top), (right - r * 0.15 - dobra, top + dobra),
             (right - r * 0.15, top + dobra))

    elif name == "transcript":  # círculo com seta para baixo
        oval(left, top, right, bottom)
        line((cx, cy - r * 0.45), (cx, cy + r * 0.4))
        line((cx - r * 0.32, cy + r * 0.08), (cx, cy + r * 0.4), (cx + r * 0.32, cy + r * 0.08))

    elif name == "folder":
        aba = size * 0.22
        line(
            (left, bottom - size * 0.05), (left, top + aba * 0.6),
            (left + size * 0.38, top + aba * 0.6), (left + size * 0.5, top + aba * 1.5),
            (right, top + aba * 1.5), (right, bottom - size * 0.05),
            (left, bottom - size * 0.05),
        )

    elif name == "chart":
        base = bottom - size * 0.06
        for indice, altura in enumerate((0.42, 0.72, 0.55)):
            x = left + size * (0.2 + indice * 0.3)
            line((x, base), (x, base - size * altura))

    elif name == "gear":
        # Silhueta fechada com seis dentes. Raios soltos em volta de um círculo
        # viram um sol, não uma engrenagem.
        dentes, raio_interno = 6, r * 0.74
        pontos: list[tuple[float, float]] = []
        for indice in range(dentes):
            base = 2 * math.pi * indice / dentes
            for angulo, raio in (
                (base - 0.30, raio_interno), (base - 0.17, r),
                (base + 0.17, r), (base + 0.30, raio_interno),
            ):
                pontos.append((cx + math.cos(angulo) * raio, cy + math.sin(angulo) * raio))
        canvas.create_polygon(
            pontos, fill="", outline=color, width=width, joinstyle="round", tags=tags
        )
        oval(cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3)

    elif name == "globe":
        oval(left, top, right, bottom)
        line((left, cy), (right, cy))
        canvas.create_arc(
            cx - r * 0.5, top, cx + r * 0.5, bottom, start=90, extent=180,
            style="arc", outline=color, width=width, tags=tags,
        )
        canvas.create_arc(
            cx - r * 0.5, top, cx + r * 0.5, bottom, start=270, extent=180,
            style="arc", outline=color, width=width, tags=tags,
        )

    elif name == "sliders":
        for indice, fracao in enumerate((0.35, 0.62)):
            y = top + size * (0.3 + indice * 0.4)
            line((left, y), (right, y))
            x = left + size * fracao
            canvas.create_oval(
                x - width * 1.6, y - width * 1.6, x + width * 1.6, y + width * 1.6,
                fill=color, outline=color, tags=tags,
            )

    elif name == "play":
        canvas.create_polygon(
            [(left + size * 0.22, top), (right, cy), (left + size * 0.22, bottom)],
            fill=color, outline=color, tags=tags,
        )

    elif name == "check":
        line((left + size * 0.12, cy), (cx - size * 0.04, bottom - size * 0.16),
             (right - size * 0.1, top + size * 0.18))

    elif name == "close":
        line((left, top), (right, bottom))
        line((right, top), (left, bottom))

    elif name == "film":
        canvas.create_rectangle(
            left, top + size * 0.1, right, bottom - size * 0.1,
            outline=color, width=width, tags=tags,
        )
        for indice in range(3):
            y = top + size * (0.26 + indice * 0.24)
            line((left, y), (left + size * 0.16, y))
            line((right - size * 0.16, y), (right, y))

    elif name == "help":
        oval(left, top, right, bottom)
        # O ponto de interrogação sai melhor como texto do que como traço: em
        # 20 px o desenho vira um rabisco.
        canvas.create_text(
            cx, cy, text="?", fill=color, tags=tags,
            font=("Segoe UI", max(7, int(size * 0.62)), "bold"),
        )

    elif name == "cloud":
        # Contorno único e fechado: arcos sobrepostos deixariam riscos por dentro.
        contorno = [
            (-0.46, 0.26), (-0.46, 0.08), (-0.38, -0.04), (-0.24, -0.08),
            (-0.18, -0.24), (0.00, -0.30), (0.18, -0.22), (0.26, -0.06),
            (0.40, 0.00), (0.46, 0.14), (0.42, 0.26),
        ]
        canvas.create_polygon(
            [(cx + px * size, cy + py * size) for px, py in contorno],
            smooth=True, splinesteps=24, fill="", outline=color, width=width,
            dash=(5, 4), tags=tags,
        )

    else:  # pragma: no cover - nome desconhecido vira um ponto discreto
        canvas.create_oval(
            cx - 2, cy - 2, cx + 2, cy + 2, fill=color, outline=color, tags=tags
        )


def draw_dashed_round_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    color: str,
    *,
    width: float = 1.6,
    dash: tuple[int, int] = (6, 5),
    tags: str = "dashed",
) -> None:
    """Contorno tracejado de cantos redondos: quatro retas e quatro arcos.

    O `create_polygon` do Tk não aceita tracejado, então a borda é montada em
    pedaços — é o que permite a zona de soltar arquivo ter o visual de recorte.
    """
    r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    for pontos in (
        [(x1 + r, y1), (x2 - r, y1)],
        [(x1 + r, y2), (x2 - r, y2)],
        [(x1, y1 + r), (x1, y2 - r)],
        [(x2, y1 + r), (x2, y2 - r)],
    ):
        canvas.create_line(
            pontos, fill=color, width=width, dash=dash, tags=tags, capstyle="round"
        )
    for cx, cy, start in (
        (x1 + r, y1 + r, 90), (x2 - r, y1 + r, 0),
        (x2 - r, y2 - r, 270), (x1 + r, y2 - r, 180),
    ):
        canvas.create_arc(
            cx - r, cy - r, cx + r, cy + r, start=start, extent=90, style="arc",
            outline=color, width=width, dash=dash, tags=tags,
        )


# --------------------------------------------------------------------------- #
# Navegação lateral
# --------------------------------------------------------------------------- #
class NavItem(RoundedSurface):
    """Item da barra lateral: ícone em cima, rótulo embaixo."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        icon: str,
        command: Callable[[], None],
        font: Any = None,
        width: int = 132,
        height: int = 74,
        parent_bg: str = "#F4F6FA",
        **kwargs: Any,
    ) -> None:
        self._text = text
        self._icon = icon
        self._command = command
        self._font = font
        self._selected = False
        self._hovering = False
        self._fill_on = "#FFFFFF"
        self._fg_on = "#1F7A73"
        self._fg_off = "#4A5163"
        super().__init__(
            master, radius=12, fill=parent_bg, parent_bg=parent_bg,
            width=width, height=height, **kwargs,
        )
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")
        self.bind("<Button-1>", lambda _e: self._command(), add="+")

    def _enter(self, _event: tk.Event) -> None:
        self._hovering = True
        self.configure(cursor="hand2")
        self.redraw()

    def _leave(self, _event: tk.Event) -> None:
        self._hovering = False
        self.configure(cursor="")
        self.redraw()

    def redraw(self) -> None:
        if self._selected:
            self._fill = self._fill_on
            self._outline = self._fg_on
        elif self._hovering:
            self._fill = mix(self._parent_bg, self._fill_on, 0.5)
            self._outline = None
        else:
            self._fill = self._parent_bg
            self._outline = None
        super().redraw()

        self.delete("icon")
        self.delete("label")
        largura, altura = max(1, self.winfo_width()), max(1, self.winfo_height())
        cor = self._fg_on if self._selected else self._fg_off
        draw_icon(self, self._icon, largura / 2, altura * 0.36, 20, cor)
        self.create_text(
            largura / 2, altura * 0.75, text=self._text, font=self._font,
            fill=cor, tags="label",
        )

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.redraw()

    def apply_theme(
        self, *, fill_on: str, fg_on: str, fg_off: str, parent_bg: str
    ) -> None:
        self._fill_on, self._fg_on, self._fg_off = fill_on, fg_on, fg_off
        self._parent_bg = parent_bg
        RoundedSurface.configure(self, background=parent_bg)
        self.redraw()


class SideNav(tk.Frame):
    """Barra lateral de navegação. Troca páginas como o `RoundedTabs` troca abas.

    Mantém a mesma API do `RoundedTabs` (`add` e `select`) para que a janela não
    precise saber qual dos dois está em uso.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        font: Any = None,
        background: str = "#EDF0F5",
        width: int = 152,
    ) -> None:
        super().__init__(master, background=background, highlightthickness=0, bd=0,
                         width=width)
        self.pack_propagate(False)
        self._font = font
        self._background = background
        self._items: list[tuple[NavItem, tk.Widget]] = []
        self._current: tk.Widget | None = None
        #: Chamado com a página que acabou de aparecer.
        self.on_change: Callable[[tk.Widget], None] | None = None

        self.top = tk.Frame(self, background=background, highlightthickness=0)
        self.top.pack(side="top", fill="x", padx=10, pady=(12, 0))
        self.bottom = tk.Frame(self, background=background, highlightthickness=0)
        self.bottom.pack(side="bottom", fill="x", padx=10, pady=(0, 14))

    def _activate(self, frame: tk.Widget) -> None:
        """Clique num item. Existe para o callback não devolver valor."""
        self.select(frame)

    def add(self, frame: tk.Widget, text: str, icon: str = "doc") -> None:
        item = NavItem(
            self.top, text=text, icon=icon, font=self._font,
            command=lambda: self._activate(frame), parent_bg=self._background,
        )
        item.pack(fill="x", pady=(0, 4))
        self._items.append((item, frame))
        if self._current is None:
            self.select(frame)

    def select(self, frame: tk.Widget | None = None) -> str | None:
        """Sem argumento devolve o id da página atual."""
        if frame is None:
            return str(self._current) if self._current is not None else None
        for item, alvo in self._items:
            selecionado = alvo is frame
            item.set_selected(selecionado)
            if selecionado:
                alvo.pack(fill="both", expand=True)
            else:
                alvo.pack_forget()
        anterior, self._current = self._current, frame
        # Quem abre uma página espera vê-la atualizada. Sem este aviso, a
        # página só se atualizaria ao ser construída.
        if self.on_change is not None and anterior is not frame:
            self.on_change(frame)
        return None

    def apply_theme(
        self, *, background: str, fill_on: str, fg_on: str, fg_off: str
    ) -> None:
        self._background = background
        for widget in (self, self.top, self.bottom):
            widget.configure(background=background)
        for item, _ in self._items:
            item.apply_theme(
                fill_on=fill_on, fg_on=fg_on, fg_off=fg_off, parent_bg=background
            )


# --------------------------------------------------------------------------- #
# Controles
# --------------------------------------------------------------------------- #
class ToggleSwitch(tk.Canvas):
    """Interruptor deslizante com rótulo à esquerda.

    Ocupa a linha inteira: o texto fica encostado à esquerda e o interruptor no
    canto direito, como num painel de preferências. Aceita `variable`, `text` e
    `command`, como o `ttk.Checkbutton` que ele substitui.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        text: str,
        variable: tk.BooleanVar,
        command: Callable[[], None] | None = None,
        font: Any = None,
        height: int = 34,
        track_width: int = 40,
        background: str = "#FFFFFF",
        on_color: str = "#1F7A73",
        off_color: str = "#BFC7D4",
        knob: str = "#FFFFFF",
        foreground: str = "#12151C",
        **kwargs: Any,
    ) -> None:
        self._text = text
        self._variable = variable
        self._command = command
        self._font = font
        self._track_width = track_width
        self._background = background
        self._on_color = on_color
        self._off_color = off_color
        self._knob = knob
        self._foreground = foreground
        self._hovering = False
        super().__init__(
            master, highlightthickness=0, borderwidth=0, background=background,
            height=height, **kwargs,
        )
        self.bind("<Configure>", lambda _e: self.redraw(), add="+")
        self.bind("<Button-1>", self._toggle, add="+")
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")
        variable.trace_add("write", lambda *_a: self.redraw())

    def redraw(self) -> None:
        self.delete("all")
        largura, altura = max(1, self.winfo_width()), max(1, self.winfo_height())
        if largura <= 1:
            return
        ligado = bool(self._variable.get())

        self.create_text(
            0, altura / 2, text=self._text, font=self._font,
            fill=self._foreground, anchor="w",
        )

        alto = 20
        topo = (altura - alto) / 2
        direita = largura
        esquerda = direita - self._track_width
        raio = alto / 2
        cor = self._on_color if ligado else self._off_color
        if self._hovering:
            cor = mix(cor, self._foreground, 0.12)
        self.create_oval(esquerda, topo, esquerda + alto, topo + alto, fill=cor, outline=cor)
        self.create_oval(direita - alto, topo, direita, topo + alto, fill=cor, outline=cor)
        self.create_rectangle(
            esquerda + raio, topo, direita - raio, topo + alto, fill=cor, outline=cor
        )

        centro = (direita - raio - 1) if ligado else (esquerda + raio + 1)
        bolinha = raio - 3
        self.create_oval(
            centro - bolinha, altura / 2 - bolinha, centro + bolinha, altura / 2 + bolinha,
            fill=self._knob, outline=self._knob,
        )

    def _toggle(self, _event: tk.Event) -> None:
        self._variable.set(not self._variable.get())
        if self._command is not None:
            self._command()

    def _enter(self, _event: tk.Event) -> None:
        self._hovering = True
        self.configure(cursor="hand2")
        self.redraw()

    def _leave(self, _event: tk.Event) -> None:
        self._hovering = False
        self.configure(cursor="")
        self.redraw()

    def apply_theme(
        self, *, background: str, on_color: str, off_color: str, knob: str,
        foreground: str,
    ) -> None:
        self._background = background
        self._on_color, self._off_color = on_color, off_color
        self._knob, self._foreground = knob, foreground
        tk.Canvas.configure(self, background=background)
        self.redraw()


class DropZone(RoundedSurface):
    """Área grande de soltar/escolher arquivo, com contorno tracejado.

    O arrastar-e-soltar depende do `tkinterdnd2` (extra `ui`). Sem ele a área
    continua funcionando pelo clique, e o texto muda para não prometer o que
    não faz.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        command: Callable[[], None],
        title: str,
        subtitle: str,
        hint: str,
        font_title: Any = None,
        font_body: Any = None,
        font_small: Any = None,
        accent: str = "#1F7A73",
        ink: str = "#12151C",
        ink_soft: str = "#4A5163",
        **kwargs: Any,
    ) -> None:
        self._command = command
        self._title = title
        self._subtitle = subtitle
        self._hint = hint
        self._font_title = font_title
        self._font_body = font_body
        self._font_small = font_small
        self._accent = accent
        self._ink = ink
        self._ink_soft = ink_soft
        self._active = False
        self._cloud: Any = None  # a referência precisa sobreviver ao coletor
        super().__init__(master, radius=14, **kwargs)
        self.bind("<Button-1>", lambda _e: self._command(), add="+")
        self.bind("<Enter>", self._enter, add="+")
        self.bind("<Leave>", self._leave, add="+")

    def _enter(self, _event: tk.Event) -> None:
        self.configure(cursor="hand2")

    def _leave(self, _event: tk.Event) -> None:
        self.configure(cursor="")

    def set_active(self, active: bool) -> None:
        """Realce enquanto um arquivo está sendo arrastado por cima."""
        self._active = active
        self.redraw()

    def redraw(self) -> None:
        super().redraw()
        self.delete("conteudo")
        largura, altura = max(1, self.winfo_width()), max(1, self.winfo_height())
        if largura <= 1 or altura <= 1:
            return

        cor_traco = self._accent if self._active else mix(self._accent, self._ink_soft, 0.45)
        meio = largura / 2

        # O bloco inteiro — moldura tracejada e três linhas de texto — fica
        # centrado no espaço disponível, seja ele qual for.
        caixa_w, caixa_h = 132.0, 92.0
        alturas = (30.0, 27.0, 32.0)
        topo = max(8.0, (altura - (caixa_h + sum(alturas))) / 2)

        draw_dashed_round_rect(
            self, meio - caixa_w / 2, topo, meio + caixa_w / 2, topo + caixa_h,
            18, cor_traco, tags="conteudo",
        )
        icone_y = topo + caixa_h / 2
        self._cloud = tinted_icon(str(CLOUD_PNG), 74, cor_traco)
        if self._cloud is not None:
            self.create_image(meio, icone_y, image=self._cloud, tags="conteudo")
        else:  # pragma: no cover - sem Pillow ou sem o arquivo
            draw_icon(self, "cloud", meio, icone_y, 52, cor_traco, width=2.0,
                      tags="conteudo")
            self.create_line(
                [(meio, icone_y + 4), (meio, icone_y - 22)],
                fill=cor_traco, width=2.0, capstyle="round", tags="conteudo",
            )
            self.create_line(
                [(meio - 8, icone_y - 14), (meio, icone_y - 23), (meio + 8, icone_y - 14)],
                fill=cor_traco, width=2.0, capstyle="round", joinstyle="round",
                tags="conteudo",
            )

        y = topo + caixa_h
        for texto, fonte, cor, avanco in (
            (self._title, self._font_title, self._ink, alturas[0]),
            (self._subtitle, self._font_body, self._ink_soft, alturas[1]),
            (self._hint, self._font_small, self._ink_soft, alturas[2]),
        ):
            y += avanco
            self.create_text(
                meio, y, text=texto, font=fonte, fill=cor, tags="conteudo"
            )

    def apply_theme(
        self, *, fill: str, outline: str | None, parent_bg: str, accent: str,
        ink: str, ink_soft: str,
    ) -> None:
        self._accent, self._ink, self._ink_soft = accent, ink, ink_soft
        self.set_surface(fill=fill, outline=outline, parent_bg=parent_bg)

    def set_texts(self, *, title: str, subtitle: str, hint: str) -> None:
        self._title, self._subtitle, self._hint = title, subtitle, hint
        self.redraw()


class Stepper(tk.Canvas):
    """Trilha de etapas: círculos ligados por linhas, da esquerda para a direita.

    Etapa cumprida ganha um "v" e a linha cheia; a atual, um anel destacado; as
    seguintes ficam apagadas com a linha tracejada.
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        steps: list[str],
        font: Any = None,
        height: int = 66,
        background: str = "#FFFFFF",
        accent: str = "#1F7A73",
        muted: str = "#BFC7D4",
        ink: str = "#12151C",
        ink_soft: str = "#4A5163",
        on_check: str = "#FFFFFF",
        **kwargs: Any,
    ) -> None:
        self._steps = steps
        self._font = font
        self._background = background
        self._accent = accent
        self._muted = muted
        self._ink = ink
        self._ink_soft = ink_soft
        self._on_check = on_check
        self._current = 0
        self._note = ""
        super().__init__(
            master, highlightthickness=0, borderwidth=0, background=background,
            height=height, **kwargs,
        )
        self.bind("<Configure>", lambda _e: self.redraw(), add="+")

    @property
    def current(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        """`index` é a etapa em andamento; as anteriores contam como cumpridas."""
        self._current = max(0, min(len(self._steps), index))
        self.redraw()

    def set_note(self, note: str) -> None:
        """Texto pequeno sob a etapa atual: porcentagem, tempo restante."""
        if note == self._note:
            return
        self._note = note
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        largura = max(1, self.winfo_width())
        if largura <= 1 or len(self._steps) < 2:
            return

        raio = 11.0
        topo = 16.0
        # A margem cabe o rótulo mais largo: sem isso o primeiro e o último saem
        # cortados nas pontas.
        meia_etiqueta = 40.0
        if self._font is not None:
            meia_etiqueta = max(self._font.measure(t) for t in self._steps) / 2
        margem = max(raio + 6, meia_etiqueta)
        passo = max(1.0, (largura - 2 * margem) / (len(self._steps) - 1))
        centros = [margem + passo * indice for indice in range(len(self._steps))]

        for indice in range(len(self._steps) - 1):
            cumprida = indice < self._current
            self.create_line(
                [(centros[indice] + raio + 4, topo), (centros[indice + 1] - raio - 4, topo)],
                fill=self._accent if cumprida else self._muted,
                width=2,
                dash=() if cumprida else (4, 4),
            )

        for indice, rotulo in enumerate(self._steps):
            x = centros[indice]
            cumprida = indice < self._current
            atual = indice == self._current
            if cumprida:
                self.create_oval(
                    x - raio, topo - raio, x + raio, topo + raio,
                    fill=self._accent, outline=self._accent,
                )
                draw_icon(self, "check", x, topo, 11, self._on_check, width=2.0)
            else:
                cor = self._accent if atual else self._muted
                self.create_oval(
                    x - raio, topo - raio, x + raio, topo + raio,
                    outline=cor, width=2, fill=self._background,
                )
                if atual:
                    self.create_oval(
                        x - 4, topo - 4, x + 4, topo + 4, fill=cor, outline=cor
                    )
            self.create_text(
                x, topo + raio + 15, text=rotulo, font=self._font,
                fill=self._ink if (cumprida or atual) else self._ink_soft,
            )
            if atual and self._note:
                self.create_text(
                    x, topo + raio + 29, text=self._note, font=self._font,
                    fill=self._ink_soft,
                )

    def apply_theme(
        self, *, background: str, accent: str, muted: str, ink: str, ink_soft: str,
        on_check: str,
    ) -> None:
        self._background = background
        self._accent, self._muted = accent, muted
        self._ink, self._ink_soft, self._on_check = ink, ink_soft, on_check
        tk.Canvas.configure(self, background=background)
        self.redraw()
