# Project Handoff — Local AI Manager

_Last updated: 2026-11-17 by Claude Code (VS Code-style CustomTkinter UI + icon)._
Read `AGENTS.md` first. Treat the source code as authoritative; this file is a
map.

## 1. Status at a glance

| Item | State | How verified |
|---|---|---|
| Unit tests | **103 passed**, 0 failed, 0 skipped | `uv run pytest -q` |
| Live load/unload + Gaming Mode | **Verified** on real Ollama/GPU | See CHANGELOG 0.2.1 |
| Service control | `wsl -u root` (user-approved) | Stop + start verified live |
| Version control | Git repo on `main` | `git status` |
| GUI | CustomTkinter 6.0.0, VS Code layout (D-009) | All 4 views captured and reviewed |
| App icon | Title bar, taskbar, exe file icon (D-010) | ExtractAssociatedIcon + taskbar capture |
| Dev GUI (`uv run python run.py`) | Launches, shows live data, closes cleanly | Screenshot + WM_CLOSE |
| Packaged exe | Builds (30.4 MB); launches with no Python on PATH; closes cleanly | `pyinstaller` + screenshot |
| Status monitoring (WSL/service/API/models/GPU) | Correct against the live system | Read-only probes |
| Start with Windows | Implemented (HKCU Run), unit-tested | Not enabled live (the user toggles it) |

**Verified executable:** `<project root>\dist\LocalAIManager\LocalAIManager.exe`
(onedir build, ~30 MB folder).

Stale artifacts from the Qwen build (old onefile exe, stray `config.json`
files) were deleted on 2026-11-17.

## 2. Environment (verified 2026-11-17)

- Windows 11, RTX 3090 Ti 24 GB (driver reports via `nvidia-smi`).
- Python 3.13.18 via uv (`.venv`), CustomTkinter 6.0.0, pytest 9.2,
  PyInstaller 6.22.3, Pillow 13.0 (dev only).
- HTTPS is intercepted on this machine: uv needs `--system-certs` for any
  network operation (`uv add`, `uv lock`).
- WSL2 distro `Ubuntu-24.04` (default, WSL 2), systemd enabled.
- `ollama` systemd service `active`, API v0.40.16 at `http://127.0.0.1:11434`,
  bound to loopback (no `OLLAMA_HOST` in the unit environment).
- Models: `qwen3.8:27b` (16.5 GB), `gpt-oss:20b` (12.8 GB).
- **No Windows-side `ollama.exe`.** All control goes through WSL + HTTP.
- `sudo -n true` in Ubuntu → "a password is required" (no NOPASSWD rule).
  The user chose `service_control_as_root: true` (in their settings.json), so
  the app controls the service with `wsl -u root`; sudoers is untouched.
- Git 2.56 at `C:\Program Files\Git\cmd\git.exe` (installed 2026-11-17;
  shells opened before the install need a restart to see it on PATH).

## 3. Project structure

```
AGENTS.md / CLAUDE.md        agent instructions (shared / Claude pointer)
docs/                        PROJECT_HANDOFF, DECISIONS, CHANGELOG
pyproject.toml, uv.lock      uv project; runtime dep = customtkinter 6.x
run.py                       launcher (dev + PyInstaller entry)
local_ai_manager.spec        PyInstaller onedir spec (bundles CTk data + assets, exe icon)
tools/make_icon.py           regenerates assets/app.ico + app.png (Pillow, dev only)
src/local_ai_manager/
  theme.py     Dark Modern palette, fonts, MDL2 glyphs, ttk styles
  widgets.py   ActivityBar, SidebarSection/Row, TabStrip, StatusItem, Card, LineChart
  assets/      app.ico, app.png
  config.py    Config dataclass, validation, atomic save, %APPDATA% path
  wsl.py       wsl.exe runner (UTF-16 decode), distro parse, service control
  ollama.py    HTTP client: version/tags/ps, load/unload, wait_until_unloaded
  gpu.py       nvidia-smi sampling (unchanged from Qwen; verified correct)
  gaming.py    Gaming Mode controller (unload + verify)
  startup.py   HKCU Run value
  ui.py        VS Code-style GUI (views, side bar, status bar), monitor thread,
               action worker, Output panel
  main.py      logging (stderr if present + rotating file), main()
tests/         conftest (isolation) + one test module per source module
```

## 4. Runtime architecture

- **Tk thread:** owns all widgets. Drains `App._ui_queue` every 100 ms.
- **Monitor thread:** every `gpu_poll_interval_ms` (2 s) collects Ollama
  version/tags/ps and GPU; every 5th tick (or on Refresh / after any action)
  also `wsl --list --verbose` and `systemctl is-active` (the latter only if the
  distro is already running, because any `wsl -d` call boots a stopped distro).
  A full tick takes ~0.5 s, a light tick ~0.1 s (measured).
- **Action worker:** one user action at a time; buttons disabled meanwhile.
  Destructive actions (stop service, terminate distro) need confirmation.
- **Shutdown:** `on_close` → asks if an action is running → stop event →
  join monitor (≤3 s) → save window size → destroy. Measured exit: 109–182 ms.
- **Settings:** `%APPDATA%\LocalAIManager\settings.json`
  (`LOCAL_AI_MANAGER_CONFIG_DIR` overrides). Logs: `…\logs\app.log`.

Settings keys (defaults): `ollama_base_url` (`http://127.0.0.1:11434`),
`keep_alive_minutes` (30), `last_model` (""), `auto_start_last_model` (false),
`wsl_distro` (`Ubuntu-24.04`), `ollama_service` (`ollama`),
`service_control_as_root` (false), `gpu_poll_interval_ms` (2000),
`gaming_mode_enabled` (false), `start_with_windows` (false), window size.

## 5. Gaming Mode behavior

Enable: set flag → `/api/ps` → `keep_alive: 0` for each model → poll `/api/ps`
up to 30 s → report unloaded / still loaded. WSL and Ollama keep running.
While ON: Load buttons disabled; auto-load skipped; a warning shows if another
client (e.g. Continue) loads a model. The app does **not** force-unload in the
background. Disable: clear the flag only; no reload.

## 6. Known issues and limitations

1. (Resolved) Service stop/start verified live via `wsl -u root`.
2. (Resolved) The exe was rebuilt with the 0.2.1 on-close fix. Verified:
   `service_control_as_root: true` survives launching and closing the
   packaged app.
3. **Gaming Mode cannot stop other clients** from loading models (by design,
   D-004).
4. **Start Distro:** `wsl --exec /bin/true` boots the distro; whether it stays
   up depends on WSL's idle timeout and systemd services (Ollama keeps it up on
   this machine).
5. No single-instance guard: two app windows can run at once.
6. Portability to other PCs is **not validated**. It needs Windows 10/11, WSL2
   with a distro named per settings, systemd + Ollama in that distro, and an
   NVIDIA driver for telemetry (degrades gracefully without one). The UI uses
   the Segoe UI / Segoe MDL2 Assets / Cascadia Mono fonts. Tk falls back if
   Cascadia Mono is missing; MDL2 ships with Windows 10/11.
7. The UI was reviewed at 100% display scaling only. Pixel sizes are
   DPI-scaled in code, but 125%/150% have not been visually checked.
8. Native message boxes (confirmations) use the light Windows style, not the
   dark theme.
9. (Resolved) Git repository initialised with `.gitignore`.

## 7. Next steps (priority order)

1. Commit work in small, described commits (AGENTS.md §1).
2. Optional: add `.gitattributes` to pin line endings.
3. Single-instance guard (named mutex via `ctypes`) so a Start-with-Windows
   launch plus a manual launch don't double up.
4. System tray / minimize-to-tray (would need a dependency such as `pystray`;
   record a decision first).
5. Version info resource in the exe (icon is done).
6. Dark CTk confirmation dialogs to replace the native message boxes.
7. Check the layout at 125% / 150% display scaling.
8. Optional: let the user pick the distro from the detected list in the UI
   rather than editing `settings.json`.
