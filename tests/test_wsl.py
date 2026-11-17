import subprocess
from types import SimpleNamespace

import pytest

from local_ai_manager import wsl

LIST_OUTPUT = (
    "  NAME            STATE           VERSION\n"
    "* Ubuntu-24.04    Running         2\n"
    "  docker-desktop  Stopped         2\n"
)


class FakeRun:
    """Records wsl.exe invocations and returns canned results."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.calls = []
        self.result = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return self.result


@pytest.fixture
def fake_run(monkeypatch):
    def make(**kw):
        fr = FakeRun(**kw)
        monkeypatch.setattr(wsl.subprocess, "run", fr)
        return fr
    return make


def test_decode_utf16_output():
    raw = LIST_OUTPUT.encode("utf-16-le")
    assert wsl._decode(raw) == LIST_OUTPUT


def test_decode_utf16_with_bom():
    raw = "﻿hello".encode("utf-16-le")
    assert wsl._decode(raw) == "hello"


def test_decode_utf8_output():
    assert wsl._decode(LIST_OUTPUT.encode("utf-8")) == LIST_OUTPUT


def test_parse_list_verbose():
    distros = wsl.parse_list_verbose(LIST_OUTPUT)
    assert [d.name for d in distros] == ["Ubuntu-24.04", "docker-desktop"]
    ubuntu = distros[0]
    assert ubuntu.is_default and ubuntu.running and ubuntu.version == "2"
    assert not distros[1].running and not distros[1].is_default


def test_detect_handles_utf16(fake_run):
    fr = fake_run(stdout=LIST_OUTPUT.encode("utf-16-le"))
    st = wsl.detect()
    assert st.wsl_available
    assert st.find("ubuntu-24.04").running
    cmd, kwargs = fr.calls[0]
    assert cmd == ["wsl.exe", "--list", "--verbose"]
    assert kwargs["shell"] is False
    assert kwargs["env"]["WSL_UTF8"] == "1"
    assert "timeout" in kwargs


def test_detect_wsl_missing(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(wsl.subprocess, "run", missing)
    st = wsl.detect()
    assert not st.wsl_available
    assert "not found" in st.error


def test_detect_timeout(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("wsl.exe", 15)
    monkeypatch.setattr(wsl.subprocess, "run", slow)
    assert "timed out" in wsl.detect().error


@pytest.mark.parametrize("name", ["Ubuntu-24.04", "ollama", "docker-desktop", "a_b.c"])
def test_valid_names(name):
    assert wsl.is_valid_name(name)


@pytest.mark.parametrize("name", ["", "-d", "a b", "x;rm -rf /", "$(id)", "a/b", "x" * 80])
def test_invalid_names(name):
    assert not wsl.is_valid_name(name)


def test_invalid_names_never_reach_subprocess(fake_run):
    fr = fake_run()
    assert "Invalid" in wsl.start_distro("bad name")
    assert "Invalid" in wsl.terminate_distro("x;y")
    assert wsl.service_status("Ubuntu-24.04", "$(id)") == "invalid name"
    assert "Invalid" in wsl.control_service("Ubuntu-24.04", "a b", "stop")
    assert "Unsupported" in wsl.control_service("Ubuntu-24.04", "ollama", "disable")
    assert fr.calls == []


def test_service_status_uses_exec_without_shell(fake_run):
    fr = fake_run(stdout=b"active\n")
    assert wsl.service_status("Ubuntu-24.04", "ollama") == "active"
    assert fr.calls[0][0] == ["wsl.exe", "-d", "Ubuntu-24.04", "--exec",
                              "systemctl", "is-active", "ollama"]


def test_service_status_inactive(fake_run):
    fake_run(returncode=3, stdout=b"inactive\n")
    assert wsl.service_status("Ubuntu-24.04", "ollama") == "inactive"


def test_control_service_uses_sudo_noninteractive(fake_run):
    fr = fake_run()
    msg = wsl.control_service("Ubuntu-24.04", "ollama", "start")
    assert "succeeded" in msg
    assert fr.calls[0][0] == ["wsl.exe", "-d", "Ubuntu-24.04", "--exec",
                              "sudo", "-n", "systemctl", "start", "ollama"]


def test_control_service_fails_safely_without_sudo(fake_run):
    fake_run(returncode=1, stderr=b"sudo: a password is required\n")
    msg = wsl.control_service("Ubuntu-24.04", "ollama", "stop")
    assert msg == wsl.SUDO_HELP
    assert "will not store a password" in msg


def test_control_service_as_root_opt_in(fake_run):
    fr = fake_run()
    wsl.control_service("Ubuntu-24.04", "ollama", "stop", as_root=True)
    assert fr.calls[0][0] == ["wsl.exe", "-d", "Ubuntu-24.04", "-u", "root", "--exec",
                              "systemctl", "stop", "ollama"]


def test_terminate_targets_only_the_distro(fake_run):
    fr = fake_run()
    assert "terminated" in wsl.terminate_distro("Ubuntu-24.04")
    assert fr.calls[0][0] == ["wsl.exe", "--terminate", "Ubuntu-24.04"]
    assert "--shutdown" not in fr.calls[0][0]


def test_start_distro_failure_message(fake_run):
    fake_run(returncode=1, stderr="There is no distribution".encode("utf-16-le"))
    assert wsl.start_distro("Nope").startswith("Failed to start Nope: There is no distribution")
