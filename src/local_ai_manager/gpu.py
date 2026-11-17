"""GPU usage / memory / temperature monitoring.

Primarily uses `nvidia-smi` (NVIDIA GPUs). If it is unavailable, the module
reports that no GPU telemetry source was found rather than failing hard, so
the UI can display a graceful "not available" state.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class GpuSample:
    """A single point-in-time GPU reading."""

    available: bool = False
    name: str = ""
    util_percent: float = 0.0        # GPU compute utilisation
    mem_used_mb: float = 0.0
    mem_total_mb: float = 0.0
    mem_percent: float = 0.0
    temp_c: float = 0.0
    power_w: float = 0.0
    source: str = ""

    @property
    def mem_percent_text(self) -> str:
        if self.mem_total_mb <= 0:
            return "n/a"
        return f"{self.mem_used_mb / self.mem_total_mb * 100:.0f}%"


def nvidia_smi_present() -> bool:
    """Return True if `nvidia-smi` is on PATH."""
    return shutil.which("nvidia-smi") is not None


def _run_nvidia_smi() -> tuple[int, str]:
    """Run nvidia-smi querying a specific field set. Returns (rc, stdout)."""
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode, proc.stdout or ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return -1, str(exc)


def sample() -> GpuSample:
    """Return the latest GPU sample. `available` is False if no source found."""
    if not nvidia_smi_present():
        return GpuSample(available=False, source="none")

    rc, out = _run_nvidia_smi()
    if rc != 0 or not out.strip():
        return GpuSample(available=False, source="nvidia-smi (error)")

    # First data line: name, util, mem_used, mem_total, temp, power
    line = out.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 6:
        return GpuSample(available=False, source="nvidia-smi (bad format)")

    def _f(idx: int) -> float:
        try:
            return float(parts[idx].replace(" [Not Supported]", ""))
        except (ValueError, IndexError):
            return 0.0

    mem_used = _f(2)
    mem_total = _f(3)
    return GpuSample(
        available=True,
        name=parts[0],
        util_percent=_f(1),
        mem_used_mb=mem_used,
        mem_total_mb=mem_total,
        mem_percent=(mem_used / mem_total * 100.0) if mem_total > 0 else 0.0,
        temp_c=_f(4),
        power_w=_f(5),
        source="nvidia-smi",
    )
