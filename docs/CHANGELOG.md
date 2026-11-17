# Changelog

All notable changes. Newest first. Record what changed, why, and how it was
verified.

## [0.2.2] — 2026-11-17 — Continuous integration (Claude Code)

### Added
- GitHub Actions CI (`.github/workflows/ci.yml`, D-011): Windows runner,
  locked uv sync, pytest, PyInstaller build, smoke test, and the build
  uploaded as an artifact.
- `tools/smoke_test.ps1`: launches the packaged exe with throw-away settings,
  waits for the UI-ready log line, closes it via WM_CLOSE, and fails on early
  exit, timeout, unclean shutdown or errors in the log.

### Changed
- Docs: replaced the machine name and user path with generic wording before
  publishing.

### Verified (locally, before push)
- `uv sync --locked` OK, 103 tests passed, build OK, smoke test passed
  (clean WM_CLOSE).
- Negative check: with CustomTkinter's themes removed from the build, the
  smoke test failed as intended.

## [0.2.1] — 2026-11-17 — Live verification, service control, cleanup (Claude Code)

### Fixed
- **Settings edited while the app runs were reverted on close.** `on_close`
  saved the whole in-memory config. It now saves only the window size onto
  the on-disk copy (every in-app setting is already saved when it changes).
  Two tests added: **103 total**.

### Changed
- User setting `service_control_as_root` = true (user-approved), so service
  start/stop uses `wsl -u root`. sudoers is unchanged.
- Removed stale artifacts: `dist\LocalAIManager.exe` (old onefile build),
  `dist\config.json`, the uv wheel and sdist in `dist`, the root `config.json`
  (old cwd bug) and the old `pyinstaller.log`. Added `.gitignore`.

### Verified live (2026-11-17, real Ollama 0.40.16 / RTX 3090 Ti)
- Load `gpt-oss:20b`: 14.8 s, `/api/ps` lists it (12.0 GiB), VRAM 2.1 → 15.2 GiB.
- Unload: confirmed via `/api/ps`, VRAM back to 2.2 GiB.
- Gaming Mode ON with a model loaded: unloaded in 0.3 s, VRAM 15.3 → 2.2 GiB;
  distro Running, service active, API reachable throughout.
- Gaming Mode OFF: no model reloaded (checked after 3 s).
- Service `start` via `wsl -u root` succeeded (no-op on an active service).
- Service **stop/start** (user-approved): stop → `inactive`, API unreachable;
  start → `active`, API back after 5.6 s with both models listed.
- Rebuilt exe: `service_control_as_root` survives launching and closing the app.

### Tooling
- Git 2.56 installed (winget, user-approved); repository initialised on
  `main` with `.gitignore` (33 tracked files; `.venv`, `build`, `dist`,
  caches excluded).

## [0.2.0-ui] — 2026-11-17 — VS Code-style CustomTkinter UI and app icon (Claude Code)

### Added
- **CustomTkinter 6.x GUI with a VS Code layout** (D-009): activity bar, side
  bar (Environment + Models with live status dots), tabbed editor area
  (Dashboard, Models, GPU, Settings), resizable OUTPUT panel, and a status bar
  that turns purple in Gaming Mode. Shortcuts: Ctrl+B, Ctrl+J, Ctrl+1..4,
  Ctrl+, and F5. Tooltips on activity bar icons.
- GPU view with stat tiles and 3-minute utilization/VRAM history charts.
- VS Code-style Settings view (category: name, description, switch), plus an
  "Open Settings Folder" button. Dashboard and Settings scroll when the
  window is small.
- **App icon** (D-010): `tools/make_icon.py` generates `assets/app.ico` and
  `app.png`. Used for the title bar, the taskbar (explicit AppUserModelID),
  and the exe file icon.
- New modules `theme.py` (palette, fonts, glyphs, ttk styles) and
  `widgets.py` (reusable VS Code-style widgets).
- 8 new UI tests (views, side bar toggle, panel toggle, side bar models,
  status bar state/colors, chart history, offline state, icon asset):
  **101 tests total**.

### Changed
- Runtime dependency `customtkinter>=6.0,<7`; dev dependency `pillow`.
  Removed the unused `pywin32` optional extra.
- PyInstaller spec bundles CustomTkinter data files and the app assets and
  sets the exe icon. Build size is 30.4 MB.
- Default window size is 1200×800 (min 1000×640). Window size is saved without
  DPI scaling.
- Business logic (monitor thread, action worker, Gaming Mode, settings) is
  unchanged.

### Verified (2026-11-17)
- `uv run pytest -q`: 101 passed.
- The dev app ran against live (read-only) status, and all four views were
  captured via PrintWindow and reviewed. Clipping on Dashboard/Settings was
  fixed and recaptured.
- The packaged exe launched with Python removed from PATH. The exe file icon
  (ExtractAssociatedIcon) and the taskbar entry (screen capture) show the new
  icon. Closed cleanly.

## [0.1.0-audit] — 2026-11-17 — Audit and repair (Claude Code)

Independent audit of the Qwen-generated 0.1.0. Qwen's "24 tests passed" was
confirmed, but those tests only covered dataclass defaults and string
formatting. Qwen's reported build was found to be misconfigured (see Build).

### Added
- Collaboration files: `AGENTS.md`, `CLAUDE.md`, `docs/PROJECT_HANDOFF.md`,
  `docs/DECISIONS.md`, `docs/CHANGELOG.md`.
- Model load / unload / unload-all through the Ollama API (`/api/generate`
  with `keep_alive`), with verification against `/api/ps`.
- Loaded-model display (name, VRAM, expiry) and a Status/VRAM column in the
  model table.
- systemd service status, start and stop for `ollama` in Ubuntu-24.04
  (`sudo -n`; fails safely with guidance; opt-in `service_control_as_root`).
- Distro start (`wsl -d … --exec /bin/true`) and terminate (target distro only,
  confirmation required).
- Auto-load last model on app start (OFF by default; skipped in Gaming Mode;
  boots the distro and waits up to 90 s for the API).
- Configurable model keep-alive (default 30 min).
- GPU power draw and a VRAM usage bar.
- VS Code-style dark theme, a log panel, and a rotating log file at
  `%APPDATA%\LocalAIManager\logs\app.log`.
- 93 tests (was 24). All external calls are mocked; `tests/conftest.py` blocks
  real subprocess/HTTP calls and isolates settings.

### Fixed
- **Critical — WSL detection was broken:** `wsl.exe` UTF-16 output was decoded
  as ANSI, yielding distros `['\x00', '\x00*\x00']` and "WSL1/unknown".
  Explicit decoding now handles UTF-16LE (+ `WSL_UTF8=1`).
- **Critical — Gaming Mode did nothing useful:** it ran
  `taskkill /IM ollama.exe` on Windows (Ollama runs in WSL) and "disable" ran a
  Windows `ollama serve` that does not exist. It now unloads all models,
  verifies, and keeps WSL/Ollama running.
- **High — settings written to the current working directory:**
  `Path(os.environ.get(..., ""))` is `Path(".")` (truthy), so the APPDATA
  branch never ran. Settings are now in `%APPDATA%\LocalAIManager\settings.json`.
- **High — crash on unknown or invalid settings keys** (`Config(**data)` raised
  `TypeError`). Unknown keys are ignored, wrong types rejected, and values
  clamped. Saving is atomic.
- **High — Tk thread blocked / unsafe threading:** `nvidia-smi` ran on the Tk
  thread every second; model pulls ran on the Tk thread; workers set Tk
  variables directly. A monitor thread plus single action worker now post to a
  UI queue (D-006).
- **High — "Stop" ran `wsl --shutdown`** (all distros, no confirmation); bare
  `wsl` was used to "start". Replaced (D-003).
- **High — Start with Windows broken for the exe:** it wrote a `.pyw` importing
  from the source tree. Now uses the HKCU Run value (D-007).
- **Medium — PyInstaller spec** produced a onefile exe copied into the onedir
  folder. It now builds a real onedir (D-008).
- **Low — log output in windowed build:** no stream handler when `sys.stderr`
  is None.

### Removed
- Model pull and delete from the UI (not in scope; pull blocked the UI thread;
  delete is destructive). Model downloads stay a manual `ollama pull` task.
- "Install WSL2" button (needs elevation and a reboot).
- Windows-side `ollama serve` / `taskkill` logic.

### Verified (2026-11-17, development workstation)
- `uv run pytest -v`: **93 passed**, 5 consecutive runs, no skips.
- Read-only live probe: Ubuntu-24.04 Running/WSL2, service `active`, API
  v0.40.16, both models, loaded model + expiry, and GPU telemetry all parsed
  correctly.
- Dev GUI and packaged exe launched, rendered correctly (screenshots via
  PrintWindow), and closed cleanly on WM_CLOSE. The exe was run with Python
  removed from PATH.
- `sudo -n` fail-safe confirmed live; HKCU Run key confirmed untouched.
- **Not verified live:** model load/unload, Gaming Mode enable, service
  start/stop success path, distro terminate, Start with Windows enable.
  These are disruptive and need user approval; they are covered by unit tests
  only.
