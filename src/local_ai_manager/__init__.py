"""Local AI Manager - a Tkinter GUI for managing local AI tooling.

Modules:
    main       - logging setup and application entry point
    config     - settings in %APPDATA%\\LocalAIManager\\settings.json
    wsl        - wsl.exe wrapper, distro state, systemd service control
    ollama     - Ollama HTTP API: models, loaded models, load/unload
    gpu        - nvidia-smi telemetry
    gaming     - Gaming Mode (unload models, keep WSL and Ollama running)
    startup    - optional Start with Windows (HKCU Run key)
    ui         - Tkinter GUI, monitor thread, action worker

See AGENTS.md and docs/PROJECT_HANDOFF.md.
"""

__version__ = "0.1.0"
