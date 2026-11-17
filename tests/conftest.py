"""Test isolation: no real subprocesses, HTTP calls, or user settings.

Every test gets a private settings directory, and any unmocked attempt to run
a process or open a URL fails loudly instead of touching WSL/Ollama/GPU.
"""

import subprocess
import urllib.request

import pytest

from local_ai_manager import config


class UnmockedSideEffect(AssertionError):
    pass


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_MANAGER_CONFIG_DIR", str(tmp_path / "cfg"))
    config.reset_config_cache()
    yield tmp_path / "cfg"
    config.reset_config_cache()


@pytest.fixture(autouse=True)
def block_side_effects(monkeypatch):
    def refuse(*args, **kwargs):
        raise UnmockedSideEffect(f"Unmocked external call: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "call", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
