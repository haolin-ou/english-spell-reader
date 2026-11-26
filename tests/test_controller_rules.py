from __future__ import annotations

import importlib
import inspect
import queue
import sys
import threading
import time
import types
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace

import pytest

from app.models import NumberMode, ParseOptions, ReadingMode, SpeakAction, WhitespaceMode
from app.parser import build_speech_plan
from app.settings import ReaderRules


def _supports_field(factory, name: str) -> bool:
    return name in inspect.signature(factory).parameters


def _make_reader_rules(**overrides):
    kwargs = {
        "special_words": frozenset(),
        "custom_symbol_readings": {},
        "custom_letter_readings": {},
        "custom_letter_audio_paths": {},
        "word_pause_ms": 120,
        "letter_pause_ms": 0,
        "spell_chunk_pause_ms": 300,
        "custom_letter_pause_ms": None,
    }
    kwargs.update(overrides)
    if not _supports_field(ReaderRules, "space_behavior"):
        kwargs.pop("space_behavior", None)
    if not _supports_field(ReaderRules, "custom_letter_pause_ms"):
        kwargs.pop("custom_letter_pause_ms", None)
    if not _supports_field(ReaderRules, "spell_chunk_pause_ms"):
        kwargs.pop("spell_chunk_pause_ms", None)
    if not _supports_field(ReaderRules, "custom_letter_readings"):
        kwargs.pop("custom_letter_readings", None)
    if not _supports_field(ReaderRules, "custom_letter_audio_paths"):
        kwargs.pop("custom_letter_audio_paths", None)
    return ReaderRules(**kwargs)


def _make_parse_options(**overrides):
    kwargs = {
        "reading_mode": ReadingMode.SPELL_THEN_READ_WORD,
        "number_mode": NumberMode.DIGIT_BY_DIGIT,
        "special_words": frozenset(),
        "custom_symbol_readings": {},
        "custom_letter_readings": {},
        "custom_letter_audio_paths": {},
        "word_pause_ms": 120,
        "letter_pause_ms": 0,
        "spell_chunk_pause_ms": 300,
    }
    kwargs.update(overrides)
    if "space_behavior" in kwargs and _supports_field(ParseOptions, "whitespace_mode"):
        kwargs["whitespace_mode"] = WhitespaceMode(kwargs.pop("space_behavior"))
    if not _supports_field(ParseOptions, "space_behavior"):
        kwargs.pop("space_behavior", None)
    if not _supports_field(ParseOptions, "custom_letter_readings"):
        kwargs.pop("custom_letter_readings", None)
    if not _supports_field(ParseOptions, "custom_letter_audio_paths"):
        kwargs.pop("custom_letter_audio_paths", None)
    if not _supports_field(ParseOptions, "spell_chunk_pause_ms"):
        kwargs.pop("spell_chunk_pause_ms", None)
    return ParseOptions(**kwargs)


def _load_parse_rules_text(monkeypatch):
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

    return importlib.import_module("app.controller")._parse_rules_text


def test_parse_rules_text_accepts_valid_rules(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    rules = parse_rules_text(
        "and\nThe\n\n",
        "&=and symbol\n-=hyphen\n",
        250,
        7,
        "read_space",
        "33",
        letter_readings_text="p=puh\nA=ah\n",
        letter_audio_text="P=/voice/p.wav\n",
    )

    assert rules == _make_reader_rules(
        special_words=frozenset({"and", "the"}),
        custom_symbol_readings={"&": "and symbol", "-": "hyphen"},
        custom_letter_readings={"P": "puh", "A": "ah"},
        custom_letter_audio_paths={"P": "/voice/p.wav"},
        word_pause_ms=250,
        letter_pause_ms=7,
        custom_letter_pause_ms=None,
        space_behavior="read_space",
    )


def test_parse_rules_text_rejects_non_ascii_special_word(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    with pytest.raises(ValueError, match="特殊单词"):
        parse_rules_text("and\n你好\n", "", 120, 0, "pause")


def test_parse_rules_text_requires_single_character_symbol(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    with pytest.raises(ValueError, match="符号左侧"):
        parse_rules_text("", "++=plus plus\n", 120, 0, "pause")


def test_parse_rules_text_requires_single_ascii_letter(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    with pytest.raises(ValueError, match="字母读法"):
        parse_rules_text("", "", 120, 0, "pause", letter_readings_text="pp=puh\n")

    with pytest.raises(ValueError, match="字母读法"):
        parse_rules_text("", "", 120, 0, "pause", letter_readings_text="你=ni\n")


def test_parse_rules_text_rejects_invalid_letter_audio(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    with pytest.raises(ValueError, match="字母录音"):
        parse_rules_text("", "", 120, 0, "pause", letter_audio_text="pp=/voice/p.wav\n")

    with pytest.raises(ValueError, match="字母录音"):
        parse_rules_text("", "", 120, 0, "pause", letter_audio_text="P=/voice/p.mp3\n")


def test_parse_rules_text_rejects_invalid_letter_pause(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    with pytest.raises(ValueError, match="字母间隔"):
        parse_rules_text("", "", 120, -1, "pause")

    with pytest.raises(ValueError, match="字母间隔"):
        parse_rules_text("", "", 120, 1001, "pause")


def test_parse_rules_text_ignores_legacy_custom_letter_pause(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    rules = parse_rules_text("", "", 120, 5, "pause", "-1")

    assert rules.letter_pause_ms == 5
    assert rules.custom_letter_pause_ms is None


def test_parse_rules_text_rejects_unknown_space_behavior(monkeypatch):
    parse_rules_text = _load_parse_rules_text(monkeypatch)

    with pytest.raises(ValueError, match="空白处理"):
        parse_rules_text("", "", 120, 0, "skip")


def test_build_parse_options_uses_current_main_word_pause(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    controller._dependencies = SimpleNamespace(
        ParseOptions=ParseOptions,
        ReadingMode=ReadingMode,
        NumberMode=NumberMode,
        WhitespaceMode=WhitespaceMode,
    )
    controller._rules = _make_reader_rules(
        special_words=frozenset({"and"}),
        custom_symbol_readings={"&": "and symbol"},
        custom_letter_readings={"P": "puh"},
        custom_letter_audio_paths={"P": "/voice/p.wav"},
        word_pause_ms=120,
        letter_pause_ms=3,
        space_behavior="pause",
    )
    controller._space_behavior = "read_blank"
    controller.view = SimpleNamespace(
        get_selected_reading_mode=lambda: "spell_then_read_word",
        get_selected_number_mode=lambda: "digit_by_digit",
        get_word_pause_ms=lambda: 480,
        get_letter_pause_ms=lambda: 5,
        get_spell_chunk_pause_ms=lambda: 700,
        get_spell_chunk_size=lambda: 3,
    )

    options = controller._build_parse_options()

    assert options == _make_parse_options(
        reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
        number_mode=NumberMode.DIGIT_BY_DIGIT,
        special_words=frozenset({"and"}),
        custom_symbol_readings={"&": "and symbol"},
        custom_letter_readings={"P": "puh"},
        custom_letter_audio_paths={"P": "/voice/p.wav"},
        word_pause_ms=480,
        letter_pause_ms=5,
        spell_chunk_size=3,
        spell_chunk_pause_ms=700,
        space_behavior="read_blank",
    )


def test_build_parse_options_accepts_new_reading_mode_raw_value(monkeypatch):
    class FutureReadingMode(str, Enum):
        SPELL_THEN_READ_WORD = "spell_then_read_word"
        READ_THEN_SPELL = "read_then_spell"
        READ_THEN_SPELL_THEN_READ = "read_then_spell_then_read"
        SPELL_ONLY = "spell_only"
        READ_ONLY = "read_only"

    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    controller._dependencies = SimpleNamespace(
        ParseOptions=ParseOptions,
        ReadingMode=FutureReadingMode,
        NumberMode=NumberMode,
        WhitespaceMode=WhitespaceMode,
    )
    controller._rules = _make_reader_rules(
        special_words=frozenset(),
        custom_symbol_readings={},
        word_pause_ms=120,
        letter_pause_ms=0,
        space_behavior="pause",
    )
    controller._space_behavior = "read_space"
    controller.view = SimpleNamespace(
        get_selected_reading_mode=lambda: "read_then_spell_then_read",
        get_selected_number_mode=lambda: "digit_by_digit",
        get_word_pause_ms=lambda: 120,
        get_letter_pause_ms=lambda: 5,
        get_spell_chunk_pause_ms=lambda: 300,
        get_spell_chunk_size=lambda: 1,
    )

    options = controller._build_parse_options()

    assert options.reading_mode == FutureReadingMode.READ_THEN_SPELL_THEN_READ
    assert options.number_mode == NumberMode.DIGIT_BY_DIGIT
    assert options.whitespace_mode is WhitespaceMode.READ_SPACE
    assert options.letter_pause_ms == 5


def test_build_parse_options_letter_pause_flows_into_split_spelling_units(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    controller._dependencies = SimpleNamespace(
        ParseOptions=ParseOptions,
        ReadingMode=ReadingMode,
        NumberMode=NumberMode,
        WhitespaceMode=WhitespaceMode,
    )
    controller._rules = _make_reader_rules(
        word_pause_ms=120,
        letter_pause_ms=0,
        custom_letter_pause_ms=None,
        space_behavior="pause",
    )
    controller._space_behavior = "pause"
    controller.view = SimpleNamespace(
        get_selected_reading_mode=lambda: "spell_only",
        get_selected_number_mode=lambda: "digit_by_digit",
        get_word_pause_ms=lambda: 120,
        get_letter_pause_ms=lambda: 90,
        get_spell_chunk_pause_ms=lambda: 300,
        get_spell_chunk_size=lambda: 1,
    )

    options = controller._build_parse_options()
    plan = build_speech_plan("go", options)

    assert options.letter_pause_ms == 90
    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [90]


def test_handle_rules_opens_dialog_with_current_main_word_pause(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    dialog = SimpleNamespace(bind_save=lambda callback: None, bind_cancel=lambda callback: None)
    captured: dict[str, object] = {}

    def open_rules_dialog(
        *,
        special_words,
        custom_symbol_readings,
        custom_letter_readings,
        custom_letter_audio_paths,
    ):
        captured["special_words"] = special_words
        captured["custom_symbol_readings"] = custom_symbol_readings
        captured["custom_letter_readings"] = custom_letter_readings
        captured["custom_letter_audio_paths"] = custom_letter_audio_paths
        return dialog

    controller._rules = _make_reader_rules(
        special_words=frozenset({"the", "and"}),
        custom_symbol_readings={"-": "hyphen"},
        custom_letter_readings={"P": "puh"},
        custom_letter_audio_paths={"P": "/voice/p.wav"},
        word_pause_ms=120,
        letter_pause_ms=4,
        custom_letter_pause_ms=42,
        space_behavior="pause",
    )
    controller._space_behavior = "read_space"
    controller.view = SimpleNamespace(
        get_word_pause_ms=lambda: 360,
        get_letter_pause_ms=lambda: 6,
        open_rules_dialog=open_rules_dialog,
        close_rules_dialog=lambda: None,
    )

    controller.handle_rules()

    assert captured == {
        "special_words": ["and", "the"],
        "custom_symbol_readings": {"-": "hyphen"},
        "custom_letter_readings": {"P": "puh"},
        "custom_letter_audio_paths": {"P": "/voice/p.wav"},
    }


def test_save_rules_from_dialog_preserves_main_settings_and_updates_rule_text(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    saved_rules: list[ReaderRules] = []

    def fake_save_rules(rules):
        saved_rules.append(rules)

    monkeypatch.setattr(controller_module, "save_rules", fake_save_rules)

    class FakeView:
        def __init__(self) -> None:
            self.closed = False
            self.status_messages: list[str] = []
            self.errors: list[tuple[str, str]] = []
            self.word_pause_ms: int | None = None
            self.letter_pause_ms: int | None = None
            self.custom_letter_pause_ms: int | None = None
            self.spell_chunk_pause_ms: int | None = None

        def close_rules_dialog(self) -> None:
            self.closed = True

        def set_status(self, message: str) -> None:
            self.status_messages.append(message)

        def show_error(self, title: str, message: str) -> None:
            self.errors.append((title, message))

        def get_word_pause_ms(self) -> int:
            return 410

        def get_letter_pause_ms(self) -> int:
            return 9

        def get_spell_chunk_pause_ms(self) -> int:
            return 640

        def get_spell_chunk_size(self) -> int:
            return 3

    dialog = SimpleNamespace(
        get_special_words_text=lambda: "and\n",
        get_symbol_readings_text=lambda: "&=and symbol\n",
        get_letter_readings_text=lambda: "P=puh\n",
        get_letter_audio_text=lambda: "P=/voice/p.wav\n",
    )
    controller.view = FakeView()
    controller._rules = _make_reader_rules(
        word_pause_ms=390,
        letter_pause_ms=8,
        spell_chunk_pause_ms=300,
        custom_letter_pause_ms=45,
        space_behavior="read_blank",
    )
    controller._space_behavior = "pause"

    controller._save_rules_from_dialog(dialog)

    assert saved_rules == [
        _make_reader_rules(
            special_words=frozenset({"and"}),
            custom_symbol_readings={"&": "and symbol"},
            custom_letter_readings={"P": "puh"},
            custom_letter_audio_paths={"P": "/voice/p.wav"},
            word_pause_ms=410,
            letter_pause_ms=9,
            spell_chunk_size=3,
            spell_chunk_pause_ms=640,
            custom_letter_pause_ms=None,
            space_behavior="read_blank",
        )
    ]
    assert controller._rules == saved_rules[0]
    assert controller._space_behavior == "pause"
    assert controller.view.closed is True
    assert controller.view.status_messages[-1] == "特殊规则已保存。"
    assert controller.view.errors == []


def test_handle_save_settings_preserves_special_rules_and_updates_main_settings(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)

    @dataclass(frozen=True)
    class FakeRules:
        special_words: frozenset[str]
        custom_symbol_readings: dict[str, str]
        word_pause_ms: int
        letter_pause_ms: int
        custom_letter_pause_ms: int | None
        space_behavior: str
        reading_mode: str
        number_mode: str
        rate: int
        volume: int
        english_voice_id: str | None
        chinese_voice_id: str | None

    saved_rules: list[FakeRules] = []

    def fake_save_rules(rules):
        saved_rules.append(rules)

    monkeypatch.setattr(controller_module, "save_rules", fake_save_rules)

    controller.view = SimpleNamespace(
        get_selected_reading_mode=lambda: "read_then_spell_then_read",
        get_selected_number_mode=lambda: "whole_number",
        get_rate=lambda: 210,
        get_volume=lambda: 65,
        get_word_pause_ms=lambda: 480,
        get_letter_pause_ms=lambda: 6,
        is_space_reading_enabled=lambda: True,
        get_selected_english_voice_index=lambda: 1,
        get_selected_chinese_voice_index=lambda: 2,
        set_status=lambda message: saved_statuses.append(message),
        show_error=lambda title, message: (_ for _ in ()).throw(AssertionError((title, message))),
    )
    saved_statuses: list[str] = []
    controller._voices = [
        SimpleNamespace(id="voice-en-old"),
        SimpleNamespace(id="voice-en-new"),
        SimpleNamespace(id="voice-zh-new"),
    ]
    controller._rules = FakeRules(
        special_words=frozenset({"and"}),
        custom_symbol_readings={"&": "and symbol"},
        word_pause_ms=120,
        letter_pause_ms=0,
        custom_letter_pause_ms=None,
        space_behavior="pause",
        reading_mode="spell_then_read_word",
        number_mode="digit_by_digit",
        rate=160,
        volume=100,
        english_voice_id="voice-en-old",
        chinese_voice_id="voice-zh-old",
    )
    controller._space_behavior = "pause"

    controller.handle_save_settings()

    assert saved_rules == [
        FakeRules(
            special_words=frozenset({"and"}),
            custom_symbol_readings={"&": "and symbol"},
            word_pause_ms=480,
            letter_pause_ms=6,
            custom_letter_pause_ms=None,
            space_behavior="read_space",
            reading_mode="read_then_spell_then_read",
            number_mode="whole_number",
            rate=210,
            volume=65,
            english_voice_id="voice-en-new",
            chinese_voice_id="voice-zh-new",
        )
    ]
    assert controller._rules == saved_rules[0]
    assert controller._space_behavior == "read_space"
    assert saved_statuses == ["设置已保存。"]


def test_init_restores_saved_main_settings_and_binds_save(monkeypatch):
    controller_module = importlib.import_module("app.controller")

    @dataclass(frozen=True)
    class FakeRules:
        special_words: frozenset[str]
        custom_symbol_readings: dict[str, str]
        word_pause_ms: int
        letter_pause_ms: int
        custom_letter_pause_ms: int | None
        space_behavior: str
        reading_mode: str
        number_mode: str
        rate: int
        volume: int
        english_voice_id: str | None
        chinese_voice_id: str | None

    class FakeView:
        def __init__(self, root) -> None:
            self.root = root
            self.bound_callbacks: dict[str, object] = {}
            self.restored: dict[str, object] = {}

        def bind_play(self, callback) -> None:
            self.bound_callbacks["play"] = callback

        def bind_stop(self, callback) -> None:
            self.bound_callbacks["stop"] = callback

        def bind_pause(self, callback) -> None:
            self.bound_callbacks["pause"] = callback

        def bind_clear(self, callback) -> None:
            self.bound_callbacks["clear"] = callback

        def bind_rules(self, callback) -> None:
            self.bound_callbacks["rules"] = callback

        def bind_save_settings(self, callback) -> None:
            self.bound_callbacks["save_settings"] = callback

        def bind_space_reading_toggle(self, callback) -> None:
            self.bound_callbacks["space_toggle"] = callback

        def bind_close(self, callback) -> None:
            self.bound_callbacks["close"] = callback

        def set_selected_reading_mode(self, value: str) -> None:
            self.restored["reading_mode"] = value

        def set_selected_number_mode(self, value: str) -> None:
            self.restored["number_mode"] = value

        def set_rate(self, value: int) -> None:
            self.restored["rate"] = value

        def set_volume(self, value: int) -> None:
            self.restored["volume"] = value

        def set_word_pause_ms(self, value: int) -> None:
            self.restored["word_pause_ms"] = value

        def set_letter_pause_ms(self, value: int) -> None:
            self.restored["letter_pause_ms"] = value

        def set_space_reading_enabled(self, enabled: bool) -> None:
            self.restored["space_reading"] = enabled

        def set_playback_state(self, is_playing: bool) -> None:
            self.restored["is_playing"] = is_playing

        def focus_text(self) -> None:
            self.restored["focused"] = True

    monkeypatch.setattr(controller_module, "SpellReaderView", FakeView)
    monkeypatch.setattr(
        controller_module,
        "load_rules",
        lambda: FakeRules(
            special_words=frozenset({"and"}),
            custom_symbol_readings={"&": "and symbol"},
            word_pause_ms=320,
            letter_pause_ms=7,
            custom_letter_pause_ms=51,
            space_behavior="read_space",
            reading_mode="read_then_spell",
            number_mode="whole_number",
            rate=190,
            volume=55,
            english_voice_id="voice-en",
            chinese_voice_id="voice-zh",
        ),
    )
    monkeypatch.setattr(controller_module.AppController, "_initialize_engine", lambda self: None)
    monkeypatch.setattr(controller_module.AppController, "_schedule_poll", lambda self: None)

    controller = controller_module.AppController(SimpleNamespace())

    assert controller.view.restored == {
        "reading_mode": "read_then_spell",
        "number_mode": "whole_number",
        "rate": 190,
        "volume": 55,
        "word_pause_ms": 320,
        "letter_pause_ms": 51,
        "space_reading": True,
        "is_playing": False,
        "focused": True,
    }
    assert controller.view.bound_callbacks["save_settings"] == controller.handle_save_settings


def test_load_voices_prefers_saved_voice_ids_when_present(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    captured: dict[str, object] = {}

    voices = [
        SimpleNamespace(id="voice-en-default", name="Default English", languages=["en-US"]),
        SimpleNamespace(id="voice-zh-saved", name="Saved Chinese", languages=["zh-CN"]),
        SimpleNamespace(id="voice-en-saved", name="Saved English", languages=["en-GB"]),
    ]
    controller._engine = SimpleNamespace(list_voices=lambda: voices)
    controller._rules = SimpleNamespace(
        english_voice_id="voice-en-saved",
        chinese_voice_id="voice-zh-saved",
    )
    controller.view = SimpleNamespace(
        set_voices=lambda english_labels, chinese_labels, english_index, chinese_index: captured.update(
            {
                "english_labels": english_labels,
                "chinese_labels": chinese_labels,
                "english_index": english_index,
                "chinese_index": chinese_index,
            }
        )
    )

    controller._load_voices()

    assert controller._voices == voices
    assert captured["english_index"] == 2
    assert captured["chinese_index"] == 1


def test_handle_space_reading_toggle_updates_and_persists_rule(monkeypatch):
    _load_parse_rules_text(monkeypatch)
    controller_module = sys.modules["app.controller"]
    controller = controller_module.AppController.__new__(controller_module.AppController)
    saved_rules: list[ReaderRules] = []

    def fake_save_rules(rules):
        saved_rules.append(rules)

    monkeypatch.setattr(controller_module, "save_rules", fake_save_rules)

    class FakeView:
        def __init__(self) -> None:
            self.status_messages: list[str] = []
            self.enabled = True

        def is_space_reading_enabled(self) -> bool:
            return self.enabled

        def set_status(self, message: str) -> None:
            self.status_messages.append(message)

        def show_error(self, title: str, message: str) -> None:
            raise AssertionError((title, message))

    controller.view = FakeView()
    controller._rules = _make_reader_rules(
        special_words=frozenset({"and"}),
        custom_symbol_readings={"&": "and symbol"},
        word_pause_ms=180,
        letter_pause_ms=3,
        custom_letter_pause_ms=40,
        space_behavior="pause",
    )
    controller._space_behavior = "pause"

    controller.handle_space_reading_toggle()

    assert saved_rules == [
        _make_reader_rules(
            special_words=frozenset({"and"}),
            custom_symbol_readings={"&": "and symbol"},
            word_pause_ms=180,
            letter_pause_ms=3,
            custom_letter_pause_ms=None,
            space_behavior="read_space",
        )
    ]
    assert controller._rules == saved_rules[0]
    assert controller._space_behavior == "read_space"
    assert controller.view.status_messages[-1] == "已开启空格朗读。"


def test_init_starts_engine_loading_in_background_and_binds_queue_poll(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    load_started = threading.Event()
    release_loader = threading.Event()
    queue_snapshot: dict[str, object] = {}

    class FakeView:
        def __init__(self, root) -> None:
            self.root = root
            self.status_messages: list[str] = []
            self.bound_callbacks: dict[str, object] = {}
            self.playback_states: list[bool] = []
            self.focused = False

        def bind_play(self, callback) -> None:
            self.bound_callbacks["play"] = callback

        def bind_stop(self, callback) -> None:
            self.bound_callbacks["stop"] = callback

        def bind_pause(self, callback) -> None:
            self.bound_callbacks["pause"] = callback

        def bind_clear(self, callback) -> None:
            self.bound_callbacks["clear"] = callback

        def bind_rules(self, callback) -> None:
            self.bound_callbacks["rules"] = callback

        def bind_space_reading_toggle(self, callback) -> None:
            self.bound_callbacks["space_toggle"] = callback

        def bind_close(self, callback) -> None:
            self.bound_callbacks["close"] = callback

        def set_word_pause_ms(self, value: int) -> None:
            pass

        def set_letter_pause_ms(self, value: int) -> None:
            pass

        def set_status(self, message: str) -> None:
            self.status_messages.append(message)

        def set_playback_state(self, is_playing: bool) -> None:
            self.playback_states.append(is_playing)

        def focus_text(self) -> None:
            self.focused = True

    class FakeRoot:
        def __init__(self) -> None:
            self.after_calls: list[tuple[int, object]] = []

        def after(self, delay_ms: int, callback) -> None:
            self.after_calls.append((delay_ms, callback))

    monkeypatch.setattr(controller_module, "SpellReaderView", FakeView)
    monkeypatch.setattr(controller_module, "load_rules", lambda: _make_reader_rules())

    def fake_load_dependencies(self):
        load_started.set()
        release_loader.wait(timeout=1.0)
        return SimpleNamespace(
            engine_class=lambda: SimpleNamespace(list_voices=lambda: []),
        )

    def fake_voice_choices(self, engine):
        queue_snapshot["thread_name"] = threading.current_thread().name
        return {
            "voices": ["voice-a"],
            "labels": ["Voice A"],
            "english_index": 0,
            "chinese_index": 0,
        }

    monkeypatch.setattr(controller_module.AppController, "_load_dependencies", fake_load_dependencies)
    monkeypatch.setattr(
        controller_module.AppController,
        "_voice_choices_for_engine",
        fake_voice_choices,
    )

    root = FakeRoot()
    controller = controller_module.AppController(root)

    assert load_started.wait(timeout=1.0)
    assert controller._engine_loading is True
    assert controller.view.status_messages == ["正在加载语音，请稍等..."]
    assert controller.view.playback_states == [False]
    assert controller.view.focused is True
    assert root.after_calls and root.after_calls[0][0] == controller._poll_interval_ms
    assert controller.event_queue.empty()

    release_loader.set()
    deadline = time.time() + 1.0
    while controller.event_queue.empty() and time.time() < deadline:
        time.sleep(0.01)

    queued = list(controller.event_queue.queue)
    assert [event.kind for event in queued] == ["engine_ready"]
    payload = queued[0].payload
    assert payload["labels"] == ["Voice A"]
    assert payload["voices"] == ["voice-a"]
    assert queue_snapshot["thread_name"] == "spell-reader-engine-loader"


def test_handle_queued_engine_ready_applies_voices_and_status(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    captured: dict[str, object] = {}
    controller.view = SimpleNamespace(
        set_voices=lambda english_labels, chinese_labels, english_index, chinese_index: captured.update(
            {
                "english_labels": english_labels,
                "chinese_labels": chinese_labels,
                "english_index": english_index,
                "chinese_index": chinese_index,
            }
        ),
        set_status=lambda message: captured.update({"status": message}),
    )
    controller._engine_loading = True
    controller._dependencies = None
    controller._engine = None
    controller._voices = []

    dependencies = SimpleNamespace()
    engine = SimpleNamespace()

    controller._handle_queued_event(
        controller_module._QueuedEvent(
            "engine_ready",
            {
                "dependencies": dependencies,
                "engine": engine,
                "voices": ["voice-a"],
                "labels": ["Voice A"],
                "english_index": 1,
                "chinese_index": 0,
            },
        )
    )

    assert controller._dependencies is dependencies
    assert controller._engine is engine
    assert controller._voices == ["voice-a"]
    assert controller._engine_loading is False
    assert captured == {
        "english_labels": ["Voice A"],
        "chinese_labels": ["Voice A"],
        "english_index": 1,
        "chinese_index": 0,
        "status": "就绪",
    }


def test_handle_queued_engine_init_error_updates_status(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    statuses: list[str] = []
    errors: list[tuple[str, str]] = []
    controller.view = SimpleNamespace(
        set_status=lambda message: statuses.append(message),
        show_error=lambda title, message: errors.append((title, message)),
    )
    controller._engine_loading = True
    controller._dependencies = object()
    controller._engine = object()

    controller._handle_queued_event(
        controller_module._QueuedEvent("engine_init_error", RuntimeError("voice load failed"))
    )

    assert controller._dependencies is None
    assert controller._engine is None
    assert controller._engine_loading is False
    assert statuses == ["初始化语音引擎失败：voice load failed"]
    assert errors == [("初始化失败", "初始化语音引擎失败：voice load failed")]


def test_ensure_ready_during_loading_sets_status_without_error(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    statuses: list[str] = []
    errors: list[tuple[str, str]] = []
    controller.view = SimpleNamespace(
        set_status=lambda message: statuses.append(message),
        show_error=lambda title, message: errors.append((title, message)),
    )
    controller._dependencies = None
    controller._engine = None
    controller._engine_loading = True

    assert controller._ensure_ready() is False
    assert statuses == ["语音正在加载，请稍等。"]
    assert errors == []


def test_request_stop_returns_quickly_when_stop_blocks(monkeypatch):
    controller_module = importlib.import_module("app.controller")
    controller = controller_module.AppController.__new__(controller_module.AppController)
    controller._stop_requested = threading.Event()
    statuses: list[str] = []
    stop_started = threading.Event()
    release_stop = threading.Event()

    def blocking_stop() -> None:
        stop_started.set()
        release_stop.wait(timeout=1.0)

    controller.view = SimpleNamespace(set_status=lambda message: statuses.append(message))
    controller._engine = SimpleNamespace(stop=blocking_stop)
    controller.event_queue = queue.Queue()

    started_at = time.perf_counter()
    controller._request_stop("正在停止播放...")
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.1
    assert controller._stop_requested.is_set()
    assert statuses == ["正在停止播放..."]
    assert stop_started.wait(timeout=1.0)

    release_stop.set()
