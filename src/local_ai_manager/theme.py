"""Visual theme: VS Code "Dark Modern" palette, fonts, icons, ttk styles."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

ASSETS = Path(__file__).resolve().parent / "assets"
APP_ICON = ASSETS / "app.ico"

# --- VS Code Dark Modern palette
CHROME = "#181818"        # title/activity bar, side bar, panel
EDITOR = "#1F1F1F"        # editor background
CARD = "#252526"
BORDER = "#2B2B2B"
FG = "#CCCCCC"
FG_STRONG = "#E7E7E7"
MUTED = "#9D9D9D"
DIM = "#6E7681"
ACCENT = "#0078D4"
ACCENT_HOVER = "#026EC1"
BUTTON2 = "#313131"
BUTTON2_HOVER = "#3C3C3C"
INPUT = "#313131"
HOVER = "#2A2D2E"
SELECT = "#04395E"
GOOD = "#89D185"
BAD = "#F14C4C"
WARN = "#CCA700"
PURPLE = "#B180D7"
STATUS_BG = "#007ACC"     # classic VS Code status bar
STATUS_HOVER = "#1F8AD2"
STATUS_GAMING = "#68217A"  # like VS Code's debug-mode status bar
STATUS_GAMING_HOVER = "#7A2E8C"
STATUS_FG = "#FFFFFF"

# --- fonts (point sizes; Tk scales them with DPI)
UI_FAMILY = "Segoe UI"
MONO_FAMILY = "Cascadia Mono"
ICON_FAMILY = "Segoe MDL2 Assets"
FONT = (UI_FAMILY, 10)
FONT_SMALL = (UI_FAMILY, 9)
FONT_BOLD = (UI_FAMILY, 10, "bold")
FONT_SECTION = (UI_FAMILY, 8, "bold")
FONT_TITLE = (UI_FAMILY, 18)
FONT_VALUE = (UI_FAMILY, 11, "bold")
FONT_BIG = (UI_FAMILY, 22)
FONT_MONO = (MONO_FAMILY, 9)

# --- Segoe MDL2 Assets glyphs
ICON = {
    "dashboard": "",
    "models": "",
    "gpu": "",
    "settings": "",
    "output": "",
    "game": "",
    "remote": "",
    "refresh": "",
    "chevron_down": "",
    "chevron_right": "",
    "check": "",
    "warning": "",
    "sync": "",
    "folder": "",
    "close": "",
}


def ui_scale(widget: tk.Misc) -> float:
    """DPI scale factor relative to 96 DPI (for pixel sizes)."""
    try:
        return max(float(widget.tk.call("tk", "scaling")) / (96 / 72), 1.0)
    except tk.TclError:
        return 1.0


def apply_ttk_styles(root: tk.Misc) -> None:
    """Style the ttk widgets (Treeview, Scrollbar) that CustomTkinter lacks."""
    scale = ui_scale(root)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=EDITOR, foreground=FG, fieldbackground=EDITOR,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                    troughcolor=EDITOR, selectbackground=SELECT, selectforeground=FG_STRONG,
                    font=FONT)
    style.configure("Treeview", background=EDITOR, fieldbackground=EDITOR, foreground=FG,
                    rowheight=int(26 * scale), borderwidth=0, relief="flat")
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # no border
    style.map("Treeview", background=[("selected", SELECT)],
              foreground=[("selected", FG_STRONG)])
    style.configure("Treeview.Heading", background=CHROME, foreground=MUTED, relief="flat",
                    font=FONT_SMALL, padding=(6, 4), borderwidth=0)
    style.map("Treeview.Heading", background=[("active", HOVER)])
    style.configure("Vertical.TScrollbar", background=BUTTON2, troughcolor=EDITOR,
                    bordercolor=EDITOR, lightcolor=BUTTON2, darkcolor=BUTTON2,
                    arrowcolor=MUTED, gripcount=0, arrowsize=int(10 * scale))
    style.map("Vertical.TScrollbar", background=[("active", BUTTON2_HOVER)])
