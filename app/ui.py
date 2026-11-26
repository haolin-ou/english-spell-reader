import tkinter as tk
from tkinter import messagebox, ttk

from .timing import MAX_LETTER_PAUSE_LEVEL, clamp_letter_pause_level


READING_MODE_OPTIONS = [
    ("拼+读", "spell_then_read_word"),
    ("读+拼", "read_then_spell"),
    ("读+拼+读", "read_then_spell_then_read"),
    ("单拼", "spell_only"),
    ("单读", "read_only"),
]

NUMBER_MODE_OPTIONS = [
    ("数字逐位读", "digit_by_digit"),
    ("数字整体读", "whole_number"),
]


class RulesDialog:
    def __init__(
        self,
        parent: tk.Tk,
        special_words: list[str],
        custom_symbol_readings: dict[str, str],
        custom_letter_readings: dict[str, str],
        custom_letter_audio_paths: dict[str, str],
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("特殊规则")
        self.window.transient(parent)
        self.window.resizable(True, True)
        self.window.minsize(460, 560)
        self.window.grab_set()

        container = ttk.Frame(self.window, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        container.rowconfigure(3, weight=1)
        container.rowconfigure(5, weight=1)
        container.rowconfigure(7, weight=1)

        ttk.Label(
            container,
            text="特殊单词（每行一个，仅英文单词）",
        ).grid(row=0, column=0, sticky="w")
        self.special_words_text = tk.Text(container, wrap=tk.WORD, height=8)
        self.special_words_text.grid(row=1, column=0, sticky="nsew", pady=(4, 10))
        self.special_words_text.insert("1.0", "\n".join(special_words))

        ttk.Label(
            container,
            text="符号读法（每行一个，格式：symbol=reading）",
        ).grid(row=2, column=0, sticky="w")
        self.symbol_readings_text = tk.Text(container, wrap=tk.WORD, height=8)
        self.symbol_readings_text.grid(row=3, column=0, sticky="nsew", pady=(4, 10))
        lines = [f"{symbol}={reading}" for symbol, reading in custom_symbol_readings.items()]
        self.symbol_readings_text.insert("1.0", "\n".join(lines))

        ttk.Label(
            container,
            text="字母读法（每行一个，格式：P=puh）",
        ).grid(row=4, column=0, sticky="w")
        self.letter_readings_text = tk.Text(container, wrap=tk.WORD, height=6)
        self.letter_readings_text.grid(row=5, column=0, sticky="nsew", pady=(4, 10))
        letter_lines = [
            f"{letter}={reading}" for letter, reading in custom_letter_readings.items()
        ]
        self.letter_readings_text.insert("1.0", "\n".join(letter_lines))

        ttk.Label(
            container,
            text="字母录音（每行一个，格式：P=C:\\path\\p.wav）",
        ).grid(row=6, column=0, sticky="w")
        self.letter_audio_text = tk.Text(container, wrap=tk.WORD, height=5)
        self.letter_audio_text.grid(row=7, column=0, sticky="nsew", pady=(4, 10))
        audio_lines = [
            f"{letter}={audio_path}"
            for letter, audio_path in custom_letter_audio_paths.items()
        ]
        self.letter_audio_text.insert("1.0", "\n".join(audio_lines))

        button_bar = ttk.Frame(container)
        button_bar.grid(row=8, column=0, sticky="e")

        self.save_button = ttk.Button(button_bar, text="保存")
        self.save_button.grid(row=0, column=0, padx=(0, 8))

        self.cancel_button = ttk.Button(button_bar, text="取消")
        self.cancel_button.grid(row=0, column=1)

    def bind_save(self, callback) -> None:
        self.save_button.configure(command=callback)

    def bind_cancel(self, callback) -> None:
        self.cancel_button.configure(command=callback)
        self.window.protocol("WM_DELETE_WINDOW", callback)

    def get_special_words_text(self) -> str:
        return self.special_words_text.get("1.0", tk.END)

    def get_symbol_readings_text(self) -> str:
        return self.symbol_readings_text.get("1.0", tk.END)

    def get_letter_readings_text(self) -> str:
        return self.letter_readings_text.get("1.0", tk.END)

    def get_letter_audio_text(self) -> str:
        return self.letter_audio_text.get("1.0", tk.END)

    def focus(self) -> None:
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def close(self) -> None:
        self.window.grab_release()
        self.window.destroy()


class SpellReaderView:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("English Spell Reader 6.4")
        self.root.geometry("980x540")
        self.root.minsize(900, 480)

        self._reading_mode_var = tk.StringVar(value=READING_MODE_OPTIONS[0][0])
        self._number_mode_var = tk.StringVar(value=NUMBER_MODE_OPTIONS[0][0])
        self._english_voice_var = tk.StringVar()
        self._chinese_voice_var = tk.StringVar()
        self._rate_var = tk.IntVar(value=160)
        self._word_pause_var = tk.IntVar(value=120)
        self._letter_pause_var = tk.IntVar(value=0)
        self._spell_chunk_size_var = tk.IntVar(value=1)
        self._spell_chunk_pause_var = tk.IntVar(value=300)
        self._volume_var = tk.IntVar(value=100)
        self._space_reading_var = tk.BooleanVar(value=False)
        self._status_var = tk.StringVar(value="就绪")
        self._progress_token_var = tk.StringVar(value="正在读：--")
        self._progress_eta_var = tk.StringVar(value="预计剩余：--")
        self._progress_count_var = tk.StringVar(value="0/0 (0%)")
        self._progress_value_var = tk.DoubleVar(value=0.0)
        self._rules_dialog: RulesDialog | None = None
        self._read_marker_tag_configured = False

        self._build_widgets()
        self.set_playback_state(False)
        self.reset_playback_progress()

    def _build_widgets(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(container, text="设置", padding=10)
        controls.grid(row=0, column=0, sticky="ew")
        for column in range(10):
            controls.columnconfigure(column, weight=1)

        ttk.Label(controls, text="朗读模式").grid(row=0, column=0, sticky="w")
        self.reading_mode_combo = ttk.Combobox(
            controls,
            state="readonly",
            textvariable=self._reading_mode_var,
            values=[label for label, _ in READING_MODE_OPTIONS],
        )
        self.reading_mode_combo.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(4, 8))

        ttk.Label(controls, text="数字模式").grid(row=0, column=1, sticky="w")
        self.number_mode_combo = ttk.Combobox(
            controls,
            state="readonly",
            textvariable=self._number_mode_var,
            values=[label for label, _ in NUMBER_MODE_OPTIONS],
        )
        self.number_mode_combo.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(4, 8))

        ttk.Label(controls, text="英文语音").grid(row=0, column=2, sticky="w")
        self.english_voice_combo = ttk.Combobox(
            controls,
            state="readonly",
            textvariable=self._english_voice_var,
        )
        self.english_voice_combo.grid(row=1, column=2, sticky="ew", padx=(0, 8), pady=(4, 8))

        ttk.Label(controls, text="中文语音").grid(row=0, column=3, sticky="w")
        self.chinese_voice_combo = ttk.Combobox(
            controls,
            state="readonly",
            textvariable=self._chinese_voice_var,
        )
        self.chinese_voice_combo.grid(row=1, column=3, sticky="ew", pady=(4, 8))

        ttk.Label(controls, text="朗读语速").grid(row=2, column=0, sticky="w")
        self.rate_scale = ttk.Scale(
            controls,
            from_=80,
            to=260,
            variable=self._rate_var,
            orient=tk.HORIZONTAL,
        )
        self.rate_scale.grid(row=3, column=0, columnspan=2, sticky="ew", padx=(0, 8))
        self.rate_value_label = ttk.Label(controls, textvariable=self._rate_var, width=4)
        self.rate_value_label.grid(row=3, column=2, sticky="w")

        ttk.Label(controls, text="单词间隔ms").grid(row=2, column=3, sticky="w")
        self.word_pause_spinbox = ttk.Spinbox(
            controls,
            from_=0,
            to=5000,
            increment=1,
            textvariable=self._word_pause_var,
            width=8,
        )
        self.word_pause_spinbox.grid(row=3, column=3, sticky="w", padx=(8, 8))

        ttk.Label(controls, text="字母间隔ms").grid(row=2, column=4, sticky="w")
        self.letter_pause_spinbox = ttk.Spinbox(
            controls,
            from_=0,
            to=MAX_LETTER_PAUSE_LEVEL,
            increment=1,
            textvariable=self._letter_pause_var,
            width=8,
        )
        self.letter_pause_spinbox.grid(row=3, column=4, sticky="w", padx=(0, 8))

        ttk.Label(controls, text="单拼拆解").grid(row=2, column=5, sticky="w")
        self.spell_chunk_size_spinbox = ttk.Spinbox(
            controls,
            from_=1,
            to=10,
            increment=1,
            textvariable=self._spell_chunk_size_var,
            width=8,
        )
        self.spell_chunk_size_spinbox.grid(row=3, column=5, sticky="w", padx=(8, 8))

        ttk.Label(controls, text="拆解间隔ms").grid(row=2, column=6, sticky="w")
        self.spell_chunk_pause_spinbox = ttk.Spinbox(
            controls,
            from_=0,
            to=5000,
            increment=1,
            textvariable=self._spell_chunk_pause_var,
            width=8,
        )
        self.spell_chunk_pause_spinbox.grid(row=3, column=6, sticky="w", padx=(0, 8))

        self.space_reading_button = ttk.Checkbutton(
            controls,
            text="空格朗读",
            variable=self._space_reading_var,
        )
        self.space_reading_button.grid(row=3, column=7, sticky="w", padx=(8, 8))

        ttk.Label(controls, text="音量").grid(row=2, column=8, sticky="w")
        self.volume_scale = ttk.Scale(
            controls,
            from_=0,
            to=100,
            variable=self._volume_var,
            orient=tk.HORIZONTAL,
        )
        self.volume_scale.grid(row=3, column=8, sticky="ew", pady=(0, 6))
        self.volume_value_label = ttk.Label(controls, textvariable=self._volume_var, width=4)
        self.volume_value_label.grid(row=3, column=9, sticky="w")

        text_frame = ttk.LabelFrame(container, text="输入文本", padding=10)
        text_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 12))
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        self.text_input = tk.Text(text_frame, wrap=tk.WORD, undo=True, height=12)
        self.text_input.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.text_input.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text_input.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(container)
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=0)
        footer.rowconfigure(1, weight=0)

        self.status_label = ttk.Label(
            footer,
            textvariable=self._status_var,
            anchor="w",
            relief=tk.SUNKEN,
            padding=(8, 4),
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        button_bar = ttk.Frame(footer)
        button_bar.grid(row=0, column=1, sticky="e")

        self.play_button = ttk.Button(button_bar, text="播放")
        self.play_button.grid(row=0, column=0, padx=(0, 8))

        self.pause_button = ttk.Button(button_bar, text="暂停")
        self.pause_button.grid(row=0, column=1, padx=(0, 8))

        self.stop_button = ttk.Button(button_bar, text="停止")
        self.stop_button.grid(row=0, column=2, padx=(0, 8))

        self.clear_button = ttk.Button(button_bar, text="清空")
        self.clear_button.grid(row=0, column=3, padx=(0, 8))

        self.save_settings_button = ttk.Button(button_bar, text="保存设置")
        self.save_settings_button.grid(row=0, column=4, padx=(0, 8))

        self.rules_button = ttk.Button(button_bar, text="特殊规则")
        self.rules_button.grid(row=0, column=5)

        progress_frame = ttk.Frame(footer)
        progress_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        progress_frame.columnconfigure(0, weight=1)
        progress_frame.columnconfigure(1, weight=0)

        self.playback_progress_bar = ttk.Progressbar(
            progress_frame,
            mode="determinate",
            maximum=100.0,
            variable=self._progress_value_var,
        )
        self.playback_progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 12))

        progress_meta = ttk.Frame(progress_frame)
        progress_meta.grid(row=0, column=1, sticky="e")

        self.playback_token_label = ttk.Label(
            progress_meta,
            textvariable=self._progress_token_var,
            width=24,
            anchor="w",
        )
        self.playback_token_label.grid(row=0, column=0, padx=(0, 12), sticky="w")

        self.playback_eta_label = ttk.Label(
            progress_meta,
            textvariable=self._progress_eta_var,
            width=16,
            anchor="w",
        )
        self.playback_eta_label.grid(row=0, column=1, padx=(0, 12), sticky="w")

        self.playback_count_label = ttk.Label(
            progress_meta,
            textvariable=self._progress_count_var,
            width=14,
            anchor="e",
        )
        self.playback_count_label.grid(row=0, column=2, sticky="e")

    def bind_play(self, callback) -> None:
        self.play_button.configure(command=callback)

    def bind_stop(self, callback) -> None:
        self.stop_button.configure(command=callback)

    def bind_pause(self, callback) -> None:
        self.pause_button.configure(command=callback)

    def bind_clear(self, callback) -> None:
        self.clear_button.configure(command=callback)

    def bind_rules(self, callback) -> None:
        self.rules_button.configure(command=callback)

    def bind_save_settings(self, callback) -> None:
        self.save_settings_button.configure(command=callback)

    def bind_space_reading_toggle(self, callback) -> None:
        self.space_reading_button.configure(command=callback)

    def bind_close(self, callback) -> None:
        self.root.protocol("WM_DELETE_WINDOW", callback)

    def get_text(self) -> str:
        return self.text_input.get("1.0", tk.END)

    def clear_text(self) -> None:
        self.text_input.delete("1.0", tk.END)

    def focus_text(self) -> None:
        self.text_input.focus_set()

    def get_selected_reading_mode(self) -> str:
        return self._map_label_to_value(self._reading_mode_var.get(), READING_MODE_OPTIONS)

    def get_selected_number_mode(self) -> str:
        return self._map_label_to_value(self._number_mode_var.get(), NUMBER_MODE_OPTIONS)

    def get_selected_english_voice_index(self) -> int:
        return self._safe_combobox_index(self.english_voice_combo)

    def get_selected_chinese_voice_index(self) -> int:
        return self._safe_combobox_index(self.chinese_voice_combo)

    def get_rate(self) -> int:
        return int(round(self._rate_var.get()))

    def get_word_pause_ms(self) -> int:
        return self._clamp_word_pause_ms(self._word_pause_var.get())

    def get_letter_pause_ms(self) -> int:
        return self._clamp_letter_pause_ms(self._letter_pause_var.get())

    def get_spell_chunk_size(self) -> int:
        return self._clamp_spell_chunk_size(self._spell_chunk_size_var.get())

    def get_spell_chunk_pause_ms(self) -> int:
        return self._clamp_spell_chunk_pause_ms(self._spell_chunk_pause_var.get())

    def get_volume(self) -> int:
        return int(round(self._volume_var.get()))

    def is_space_reading_enabled(self) -> bool:
        return bool(self._space_reading_var.get())

    def set_word_pause_ms(self, value: int) -> None:
        self._word_pause_var.set(self._clamp_word_pause_ms(value))

    def set_letter_pause_ms(self, value: int) -> None:
        self._letter_pause_var.set(self._clamp_letter_pause_ms(value))

    def set_spell_chunk_size(self, value: int) -> None:
        self._spell_chunk_size_var.set(self._clamp_spell_chunk_size(value))

    def set_spell_chunk_pause_ms(self, value: int) -> None:
        self._spell_chunk_pause_var.set(self._clamp_spell_chunk_pause_ms(value))

    def set_selected_reading_mode(self, value: str) -> None:
        self._reading_mode_var.set(self._map_value_to_label(value, READING_MODE_OPTIONS))

    def set_selected_number_mode(self, value: str) -> None:
        self._number_mode_var.set(self._map_value_to_label(value, NUMBER_MODE_OPTIONS))

    def set_rate(self, value: int) -> None:
        self._rate_var.set(max(80, min(260, int(round(value)))))

    def set_volume(self, value: int) -> None:
        self._volume_var.set(max(0, min(100, int(round(value)))))

    def set_space_reading_enabled(self, enabled: bool) -> None:
        self._space_reading_var.set(bool(enabled))

    def set_voices(
        self,
        english_labels: list[str],
        chinese_labels: list[str],
        english_index: int = 0,
        chinese_index: int = 0,
    ) -> None:
        self.english_voice_combo.configure(values=english_labels)
        self.chinese_voice_combo.configure(values=chinese_labels)

        if english_labels:
            self.english_voice_combo.current(max(0, min(english_index, len(english_labels) - 1)))
        else:
            self._english_voice_var.set("")

        if chinese_labels:
            self.chinese_voice_combo.current(max(0, min(chinese_index, len(chinese_labels) - 1)))
        else:
            self._chinese_voice_var.set("")

    def set_status(self, message: str) -> None:
        self._status_var.set(message)

    def set_playback_state(self, is_playing: bool) -> None:
        self.play_button.configure(state=tk.DISABLED if is_playing else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if is_playing else tk.DISABLED)
        self.pause_button.configure(state=tk.NORMAL if is_playing else tk.DISABLED)

    def set_playback_progress(
        self,
        completed_units: int,
        total_units: int,
        *,
        token: str = "",
        eta_seconds: float | int | None = None,
        state: str = "playing",
    ) -> None:
        safe_total = max(0, int(total_units))
        safe_completed = max(0, int(completed_units))
        if safe_total > 0:
            safe_completed = min(safe_completed, safe_total)

        percent = 0
        if safe_total > 0:
            percent = int(round((safe_completed / safe_total) * 100))
        clamped_percent = max(0, min(100, percent))

        state_label = self._format_progress_token_label(token)
        if state == "paused" and token:
            state_label = f"已暂停：{token}"
        elif state == "paused":
            state_label = "已暂停：--"
        elif state in {"stopped", "idle", "reset"}:
            state_label = "正在读：--"
        elif state in {"finished", "done", "completed"} and not token and safe_total > 0:
            state_label = "正在读：完成"

        self._progress_value_var.set(float(clamped_percent))
        self._progress_token_var.set(state_label)
        self._progress_eta_var.set(self._format_eta_label(eta_seconds))
        self._progress_count_var.set(
            f"{safe_completed}/{safe_total} ({clamped_percent}%)"
        )

    def reset_playback_progress(self) -> None:
        self._progress_value_var.set(0.0)
        self._progress_token_var.set("正在读：--")
        self._progress_eta_var.set("预计剩余：--")
        self._progress_count_var.set("0/0 (0%)")
        self.clear_read_markers()

    def mark_text_read_until(self, char_offset: int) -> None:
        try:
            offset = max(0, int(char_offset))
        except (TypeError, ValueError):
            return
        self._ensure_read_marker_tag()
        self.text_input.tag_remove("read_text", "1.0", "end")
        if offset <= 0:
            return
        self.text_input.tag_add("read_text", "1.0", f"1.0+{offset}c")

    def clear_read_markers(self) -> None:
        if not hasattr(self, "text_input"):
            return
        self.text_input.tag_remove("read_text", "1.0", "end")

    def _ensure_read_marker_tag(self) -> None:
        if self._read_marker_tag_configured:
            return
        self.text_input.tag_configure("read_text", background="#d9f2df")
        self._read_marker_tag_configured = True

    def show_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self.root)

    def open_rules_dialog(
        self,
        special_words: list[str],
        custom_symbol_readings: dict[str, str],
        custom_letter_readings: dict[str, str],
        custom_letter_audio_paths: dict[str, str],
    ) -> RulesDialog:
        if self._rules_dialog is not None:
            self._rules_dialog.focus()
            return self._rules_dialog

        dialog = RulesDialog(
            self.root,
            special_words=special_words,
            custom_symbol_readings=custom_symbol_readings,
            custom_letter_readings=custom_letter_readings,
            custom_letter_audio_paths=custom_letter_audio_paths,
        )
        self._rules_dialog = dialog
        return dialog

    def close_rules_dialog(self) -> None:
        if self._rules_dialog is None:
            return
        dialog = self._rules_dialog
        self._rules_dialog = None
        dialog.close()

    def _map_label_to_value(self, selected_label: str, options: list[tuple[str, str]]) -> str:
        for label, value in options:
            if label == selected_label:
                return value
        return options[0][1]

    def _map_value_to_label(self, selected_value: str, options: list[tuple[str, str]]) -> str:
        for label, value in options:
            if value == selected_value:
                return label
        return options[0][0]

    def _safe_combobox_index(self, combobox: ttk.Combobox) -> int:
        index = combobox.current()
        return index if index >= 0 else 0

    def _clamp_word_pause_ms(self, value: object) -> int:
        try:
            pause_ms = int(round(float(value)))
        except (TypeError, ValueError):
            pause_ms = 120
        return max(0, min(5000, pause_ms))

    def _clamp_letter_pause_ms(self, value: object) -> int:
        return clamp_letter_pause_level(value)

    def _clamp_spell_chunk_size(self, value: object) -> int:
        try:
            chunk_size = int(round(float(value)))
        except (TypeError, ValueError):
            chunk_size = 1
        return max(1, min(10, chunk_size))

    def _clamp_spell_chunk_pause_ms(self, value: object) -> int:
        try:
            pause_ms = int(round(float(value)))
        except (TypeError, ValueError):
            pause_ms = 300
        return max(0, min(5000, pause_ms))

    def _format_progress_token_label(self, token: str) -> str:
        cleaned = token.strip()
        if not cleaned:
            return "正在读：--"
        return f"正在读：{cleaned}"

    def _format_eta_label(self, eta_seconds: float | int | None) -> str:
        if eta_seconds is None:
            return "预计剩余：--"

        try:
            total_seconds = max(0, int(round(float(eta_seconds))))
        except (TypeError, ValueError):
            return "预计剩余：--"

        minutes, seconds = divmod(total_seconds, 60)
        if minutes > 0:
            eta_text = f"{minutes}分{seconds:02d}秒"
        else:
            eta_text = f"{seconds}秒"
        return f"预计剩余：{eta_text}"
