"""GUI logic tests with a real (hidden) Tk root and all backends faked."""

import threading
import time
import tkinter as tk

import pytest

from local_ai_manager import ui, ollama, wsl, gpu
from local_ai_manager.config import Config


@pytest.fixture(scope="session")
def tk_session():
    # One Tcl interpreter per test session: creating many Tk() roots in one
    # process intermittently failed to source tk.tcl under pytest.
    try:
        r = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk not available: {exc}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def root(tk_session):
    top = tk.Toplevel(tk_session)
    top.withdraw()
    yield top
    for h in list(ui.logging.getLogger().handlers):
        if isinstance(h, ui._QueueLogHandler):
            ui.logging.getLogger().removeHandler(h)
    try:
        top.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def no_registry(monkeypatch):
    monkeypatch.setattr(ui.startup, "is_enabled", lambda: False)


def pump(app, root, until, timeout=3.0):
    """Process the UI queue until `until()` is true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def make_snapshot(running=("qwen3.8:27b",)):
    st = wsl.WslStatus(wsl_available=True, distros=[
        wsl.DistroInfo("Ubuntu-24.04", "Running", "2", True)])
    return ui.Snapshot(
        wsl=st, service_state="active", ollama_version="0.40.16",
        models=[ollama.Model("gpt-oss:20b", 13793441566), ollama.Model("qwen3.8:27b", 17741872154)],
        running=[ollama.RunningModel(n, size_vram=17445871942,
                                     expires_at="2026-11-17T01:11:40.076855067-06:00")
                 for n in running],
        gpu=gpu.GpuSample(available=True, name="NVIDIA GeForce RTX 3090 Ti", util_percent=12,
                          mem_used_mb=22172, mem_total_mb=24564, mem_percent=90.3,
                          temp_c=39, power_w=103.85),
    )


def test_format_expiry_handles_nanoseconds():
    assert ui.format_expiry("2026-11-17T01:11:40.076855067-06:00").startswith("until ")
    assert ui.format_expiry("2318-01-01T00:00:00Z") == "kept loaded indefinitely"
    assert ui.format_expiry("garbage") == ""
    assert ui.format_expiry("") == ""


def test_collect_snapshot_does_not_boot_stopped_distro(monkeypatch):
    monkeypatch.setattr(ui.wsl, "detect", lambda: wsl.WslStatus(
        wsl_available=True, distros=[wsl.DistroInfo("Ubuntu-24.04", "Stopped", "2")]))
    monkeypatch.setattr(ui.wsl, "service_status",
                        lambda *a: pytest.fail("must not query a stopped distro"))
    monkeypatch.setattr(ui.ollama, "get_version", lambda base: None)
    monkeypatch.setattr(ui.gpu, "sample", lambda: gpu.GpuSample())
    snap = ui.collect_snapshot(Config(), include_wsl=True)
    assert snap.service_state == "distro stopped"
    assert snap.running is None


def test_apply_snapshot_renders_status(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    app._apply_snapshot(make_snapshot())
    assert app.distro_var.get() == "Running (WSL 2)"
    assert app.service_var.get() == "active"
    assert "v0.40.16" in app.api_var.get()
    assert set(app.model_tree.get_children()) == {"gpt-oss:20b", "qwen3.8:27b"}
    assert app.model_tree.item("qwen3.8:27b", "values")[1].startswith("Loaded")
    assert "qwen3.8:27b" in app.loaded_var.get()
    assert app.gpu_vars["power"].get() == "104 W"
    assert app.gaming_warn_var.get() == ""


def test_selection_survives_refresh(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    app._apply_snapshot(make_snapshot())
    app.model_tree.selection_set("gpt-oss:20b")
    app._apply_snapshot(make_snapshot(running=()))
    assert app._selected_model() == "gpt-oss:20b"
    assert app.loaded_var.get() == "Loaded: none"


def test_gaming_mode_warns_about_external_loads_and_blocks_load(root, no_registry, monkeypatch):
    app = ui.App(root, Config(gaming_mode_enabled=True), start_background=False)
    app._update_buttons()
    app._apply_snapshot(make_snapshot())
    assert "another client loaded" in app.gaming_warn_var.get()
    assert all(b.cget("state") == "disabled" for b in app._load_buttons)
    shown = []
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(ui.ollama, "load_model", lambda *a: pytest.fail("must not load"))
    app.model_tree.selection_set("gpt-oss:20b")
    app._load_selected()
    assert shown and "Gaming Mode" in shown[0][1]


def test_load_action_runs_off_thread_and_remembers_model(root, no_registry, monkeypatch):
    cfg = Config()
    app = ui.App(root, cfg, start_background=False)
    app._apply_snapshot(make_snapshot(running=()))
    app.model_tree.selection_set("gpt-oss:20b")
    threads = []

    def load(name, ka, base):
        threads.append(threading.current_thread())
        assert ka == 30
    monkeypatch.setattr(ui.ollama, "load_model", load)
    monkeypatch.setattr(ui.ollama, "get_running",
                        lambda base: [ollama.RunningModel("gpt-oss:20b")])
    app._load_selected()
    assert app._busy
    pump(app, root, lambda: not app._busy)
    assert threads and threads[0] is not threading.main_thread()
    assert cfg.last_model == "gpt-oss:20b"
    assert Config.load().last_model == "gpt-oss:20b"
    assert "Loaded gpt-oss:20b" in app.status_var.get()


def test_only_one_action_at_a_time(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    gate = threading.Event()
    assert app._run_action("first", lambda: (gate.wait(2), (True, "ok"))[1])
    assert not app._run_action("second", lambda: (True, "ok"))
    assert "still running" in app.status_var.get()
    gate.set()
    pump(app, root, lambda: not app._busy)


def test_action_exception_is_reported(root, no_registry):
    app = ui.App(root, Config(), start_background=False)

    def boom():
        raise ollama.OllamaError("Load of 'x' failed: HTTP 500")
    app._run_action("Loading x", boom)
    pump(app, root, lambda: not app._busy)
    assert "HTTP 500" in app.status_var.get()


def test_gaming_toggle_unloads_via_worker(root, no_registry, monkeypatch):
    cfg = Config()
    app = ui.App(root, cfg, start_background=False)
    calls = []

    class FakeGM:
        def __init__(self, c):
            pass

        def enable(self):
            calls.append(threading.current_thread())
            cfg.gaming_mode_enabled = True
            return ui.gaming.GamingResult(True, "Gaming Mode ON. Unloaded: qwen3.8:27b.")
    monkeypatch.setattr(ui.gaming, "GamingMode", FakeGM)
    app.gaming_var.set(True)
    app._on_gaming_toggled()
    pump(app, root, lambda: not app._busy)
    assert calls[0] is not threading.main_thread()
    assert app.gaming_var.get() is True
    assert all(b.cget("state") == "disabled" for b in app._load_buttons)


def test_stop_service_requires_confirmation(root, no_registry, monkeypatch):
    app = ui.App(root, Config(), start_background=False)
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(ui.wsl, "control_service", lambda *a: pytest.fail("must not run"))
    monkeypatch.setattr(ui.wsl, "terminate_distro", lambda *a: pytest.fail("must not run"))
    app._stop_service()
    app._stop_distro()
    assert not app._busy


def test_autoload_skipped_in_gaming_mode(root, no_registry, monkeypatch):
    app = ui.App(root, Config(gaming_mode_enabled=True, last_model="x",
                              auto_start_last_model=True), start_background=False)
    monkeypatch.setattr(ui.wsl, "detect", lambda: pytest.fail("must not run"))
    app._auto_load_last_model()
    assert not app._busy


def test_log_messages_reach_panel_from_worker_threads(root, no_registry, caplog):
    caplog.set_level("INFO")  # main.setup_logging() does this in the real app
    app = ui.App(root, Config(), start_background=False)
    t = threading.Thread(target=lambda: ui.log.info("hello from worker"))
    t.start()
    t.join()
    pump(app, root, lambda: "hello from worker" in app.log_text.get("1.0", "end"))
    app.on_close()


def test_monitor_thread_posts_snapshots_and_stops_on_close(root, no_registry, monkeypatch):
    seen_threads = []

    def collect(cfg, include_wsl):
        seen_threads.append(threading.current_thread())
        return make_snapshot()
    monkeypatch.setattr(ui, "collect_snapshot", collect)
    cfg = Config(gpu_poll_interval_ms=500)
    app = ui.App(root, cfg, start_background=True)
    pump(app, root, lambda: app.service_var.get() == "active")
    assert seen_threads[0] is not threading.main_thread()
    monitor = app._monitor
    app.on_close()
    assert not monitor.is_alive()
    assert Config.load().window_width >= 640  # settings saved on close


def test_close_keeps_external_settings_edits(root, no_registry):
    cfg = Config()
    cfg.save()
    app = ui.App(root, cfg, start_background=False)
    external = Config.load()                    # user edits settings.json meanwhile
    external.service_control_as_root = True
    external.save()
    app.on_close()
    after = Config.load()
    assert after.service_control_as_root is True
    assert after.window_width >= 640


def test_in_app_changes_are_saved_immediately(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    app.autoload_var.set(True)
    app._on_autoload_toggled()
    app.keepalive_var.set("45")
    app._on_keepalive_changed()
    on_disk = Config.load()
    assert on_disk.auto_start_last_model is True and on_disk.keep_alive_minutes == 45


# ---------------------------------------------------------------- VS Code layout

def test_app_icon_asset_exists_and_is_multi_size():
    from local_ai_manager import theme
    data = theme.APP_ICON.read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00"            # ICO header
    assert int.from_bytes(data[4:6], "little") >= 5   # several sizes


def test_views_switch_with_tabs_and_activity_bar(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    root.update_idletasks()
    for key, _title in ui.VIEWS:
        app.show_view(key)
        assert app._current_view == key
        assert app.activity._active == key


def test_clicking_active_activity_icon_toggles_sidebar(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    root.deiconify()
    root.update()
    try:
        assert app.sidebar.winfo_ismapped()
        app._on_activity("dashboard")          # already active -> hide
        root.update()
        assert not app.sidebar.winfo_ismapped()
        app._on_activity("models")             # another view -> show again
        root.update()
        assert app.sidebar.winfo_ismapped() and app._current_view == "models"
    finally:
        root.withdraw()


def test_output_panel_toggles(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    assert app._panel_visible
    app.toggle_panel()
    assert not app._panel_visible and str(app.panel) not in app.editor_col.panes()
    app.toggle_panel()
    assert app._panel_visible


def test_sidebar_lists_models_and_reveals_them(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    app._apply_snapshot(make_snapshot())
    assert list(app._sb_model_rows) == ["gpt-oss:20b", "qwen3.8:27b"]
    assert app._sb_model_rows["qwen3.8:27b"].right.cget("text") == "loaded"
    assert app._sb_model_rows["gpt-oss:20b"].right.cget("text") == ""
    app._reveal_model("gpt-oss:20b")
    assert app._current_view == "models"
    assert app._selected_model() == "gpt-oss:20b"
    assert app._sb_model_rows["gpt-oss:20b"]._selected


def test_status_bar_reflects_state_and_gaming_color(root, no_registry):
    from local_ai_manager import theme
    cfg = Config()
    app = ui.App(root, cfg, start_background=False)
    app._apply_snapshot(make_snapshot())
    assert "qwen3.8:27b" in app.st_model.cget("text")
    assert app.st_vram.cget("text") == "VRAM 21.7/24.0 GB"
    assert app.st_service.cget("text") == "ollama: active"
    assert app.status_bar.cget("bg") == theme.STATUS_BG
    cfg.gaming_mode_enabled = True
    app._update_buttons()
    assert app.status_bar.cget("bg") == theme.STATUS_GAMING
    assert app.st_gaming.cget("text") == "Gaming Mode: ON"


def test_gpu_charts_record_history(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    for _ in range(3):
        app._apply_snapshot(make_snapshot())
    assert list(app.util_chart.values) == [12, 12, 12]
    assert round(app.vram_chart.values[-1]) == 90


def test_offline_api_shows_in_sidebar(root, no_registry):
    app = ui.App(root, Config(), start_background=False)
    app._apply_snapshot(ui.Snapshot())
    assert app.sb_models_empty.cget("text") == "Ollama API not reachable"
    assert app.st_model.cget("text") == "Ollama offline"
    assert app.gpu_vars["name"].get().startswith("No telemetry")
