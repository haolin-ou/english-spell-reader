from __future__ import annotations

import importlib
import sys
import types

import pytest


def _load_ui_module(monkeypatch):
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
    fake_tkinter.BooleanVar = dummy_widget
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
    fake_ttk.Checkbutton = dummy_widget
    fake_messagebox.showerror = lambda *args, **kwargs: None
    fake_tkinter.ttk = fake_ttk
    fake_tkinter.messagebox = fake_messagebox

    sys.modules.pop("app.ui", None)
    monkeypatch.setitem(sys.modules, "tkinter", fake_tkinter)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", fake_ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", fake_messagebox)

    return importlib.import_module("app.ui")


class _RecordingWidget:
    instances: list["_RecordingWidget"] = []

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.grid_calls: list[dict[str, object]] = []
        self.configure_calls: list[dict[str, object]] = []
        _RecordingWidget.instances.append(self)

    def grid(self, **kwargs) -> None:
        self.grid_calls.append(kwargs)

    def configure(self, **kwargs) -> None:
        self.configure_calls.append(kwargs)

    def columnconfigure(self, *args, **kwargs) -> None:
        pass

    def rowconfigure(self, *args, **kwargs) -> None:
        pass

    def pack(self, *args, **kwargs) -> None:
        pass

    def bind(self, *args, **kwargs) -> None:
        pass

    def tag_configure(self, *args, **kwargs) -> None:
        pass

    def tag_remove(self, *args, **kwargs) -> None:
        pass

    def protocol(self, *args, **kwargs) -> None:
        pass

    def title(self, *args, **kwargs) -> None:
        pass

    def geometry(self, *args, **kwargs) -> None:
        pass

    def minsize(self, *args, **kwargs) -> None:
        pass

    def focus_set(self) -> None:
        pass

    def yview(self, *args, **kwargs) -> None:
        pass

    def set(self, *args, **kwargs) -> None:
        pass


class _RecordingVar:
    def __init__(self, value=None, *args, **kwargs) -> None:
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


def test_space_reading_checkbox_is_visible_with_main_controls(monkeypatch):
    ui_module = _load_ui_module(monkeypatch)
    _RecordingWidget.instances = []
    ui_module.tk.Text = _RecordingWidget
    ui_module.tk.StringVar = _RecordingVar
    ui_module.tk.IntVar = _RecordingVar
    ui_module.tk.DoubleVar = _RecordingVar
    ui_module.tk.BooleanVar = _RecordingVar
    ui_module.ttk.Frame = _RecordingWidget
    ui_module.ttk.LabelFrame = _RecordingWidget
    ui_module.ttk.Label = _RecordingWidget
    ui_module.ttk.Combobox = _RecordingWidget
    ui_module.ttk.Scale = _RecordingWidget
    ui_module.ttk.Button = _RecordingWidget
    ui_module.ttk.Scrollbar = _RecordingWidget
    ui_module.ttk.Spinbox = _RecordingWidget
    ui_module.ttk.Progressbar = _RecordingWidget
    ui_module.ttk.Checkbutton = _RecordingWidget

    root = _RecordingWidget()
    view = ui_module.SpellReaderView(root)

    assert view.space_reading_button.kwargs["text"] == "空格朗读"
    assert view.space_reading_button.grid_calls[-1]["row"] == 3
    assert view.spell_chunk_size_spinbox.grid_calls[-1]["row"] == 3
    assert view.spell_chunk_size_spinbox.grid_calls[-1]["column"] == 5
    assert view.spell_chunk_pause_spinbox.grid_calls[-1]["row"] == 3
    assert view.spell_chunk_pause_spinbox.grid_calls[-1]["column"] == 6
    assert view.space_reading_button.grid_calls[-1]["column"] == 7


@pytest.mark.parametrize(
    ("eta_seconds", "expected"),
    [
        (65, "预计剩余：1分05秒"),
        (5, "预计剩余：5秒"),
    ],
)
def test_eta_label_uses_chinese_minute_second_format(monkeypatch, eta_seconds, expected):
    ui_module = _load_ui_module(monkeypatch)
    view = ui_module.SpellReaderView.__new__(ui_module.SpellReaderView)

    assert view._format_eta_label(eta_seconds) == expected
