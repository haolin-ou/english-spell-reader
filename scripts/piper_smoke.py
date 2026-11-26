from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.models import (
    NumberMode,
    ParseOptions,
    ReadingMode,
    SourceSpan,
    SpeakAction,
    SpeechPlan,
    SpeechUnit,
    VoiceRole,
)
from app.speech_engine import PlaybackSettings, PlaybackState, PiperSpeechEngine


def main() -> int:
    played_frames: list[tuple[int, int, int, int]] = []

    def record_wav(path, stop_event) -> None:
        import wave

        with wave.open(str(path), "rb") as wav_file:
            played_frames.append(
                (
                    wav_file.getnchannels(),
                    wav_file.getsampwidth(),
                    wav_file.getframerate(),
                    wav_file.getnframes(),
                )
            )

    unit = SpeechUnit(
        index=0,
        source_text="hello",
        span=SourceSpan(0, 5),
        action=SpeakAction.READ_WORD,
        voice_role=VoiceRole.ENGLISH,
        speak_text="hello",
        pause_ms=0,
    )
    plan = SpeechPlan(
        source_text="hello",
        options=ParseOptions(ReadingMode.READ_ONLY, NumberMode.DIGIT_BY_DIGIT),
        tokens=[],
        units=[unit],
    )

    engine = PiperSpeechEngine(wav_player=record_wav)
    voices = engine.list_voices()
    if not voices:
        raise RuntimeError("Piper smoke test found no bundled voices.")

    session = engine.play(plan, PlaybackSettings())
    if session.state != PlaybackState.COMPLETED:
        raise RuntimeError(
            "Piper smoke test failed: "
            + (session.error_message or str(session.state))
        )
    if not played_frames or played_frames[0][3] <= 0:
        raise RuntimeError("Piper smoke test produced an empty WAV.")

    print("Piper smoke test passed.")
    print("Voices: " + ", ".join(voice.id for voice in voices))
    print(
        "WAV: channels={0} width={1} rate={2} frames={3}".format(
            *played_frames[0]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
