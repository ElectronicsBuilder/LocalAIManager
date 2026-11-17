# AGENTS.md — Shared Instructions for Coding Agents

This file is the single source of project instructions for every coding agent
(Claude Code, Codex, Continue/Qwen, or others) working on **Local AI Manager**.
`CLAUDE.md` points here. Keep this file accurate when conventions change.

## 1. Session protocol (mandatory)

1. **Before starting work**, read this file and `docs/PROJECT_HANDOFF.md`.
2. Review current status: skim `docs/CHANGELOG.md` (latest entries) and
   `docs/DECISIONS.md`, then run the test suite to confirm the baseline.
3. **After making changes**, run the relevant tests (see §4). Never claim a
   test, build, or GUI check passed unless you actually executed it.
4. **After substantial work**, update `docs/PROJECT_HANDOFF.md` with verified
   results and next steps.
5. Record architectural changes in `docs/DECISIONS.md` (new numbered entry;
   never silently rewrite an old decision — supersede it).
6. Record completed fixes and features in `docs/CHANGELOG.md`.
7. Communicate exclusively in **English** (code, comments, docs, UI text, logs).
8. **Never run two agents simultaneously against the same files.** If another
   agent may be active, stop and ask the user.

## 2. Safety restrictions

Do **not** do any of the following without explicit, per-action authorization
from the user:

- Modify Windows startup (Run registry key, Startup folder), the registry in
  general, firewall rules, or scheduled tasks.
- Modify WSL configuration (`.wslconfig`, `/etc/wsl.conf`), shut down WSL
  (`wsl --shutdown`), or terminate the Ubuntu-24.04 distribution.
- Stop or restart the `ollama` systemd service.
- Modify Linux sudo permissions (`/etc/sudoers`, `/etc/sudoers.d/*`) or store
  sudo passwords anywhere.
- Download, pull, delete, or replace AI models.
- Unload a model that may be in use (e.g. by Continue in VS Code) — ask first.
- Expose the Ollama API beyond loopback (`OLLAMA_HOST=0.0.0.0` etc.).

Read-only probes are always fine: `wsl --list --verbose`,
`wsl -d Ubuntu-24.04 -- systemctl is-active ollama`, `GET /api/tags`,
`GET /api/ps`, `GET /api/version`, `nvidia-smi`.

Unit tests must never touch the real system: `tests/conftest.py` blocks real
`subprocess` and `urllib` calls and redirects settings to a temp directory.

## 3. Development conventions

- Python **3.13**, managed by **uv** (`.venv` in the project). Use `uv run …`.
  HTTPS on this machine is intercepted (uv reports `UnknownIssuer`); when uv
  needs the network, add `--system-certs` (uses the Windows certificate store).
- GUI: **CustomTkinter 6.x** on top of Tkinter, laid out like VS Code
  (D-009). The only runtime dependency is `customtkinter`; ttk is still used
  for widgets CTk lacks (Treeview, Scrollbar). Add any other runtime
  dependency only with a new decision record. Pillow is a **dev-only**
  dependency (icon generation) and must not be imported by the app.
- Colors, fonts and glyphs come from `theme.py`; reusable VS Code-style
  pieces live in `widgets.py`. Do not hard-code colors in `ui.py`.
- The app icon is generated: edit `tools/make_icon.py`, then run
  `uv run python tools/make_icon.py` (writes `src/local_ai_manager/assets/`).
- Prefer targeted fixes over rewrites. Preserve working behavior.
- Subprocesses: always pass argument **lists**, `shell=False`, a timeout, and
  `CREATE_NO_WINDOW`. Validate any user/config-supplied name (distro, service,
  model) before passing it to a command. Use `wsl.exe --exec` (no Linux shell).
- `wsl.exe` writes UTF-16LE; decode through `wsl._decode()` (also sets
  `WSL_UTF8=1`).
- **Threading:** background threads must never touch Tk widgets or Tk
  variables, and must never call `root.after`. They post callables to
  `App._ui_queue`; the Tk thread drains it (`App._drain_ui_queue`).
- Only one user action runs at a time (`App._run_action`); the monitor thread
  polls status independently.
- Settings live in `%APPDATA%\LocalAIManager\settings.json`
  (override with `LOCAL_AI_MANAGER_CONFIG_DIR`). Never write next to the exe.
- Defaults that must stay OFF: Gaming Mode, Start with Windows, auto-load last
  model. Model keep-alive default: 30 minutes.
- Exclude `.venv`, `build`, `dist`, `.git`, `__pycache__`, `.pytest_cache`
  from broad searches.

## 4. Commands

```powershell
uv run pytest -v                                   # unit tests (must all pass)
uv run python run.py                               # launch dev GUI
uv run pyinstaller local_ai_manager.spec --noconfirm   # build
.\dist\LocalAIManager\LocalAIManager.exe           # launch packaged GUI
```

## 5. Architecture (summary — details in docs/PROJECT_HANDOFF.md)

```
Windows host (Tkinter app)                      WSL2: Ubuntu-24.04
┌───────────────────────────┐   wsl.exe --exec  ┌─────────────────────────┐
│ ui.py  (Tk thread)        │──────────────────▶│ systemd: ollama.service │
│   ▲ _ui_queue             │   HTTP loopback   │ Ollama API :11434       │
│ monitor thread / action   │──────────────────▶│ (forwarded to Windows   │
│ worker thread             │                   │  localhost by WSL)      │
│ gpu.py → nvidia-smi.exe   │                   └─────────────────────────┘
└───────────────────────────┘
```

| Module | Responsibility |
|---|---|
| `config.py` | Settings dataclass, validation, atomic save to `%APPDATA%` |
| `wsl.py` | `wsl.exe` wrapper, distro detection, systemd service control (`sudo -n`) |
| `ollama.py` | Ollama HTTP API: list/running models, load/unload, wait-for-unload |
| `gpu.py` | `nvidia-smi` telemetry |
| `gaming.py` | Gaming Mode: unload all models and verify, block reloads |
| `startup.py` | HKCU `Run` value for Start with Windows (explicit user action only) |
| `ui.py` | VS Code-style GUI: views, monitor thread, action worker, Output panel |
| `theme.py` | Dark Modern palette, fonts, Segoe MDL2 glyphs, ttk styles, icon path |
| `widgets.py` | Activity bar, side bar sections/rows, tabs, status items, cards, charts |
| `main.py` | Logging setup and entry point |
| `assets/` | `app.ico` / `app.png` (generated by `tools/make_icon.py`) |
