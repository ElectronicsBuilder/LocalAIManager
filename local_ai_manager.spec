# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Local AI Manager (Windows onedir GUI app).

Build with:
    uv run pyinstaller local_ai_manager.spec --noconfirm

Output: dist\\LocalAIManager\\LocalAIManager.exe (+ _internal\\).
See docs/DECISIONS.md D-008 for why this is onedir only.
"""

from PyInstaller.utils.hooks import collect_data_files

ICON = "src/local_ai_manager/assets/app.ico"

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("src/local_ai_manager/assets", "local_ai_manager/assets"),  # window/taskbar icon
        *collect_data_files("customtkinter"),                          # themes, fonts
    ],
    hiddenimports=["local_ai_manager.ui"],  # imported lazily from main()
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "IPython", "jupyter", "matplotlib", "numpy", "pandas", "PIL", "cv2"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # onedir: binaries go to COLLECT, not into the exe
    name="LocalAIManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # GUI app, no console window
    icon=ICON,               # Explorer / pinned-taskbar icon of the exe file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="LocalAIManager",
)
