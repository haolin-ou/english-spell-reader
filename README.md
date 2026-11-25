# English Spell Reader — Speech-Planning Core

A deterministic Python parser that turns English words, numbers, punctuation,
and whitespace into explicit speech and pause instructions. It separates text
interpretation from the speech backend so the plan can be inspected and tested
without playing audio.

## Current publication

This is a **staged public extraction of an existing local Windows spelling-reader
project**. Publication began on 2026-11-25; commit dates record preparation and
publication here, not the original application's development timeline. AI tools
assist with extraction, documentation, and verification.

The first slice includes the original parser, data models, symbol map, and the
available original parser/number tests, unchanged. A lightweight package
initializer and JSON command-line example are new publication conveniences.
The original initializer is not used in this standalone core.

Desktop UI, audio playback, voice models, user settings, and Windows packaging
are outside this first slice. This is a rule-based text-processing component,
not a trained language model, speech synthesizer, or complete desktop release.

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

## Behaviors covered

- English reading/spelling order and configurable spelling chunks.
- Special-word overrides and custom letter/symbol readings.
- Digit-by-digit or whole-number Chinese readings, with a leading-zero fallback.
- Punctuation, contextual numeric minus signs, whitespace, and newline pauses.
- Source spans and explicit pause instructions for downstream playback.

Audio path options are metadata for a future backend; this core does not open or
validate audio files.

## Test

Create an isolated environment, activate it using your platform's normal method,
and install the existing test dependency:

```sh
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest -q
python -m compileall -q app tests
```

The original tests retain their assertions; one new regression test verifies
that the documented CLI returns a valid JSON speech plan. The source project's
separate `test_symbols.py` file has not yet been recovered from cloud storage and
is tracked as a publication gap, not a passing or skipped test. Symbol behaviors
are also covered by cases in the included `test_parser.py`. Windows playback and
packaging have not been validated in this publication.

## Layout and next steps

```text
app/models.py        Typed options, tokens, source spans and speech units
app/parser.py        Pure tokenization and speech-plan construction
app/symbol_map.py    Built-in Chinese symbol readings
app/__main__.py      JSON inspection command
tests/              Original available parser and number regression tests
docs/ROADMAP.md      Remaining publication milestones and validation limits
```

The source is being published for inspection as a project portfolio. No separate
open-source license has been selected for original project code. Third-party
packages, when used in later slices, retain their own license terms.
