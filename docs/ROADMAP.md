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
- [ ] Publish speech orchestration and adapters with an explicit distinction
      between fake-backend tests and real audio/provider evidence.
- [ ] Publish the desktop UI and Windows packaging sources after recovery and
      review. Preserve Windows script line endings; identify Windows runtime
      validation as pending until actually performed.
- [ ] Complete integration checks, a reproducible demo, and documentation of all
      remaining platform limits.

Incomplete or unverifiable source is not a release. A blocked milestone may take
more than one day; publication dates are not a commitment to manufacture commits.
