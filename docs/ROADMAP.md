# Staged publication

These are publication and verification milestones for an existing local project.
They do not represent a recreated history of the original development work.

- [x] Standalone parser, data models, symbol map, available original regression
      tests, and JSON command-line inspection.
- [x] Publish standalone rule persistence and timing helpers with their original
      regression tests and explicit per-module source-snapshot provenance.
- [ ] Recover the remaining original symbol tests and compare the unreadable
      `6.6` settings module with the published `6.4` copy. These remain known
      source-recovery gaps; no test has been recreated, skipped, or declared passing.
- [x] Publish speech orchestration and adapters with the existing main/Piper worker
      entry points and controller/UI needed by their unchanged regression tests.
      Fake-backend checks are explicitly separate from real audio/provider evidence.
- [x] Recover and publish Windows packaging scripts and their original tests.
      UI source was included with speech orchestration to keep that slice coherent.
      CRLF is retained; real Windows validation is pending. The build script was
      recovered from original Git objects, with dependency-selection adaptation
      documented in `WINDOWS_BUILD.md`.
- [ ] Recover the current `run_windows.bat` launcher. It is not required by the
      build pipeline; `python -m app.main` remains the documented source entry.
- [x] Complete the planned core integration check, a reproducible JSON demo, and
      documentation of remaining platform limits. A fresh installed wheel was
      checked outside the source tree; the included suite was exercised on two
      Python versions on macOS. See `VALIDATION.md` for the exact evidence boundary.

The planned source-publication sequence is complete. The unchecked recovery
items above and real Windows/provider/GUI validation remain explicit limitations,
not new scheduled publication batches or claims of a complete desktop release.

Incomplete or unverifiable source is not a release. A blocked milestone may take
more than one day; publication dates are not a commitment to manufacture commits.
