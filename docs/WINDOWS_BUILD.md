# Windows build source

This release publishes the existing build pipeline for review and reproduction.
It does **not** provide a verified Windows executable. Preparation was performed
on macOS without Windows, PowerShell, installed speech runtimes or voice models.

## Requirements and command

Use a dedicated checkout on Windows with Python 3.11 or newer, Tkinter and
PowerShell. The scripts download dependencies through pip and can recreate the
checkout's `.venv` when its pip installation cannot be repaired; do not store
unrelated files there.

The complete build requires separately obtained Piper `.onnx` model files and
matching `.onnx.json` configurations in `app/voices/piper/`. Obtain each pair
from its authorized source and check its license before use or redistribution.
No models, binaries or audio recordings are supplied here. Without suitable
models, the mandatory source Piper smoke check fails and stops the build.

From a Windows command prompt in the repository root:

```bat
scripts\build_windows.bat
```

The batch entry invokes `build_windows.ps1`, which:

1. Finds Python and creates or repairs a local virtual environment.
2. Installs the project's `dev`, `speech` and `build` dependency groups.
3. Runs pytest and `scripts/piper_smoke.py` against actual local Piper models.
4. Runs PyInstaller using `spelling_reader.spec`.
5. Invokes `scripts/piper_exe_smoke.py` against the executable, asking its
   `--piper-render` worker to create a nonempty WAV in a temporary directory.

The intended output is `dist/EnglishSpellReader.exe`. Inspect the output and all
smoke-check results: the recovered script has a final fallback that reports a
missing executable but returns exit code zero. Exit status alone is therefore
insufficient evidence of a successful build. The WAV checks measure format and
nonempty frames, not intelligibility, speaker playback or UI behavior.

Dependencies are not locked. A future Windows run must record the actual Python,
package and voice-model versions; no reproducible binary claim is made here.
The spec collects all matching model/config files from the model directory, so
only place assets there that you intend and are permitted to bundle.

The current `run_windows.bat` launcher could not be recovered. To run the source
after separately setting up the speech dependencies, use the existing command:

```bat
python -m pip install -e ".[speech]"
python -m app.main
```

The GUI's existing Piper-to-Edge fallback can send text to an external service;
see [speech and network boundaries](SPEECH.md).

## Source provenance and publication changes

| File | Recovered source | Publication change |
| --- | --- | --- |
| `scripts/build_windows.bat` | Local `6.6` snapshot | None; original CRLF retained |
| `scripts/piper_smoke.py` | Local `6.6` snapshot | None |
| `scripts/piper_exe_smoke.py` | Local `6.6` snapshot | None |
| `tests/test_packaging.py` | Local `6.6` snapshot | None; all three original tests retained |
| `spelling_reader.spec` | Local `New project 2` snapshot | None |
| `scripts/build_windows.ps1` | Recoverable Git blob `e38c2cae383b43c565cc4fc30ae69722c2b001a2` in the same project's local object store | Mixed newlines normalized to CRLF; install argument and its error message changed from `.[dev]` to `.[dev,speech,build]` |

The recovered PowerShell blob is mapped to `scripts/build_windows.ps1` by its
original Git tree. This is source provenance, not a claim of identity with the
unreadable current `6.6` file or of a particular development date. The original
blob remains preserved in local publication evidence.

The optional `build` extra restores the source project's existing
`pyinstaller>=6.0` requirement. Selecting all three extras is necessary because
this public extraction keeps its core runtime dependencies empty. No application
or original test logic was changed for this milestone. Git attributes retain
Windows script CRLF bytes in both clones and source archives; models and generated
audio are ignored to avoid accidental publication.

## What was verified

The three original packaging tests check source strings for runtime collection,
the packaged-executable smoke step and pip-repair ordering. They do not execute
PowerShell or PyInstaller. The full included Python suite uses fake backends for
speech and GUI behavior; Python compilation and spec syntax can also be checked
without installing speech runtimes.

Real Windows builds, real Piper model inference, packaged WAV generation, SAPI,
Edge calls, GUI interaction and audible playback remain unverified in this
publication. The build smoke scripts are published source, not successful test
results from this machine.
