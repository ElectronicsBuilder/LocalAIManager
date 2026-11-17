"""Gaming Mode.

Enabling Gaming Mode frees GPU memory for games by unloading every model
Ollama currently has in memory, then verifying via /api/ps that they are
gone. WSL and the Ollama service keep running, so leaving Gaming Mode is
instant. While active, the app will not load models (manually or via
auto-load). Disabling it only clears the flag; nothing is reloaded.

Gaming Mode is OFF by default (see config.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import ollama
from .config import Config, get_config

log = logging.getLogger(__name__)


@dataclass
class GamingResult:
    ok: bool
    message: str
    unloaded: list[str] = field(default_factory=list)
    still_loaded: list[str] = field(default_factory=list)


class GamingMode:
    """Controller for Gaming Mode. Methods block; call them off the Tk thread."""

    def __init__(self, cfg: Config | None = None, unload_timeout: float = 30) -> None:
        self.cfg = cfg or get_config()
        self.unload_timeout = unload_timeout

    def is_enabled(self) -> bool:
        return bool(self.cfg.gaming_mode_enabled)

    def enable(self) -> GamingResult:
        """Unload all models, verify, and persist the flag.

        The flag is set before unloading so that nothing in this app reloads a
        model mid-transition; it stays set even if verification fails, so the
        user can retry while still protected from auto-load.
        """
        self.cfg.gaming_mode_enabled = True
        self.cfg.save()
        base = self.cfg.ollama_base_url

        running = ollama.get_running(base)
        if running is None:
            msg = "Gaming Mode ON. Ollama is not reachable, so no models are loaded by it."
            log.info(msg)
            return GamingResult(ok=True, message=msg)
        names = [m.name for m in running]
        if not names:
            msg = "Gaming Mode ON. No models were loaded."
            log.info(msg)
            return GamingResult(ok=True, message=msg)

        errors = []
        for name in names:
            try:
                log.info("Gaming Mode: unloading %s", name)
                ollama.unload_model(name, base)
            except ollama.OllamaError as exc:
                errors.append(str(exc))
        try:
            remaining = ollama.wait_until_unloaded(names, base, timeout=self.unload_timeout)
        except ollama.OllamaError as exc:
            errors.append(str(exc))
            remaining = names
        unloaded = [n for n in names if n not in remaining]

        if remaining:
            msg = (f"Gaming Mode ON, but still loaded after {self.unload_timeout:.0f}s: "
                   f"{', '.join(remaining)}.")
            if errors:
                msg += " " + " ".join(errors)
            log.warning(msg)
            return GamingResult(ok=False, message=msg, unloaded=unloaded, still_loaded=remaining)
        msg = f"Gaming Mode ON. Unloaded: {', '.join(unloaded)}."
        log.info(msg)
        return GamingResult(ok=True, message=msg, unloaded=unloaded)

    def disable(self) -> GamingResult:
        """Clear the flag. Models are NOT reloaded automatically."""
        self.cfg.gaming_mode_enabled = False
        self.cfg.save()
        msg = "Gaming Mode OFF. Load a model manually when needed."
        log.info(msg)
        return GamingResult(ok=True, message=msg)
