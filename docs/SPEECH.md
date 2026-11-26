# Speech source and validation boundaries

The adapters orchestrate existing speech systems. No original speech model is
claimed, and no third-party models, libraries or binaries are copied into this
repository. The optional `speech` dependencies are the packages already declared
by the local source project; their package/model licenses remain applicable.

## Architecture and entry points

- `SpeechEngine` runs queued SAPI/pyttsx3 work on a background thread. Call
  `wait_until_finished` before treating a session as finished and `shutdown` when
  done. Session state and events represent progress, completion, stop and errors.
- `PiperSpeechEngine` discovers local `.onnx`/`.onnx.json` pairs, renders WAV data,
  and uses a player callback or platform playback. Its Windows default renderer
  may spawn `python -m app.main --piper-render <job.json>`.
- `MicrosoftEdgeSpeechEngine` uses the external Edge synthesis service and
  temporary audio files when actually invoked.
- The controller routes voices, queues UI events, persists reader rules and
  handles stop/pause/resume. It imports the Tkinter view, so both source files are
  included in this milestone. Main dispatches Piper jobs before importing Tkinter.
- `python -m app` remains the standalone JSON planning CLI. `python -m app.main`
  is the existing desktop entry, requiring Tkinter and a working speech setup.

## Network and file behavior

The real Edge path transmits the text being synthesized to an external service.
The existing controller can automatically fall back from Piper failure to Edge
when that backend is available. A selected Piper voice alone is not an offline
boundary. This fallback is preserved source behavior and is tested with fakes;
no live service request was made for publication.

Piper and Edge write temporary audio files; Piper can also stage eSpeak resources
and set `ESPEAK_DATA_PATH`. The Piper worker reads a local JSON job and writes its
specified output path. Such jobs are trusted local application input, not a
service interface for untrusted remote requests. The desktop controller can save
preferences using the paths documented in [RULES.md](RULES.md).

Default real playback is Windows-oriented. Some non-Windows adapter paths can
finish without audible output unless a player callback is supplied. A completed
fake session is not evidence of audible cross-platform playback.

## What was verified

All 148 included regression tests passed on the preparation machine. The 88
additional original tests cover speech sessions/events, chunk and pause handling,
voice routing, worker/subprocess behavior, cancellation, controller rules,
progress state and import-time initialization. Test drivers, model loaders,
synthesizers, players and GUI objects are substituted. The original Piper
subprocess test uses a local fake WAV generator.

Real Windows SAPI playback, real Piper model inference, live Edge requests,
interactive GUI operation and packaged Windows execution are **unverified**.
The tests do not establish voice quality, timing accuracy on physical devices,
remote availability or privacy behavior of a real service. No real provider was
called and no voice assets were redistributed during this publication.

## Source provenance

| Files | Existing local snapshot |
| --- | --- |
| `app/speech_engine.py`, `app/piper_worker.py`, `app/main.py` | `6.6` |
| `app/controller.py`, `app/ui.py` | `1111` |
| Playback, Piper and Edge regression files | `1111` |
| Voice-selection and UI-progress regression files | `6.6` |
| Controller-rule and import-smoke regression files | `New project 2` |
| Previously published settings implementation | `6.4` |

All copied source/test bytes were retained, with per-file hashes in the local
publication evidence. The suite checks this assembled source; it is not proof
that unavailable copies of every file in the snapshots are identical. The
original desktop package initializer remains replaced by the lightweight
publication initializer. The original symbol test file and the exact `6.6`
settings comparison remain recovery gaps. Windows packaging is a later slice.
