from __future__ import annotations

import sys
import types

from app.models import SourceSpan, SpeakAction, SpeechPlan, SpeechUnit, VoiceRole
from app.speech_engine import (
    MicrosoftEdgeSpeechEngine,
    PlaybackEventType,
    PlaybackSettings,
    PlaybackState,
    VoiceSelection,
)


def _make_unit(
    index: int,
    action: SpeakAction,
    speak_text: str,
    *,
    pause_ms: int = 0,
    voice_role: VoiceRole = VoiceRole.ENGLISH,
) -> SpeechUnit:
    return SpeechUnit(
        index=index,
        source_text=speak_text,
        span=SourceSpan(index, index + len(speak_text)),
        action=action,
        voice_role=voice_role,
        speak_text=speak_text,
        pause_ms=pause_ms,
    )


def _make_plan(*units: SpeechUnit) -> SpeechPlan:
    return SpeechPlan(source_text="", options=None, tokens=[], units=list(units))


def test_microsoft_edge_engine_lists_ranked_clear_voices() -> None:
    voices = MicrosoftEdgeSpeechEngine().list_voices()

    assert [voice.id for voice in voices] == [
        "edge:en-US-RogerNeural",
    ]
    assert voices[0].name == "Microsoft Clear Roger"
    assert voices[0].languages == ("en-US",)


def test_microsoft_edge_engine_renders_selected_voice_and_emits_events(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, object]] = []

    class FakeCommunicate:
        def __init__(self, text, voice, *, rate="+0%", volume="+0%", pitch="+0Hz", **kwargs):
            calls.append(("communicate", (text, voice, rate, volume, pitch)))
            self.text = text

        async def save(self, audio_fname, metadata_fname=None):
            calls.append(("save", audio_fname))
            with open(audio_fname, "wb") as audio_file:
                audio_file.write(b"fake mp3")

    fake_edge_tts = types.SimpleNamespace(Communicate=FakeCommunicate)
    monkeypatch.setitem(sys.modules, "edge_tts", fake_edge_tts)

    played_paths: list[str] = []
    slept: list[float] = []
    engine = MicrosoftEdgeSpeechEngine(
        temp_dir=tmp_path,
        audio_player=lambda path, stop_event: played_paths.append(str(path)),
    )
    engine._sleep_pause = lambda seconds, stop_event: slept.append(seconds)
    events: list[tuple[PlaybackEventType, int | None]] = []

    session = engine.play(
        _make_plan(
            _make_unit(0, SpeakAction.READ_WORD, "hello"),
            _make_unit(1, SpeakAction.PAUSE, "", pause_ms=250, voice_role=VoiceRole.NONE),
            _make_unit(2, SpeakAction.SPELL_LETTER, "A B"),
        ),
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="edge:en-US-RogerNeural"),
            rate=160,
            volume=0.75,
        ),
        on_event=lambda event: events.append((event.event_type, event.unit_index)),
    )

    assert session.state == PlaybackState.COMPLETED
    assert [call[0] for call in calls] == [
        "communicate",
        "save",
        "communicate",
        "save",
        "communicate",
        "save",
    ]
    assert calls[0][1] == ("hello", "en-US-RogerNeural", "-20%", "-25%", "+0Hz")
    assert calls[2][1] == ("ay", "en-US-RogerNeural", "-20%", "-25%", "+0Hz")
    assert calls[4][1] == ("bee", "en-US-RogerNeural", "-20%", "-25%", "+0Hz")
    assert len(played_paths) == 3
    assert slept == [0.25]
    assert events == [
        (PlaybackEventType.STARTED, None),
        (PlaybackEventType.UNIT_STARTED, 0),
        (PlaybackEventType.UNIT_FINISHED, 0),
        (PlaybackEventType.UNIT_STARTED, 1),
        (PlaybackEventType.UNIT_FINISHED, 1),
        (PlaybackEventType.UNIT_STARTED, 2),
        (PlaybackEventType.UNIT_FINISHED, 2),
        (PlaybackEventType.COMPLETED, None),
    ]


def test_microsoft_edge_engine_spells_letters_as_separate_roger_chunks(monkeypatch, tmp_path) -> None:
    captured_texts: list[str] = []

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            captured_texts.append(text)

        async def save(self, audio_fname, metadata_fname=None):
            with open(audio_fname, "wb") as audio_file:
                audio_file.write(b"fake mp3")

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))

    engine = MicrosoftEdgeSpeechEngine(
        temp_dir=tmp_path,
        audio_player=lambda path, stop_event: None,
    )
    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.SPELL_LETTER, "A B C")),
        PlaybackSettings(voices=VoiceSelection(english_voice_id="edge:en-US-RogerNeural")),
    )

    assert session.state == PlaybackState.COMPLETED
    assert captured_texts == ["ay", "bee", "see"]


def test_microsoft_edge_engine_keeps_custom_letter_readings_in_spelling_chunks(
    monkeypatch,
    tmp_path,
) -> None:
    captured_texts: list[str] = []

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            captured_texts.append(text)

        async def save(self, audio_fname, metadata_fname=None):
            with open(audio_fname, "wb") as audio_file:
                audio_file.write(b"fake mp3")

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))

    engine = MicrosoftEdgeSpeechEngine(
        temp_dir=tmp_path,
        audio_player=lambda path, stop_event: None,
    )
    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.SPELL_LETTER, "puh A")),
        PlaybackSettings(voices=VoiceSelection(english_voice_id="edge:en-US-RogerNeural")),
    )

    assert session.state == PlaybackState.COMPLETED
    assert captured_texts == ["puh", "ay"]


def test_microsoft_edge_engine_converts_chinese_number_and_symbol_to_english(monkeypatch, tmp_path) -> None:
    captured_texts: list[str] = []

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            captured_texts.append(text)

        async def save(self, audio_fname, metadata_fname=None):
            with open(audio_fname, "wb") as audio_file:
                audio_file.write(b"fake mp3")

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))

    engine = MicrosoftEdgeSpeechEngine(
        temp_dir=tmp_path,
        audio_player=lambda path, stop_event: None,
    )
    session = engine.play(
        _make_plan(
            SpeechUnit(
                index=0,
                source_text="123",
                span=SourceSpan(0, 3),
                action=SpeakAction.READ_NUMBER,
                voice_role=VoiceRole.CHINESE,
                speak_text="一二三",
                pause_ms=0,
            ),
            SpeechUnit(
                index=1,
                source_text="-",
                span=SourceSpan(3, 4),
                action=SpeakAction.READ_SYMBOL,
                voice_role=VoiceRole.CHINESE,
                speak_text="连字符",
                pause_ms=0,
            ),
        ),
        PlaybackSettings(voices=VoiceSelection(english_voice_id="edge:en-US-AvaMultilingualNeural")),
    )

    assert session.state == PlaybackState.COMPLETED
    assert captured_texts == ["1 2 3", "hyphen"]


def test_microsoft_edge_engine_preserves_custom_symbol_reading_for_roger() -> None:
    engine = MicrosoftEdgeSpeechEngine()
    settings = PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id="edge:en-US-RogerNeural",
            chinese_voice_id="edge:en-US-RogerNeural",
        )
    )
    unit = SpeechUnit(
        index=0,
        source_text="&",
        span=SourceSpan(0, 1),
        action=SpeakAction.READ_SYMBOL,
        voice_role=VoiceRole.CHINESE,
        speak_text="和符号",
        pause_ms=0,
    )

    assert engine._get_driver_speak_text(settings, unit) == "和符号"
