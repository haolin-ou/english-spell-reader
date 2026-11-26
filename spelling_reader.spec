# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import importlib.util

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


_repo_root = Path(SPECPATH)
_piper_asset_dir = _repo_root / "app" / "voices" / "piper"
_piper_voice_datas = []
for pattern in ("*.onnx", "*.onnx.json"):
    for asset_path in sorted(_piper_asset_dir.glob(pattern)):
        _piper_voice_datas.append((str(asset_path), "app/voices/piper"))

_piper_runtime_datas = collect_data_files("piper")
_piper_runtime_binaries = collect_dynamic_libs("piper")
_piper_espeak_datas = []
_piper_spec = importlib.util.find_spec("piper")
if _piper_spec and _piper_spec.origin:
    _piper_package_dir = Path(_piper_spec.origin).parent
    _piper_espeak_dir = _piper_package_dir / "espeak-ng-data"
    if _piper_espeak_dir.exists():
        for asset_path in sorted(_piper_espeak_dir.rglob("*")):
            if asset_path.is_file():
                relative_parent = asset_path.relative_to(_piper_espeak_dir).parent
                _piper_espeak_datas.append(
                    (
                        str(asset_path),
                        str(Path("piper") / "espeak-ng-data" / relative_parent),
                    )
                )
_onnxruntime_datas = collect_data_files("onnxruntime")
_onnxruntime_binaries = collect_dynamic_libs("onnxruntime")
_piper_hiddenimports = collect_submodules("piper") + collect_submodules("onnxruntime")
_edge_tts_hiddenimports = collect_submodules("edge_tts")

a = Analysis(
    ["app/main.py"],
    pathex=[],
    binaries=_piper_runtime_binaries + _onnxruntime_binaries,
    datas=_piper_voice_datas + _piper_runtime_datas + _piper_espeak_datas + _onnxruntime_datas,
    hiddenimports=[
        # AppController loads these modules via importlib.import_module().
        "app.parser",
        "app.models",
        "app.symbol_map",
        "app.speech_engine",
        "app.controller",
        "app.ui",
        "app.piper_worker",
        # pyttsx3 uses a dynamic driver import on Windows for SAPI5 playback.
        "pyttsx3",
        "pyttsx3.drivers",
        "pyttsx3.drivers.sapi5",
        # Common Windows COM modules needed by pyttsx3's SAPI integration.
        "comtypes",
        "comtypes.client",
        "comtypes.gen",
        "pythoncom",
        "pywintypes",
        "win32com",
        "win32com.client",
    ]
    + _piper_hiddenimports
    + _edge_tts_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EnglishSpellReader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
