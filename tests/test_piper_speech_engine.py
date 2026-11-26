from __future__ import annotations

import io
import sys
import wave
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.models import SourceSpan, SpeakAction, SpeechPlan, SpeechUnit, VoiceRole
from app.models import NumberMode, ParseOptions, ReadingMode
from app.parser import build_speech_plan
import app.speech_engine as speech_engine_module
from app.speech_engine import (
    PiperSpeechEngine,
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
    source_text: str | None = None,
    pause_ms: int = 0,
    voice_role: VoiceRole = VoiceRole.ENGLISH,
) -> SpeechUnit:
    return SpeechUnit(
        index=index,
        source_text=speak_text if source_text is None else source_text,
        span=SourceSpan(index, index + len(speak_text)),
        action=action,
        voice_role=voice_role,
        speak_text=speak_text,
        pause_ms=pause_ms,
    )


def _make_plan(*units: SpeechUnit) -> SpeechPlan:
    return SpeechPlan(source_text="", options=None, tokens=[], units=list(units))


def _write_tiny_wav(file_obj, marker: int) -> None:
    if hasattr(file_obj, "setframerate"):
        file_obj.setnchannels(1)
        file_obj.setsampwidth(2)
        file_obj.setframerate(1000)
        file_obj.writeframes(bytes([marker, 0]) * 10)
        return

    with wave.open(file_obj, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(1000)
        wav_file.writeframes(bytes([marker, 0]) * 10)


def _write_tiny_wav_path(path: Path, marker: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(1000)
        wav_file.writeframes(bytes([marker, 0]) * 10)


def _sample_runs(frames: bytes) -> list[tuple[bool, int]]:
    runs: list[tuple[bool, int]] = []
    current_is_silence: bool | None = None
    current_count = 0
    for index in range(0, len(frames), 2):
        is_silence = frames[index : index + 2] == b"\x00\x00"
        if current_is_silence is None:
            current_is_silence = is_silence
            current_count = 1
            continue
        if is_silence == current_is_silence:
            current_count += 1
            continue
        runs.append((current_is_silence, current_count))
        current_is_silence = is_silence
        current_count = 1
    if current_is_silence is not None:
        runs.append((current_is_silence, current_count))
    return runs


class FakePiperVoice:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize_wav(self, text, wav_file, syn_config=None):
        self.texts.append(text)
        marker = (sum(text.encode("utf-8")) % 250) + 1
        _write_tiny_wav(wav_file, marker)


def _add_model_pair(model_dir: Path, basename: str, metadata: str = "{}") -> None:
    (model_dir / f"{basename}.onnx").write_bytes(b"fake")
    (model_dir / f"{basename}.onnx.json").write_text(metadata, encoding="utf-8")


def _make_model_dir(tmp_path: Path) -> Path:
    model_dir = tmp_path / "voices"
    model_dir.mkdir()
    _add_model_pair(model_dir, "en_US-lessac-medium")
    return model_dir


def test_piper_engine_lists_bundled_english_voice(tmp_path):
    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=lambda path, stop_event: None,
    )

    assert engine.list_voices()[0].id == "piper:en_US-lessac-medium"
    assert engine.list_voices()[0].languages == ("en_US",)


def test_piper_engine_discovers_every_bundled_voice_pair(tmp_path):
    model_dir = _make_model_dir(tmp_path)
    _add_model_pair(model_dir, "en_US-amy-medium")
    _add_model_pair(model_dir, "en_GB-alba-medium")
    engine = PiperSpeechEngine(
        model_dir=model_dir,
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=lambda path, stop_event: None,
    )

    assert [voice.id for voice in engine.list_voices()] == [
        "piper:en_GB-alba-medium",
        "piper:en_US-amy-medium",
        "piper:en_US-lessac-medium",
    ]


def test_piper_engine_constructor_does_not_import_piper_until_synthesis(tmp_path, monkeypatch):
    model_dir = _make_model_dir(tmp_path)
    imported: list[str] = []
    real_import = speech_engine_module.importlib.import_module

    def record_import(module_name):
        imported.append(module_name)
        if module_name.startswith("piper"):
            raise AssertionError("Piper should be imported lazily during synthesis.")
        return real_import(module_name)

    monkeypatch.setattr(speech_engine_module.importlib, "import_module", record_import)

    engine = PiperSpeechEngine(model_dir=model_dir, wav_player=lambda path, stop_event: None)

    assert engine.list_voices()
    assert not any(module_name.startswith("piper") for module_name in imported)


def test_piper_engine_requires_model_files(tmp_path):
    with pytest.raises(RuntimeError, match="Piper model"):
        PiperSpeechEngine(model_dir=tmp_path)


def test_piper_engine_synthesizes_units_and_pause_into_one_wav(tmp_path):
    fake_voice = FakePiperVoice()
    played_paths: list[Path] = []
    events: list[tuple[object, int | None]] = []

    def record_playback(path, stop_event):
        played_paths.append(Path(path))
        with wave.open(str(path), "rb") as wav_file:
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
            assert wav_file.getframerate() == 1000
            frames = wav_file.readframes(wav_file.getnframes())
        hello_marker = (sum(b"hello") % 250) + 1
        letter_marker = (sum(b"aitch") % 250) + 1
        assert frames[:20] == bytes([hello_marker, 0]) * 10
        assert frames[20:120] == b"\x00" * 100
        assert frames[120:140] == bytes([letter_marker, 0]) * 10
        events.append(("wav_played", None))

    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: fake_voice,
        wav_player=record_playback,
    )
    plan = _make_plan(
        _make_unit(0, SpeakAction.READ_WORD, "hello"),
        _make_unit(1, SpeakAction.PAUSE, "", pause_ms=50, voice_role=VoiceRole.NONE),
        _make_unit(2, SpeakAction.SPELL_LETTER, "H E L L O"),
    )

    session = engine.play(
        plan,
        PlaybackSettings(),
        on_event=lambda event: events.append((event.event_type, event.unit_index)),
    )

    assert session.state == PlaybackState.COMPLETED
    assert fake_voice.texts == ["hello", "aitch", "ee", "ell", "ell", "oh"]
    assert len(played_paths) == 1
    assert events == [
        (PlaybackEventType.STARTED, None),
        (PlaybackEventType.UNIT_STARTED, 0),
        (PlaybackEventType.UNIT_STARTED, 1),
        (PlaybackEventType.UNIT_STARTED, 2),
        ("wav_played", None),
        (PlaybackEventType.UNIT_FINISHED, 0),
        (PlaybackEventType.UNIT_FINISHED, 1),
        (PlaybackEventType.UNIT_FINISHED, 2),
        (PlaybackEventType.COMPLETED, None),
    ]


def test_piper_engine_preserves_parser_interval_settings_in_final_wav(tmp_path):
    played_runs: list[tuple[bool, int]] = []

    def record_playback(path, stop_event):
        with wave.open(str(path), "rb") as wav_file:
            assert wav_file.getframerate() == 1000
            frames = wav_file.readframes(wav_file.getnframes())
        played_runs.extend(_sample_runs(frames))

    plan = build_speech_plan(
        "hello go",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=250,
            letter_pause_ms=15,
            spell_chunk_size=3,
            spell_chunk_pause_ms=400,
        ),
    )
    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=record_playback,
    )

    session = engine.play(plan, PlaybackSettings())

    assert session.state == PlaybackState.COMPLETED
    assert played_runs == [
        (False, 10),
        (True, 15),
        (False, 10),
        (True, 15),
        (False, 10),
        (True, 400),
        (False, 10),
        (True, 15),
        (False, 10),
        (True, 250),
        (False, 10),
        (True, 15),
        (False, 10),
    ]


def test_piper_engine_emits_unit_finished_only_after_wav_playback(tmp_path):
    fake_voice = FakePiperVoice()
    sequence: list[object] = []

    def record_playback(path, stop_event):
        sequence.append("wav_played")

    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: fake_voice,
        wav_player=record_playback,
    )

    session = engine.play(
        _make_plan(
            _make_unit(0, SpeakAction.READ_WORD, "hello"),
            _make_unit(1, SpeakAction.READ_SYMBOL, "world"),
        ),
        PlaybackSettings(),
        on_event=lambda event: sequence.append((event.event_type, event.unit_index)),
    )

    assert session.state == PlaybackState.COMPLETED
    assert sequence == [
        (PlaybackEventType.STARTED, None),
        (PlaybackEventType.UNIT_STARTED, 0),
        (PlaybackEventType.UNIT_STARTED, 1),
        "wav_played",
        (PlaybackEventType.UNIT_FINISHED, 0),
        (PlaybackEventType.UNIT_FINISHED, 1),
        (PlaybackEventType.COMPLETED, None),
    ]


def test_piper_engine_uses_pronounceable_letter_names_for_spelling_units(tmp_path):
    fake_voice = FakePiperVoice()
    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: fake_voice,
        wav_player=lambda path, stop_event: None,
    )

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.SPELL_LETTER, "A B C")),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.COMPLETED
    assert fake_voice.texts == ["ay", "bee", "see"]


def test_piper_engine_keeps_custom_letter_reading_text_for_spelling_units(tmp_path):
    fake_voice = FakePiperVoice()
    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: fake_voice,
        wav_player=lambda path, stop_event: None,
    )

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.SPELL_LETTER, "puh A")),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.COMPLETED
    assert fake_voice.texts == ["puh", "ay"]


def test_piper_engine_mixes_custom_letter_audio_without_synthesizing_it(tmp_path):
    fake_voice = FakePiperVoice()
    custom_audio = tmp_path / "p.wav"
    _write_tiny_wav_path(custom_audio, 77)

    def record_playback(path, stop_event):
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
        a_marker = (sum(b"ay") % 250) + 1
        assert frames[:20] == bytes([a_marker, 0]) * 10
        assert frames[20:40] == bytes([77, 0]) * 10

    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: fake_voice,
        wav_player=record_playback,
    )
    audio_unit = _make_unit(1, SpeakAction.SPELL_LETTER, "P")
    audio_unit = SpeechUnit(
        index=audio_unit.index,
        source_text=audio_unit.source_text,
        span=audio_unit.span,
        action=audio_unit.action,
        voice_role=audio_unit.voice_role,
        speak_text=audio_unit.speak_text,
        pause_ms=audio_unit.pause_ms,
        audio_path=str(custom_audio),
    )

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.SPELL_LETTER, "A"), audio_unit),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.COMPLETED
    assert fake_voice.texts == ["ay"]


def test_piper_engine_uses_selected_english_voice_model(tmp_path):
    model_dir = _make_model_dir(tmp_path)
    _add_model_pair(model_dir, "en_GB-alba-medium")
    loaded_paths: list[Path] = []

    def load_voice(path: Path) -> FakePiperVoice:
        loaded_paths.append(path)
        return FakePiperVoice()

    engine = PiperSpeechEngine(
        model_dir=model_dir,
        voice_loader=load_voice,
        wav_player=lambda path, stop_event: None,
    )

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.READ_WORD, "hello")),
        PlaybackSettings(voices=VoiceSelection(english_voice_id="piper:en_GB-alba-medium")),
    )

    assert session.state == PlaybackState.COMPLETED
    assert loaded_paths == [model_dir / "en_GB-alba-medium.onnx"]


def test_piper_subprocess_job_uses_english_safe_text_for_chinese_role_units(tmp_path):
    model_dir = _make_model_dir(tmp_path)
    engine = PiperSpeechEngine(
        model_dir=model_dir,
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=lambda path, stop_event: None,
        render_in_subprocess=True,
    )
    settings = PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id="piper:en_US-lessac-medium",
            chinese_voice_id="piper:en_US-lessac-medium",
        )
    )
    plan = _make_plan(
        _make_unit(
            0,
            SpeakAction.READ_NUMBER,
            "一二三",
            source_text="123",
            voice_role=VoiceRole.CHINESE,
        ),
        _make_unit(
            1,
            SpeakAction.READ_SYMBOL,
            "连字符",
            source_text="-",
            voice_role=VoiceRole.CHINESE,
        ),
        _make_unit(
            2,
            SpeakAction.READ_SYMBOL,
            "空格",
            source_text=" ",
            voice_role=VoiceRole.CHINESE,
        ),
    )

    job = engine._subprocess_render_job(
        SimpleNamespace(plan=plan, settings=settings, units=plan.units),
        tmp_path / "out.wav",
    )

    assert [payload["speak_text"] for payload in job["units"]] == ["1 2 3", "hyphen", "space"]


def test_piper_engine_keeps_chinese_text_with_chinese_model(tmp_path):
    model_dir = _make_model_dir(tmp_path)
    _add_model_pair(
        model_dir,
        "zh_CN-huayan-medium",
        '{"language": {"code": "zh_CN"}, "name": "Chinese Huayan"}',
    )
    engine = PiperSpeechEngine(
        model_dir=model_dir,
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=lambda path, stop_event: None,
    )
    settings = PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id="piper:en_US-lessac-medium",
            chinese_voice_id="piper:zh_CN-huayan-medium",
        )
    )
    unit = _make_unit(
        0,
        SpeakAction.READ_SYMBOL,
        "空格",
        source_text=" ",
        voice_role=VoiceRole.CHINESE,
    )

    assert engine._piper_speak_text(settings, unit) == "空格"


def test_piper_engine_synthesizes_english_safe_text_for_chinese_role_units(tmp_path):
    fake_voice = FakePiperVoice()
    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: fake_voice,
        wav_player=lambda path, stop_event: None,
    )
    settings = PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id="piper:en_US-lessac-medium",
            chinese_voice_id="piper:en_US-lessac-medium",
        )
    )

    session = engine.play(
        _make_plan(
            _make_unit(
                0,
                SpeakAction.READ_NUMBER,
                "一二三",
                source_text="123",
                voice_role=VoiceRole.CHINESE,
            ),
            _make_unit(
                1,
                SpeakAction.READ_SYMBOL,
                "连字符",
                source_text="-",
                voice_role=VoiceRole.CHINESE,
            ),
            _make_unit(
                2,
                SpeakAction.READ_SYMBOL,
                "空格",
                source_text=" ",
                voice_role=VoiceRole.CHINESE,
            ),
        ),
        settings,
    )

    assert session.state == PlaybackState.COMPLETED
    assert fake_voice.texts == ["1", "2", "3", "hyphen", "space"]


def test_piper_engine_preserves_custom_symbol_reading_with_english_model(tmp_path):
    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=lambda path, stop_event: None,
    )
    settings = PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id="piper:en_US-lessac-medium",
            chinese_voice_id="piper:en_US-lessac-medium",
        )
    )
    unit = _make_unit(
        0,
        SpeakAction.READ_SYMBOL,
        "和符号",
        source_text="&",
        voice_role=VoiceRole.CHINESE,
    )

    assert engine._piper_speak_text(settings, unit) == "和符号"


def test_piper_engine_limits_onnx_cpu_threads_by_default(tmp_path, monkeypatch):
    model_dir = _make_model_dir(tmp_path)
    model_path = model_dir / "en_US-lessac-medium.onnx"
    captured: dict[str, object] = {}

    class FakeSessionOptions:
        def __init__(self):
            self.intra_op_num_threads = None
            self.inter_op_num_threads = None
            self.execution_mode = None
            self.entries: dict[str, str] = {}

        def add_session_config_entry(self, key, value):
            self.entries[key] = value

    class FakeInferenceSession:
        def __init__(self, path, sess_options=None, providers=None):
            captured["path"] = path
            captured["sess_options"] = sess_options
            captured["providers"] = providers

    class FakePiperVoice:
        def __init__(self, **kwargs):
            captured["voice_kwargs"] = kwargs

    fake_ort = SimpleNamespace(
        SessionOptions=FakeSessionOptions,
        InferenceSession=FakeInferenceSession,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
    )
    fake_config = SimpleNamespace(
        PiperConfig=SimpleNamespace(from_dict=lambda payload: ("config", payload))
    )
    real_import = speech_engine_module.importlib.import_module

    def fake_import(module_name):
        if module_name == "onnxruntime":
            return fake_ort
        if module_name == "piper.config":
            return fake_config
        return real_import(module_name)

    monkeypatch.delenv(PiperSpeechEngine.THREADS_ENV_VAR, raising=False)
    monkeypatch.setattr(speech_engine_module.importlib, "import_module", fake_import)

    engine = PiperSpeechEngine(
        model_dir=model_dir,
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=lambda path, stop_event: None,
    )
    voice = engine._load_piper_voice_with_limited_cpu(
        FakePiperVoice,
        model_path,
        tmp_path,
    )

    session_options = captured["sess_options"]
    assert isinstance(voice, FakePiperVoice)
    assert captured["voice_kwargs"]["config"][0] == "config"
    assert captured["voice_kwargs"]["espeak_data_dir"] == tmp_path
    assert captured["path"] == str(model_path)
    assert captured["providers"] == ["CPUExecutionProvider"]
    assert session_options.intra_op_num_threads == 1
    assert session_options.inter_op_num_threads == 1
    assert session_options.execution_mode == "sequential"
    assert session_options.entries == {
        "session.intra_op.allow_spinning": "0",
        "session.inter_op.allow_spinning": "0",
    }


def test_piper_engine_accepts_bounded_cpu_thread_override(tmp_path, monkeypatch):
    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=lambda path, stop_event: None,
    )

    monkeypatch.setenv(PiperSpeechEngine.THREADS_ENV_VAR, "3")
    assert engine._piper_cpu_threads() == 3

    monkeypatch.setenv(PiperSpeechEngine.THREADS_ENV_VAR, "99")
    assert engine._piper_cpu_threads() == 4

    monkeypatch.setenv(PiperSpeechEngine.THREADS_ENV_VAR, "bad")
    assert engine._piper_cpu_threads() == 1


def test_piper_engine_passes_bundled_espeak_data_dir_to_voice_loader(tmp_path, monkeypatch):
    model_dir = _make_model_dir(tmp_path)
    espeak_data_dir = tmp_path / "bundle" / "piper" / "espeak-ng-data"
    espeak_data_dir.mkdir(parents=True)
    (espeak_data_dir / "phondata").write_bytes(b"fake")
    loaded_kwargs: list[dict[str, object]] = []

    class FakePiperVoiceClass:
        @staticmethod
        def load(model_path, **kwargs):
            loaded_kwargs.append(kwargs)
            return FakePiperVoice()

    monkeypatch.setattr(
        speech_engine_module.sys,
        "_MEIPASS",
        str(tmp_path / "bundle"),
        raising=False,
    )
    engine = PiperSpeechEngine(
        model_dir=model_dir,
        wav_player=lambda path, stop_event: None,
    )
    engine._piper_voice_class = FakePiperVoiceClass

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.READ_WORD, "hello")),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.COMPLETED
    assert loaded_kwargs[0]["espeak_data_dir"] == espeak_data_dir


def test_piper_engine_stages_non_ascii_espeak_data_dir_before_loading(tmp_path, monkeypatch):
    model_dir = _make_model_dir(tmp_path)
    bundle_dir = tmp_path / "新建文件夹"
    espeak_data_dir = bundle_dir / "piper" / "espeak-ng-data"
    espeak_data_dir.mkdir(parents=True)
    (espeak_data_dir / "phondata").write_bytes(b"fake")
    staged_root = tmp_path / "ascii-cache"
    staged_root.mkdir()
    loaded_kwargs: list[dict[str, object]] = []

    class FakePiperVoiceClass:
        @staticmethod
        def load(model_path, **kwargs):
            loaded_kwargs.append(kwargs)
            return FakePiperVoice()

    monkeypatch.setattr(
        speech_engine_module.sys,
        "_MEIPASS",
        str(bundle_dir),
        raising=False,
    )
    monkeypatch.setattr(
        speech_engine_module.tempfile,
        "gettempdir",
        lambda: str(staged_root),
    )
    engine = PiperSpeechEngine(
        model_dir=model_dir,
        wav_player=lambda path, stop_event: None,
    )
    engine._piper_voice_class = FakePiperVoiceClass

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.READ_WORD, "hello")),
        PlaybackSettings(),
    )

    staged_dir = loaded_kwargs[0]["espeak_data_dir"]
    assert session.state == PlaybackState.COMPLETED
    assert isinstance(staged_dir, Path)
    assert staged_dir != espeak_data_dir
    assert (staged_dir / "phondata").exists()
    str(staged_dir).encode("ascii")


def test_piper_engine_can_render_wav_in_subprocess(tmp_path):
    model_dir = _make_model_dir(tmp_path)
    worker = tmp_path / "render_worker.py"
    worker.write_text(
        """
import json
import wave
from pathlib import Path

job = json.loads(Path(__import__('sys').argv[1]).read_text(encoding='utf-8'))
with wave.open(str(job['output_path']), 'wb') as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(1000)
    wav_file.writeframes(bytes([42, 0]) * 10)
""".strip(),
        encoding="utf-8",
    )
    played_frames: list[bytes] = []
    engine = PiperSpeechEngine(
        model_dir=model_dir,
        render_in_subprocess=True,
        wav_player=lambda path, stop_event: played_frames.append(Path(path).read_bytes()),
    )
    engine._piper_render_command = lambda job_path: [sys.executable, str(worker), str(job_path)]

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.READ_WORD, "hello")),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.COMPLETED
    assert played_frames


def test_piper_engine_stop_before_play_marks_session_stopped(tmp_path):
    played = False

    def record_playback(path, stop_event):
        nonlocal played
        played = True

    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: FakePiperVoice(),
        wav_player=record_playback,
    )
    engine.stop()

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.READ_WORD, "hello")),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.STOPPED
    assert played is False


def test_piper_engine_stop_checks_between_phrase_chunks_before_playback(tmp_path):
    played = False
    engine_holder: dict[str, PiperSpeechEngine] = {}

    class StoppingVoice(FakePiperVoice):
        def synthesize_wav(self, text, wav_file, syn_config=None):
            super().synthesize_wav(text, wav_file, syn_config=syn_config)
            if text == "alpha":
                engine_holder["engine"].stop()

    def record_playback(path, stop_event):
        nonlocal played
        played = True

    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: StoppingVoice(),
        wav_player=record_playback,
    )
    engine_holder["engine"] = engine

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.READ_SYMBOL, "alpha beta gamma")),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.STOPPED
    assert played is False


def test_piper_engine_stop_between_spelled_letters_prevents_playback(tmp_path):
    played = False
    engine_holder: dict[str, PiperSpeechEngine] = {}

    class StoppingVoice(FakePiperVoice):
        def synthesize_wav(self, text, wav_file, syn_config=None):
            super().synthesize_wav(text, wav_file, syn_config=syn_config)
            if text == "ay":
                engine_holder["engine"].stop()

    def record_playback(path, stop_event):
        nonlocal played
        played = True

    engine = PiperSpeechEngine(
        model_dir=_make_model_dir(tmp_path),
        voice_loader=lambda path: StoppingVoice(),
        wav_player=record_playback,
    )
    engine_holder["engine"] = engine

    session = engine.play(
        _make_plan(_make_unit(0, SpeakAction.SPELL_LETTER, "A B")),
        PlaybackSettings(),
    )

    assert session.state == PlaybackState.STOPPED
    assert played is False
