"""WSL2 and systemd service helpers.

All commands are passed to ``wsl.exe`` as argument lists with ``--exec`` so
no Linux shell interprets them. Distro and service names are validated
before use. Failures are returned as readable strings, never raised.

Privileged service operations use ``sudo -n`` (non-interactive): if the user
has not authorized passwordless sudo for systemctl, the command fails
immediately with a clear message. The app never stores or prompts for a sudo
password and never edits sudoers. Running as WSL root (``wsl -u root``)
is used only if the user explicitly opts in via the
``service_control_as_root`` setting.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class DistroInfo:
    name: str
    state: str = ""          # e.g. "Running", "Stopped"
    version: str = ""        # "1" or "2"
    is_default: bool = False

    @property
    def running(self) -> bool:
        return self.state.lower() == "running"


@dataclass
class WslStatus:
    """Snapshot of the WSL environment."""

    wsl_available: bool = False
    distros: list[DistroInfo] = field(default_factory=list)
    error: str = ""

    def find(self, name: str) -> DistroInfo | None:
        for d in self.distros:
            if d.name.lower() == name.lower():
                return d
        return None


def is_valid_name(name: str) -> bool:
    """True if `name` is a safe distro/service identifier."""
    return bool(_NAME_RE.match(name or ""))


def _decode(raw: bytes) -> str:
    """Decode wsl.exe output, which is UTF-16LE unless WSL_UTF8=1 is honored."""
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or b"\x00" in raw[:200]:
        text = raw.decode("utf-16-le", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return text.replace("﻿", "").replace("\x00", "")


def _run(args: list[str], timeout: float = 15) -> tuple[int, str, str]:
    """Run ``wsl.exe`` with `args`. Returns (returncode, stdout, stderr)."""
    env = dict(os.environ, WSL_UTF8="1")
    try:
        proc = subprocess.run(
            ["wsl.exe", *args],
            capture_output=True,
            timeout=timeout,
            shell=False,
            env=env,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        return -1, "", "wsl.exe not found. Is WSL installed?"
    except subprocess.TimeoutExpired:
        return -1, "", f"wsl.exe timed out after {timeout:.0f}s."
    except OSError as exc:
        return -1, "", str(exc)
    return proc.returncode, _decode(proc.stdout), _decode(proc.stderr)


def parse_list_verbose(text: str) -> list[DistroInfo]:
    """Parse ``wsl --list --verbose`` output."""
    distros: list[DistroInfo] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_default = line.startswith("*")
        parts = line.lstrip("*").split()
        if not parts or parts[0].upper() == "NAME":
            continue
        distros.append(
            DistroInfo(
                name=parts[0],
                state=parts[1] if len(parts) > 1 else "",
                version=parts[2] if len(parts) > 2 else "",
                is_default=is_default,
            )
        )
    return distros


def detect() -> WslStatus:
    """Return installed distros with their state and WSL version."""
    code, out, err = _run(["--list", "--verbose"], timeout=15)
    if code == -1:
        return WslStatus(wsl_available=False, error=err)
    status = WslStatus(wsl_available=True)
    if code != 0:
        status.error = (err or out).strip() or f"wsl --list failed (exit {code})."
        return status
    status.distros = parse_list_verbose(out)
    return status


def start_distro(distro: str) -> str:
    """Boot `distro` (systemd then starts enabled services such as ollama)."""
    if not is_valid_name(distro):
        return f"Invalid distro name: {distro!r}"
    code, out, err = _run(["-d", distro, "--exec", "/bin/true"], timeout=60)
    if code == 0:
        return f"{distro} started."
    return f"Failed to start {distro}: {(err or out).strip() or f'exit {code}'}"


def terminate_distro(distro: str) -> str:
    """Terminate only `distro` (never ``wsl --shutdown``)."""
    if not is_valid_name(distro):
        return f"Invalid distro name: {distro!r}"
    code, out, err = _run(["--terminate", distro], timeout=30)
    if code == 0:
        return f"{distro} terminated."
    return f"Failed to terminate {distro}: {(err or out).strip() or f'exit {code}'}"


def service_status(distro: str, service: str) -> str:
    """Return ``systemctl is-active`` output (e.g. 'active', 'inactive').

    Callers should only query a distro that is already running, because any
    ``wsl -d`` command boots a stopped distro.
    """
    if not (is_valid_name(distro) and is_valid_name(service)):
        return "invalid name"
    code, out, err = _run(["-d", distro, "--exec", "systemctl", "is-active", service], timeout=15)
    text = out.strip().splitlines()
    if text:
        return text[0].strip()
    return (err.strip() or f"unknown (exit {code})")


SUDO_HELP = (
    "Passwordless sudo is not authorized for systemctl, so the service cannot be "
    "controlled from this app. The app will not store a password or change sudo "
    "settings. Either run the command yourself in an Ubuntu terminal, add a "
    "NOPASSWD sudoers rule for 'systemctl start/stop ollama' yourself, or set "
    "\"service_control_as_root\": true in settings.json to use 'wsl -u root'."
)


def control_service(distro: str, service: str, action: str, as_root: bool = False) -> str:
    """Run ``systemctl start|stop|restart <service>`` inside `distro`."""
    if action not in ("start", "stop", "restart"):
        return f"Unsupported action: {action!r}"
    if not (is_valid_name(distro) and is_valid_name(service)):
        return "Invalid distro or service name."
    if as_root:
        args = ["-d", distro, "-u", "root", "--exec", "systemctl", action, service]
    else:
        args = ["-d", distro, "--exec", "sudo", "-n", "systemctl", action, service]
    code, out, err = _run(args, timeout=60)
    if code == 0:
        return f"Service '{service}' {action} succeeded."
    detail = (err or out).strip()
    if "password is required" in detail.lower() or "a terminal is required" in detail.lower():
        return SUDO_HELP
    return f"Service '{service}' {action} failed: {detail or f'exit {code}'}"
