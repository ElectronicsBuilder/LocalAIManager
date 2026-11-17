import pytest

from local_ai_manager import ollama
from local_ai_manager.ollama import Model

BASE = "http://127.0.0.1:11434"


class FakeApi:
    """Stands in for ollama._http_json; routes by path."""

    def __init__(self):
        self.calls = []
        self.routes = {}

    def __call__(self, url, method="GET", payload=None, timeout=15):
        path = url.removeprefix(BASE)
        self.calls.append((method, path, payload))
        handler = self.routes.get(path, (0, {"error": "Connection failed"}))
        return handler(payload) if callable(handler) else handler


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(ollama, "_http_json", fake)
    return fake


@pytest.mark.parametrize("size,text", [
    (0, "0 B"), (999, "999 B"), (512 * 1024, "512.0 KB"),
    (10 * 1024**2, "10.0 MB"), (2 * 1024**3, "2.0 GB"),
])
def test_size_human(size, text):
    assert Model(name="x", size=size).size_human == text


def test_get_version(api):
    api.routes["/api/version"] = (200, {"version": "0.40.16"})
    assert ollama.get_version(BASE) == "0.40.16"
    assert ollama.is_running(BASE)


def test_unreachable(api):
    assert ollama.get_version(BASE) is None
    assert ollama.get_models(BASE) == []
    assert ollama.get_running(BASE) is None


def test_get_models_parses_and_sorts(api):
    api.routes["/api/tags"] = (200, {"models": [
        {"name": "qwen3.8:27b", "size": 17741872154},
        {"name": "gpt-oss:20b", "size": 13793441566},
        {"bogus": True},
    ]})
    names = [m.name for m in ollama.get_models(BASE)]
    assert names == ["gpt-oss:20b", "qwen3.8:27b"]


def test_get_running_parses_ps(api):
    api.routes["/api/ps"] = (200, {"models": [{
        "name": "qwen3.8:27b", "size": 17445871942, "size_vram": 17445871942,
        "expires_at": "2026-11-17T01:11:40.076855067-06:00"}]})
    [m] = ollama.get_running(BASE)
    assert m.name == "qwen3.8:27b" and m.size_vram == 17445871942


def test_get_running_empty(api):
    api.routes["/api/ps"] = (200, {"models": []})
    assert ollama.get_running(BASE) == []


def test_load_sends_keep_alive_minutes(api):
    api.routes["/api/generate"] = (200, {"done": True})
    ollama.load_model("gpt-oss:20b", 30, BASE)
    method, path, payload = api.calls[0]
    assert (method, path) == ("POST", "/api/generate")
    assert payload == {"model": "gpt-oss:20b", "keep_alive": "30m", "stream": False}
    assert "prompt" not in payload


def test_load_failure_raises(api):
    api.routes["/api/generate"] = (404, {"error": "model 'x' not found"})
    with pytest.raises(ollama.OllamaError, match="not found"):
        ollama.load_model("x", 30, BASE)


def test_unload_sends_keep_alive_zero(api):
    api.routes["/api/generate"] = (200, {"done": True})
    ollama.unload_model("qwen3.8:27b", BASE)
    assert api.calls[0][2] == {"model": "qwen3.8:27b", "keep_alive": 0, "stream": False}


def test_unload_failure_raises(api):
    with pytest.raises(ollama.OllamaError):
        ollama.unload_model("qwen3.8:27b", BASE)


def _ps_sequence(api, *states):
    seq = iter(states)
    last = {"v": states[-1]}

    def handler(_payload):
        try:
            last["v"] = next(seq)
        except StopIteration:
            pass
        return 200, {"models": [{"name": n} for n in last["v"]]}
    api.routes["/api/ps"] = handler


def test_wait_until_unloaded_success(api):
    _ps_sequence(api, ["a"], ["a"], [])
    sleeps = []
    assert ollama.wait_until_unloaded(["a"], BASE, sleep=sleeps.append) == []
    assert len(sleeps) == 2


def test_wait_until_unloaded_timeout(api):
    _ps_sequence(api, ["a", "b"])
    t = {"now": 0.0}

    def sleep(s):
        t["now"] += s
    remaining = ollama.wait_until_unloaded(["a"], BASE, timeout=2, interval=0.5,
                                           sleep=sleep, clock=lambda: t["now"])
    assert remaining == ["a"]


def test_wait_until_unloaded_ignores_other_models(api):
    _ps_sequence(api, ["other"])
    assert ollama.wait_until_unloaded(["a"], BASE, sleep=lambda s: None) == []


def test_wait_until_unloaded_unreachable(api):
    with pytest.raises(ollama.OllamaError):
        ollama.wait_until_unloaded(None, BASE, sleep=lambda s: None)


def test_http_json_connection_refused_is_handled(monkeypatch):
    import urllib.error

    def refused(*a, **k):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(ollama.urllib.request, "urlopen", refused)
    code, body = ollama._http_json(f"{BASE}/api/version")
    assert code == 0 and "refused" in body["error"]
