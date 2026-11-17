# Architectural Decisions

Numbered, append-only log. To change a decision, add a new entry that
supersedes the old one and mark the old one "Superseded by D-NNN".

---

## D-001 — Python 3.13 + Tkinter, standard library only

**Status:** Partly superseded by D-009 (CustomTkinter is now a runtime
dependency). Python 3.13 and the standard-library backends (urllib, winreg,
subprocess) still apply.

**Decision:** The app is a native Windows desktop GUI in Python 3.13 using
Tkinter/ttk. Runtime has **no third-party dependencies**; HTTP uses `urllib`,
registry uses `winreg`, process control uses `subprocess`.

**Why:** Tkinter ships with CPython, keeps the PyInstaller bundle small
(~15–20 MB onedir), and avoids dependency drift. The app's UI needs are modest
(status panels, a model table, toggles, a log).

**Consequences:** Styling is done manually through `ttk.Style` (`clam` theme
with VS Code–like dark colors). No async framework; concurrency uses threads
plus a queue drained on the Tk thread (see D-006).

---

## D-002 — Local inference through Ollama in WSL2, reached via loopback HTTP

**Status:** Accepted

**Decision:** Ollama runs inside WSL2 (Ubuntu-24.04) as the `ollama` systemd
service. The app talks to it only through the HTTP API at
`http://127.0.0.1:11434`, which WSL forwards to Windows localhost. Model
listing uses `/api/tags`, loaded models `/api/ps`, load/unload
`/api/generate` with `keep_alive`.

**Why:** No Windows-side `ollama.exe` is installed (verified 2026-11-17), so
the original approach (`ollama serve` / `taskkill ollama.exe` on Windows) could
never work. The HTTP API is stable, needs no credentials, and is the same path
Continue uses.

**Consequences:** No cloud services. The app never changes `OLLAMA_HOST`; the
service is bound to loopback (verified: no `OLLAMA_HOST` in the unit's
environment). Model download/delete are out of scope (removed from the UI).

---

## D-003 — WSL2 integration via `wsl.exe --exec`, privileged actions via `sudo -n`

**Status:** Accepted

**Decision:**
- All WSL commands are run as argument lists through
  `wsl.exe -d <distro> --exec <cmd> …` (no Linux shell, no string
  interpolation). Distro and service names are validated against a strict
  regex before use.
- `wsl.exe` output is decoded explicitly (UTF-16LE detection, plus
  `WSL_UTF8=1`), because the default decoding produced garbage distro names.
- Service status uses unprivileged `systemctl is-active`.
- Service start/stop use `sudo -n systemctl …`. `-n` makes sudo fail
  immediately instead of prompting. The app never stores or asks for a sudo
  password and never edits sudoers. If not authorized, the user gets a clear
  message explaining that a NOPASSWD rule is required and that they must add
  it themselves.
- Stopping the distro uses `wsl --terminate <distro>` (only the target distro,
  never `wsl --shutdown`) and requires a confirmation dialog.
- `wsl --install` was removed from the UI (needs elevation and a reboot; out
  of scope for a manager app).

**Why:** Safety restrictions in AGENTS.md; `sudo` on this machine requires a
password (verified with `sudo -n true` → "a password is required").

---

## D-004 — Gaming Mode unloads models but keeps WSL and Ollama running

**Status:** Accepted (supersedes initial implementation, which stopped the
Ollama server)

**Decision:** Enabling Gaming Mode:
1. Reads loaded models from `/api/ps`.
2. Sends `keep_alive: 0` unload requests for each.
3. Polls `/api/ps` until empty (timeout 30 s) and reports success/failure.
4. Persists `gaming_mode_enabled = true`.

While active, the app refuses its own model loads and skips auto-load of the
last model. If another client (e.g. Continue) loads a model, the UI shows a
warning; the app does **not** forcibly unload it in the background.
Disabling Gaming Mode only clears the flag — no automatic reload.

**Why:** Keeping WSL and Ollama running makes returning from a game fast and
avoids privileged service operations. Background re-unloading could break a
user's deliberate use of a model.

**Consequences:** Gaming Mode cannot stop external clients from loading models;
this is documented as a limitation.

---

## D-005 — Settings in `%APPDATA%\LocalAIManager\settings.json`

**Status:** Accepted

**Decision:** User preferences persist to
`%APPDATA%\LocalAIManager\settings.json` (overridable with
`LOCAL_AI_MANAGER_CONFIG_DIR`). Defaults live in the `Config` dataclass, not in
a file. Loading ignores unknown keys, rejects values of the wrong type
field-by-field, and falls back to defaults on corrupt JSON. Saving is atomic
(temp file + `os.replace`). A legacy `config.json` in the same directory is
read once if `settings.json` does not exist.

**Why:** The original code (due to a `Path("")` truthiness bug) wrote
`config.json` into the current working directory, which breaks under Program
Files and scatters files. Separating defaults from user data keeps the onedir
build portable.

---

## D-006 — Thread model: monitor thread + single action worker + UI queue

**Status:** Accepted

**Decision:**
- A daemon **monitor thread** polls WSL state, service state, Ollama
  models/loaded models, and GPU telemetry every `gpu_poll_interval_ms`
  (default 2000 ms; WSL/service status every 5th tick).
- **User actions** run one at a time on a worker thread; action buttons are
  disabled while one runs.
- Background threads only post callables to a `queue.Queue`; the Tk thread
  drains it every 100 ms. Background threads never call Tk APIs (including
  `root.after`).
- On close, a stop `Event` is set, the monitor thread is joined (bounded),
  settings are saved, and the window is destroyed.

**Why:** The original code ran `nvidia-smi` on the Tk thread every second,
performed multi-GB model pulls on the Tk thread, and set Tk variables from
worker threads.

---

## D-007 — Start with Windows via HKCU Run key

**Status:** Accepted (supersedes Startup-folder `.pyw` launcher)

**Decision:** Start with Windows writes/removes the value `LocalAIManager`
under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, only when the user
ticks/unticks the checkbox. Frozen build: quoted exe path. Dev run:
`pythonw.exe` from the venv plus `run.py`. Status is read from the registry.

**Why:** The old `.pyw` launcher imported from the source tree and did not
work for the packaged exe; it also required pywin32 for the shortcut.
`winreg` is in the standard library and the Run key needs no elevation.

---

## D-008 — PyInstaller onedir build

**Status:** Accepted

**Decision:** `local_ai_manager.spec` builds a proper onedir app
(`EXE(exclude_binaries=True)` + `COLLECT`). Output:
`dist\LocalAIManager\LocalAIManager.exe`. No onefile build.

**Why:** The original spec passed binaries/datas to `EXE` *and* `COLLECT`,
producing a onefile exe duplicated into the onedir folder (slow startup from
temp extraction plus a redundant `_internal`). Onedir starts faster and is
easier to inspect.

---

## D-009 — CustomTkinter with a VS Code–style layout

**Status:** Accepted (2026-11-17, requested by the user). Supersedes the
"no third-party runtime dependencies" part of D-001.

**Decision:** The GUI uses **CustomTkinter 6.x** (`customtkinter>=6.0,<7`)
and copies VS Code's structure and "Dark Modern" palette:
- Activity bar (Dashboard, Models, GPU; Settings gear at the bottom).
  Clicking the active icon toggles the side bar.
- Side bar with collapsible ENVIRONMENT and MODELS sections showing live
  status dots.
- Editor area with tabs for the four views, above a resizable OUTPUT panel
  (log).
- Status bar: green remote indicator (`WSL: <distro>`), service state,
  action status, loaded model, VRAM, GPU. Blue normally, purple in Gaming
  Mode (like VS Code's debug status bar).
- Shortcuts: Ctrl+B side bar, Ctrl+J panel, Ctrl+1..4 views, Ctrl+, Settings,
  F5 refresh.

ttk `Treeview`/`Scrollbar` are kept (CTk has no table widget) and styled in
`theme.apply_ttk_styles`. Icons in the chrome are Segoe MDL2 Assets glyphs,
which ship with Windows 10/11, so no image files are needed.

**Why:** User request ("tkinter version 2", clarified as CustomTkinter, with a
full VS Code layout). CTk gives rounded buttons, switches and progress bars,
plus a dark title bar on Windows. The cost is ~1 MB in the build.

**Consequences:** All threading rules (D-006) apply unchanged to CTk widgets.
CTk scales geometry by DPI, so window size is stored unscaled
(`on_close`). CTk 6.0.0 was installed by uv; its API matched 5.x for every
call used.

---

## D-010 — Generated application icon

**Status:** Accepted (2026-11-17)

**Decision:** `tools/make_icon.py` (Pillow, dev-only) renders
`assets/app.ico` (16–256 px; simplified drawing at ≤24 px) and `app.png`.
The icon is applied in three places:
1. `root.iconbitmap()` → title bar (called before CTk's 200 ms default-icon
   hook, so CTk's own icon is never shown).
2. `SetCurrentProcessExplicitAppUserModelID("LocalAIManager.App")` → the
   dev run gets its own taskbar entry instead of grouping under python.exe.
3. PyInstaller `icon=` → the exe file icon in Explorer and on pinned taskbar
   items.

**Why:** User request for a taskbar and title bar icon. Generating the icon
from code keeps it reproducible and editable without binary design tools.

---

## D-011 — Continuous integration on GitHub Actions (Windows)

**Status:** Accepted (2026-11-17, requested by the user)

**Decision:** `.github/workflows/ci.yml` runs on `windows-latest` (the app is
Windows-only), on pushes to `main`, pull requests and manual dispatch:
1. **test:** `uv sync --locked` + `uv run pytest -v`.
2. **build** (after test): PyInstaller build, then `tools/smoke_test.ps1`,
   then upload `dist/LocalAIManager/` as an artifact (14 days).

uv is pinned (`UV_VERSION`) to the local version; dependencies come only from
`uv.lock`. Workflow permissions are `contents: read`.

The smoke test judges success from the app log, not the exit code: a
crashing windowed PyInstaller app shows an error dialog and never exits.
`ui: Settings:` is logged only after the UI is fully built. A deliberately
broken build (CustomTkinter themes removed) was confirmed to fail the smoke
test.

**Why:** Catch regressions and packaging breakage (missing data files,
hidden imports) automatically. The unit tests need no WSL, Ollama or GPU
because conftest blocks all real external calls.

**Consequences:** CI cannot exercise the real WSL/Ollama/GPU paths; those
remain manual, live checks (see CHANGELOG "Verified live").
