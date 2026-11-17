"""Application entry point: logging setup, then the Tkinter GUI."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .config import config_dir

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # The windowed (PyInstaller) build has no stderr.
    if sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(stream)
    try:
        log_dir = config_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "app.log", maxBytes=1_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(fh)
    except OSError as exc:
        root.warning("File logging disabled: %s", exc)


def main() -> int:
    """Create and run the Tkinter application. Returns a process exit code."""
    setup_logging()
    logging.getLogger(__name__).info("Local AI Manager starting.")
    from .ui import run
    run()
    logging.getLogger(__name__).info("Local AI Manager exited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
