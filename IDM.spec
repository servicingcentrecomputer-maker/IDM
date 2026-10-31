# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for IDM, the updater and the native host.

Build with the project automation (build_windows.ps1) or directly::

    python -m PyInstaller --noconfirm --clean IDM.spec

The application is packaged in one-folder mode.  All Qt plugins, Qt modules
and Python dependencies that the Analysis phase detects are collected by
PyInstaller's built-in hooks.  The `assets` folder is copied intact so that
`idm.core.paths.asset_path` resolves both in development and when frozen.

``IDM_Updater.exe`` is built as a single file so it can be copied into the
temporary update folder and run outside the installation directory.  It never
imports PySide6.  The build script copies ``dist\\IDM_Updater.exe`` into
``dist\\IDM\\IDM_Updater.exe`` so the installer ships both executables.

``IDM_NativeHost.exe`` is the browser native messaging host.  It is a
console-subsystem, Qt-free single file because it communicates over inherited
stdin/stdout; browsers launch it without showing a console window.  The build
script stages it into ``dist\\IDM\\IDM_NativeHost.exe`` for the installer.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)
APP_NAME = "IDM"
UPDATER_NAME = "IDM_Updater"
NATIVE_HOST_NAME = "IDM_NativeHost"

datas = [(str(ROOT / "assets"), "assets")]

hiddenimports = [
    "PySide6.QtSvg",
    *collect_submodules("idm"),
]

# Modules that are never imported by IDM.  Excluding them keeps the bundle
# smaller without removing any functionality.
excludes = [
    "tkinter",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNfc",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "logo" / "idm.ico"),
    version=str(ROOT / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# The updater is deliberately Qt-free and built as one self-contained file.
updater_a = Analysis(
    ["updater_main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("idm.updater"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[*excludes, "PySide6", "shiboken6"],
    noarchive=False,
    optimize=0,
)
updater_pyz = PYZ(updater_a.pure, updater_a.zipped_data)

updater_exe = EXE(
    updater_pyz,
    updater_a.scripts,
    updater_a.binaries,
    updater_a.datas,
    [],
    name=UPDATER_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "logo" / "idm.ico"),
    version=str(ROOT / "version_info_updater.txt"),
)

# The native messaging host must remain Qt-free and uses stdin/stdout for the
# browser protocol.  It is built with the console subsystem so those handles
# are available; Chrome and Firefox launch native hosts without a visible
# window.
native_host_a = Analysis(
    ["native_host_main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "integrations.native_host",
        "integrations.message_handler",
        "integrations.protocol",
        "integrations.browser_registry",
        "integrations.browser_detector",
        "integrations.paths",
        "idm.core.url_utils",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[*excludes, "PySide6", "shiboken6"],
    noarchive=False,
    optimize=0,
)
native_host_pyz = PYZ(native_host_a.pure, native_host_a.zipped_data)

native_host_exe = EXE(
    native_host_pyz,
    native_host_a.scripts,
    native_host_a.binaries,
    native_host_a.datas,
    [],
    name=NATIVE_HOST_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "logo" / "idm.ico"),
    version=str(ROOT / "version_info_native_host.txt"),
)
