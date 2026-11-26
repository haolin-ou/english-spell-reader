from __future__ import annotations

import importlib
import sys
import types
from types import SimpleNamespace


def _load_controller(monkeypatch):
    fake_tkinter = types.ModuleType("tkinter")
    fake_ttk = types.ModuleType("tkinter.ttk")
    fake_messagebox = types.ModuleType("tkinter.messagebox")
    dummy_widget = type("DummyWidget", (), {})

    fake_tkinter.Tk = dummy_widget
    fake_tkinter.Toplevel = dummy_widget
    fake_tkinter.Text = dummy_widget
    fake_tkinter.StringVar = dummy_widget
    fake_tkinter.IntVar = dummy_widget
    fake_tkinter.DoubleVar = dummy_widget
    fake_tkinter.Scale = dummy_widget
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
    fake_ttk.Spinbox = dummy_widget
    fake_ttk.Progressbar = dummy_widget
    fake_messagebox.showerror = lambda *args, **kwargs: None
    fake_tkinter.ttk = fake_ttk
    fake_tkinter.messagebox = fake_messagebox

    for module_name in ("app.controller", "app.ui"):
        sys.modules.pop(module_name, None)
    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", fake_messagebox)
    return importlib.import_module("app.controller")


def test_default_english_voice_prefers_sapi_english_voice_over_piper(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    voices = [
        SimpleNamespace(id="sapi-zira", name="Microsoft Zira", languages=("en_US",)),
        SimpleNamespace(id="piper-en", name="Piper built-in English", languages=("en_US",)),
        SimpleNamespace(id="piper-zh", name="Piper Chinese", languages=("zh_CN",)),
    ]

    assert controller._pick_default_english_voice_index(voices) == 0


def test_default_english_voice_falls_back_to_existing_english_match(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    voices = [
        SimpleNamespace(id="sapi-zh", name="Microsoft Huihui", languages=("zh_CN",)),
        SimpleNamespace(id="sapi-en", name="Microsoft Zira", languages=("en_US",)),
    ]

    assert controller._pick_default_english_voice_index(voices) == 1


def test_default_english_voice_does_not_pick_non_english_piper_voice(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    voices = [
        SimpleNamespace(id="piper-fr", name="Piper French", languages=("fr_FR",)),
        SimpleNamespace(id="sapi-en", name="Microsoft Zira", languages=("en_US",)),
    ]

    assert controller._pick_default_english_voice_index(voices) == 1


def test_load_dependencies_routes_to_sapi_by_default_when_piper_and_edge_available(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    calls: list[str] = []

    class FakePiperSpeechEngine:
        def __init__(self) -> None:
            calls.append("piper")

        def list_voices(self):
            return [SimpleNamespace(id="piper:en_US-lessac-medium", name="Piper")]

        def play(self, plan, settings, on_event=None):
            calls.append("piper-play")
            return SimpleNamespace(state="completed")

        def wait_until_finished(self, session, timeout=None):
            return session.state

    class FakeMicrosoftEdgeSpeechEngine:
        def __init__(self) -> None:
            calls.append("edge")

        def list_voices(self):
            return [SimpleNamespace(id="edge:en-US-AvaMultilingualNeural", name="Microsoft Ava")]

        def play(self, plan, settings, on_event=None):
            calls.append("edge-play")
            return SimpleNamespace(state="completed")

        def wait_until_finished(self, session, timeout=None):
            return session.state

    class FakeSpeechEngine:
        def __init__(self) -> None:
            calls.append("speech")

        def list_voices(self):
            return [SimpleNamespace(id="sapi-zira", name="Microsoft Zira")]

        def play(self, plan, settings, on_event=None):
            calls.append("speech-play")
            return SimpleNamespace(state="completed")

        def wait_until_finished(self, session, timeout=None):
            return session.state

    fake_parser = SimpleNamespace(build_speech_plan=lambda text, options: None)
    fake_models = SimpleNamespace(
        ParseOptions=object,
        ReadingMode=object,
        NumberMode=object,
        WhitespaceMode=object,
    )
    fake_speech = SimpleNamespace(
        PiperSpeechEngine=FakePiperSpeechEngine,
        MicrosoftEdgeSpeechEngine=FakeMicrosoftEdgeSpeechEngine,
        SpeechEngine=FakeSpeechEngine,
        VoiceSelection=object,
        PlaybackSettings=object,
        PlaybackEventType=object,
    )

    def fake_import_first(module_names):
        module_name = module_names[0]
        if module_name.endswith("parser"):
            return fake_parser
        if module_name.endswith("models"):
            return fake_models
        if module_name.endswith("speech_engine"):
            return fake_speech
        raise AssertionError(module_names)

    controller._import_first = fake_import_first

    dependencies = controller._load_dependencies()
    engine = dependencies.engine_class()
    voices = engine.list_voices()
    session = engine.play(
        object(),
        SimpleNamespace(voices=SimpleNamespace(english_voice_id="sapi-zira")),
    )

    assert [voice.id for voice in voices] == [
        "sapi-zira",
        "piper:en_US-lessac-medium",
        "edge:en-US-AvaMultilingualNeural",
    ]
    assert session.state == "completed"
    assert calls == ["speech", "piper", "edge", "speech-play"]


def test_routed_engine_uses_piper_only_when_piper_voice_selected(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    calls: list[str] = []

    class FakePiperSpeechEngine:
        def __init__(self) -> None:
            calls.append("piper")

        def list_voices(self):
            return [SimpleNamespace(id="piper:en_US-lessac-medium", name="Piper")]

        def play(self, plan, settings, on_event=None):
            calls.append("piper-play")
            return SimpleNamespace(state="completed")

    class FakeSpeechEngine:
        def __init__(self) -> None:
            calls.append("speech")

        def list_voices(self):
            return [SimpleNamespace(id="sapi-zira", name="Microsoft Zira")]

        def play(self, plan, settings, on_event=None):
            calls.append("speech-play")
            return SimpleNamespace(state="completed")

    engine = controller._build_engine_factory(FakePiperSpeechEngine, FakeSpeechEngine)()

    session = engine.play(
        object(),
        SimpleNamespace(voices=SimpleNamespace(english_voice_id="piper:en_US-lessac-medium")),
    )

    assert session.state == "completed"
    assert calls == ["speech", "piper", "piper-play"]


def test_routed_engine_uses_microsoft_edge_when_edge_voice_selected(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    calls: list[str] = []

    class FakePiperSpeechEngine:
        def __init__(self) -> None:
            calls.append("piper")

        def list_voices(self):
            return [SimpleNamespace(id="piper:en_US-lessac-medium", name="Piper")]

        def play(self, plan, settings, on_event=None):
            calls.append("piper-play")
            return SimpleNamespace(state="completed")

    class FakeMicrosoftEdgeSpeechEngine:
        def __init__(self) -> None:
            calls.append("edge")

        def list_voices(self):
            return [SimpleNamespace(id="edge:en-US-AvaMultilingualNeural", name="Microsoft Ava")]

        def play(self, plan, settings, on_event=None):
            calls.append("edge-play")
            return SimpleNamespace(state="completed")

    class FakeSpeechEngine:
        def __init__(self) -> None:
            calls.append("speech")

        def list_voices(self):
            return [SimpleNamespace(id="sapi-zira", name="Microsoft Zira")]

        def play(self, plan, settings, on_event=None):
            calls.append("speech-play")
            return SimpleNamespace(state="completed")

    engine = controller._build_engine_factory(
        FakePiperSpeechEngine,
        FakeSpeechEngine,
        FakeMicrosoftEdgeSpeechEngine,
    )()

    session = engine.play(
        object(),
        SimpleNamespace(voices=SimpleNamespace(english_voice_id="edge:en-US-AvaMultilingualNeural")),
    )

    assert session.state == "completed"
    assert calls == ["speech", "piper", "edge", "edge-play"]


def test_routed_engine_falls_back_to_edge_when_selected_piper_returns_error(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    calls: list[str] = []

    class FakePiperSpeechEngine:
        def __init__(self) -> None:
            calls.append("piper")

        def list_voices(self):
            return [SimpleNamespace(id="piper:en_US-lessac-medium", name="Piper")]

        def play(self, plan, settings, on_event=None):
            calls.append("piper-play")
            return SimpleNamespace(state="error", error_message="piper unavailable")

    class FakeMicrosoftEdgeSpeechEngine:
        def __init__(self) -> None:
            calls.append("edge")

        def list_voices(self):
            return [SimpleNamespace(id="edge:en-US-AvaMultilingualNeural", name="Microsoft Ava")]

        def play(self, plan, settings, on_event=None):
            calls.append(("edge-play", settings.voices.english_voice_id))
            return SimpleNamespace(state="completed")

    class FakeSpeechEngine:
        def __init__(self) -> None:
            calls.append("speech")

        def list_voices(self):
            return [SimpleNamespace(id="sapi-zira", name="Microsoft Zira")]

        def play(self, plan, settings, on_event=None):
            calls.append("speech-play")
            return SimpleNamespace(state="completed")

    engine = controller._build_engine_factory(
        FakePiperSpeechEngine,
        FakeSpeechEngine,
        FakeMicrosoftEdgeSpeechEngine,
    )()

    session = engine.play(
        object(),
        SimpleNamespace(
            voices=SimpleNamespace(
                english_voice_id="piper:en_US-lessac-medium",
                chinese_voice_id="piper:en_US-lessac-medium",
            )
        ),
    )

    assert session.state == "completed"
    assert calls == [
        "speech",
        "piper",
        "edge",
        "piper-play",
        ("edge-play", "edge:en-US-AvaMultilingualNeural"),
    ]


def test_load_dependencies_falls_back_when_piper_init_fails(monkeypatch) -> None:
    controller_module = _load_controller(monkeypatch)
    controller = controller_module.AppController.__new__(controller_module.AppController)
    calls: list[str] = []

    class FakePiperSpeechEngine:
        def __init__(self) -> None:
            calls.append("piper")
            raise RuntimeError("piper unavailable")

    class FakeSpeechEngine:
        def __init__(self) -> None:
            calls.append("speech")

        def list_voices(self):
            return [SimpleNamespace(id="sapi-zira", name="Microsoft Zira")]

    fake_parser = SimpleNamespace(build_speech_plan=lambda text, options: None)
    fake_models = SimpleNamespace(
        ParseOptions=object,
        ReadingMode=object,
        NumberMode=object,
        WhitespaceMode=object,
    )
    fake_speech = SimpleNamespace(
        PiperSpeechEngine=FakePiperSpeechEngine,
        SpeechEngine=FakeSpeechEngine,
        VoiceSelection=object,
        PlaybackSettings=object,
        PlaybackEventType=object,
    )

    def fake_import_first(module_names):
        module_name = module_names[0]
        if module_name.endswith("parser"):
            return fake_parser
        if module_name.endswith("models"):
            return fake_models
        if module_name.endswith("speech_engine"):
            return fake_speech
        raise AssertionError(module_names)

    controller._import_first = fake_import_first

    dependencies = controller._load_dependencies()
    engine = dependencies.engine_class()

    assert [voice.id for voice in engine.list_voices()] == ["sapi-zira"]
    assert calls == ["speech", "piper"]
