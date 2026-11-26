# English Spell Reader — Speech Planning and Saved Rules

A deterministic Python parser that turns English words, numbers, punctuation,
and whitespace into explicit speech and pause instructions. It separates text
interpretation from the speech backend so the plan can be inspected and tested
without playing audio.

## Current publication

This is a **staged public extraction of an existing local Windows spelling-reader
project**. Publication began on 2026-11-25; commit dates record preparation and
publication here, not the original application's development timeline. AI tools
assist with extraction, documentation, and verification.

The current extraction includes the original parser, data models, symbol map,
rule persistence, pause-timing helpers, and their available original tests,
unchanged. A lightweight package initializer and JSON command-line example are
publication conveniences. The original desktop initializer is not used here.

The settings module was recovered from the local `6.4` snapshot; the parser,
timing helpers and included original tests come from `6.6`. The settings tests
in those two snapshots are byte-identical, and all 60 included tests pass
against this assembled core. The unreadable `6.6` settings copy has not been
compared, so this is not claimed to be a complete, identical `6.6` release.

Desktop UI, audio playback, voice models, and Windows packaging are outside the
current extraction. This is a rule-based text-processing component, not a
trained language model, speech synthesizer, or complete desktop release.

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

## Behaviors covered

- English reading/spelling order and configurable spelling chunks.
- Special-word overrides and custom letter/symbol readings.
- Digit-by-digit or whole-number Chinese readings, with a leading-zero fallback.
- Punctuation, contextual numeric minus signs, whitespace, and newline pauses.
- Source spans and explicit pause instructions for downstream playback.
- JSON rule round trips, field normalization, and letter-pause control limits.

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

The original tests retain their assertions. There are 60 included tests: 42
original parser/number tests, 17 original settings/timing tests, and one
publication-specific CLI regression test. The source project's
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
app/settings.py      Serializable rules and JSON persistence
app/timing.py        Letter-pause control normalization and resolution
tests/               Original available core/rules/timing tests and CLI regression
docs/ROADMAP.md      Remaining publication milestones and validation limits
```

The source is being published for inspection as a project portfolio. No separate
open-source license has been selected for original project code. Third-party
packages, when used in later slices, retain their own license terms.
