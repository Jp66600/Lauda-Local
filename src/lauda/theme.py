"""Temas claro e escuro do aplicativo de janela.

Três decisões que importam aqui:

1. O tema padrão é **auto**: segue o que o Windows já usa. Quem trabalha no
   escuro não deveria precisar configurar nada.
2. A escolha do usuário fica guardada no perfil dele (`~/.lauda/ui.json`),
   não na pasta do projeto — assim sobrevive a mover ou reinstalar o programa.
3. O ttk só deixa recolorir tudo (botões, campos, abas, barras) no tema
   `clam`. Os temas nativos ignoram cor de fundo em vários widgets, o que
   produziria um "modo escuro" com botões brancos.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("lauda.theme")

PREFS_PATH = Path.home() / ".lauda" / "ui.json"

#: Valores aceitos para a preferência de tema.
THEME_CHOICES = ("auto", "claro", "escuro")


@dataclass(frozen=True)
class Theme:
    """Paleta completa da interface."""

    name: str            # "claro" | "escuro"
    dark: bool

    canvas: str          # fundo da janela
    paper: str           # fundo dos painéis
    surface: str         # fundo de áreas internas (zona de soltar, listas)
    sidebar: str         # fundo da barra lateral de navegação
    nav_active: str      # fundo do item de navegação selecionado
    field: str           # fundo de campos de entrada
    ink: str             # texto principal
    ink_soft: str        # texto secundário
    line: str            # linhas e bordas
    muted: str           # controles desligados e etapas ainda não cumpridas

    accent: str          # cor dos títulos de passo
    accent_warm: str     # avisos
    danger: str          # erros
    success: str         # conclusão

    button: str          # fundo dos botões
    button_active: str
    button_text: str
    primary: str         # botão principal (Processar)
    primary_active: str
    primary_text: str

    preview_bg: str      # fundo da pré-visualização do relatório
    preview_fg: str
    selection: str       # fundo do texto selecionado
    selection_text: str


LIGHT = Theme(
    name="claro",
    dark=False,
    canvas="#F4F6FA",
    paper="#FFFFFF",
    surface="#F7F9FC",
    sidebar="#EDF0F5",
    nav_active="#FFFFFF",
    field="#FFFFFF",
    ink="#12151C",
    ink_soft="#4A5163",
    line="#D9DEE7",
    muted="#BFC7D4",
    accent="#1F7A73",
    accent_warm="#B26A00",
    danger="#B3261E",
    success="#1F7A73",
    button="#EDF0F5",
    button_active="#DFE4EC",
    button_text="#12151C",
    primary="#1F7A73",
    primary_active="#186963",
    primary_text="#FFFFFF",
    preview_bg="#FFFFFF",
    preview_fg="#12151C",
    selection="#CDE7E4",
    selection_text="#12151C",
)

DARK = Theme(
    name="escuro",
    dark=True,
    canvas="#0F1218",
    paper="#171B23",
    surface="#1C222C",
    sidebar="#12161D",
    nav_active="#232A36",
    field="#1F242E",
    ink="#E8EAF0",
    ink_soft="#9AA3B4",
    line="#2B313D",
    muted="#3B4351",
    accent="#5ECDC3",
    accent_warm="#FFB02E",
    danger="#FF6B60",
    success="#5ECDC3",
    button="#242A35",
    button_active="#2F3745",
    button_text="#E8EAF0",
    primary="#2A8C84",
    primary_active="#34A79D",
    primary_text="#FFFFFF",
    preview_bg="#12151C",
    preview_fg="#E8EAF0",
    selection="#2A4C4A",
    selection_text="#FFFFFF",
)


def detect_system_theme() -> str:
    """Lê o tema do sistema. Devolve "claro" ou "escuro" (padrão: claro)."""
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            with key:
                # 0 = escuro, 1 = claro. Sim, o nome da chave é enganoso.
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "claro" if value else "escuro"
        except Exception as exc:  # pragma: no cover - chave ausente
            log.debug("Não consegui ler o tema do Windows: %s", exc)
    elif sys.platform == "darwin":  # pragma: no cover - específico do macOS
        try:
            import subprocess

            proc = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=5,
            )
            if "dark" in (proc.stdout or "").lower():
                return "escuro"
        except Exception as exc:
            log.debug("Nao consegui ler o tema do macOS: %s", exc)
    return "claro"


def resolve(choice: str) -> Theme:
    """Converte a preferência ("auto"/"claro"/"escuro") na paleta."""
    if choice == "auto":
        choice = detect_system_theme()
    return DARK if choice == "escuro" else LIGHT


def load_choice() -> str:
    """Preferência guardada. "auto" quando nunca foi escolhida."""
    try:
        data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
        choice = str(data.get("theme", "auto"))
        return choice if choice in THEME_CHOICES else "auto"
    except (OSError, json.JSONDecodeError, ValueError):
        return "auto"


def save_choice(choice: str) -> None:
    """Guarda a preferência. Falha em disco não pode derrubar a interface."""
    if choice not in THEME_CHOICES:
        return
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        if PREFS_PATH.exists():
            try:
                data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        data["theme"] = choice
        PREFS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover - disco cheio, permissão
        log.debug("Não consegui salvar a preferência de tema: %s", exc)



def load_value(name: str, default: Any = None) -> Any:
    """Lê uma preferência qualquer do `ui.json`.

    Este arquivo é a casa de tudo que o usuário escolheu e espera reencontrar:
    tema, limites de máquina e as opções da tela de trabalho. Nunca levanta —
    perfil corrompido volta ao padrão em vez de impedir a abertura.
    """
    try:
        data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default
    return data.get(name, default)


def save_value(name: str, value: Any) -> None:
    """Guarda uma preferência sem apagar as outras chaves do arquivo."""
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, object] = {}
        if PREFS_PATH.exists():
            try:
                data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        data[name] = value
        PREFS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:  # pragma: no cover - disco cheio, permissão
        log.debug("Não consegui salvar a preferência '%s': %s", name, exc)


def load_flag(name: str, default: bool = False) -> bool:
    """Preferência de sim/não."""
    return bool(load_value(name, default))


def save_flag(name: str, value: bool) -> None:
    save_value(name, bool(value))

def apply_titlebar(window, dark: bool) -> None:
    """Pinta a barra de título do Windows 10/11 de escuro.

    Sem isto o modo escuro fica com uma faixa branca em cima, que denuncia
    que o tema é só pintura por dentro.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()
        handle = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (19 nas builds antigas do Win10).
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                handle, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                return
    except Exception as exc:  # pragma: no cover - API ausente
        log.debug("Não consegui pintar a barra de título: %s", exc)
