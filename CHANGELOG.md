# Changelog

## 2026-11-26 — Windows build source and packaging checks

- Recovered the existing PowerShell builder from the original project's Git
  objects and published its batch entry, PyInstaller spec and Piper smoke scripts.
- Preserved three additional original packaging tests; 151 included tests pass.
- Normalized the recovered builder to CRLF and selected the existing speech,
  build and test dependency groups for this extraction's optional-dependency layout.
- Retained script bytes in source archives and excluded local voice/audio assets.
- Documented missing model prerequisites, the unrecovered current launcher, the
  original missing-executable exit-code limitation and unperformed Windows checks.

## 2026-11-26 — Speech orchestration and application entry points

- Recovered and copied the existing `6.6` speech engine and Piper worker unchanged.
- Included the original main entry point, controller and Tkinter view required by
  the worker route and complete original playback/controller regression files.
- Preserved 88 additional original tests; 148 included tests now pass using fake
  speech backends, players and UI objects.
- Declared existing source-project speech dependencies as an optional extra.
- Documented automatic Piper-to-Edge fallback and its external text transmission,
  source-snapshot provenance, and the lack of real audio/Windows validation.
- Left voice models, third-party binaries and Windows packaging for separate review.

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
