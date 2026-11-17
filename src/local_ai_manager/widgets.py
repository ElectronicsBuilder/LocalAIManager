"""VS Code-style building blocks (activity bar, side bar sections, tabs,
status bar items, cards, charts, tooltips). Tk-thread only."""

from __future__ import annotations

import tkinter as tk
from collections import deque
from typing import Callable

import customtkinter as ctk

from . import theme as t


class Tooltip:
    """Small hover tooltip, like VS Code's activity bar hints."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 450) -> None:
        self.widget, self.text, self.delay = widget, text, delay_ms
        self._job: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None) -> None:
        self._cancel()
        self._job = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None

    def _show(self) -> None:
        if self._tip or not self.widget.winfo_viewable():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 4
        y = self.widget.winfo_rooty() + self.widget.winfo_height() // 2 - 12
        self._tip = tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        tk.Label(tip, text=self.text, bg=t.CARD, fg=t.FG, font=t.FONT_SMALL, padx=8, pady=4,
                 highlightthickness=1, highlightbackground=t.BORDER).pack()

    def _hide(self, _e=None) -> None:
        self._cancel()
        if self._tip:
            self._tip.destroy()
            self._tip = None


class ActivityBar(tk.Frame):
    """Vertical icon strip on the far left."""

    def __init__(self, master: tk.Misc, scale: float) -> None:
        super().__init__(master, bg=t.CHROME, width=int(48 * scale))
        self.pack_propagate(False)
        self.scale = scale
        self._items: dict[str, tuple[tk.Frame, tk.Label]] = {}
        self._active: str | None = None
        self._bottom = tk.Frame(self, bg=t.CHROME)
        self._bottom.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, int(6 * scale)))

    def add(self, key: str, glyph: str, tooltip: str, command: Callable[[], None],
            bottom: bool = False) -> None:
        parent = self._bottom if bottom else self
        row = tk.Frame(parent, bg=t.CHROME, height=int(48 * self.scale))
        row.pack(side=tk.TOP, fill=tk.X)
        row.pack_propagate(False)
        indicator = tk.Frame(row, bg=t.CHROME, width=max(int(2 * self.scale), 2))
        indicator.pack(side=tk.LEFT, fill=tk.Y)
        label = tk.Label(row, text=glyph, font=(t.ICON_FAMILY, 17), bg=t.CHROME, fg=t.DIM,
                         cursor="hand2")
        label.pack(expand=True, fill=tk.BOTH)
        label.bind("<Button-1>", lambda _e: command())
        label.bind("<Enter>", lambda _e: label.configure(fg=t.FG_STRONG))
        label.bind("<Leave>", lambda _e, k=key: label.configure(
            fg=t.FG_STRONG if self._active == k else t.DIM))
        Tooltip(label, tooltip)
        self._items[key] = (indicator, label)

    def set_active(self, key: str | None) -> None:
        self._active = key
        for k, (indicator, label) in self._items.items():
            on = k == key
            indicator.configure(bg=t.ACCENT if on else t.CHROME)
            label.configure(fg=t.FG_STRONG if on else t.DIM)


class SidebarSection(tk.Frame):
    """Collapsible side bar section with an uppercase header (like EXPLORER)."""

    def __init__(self, master: tk.Misc, title: str, expanded: bool = True) -> None:
        super().__init__(master, bg=t.CHROME)
        self._expanded = expanded
        self.header = tk.Frame(self, bg=t.CHROME, cursor="hand2")
        self.header.pack(fill=tk.X)
        self._chev = tk.Label(self.header, font=(t.ICON_FAMILY, 7), bg=t.CHROME, fg=t.FG)
        self._chev.pack(side=tk.LEFT, padx=(6, 4), pady=4)
        self._title = tk.Label(self.header, text=title.upper(), font=t.FONT_SECTION,
                               bg=t.CHROME, fg=t.FG)
        self._title.pack(side=tk.LEFT, pady=4)
        for w in (self.header, self._chev, self._title):
            w.bind("<Button-1>", lambda _e: self.toggle())
        self.body = tk.Frame(self, bg=t.CHROME)
        self._sync()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._sync()

    def _sync(self) -> None:
        self._chev.configure(text=t.ICON["chevron_down" if self._expanded else "chevron_right"])
        if self._expanded:
            self.body.pack(fill=tk.X, pady=(0, 6))
        else:
            self.body.pack_forget()


class SidebarRow(tk.Frame):
    """Hoverable side bar row: colored glyph + label + optional right text."""

    def __init__(self, master: tk.Misc, text: str = "", glyph: str = "●",
                 command: Callable[[], None] | None = None) -> None:
        super().__init__(master, bg=t.CHROME, cursor="hand2" if command else "")
        self.dot = tk.Label(self, text=glyph, font=(t.UI_FAMILY, 8), bg=t.CHROME, fg=t.DIM)
        self.dot.pack(side=tk.LEFT, padx=(22, 6))
        self.label = tk.Label(self, text=text, font=t.FONT, bg=t.CHROME, fg=t.FG, anchor="w")
        self.label.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2)
        self.right = tk.Label(self, text="", font=t.FONT_SMALL, bg=t.CHROME, fg=t.MUTED)
        self.right.pack(side=tk.RIGHT, padx=(4, 10))
        self._selected = False
        parts = (self, self.dot, self.label, self.right)
        for w in parts:
            w.bind("<Enter>", lambda _e: self._paint(hover=True))
            w.bind("<Leave>", lambda _e: self._paint(hover=False))
            if command:
                w.bind("<Button-1>", lambda _e: command())

    def set(self, text: str | None = None, color: str | None = None,
            right: str | None = None) -> None:
        if text is not None:
            self.label.configure(text=text)
        if color is not None:
            self.dot.configure(fg=color)
        if right is not None:
            self.right.configure(text=right)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._paint(hover=False)

    def _paint(self, hover: bool) -> None:
        bg = t.SELECT if self._selected else t.HOVER if hover else t.CHROME
        for w in (self, self.dot, self.label, self.right):
            w.configure(bg=bg)


class TabStrip(tk.Frame):
    """Editor tab strip; the active tab has a blue top border."""

    def __init__(self, master: tk.Misc, scale: float) -> None:
        super().__init__(master, bg=t.CHROME, height=int(35 * scale))
        self.pack_propagate(False)
        self._tabs: dict[str, tuple[tk.Frame, tk.Frame, list[tk.Label]]] = {}

    def add(self, key: str, glyph: str, title: str, command: Callable[[], None]) -> None:
        outer = tk.Frame(self, bg=t.CHROME, cursor="hand2")
        outer.pack(side=tk.LEFT, fill=tk.Y)
        topline = tk.Frame(outer, bg=t.CHROME, height=1)
        topline.pack(side=tk.TOP, fill=tk.X)
        icon = tk.Label(outer, text=glyph, font=(t.ICON_FAMILY, 9), bg=t.CHROME, fg=t.MUTED)
        icon.pack(side=tk.LEFT, padx=(12, 6))
        label = tk.Label(outer, text=title, font=t.FONT, bg=t.CHROME, fg=t.MUTED)
        label.pack(side=tk.LEFT, padx=(0, 14))
        tk.Frame(self, bg=t.BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)
        for w in (outer, icon, label):
            w.bind("<Button-1>", lambda _e: command())
        self._tabs[key] = (outer, topline, [icon, label])

    def set_active(self, key: str) -> None:
        for k, (outer, topline, labels) in self._tabs.items():
            on = k == key
            bg = t.EDITOR if on else t.CHROME
            outer.configure(bg=bg)
            topline.configure(bg=t.ACCENT if on else t.CHROME)
            for lbl in labels:
                lbl.configure(bg=bg, fg=t.FG_STRONG if on else t.MUTED)


class StatusItem(tk.Label):
    """Clickable status bar entry with hover highlight."""

    def __init__(self, master: tk.Misc, text: str = "", command: Callable[[], None] | None = None,
                 icon: bool = False) -> None:
        super().__init__(master, text=text, bg=t.STATUS_BG, fg=t.STATUS_FG, padx=8,
                         font=(t.ICON_FAMILY, 8) if icon else t.FONT_SMALL,
                         cursor="hand2" if command else "")
        self._base = t.STATUS_BG
        self._hover = t.STATUS_HOVER
        self.bind("<Enter>", lambda _e: command and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda _e: self.configure(bg=self._base))
        if command:
            self.bind("<Button-1>", lambda _e: command())

    def set_colors(self, base: str, hover: str) -> None:
        self._base, self._hover = base, hover
        self.configure(bg=base)


class Card(ctk.CTkFrame):
    """Rounded content card with a small uppercase title."""

    def __init__(self, master: tk.Misc, title: str, glyph: str = "") -> None:
        super().__init__(master, fg_color=t.CARD, corner_radius=8, border_width=1,
                         border_color=t.BORDER)
        head = tk.Frame(self, bg=t.CARD)
        head.pack(fill=tk.X, padx=14, pady=(12, 4))
        if glyph:
            tk.Label(head, text=glyph, font=(t.ICON_FAMILY, 10), bg=t.CARD,
                     fg=t.MUTED).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(head, text=title.upper(), font=t.FONT_SECTION, bg=t.CARD,
                 fg=t.MUTED).pack(side=tk.LEFT)
        self.body = tk.Frame(self, bg=t.CARD)
        self.body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 14))


class LineChart(tk.Canvas):
    """Minimal percentage history chart (0-100)."""

    def __init__(self, master: tk.Misc, color: str, fill: str, capacity: int = 90,
                 height: int = 90, bg: str = t.CARD) -> None:
        super().__init__(master, bg=bg, height=height, highlightthickness=0)
        self.color, self.fill = color, fill
        self.values: deque[float] = deque(maxlen=capacity)
        self.capacity = capacity
        self.bind("<Configure>", lambda _e: self.redraw())

    def push(self, value: float) -> None:
        self.values.append(max(0.0, min(100.0, value)))
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        for frac in (0.25, 0.5, 0.75):
            y = h - frac * h
            self.create_line(0, y, w, y, fill=t.BORDER, dash=(2, 4))
        if len(self.values) < 2:
            return
        step = w / (self.capacity - 1)
        x0 = w - step * (len(self.values) - 1)
        pts = [(x0 + i * step, h - 2 - v / 100 * (h - 4)) for i, v in enumerate(self.values)]
        poly = [(pts[0][0], h)] + pts + [(pts[-1][0], h)]
        self.create_polygon(*[c for p in poly for c in p], fill=self.fill, outline="")
        self.create_line(*[c for p in pts for c in p], fill=self.color, width=2)


def primary_button(master, text: str, command, width: int = 120) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width, height=28,
                         corner_radius=4, fg_color=t.ACCENT, hover_color=t.ACCENT_HOVER,
                         text_color="#FFFFFF", text_color_disabled="#8AA9C4",
                         font=ctk.CTkFont(t.UI_FAMILY, 13))


def secondary_button(master, text: str, command, width: int = 110) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width, height=28,
                         corner_radius=4, fg_color=t.BUTTON2, hover_color=t.BUTTON2_HOVER,
                         border_width=1, border_color="#3C3C3C", text_color=t.FG,
                         text_color_disabled=t.DIM, font=ctk.CTkFont(t.UI_FAMILY, 13))


def switch(master, text: str, variable, command) -> ctk.CTkSwitch:
    return ctk.CTkSwitch(master, text=text, variable=variable, command=command,
                         onvalue=True, offvalue=False, progress_color=t.ACCENT,
                         fg_color="#3C3C3C", button_color=t.FG_STRONG,
                         button_hover_color="#FFFFFF", text_color=t.FG,
                         font=ctk.CTkFont(t.UI_FAMILY, 13), switch_width=36, switch_height=18)


def progress(master, color: str = t.ACCENT) -> ctk.CTkProgressBar:
    bar = ctk.CTkProgressBar(master, height=6, corner_radius=3, fg_color="#3C3C3C",
                             progress_color=color)
    bar.set(0)
    return bar
