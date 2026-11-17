"""JSON-backed settings store.

User preferences persist to ``%APPDATA%\\LocalAIManager\\settings.json``
(override the directory with ``LOCAL_AI_MANAGER_CONFIG_DIR``). Defaults live
in the :class:`Config` dataclass, not in a file. Gaming Mode, Start with
Windows and auto-load of the last model are all OFF by default.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"
LEGACY_FILENAME = "config.json"


def config_dir() -> Path:
    """Return the per-user settings directory (not created here)."""
    override = os.environ.get("LOCAL_AI_MANAGER_CONFIG_DIR", "").strip()
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "LocalAIManager"
    return Path.home() / ".local-ai-manager"


def settings_path() -> Path:
    return config_dir() / SETTINGS_FILENAME


@dataclass
class Config:
    """Persistent user settings with safe defaults."""

    # Ollama (loopback only; the app never changes OLLAMA_HOST)
    ollama_base_url: str = "http://127.0.0.1:11434"
    keep_alive_minutes: int = 30
    last_model: str = ""
    auto_start_last_model: bool = False   # OFF by default

    # WSL2 / systemd
    wsl_distro: str = "Ubuntu-24.04"
    ollama_service: str = "ollama"
    # Opt-in: control the service with `wsl -u root` instead of `sudo -n`.
    service_control_as_root: bool = False

    # Monitoring
    gpu_poll_interval_ms: int = 2000

    # Modes -- OFF by default
    gaming_mode_enabled: bool = False
    start_with_windows: bool = False

    # Window geometry (last used)
    window_width: int = 1200
    window_height: int = 800

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Build a Config, keeping only known keys whose value type matches."""
        cfg = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            default = getattr(cfg, f.name)
            # bool is a subclass of int; require exact type for both.
            if type(value) is not type(default):
                log.warning("Ignoring setting %r with invalid value %r", f.name, value)
                continue
            setattr(cfg, f.name, value)
        cfg._clamp()
        return cfg

    def _clamp(self) -> None:
        """Keep numeric settings within sane bounds."""
        self.gpu_poll_interval_ms = min(max(self.gpu_poll_interval_ms, 500), 60_000)
        self.keep_alive_minutes = min(max(self.keep_alive_minutes, 1), 24 * 60)
        self.window_width = min(max(self.window_width, 640), 4000)
        self.window_height = min(max(self.window_height, 480), 3000)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """Load settings, falling back to defaults on any problem."""
        path = path or settings_path()
        candidates = [path]
        if path.name == SETTINGS_FILENAME:
            candidates.append(path.with_name(LEGACY_FILENAME))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log.warning("Could not read settings %s (%s); using defaults.", candidate, exc)
                return cls()
            if not isinstance(data, dict):
                log.warning("Settings file %s is not a JSON object; using defaults.", candidate)
                return cls()
            return cls.from_dict(data)
        return cls()

    def save(self, path: Path | None = None) -> bool:
        """Atomically persist settings. Returns False (and logs) on failure."""
        path = path or settings_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.to_dict(), fh, indent=2)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            return True
        except OSError as exc:
            log.error("Could not save settings to %s: %s", path, exc)
            return False


_CONFIG: Config | None = None


def get_config() -> Config:
    """Return the process-wide settings singleton, loading it on first use."""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = Config.load()
    return _CONFIG


def reset_config_cache() -> None:
    """Forget the cached singleton (used by tests)."""
    global _CONFIG
    _CONFIG = None
