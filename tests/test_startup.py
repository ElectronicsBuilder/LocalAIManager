"""Start with Windows: registry access is fully faked."""

import pytest

from local_ai_manager import startup
from local_ai_manager.config import Config


class FakeKey:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}
        self.opened = []

    def OpenKey(self, root, path, reserved, access):
        self.opened.append((root, path))
        return FakeKey(self.values)

    def CreateKeyEx(self, root, path, reserved, access):
        self.opened.append((root, path))
        return FakeKey(self.values)

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


@pytest.fixture
def reg(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(startup, "winreg", fake)
    return fake


def test_disabled_when_value_absent(reg):
    assert startup.is_enabled() is False


def test_enable_writes_hkcu_run_value(reg):
    cfg = Config()
    assert startup.enable(cfg) == "Start with Windows enabled."
    assert startup.is_enabled()
    assert set(reg.opened) == {("HKCU", startup.RUN_KEY_PATH)}
    assert reg.values["LocalAIManager"] == startup.launch_command()
    assert cfg.start_with_windows is True


def test_disable_removes_value(reg):
    cfg = Config()
    startup.enable(cfg)
    assert startup.disable(cfg) == "Start with Windows disabled."
    assert not startup.is_enabled()
    assert cfg.start_with_windows is False


def test_disable_when_already_absent_is_ok(reg):
    assert startup.disable(Config()) == "Start with Windows disabled."


def test_enable_failure_is_reported(reg, monkeypatch):
    def denied(*a):
        raise PermissionError("Access is denied")
    monkeypatch.setattr(reg, "SetValueEx", denied)
    cfg = Config()
    assert "Access is denied" in startup.enable(cfg)
    assert cfg.start_with_windows is False


def test_launch_command_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "LocalAIManager.exe"
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(startup.sys, "executable", str(exe))
    assert startup.launch_command() == f'"{exe.resolve()}"'


def test_launch_command_dev_points_to_run_py(monkeypatch):
    monkeypatch.delattr(startup.sys, "frozen", raising=False)
    cmd = startup.launch_command()
    assert cmd.endswith('run.py"')
    assert cmd.startswith('"')


def test_importing_does_not_touch_registry(reg):
    assert reg.opened == []
