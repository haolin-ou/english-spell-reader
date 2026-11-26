from __future__ import annotations

import importlib
import inspect
import sys
import types


def _fake_tkinter_module() -> types.ModuleType:
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
    return fake_tkinter


def test_importing_app_main_does_not_initialize_pyttsx3(monkeypatch):
    called = False

    def fail_init(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("pyttsx3.init must not run during import")

    fake_pyttsx3 = types.SimpleNamespace(init=fail_init)
    monkeypatch.setitem(sys.modules, "pyttsx3", fake_pyttsx3)
    fake_tkinter = _fake_tkinter_module()
    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_tkinter.ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", fake_tkinter.messagebox)
    for module_name in ("app.main", "app.controller", "app.ui", "app"):
        sys.modules.pop(module_name, None)

    module = importlib.import_module("app.main")

    assert module is not None
    assert hasattr(module, "main"), "app.main must expose a `main` entry point"
    assert callable(module.main), "`main` must be callable"
    assert called is False


def test_importing_app_ui_exposes_expected_reading_mode_options(monkeypatch):
    fake_tkinter = _fake_tkinter_module()
    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_tkinter.ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", fake_tkinter.messagebox)
    sys.modules.pop("app.ui", None)

    module = importlib.import_module("app.ui")

    assert module.READING_MODE_OPTIONS == [
        ("拼+读", "spell_then_read_word"),
        ("读+拼", "read_then_spell"),
        ("读+拼+读", "read_then_spell_then_read"),
        ("单拼", "spell_only"),
        ("单读", "read_only"),
    ]
    assert hasattr(module.SpellReaderView, "bind_save_settings")
    assert hasattr(module.SpellReaderView, "set_selected_reading_mode")
    assert hasattr(module.SpellReaderView, "set_selected_number_mode")
    assert hasattr(module.SpellReaderView, "set_rate")
    assert hasattr(module.SpellReaderView, "set_volume")
    assert list(inspect.signature(module.SpellReaderView.open_rules_dialog).parameters) == [
        "self",
        "special_words",
        "custom_symbol_readings",
        "custom_letter_readings",
        "custom_letter_audio_paths",
    ]
