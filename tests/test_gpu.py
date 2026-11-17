from types import SimpleNamespace

from local_ai_manager import gpu
from local_ai_manager.gpu import GpuSample


def _fake_smi(monkeypatch, stdout, returncode=0, present=True):
    calls = []
    monkeypatch.setattr(gpu.shutil, "which", lambda name: "nvidia-smi.exe" if present else None)

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=returncode, stdout=stdout)
    monkeypatch.setattr(gpu.subprocess, "run", run)
    return calls


def test_default_sample_is_unavailable():
    s = GpuSample()
    assert s.available is False
    assert s.mem_percent_text == "n/a"


def test_mem_percent_text():
    assert GpuSample(mem_used_mb=500.0, mem_total_mb=1000.0).mem_percent_text == "50%"


def test_sample_parses_real_rtx_3090_ti_output(monkeypatch):
    calls = _fake_smi(monkeypatch, "NVIDIA GeForce RTX 3090 Ti, 12, 22172, 24564, 39, 103.85\n")
    s = gpu.sample()
    assert s.available and s.name == "NVIDIA GeForce RTX 3090 Ti"
    assert s.util_percent == 12 and s.mem_used_mb == 22172 and s.mem_total_mb == 24564
    assert s.temp_c == 39 and s.power_w == 103.85
    assert round(s.mem_percent) == 90
    assert calls[0][0][0] == "nvidia-smi"
    assert "timeout" in calls[0][1]


def test_sample_handles_unsupported_fields(monkeypatch):
    _fake_smi(monkeypatch, "Some GPU, 5, 100, 1000, 40, [N/A]\n")
    s = gpu.sample()
    assert s.available and s.power_w == 0.0


def test_sample_without_nvidia_smi(monkeypatch):
    _fake_smi(monkeypatch, "", present=False)
    assert gpu.sample().available is False


def test_sample_with_error_exit(monkeypatch):
    _fake_smi(monkeypatch, "NVIDIA-SMI has failed", returncode=9)
    assert gpu.sample().available is False


def test_sample_bad_format(monkeypatch):
    _fake_smi(monkeypatch, "only, three, fields\n")
    assert gpu.sample().source == "nvidia-smi (bad format)"
