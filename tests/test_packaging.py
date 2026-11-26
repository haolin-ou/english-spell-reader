from pathlib import Path


def test_pyinstaller_spec_collects_piper_and_onnxruntime_runtime_files() -> None:
    spec_text = Path("spelling_reader.spec").read_text(encoding="utf-8")

    assert 'collect_data_files("piper")' in spec_text
    assert 'collect_dynamic_libs("piper")' in spec_text
    assert 'collect_submodules("piper")' in spec_text
    assert "_piper_espeak_datas" in spec_text
    assert '"espeak-ng-data"' in spec_text
    assert 'collect_data_files("onnxruntime")' in spec_text
    assert 'collect_dynamic_libs("onnxruntime")' in spec_text
    assert 'collect_submodules("onnxruntime")' in spec_text
    assert "binaries=_piper_runtime_binaries + _onnxruntime_binaries" in spec_text
    assert "_piper_voice_datas + _piper_runtime_datas + _piper_espeak_datas + _onnxruntime_datas" in spec_text


def test_windows_build_runs_packaged_exe_piper_smoke_test() -> None:
    script_text = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")

    assert "scripts\\piper_exe_smoke.py" in script_text
    assert "Running packaged Piper smoke test..." in script_text
    assert "Packaged Piper smoke test failed. Build stopped." in script_text


def test_windows_build_repairs_broken_reused_venv_pip_before_upgrading() -> None:
    script_text = Path("scripts/build_windows.ps1").read_text(encoding="utf-8")

    assert "function Test-VenvPip" in script_text
    assert "function Initialize-VenvPip" in script_text
    assert "Virtual environment pip is not usable. Attempting repair with ensurepip..." in script_text
    assert "Existing virtual environment pip is still broken. Recreating .venv..." in script_text
    assert script_text.index("Initialize-VenvPip") < script_text.index("Upgrading pip, setuptools, and wheel...")
