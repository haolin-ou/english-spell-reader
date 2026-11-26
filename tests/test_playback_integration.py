from __future__ import annotations

import importlib
import queue
import sys
import threading
import time
import types

from app.models import SourceSpan, SpeakAction, SpeechPlan, SpeechUnit, VoiceRole
from app.speech_engine import PlaybackSession, PlaybackState, SpeechEngine
from app.speech_engine import PlaybackSettings, VoiceSelection


def _install_fake_tkinter(monkeypatch) -> None:
    fake_tkinter = types.ModuleType("tkinter")
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_messagebox = types.ModuleType("tkinter.messagebox")
    dummy_widget = type("DummyWidget", (), {})

    fake_tkinter.Tk = dummy_widget
    fake_tkinter.Text = dummy_widget
    fake_tkinter.StringVar = dummy_widget
    fake_tkinter.IntVar = dummy_widget
    fake_tkinter.DoubleVar = dummy_widget
    fake_tkinter.BOTH = "both"
    fake_tkinter.WORD = "word"
    fake_tkinter.VERTICAL = "vertical"
    fake_tkinter.HORIZONTAL = "horizontal"
    fake_tkinter.DISABLED = "disabled"
    fake_tkinter.NORMAL = "normal"
    fake_tkinter.SUNKEN = "sunken"
    fake_ttk.Frame = dummy_widget
    fake_ttk.LabelFrame = dummy_widget
    fake_ttk.Label = dummy_widget
    fake_ttk.Combobox = dummy_widget
    fake_ttk.Scale = dummy_widget
    fake_ttk.Button = dummy_widget
    fake_ttk.Scrollbar = dummy_widget
    fake_ttk.Progressbar = dummy_widget
    fake_messagebox.showerror = lambda *args, **kwargs: None
    fake_tkinter.ttk = fake_ttk
    fake_tkinter.messagebox = fake_messagebox

    for module_name in ("app.main", "app.controller", "app.ui", "app"):
        sys.modules.pop(module_name, None)

    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", fake_messagebox)


def _make_unit(
    index: int,
    source_text: str,
    action: SpeakAction,
    speak_text: str,
    *,
    pause_ms: int = 0,
    voice_role: VoiceRole = VoiceRole.ENGLISH,
) -> SpeechUnit:
    return SpeechUnit(
        index=index,
        source_text=source_text,
        span=SourceSpan(index, index + len(source_text)),
        action=action,
        voice_role=voice_role,
        speak_text=speak_text,
        pause_ms=pause_ms,
    )


def _make_plan(*units: SpeechUnit) -> SpeechPlan:
    return SpeechPlan(
        source_text="",
        options=None,
        tokens=[],
        units=list(units),
    )


def test_speech_engine_waits_until_session_finishes() -> None:
    engine = SpeechEngine.__new__(SpeechEngine)
    engine._condition = threading.Condition()
    session = PlaybackSession(total_units=2)

    def finish_later() -> None:
        time.sleep(0.05)
        engine._mark_session(session, PlaybackState.COMPLETED, finished=True)

    threading.Thread(target=finish_later, daemon=True).start()

    state = engine.wait_until_finished(session, timeout=1.0)

    assert state == PlaybackState.COMPLETED
    assert session.finished_at is not None


def test_speech_engine_spell_only_uses_one_spoken_utterance_and_one_run():
    class FakeDriver:
        def __init__(self) -> None:
            self.said: list[str] = []
            self.run_count = 0
            self.properties: list[tuple[str, object]] = []

        def say(self, text: str) -> None:
            self.said.append(text)

        def runAndWait(self) -> None:
            self.run_count += 1
            if self.run_count > 1:
                raise RuntimeError("SAPI driver was restarted for contiguous speech")

        def setProperty(self, name: str, value: object) -> None:
            self.properties.append((name, value))

        def stop(self) -> None:
            pass

    created_drivers: list[FakeDriver] = []
    engine = SpeechEngine()
    engine._init_driver = lambda: created_drivers.append(FakeDriver()) or created_drivers[-1]
    engine._validate_selected_voices = lambda settings: None

    plan = _make_plan(_make_unit(0, "hello", SpeakAction.SPELL_LETTER, "H E L L O"))
    session = engine.play(
        plan,
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="english", chinese_voice_id="chinese")
        ),
    )
    state = engine.wait_until_finished(session, timeout=1.0)
    engine.shutdown()

    assert state == PlaybackState.COMPLETED
    assert len(created_drivers) == 1
    assert created_drivers[0].said == ["H E L L O"]
    assert created_drivers[0].run_count == 1


def test_speech_engine_spell_then_read_word_uses_fresh_driver_per_segment():
    class FakeDriver:
        def __init__(self, name: str) -> None:
            self.name = name
            self.said: list[str] = []
            self.run_count = 0

        def say(self, text: str) -> None:
            self.said.append(text)

        def runAndWait(self) -> None:
            self.run_count += 1

        def setProperty(self, name: str, value: object) -> None:
            pass

        def stop(self) -> None:
            pass

    created_drivers: list[FakeDriver] = []
    engine = SpeechEngine()
    engine._init_driver = lambda: created_drivers.append(
        FakeDriver(f"driver-{len(created_drivers)}")
    ) or created_drivers[-1]
    engine._validate_selected_voices = lambda settings: None

    pause_durations: list[float] = []

    def record_pause(seconds: float, stop_event: threading.Event) -> None:
        pause_durations.append(seconds)

    engine._sleep_pause = record_pause

    plan = _make_plan(
        _make_unit(0, "hello", SpeakAction.SPELL_LETTER, "H E L L O"),
        _make_unit(1, " ", SpeakAction.PAUSE, "", pause_ms=500, voice_role=VoiceRole.NONE),
        _make_unit(2, "hello", SpeakAction.READ_WORD, "hello"),
    )
    session = engine.play(
        plan,
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="english", chinese_voice_id="chinese")
        ),
    )
    state = engine.wait_until_finished(session, timeout=1.0)
    engine.shutdown()

    assert state == PlaybackState.COMPLETED
    assert len(created_drivers) == 2
    assert created_drivers[0] is not created_drivers[1]
    assert created_drivers[0].said == ["H E L L O"]
    assert created_drivers[1].said == ["hello"]
    assert pause_durations == [0.5]
    assert [driver.run_count for driver in created_drivers] == [1, 1]


def test_speech_engine_keeps_inline_letter_pauses_in_one_driver_segment():
    class FakeDriver:
        def __init__(self) -> None:
            self.said: list[str] = []
            self.run_count = 0

        def say(self, text: str) -> None:
            self.said.append(text)

        def runAndWait(self) -> None:
            self.run_count += 1

        def setProperty(self, name: str, value: object) -> None:
            pass

        def stop(self) -> None:
            pass

    driver = FakeDriver()
    engine = SpeechEngine()
    engine._init_driver = lambda: driver
    engine._validate_selected_voices = lambda settings: None
    pause_durations: list[float] = []
    engine._sleep_pause = lambda seconds, stop_event: pause_durations.append(seconds)

    plan = _make_plan(
        _make_unit(0, "h", SpeakAction.SPELL_LETTER, "H"),
        _make_unit(1, "", SpeakAction.PAUSE, "", pause_ms=12, voice_role=VoiceRole.NONE),
        _make_unit(2, "e", SpeakAction.SPELL_LETTER, "E"),
    )
    session = engine.play(
        plan,
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="english", chinese_voice_id="chinese")
        ),
    )
    state = engine.wait_until_finished(session, timeout=1.0)
    engine.shutdown()

    assert state == PlaybackState.COMPLETED
    assert driver.said == ["H", "E"]
    assert driver.run_count == 1
    assert pause_durations == [0.012]


def test_speech_engine_uses_sapi_xml_for_inline_letter_pauses():
    class FakeSapiVoice:
        def __init__(self) -> None:
            self.spoken: list[tuple[str, int]] = []

        def Speak(self, text: str, flags: int) -> None:
            self.spoken.append((text, flags))

    class FakeSapiDriver:
        def __init__(self) -> None:
            self._tts = FakeSapiVoice()
            self.properties: list[tuple[str, object]] = []

        def setProperty(self, name: str, value: object) -> None:
            self.properties.append((name, value))

    class FakeDriver:
        def __init__(self) -> None:
            self.proxy = types.SimpleNamespace(_driver=FakeSapiDriver())
            self.said: list[str] = []
            self.run_count = 0

        def say(self, text: str) -> None:
            self.said.append(text)

        def runAndWait(self) -> None:
            self.run_count += 1

        def stop(self) -> None:
            pass

    driver = FakeDriver()
    engine = SpeechEngine()
    engine._init_driver = lambda: driver
    engine._validate_selected_voices = lambda settings: None

    plan = _make_plan(
        _make_unit(0, "h", SpeakAction.SPELL_LETTER, "H"),
        _make_unit(1, "", SpeakAction.PAUSE, "", pause_ms=12, voice_role=VoiceRole.NONE),
        _make_unit(2, "e", SpeakAction.SPELL_LETTER, "E"),
    )
    session = engine.play(
        plan,
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="english", chinese_voice_id="chinese")
        ),
    )
    state = engine.wait_until_finished(session, timeout=1.0)
    engine.shutdown()

    sapi_driver = driver.proxy._driver
    assert state == PlaybackState.COMPLETED
    assert driver.said == []
    assert driver.run_count == 0
    assert sapi_driver._tts.spoken == [('H<silence msec="12"/>E', 8)]
    assert ("voice", "english") in sapi_driver.properties


def test_speech_engine_words_separated_by_pauses_never_reuse_driver_runs():
    class FakeDriver:
        def __init__(self, name: str) -> None:
            self.name = name
            self.said: list[str] = []
            self.run_count = 0

        def say(self, text: str) -> None:
            self.said.append(text)

        def runAndWait(self) -> None:
            self.run_count += 1
            if self.run_count > 1:
                raise RuntimeError("driver reused across pause-delimited segments")

        def setProperty(self, name: str, value: object) -> None:
            pass

        def stop(self) -> None:
            pass

    created_drivers: list[FakeDriver] = []
    engine = SpeechEngine()
    engine._init_driver = lambda: created_drivers.append(
        FakeDriver(f"driver-{len(created_drivers)}")
    ) or created_drivers[-1]
    engine._validate_selected_voices = lambda settings: None
    engine._sleep_pause = lambda seconds, stop_event: None

    plan = _make_plan(
        _make_unit(0, "hello", SpeakAction.READ_WORD, "hello"),
        _make_unit(1, " ", SpeakAction.PAUSE, "", pause_ms=120, voice_role=VoiceRole.NONE),
        _make_unit(2, "world", SpeakAction.READ_WORD, "world"),
        _make_unit(3, " ", SpeakAction.PAUSE, "", pause_ms=120, voice_role=VoiceRole.NONE),
        _make_unit(4, "again", SpeakAction.READ_WORD, "again"),
    )
    session = engine.play(
        plan,
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="english", chinese_voice_id="chinese")
        ),
    )
    state = engine.wait_until_finished(session, timeout=1.0)
    engine.shutdown()

    assert state == PlaybackState.COMPLETED
    assert [driver.said for driver in created_drivers] == [["hello"], ["world"], ["again"]]
    assert [driver.run_count for driver in created_drivers] == [1, 1, 1]


def test_speech_engine_flushes_when_voice_role_changes_without_pause():
    class FakeDriver:
        def __init__(self, name: str) -> None:
            self.name = name
            self.said: list[str] = []
            self.run_count = 0

        def say(self, text: str) -> None:
            self.said.append(text)

        def runAndWait(self) -> None:
            self.run_count += 1

        def setProperty(self, name: str, value: object) -> None:
            pass

        def stop(self) -> None:
            pass

    created_drivers: list[FakeDriver] = []
    engine = SpeechEngine()
    engine._init_driver = lambda: created_drivers.append(
        FakeDriver(f"driver-{len(created_drivers)}")
    ) or created_drivers[-1]
    engine._validate_selected_voices = lambda settings: None

    plan = _make_plan(
        _make_unit(0, "a", SpeakAction.READ_WORD, "a", voice_role=VoiceRole.ENGLISH),
        _make_unit(1, " ", SpeakAction.READ_SYMBOL, "空格", voice_role=VoiceRole.CHINESE),
        _make_unit(2, "b", SpeakAction.READ_WORD, "b", voice_role=VoiceRole.ENGLISH),
    )
    session = engine.play(
        plan,
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="english", chinese_voice_id="chinese")
        ),
    )
    state = engine.wait_until_finished(session, timeout=1.0)
    engine.shutdown()

    assert state == PlaybackState.COMPLETED
    assert [driver.said for driver in created_drivers] == [["a"], ["空格"], ["b"]]
    assert [driver.run_count for driver in created_drivers] == [1, 1, 1]


def test_speech_engine_uses_english_safe_text_when_chinese_voice_is_same_as_english():
    class FakeDriver:
        def __init__(self, name: str) -> None:
            self.name = name
            self.said: list[str] = []

        def say(self, text: str) -> None:
            self.said.append(text)

        def runAndWait(self) -> None:
            pass

        def setProperty(self, name: str, value: object) -> None:
            pass

        def stop(self) -> None:
            pass

    created_drivers: list[FakeDriver] = []
    engine = SpeechEngine()
    engine._init_driver = lambda: created_drivers.append(
        FakeDriver(f"driver-{len(created_drivers)}")
    ) or created_drivers[-1]
    engine._validate_selected_voices = lambda settings: None

    plan = _make_plan(
        _make_unit(0, "123", SpeakAction.READ_NUMBER, "一二三", voice_role=VoiceRole.CHINESE),
        _make_unit(1, "-", SpeakAction.READ_SYMBOL, "连字符", voice_role=VoiceRole.CHINESE),
        _make_unit(2, " ", SpeakAction.READ_SYMBOL, "空格", voice_role=VoiceRole.CHINESE),
    )
    session = engine.play(
        plan,
        PlaybackSettings(
            voices=VoiceSelection(english_voice_id="english", chinese_voice_id="english")
        ),
    )
    state = engine.wait_until_finished(session, timeout=1.0)
    engine.shutdown()

    assert state == PlaybackState.COMPLETED
    assert [driver.said for driver in created_drivers] == [["1 2 3", "hyphen", "space"]]


def test_speech_engine_uses_english_safe_text_when_chinese_voice_is_not_chinese():
    engine = SpeechEngine.__new__(SpeechEngine)

    unit = _make_unit(
        0,
        "123",
        SpeakAction.READ_NUMBER,
        "一二三",
        voice_role=VoiceRole.CHINESE,
    )
    settings = PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id="HKEY\\Microsoft David",
            chinese_voice_id="HKEY\\Microsoft Mark",
        )
    )

    assert engine._get_driver_speak_text(settings, unit) == "1 2 3"


def test_speech_engine_keeps_chinese_text_when_chinese_voice_looks_chinese():
    engine = SpeechEngine.__new__(SpeechEngine)

    unit = _make_unit(
        0,
        "123",
        SpeakAction.READ_NUMBER,
        "一二三",
        voice_role=VoiceRole.CHINESE,
    )
    settings = PlaybackSettings(
        voices=VoiceSelection(
            english_voice_id="HKEY\\Microsoft David",
            chinese_voice_id="HKEY\\MSTTS_V110_zhCN_HuihuiM",
        )
    )

    assert engine._get_driver_speak_text(settings, unit) == "一二三"


def test_speech_engine_keeps_space_chinese_when_selected_voice_metadata_is_chinese():
    engine = SpeechEngine.__new__(SpeechEngine)

    unit = _make_unit(
        0,
        " ",
        SpeakAction.READ_SYMBOL,
        "空格",
        voice_role=VoiceRole.CHINESE,
    )
    settings = PlaybackSettings(
        voices=types.SimpleNamespace(
            english_voice_id="voice-1",
            chinese_voice_id="voice-2",
            chinese_voice=types.SimpleNamespace(
                id="voice-2",
                name="Microsoft Huihui",
                languages=("zh_CN",),
            ),
        )
    )

    assert engine._get_driver_speak_text(settings, unit) == "空格"


def test_speech_engine_keeps_symbol_chinese_when_chinese_voice_is_distinct():
    engine = SpeechEngine.__new__(SpeechEngine)
    settings = PlaybackSettings(
        voices=VoiceSelection(english_voice_id="voice-1", chinese_voice_id="voice-2")
    )

    units = [
        _make_unit(0, "+", SpeakAction.READ_SYMBOL, "加号", voice_role=VoiceRole.CHINESE),
        _make_unit(1, "-", SpeakAction.READ_SYMBOL, "连字符", voice_role=VoiceRole.CHINESE),
        _make_unit(2, "=", SpeakAction.READ_SYMBOL, "等于号", voice_role=VoiceRole.CHINESE),
    ]

    assert [engine._get_driver_speak_text(settings, unit) for unit in units] == [
        "加号",
        "连字符",
        "等于号",
    ]


def test_controller_waits_for_playback_session_completion(monkeypatch) -> None:
    _install_fake_tkinter(monkeypatch)
    controller_module = importlib.import_module("app.controller")
    AppController = controller_module.AppController

    finish_event = threading.Event()
    controller = AppController.__new__(AppController)
    controller.event_queue = queue.Queue()
    controller._stop_requested = threading.Event()
    controller._dependencies = types.SimpleNamespace(
        build_speech_plan=lambda text, options: types.SimpleNamespace(units=["u1", "u2"]),
        ParseOptions=types.SimpleNamespace,
        ReadingMode=types.SimpleNamespace,
        NumberMode=types.SimpleNamespace,
        VoiceSelection=types.SimpleNamespace,
        PlaybackSettings=types.SimpleNamespace,
        PlaybackEventType=types.SimpleNamespace(
            STARTED="started",
            STOPPED="stopped",
            COMPLETED="completed",
            ERROR="error",
        ),
    )
    controller._engine = types.SimpleNamespace()
    controller._build_parse_options = lambda: None
    controller._build_voice_selection = lambda: None
    controller._build_playback_settings = lambda voice_selection: None

    session = PlaybackSession(total_units=2)

    def play(*args, **kwargs):
        return session

    def wait_until_finished(waited_session):
        assert waited_session is session
        assert not finish_event.is_set()
        finish_event.wait(timeout=1.0)
        if not finish_event.is_set():
            raise AssertionError("controller returned before playback finished")
        session.state = PlaybackState.COMPLETED
        session.finished_at = time.time()
        return session.state

    controller._engine.play = play
    controller._engine.wait_until_finished = wait_until_finished

    worker = threading.Thread(
        target=controller._playback_worker,
        args=("Hello",),
        daemon=True,
    )
    worker.start()

    time.sleep(0.1)
    queued = list(controller.event_queue.queue)
    assert [event.kind for event in queued] == ["progress", "status"]
    assert queued[1].payload == "正在播放..."

    finish_event.set()
    worker.join(timeout=1.0)
    assert not worker.is_alive()

    queued = list(controller.event_queue.queue)
    assert [event.kind for event in queued] == [
        "progress",
        "status",
        "progress",
        "status",
        "playback_finished",
    ]
    assert queued[3].payload == "播放完成。"


def test_controller_reports_session_error_message(monkeypatch) -> None:
    _install_fake_tkinter(monkeypatch)
    controller_module = importlib.import_module("app.controller")
    AppController = controller_module.AppController

    controller = AppController.__new__(AppController)
    controller.event_queue = queue.Queue()
    controller._stop_requested = threading.Event()
    controller._dependencies = types.SimpleNamespace(
        build_speech_plan=lambda text, options: types.SimpleNamespace(units=["u1"]),
        ParseOptions=types.SimpleNamespace,
        ReadingMode=types.SimpleNamespace,
        NumberMode=types.SimpleNamespace,
        VoiceSelection=types.SimpleNamespace,
        PlaybackSettings=types.SimpleNamespace,
        PlaybackEventType=types.SimpleNamespace(
            STARTED="started",
            STOPPED="stopped",
            COMPLETED="completed",
            ERROR="error",
        ),
    )
    controller._engine = types.SimpleNamespace()
    controller._build_parse_options = lambda: None
    controller._build_voice_selection = lambda: None
    controller._build_playback_settings = lambda voice_selection: None

    session = PlaybackSession(total_units=1)
    session.error_message = "speaker unavailable"

    def play(*args, **kwargs):
        return session

    def wait_until_finished(waited_session):
        assert waited_session is session
        session.state = PlaybackState.ERROR
        session.finished_at = time.time()
        return session.state

    controller._engine.play = play
    controller._engine.wait_until_finished = wait_until_finished

    controller._playback_worker("Hello")

    queued = list(controller.event_queue.queue)
    assert [event.kind for event in queued] == [
        "progress",
        "status",
        "progress_reset",
        "error",
        "playback_finished",
    ]
    assert str(queued[3].payload) == "speaker unavailable"


def test_controller_resume_uses_remaining_units_after_pause(monkeypatch) -> None:
    _install_fake_tkinter(monkeypatch)
    controller_module = importlib.import_module("app.controller")
    AppController = controller_module.AppController

    text = "one two three"
    full_plan = _make_plan(
        _make_unit(0, "one", SpeakAction.READ_WORD, "one"),
        _make_unit(1, "two", SpeakAction.READ_WORD, "two"),
        _make_unit(2, "three", SpeakAction.READ_WORD, "three"),
    )
    played_units: list[list[str]] = []

    controller = AppController.__new__(AppController)
    controller.event_queue = queue.Queue()
    controller._stop_requested = threading.Event()
    controller._dependencies = types.SimpleNamespace(
        build_speech_plan=lambda playback_text, options: full_plan,
        ParseOptions=types.SimpleNamespace,
        ReadingMode=types.SimpleNamespace,
        NumberMode=types.SimpleNamespace,
        VoiceSelection=types.SimpleNamespace,
        PlaybackSettings=types.SimpleNamespace,
        PlaybackEventType=types.SimpleNamespace(
            STARTED="started",
            STOPPED="stopped",
            COMPLETED="completed",
            ERROR="error",
            UNIT_FINISHED="unit_finished",
        ),
    )
    controller._engine = types.SimpleNamespace()
    controller._build_parse_options = lambda: None
    controller._build_voice_selection = lambda: None
    controller._build_playback_settings = lambda voice_selection: None
    controller._paused_text = text
    controller._resume_unit_index = 1
    controller._last_finished_unit_index = 0
    controller._pause_requested = False
    controller._current_playback_text = None
    controller._progress_lock = threading.Lock()

    session = PlaybackSession(total_units=2)

    def play(plan, *args, **kwargs):
        played_units.append([unit.speak_text for unit in plan.units])
        session.state = PlaybackState.COMPLETED
        session.finished_at = time.time()
        return session

    controller._engine.play = play
    controller._engine.wait_until_finished = lambda waited_session: waited_session.state

    controller._playback_worker(text)

    assert played_units == [["two", "three"]]


def test_controller_stop_resets_resume_progress(monkeypatch) -> None:
    _install_fake_tkinter(monkeypatch)
    controller_module = importlib.import_module("app.controller")
    AppController = controller_module.AppController

    text = "one two"
    full_plan = _make_plan(
        _make_unit(0, "one", SpeakAction.READ_WORD, "one"),
        _make_unit(1, "two", SpeakAction.READ_WORD, "two"),
    )
    status_messages: list[str] = []
    played_units: list[list[str]] = []

    controller = AppController.__new__(AppController)
    controller.event_queue = queue.Queue()
    controller._stop_requested = threading.Event()
    controller._is_playing = True
    controller._paused_text = text
    controller._resume_unit_index = 1
    controller._last_finished_unit_index = 0
    controller._pause_requested = True
    controller._current_playback_text = text
    controller._progress_lock = threading.Lock()
    controller.view = types.SimpleNamespace(
        set_status=lambda message: status_messages.append(message)
    )
    controller._dependencies = types.SimpleNamespace(
        build_speech_plan=lambda playback_text, options: full_plan,
        ParseOptions=types.SimpleNamespace,
        ReadingMode=types.SimpleNamespace,
        NumberMode=types.SimpleNamespace,
        VoiceSelection=types.SimpleNamespace,
        PlaybackSettings=types.SimpleNamespace,
        PlaybackEventType=types.SimpleNamespace(
            STARTED="started",
            STOPPED="stopped",
            COMPLETED="completed",
            ERROR="error",
            UNIT_FINISHED="unit_finished",
        ),
    )
    controller._build_parse_options = lambda: None
    controller._build_voice_selection = lambda: None
    controller._build_playback_settings = lambda voice_selection: None

    session = PlaybackSession(total_units=2)

    def play(plan, *args, **kwargs):
        played_units.append([unit.speak_text for unit in plan.units])
        session.state = PlaybackState.COMPLETED
        session.finished_at = time.time()
        return session

    controller._engine = types.SimpleNamespace(
        stop=lambda: None,
        play=play,
        wait_until_finished=lambda waited_session: waited_session.state,
    )

    controller.handle_stop()
    controller._playback_worker(text)

    assert controller._resume_unit_index == 0
    assert played_units == [["one", "two"]]


def _make_progress_controller(monkeypatch):
    _install_fake_tkinter(monkeypatch)
    controller_module = importlib.import_module("app.controller")
    AppController = controller_module.AppController
    controller = AppController.__new__(AppController)
    controller.event_queue = queue.Queue()
    controller._progress_lock = threading.Lock()
    controller._pause_requested = False
    controller._paused_text = None
    controller._current_playback_text = "one two three"
    controller._resume_unit_index = 0
    controller._last_finished_unit_index = -1
    controller._dependencies = types.SimpleNamespace(
        PlaybackEventType=types.SimpleNamespace(
            UNIT_STARTED="unit_started",
            UNIT_FINISHED="unit_finished",
        )
    )
    return controller_module, controller


def test_controller_progress_updates_current_token_on_unit_started(monkeypatch) -> None:
    _, controller = _make_progress_controller(monkeypatch)
    units = [
        _make_unit(0, "one", SpeakAction.READ_WORD, "one"),
        _make_unit(1, "two", SpeakAction.READ_WORD, "two"),
    ]
    controller._begin_progress_tracking(units)

    controller._record_playback_progress(
        types.SimpleNamespace(event_type="unit_started", unit=units[0], unit_index=0)
    )

    queued = list(controller.event_queue.queue)
    assert queued[-1].kind == "progress"
    assert queued[-1].payload["completed"] == 0
    assert queued[-1].payload["total"] == 2
    assert queued[-1].payload["token"] == "one"
    assert queued[-1].payload["read_until"] == 3


def test_controller_progress_advances_and_uses_plan_eta(monkeypatch) -> None:
    controller_module, controller = _make_progress_controller(monkeypatch)
    times = iter([100.0, 104.0])
    monkeypatch.setattr(controller_module.time, "monotonic", lambda: next(times))
    units = [
        _make_unit(0, "one", SpeakAction.READ_WORD, "one"),
        _make_unit(1, "two", SpeakAction.READ_WORD, "two"),
        _make_unit(2, "three", SpeakAction.READ_WORD, "three"),
    ]
    controller._begin_progress_tracking(units)

    controller._record_playback_progress(
        types.SimpleNamespace(event_type="unit_finished", unit=units[0], unit_index=0)
    )

    queued = list(controller.event_queue.queue)
    assert queued[-1].payload["completed"] == 1
    assert queued[-1].payload["total"] == 3
    assert queued[-1].payload["token"] == "one"
    assert queued[-1].payload["eta_seconds"] == 0.9
    assert controller._resume_unit_index == 1


def test_controller_progress_marks_read_source_span(monkeypatch) -> None:
    _, controller = _make_progress_controller(monkeypatch)
    units = [
        _make_unit(0, "one", SpeakAction.READ_WORD, "one"),
        _make_unit(4, "two", SpeakAction.READ_WORD, "two"),
    ]
    controller._begin_progress_tracking(units)

    controller._record_playback_progress(
        types.SimpleNamespace(event_type="unit_finished", unit=units[0], unit_index=0)
    )

    queued = list(controller.event_queue.queue)
    assert queued[-1].payload["read_until"] == 3


def test_controller_eta_uses_plan_estimates_instead_of_elapsed_average(monkeypatch) -> None:
    controller_module, controller = _make_progress_controller(monkeypatch)
    times = iter([100.0, 1100.0])
    monkeypatch.setattr(controller_module.time, "monotonic", lambda: next(times))
    units = [
        _make_unit(0, " ", SpeakAction.PAUSE, "", pause_ms=1000, voice_role=VoiceRole.NONE),
        _make_unit(1, " ", SpeakAction.PAUSE, "", pause_ms=2000, voice_role=VoiceRole.NONE),
        _make_unit(2, " ", SpeakAction.PAUSE, "", pause_ms=3000, voice_role=VoiceRole.NONE),
    ]
    controller._begin_progress_tracking(units)

    controller._record_playback_progress(
        types.SimpleNamespace(event_type="unit_finished", unit=units[0], unit_index=0)
    )

    queued = list(controller.event_queue.queue)
    assert queued[-1].payload["eta_seconds"] == 5.0


def test_controller_progress_uses_resume_slice_indexes(monkeypatch) -> None:
    _, controller = _make_progress_controller(monkeypatch)
    units = [
        _make_unit(2, "two", SpeakAction.READ_WORD, "two"),
        _make_unit(3, "three", SpeakAction.READ_WORD, "three"),
        _make_unit(4, "four", SpeakAction.READ_WORD, "four"),
    ]
    controller._begin_progress_tracking(units)

    controller._record_playback_progress(
        types.SimpleNamespace(event_type="unit_finished", unit=units[0], unit_index=2)
    )
    controller._record_playback_progress(
        types.SimpleNamespace(event_type="unit_finished", unit=units[2], unit_index=4)
    )

    queued = [event for event in controller.event_queue.queue if event.kind == "progress"]
    assert queued[0].payload["completed"] == 1
    assert queued[0].payload["total"] == 3
    assert queued[-1].payload["completed"] == 3
    assert queued[-1].payload["total"] == 3


def test_controller_handles_progress_queue_event(monkeypatch) -> None:
    _, controller = _make_progress_controller(monkeypatch)
    calls: list[tuple[int, int, str, float | None, str]] = []
    marks: list[int] = []
    controller.view = types.SimpleNamespace(
        set_playback_progress=lambda completed, total, **kwargs: calls.append(
            (
                completed,
                total,
                kwargs.get("token", ""),
                kwargs.get("eta_seconds"),
                kwargs.get("state", ""),
            )
        ),
        mark_text_read_until=lambda read_until: marks.append(read_until),
    )

    controller._handle_queued_event(
        types.SimpleNamespace(
            kind="progress",
            payload={
                "completed": 2,
                "total": 5,
                "token": "two",
                "eta_seconds": 3.5,
                "state": "playing",
                "read_until": 7,
            },
        )
    )

    assert calls == [(2, 5, "two", 3.5, "playing")]
    assert marks == [7]


def test_controller_pause_keeps_progress_state(monkeypatch) -> None:
    _, controller = _make_progress_controller(monkeypatch)
    reset_calls: list[None] = []
    controller._is_playing = True
    controller._current_playback_text = "one two"
    controller._last_finished_unit_index = 0
    controller._resume_unit_index = 1
    controller._playback_total_units = 2
    controller._playback_completed_units = 1
    controller.view = types.SimpleNamespace(
        set_status=lambda message: None,
        reset_playback_progress=lambda: reset_calls.append(None),
    )
    controller._engine = types.SimpleNamespace(stop=lambda: None)
    controller._stop_requested = threading.Event()

    controller.handle_pause()

    assert controller._pause_requested is True
    assert controller._playback_completed_units == 1
    assert reset_calls == []


def test_view_marks_and_clears_read_text_ranges(monkeypatch) -> None:
    _install_fake_tkinter(monkeypatch)
    ui_module = importlib.import_module("app.ui")
    view = ui_module.SpellReaderView.__new__(ui_module.SpellReaderView)

    class FakeText:
        def __init__(self) -> None:
            self.added: list[tuple[str, str, str]] = []
            self.deleted: list[tuple[str, str, str]] = []
            self.configured: list[tuple[str, dict[str, object]]] = []

        def tag_configure(self, tag: str, **kwargs) -> None:
            self.configured.append((tag, kwargs))

        def tag_remove(self, tag: str, start: str, end: str) -> None:
            self.deleted.append((tag, start, end))

        def tag_add(self, tag: str, start: str, end: str) -> None:
            self.added.append((tag, start, end))

    fake_text = FakeText()
    view.text_input = fake_text
    view._read_marker_tag_configured = False

    view.mark_text_read_until(5)
    view.clear_read_markers()

    assert fake_text.configured
    assert fake_text.added == [("read_text", "1.0", "1.0+5c")]
    assert fake_text.deleted[-1] == ("read_text", "1.0", "end")
