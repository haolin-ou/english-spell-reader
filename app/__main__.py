"""Print a deterministic speech plan without starting a speech backend."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .models import NumberMode, ParseOptions, ReadingMode
from .parser import build_speech_plan


def _json_default(value: object) -> list:
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", help="Text to turn into speech instructions")
    args = parser.parse_args()
    options = ParseOptions(
        reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
        number_mode=NumberMode.DIGIT_BY_DIGIT,
    )
    plan = build_speech_plan(args.text, options)
    print(json.dumps(asdict(plan), ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
