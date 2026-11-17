"""Optional 'Start with Windows' (per-user, no elevation).

Writes or removes the value ``LocalAIManager`` under
``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``. This happens only
when the user explicitly toggles the setting in the UI; nothing here runs at
import time. OFF by default.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # non-Windows; feature unavailable
    winreg = None  # type: ignore[assignment]

from .config import Config, get_config

log = logging.getLogger(__name__)

APP_NAME = "LocalAIManager"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> str:
    """Command line that starts this app at sign-in."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    run_py = Path(__file__).resolve().parents[2] / "run.py"
    return f'"{interpreter}" "{run_py}"'


def registered_command() -> str | None:
    """Return the current Run value, or None if absent/unavailable."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return str(value)
    except OSError:
        return None


def is_enabled() -> bool:
    return registered_command() is not None


def enable(cfg: Config | None = None) -> str:
    cfg = cfg or get_config()
    if winreg is None:
        return "Start with Windows is only available on Windows."
    command = launch_command()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
    except OSError as exc:
        log.error("Failed to enable Start with Windows: %s", exc)
        return f"Failed to enable Start with Windows: {exc}"
    cfg.start_with_windows = True
    cfg.save()
    log.info("Start with Windows enabled: %s", command)
    return "Start with Windows enabled."


def disable(cfg: Config | None = None) -> str:
    cfg = cfg or get_config()
    if winreg is None:
        return "Start with Windows is only available on Windows."
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass  # already absent
    except OSError as exc:
        log.error("Failed to disable Start with Windows: %s", exc)
        return f"Failed to disable Start with Windows: {exc}"
    cfg.start_with_windows = False
    cfg.save()
    log.info("Start with Windows disabled.")
    return "Start with Windows disabled."
