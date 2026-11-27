# Reproducing the published core

The final publication check on 2026-11-27 covers the assembled source, an installed
Python wheel and a deterministic planning example. It does not certify a Windows
desktop release. Application code and tests are unchanged from the preceding
build-source milestone; package version remains `0.4.0`.

## Inspect the example

From the repository root, using Python 3.11 or newer:

```sh
python -X utf8 -m app "hello 123!"
```

The complete generated output is saved in
[`examples/hello-123.json`](../examples/hello-123.json). It contains four tokens
and seven speech/pause units. Nonempty speech instructions, in order, are
`H E L L O`, `hello`, `一二三`, and `感叹号`. This is a speech **plan**; no audio is
played, recorded or transmitted. UTF-8 mode makes the Chinese output explicit
when redirecting output on systems with another default encoding.

## Build and install the Python package

Use a fresh virtual environment. After `python -m venv .venv`, activate it with
`source .venv/bin/activate` on macOS/Linux or `.venv\Scripts\activate.bat` in a
Windows command prompt. Then, from the repository root:

```sh
python -m pip wheel --no-deps --wheel-dir wheelhouse .
python -m pip install --no-index --no-deps wheelhouse/english_spell_reader_core-0.4.0-py3-none-any.whl
```

The wheel build may download the declared setuptools/wheel build tools. Core
installation does not install speech packages; the generated wheel contains the
`app` package and distribution metadata. Use the repository or source archive for
the tests, examples, documentation and Windows build scripts.

To check the installed package without importing from the checkout, run this
Python snippet from the repository root in that activated environment:

```python
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

expected = json.loads(Path("examples/hello-123.json").read_text(encoding="utf-8"))
with TemporaryDirectory() as directory:
    result = subprocess.check_output(
        [sys.executable, "-I", "-X", "utf8", "-m", "app", "hello 123!"],
        cwd=directory,
        text=True,
        encoding="utf-8",
    )
assert json.loads(result) == expected
print("Installed-package output matches the published example.")
```

`-I` uses isolated Python mode; the temporary working directory also separates
this check from the source tree. The comparison checks the complete JSON plan,
not just a successful process exit.

## Original regression suite

Run tests from the repository root because the original packaging tests inspect
relative script/spec paths:

```sh
python -m pip install "pytest>=8.0"
python -m pytest -q
python -m compileall -q app tests scripts
```

The included suite has 151 tests: 150 preserved original tests and one CLI
regression added during publication. No original tests were removed, weakened or
marked skipped. Speech and GUI tests use doubles. The packaging tests inspect
source text; they do not execute the Windows builder.

## Evidence and limits

The local verification record contains the actual commands, interpreter versions,
results, wheel hash and source-file comparisons. Private machine paths and local
receipt records are not distributed in this repository.

| Check | Publication evidence |
| --- | --- |
| Clean source archive | Exported from the preceding reviewed Git commit before preparing this milestone |
| Included Python suite | 151 tests passed on macOS with Python 3.11 and Python 3.14; a network audit guard was enabled in the test interpreter |
| Python distribution | Built a wheel and installed it without dependencies into a fresh Python 3.11 virtual environment |
| Installed CLI and API examples | Complete JSON matched the published example from outside the checkout; both README Python examples ran with the installed package |
| Syntax | Python compilation and PyInstaller-spec AST parsing passed |
| Windows scripts | CRLF retained in source archive; original script behavior was not executed |
| Linux/Windows execution | Not run; portable source and a platform-independent wheel filename are not platform-validation evidence |
| Real speech/GUI and Windows executable | Not run; no model inference, service calls or playback evidence is claimed |

Python 3.11 and 3.14 checks on the same macOS host do not establish operation on
every supported Python version or operating system. Optional speech/build
dependencies and model versions are not locked. A real Windows build additionally
requires separately obtained, appropriately licensed Piper model/config pairs.
See [Windows build scope](WINDOWS_BUILD.md) for prerequisites and the recovered
builder's missing-executable exit-code limitation.

The unavailable original `test_symbols.py`, exact `6.6` settings comparison and
current `run_windows.bat` remain source-recovery gaps. They have not been
reconstructed or declared passing. The existing direct GUI entry is documented,
and the recovered builder does not depend on that missing launcher.

The GUI can fall back from Piper to the external Edge service; see
[speech and network boundaries](SPEECH.md). The JSON example uses neither route.
