"""Ollama HTTP API client (standard library only).

Ollama runs inside WSL2 as a systemd service and is reached through WSL's
localhost forwarding at http://127.0.0.1:11434. This module never starts or
stops the server process; service control lives in :mod:`wsl`.

Endpoints used:
  GET  /api/version   - reachability
  GET  /api/tags      - installed models
  GET  /api/ps        - models currently loaded in memory
  POST /api/generate  - load (keep_alive > 0) / unload (keep_alive = 0)
"""

from __future__ import annotations

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:11434"


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size} B"  # unreachable


@dataclass
class Model:
    name: str
    size: int = 0          # bytes on disk
    modified_at: str = ""

    @property
    def size_human(self) -> str:
        return human_size(self.size)


@dataclass
class RunningModel:
    name: str
    size: int = 0          # bytes in memory
    size_vram: int = 0     # bytes in GPU memory
    expires_at: str = ""   # ISO timestamp from Ollama


class OllamaError(Exception):
    """Raised for API failures in operations where the caller needs details."""


def _http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None,
               timeout: float = 15) -> tuple[int, Any]:
    """HTTP request returning (status, parsed_body). status 0 = connection failure."""
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            return exc.code, (json.loads(body) if body.strip() else {"error": exc.reason})
        except (OSError, ValueError):
            return exc.code, {"error": str(exc)}
    except urllib.error.URLError as exc:
        return 0, {"error": f"Connection failed: {exc.reason}"}
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return 0, {"error": str(exc)}


def _error_text(code: int, body: Any) -> str:
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return f"HTTP {code}"


def get_version(base_url: str = DEFAULT_BASE_URL) -> str | None:
    """Return the server version, or None if unreachable."""
    code, body = _http_json(f"{base_url}/api/version", timeout=3)
    if code == 200 and isinstance(body, dict):
        return str(body.get("version", "unknown"))
    return None


def is_running(base_url: str = DEFAULT_BASE_URL) -> bool:
    return get_version(base_url) is not None


def get_models(base_url: str = DEFAULT_BASE_URL) -> list[Model]:
    """Return installed models (empty list if unreachable)."""
    code, body = _http_json(f"{base_url}/api/tags", timeout=8)
    if code != 200 or not isinstance(body, dict):
        return []
    models = []
    for m in body.get("models") or []:
        if isinstance(m, dict) and m.get("name"):
            models.append(Model(name=m["name"], size=int(m.get("size") or 0),
                                modified_at=str(m.get("modified_at", ""))))
    return sorted(models, key=lambda m: m.name)


def get_running(base_url: str = DEFAULT_BASE_URL) -> list[RunningModel] | None:
    """Return models loaded in memory, or None if the server is unreachable."""
    code, body = _http_json(f"{base_url}/api/ps", timeout=5)
    if code != 200 or not isinstance(body, dict):
        return None
    running = []
    for m in body.get("models") or []:
        if isinstance(m, dict) and (m.get("name") or m.get("model")):
            running.append(RunningModel(
                name=m.get("name") or m.get("model"),
                size=int(m.get("size") or 0),
                size_vram=int(m.get("size_vram") or 0),
                expires_at=str(m.get("expires_at", "")),
            ))
    return running


def load_model(name: str, keep_alive_minutes: int,
               base_url: str = DEFAULT_BASE_URL, timeout: float = 600) -> None:
    """Load `name` into memory and keep it for `keep_alive_minutes`.

    An empty generate request makes Ollama load the model without generating.
    Raises OllamaError on failure.
    """
    code, body = _http_json(
        f"{base_url}/api/generate", method="POST",
        payload={"model": name, "keep_alive": f"{int(keep_alive_minutes)}m", "stream": False},
        timeout=timeout,
    )
    if code != 200:
        raise OllamaError(f"Load of '{name}' failed: {_error_text(code, body)}")


def unload_model(name: str, base_url: str = DEFAULT_BASE_URL) -> None:
    """Ask Ollama to unload `name` immediately. Raises OllamaError on failure."""
    code, body = _http_json(
        f"{base_url}/api/generate", method="POST",
        payload={"model": name, "keep_alive": 0, "stream": False},
        timeout=60,
    )
    if code != 200:
        raise OllamaError(f"Unload of '{name}' failed: {_error_text(code, body)}")


def wait_until_unloaded(names: list[str] | None = None, base_url: str = DEFAULT_BASE_URL,
                        timeout: float = 30, interval: float = 0.5,
                        sleep=time.sleep, clock=time.monotonic) -> list[str]:
    """Poll /api/ps until `names` (or all models, if None) are gone.

    Returns the names still loaded when the timeout expired (empty = success).
    Raises OllamaError if the server becomes unreachable.
    """
    deadline = clock() + timeout
    while True:
        running = get_running(base_url)
        if running is None:
            raise OllamaError("Ollama became unreachable while waiting for unload.")
        remaining = [m.name for m in running if names is None or m.name in names]
        if not remaining or clock() >= deadline:
            return remaining
        sleep(interval)
