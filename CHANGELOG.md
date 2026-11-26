# Changelog

## 2026-11-26 — Saved rules and pause controls

- Extracted existing JSON rule persistence and letter-pause helpers unchanged.
- Preserved 17 additional original regression tests; the included suite now has
  60 passing tests.
- Documented explicit saved-rule application, file write behavior, and an example
  that uses a temporary configuration file.
- Recorded the `6.4` settings / `6.6` core and timing source mix, the unavailable
  symbol tests, and the still-unverified desktop/audio behavior.

## 2026-11-25 — First public extraction

- Copied the existing parser, models, and symbol map without behavior changes.
- Preserved the available parser and number regression tests unchanged.
- Added a standalone package initializer, JSON inspection command, and scoped
  packaging/documentation without desktop or TTS runtime dependencies.
- Added a CLI regression test and converted set-valued options to JSON arrays.
- Recorded unrecovered source tests and Windows runtime verification as gaps.

This is a publication date, not the original application's creation date.
