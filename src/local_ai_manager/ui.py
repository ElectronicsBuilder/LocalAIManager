"""CustomTkinter GUI for Local AI Manager, laid out like VS Code.

Layout: activity bar | side bar (Environment, Models) | editor area with tabs
(Dashboard, Models, GPU, Settings) above a resizable Output panel, and a
status bar along the bottom (blue normally, purple in Gaming Mode).

Threading model (see docs/DECISIONS.md D-006):
  * A daemon monitor thread polls WSL, the ollama service, the Ollama API and
    nvidia-smi, and posts snapshots to ``_ui_queue``.
  * User actions run one at a time on a worker thread (``_run_action``).
  * Background threads NEVER touch Tk objects or call ``root.after``; they
    only call ``_post``. The Tk thread drains the queue every 100 ms.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass, field
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Callable

import customtkinter as ctk

from . import __version__, gaming, gpu, ollama, startup, wsl
from . import theme as t
from .config import Config, get_config, settings_path
from .widgets import (ActivityBar, Card, LineChart, SidebarRow, SidebarSection, StatusItem,
                      TabStrip, primary_button, progress, secondary_button, switch)

log = logging.getLogger(__name__)

WSL_REFRESH_EVERY = 5          # monitor ticks between WSL/service queries
MAX_LOG_LINES = 500
AUTOLOAD_API_WAIT_S = 90
KIND_COLOR = {"good": t.GOOD, "bad": t.BAD, "warn": t.WARN, "muted": t.MUTED}
VIEWS = [("dashboard", "Dashboard"), ("models", "Models"), ("gpu", "GPU"),
         ("settings", "Settings")]


@dataclass
class Snapshot:
    """Data gathered by the monitor thread. ``wsl`` is None on light ticks."""

    wsl: wsl.WslStatus | None = None
    service_state: str = ""
    ollama_version: str | None = None
    models: list[ollama.Model] = field(default_factory=list)
    running: list[ollama.RunningModel] | None = None
    gpu: gpu.GpuSample = field(default_factory=gpu.GpuSample)


def collect_snapshot(cfg: Config, include_wsl: bool) -> Snapshot:
    """Gather status. Blocking; call from a background thread only."""
    snap = Snapshot()
    if include_wsl:
        snap.wsl = wsl.detect()
        distro = snap.wsl.find(cfg.wsl_distro)
        if distro is None:
            snap.service_state = "distro not found"
        elif not distro.running:
            # Querying systemctl would boot the distro; don't.
            snap.service_state = "distro stopped"
        else:
            snap.service_state = wsl.service_status(cfg.wsl_distro, cfg.ollama_service)
    snap.ollama_version = ollama.get_version(cfg.ollama_base_url)
    if snap.ollama_version is not None:
        snap.models = ollama.get_models(cfg.ollama_base_url)
        snap.running = ollama.get_running(cfg.ollama_base_url)
    snap.gpu = gpu.sample()
    return snap


def format_expiry(expires_at: str) -> str:
    """Turn Ollama's expires_at into 'until HH:MM' (local time)."""
    if not expires_at:
        return ""
    text = expires_at.replace("Z", "+00:00")
    # Ollama emits nanoseconds; fromisoformat accepts at most microseconds.
    if "." in text:
        head, _, rest = text.partition(".")
        digits = "".join(ch for ch in rest if ch.isdigit())
        tz = rest[len(digits):]
        text = f"{head}.{digits[:6]}{tz}"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if dt.year > 2100:
        return "kept loaded indefinitely"
    return f"until {dt.astimezone().strftime('%H:%M')}"


class _QueueLogHandler(logging.Handler):
    """Forwards log records to the Output panel via the UI queue."""

    def __init__(self, app: "App") -> None:
        super().__init__(level=logging.INFO)
        self.app = app
        self.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
                                            "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            return
        self.app._post(lambda: self.app._append_log(line, record.levelno))


def _label(master, text: str = "", var: tk.Variable | None = None, font=t.FONT, fg: str = t.FG,
           bg: str = t.CARD, **kw) -> tk.Label:
    return tk.Label(master, text=text, textvariable=var, font=font, fg=fg, bg=bg,
                    anchor="w", justify="left", **kw)


class App:
    def __init__(self, root: tk.Tk | tk.Toplevel, cfg: Config | None = None,
                 start_background: bool = True) -> None:
        self.root = root
        self.cfg = cfg or get_config()
        self._ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._full_refresh = threading.Event()
        self._monitor: threading.Thread | None = None
        self._busy = False
        self._closing = False
        self._action_widgets: list[ctk.CTkBaseClass] = []
        self._load_buttons: list[ctk.CTkBaseClass] = []
        self._running_names: list[str] = []
        self._sb_model_rows: dict[str, SidebarRow] = {}
        self._current_view = "dashboard"
        self.scale = t.ui_scale(root)

        root.title(f"Local AI Manager {__version__}")
        self._set_window_icon()
        root.geometry(f"{self.cfg.window_width}x{self.cfg.window_height}")
        root.minsize(1000, 640)
        if isinstance(root, ctk.CTk):
            root.configure(fg_color=t.EDITOR)
        else:
            root.configure(bg=t.EDITOR)
        t.apply_ttk_styles(root)
        self._build_ui()
        self._bind_shortcuts()
        self.show_view("dashboard")

        self._log_handler = _QueueLogHandler(self)
        logging.getLogger().addHandler(self._log_handler)
        self._drain_ui_queue()

        log.info("Settings: %s", settings_path())
        if start_background:
            self._start_monitor()
            if self.cfg.auto_start_last_model:
                self.root.after(500, self._auto_load_last_model)

    def _set_window_icon(self) -> None:
        """Title bar + taskbar icon (and default for dialogs)."""
        if not t.APP_ICON.is_file():
            log.warning("App icon missing: %s", t.APP_ICON)
            return
        try:
            self.root.iconbitmap(str(t.APP_ICON))
            self.root.iconbitmap(default=str(t.APP_ICON))
        except tk.TclError as exc:
            log.warning("Could not set window icon: %s", exc)

    # ================================================================ layout
    def _build_ui(self) -> None:
        s = self.scale
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        body = tk.Frame(self.root, bg=t.EDITOR)
        body.grid(row=0, column=0, sticky="nsew")
        self._build_status_bar()

        self.activity = ActivityBar(body, s)
        self.activity.pack(side=tk.LEFT, fill=tk.Y)
        for key, title in VIEWS:
            self.activity.add(key, t.ICON[key], title, lambda k=key: self._on_activity(k),
                              bottom=(key == "settings"))
        tk.Frame(body, bg=t.BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y)

        self.sidebar = tk.Frame(body, bg=t.CHROME, width=int(250 * s))
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        self.sidebar_border = tk.Frame(body, bg=t.BORDER, width=1)
        self.sidebar_border.pack(side=tk.LEFT, fill=tk.Y)
        self._build_sidebar()

        self.editor_col = tk.PanedWindow(body, orient=tk.VERTICAL, bg=t.BORDER, bd=0,
                                         sashwidth=max(int(3 * s), 3), sashrelief="flat",
                                         showhandle=False)
        self.editor_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        editor = tk.Frame(self.editor_col, bg=t.EDITOR)
        self.tabs = TabStrip(editor, s)
        self.tabs.pack(fill=tk.X)
        for key, title in VIEWS:
            self.tabs.add(key, t.ICON[key], title, lambda k=key: self.show_view(k))
        self.view_host = tk.Frame(editor, bg=t.EDITOR)
        self.view_host.pack(fill=tk.BOTH, expand=True)
        self.view_host.grid_rowconfigure(0, weight=1)
        self.view_host.grid_columnconfigure(0, weight=1)
        self.views: dict[str, tk.Frame] = {}
        for key, builder, scrolls in (("dashboard", self._build_dashboard, True),
                                      ("models", self._build_models, False),
                                      ("gpu", self._build_gpu, False),
                                      ("settings", self._build_settings, True)):
            frame = tk.Frame(self.view_host, bg=t.EDITOR)
            frame.grid(row=0, column=0, sticky="nsew")
            if scrolls:
                inner = ctk.CTkScrollableFrame(
                    frame, fg_color=t.EDITOR, corner_radius=0,
                    scrollbar_button_color=t.BUTTON2, scrollbar_button_hover_color=t.BUTTON2_HOVER)
                inner.pack(fill=tk.BOTH, expand=True)
                builder(inner)
            else:
                builder(frame)
            self.views[key] = frame

        self.panel = tk.Frame(self.editor_col, bg=t.CHROME)
        self._build_output_panel(self.panel)
        self.editor_col.add(editor, stretch="always", minsize=int(300 * s))
        self.editor_col.add(self.panel, stretch="never", height=int(140 * s), minsize=int(60 * s))
        self._panel_visible = True

    def _view_header(self, parent: tk.Frame, title: str, subtitle: str) -> tk.Frame:
        head = tk.Frame(parent, bg=t.EDITOR)
        head.pack(fill=tk.X, padx=28, pady=(22, 14))
        _label(head, title, font=t.FONT_TITLE, fg=t.FG_STRONG, bg=t.EDITOR).pack(anchor="w")
        _label(head, subtitle, fg=t.MUTED, bg=t.EDITOR).pack(anchor="w", pady=(2, 0))
        return head

    def _kv_row(self, parent: tk.Frame, row: int, key: str,
                var: tk.StringVar | None = None) -> tk.Label:
        _label(parent, key, fg=t.MUTED).grid(row=row, column=0, sticky="w", pady=3)
        value = _label(parent, var=var, font=t.FONT_BOLD)
        value.grid(row=row, column=1, sticky="w", padx=(14, 0), pady=3)
        return value

    def _action(self, widget: ctk.CTkBaseClass, is_load: bool = False) -> ctk.CTkBaseClass:
        self._action_widgets.append(widget)
        if is_load:
            self._load_buttons.append(widget)
        return widget

    # ---------------------------------------------------------------- side bar
    def _build_sidebar(self) -> None:
        sb = self.sidebar
        _label(sb, "LOCAL AI MANAGER", font=t.FONT_SECTION, fg=t.MUTED,
               bg=t.CHROME).pack(fill=tk.X, padx=20, pady=(10, 8))

        env = SidebarSection(sb, "Environment")
        env.pack(fill=tk.X)
        go_dash = lambda: self.show_view("dashboard")  # noqa: E731
        self.sb_distro = SidebarRow(env.body, f"WSL  {self.cfg.wsl_distro}", command=go_dash)
        self.sb_service = SidebarRow(env.body, f"Service  {self.cfg.ollama_service}", command=go_dash)
        self.sb_api = SidebarRow(env.body, "Ollama API", command=go_dash)
        self.sb_gpu = SidebarRow(env.body, "GPU", command=lambda: self.show_view("gpu"))
        for row in (self.sb_distro, self.sb_service, self.sb_api, self.sb_gpu):
            row.pack(fill=tk.X)

        models = SidebarSection(sb, "Models")
        models.pack(fill=tk.X, pady=(4, 0))
        self.sb_models_body = models.body
        self.sb_models_empty = _label(models.body, "Waiting for Ollama...", fg=t.DIM,
                                      bg=t.CHROME, font=t.FONT_SMALL)
        self.sb_models_empty.pack(fill=tk.X, padx=24, pady=2)

    def _sync_sidebar_models(self, names: list[str], loaded: set[str], reachable: bool) -> None:
        if list(self._sb_model_rows) != names:
            for row in self._sb_model_rows.values():
                row.destroy()
            self._sb_model_rows = {}
            for name in names:
                row = SidebarRow(self.sb_models_body, name,
                                 command=lambda n=name: self._reveal_model(n))
                row.pack(fill=tk.X)
                self._sb_model_rows[name] = row
        if names:
            self.sb_models_empty.pack_forget()
        else:
            self.sb_models_empty.configure(
                text="No models installed" if reachable else "Ollama API not reachable")
            self.sb_models_empty.pack(fill=tk.X, padx=24, pady=2)
        selected = self._selected_model()
        for name, row in self._sb_model_rows.items():
            row.set(color=t.GOOD if name in loaded else t.DIM,
                    right="loaded" if name in loaded else "")
            row.set_selected(name == selected)

    # ---------------------------------------------------------------- dashboard
    def _build_dashboard(self, view: tk.Frame) -> None:
        self._view_header(view, "Dashboard", "WSL2, Ollama and GPU at a glance")
        grid = tk.Frame(view, bg=t.EDITOR)
        grid.pack(fill=tk.BOTH, expand=True, padx=28, pady=(0, 20))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="dash")

        env = Card(grid, "WSL2 and Ollama Service", t.ICON["remote"])
        env.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        b = env.body
        b.grid_columnconfigure(1, weight=1)
        self.distro_var = tk.StringVar(value="Checking...")
        self.service_var = tk.StringVar(value="Checking...")
        self.api_var = tk.StringVar(value="Checking...")
        self.distro_label = self._kv_row(b, 0, f"Distro ({self.cfg.wsl_distro})", self.distro_var)
        self.service_label = self._kv_row(b, 1, f"Service ({self.cfg.ollama_service})", self.service_var)
        self.api_label = self._kv_row(b, 2, f"API ({self.cfg.ollama_base_url.split('//')[-1]})",
                                      self.api_var)
        btns = tk.Frame(b, bg=t.CARD)
        btns.grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))
        for i, (text, cmd) in enumerate((("Start Distro", self._start_distro),
                                         ("Stop Distro", self._stop_distro),
                                         ("Start Service", self._start_service),
                                         ("Stop Service", self._stop_service))):
            self._action(secondary_button(btns, text, cmd, width=104)).grid(
                row=i // 2, column=i % 2, padx=(0, 6), pady=(0, 6), sticky="w")
        secondary_button(btns, "Refresh", self.request_refresh, width=80).grid(
            row=0, column=2, padx=(6, 0), pady=(0, 6), sticky="w")

        gcard = Card(grid, "GPU", t.ICON["gpu"])
        gcard.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        g = gcard.body
        g.grid_columnconfigure(1, weight=1)
        self.gpu_vars = {k: tk.StringVar(value="-") for k in ("name", "util", "mem", "temp", "power")}
        _label(g, var=self.gpu_vars["name"], font=t.FONT_VALUE, fg=t.FG_STRONG).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        for r, (key, title) in enumerate((("util", "Utilization"), ("mem", "VRAM"),
                                          ("temp", "Temperature"), ("power", "Power")), start=1):
            self._kv_row(g, r, title, self.gpu_vars[key])
        _label(g, "GPU load", fg=t.MUTED).grid(row=5, column=0, sticky="w", pady=(14, 2))
        self.util_bar = progress(g)
        self.util_bar.grid(row=5, column=1, sticky="ew", padx=(14, 0), pady=(14, 2))
        _label(g, "VRAM used", fg=t.MUTED).grid(row=6, column=0, sticky="w", pady=(6, 2))
        self.vram_bar = progress(g, t.PURPLE)
        self.vram_bar.grid(row=6, column=1, sticky="ew", padx=(14, 0), pady=(6, 2))

        mcard = Card(grid, "Active Model", t.ICON["models"])
        mcard.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        self.loaded_var = tk.StringVar(value="Loaded: -")
        self.loaded_label = _label(mcard.body, var=self.loaded_var, font=t.FONT_VALUE,
                                   wraplength=int(380 * self.scale))
        self.loaded_label.pack(anchor="w")
        mb = tk.Frame(mcard.body, bg=t.CARD)
        mb.pack(anchor="w", pady=(12, 0))
        primary_button(mb, "Manage Models", lambda: self.show_view("models"),
                       width=130).pack(side=tk.LEFT)
        self._action(secondary_button(mb, "Unload All", self._unload_all)).pack(
            side=tk.LEFT, padx=(6, 0))

        gm = Card(grid, "Gaming Mode", t.ICON["game"])
        gm.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        self.gaming_var = tk.BooleanVar(value=self.cfg.gaming_mode_enabled)
        self._action(switch(gm.body, "Gaming Mode", self.gaming_var,
                            self._on_gaming_toggled)).pack(anchor="w")
        _label(gm.body, "Unloads every model to free VRAM. WSL and Ollama keep running; "
                        "nothing reloads when you turn it off.",
               fg=t.MUTED, wraplength=int(360 * self.scale)).pack(anchor="w", pady=(6, 0))
        self.gaming_warn_var = tk.StringVar(value="")
        _label(gm.body, var=self.gaming_warn_var, fg=t.WARN,
               wraplength=int(360 * self.scale)).pack(anchor="w", pady=(4, 0))

    # ---------------------------------------------------------------- models
    def _build_models(self, view: tk.Frame) -> None:
        self._view_header(view, "Models", "Installed Ollama models. Double-click to load.")
        bar = tk.Frame(view, bg=t.EDITOR)
        bar.pack(fill=tk.X, padx=28, pady=(0, 10))
        self._action(primary_button(bar, "Load Selected", self._load_selected),
                     is_load=True).pack(side=tk.LEFT)
        self._action(secondary_button(bar, "Unload Selected", self._unload_selected,
                                      width=130)).pack(side=tk.LEFT, padx=(6, 0))
        self._action(secondary_button(bar, "Unload All", self._unload_all)).pack(
            side=tk.LEFT, padx=(6, 0))
        _label(bar, "min", fg=t.MUTED, bg=t.EDITOR).pack(side=tk.RIGHT)
        self.keepalive_var = tk.StringVar(value=str(self.cfg.keep_alive_minutes))
        self._keepalive_entry(bar).pack(side=tk.RIGHT, padx=(0, 6))
        _label(bar, "Keep-alive", fg=t.MUTED, bg=t.EDITOR).pack(side=tk.RIGHT, padx=(0, 8))

        frame = tk.Frame(view, bg=t.BORDER, padx=1, pady=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=28, pady=(0, 20))
        inner = tk.Frame(frame, bg=t.EDITOR)
        inner.pack(fill=tk.BOTH, expand=True)
        cols = ("size", "status", "vram")
        self.model_tree = ttk.Treeview(inner, columns=cols, show="tree headings",
                                       selectmode="browse")
        s = self.scale
        for col, title, width, anchor in (("#0", "Model", 260, "w"), ("size", "Size", 90, "e"),
                                          ("status", "Status", 170, "w"),
                                          ("vram", "VRAM", 90, "e")):
            self.model_tree.heading(col, text=title, anchor=anchor)
            self.model_tree.column(col, width=int(width * s), anchor=anchor,
                                   stretch=(col == "#0"))
        self.model_tree.tag_configure("loaded", foreground=t.GOOD)
        sbar = ttk.Scrollbar(inner, orient="vertical", command=self.model_tree.yview)
        self.model_tree.configure(yscrollcommand=sbar.set)
        self.model_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.model_tree.bind("<Double-1>", lambda _e: self._load_selected())
        self.model_tree.bind("<<TreeviewSelect>>", lambda _e: self._sync_sidebar_selection())

    def _keepalive_entry(self, master) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(master, textvariable=self.keepalive_var, width=60, height=28,
                             corner_radius=4, fg_color=t.INPUT, border_color="#3C3C3C",
                             text_color=t.FG, font=ctk.CTkFont(t.UI_FAMILY, 13), justify="right")
        entry.bind("<Return>", lambda _e: self._on_keepalive_changed())
        entry.bind("<FocusOut>", lambda _e: self._on_keepalive_changed())
        return entry

    # ---------------------------------------------------------------- GPU
    def _build_gpu(self, view: tk.Frame) -> None:
        self._view_header(view, "GPU", "Live NVIDIA telemetry from nvidia-smi")
        tiles = tk.Frame(view, bg=t.EDITOR)
        tiles.pack(fill=tk.X, padx=28)
        tiles.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="tile")
        self.vram_big = tk.StringVar(value="-")
        self.vram_sub = tk.StringVar(value="")
        for i, (title, var, sub) in enumerate((
                ("Utilization", self.gpu_vars["util"], None),
                ("VRAM", self.vram_big, self.vram_sub),
                ("Temperature", self.gpu_vars["temp"], None),
                ("Power", self.gpu_vars["power"], None))):
            card = Card(tiles, title)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            _label(card.body, var=var, font=t.FONT_BIG, fg=t.FG_STRONG).pack(anchor="w")
            if sub is not None:
                _label(card.body, var=sub, fg=t.MUTED, font=t.FONT_SMALL).pack(anchor="w")

        charts = tk.Frame(view, bg=t.EDITOR)
        charts.pack(fill=tk.BOTH, expand=True, padx=28, pady=(16, 20))
        charts.grid_columnconfigure((0, 1), weight=1, uniform="chart")
        charts.grid_rowconfigure(0, weight=1)
        c1 = Card(charts, "GPU utilization  (last 3 min)")
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.util_chart = LineChart(c1.body, t.ACCENT, "#0B3350")
        self.util_chart.pack(fill=tk.BOTH, expand=True)
        c2 = Card(charts, "VRAM usage  (last 3 min)")
        c2.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.vram_chart = LineChart(c2.body, t.PURPLE, "#3A2A4A")
        self.vram_chart.pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------------------------- settings
    def _build_settings(self, view: tk.Frame) -> None:
        self._view_header(view, "Settings", "Preferences for Local AI Manager")
        body = tk.Frame(view, bg=t.EDITOR)
        body.pack(fill=tk.BOTH, expand=True, padx=28)

        def entry(category: str, name: str, desc: str) -> tk.Frame:
            row = tk.Frame(body, bg=t.EDITOR)
            row.pack(fill=tk.X, pady=(0, 18))
            head = tk.Frame(row, bg=t.EDITOR)
            head.pack(anchor="w")
            _label(head, f"{category}: ", font=t.FONT_BOLD, fg=t.MUTED, bg=t.EDITOR).pack(side=tk.LEFT)
            _label(head, name, font=t.FONT_BOLD, fg=t.FG_STRONG, bg=t.EDITOR).pack(side=tk.LEFT)
            _label(row, desc, fg=t.MUTED, bg=t.EDITOR,
                   wraplength=int(760 * self.scale)).pack(anchor="w", pady=(2, 6))
            return row

        r = entry("Modes", "Gaming Mode",
                  "Unload all models and block loading from this app. WSL and Ollama keep running.")
        self._action(switch(r, "Enabled", self.gaming_var, self._on_gaming_toggled)).pack(anchor="w")

        r = entry("Startup", "Start With Windows",
                  "Adds 'LocalAIManager' to HKCU\\...\\CurrentVersion\\Run. "
                  "Changed only when you toggle it here.")
        self.startup_var = tk.BooleanVar(value=startup.is_enabled())
        switch(r, "Enabled", self.startup_var, self._on_startup_toggled).pack(anchor="w")

        r = entry("Models", "Auto Load Last Model",
                  "When the app starts, boot the distro if needed and load the last model you "
                  "loaded. Skipped while Gaming Mode is on.")
        self.autoload_var = tk.BooleanVar(value=self.cfg.auto_start_last_model)
        switch(r, "Enabled", self.autoload_var, self._on_autoload_toggled).pack(anchor="w")
        self.last_model_var = tk.StringVar()
        _label(r, var=self.last_model_var, fg=t.DIM, bg=t.EDITOR,
               font=t.FONT_SMALL).pack(anchor="w", pady=(4, 0))
        self._update_last_model_label()

        r = entry("Models", "Keep Alive (minutes)",
                  "How long Ollama keeps a model in memory after it is loaded from this app.")
        self._keepalive_entry(r).pack(anchor="w")

        mode = "wsl -u root (opt-in)" if self.cfg.service_control_as_root else "sudo -n (non-interactive)"
        r = entry("Environment", "Read-only",
                  f"WSL distro: {self.cfg.wsl_distro}\n"
                  f"Ollama service: {self.cfg.ollama_service}\n"
                  f"Ollama API: {self.cfg.ollama_base_url}\n"
                  f"Service control: {mode}\n"
                  f"Settings file: {settings_path()}\n"
                  "Edit settings.json to change these values.")
        secondary_button(r, "Open Settings Folder", self._open_settings_folder,
                         width=160).pack(anchor="w")

    def _open_settings_folder(self) -> None:
        folder = settings_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            self._set_status(f"Could not open {folder}: {exc}", "bad")

    # ---------------------------------------------------------------- output panel
    def _build_output_panel(self, panel: tk.Frame) -> None:
        head = tk.Frame(panel, bg=t.CHROME)
        head.pack(fill=tk.X)
        tab = tk.Frame(head, bg=t.CHROME)
        tab.pack(side=tk.LEFT, padx=(16, 0))
        _label(tab, "OUTPUT", font=t.FONT_SECTION, fg=t.FG_STRONG,
               bg=t.CHROME).pack(pady=(8, 4))
        tk.Frame(tab, bg=t.ACCENT, height=1).pack(fill=tk.X)
        for glyph, tip, cmd in ((t.ICON["close"], "Close Panel (Ctrl+J)", self.toggle_panel),
                                ("", "Clear Output", self._clear_log)):
            btn = tk.Label(head, text=glyph, font=(t.ICON_FAMILY, 9), bg=t.CHROME, fg=t.MUTED,
                           cursor="hand2", padx=6)
            btn.pack(side=tk.RIGHT, padx=(0, 6), pady=4)
            btn.bind("<Button-1>", lambda _e, c=cmd: c())
            btn.bind("<Enter>", lambda _e, b=btn: b.configure(fg=t.FG_STRONG))
            btn.bind("<Leave>", lambda _e, b=btn: b.configure(fg=t.MUTED))
        body = tk.Frame(panel, bg=t.CHROME)
        body.pack(fill=tk.BOTH, expand=True, padx=(16, 0), pady=(6, 0))
        self.log_text = tk.Text(body, bg=t.CHROME, fg=t.FG, insertbackground=t.FG, relief="flat",
                                wrap="word", font=t.FONT_MONO, highlightthickness=0,
                                state="disabled", padx=0, pady=0)
        self.log_text.tag_configure("warn", foreground=t.WARN)
        self.log_text.tag_configure("error", foreground=t.BAD)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    # ---------------------------------------------------------------- status bar
    def _build_status_bar(self) -> None:
        bar = tk.Frame(self.root, bg=t.STATUS_BG, height=int(22 * self.scale))
        bar.grid(row=1, column=0, sticky="ew")
        bar.pack_propagate(False)
        self.status_bar = bar
        self.sb_remote = StatusItem(bar, f"WSL: {self.cfg.wsl_distro}",
                                    command=lambda: self.show_view("dashboard"))
        self.sb_remote.set_colors("#16825D", "#1A9A6C")
        self.sb_remote.pack(side=tk.LEFT, fill=tk.Y)
        self.st_service = StatusItem(bar, "ollama: ...", command=lambda: self.show_view("dashboard"))
        self.st_service.pack(side=tk.LEFT, fill=tk.Y)
        self.st_icon = StatusItem(bar, "", icon=True)
        self.st_icon.pack(side=tk.LEFT, fill=tk.Y)
        self.status_var = tk.StringVar(value="Starting...")
        self.st_message = StatusItem(bar)
        self.st_message.configure(textvariable=self.status_var, padx=0)
        self.st_message.pack(side=tk.LEFT, fill=tk.Y)

        self.st_gaming = StatusItem(bar, "Gaming: OFF", command=lambda: self.show_view("settings"))
        self.st_gaming.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 6))
        self.st_gpu = StatusItem(bar, "GPU -", command=lambda: self.show_view("gpu"))
        self.st_gpu.pack(side=tk.RIGHT, fill=tk.Y)
        self.st_vram = StatusItem(bar, "VRAM -", command=lambda: self.show_view("gpu"))
        self.st_vram.pack(side=tk.RIGHT, fill=tk.Y)
        self.st_model = StatusItem(bar, "No model loaded", command=lambda: self.show_view("models"))
        self.st_model.pack(side=tk.RIGHT, fill=tk.Y)
        self._status_items = [self.st_service, self.st_icon, self.st_message, self.st_gaming,
                              self.st_gpu, self.st_vram, self.st_model]
        self._paint_status_bar()

    def _paint_status_bar(self) -> None:
        on = self.cfg.gaming_mode_enabled
        base = t.STATUS_GAMING if on else t.STATUS_BG
        hover = t.STATUS_GAMING_HOVER if on else t.STATUS_HOVER
        self.status_bar.configure(bg=base)
        for item in self._status_items:
            item.set_colors(base, hover)
        self.st_gaming.configure(text="Gaming Mode: ON" if on else "Gaming: OFF")

    # ================================================================ navigation
    def show_view(self, key: str) -> None:
        self.views[key].tkraise()
        self.tabs.set_active(key)
        self.activity.set_active(key)
        self._current_view = key

    def _on_activity(self, key: str) -> None:
        # VS Code: clicking the active icon toggles the side bar.
        if key == self._current_view and self.sidebar.winfo_ismapped():
            self.toggle_sidebar()
            return
        if not self.sidebar.winfo_ismapped():
            self.toggle_sidebar()
        self.show_view(key)

    def toggle_sidebar(self) -> None:
        if self.sidebar.winfo_ismapped():
            self.sidebar.pack_forget()
            self.sidebar_border.pack_forget()
        else:
            self.sidebar.pack(side=tk.LEFT, fill=tk.Y, before=self.editor_col)
            self.sidebar_border.pack(side=tk.LEFT, fill=tk.Y, before=self.editor_col)

    def toggle_panel(self) -> None:
        if self._panel_visible:
            self.editor_col.forget(self.panel)
        else:
            self.editor_col.add(self.panel, stretch="never", height=int(140 * self.scale),
                                minsize=int(60 * self.scale))
        self._panel_visible = not self._panel_visible

    def _bind_shortcuts(self) -> None:
        r = self.root
        r.bind("<Control-b>", lambda _e: self.toggle_sidebar())
        r.bind("<Control-j>", lambda _e: self.toggle_panel())
        r.bind("<F5>", lambda _e: self.request_refresh())
        r.bind("<Control-comma>", lambda _e: self.show_view("settings"))
        for i, (key, _title) in enumerate(VIEWS, start=1):
            r.bind(f"<Control-Key-{i}>", lambda _e, k=key: self.show_view(k))

    def _reveal_model(self, name: str) -> None:
        self.show_view("models")
        if self.model_tree.exists(name):
            self.model_tree.selection_set(name)
            self.model_tree.see(name)
        self._sync_sidebar_selection()

    def _sync_sidebar_selection(self) -> None:
        selected = self._selected_model()
        for name, row in self._sb_model_rows.items():
            row.set_selected(name == selected)

    # ================================================================ queue
    def _post(self, fn: Callable[[], None]) -> None:
        """Schedule `fn` on the Tk thread. Safe to call from any thread."""
        self._ui_queue.put(fn)

    def _drain_ui_queue(self) -> None:
        for _ in range(200):
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # noqa: BLE001 - keep the UI loop alive
                log.exception("UI update failed")
        if not self._closing:
            self.root.after(100, self._drain_ui_queue)

    def _append_log(self, line: str, level: int = logging.INFO) -> None:
        tag = "error" if level >= logging.ERROR else "warn" if level >= logging.WARNING else ""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n", tag)
        excess = int(self.log_text.index("end-1c").split(".")[0]) - MAX_LOG_LINES
        if excess > 0:
            self.log_text.delete("1.0", f"{excess + 1}.0")
        self.log_text.configure(state="disabled")
        self.log_text.see("end")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_status(self, text: str, kind: str = "muted") -> None:
        self.status_var.set(text)
        glyph = {"good": t.ICON["check"], "bad": t.ICON["warning"], "warn": t.ICON["warning"],
                 "busy": t.ICON["sync"]}.get(kind, "")
        self.st_icon.configure(text=glyph)

    # ================================================================ monitor
    def _start_monitor(self) -> None:
        self._full_refresh.set()
        self._monitor = threading.Thread(target=self._monitor_loop, name="monitor", daemon=True)
        self._monitor.start()

    def request_refresh(self) -> None:
        """Ask the monitor for an immediate full refresh (WSL included)."""
        self._full_refresh.set()
        self._wake.set()

    def _monitor_loop(self) -> None:
        tick = 0
        while not self._stop.is_set():
            full = self._full_refresh.is_set() or tick % WSL_REFRESH_EVERY == 0
            self._full_refresh.clear()
            try:
                snap = collect_snapshot(self.cfg, include_wsl=full)
            except Exception:  # noqa: BLE001 - monitor must survive anything
                log.exception("Status refresh failed")
            else:
                self._post(lambda s=snap: self._apply_snapshot(s))
            tick += 1
            self._wake.wait(self.cfg.gpu_poll_interval_ms / 1000)
            self._wake.clear()

    def _apply_snapshot(self, snap: Snapshot) -> None:
        if snap.wsl is not None:
            self._apply_wsl(snap)
        if snap.ollama_version is not None:
            self.api_var.set(f"Reachable (v{snap.ollama_version})")
            kind = "good"
            self.sb_api.set(color=t.GOOD, right=f"v{snap.ollama_version}")
        else:
            self.api_var.set("Not reachable")
            kind = "bad"
            self.sb_api.set(color=t.BAD, right="offline")
        self.api_label.configure(fg=KIND_COLOR[kind])
        self._apply_models(snap.models, snap.running or [], snap.ollama_version is not None)
        self._apply_gpu(snap.gpu)
        if self.status_var.get() == "Starting..." and not self._busy:
            self._set_status("Ready.")

    def _apply_wsl(self, snap: Snapshot) -> None:
        st = snap.wsl
        assert st is not None
        distro = st.find(self.cfg.wsl_distro)
        if not st.wsl_available:
            text, kind, short = st.error or "WSL not available", "bad", "unavailable"
        elif distro is None:
            text, kind, short = st.error or "Not installed", "bad", "not found"
        else:
            text = f"{distro.state} (WSL {distro.version})"
            kind = "good" if distro.running else "muted"
            short = distro.state.lower()
        self.distro_var.set(text)
        self.distro_label.configure(fg=KIND_COLOR[kind])
        self.sb_distro.set(color=KIND_COLOR[kind], right=short)

        state = snap.service_state
        kind = "good" if state == "active" else "muted" if state == "distro stopped" else "bad"
        self.service_var.set(state)
        self.service_label.configure(fg=KIND_COLOR[kind])
        self.sb_service.set(color=KIND_COLOR[kind], right=state if len(state) < 16 else "")
        self.st_service.configure(text=f"ollama: {state}")

    def _apply_models(self, models: list[ollama.Model], running: list[ollama.RunningModel],
                      reachable: bool) -> None:
        self._running_names = [m.name for m in running]
        by_name = {m.name: m for m in running}
        rows: dict[str, tuple[str, str, str]] = {}
        for m in models:
            r = by_name.get(m.name)
            status = f"Loaded {format_expiry(r.expires_at)}".strip() if r else ""
            vram = ollama.human_size(r.size_vram) if r else ""
            rows[m.name] = (m.size_human, status, vram)
        for r in running:  # loaded but not in tags (unlikely)
            rows.setdefault(r.name, ("", f"Loaded {format_expiry(r.expires_at)}".strip(),
                                     ollama.human_size(r.size_vram)))
        tree = self.model_tree
        for iid in tree.get_children():
            if iid not in rows:
                tree.delete(iid)
        for name, values in rows.items():
            tags = ("loaded",) if name in by_name else ()
            if tree.exists(name):
                tree.item(name, values=values, tags=tags)
            else:
                tree.insert("", "end", iid=name, text=name, values=values, tags=tags)
        self._sync_sidebar_models(list(rows), set(by_name), reachable)

        if not reachable:
            self.loaded_var.set("Loaded: unknown (Ollama API not reachable)")
            self.loaded_label.configure(fg=t.MUTED)
            self.st_model.configure(text="Ollama offline")
        elif running:
            parts = [f"{r.name} ({ollama.human_size(r.size_vram)} VRAM"
                     f"{', ' + format_expiry(r.expires_at) if format_expiry(r.expires_at) else ''})"
                     for r in running]
            self.loaded_var.set("Loaded: " + "; ".join(parts))
            self.loaded_label.configure(fg=t.GOOD)
            self.st_model.configure(text="● " + ", ".join(self._running_names))
        else:
            self.loaded_var.set("Loaded: none")
            self.loaded_label.configure(fg=t.FG)
            self.st_model.configure(text="No model loaded")

        if self.cfg.gaming_mode_enabled and running:
            self.gaming_warn_var.set("Gaming Mode is ON, but another client loaded: "
                                     + ", ".join(self._running_names)
                                     + ". Use Unload All to free VRAM.")
        elif self.cfg.gaming_mode_enabled:
            self.gaming_warn_var.set("Gaming Mode is ON: model loading is disabled.")
        else:
            self.gaming_warn_var.set("")

    def _apply_gpu(self, s: gpu.GpuSample) -> None:
        v = self.gpu_vars
        if not s.available:
            v["name"].set("No telemetry (nvidia-smi unavailable)")
            for key in ("util", "mem", "temp", "power"):
                v[key].set("-")
            self.vram_big.set("-")
            self.vram_sub.set("")
            self.util_bar.set(0)
            self.vram_bar.set(0)
            self.sb_gpu.set(color=t.DIM, right="n/a")
            self.st_gpu.configure(text="GPU n/a")
            self.st_vram.configure(text="VRAM n/a")
            return
        v["name"].set(s.name)
        v["util"].set(f"{s.util_percent:.0f}%")
        v["mem"].set(f"{s.mem_used_mb / 1024:.1f} / {s.mem_total_mb / 1024:.1f} GB "
                     f"({s.mem_percent_text})")
        v["temp"].set(f"{s.temp_c:.0f} °C")
        v["power"].set(f"{s.power_w:.0f} W")
        self.vram_big.set(f"{s.mem_used_mb / 1024:.1f} GB")
        self.vram_sub.set(f"of {s.mem_total_mb / 1024:.1f} GB  ({s.mem_percent_text})")
        self.util_bar.set(s.util_percent / 100)
        self.vram_bar.set(s.mem_percent / 100)
        self.util_chart.push(s.util_percent)
        self.vram_chart.push(s.mem_percent)
        self.sb_gpu.set(color=t.GOOD, right=f"{s.temp_c:.0f}°C")
        self.st_gpu.configure(text=f"GPU {s.util_percent:.0f}%  {s.temp_c:.0f}°C")
        self.st_vram.configure(text=f"VRAM {s.mem_used_mb / 1024:.1f}/{s.mem_total_mb / 1024:.1f} GB")

    # ================================================================ actions
    def _update_buttons(self) -> None:
        for w in self._action_widgets:
            w.configure(state="disabled" if self._busy else "normal")
        if self.cfg.gaming_mode_enabled:
            for w in self._load_buttons:
                w.configure(state="disabled")
        self._paint_status_bar()

    def _run_action(self, label: str, fn: Callable[[], tuple[bool, str]],
                    on_done: Callable[[], None] | None = None) -> bool:
        """Run `fn` on a worker thread. Only one action at a time."""
        if self._busy:
            self._set_status("Another operation is still running. Please wait.", "warn")
            return False
        self._busy = True
        self._update_buttons()
        self._set_status(f"{label}...", "busy")
        log.info("%s...", label)

        def worker() -> None:
            try:
                ok, msg = fn()
            except Exception as exc:  # noqa: BLE001 - report any failure to the user
                log.exception("%s failed", label)
                ok, msg = False, f"{label} failed: {exc}"
            else:
                (log.info if ok else log.warning)("%s", msg)
            self._post(lambda: self._finish_action(ok, msg, on_done))

        threading.Thread(target=worker, name=f"action: {label}", daemon=True).start()
        return True

    def _finish_action(self, ok: bool, msg: str, on_done: Callable[[], None] | None) -> None:
        self._busy = False
        self._update_buttons()
        self._set_status(msg, "good" if ok else "bad")
        if on_done:
            on_done()
        self.request_refresh()

    def _selected_model(self) -> str | None:
        sel = self.model_tree.selection()
        return sel[0] if sel else None

    # ---- WSL / service
    def _start_distro(self) -> None:
        d = self.cfg.wsl_distro
        self._run_action(f"Starting {d}", lambda: self._result(wsl.start_distro(d), "started"))

    def _stop_distro(self) -> None:
        d = self.cfg.wsl_distro
        if not messagebox.askyesno(
                "Stop distro",
                f"Terminate {d}? This stops the Ollama service, unloads all models and "
                "closes any open WSL terminals for this distro.", parent=self.root):
            return
        self._run_action(f"Stopping {d}", lambda: self._result(wsl.terminate_distro(d), "terminated"))

    def _start_service(self) -> None:
        c = self.cfg
        self._run_action("Starting Ollama service", lambda: self._result(
            wsl.control_service(c.wsl_distro, c.ollama_service, "start", c.service_control_as_root),
            "succeeded"))

    def _stop_service(self) -> None:
        c = self.cfg
        if not messagebox.askyesno(
                "Stop service",
                f"Stop the '{c.ollama_service}' service? All models are unloaded and clients "
                "such as Continue lose access until it is started again.", parent=self.root):
            return
        self._run_action("Stopping Ollama service", lambda: self._result(
            wsl.control_service(c.wsl_distro, c.ollama_service, "stop", c.service_control_as_root),
            "succeeded"))

    @staticmethod
    def _result(msg: str, success_word: str) -> tuple[bool, str]:
        return success_word in msg and "fail" not in msg.lower(), msg

    # ---- models
    def _load_selected(self) -> None:
        name = self._selected_model()
        if not name:
            messagebox.showinfo("Load model", "Select a model in the list first.", parent=self.root)
            return
        if self.cfg.gaming_mode_enabled:
            messagebox.showinfo("Load model", "Gaming Mode is ON. Disable it before loading a model.",
                                parent=self.root)
            return
        others = [n for n in self._running_names if n != name]
        unload_first = False
        if others:
            answer = messagebox.askyesnocancel(
                "Load model",
                f"Currently loaded: {', '.join(others)}.\n\n"
                f"Unload it before loading {name}?\n"
                "Yes = unload first (recommended), No = keep both loaded.", parent=self.root)
            if answer is None:
                return
            unload_first = answer
        base, ka = self.cfg.ollama_base_url, self.cfg.keep_alive_minutes

        def work() -> tuple[bool, str]:
            if unload_first:
                for other in others:
                    ollama.unload_model(other, base)
                left = ollama.wait_until_unloaded(others, base)
                if left:
                    return False, f"Could not unload {', '.join(left)}; not loading {name}."
            ollama.load_model(name, ka, base)
            running = ollama.get_running(base) or []
            if name not in [m.name for m in running]:
                return False, f"Load request for {name} finished, but Ollama does not list it as loaded."
            self._post(lambda: self._remember_model(name))
            return True, f"Loaded {name} (keep-alive {ka} min)."

        self._run_action(f"Loading {name}", work)

    def _remember_model(self, name: str) -> None:
        self.cfg.last_model = name
        self.cfg.save()
        self._update_last_model_label()

    def _unload_selected(self) -> None:
        name = self._selected_model()
        if not name:
            messagebox.showinfo("Unload model", "Select a model in the list first.", parent=self.root)
            return
        if name not in self._running_names:
            self._set_status(f"{name} is not loaded.")
            return
        self._run_action(f"Unloading {name}", lambda: self._unload([name]))

    def _unload_all(self) -> None:
        if not self._running_names:
            self._set_status("No models are loaded.")
            return
        names = list(self._running_names)
        self._run_action("Unloading all models", lambda: self._unload(names))

    def _unload(self, names: list[str]) -> tuple[bool, str]:
        base = self.cfg.ollama_base_url
        for n in names:
            ollama.unload_model(n, base)
        left = ollama.wait_until_unloaded(names, base)
        if left:
            return False, f"Still loaded after 30s: {', '.join(left)}."
        return True, f"Unloaded: {', '.join(names)}."

    def _auto_load_last_model(self) -> None:
        c = self.cfg
        name = c.last_model
        if c.gaming_mode_enabled:
            log.info("Auto-load skipped: Gaming Mode is ON.")
            return
        if not name:
            log.info("Auto-load skipped: no last model recorded yet.")
            return

        def work() -> tuple[bool, str]:
            st = wsl.detect()
            distro = st.find(c.wsl_distro)
            if distro is None:
                return False, f"Auto-load skipped: distro {c.wsl_distro} not found."
            if not distro.running:
                log.info("Auto-load: starting %s", c.wsl_distro)
                wsl.start_distro(c.wsl_distro)
            waited = 0.0
            while ollama.get_version(c.ollama_base_url) is None:
                if waited >= AUTOLOAD_API_WAIT_S or self._stop.is_set():
                    return False, "Auto-load skipped: Ollama API did not become reachable."
                self._stop.wait(2)
                waited += 2
            if name not in [m.name for m in ollama.get_models(c.ollama_base_url)]:
                return False, f"Auto-load skipped: {name} is not installed."
            if c.gaming_mode_enabled:
                return False, "Auto-load skipped: Gaming Mode is ON."
            ollama.load_model(name, c.keep_alive_minutes, c.ollama_base_url)
            return True, f"Auto-loaded {name}."

        self._run_action(f"Auto-loading {name}", work)

    # ---- settings
    def _on_gaming_toggled(self) -> None:
        want = bool(self.gaming_var.get())
        self.gaming_var.set(self.cfg.gaming_mode_enabled)  # reflect real state until done
        gm = gaming.GamingMode(self.cfg)

        def work() -> tuple[bool, str]:
            r = gm.enable() if want else gm.disable()
            return r.ok, r.message

        def done() -> None:
            self.gaming_var.set(self.cfg.gaming_mode_enabled)
            self._update_buttons()

        self._run_action("Enabling Gaming Mode" if want else "Disabling Gaming Mode", work, done)

    def _on_startup_toggled(self) -> None:
        want = bool(self.startup_var.get())
        msg = startup.enable(self.cfg) if want else startup.disable(self.cfg)
        actual = startup.is_enabled()
        self.startup_var.set(actual)
        self._set_status(msg, "good" if actual == want else "bad")
        log.info(msg)

    def _on_autoload_toggled(self) -> None:
        self.cfg.auto_start_last_model = bool(self.autoload_var.get())
        self.cfg.save()
        self._update_last_model_label()

    def _update_last_model_label(self) -> None:
        self.last_model_var.set(f"Last model: {self.cfg.last_model or '(none loaded yet)'}")

    def _on_keepalive_changed(self) -> None:
        try:
            value = int(self.keepalive_var.get())
        except ValueError:
            value = self.cfg.keep_alive_minutes
        value = min(max(value, 1), 1440)
        self.keepalive_var.set(str(value))
        if value != self.cfg.keep_alive_minutes:
            self.cfg.keep_alive_minutes = value
            self.cfg.save()
            log.info("Keep-alive set to %d minutes (applies to the next load).", value)

    # ================================================================ shutdown
    def on_close(self) -> None:
        if self._busy and not messagebox.askyesno(
                "Quit", "An operation is still running. Quit anyway?", parent=self.root):
            return
        self._closing = True
        self._stop.set()
        self._wake.set()
        if self._monitor is not None:
            self._monitor.join(timeout=3)
        # Every in-app setting is saved when it changes, so only the window size
        # is new here. Update it on the on-disk copy so edits made to
        # settings.json while the app was running are not overwritten.
        disk = Config.load()
        try:
            # CTk scales geometry by DPI; store unscaled values.
            factor = (ctk.ScalingTracker.get_window_scaling(self.root)
                      if isinstance(self.root, ctk.CTk) else 1.0)
            disk.window_width = max(int(self.root.winfo_width() / factor), 640)
            disk.window_height = max(int(self.root.winfo_height() / factor), 480)
        except tk.TclError:
            pass
        disk.save()
        logging.getLogger().removeHandler(self._log_handler)
        self.root.destroy()


def _set_app_user_model_id() -> None:
    """Give the process its own taskbar identity (so our icon is used, not python's)."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LocalAIManager.App")
    except (AttributeError, OSError):
        pass


def run() -> None:
    _set_app_user_model_id()
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
