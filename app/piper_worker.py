from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .models import (
    NumberMode,
    ParseOptions,
    ReadingMode,
    SourceSpan,
    SpeakAction,
    SpeechPlan,
    SpeechUnit,
    VoiceRole,
)
from .speech_engine import PlaybackSettings, PlaybackState, PiperSpeechEngine, VoiceSelection


def main(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if len(args) != 1:
        raise RuntimeError("Expected one Piper render job JSON path.")

    job_path = Path(args[0])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    output_path = Path(str(job["output_path"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    def copy_rendered_wav(path, stop_event) -> None:
        shutil.copyfile(path, output_path)

    engine = PiperSpeechEngine(
        model_dir=job.get("model_dir"),
        wav_player=copy_rendered_wav,
        render_in_subprocess=False,
    )
    session = engine.play(_speech_plan_from_job(job), _playback_settings_from_job(job))
    if session.state != PlaybackState.COMPLETED:
        raise RuntimeError(session.error_message or f"Piper render failed: {session.state}")
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError("Piper render produced an empty WAV.")
    return 0


def _speech_plan_from_job(job: dict[str, Any]) -> SpeechPlan:
    units = [_speech_unit_from_payload(payload) for payload in job.get("units", [])]
    return SpeechPlan(
        source_text=str(job.get("source_text", "")),
        options=ParseOptions(ReadingMode.READ_ONLY, NumberMode.DIGIT_BY_DIGIT),
        tokens=[],
        units=units,
    )


def _speech_unit_from_payload(payload: dict[str, Any]) -> SpeechUnit:
    span_payload = payload.get("span") or {}
    start = _int_or_default(span_payload.get("start"), 0)
    end = _int_or_default(span_payload.get("end"), start)
    return SpeechUnit(
        index=_int_or_default(payload.get("index"), 0),
        source_text=str(payload.get("source_text", "")),
        span=SourceSpan(start, end),
        action=_speak_action(payload.get("action")),
        voice_role=_voice_role(payload.get("voice_role")),
        speak_text=str(payload.get("speak_text", "")),
        pause_ms=_int_or_default(payload.get("pause_ms"), 0),
        audio_path=_optional_text(payload.get("audio_path")),
    )


def _playback_settings_from_job(job: dict[str, Any]) -> PlaybackSettings:
    return PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id=_optional_text(job.get("english_voice_id")),
            chinese_voice_id=_optional_text(job.get("chinese_voice_id")),
        ),
        rate=_int_or_default(job.get("rate"), 200),
        volume=_float_or_default(job.get("volume"), 1.0),
    )


def _speak_action(value: Any) -> SpeakAction:
    text = str(value or SpeakAction.READ_WORD.value).strip().lower()
    try:
        return SpeakAction(text)
    except ValueError:
        return getattr(SpeakAction, text.upper(), SpeakAction.READ_WORD)


def _voice_role(value: Any) -> VoiceRole:
    text = str(value or VoiceRole.ENGLISH.value).strip().lower()
    try:
        return VoiceRole(text)
    except ValueError:
        return getattr(VoiceRole, text.upper(), VoiceRole.ENGLISH)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
