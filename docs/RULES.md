# Rule persistence and timing

This module pair is extracted existing behavior. It does not start a GUI, select
an audio device, synthesize speech, or contact a service.

## Persistence

`ReaderRules` stores special words, symbol and letter pronunciation overrides,
letter-audio paths, pause and spelling-chunk controls, reading/number modes, rate,
volume and optional voice identifiers. `save_rules` normalizes these values and
writes sorted, indented UTF-8 JSON. `load_rules` returns defaults for a missing
file, malformed JSON or a non-object JSON value; the per-field sanitizers handle
supported input types and ranges. See the original tests for the covered cases.

The write creates parent directories and replaces the destination file. Pass an
explicit path when embedding the module. If omitted, `APPDATA` selects
`EnglishSpellReader/rules.json` beneath that directory; otherwise the fallback is
`~/.english_spell_reader_rules.json`. The path rule is inherited behavior, not a
claim that Windows playback or installation has been tested here.

Special words are normalized to lowercase ASCII words. Symbol override keys must
normalize to one character; letter override keys normalize to one uppercase ASCII
letter. The loader bounds rate to 80–260, volume to 0–100, spelling chunk size to
1–10, and chunk pause to 0–5000 milliseconds. Voice identifiers and audio paths
are stored strings; they are not evidence that a voice or audio file is usable.

## Letter pauses

The standard letter-pause control represents 0–100 milliseconds, with values
normalized to an integer within that range. An optional custom pause can select
up to 1000 milliseconds. `resolve_letter_pause_ms` uses a valid custom value in
preference to the standard control. This produces a planned delay, not a measured
real-time playback guarantee.

## Applying rules

The parser and JSON CLI do not read saved preferences implicitly. A caller loads
rules and supplies the intended fields to `ParseOptions`, converting the stored
reading and number mode strings to their enum values. The README demonstrates
special-word and pause settings. To apply the saved space rule, map
`ReaderRules.space_behavior` to `ParseOptions.whitespace_mode`. Rate, volume and
voice IDs are used by the optional audio integration and have no effect on the
pure speech-planning CLI.

## Source and validation limits

The published settings implementation came from the existing local `6.4` snapshot.
Timing helpers and the original settings/timing tests came from `6.6`; the original
settings test file is byte-identical in `6.4` and `6.6`. The assembled core passes
the available regression suite. This verifies the tested module interactions,
not byte identity with the unavailable `6.6` settings implementation.

The separate original symbol test file remains unavailable in cloud storage.
It has not been reconstructed or skipped. Real audio playback, interactive desktop behavior,
and Windows packaging remain outside this release's verification.

Existing input-handling limits are retained: infinite pause values can raise
`OverflowError`, and a non-UTF-8 rules file can raise `UnicodeDecodeError`. The
covered JSON/type fallbacks should not be read as a promise to accept every
malformed file or arbitrary Python value.
