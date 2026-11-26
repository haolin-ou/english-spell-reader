# English Spell Reader — Planning, Rules and Speech Orchestration

A deterministic Python parser that turns English words, numbers, punctuation,
and whitespace into explicit speech and pause instructions. It separates text
interpretation from the speech backend so the plan can be inspected and tested
without playing audio.

## Current publication

This is a **staged public extraction of an existing local Windows spelling-reader
project**. Publication began on 2026-11-25; commit dates record preparation and
publication here, not the original application's development timeline. AI tools
assist with extraction, documentation, and verification.

The current extraction includes the original parser, rule persistence, timing
helpers, speech adapters, controller, UI and application/worker entry points.
Their source and available original tests are copied unchanged. A lightweight
package initializer and JSON command-line example are publication conveniences;
the original desktop package initializer is not used here.

The settings implementation comes from local snapshot `6.4`. The speech engine,
parser, timing helpers and Piper/main entry points come from `6.6`; controller/UI
and additional tests were recovered from `1111` and `New project 2` copies of the
same project. Exact per-file provenance is documented in
[speech publication scope](docs/SPEECH.md). All 148 included tests pass against
this assembled source. This is not claimed to be an identical full `6.6` snapshot.

**Validation is limited to the pure core and fake speech/UI backends.** Real
Windows playback, real SAPI/Piper/Edge calls, GUI interaction and packaging have
not been verified here. Voice models and Windows build scripts are not included
in this slice. This is application orchestration around existing speech systems,
not an original trained speech model or a validated desktop binary.

## Try it

Python 3.11 or newer is required. The parser and example need no third-party
runtime packages. From the repository root:

```sh
python -m app "hello 123!"
```

The command prints JSON with source spans, tokens, selected options, and ordered
speech/pause units. The defaults spell each English word before reading it and
read digits using Chinese digit names. No audio is generated or transmitted.

To configure the parser in Python:

```python
from app.models import NumberMode, ParseOptions, ReadingMode
from app.parser import build_speech_plan

plan = build_speech_plan(
    "hello 123!",
    ParseOptions(
        reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
        number_mode=NumberMode.DIGIT_BY_DIGIT,
    ),
)
for unit in plan.units:
    print(unit.action.value, unit.speak_text, unit.pause_ms)
```

## Save and reuse rules

The standalone `app.settings` module reads and writes JSON rules, and
`app.timing` resolves letter-pause controls. They use only the Python standard
library. Saved rules are not loaded automatically by the parser or JSON CLI;
callers explicitly map them to `ParseOptions`.

This example uses a temporary file, leaving any existing reader preferences alone:

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import NumberMode, ParseOptions, ReadingMode
from app.parser import build_speech_plan
from app.settings import ReaderRules, load_rules, save_rules
from app.timing import resolve_letter_pause_ms

with TemporaryDirectory() as directory:
    path = Path(directory) / "rules.json"
    save_rules(
        ReaderRules(
            special_words=frozenset({"and"}),
            word_pause_ms=250,
            letter_pause_ms=10,
            custom_letter_pause_ms=33,
        ),
        path,
    )
    rules = load_rules(path)
    plan = build_speech_plan(
        "and hello",
        ParseOptions(
            reading_mode=ReadingMode(rules.reading_mode),
            number_mode=NumberMode(rules.number_mode),
            special_words=rules.special_words,
            word_pause_ms=rules.word_pause_ms,
            letter_pause_ms=resolve_letter_pause_ms(
                rules.letter_pause_ms, rules.custom_letter_pause_ms
            ),
        ),
    )
    print([(unit.action.value, unit.speak_text, unit.pause_ms) for unit in plan.units])
```

`save_rules` creates parent directories and overwrites the chosen JSON file.
Without an explicit path, the existing implementation uses
`%APPDATA%/EnglishSpellReader/rules.json` when `APPDATA` is set, otherwise
`~/.english_spell_reader_rules.json`. No real user preferences are distributed
in this repository. See [rule persistence and timing](docs/RULES.md) for scope
and normalization details.

## Speech and desktop source

The source now contains the existing SAPI/pyttsx3, Piper and Edge adapters,
playback sessions/events, stop/pause/resume orchestration and Tkinter view.
Controller and view files are included together because the original controller
imports the view and the unchanged playback tests exercise both. `app.main` is
also required by Piper's existing subprocess-render route.

The original runtime dependencies are available as an optional extra. Installing
this extra or launching the GUI was **not** part of this release's validation:

```sh
python -m pip install -e ".[speech]"
python -m app.main
```

The desktop path targets Windows with Tkinter and a working speech backend.
Piper additionally needs appropriately licensed `.onnx`/`.onnx.json` model pairs;
no models, audio samples or third-party binaries are bundled.

**Network behavior:** Edge synthesis sends input text to an external service.
The existing controller can also fall back from a failed Piper request to Edge
when available, so selecting Piper in the GUI does not guarantee offline use.
The JSON planning command `python -m app` does not invoke these speech routes.
See [speech scope and validation](docs/SPEECH.md) before using real playback.

## Behaviors covered

- English reading/spelling order and configurable spelling chunks.
- Special-word overrides and custom letter/symbol readings.
- Digit-by-digit or whole-number Chinese readings, with a leading-zero fallback.
- Punctuation, contextual numeric minus signs, whitespace, and newline pauses.
- Source spans and explicit pause instructions for downstream playback.
- JSON rule round trips, field normalization, and letter-pause control limits.
- Playback sessions, events, cancellation, routing and controller/UI state using
  fake drivers, synthesizers, players and widgets.

The parser treats audio paths as metadata. The optional playback adapters can
open audio/model files; their behavior is described separately in the speech docs.

## Test

Create an isolated environment, activate it using your platform's normal method,
and install the existing test dependency:

```sh
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest -q
python -m compileall -q app tests
```

The original tests retain their assertions. There are 148 included tests: 147
original tests covering parsing, rules, timing, fake playback/controller/UI
behavior, and one publication-specific CLI regression. The speech tests inject
fake drivers, synthesize stub data, and substitute players; they do not prove real
audio quality, model inference, external-service access or Windows operation.

The separate original `test_symbols.py` file remains unavailable in cloud storage.
It has not been recreated or skipped. Symbol cases are also covered in the
included `test_parser.py`. Missing source, platform and provider evidence remains
explicitly tracked in the roadmap.

## Layout and next steps

```text
app/models.py        Typed options, tokens, source spans and speech units
app/parser.py        Pure tokenization and speech-plan construction
app/symbol_map.py    Built-in Chinese symbol readings
app/__main__.py      JSON inspection command
app/settings.py      Serializable rules and JSON persistence
app/timing.py        Letter-pause control normalization and resolution
app/speech_engine.py Existing SAPI, Piper and Edge adapters and session/events
app/piper_worker.py  Local Piper render-job worker
app/controller.py    UI bindings, queue handling and speech routing
app/ui.py            Existing Tkinter view
app/main.py          GUI entry and Piper subprocess dispatch
tests/               Original available regression tests and CLI regression
docs/SPEECH.md       Backend boundaries, provenance and validation limits
docs/ROADMAP.md      Remaining publication milestones and validation limits
```

The source is being published for inspection as a project portfolio. No separate
open-source license has been selected for original project code. Third-party
runtime packages and separately obtained voice models retain their own license
terms. No such models or binaries are redistributed here.
