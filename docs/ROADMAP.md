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
- [ ] Recover and publish Windows packaging scripts and their original tests.
      UI source was included with speech orchestration to keep that slice coherent.
      Preserve Windows script line endings; real Windows validation is pending.
- [ ] Complete integration checks, a reproducible demo, and documentation of all
      remaining platform limits.

Incomplete or unverifiable source is not a release. A blocked milestone may take
more than one day; publication dates are not a commitment to manufacture commits.
