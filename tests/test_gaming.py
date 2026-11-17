import pytest

from local_ai_manager import gaming, ollama
from local_ai_manager.config import Config


class FakeOllama:
    def __init__(self, loaded, stuck=(), reachable=True):
        self.loaded = list(loaded)
        self.stuck = set(stuck)
        self.reachable = reachable
        self.unload_calls = []
        self.load_calls = []

    def get_running(self, base):
        if not self.reachable:
            return None
        return [ollama.RunningModel(name=n) for n in self.loaded]

    def unload_model(self, name, base):
        self.unload_calls.append(name)
        if name not in self.stuck:
            self.loaded.remove(name)

    def load_model(self, *a, **k):
        self.load_calls.append(a)

    def wait_until_unloaded(self, names, base, timeout=30):
        return [n for n in self.loaded if n in names]


@pytest.fixture
def fake(monkeypatch):
    def install(*args, **kwargs):
        f = FakeOllama(*args, **kwargs)
        for attr in ("get_running", "unload_model", "load_model", "wait_until_unloaded"):
            monkeypatch.setattr(gaming.ollama, attr, getattr(f, attr))
        return f
    return install


def test_disabled_by_default():
    assert gaming.GamingMode(Config()).is_enabled() is False


def test_enable_unloads_all_and_verifies(fake, isolated_settings):
    f = fake(["qwen3.8:27b", "gpt-oss:20b"])
    cfg = Config()
    r = gaming.GamingMode(cfg).enable()
    assert r.ok
    assert f.unload_calls == ["qwen3.8:27b", "gpt-oss:20b"]
    assert f.loaded == []
    assert r.unloaded == ["qwen3.8:27b", "gpt-oss:20b"]
    assert cfg.gaming_mode_enabled is True
    assert Config.load().gaming_mode_enabled is True  # persisted


def test_enable_reports_models_that_stay_loaded(fake):
    fake(["a", "b"], stuck={"b"})
    r = gaming.GamingMode(Config()).enable()
    assert not r.ok
    assert r.still_loaded == ["b"] and r.unloaded == ["a"]
    assert "still loaded" in r.message


def test_enable_with_nothing_loaded(fake):
    f = fake([])
    r = gaming.GamingMode(Config()).enable()
    assert r.ok and f.unload_calls == []


def test_enable_when_ollama_unreachable(fake):
    fake([], reachable=False)
    cfg = Config()
    r = gaming.GamingMode(cfg).enable()
    assert r.ok and cfg.gaming_mode_enabled


def test_unload_error_is_reported(fake, monkeypatch):
    fake(["a"])

    def boom(name, base):
        raise ollama.OllamaError("Unload of 'a' failed: HTTP 500")
    monkeypatch.setattr(gaming.ollama, "unload_model", boom)
    r = gaming.GamingMode(Config()).enable()
    assert not r.ok and "HTTP 500" in r.message


def test_disable_does_not_reload_or_touch_service(fake):
    f = fake([])
    cfg = Config(gaming_mode_enabled=True, last_model="qwen3.8:27b")
    r = gaming.GamingMode(cfg).disable()
    assert r.ok and cfg.gaming_mode_enabled is False
    assert f.load_calls == [] and f.unload_calls == []
