import importlib
import inspect
import queue
import threading
import time
from dataclasses import dataclass, fields, replace
from types import SimpleNamespace
from typing import Any

from .settings import ReaderRules, load_rules, save_rules
from .timing import (
    MAX_LETTER_PAUSE_LEVEL,
    clamp_letter_pause_level,
    resolve_letter_pause_ms,
)
from .ui import SpellReaderView


@dataclass
class _DependencyBundle:
    build_speech_plan: Any
    ParseOptions: Any
    ReadingMode: Any
    NumberMode: Any
    WhitespaceMode: Any
    engine_class: Any
    VoiceSelection: Any
    PlaybackSettings: Any
    PlaybackEventType: Any


@dataclass
class _QueuedEvent:
    kind: str
    payload: Any = None


class _RoutedSpeechEngine:
    """Expose SAPI, Piper, and Microsoft voices while keeping SAPI as the safe default."""

    def __init__(
        self,
        fallback_engine_class: Any,
        piper_engine_class: Any,
        edge_engine_class: Any = None,
    ) -> None:
        self._fallback_engine = fallback_engine_class() if fallback_engine_class is not None else None
        self._piper_engine = None
        self._edge_engine = None
        self._piper_error: Exception | None = None
        self._edge_error: Exception | None = None
        self._session_engines: dict[int, Any] = {}
        self._active_engine: Any = None
        self._active_session_id: int | None = None
        if piper_engine_class is not None:
            try:
                self._piper_engine = piper_engine_class()
            except Exception as exc:
                self._piper_error = exc
        if edge_engine_class is not None:
            try:
                self._edge_engine = edge_engine_class()
            except Exception as exc:
                self._edge_error = exc
        if self._fallback_engine is None and self._piper_engine is None and self._edge_engine is None:
            if self._piper_error is not None:
                raise self._piper_error
            if self._edge_error is not None:
                raise self._edge_error
            raise RuntimeError("No speech engine is available.")

    def list_voices(self) -> list[Any]:
        voices: list[Any] = []
        errors: list[Exception] = []
        for engine in (self._fallback_engine, self._piper_engine, self._edge_engine):
            if engine is None:
                continue
            try:
                voices.extend(list(engine.list_voices() or []))
            except Exception as exc:
                errors.append(exc)
        if voices:
            return voices
        if errors:
            raise errors[0]
        return []

    def play(self, plan: Any, settings: Any, on_event: Any = None) -> Any:
        engine = self._engine_for_settings(settings)
        self._active_engine = engine
        try:
            session = engine.play(plan, settings, on_event=on_event)
            fallback = self._fallback_session_for_error(
                engine,
                session,
                plan,
                settings,
                on_event,
            )
            if fallback is not None:
                engine, session = fallback
        except Exception:
            if self._active_engine is engine:
                self._active_engine = None
                self._active_session_id = None
            raise
        self._session_engines[id(session)] = engine
        self._active_session_id = id(session)
        return session

    def wait_until_finished(self, session: Any, timeout: float | None = None) -> Any:
        engine = self._session_engines.get(id(session))
        wait_until_finished = getattr(engine, "wait_until_finished", None)
        try:
            if callable(wait_until_finished):
                return wait_until_finished(session, timeout=timeout)
            return getattr(session, "state", None)
        finally:
            if self._active_session_id == id(session):
                self._active_engine = None
                self._active_session_id = None

    def stop(self) -> None:
        engines: list[Any] = []
        if self._active_engine is not None:
            engines.append(self._active_engine)
        for engine in (self._fallback_engine, self._piper_engine, self._edge_engine):
            stop = getattr(engine, "stop", None)
            if engine is not None and engine not in engines and callable(stop):
                engines.append(engine)
        for engine in engines:
            stop = getattr(engine, "stop", None)
            if callable(stop):
                stop()

    def shutdown(self) -> None:
        for engine in (self._fallback_engine, self._piper_engine, self._edge_engine):
            shutdown = getattr(engine, "shutdown", None)
            if callable(shutdown):
                shutdown()

    def _engine_for_settings(self, settings: Any) -> Any:
        if self._settings_request_edge(settings) and self._edge_engine is not None:
            return self._edge_engine
        if self._settings_request_piper(settings) and self._piper_engine is not None:
            return self._piper_engine
        if self._fallback_engine is not None:
            return self._fallback_engine
        if self._edge_engine is not None:
            return self._edge_engine
        if self._piper_engine is not None:
            return self._piper_engine
        if self._edge_error is not None:
            raise self._edge_error
        if self._piper_error is not None:
            raise self._piper_error
        raise RuntimeError("No speech engine is available.")

    def _fallback_session_for_error(
        self,
        failed_engine: Any,
        session: Any,
        plan: Any,
        settings: Any,
        on_event: Any,
    ) -> tuple[Any, Any] | None:
        if self._session_state_name(getattr(session, "state", None)) != "error":
            return None

        for engine, voice_id in self._fallback_engines_for_failed_engine(failed_engine):
            fallback_settings = self._settings_with_voice_ids(
                settings,
                english_voice_id=voice_id,
                chinese_voice_id=None,
            )
            fallback_session = engine.play(plan, fallback_settings, on_event=on_event)
            if self._session_state_name(getattr(fallback_session, "state", None)) != "error":
                return engine, fallback_session
        return None

    def _fallback_engines_for_failed_engine(self, failed_engine: Any) -> list[tuple[Any, str | None]]:
        candidates: list[tuple[Any, str | None]] = []
        if failed_engine is self._piper_engine:
            if self._edge_engine is not None:
                candidates.append((self._edge_engine, self._first_voice_id(self._edge_engine)))
            if self._fallback_engine is not None:
                candidates.append((self._fallback_engine, None))
        elif failed_engine is self._edge_engine:
            if self._fallback_engine is not None:
                candidates.append((self._fallback_engine, None))
            if self._piper_engine is not None:
                candidates.append((self._piper_engine, self._first_voice_id(self._piper_engine)))
        return [(engine, voice_id) for engine, voice_id in candidates if engine is not failed_engine]

    def _first_voice_id(self, engine: Any) -> str | None:
        try:
            voices = list(engine.list_voices() or [])
        except Exception:
            return None
        for voice in voices:
            voice_id = getattr(voice, "id", None)
            if isinstance(voice_id, str) and voice_id.strip():
                return voice_id.strip()
        return None

    def _settings_with_voice_ids(
        self,
        settings: Any,
        *,
        english_voice_id: str | None,
        chinese_voice_id: str | None,
    ) -> Any:
        voices = SimpleNamespace(
            english_voice_id=english_voice_id,
            chinese_voice_id=chinese_voice_id,
        )
        return SimpleNamespace(
            voices=voices,
            voice_selection=voices,
            rate=getattr(settings, "rate", 200),
            volume=getattr(settings, "volume", 1.0),
        )

    def _session_state_name(self, state: Any) -> str:
        raw_value = getattr(state, "value", state)
        if raw_value is None:
            return ""
        return str(raw_value).strip().lower()

    def _settings_request_piper(self, settings: Any) -> bool:
        return self._settings_request_voice_prefix(settings, "piper:")

    def _settings_request_edge(self, settings: Any) -> bool:
        return self._settings_request_voice_prefix(settings, "edge:")

    def _settings_request_voice_prefix(self, settings: Any, prefix: str) -> bool:
        selection = getattr(settings, "voice_selection", None)
        if selection is None:
            selection = getattr(settings, "voices", None)
        if selection is None:
            return False
        for attr in ("english_voice_id", "english_id", "chinese_voice_id", "chinese_id"):
            voice_id = getattr(selection, attr, None)
            if isinstance(voice_id, str) and voice_id.startswith(prefix):
                return True
        return False


def _parse_rules_text(
    special_words_text: str,
    symbol_readings_text: str,
    word_pause_ms: int,
    letter_pause_ms: int,
    space_behavior: str,
    custom_letter_pause_ms: object = None,
    *,
    letter_readings_text: str = "",
    letter_audio_text: str = "",
) -> ReaderRules:
    special_words: set[str] = set()
    for line_number, raw_line in enumerate(special_words_text.splitlines(), start=1):
        word = raw_line.strip()
        if not word:
            continue
        if not word.isascii() or not word.isalpha():
            raise ValueError(f"特殊单词第 {line_number} 行必须只包含英文字母。")
        special_words.add(word.lower())

    custom_symbol_readings: dict[str, str] = {}
    for line_number, raw_line in enumerate(symbol_readings_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.count("=") != 1:
            raise ValueError(f"符号读法第 {line_number} 行必须使用 symbol=reading 格式。")
        symbol, reading = (part.strip() for part in line.split("=", 1))
        if not symbol or not reading:
            raise ValueError(f"符号读法第 {line_number} 行左右两侧都不能为空。")
        if len(symbol) != 1:
            raise ValueError(f"符号左侧第 {line_number} 行只能填写一个字符。")
        custom_symbol_readings[symbol] = reading

    custom_letter_readings: dict[str, str] = {}
    for line_number, raw_line in enumerate(letter_readings_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.count("=") != 1:
            raise ValueError(f"字母读法第 {line_number} 行必须使用 letter=reading 格式。")
        letter, reading = (part.strip() for part in line.split("=", 1))
        normalized_letter = letter.upper()
        if (
            len(normalized_letter) != 1
            or not normalized_letter.isascii()
            or not normalized_letter.isalpha()
        ):
            raise ValueError(f"字母读法第 {line_number} 行左侧必须是一个英文字母。")
        if not reading:
            raise ValueError(f"字母读法第 {line_number} 行右侧不能为空。")
        custom_letter_readings[normalized_letter] = reading

    custom_letter_audio_paths: dict[str, str] = {}
    for line_number, raw_line in enumerate(letter_audio_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line.count("=") != 1:
            raise ValueError(f"字母录音第 {line_number} 行必须使用 letter=path.wav 格式。")
        letter, audio_path = (part.strip() for part in line.split("=", 1))
        normalized_letter = letter.upper()
        if (
            len(normalized_letter) != 1
            or not normalized_letter.isascii()
            or not normalized_letter.isalpha()
        ):
            raise ValueError(f"字母录音第 {line_number} 行左侧必须是一个英文字母。")
        if not audio_path:
            raise ValueError(f"字母录音第 {line_number} 行右侧不能为空。")
        if not audio_path.lower().endswith(".wav"):
            raise ValueError(f"字母录音第 {line_number} 行目前只支持 .wav 文件。")
        custom_letter_audio_paths[normalized_letter] = audio_path

    try:
        pause_ms = int(word_pause_ms)
    except (TypeError, ValueError) as exc:
        raise ValueError("词间停顿必须是整数毫秒。") from exc
    if pause_ms < 0 or pause_ms > 5000:
        raise ValueError("词间停顿必须在 0 到 5000 毫秒之间。")

    try:
        letter_level = int(letter_pause_ms)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"字母间隔必须是 0 到 {MAX_LETTER_PAUSE_LEVEL} 的整数毫秒。"
        ) from exc
    if letter_level < 0 or letter_level > MAX_LETTER_PAUSE_LEVEL:
        raise ValueError(f"字母间隔必须在 0 到 {MAX_LETTER_PAUSE_LEVEL} 毫秒之间。")
    normalized_space_behavior = _normalize_space_behavior(space_behavior)

    return _build_reader_rules(
        special_words=frozenset(special_words),
        custom_symbol_readings=custom_symbol_readings,
        custom_letter_readings=custom_letter_readings,
        custom_letter_audio_paths=custom_letter_audio_paths,
        word_pause_ms=pause_ms,
        letter_pause_ms=letter_level,
        spell_chunk_pause_ms=300,
        custom_letter_pause_ms=None,
        space_behavior=normalized_space_behavior,
    )


def _reader_rules_supports_space_behavior() -> bool:
    return "space_behavior" in {field.name for field in fields(ReaderRules)}


def _build_reader_rules(
    *,
    special_words: frozenset[str],
    custom_symbol_readings: dict[str, str],
    custom_letter_readings: dict[str, str],
    custom_letter_audio_paths: dict[str, str],
    word_pause_ms: int,
    letter_pause_ms: int,
    spell_chunk_pause_ms: int,
    custom_letter_pause_ms: int | None,
    space_behavior: str,
) -> ReaderRules:
    kwargs: dict[str, Any] = {
        "special_words": special_words,
        "custom_symbol_readings": custom_symbol_readings,
        "custom_letter_readings": custom_letter_readings,
        "custom_letter_audio_paths": custom_letter_audio_paths,
        "word_pause_ms": word_pause_ms,
        "letter_pause_ms": letter_pause_ms,
        "spell_chunk_pause_ms": spell_chunk_pause_ms,
        "custom_letter_pause_ms": custom_letter_pause_ms,
    }
    if _reader_rules_supports_space_behavior():
        kwargs["space_behavior"] = space_behavior
    return ReaderRules(**kwargs)


def _normalize_space_behavior(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"pause", "read_space", "read_blank"}:
        return normalized
    raise ValueError("空白处理方式无效。")


class AppController:
    def __init__(self, root) -> None:
        self.root = root
        self.view = SpellReaderView(root)
        self.event_queue: queue.Queue[_QueuedEvent] = queue.Queue()
        self._poll_interval_ms = 100
        self._play_thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._is_playing = False
        self._closing = False
        self._voices: list[Any] = []
        self._dependencies: _DependencyBundle | None = None
        self._engine: Any = None
        self._engine_loading = False
        self._rules = load_rules()
        self._space_behavior = getattr(self._rules, "space_behavior", "pause")
        self._pause_requested = False
        self._paused_text: str | None = None
        self._current_playback_text: str | None = None
        self._resume_unit_index = 0
        self._last_finished_unit_index = -1
        self._progress_lock = threading.Lock()
        self._playback_total_units = 0
        self._playback_completed_units = 0
        self._playback_unit_base_index = 0
        self._playback_started_at: float | None = None
        self._playback_last_token = ""
        self._playback_unit_estimates: list[float] = []
        self._playback_read_until = 0

        self.view.bind_play(self.handle_play)
        self.view.bind_stop(self.handle_stop)
        self.view.bind_pause(self.handle_pause)
        self.view.bind_clear(self.handle_clear)
        self.view.bind_rules(self.handle_rules)
        bind_save_settings = getattr(self.view, "bind_save_settings", None)
        if callable(bind_save_settings):
            bind_save_settings(self.handle_save_settings)
        self.view.bind_space_reading_toggle(self.handle_space_reading_toggle)
        self.view.bind_close(self.handle_close)
        self._restore_main_settings_from_rules()
        self.view.set_playback_state(False)
        self.view.focus_text()

        self._initialize_engine()
        self._schedule_poll()

    def handle_play(self) -> None:
        if self._is_playing:
            return

        if not self._ensure_ready():
            return

        text = self.view.get_text()
        if not text.strip():
            self.view.set_status("请输入要朗读的文本。")
            self._reset_playback_progress_view()
            return

        is_resume = False
        with self._progress_lock:
            if self._paused_text != text:
                self._clear_resume_state_locked()
                self._clear_progress_state_locked()
            else:
                is_resume = self._resume_unit_index > 0
            self._current_playback_text = text
            self._pause_requested = False
            self._last_finished_unit_index = self._resume_unit_index - 1
        if not is_resume:
            self._reset_playback_progress_view()
        self._stop_requested.clear()
        self._set_playing(True)
        if self._resume_unit_index > 0:
            self.view.set_status("正在继续朗读...")
        else:
            self.view.set_status("正在准备朗读...")

        self._play_thread = threading.Thread(
            target=self._playback_worker,
            args=(text,),
            daemon=True,
            name="spell-reader-playback",
        )
        self._play_thread.start()

    def handle_stop(self) -> None:
        self._reset_resume_state()
        self._reset_progress_state()
        self._reset_playback_progress_view()
        if not self._is_playing:
            self.view.set_status("当前没有正在播放的内容。")
            return

        self._request_stop("正在停止播放...")

    def handle_pause(self) -> None:
        if not self._is_playing:
            self.view.set_status("当前没有正在播放的内容。")
            return

        with self._progress_lock:
            self._pause_requested = True
            if self._current_playback_text is not None:
                self._paused_text = self._current_playback_text
            self._resume_unit_index = max(
                self._resume_unit_index,
                self._last_finished_unit_index + 1,
            )
        self._request_stop("正在暂停播放...")

    def handle_clear(self) -> None:
        self._reset_resume_state()
        self._reset_progress_state()
        self._reset_playback_progress_view()
        if self._is_playing:
            self._request_stop("正在停止播放并清空文本...")
        self.view.clear_text()
        self.view.set_status("文本已清空。")
        self.view.focus_text()

    def handle_rules(self) -> None:
        dialog = self.view.open_rules_dialog(
            special_words=sorted(self._rules.special_words),
            custom_symbol_readings=dict(sorted(self._rules.custom_symbol_readings.items())),
            custom_letter_readings=dict(sorted(self._rules.custom_letter_readings.items())),
            custom_letter_audio_paths=dict(
                sorted(getattr(self._rules, "custom_letter_audio_paths", {}).items())
            ),
        )
        dialog.bind_save(lambda: self._save_rules_from_dialog(dialog))
        dialog.bind_cancel(self.view.close_rules_dialog)

    def handle_save_settings(self) -> None:
        rules = self._rules_from_current_main_settings()
        try:
            save_rules(rules)
        except Exception as exc:
            message = f"保存设置失败：{exc}"
            self.view.set_status(message)
            self.view.show_error("保存失败", message)
            return

        self._rules = rules
        self._space_behavior = getattr(rules, "space_behavior", self._space_behavior)
        self.view.set_status("设置已保存。")

    def handle_space_reading_toggle(self) -> None:
        is_enabled = bool(self.view.is_space_reading_enabled())
        space_behavior = "read_space" if is_enabled else "pause"
        rules = replace(
            self._rules,
            word_pause_ms=self._get_current_word_pause_ms(),
            letter_pause_ms=self._get_current_letter_pause_ms(),
            spell_chunk_size=self._get_current_spell_chunk_size(),
            spell_chunk_pause_ms=self._get_current_spell_chunk_pause_ms(),
            custom_letter_pause_ms=None,
            space_behavior=space_behavior,
        )

        try:
            save_rules(rules)
        except Exception as exc:
            message = f"保存空格朗读设置失败：{exc}"
            self.view.set_status(message)
            self.view.show_error("保存失败", message)
            return

        self._rules = rules
        self._space_behavior = space_behavior
        self.view.set_status("已开启空格朗读。" if is_enabled else "已关闭空格朗读。")

    def handle_close(self) -> None:
        self._closing = True
        if self._is_playing:
            self._request_stop("正在关闭并停止播放...")

        try:
            self._shutdown_engine()
        finally:
            self.view.close_rules_dialog()
            self.root.destroy()

    def _save_rules_from_dialog(self, dialog: Any) -> None:
        try:
            parsed_rules = _parse_rules_text(
                dialog.get_special_words_text(),
                dialog.get_symbol_readings_text(),
                getattr(self._rules, "word_pause_ms", 120),
                getattr(self._rules, "letter_pause_ms", 0),
                getattr(self._rules, "space_behavior", "pause"),
                letter_readings_text=dialog.get_letter_readings_text(),
                letter_audio_text=dialog.get_letter_audio_text(),
            )
        except ValueError as exc:
            self.view.show_error("规则格式错误", str(exc))
            return

        rules = self._replace_rules(
            special_words=parsed_rules.special_words,
            custom_symbol_readings=parsed_rules.custom_symbol_readings,
            custom_letter_readings=parsed_rules.custom_letter_readings,
            custom_letter_audio_paths=parsed_rules.custom_letter_audio_paths,
            word_pause_ms=self._get_current_word_pause_ms(),
            letter_pause_ms=self._get_current_letter_pause_ms(),
            spell_chunk_size=self._get_current_spell_chunk_size(),
            spell_chunk_pause_ms=self._get_current_spell_chunk_pause_ms(),
            custom_letter_pause_ms=None,
        )

        try:
            save_rules(rules)
        except Exception as exc:
            message = f"保存特殊规则失败：{exc}"
            self.view.set_status(message)
            self.view.show_error("保存失败", message)
            return

        self._rules = rules
        self.view.close_rules_dialog()
        self.view.set_status("特殊规则已保存。")

    def _initialize_engine(self) -> None:
        self._engine_loading = True
        self.view.set_status("正在加载语音，请稍等...")
        threading.Thread(
            target=self._initialize_engine_worker,
            daemon=True,
            name="spell-reader-engine-loader",
        ).start()

    def _initialize_engine_worker(self) -> None:
        try:
            dependencies = self._load_dependencies()
            engine = dependencies.engine_class()
            voice_payload = self._voice_choices_for_engine(engine)
            self.event_queue.put(
                _QueuedEvent(
                    "engine_ready",
                    {
                        "dependencies": dependencies,
                        "engine": engine,
                        "voices": voice_payload["voices"],
                        "labels": voice_payload["labels"],
                        "english_index": voice_payload["english_index"],
                        "chinese_index": voice_payload["chinese_index"],
                    },
                )
            )
        except Exception as exc:
            self.event_queue.put(_QueuedEvent("engine_init_error", exc))

    def _load_dependencies(self) -> _DependencyBundle:
        parser_module = self._import_first(("app.parser", "parser"))
        models_module = self._import_first(("app.models", "models"))
        speech_module = self._import_first(("app.speech_engine", "speech_engine"))

        build_speech_plan = getattr(parser_module, "build_speech_plan")
        parse_options = getattr(models_module, "ParseOptions")
        reading_mode = getattr(models_module, "ReadingMode")
        number_mode = getattr(models_module, "NumberMode")
        whitespace_mode = getattr(models_module, "WhitespaceMode", None)
        piper_engine_class = getattr(speech_module, "PiperSpeechEngine", None)
        edge_engine_class = getattr(speech_module, "MicrosoftEdgeSpeechEngine", None)
        pyttsx3_engine_class = getattr(speech_module, "Pyttsx3SpeechEngine", None) or getattr(
            speech_module, "SpeechEngine"
        )
        engine_class = self._build_engine_factory(
            piper_engine_class,
            pyttsx3_engine_class,
            edge_engine_class,
        )
        voice_selection = getattr(speech_module, "VoiceSelection")
        playback_settings = getattr(speech_module, "PlaybackSettings")
        playback_event_type = getattr(speech_module, "PlaybackEventType", SimpleNamespace())

        return _DependencyBundle(
            build_speech_plan=build_speech_plan,
            ParseOptions=parse_options,
            ReadingMode=reading_mode,
            NumberMode=number_mode,
            WhitespaceMode=whitespace_mode,
            engine_class=engine_class,
            VoiceSelection=voice_selection,
            PlaybackSettings=playback_settings,
            PlaybackEventType=playback_event_type,
        )

    def _build_engine_factory(
        self,
        preferred_engine_class: Any,
        fallback_engine_class: Any,
        edge_engine_class: Any = None,
    ) -> Any:
        if preferred_engine_class is None and edge_engine_class is None:
            return fallback_engine_class
        if fallback_engine_class is None:
            return preferred_engine_class or edge_engine_class

        def engine_factory() -> Any:
            return _RoutedSpeechEngine(
                fallback_engine_class,
                preferred_engine_class,
                edge_engine_class,
            )

        return engine_factory

    def _import_first(self, module_names: tuple[str, ...]):
        errors: list[str] = []
        for module_name in module_names:
            try:
                return importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                if exc.name != module_name:
                    raise
                errors.append(str(exc))
        raise ModuleNotFoundError("; ".join(errors))

    def _load_voices(self) -> None:
        if self._engine is None:
            return
        voice_payload = self._voice_choices_for_engine(self._engine)
        self._voices = voice_payload["voices"]
        self.view.set_voices(
            voice_payload["labels"],
            voice_payload["labels"],
            voice_payload["english_index"],
            voice_payload["chinese_index"],
        )

    def _voice_choices_for_engine(self, engine: Any) -> dict[str, Any]:
        list_voices = getattr(engine, "list_voices", None)
        if not callable(list_voices):
            raise AttributeError("speech engine does not expose list_voices()")

        voices = list(list_voices() or [])
        labels = [self._describe_voice(voice) for voice in voices]
        english_index = self._voice_index_for_saved_id(
            voices,
            getattr(self._rules, "english_voice_id", None),
        )
        if english_index is None:
            english_index = self._pick_default_english_voice_index(voices)
        chinese_index = self._voice_index_for_saved_id(
            voices,
            getattr(self._rules, "chinese_voice_id", None),
        )
        if chinese_index is None:
            chinese_index = self._pick_default_voice_index(voices, ("zh", "chinese", "mandarin"))
        return {
            "voices": voices,
            "labels": labels,
            "english_index": english_index,
            "chinese_index": chinese_index,
        }

    def _pick_default_english_voice_index(self, voices: list[Any]) -> int:
        for index, voice in enumerate(voices):
            if self._voice_looks_english(voice) and not self._voice_matches_all_keywords(
                voice,
                ("piper",),
            ):
                return index
        for index, voice in enumerate(voices):
            if self._voice_looks_english(voice):
                return index
        return 0

    def _pick_default_voice_index(self, voices: list[Any], keywords: tuple[str, ...]) -> int:
        if not voices:
            return 0

        for index, voice in enumerate(voices):
            if self._voice_matches_any_keyword(voice, keywords):
                return index
        return 0

    def _voice_index_for_saved_id(self, voices: list[Any], saved_voice_id: object) -> int | None:
        if not isinstance(saved_voice_id, str) or not saved_voice_id.strip():
            return None
        normalized_saved_id = saved_voice_id.strip()
        for index, voice in enumerate(voices):
            if self._voice_identifier(voice) == normalized_saved_id:
                return index
        return None

    def _voice_matches_any_keyword(self, voice: Any, keywords: tuple[str, ...]) -> bool:
        if voice is None:
            return False
        haystack = " ".join(self._voice_metadata_strings(voice)).lower()
        return any(keyword in haystack for keyword in keywords)

    def _voice_matches_all_keywords(self, voice: Any, keywords: tuple[str, ...]) -> bool:
        if voice is None:
            return False
        haystack = " ".join(self._voice_metadata_strings(voice)).lower()
        return all(keyword in haystack for keyword in keywords)

    def _voice_looks_english(self, voice: Any) -> bool:
        if voice is None:
            return False
        haystack = " ".join(self._voice_metadata_strings(voice)).lower()
        if "english" in haystack:
            return True
        languages = self._coerce_languages(
            self._first_attr(voice, ("languages", "language", "locale"))
        )
        return any(language.lower().replace("-", "_").startswith("en") for language in languages)

    def _voice_metadata_strings(self, voice: Any) -> list[str]:
        languages = self._coerce_languages(self._first_attr(voice, ("languages", "language", "locale")))
        values = [
            self._first_attr(voice, ("name", "display_name")),
            self._first_attr(voice, ("id", "voice_id", "identifier")),
            self._first_attr(voice, ("gender",)),
        ]
        values.extend(languages)
        return [str(value) for value in values if value]

    def _describe_voice(self, voice: Any) -> str:
        name = self._first_attr(voice, ("name", "display_name")) or "未知语音"
        languages = ", ".join(self._coerce_languages(self._first_attr(voice, ("languages", "language", "locale"))))
        return f"{name} ({languages})" if languages else str(name)

    def _playback_worker(self, text: str) -> None:
        try:
            dependencies = self._dependencies
            if dependencies is None:
                raise RuntimeError("语音依赖尚未初始化。")
            self._ensure_resume_state_fields()

            parse_options = self._build_parse_options()
            speech_plan = self._build_resumable_speech_plan(text, parse_options)
            units = list(getattr(speech_plan, "units", []) or [])
            voice_selection = self._build_voice_selection()
            playback_settings = self._build_playback_settings(voice_selection)

            if not units:
                self._reset_resume_state()
                self._reset_progress_state()
                self.event_queue.put(_QueuedEvent("progress_reset"))
                self.event_queue.put(_QueuedEvent("status", "播放完成。"))
                return

            self._begin_progress_tracking(units)
            self._queue_playback_progress(token="准备中...", eta_seconds=None)
            self.event_queue.put(_QueuedEvent("status", "正在播放..."))
            session = self._run_playback(speech_plan, voice_selection, playback_settings)
            session_state = self._session_state_name(getattr(session, "state", None))
            if session_state == "error":
                message = self._session_error_message(session)
                raise RuntimeError(message or "语音引擎返回了错误状态。")
            if session_state == "stopped":
                if self._is_pause_requested():
                    self._queue_playback_progress(state="paused")
                    self.event_queue.put(_QueuedEvent("status", "已暂停，可继续播放。"))
                else:
                    self._reset_resume_state()
                    self._reset_progress_state()
                    self.event_queue.put(_QueuedEvent("progress_reset"))
                    self.event_queue.put(_QueuedEvent("status", "播放已停止。"))
            else:
                self._queue_playback_progress(
                    completed=self._playback_total_units,
                    token="",
                    eta_seconds=0,
                    state="completed",
                )
                self._reset_resume_state()
                self.event_queue.put(_QueuedEvent("status", "播放完成。"))
        except Exception as exc:
            self._reset_resume_state()
            self._reset_progress_state()
            self.event_queue.put(_QueuedEvent("progress_reset"))
            self.event_queue.put(_QueuedEvent("error", exc))
        finally:
            self.event_queue.put(_QueuedEvent("playback_finished"))

    def _build_parse_options(self) -> Any:
        dependencies = self._require_dependencies()
        reading_mode = self._resolve_enum_member(
            dependencies.ReadingMode,
            self.view.get_selected_reading_mode(),
        )
        number_mode = self._resolve_enum_member(
            dependencies.NumberMode,
            self.view.get_selected_number_mode(),
        )
        space_behavior = self._get_current_space_behavior()
        whitespace_mode = self._resolve_whitespace_mode(dependencies, space_behavior)

        kwargs = {
            "reading_mode": reading_mode,
            "mode": reading_mode,
            "reading": reading_mode,
            "number_mode": number_mode,
            "numbers": number_mode,
            "special_words": self._rules.special_words,
            "custom_symbol_readings": self._rules.custom_symbol_readings,
            "custom_letter_readings": self._rules.custom_letter_readings,
            "custom_letter_audio_paths": getattr(
                self._rules,
                "custom_letter_audio_paths",
                {},
            ),
            "word_pause_ms": self._get_current_word_pause_ms(),
            "letter_pause_ms": self._get_current_letter_pause_ms(),
            "spell_chunk_size": self._get_current_spell_chunk_size(),
            "spell_chunk_pause_ms": self._get_current_spell_chunk_pause_ms(),
            "whitespace_mode": whitespace_mode,
            "space_behavior": space_behavior,
        }
        return self._construct_with_fallbacks(
            dependencies.ParseOptions,
            kwargs,
            [
                (reading_mode, number_mode),
            ],
        )

    def _build_resumable_speech_plan(self, text: str, parse_options: Any) -> Any:
        self._ensure_resume_state_fields()
        dependencies = self._require_dependencies()
        speech_plan = dependencies.build_speech_plan(text, parse_options)
        units = list(getattr(speech_plan, "units", []) or [])
        start_index = self._resume_start_index_for_text(text, len(units))
        if start_index <= 0:
            return speech_plan
        return self._copy_speech_plan_with_units(speech_plan, units[start_index:])

    def _resume_start_index_for_text(self, text: str, unit_count: int) -> int:
        with self._progress_lock:
            if self._paused_text != text:
                self._clear_resume_state_locked()
                self._current_playback_text = text
                return 0
            start_index = max(0, min(self._resume_unit_index, unit_count))
            self._current_playback_text = text
            self._last_finished_unit_index = start_index - 1
            return start_index

    def _copy_speech_plan_with_units(self, speech_plan: Any, units: list[Any]) -> Any:
        try:
            return replace(speech_plan, units=list(units))
        except Exception:
            return SimpleNamespace(
                source_text=getattr(speech_plan, "source_text", ""),
                options=getattr(speech_plan, "options", None),
                tokens=getattr(speech_plan, "tokens", []),
                units=list(units),
            )

    def _get_current_word_pause_ms(self) -> int:
        get_word_pause_ms = getattr(self.view, "get_word_pause_ms", None)
        if callable(get_word_pause_ms):
            try:
                pause_ms = int(get_word_pause_ms())
            except (TypeError, ValueError):
                pause_ms = self._rules.word_pause_ms
            return max(0, pause_ms)
        return self._rules.word_pause_ms

    def _get_current_letter_pause_ms(self) -> int:
        get_letter_pause_ms = getattr(self.view, "get_letter_pause_ms", None)
        if callable(get_letter_pause_ms):
            try:
                pause_ms = int(get_letter_pause_ms())
            except (TypeError, ValueError):
                pause_ms = self._rules.letter_pause_ms
            return clamp_letter_pause_level(pause_ms)
        return clamp_letter_pause_level(self._rules.letter_pause_ms)

    def _get_current_spell_chunk_size(self) -> int:
        get_spell_chunk_size = getattr(self.view, "get_spell_chunk_size", None)
        if callable(get_spell_chunk_size):
            try:
                chunk_size = int(get_spell_chunk_size())
            except (TypeError, ValueError):
                chunk_size = getattr(self._rules, "spell_chunk_size", 1)
            return max(1, min(10, chunk_size))
        try:
            chunk_size = int(getattr(self._rules, "spell_chunk_size", 1))
        except (TypeError, ValueError):
            chunk_size = 1
        return max(1, min(10, chunk_size))

    def _get_current_spell_chunk_pause_ms(self) -> int:
        get_spell_chunk_pause_ms = getattr(self.view, "get_spell_chunk_pause_ms", None)
        if callable(get_spell_chunk_pause_ms):
            try:
                pause_ms = int(get_spell_chunk_pause_ms())
            except (TypeError, ValueError):
                pause_ms = getattr(self._rules, "spell_chunk_pause_ms", 300)
            return max(0, min(5000, pause_ms))
        try:
            pause_ms = int(getattr(self._rules, "spell_chunk_pause_ms", 300))
        except (TypeError, ValueError):
            pause_ms = 300
        return max(0, min(5000, pause_ms))

    def _get_current_space_behavior(self) -> str:
        try:
            return _normalize_space_behavior(getattr(self, "_space_behavior", "pause"))
        except ValueError:
            return "pause"

    def _restore_main_settings_from_rules(self) -> None:
        set_selected_reading_mode = getattr(self.view, "set_selected_reading_mode", None)
        if callable(set_selected_reading_mode):
            set_selected_reading_mode(
                getattr(self._rules, "reading_mode", "spell_then_read_word")
            )

        set_selected_number_mode = getattr(self.view, "set_selected_number_mode", None)
        if callable(set_selected_number_mode):
            set_selected_number_mode(getattr(self._rules, "number_mode", "digit_by_digit"))

        set_rate = getattr(self.view, "set_rate", None)
        if callable(set_rate):
            set_rate(getattr(self._rules, "rate", 160))

        set_volume = getattr(self.view, "set_volume", None)
        if callable(set_volume):
            set_volume(getattr(self._rules, "volume", 100))

        self.view.set_word_pause_ms(getattr(self._rules, "word_pause_ms", 120))
        self.view.set_letter_pause_ms(
            resolve_letter_pause_ms(
                getattr(self._rules, "letter_pause_ms", 0),
                getattr(self._rules, "custom_letter_pause_ms", None),
            )
        )
        set_spell_chunk_size = getattr(self.view, "set_spell_chunk_size", None)
        if callable(set_spell_chunk_size):
            set_spell_chunk_size(getattr(self._rules, "spell_chunk_size", 1))
        set_spell_chunk_pause_ms = getattr(self.view, "set_spell_chunk_pause_ms", None)
        if callable(set_spell_chunk_pause_ms):
            set_spell_chunk_pause_ms(getattr(self._rules, "spell_chunk_pause_ms", 300))
        set_space_reading_enabled = getattr(self.view, "set_space_reading_enabled", None)
        if callable(set_space_reading_enabled):
            set_space_reading_enabled(self._space_behavior == "read_space")

    def _rules_from_current_main_settings(self) -> ReaderRules:
        english_voice = self._get_selected_voice(self.view.get_selected_english_voice_index())
        chinese_voice = self._get_selected_voice(self.view.get_selected_chinese_voice_index())
        space_behavior = "read_space" if self.view.is_space_reading_enabled() else "pause"
        return self._replace_rules(
            reading_mode=self.view.get_selected_reading_mode(),
            number_mode=self.view.get_selected_number_mode(),
            rate=self.view.get_rate(),
            volume=self.view.get_volume(),
            word_pause_ms=self._get_current_word_pause_ms(),
            letter_pause_ms=self._get_current_letter_pause_ms(),
            spell_chunk_size=self._get_current_spell_chunk_size(),
            spell_chunk_pause_ms=self._get_current_spell_chunk_pause_ms(),
            custom_letter_pause_ms=None,
            space_behavior=space_behavior,
            english_voice_id=self._voice_identifier(english_voice),
            chinese_voice_id=self._voice_identifier(chinese_voice),
        )

    def _replace_rules(self, **updates: Any) -> ReaderRules:
        supported_fields = {field.name for field in fields(type(self._rules))}
        filtered_updates = {
            name: value for name, value in updates.items() if name in supported_fields
        }
        return replace(self._rules, **filtered_updates)

    def _resolve_whitespace_mode(self, dependencies: _DependencyBundle, space_behavior: str) -> Any:
        if dependencies.WhitespaceMode is None:
            return space_behavior
        return self._resolve_enum_member(dependencies.WhitespaceMode, space_behavior)

    def _build_voice_selection(self) -> Any:
        dependencies = self._require_dependencies()
        english_voice = self._get_selected_voice(self.view.get_selected_english_voice_index())
        chinese_voice = self._get_selected_voice(self.view.get_selected_chinese_voice_index())
        english_voice_id = self._voice_identifier(english_voice)
        chinese_voice_id = self._voice_identifier(chinese_voice)

        kwargs = {
            "english_voice_id": english_voice_id,
            "chinese_voice_id": chinese_voice_id,
            "english_id": english_voice_id,
            "chinese_id": chinese_voice_id,
            "english_voice": english_voice,
            "chinese_voice": chinese_voice,
            "english": english_voice,
            "chinese": chinese_voice,
        }
        return self._construct_with_fallbacks(
            dependencies.VoiceSelection,
            kwargs,
            [
                (english_voice_id, chinese_voice_id),
                (english_voice, chinese_voice),
            ],
        )

    def _build_playback_settings(self, voice_selection: Any) -> Any:
        dependencies = self._require_dependencies()
        rate = self.view.get_rate()
        volume_percent = self.view.get_volume()
        volume_normalized = volume_percent / 100.0

        kwargs = {
            "rate": rate,
            "speech_rate": rate,
            "volume": volume_normalized,
            "volume_percent": volume_percent,
            "volume_level": volume_normalized,
            "voice_selection": voice_selection,
            "voices": voice_selection,
        }
        settings = self._construct_with_fallbacks(
            dependencies.PlaybackSettings,
            kwargs,
            [
                (rate, volume_normalized, voice_selection),
                (rate, volume_percent, voice_selection),
                (voice_selection, rate, volume_normalized),
                (voice_selection, rate, volume_percent),
                (rate, voice_selection, volume_normalized),
                (rate, voice_selection, volume_percent),
                (rate, volume_normalized),
                (rate, volume_percent),
            ],
        )
        return self._embed_voice_selection_in_settings(settings, voice_selection)

    def _run_playback(self, speech_plan: Any, voice_selection: Any, playback_settings: Any) -> Any:
        if self._engine is None:
            raise RuntimeError("语音引擎不可用。")

        callback = self._make_engine_callback()
        playback_method = self._find_playback_method()

        kwargs = {
            "speech_plan": speech_plan,
            "plan": speech_plan,
            "voice_selection": voice_selection,
            "voices": voice_selection,
            "playback_settings": playback_settings,
            "settings": playback_settings,
            "event_callback": callback,
            "callback": callback,
            "on_event": callback,
            "stop_event": self._stop_requested,
            "cancel_event": self._stop_requested,
        }
        fallback_args = [
            (speech_plan, voice_selection, playback_settings, callback, self._stop_requested),
            (speech_plan, voice_selection, playback_settings, callback),
            (speech_plan, voice_selection, playback_settings),
            (speech_plan, voice_selection),
            (speech_plan,),
        ]
        session = self._call_with_supported_signature(playback_method, kwargs, fallback_args)
        self._wait_for_playback_session(session)
        return session

    def _wait_for_playback_session(self, session: Any) -> Any:
        if session is None:
            return None
        wait_method = getattr(self._engine, "wait_until_finished", None)
        if callable(wait_method):
            return wait_method(session)
        return getattr(session, "state", None)

    def _make_engine_callback(self):
        def callback(*args, **kwargs) -> None:
            raw_event = kwargs.get("event")
            if raw_event is None and args:
                raw_event = args[0]
            self._record_playback_progress(raw_event)
            self.event_queue.put(_QueuedEvent("engine_event", (args, kwargs)))

        return callback

    def _record_playback_progress(self, raw_event: Any) -> None:
        if raw_event is None:
            return

        event_type = self._extract_event_type(raw_event)
        if event_type == "unit_started":
            token = self._extract_event_token(raw_event)
            with self._progress_lock:
                if token:
                    self._playback_last_token = token
                read_until = self._read_until_for_event_locked(raw_event)
            self._queue_playback_progress(token=token, read_until=read_until)
            return

        if event_type != "unit_finished":
            return

        unit_index = self._extract_event_unit_index(raw_event)
        if unit_index is None:
            return

        token = self._extract_event_token(raw_event)
        with self._progress_lock:
            self._last_finished_unit_index = max(
                self._last_finished_unit_index,
                unit_index,
            )
            self._resume_unit_index = max(
                self._resume_unit_index,
                self._last_finished_unit_index + 1,
            )
            if self._current_playback_text is not None:
                self._paused_text = self._current_playback_text
            relative_completed = unit_index - self._playback_unit_base_index + 1
            if self._playback_total_units > 0:
                self._playback_completed_units = max(
                    self._playback_completed_units,
                    max(0, min(relative_completed, self._playback_total_units)),
                )
            if token:
                self._playback_last_token = token
            completed = self._playback_completed_units
            total = self._playback_total_units
            display_token = self._playback_last_token
            eta_seconds = self._remaining_estimated_seconds_locked(completed)
            read_until = self._read_until_for_event_locked(raw_event)

        self.event_queue.put(
            _QueuedEvent(
                "progress",
                {
                    "completed": completed,
                    "total": total,
                    "token": display_token,
                    "eta_seconds": eta_seconds,
                    "state": "playing",
                    "read_until": read_until,
                },
            )
        )

    def _extract_event_unit_index(self, raw_event: Any) -> int | None:
        unit = self._first_attr(raw_event, ("unit",))
        unit_index = self._first_attr(unit, ("index",)) if unit is not None else None
        if unit_index is None:
            unit_index = self._first_attr(raw_event, ("unit_index", "index"))
        try:
            return int(unit_index)
        except (TypeError, ValueError):
            return None

    def _extract_event_token(self, raw_event: Any) -> str:
        unit = self._first_attr(raw_event, ("unit",))
        if unit is None:
            return ""
        action = self._enumish_text(self._first_attr(unit, ("action", "unit_type", "kind", "type")))
        if action == "pause":
            return ""
        for attr in ("source_text", "speak_text", "text"):
            value = self._first_attr(unit, (attr,))
            if value is None:
                continue
            token = str(value).strip()
            if token:
                return token
        return ""

    def _is_pause_requested(self) -> bool:
        self._ensure_resume_state_fields()
        with self._progress_lock:
            return self._pause_requested

    def _reset_resume_state(self) -> None:
        self._ensure_resume_state_fields()
        with self._progress_lock:
            self._clear_resume_state_locked()

    def _reset_progress_state(self) -> None:
        self._ensure_resume_state_fields()
        with self._progress_lock:
            self._clear_progress_state_locked()

    def _ensure_resume_state_fields(self) -> None:
        if not hasattr(self, "_progress_lock"):
            self._progress_lock = threading.Lock()
        if not hasattr(self, "_pause_requested"):
            self._pause_requested = False
        if not hasattr(self, "_paused_text"):
            self._paused_text = None
        if not hasattr(self, "_current_playback_text"):
            self._current_playback_text = None
        if not hasattr(self, "_resume_unit_index"):
            self._resume_unit_index = 0
        if not hasattr(self, "_last_finished_unit_index"):
            self._last_finished_unit_index = -1
        if not hasattr(self, "_playback_total_units"):
            self._playback_total_units = 0
        if not hasattr(self, "_playback_completed_units"):
            self._playback_completed_units = 0
        if not hasattr(self, "_playback_unit_base_index"):
            self._playback_unit_base_index = 0
        if not hasattr(self, "_playback_started_at"):
            self._playback_started_at = None
        if not hasattr(self, "_playback_last_token"):
            self._playback_last_token = ""
        if not hasattr(self, "_playback_unit_estimates"):
            self._playback_unit_estimates = []
        if not hasattr(self, "_playback_read_until"):
            self._playback_read_until = 0

    def _clear_resume_state_locked(self) -> None:
        self._pause_requested = False
        self._paused_text = None
        self._current_playback_text = None
        self._resume_unit_index = 0
        self._last_finished_unit_index = -1

    def _clear_progress_state_locked(self) -> None:
        self._playback_total_units = 0
        self._playback_completed_units = 0
        self._playback_unit_base_index = 0
        self._playback_started_at = None
        self._playback_last_token = ""
        self._playback_unit_estimates = []
        self._playback_read_until = 0

    def _begin_progress_tracking(self, units: list[Any]) -> None:
        self._ensure_resume_state_fields()
        first_index = self._unit_index_or_default(units[0], 0) if units else 0
        with self._progress_lock:
            self._playback_total_units = len(units)
            self._playback_completed_units = 0
            self._playback_unit_base_index = first_index
            self._playback_started_at = time.monotonic()
            self._playback_last_token = ""
            self._playback_unit_estimates = [
                self._estimate_unit_seconds(unit) for unit in units
            ]
            self._playback_read_until = 0

    def _unit_index_or_default(self, unit: Any, default: int) -> int:
        try:
            return int(self._first_attr(unit, ("index",)))
        except (TypeError, ValueError):
            return default

    def _queue_playback_progress(
        self,
        *,
        completed: int | None = None,
        token: str | None = None,
        eta_seconds: float | None = None,
        state: str = "playing",
        read_until: int | None = None,
    ) -> None:
        self._ensure_resume_state_fields()
        with self._progress_lock:
            current = self._playback_completed_units if completed is None else completed
            total = self._playback_total_units
            if token is not None:
                display_token = token
                if token and state == "playing":
                    self._playback_last_token = token
            else:
                display_token = self._playback_last_token
            if eta_seconds is None:
                eta_seconds = self._remaining_estimated_seconds_locked(current)

        self.event_queue.put(
            _QueuedEvent(
                "progress",
                {
                    "completed": current,
                    "total": total,
                    "token": display_token,
                    "eta_seconds": eta_seconds,
                    "state": state,
                    "read_until": read_until,
                },
            )
        )

    def _remaining_estimated_seconds_locked(self, completed: int) -> float | None:
        if self._playback_total_units <= 0 or not self._playback_unit_estimates:
            return None
        start = max(0, min(completed, len(self._playback_unit_estimates)))
        return round(sum(self._playback_unit_estimates[start:]), 1)

    def _estimate_unit_seconds(self, unit: Any) -> float:
        pause_ms = self._first_attr(unit, ("pause_ms",))
        action = self._enumish_text(self._first_attr(unit, ("action", "unit_type", "kind", "type")))
        if action == "pause" or pause_ms:
            try:
                return max(0.0, float(pause_ms) / 1000.0)
            except (TypeError, ValueError):
                return 0.0

        text = str(self._first_attr(unit, ("speak_text", "text", "source_text")) or "").strip()
        if not text:
            return 0.1
        words = [part for part in text.split() if part]
        base_seconds = max(0.35, len(text) / 9.0, len(words) * 0.28)
        rate = self._rate_for_estimate()
        return round(base_seconds * (160.0 / rate), 2)

    def _rate_for_estimate(self) -> float:
        view = getattr(self, "view", None)
        get_rate = getattr(view, "get_rate", None)
        if callable(get_rate):
            try:
                return max(80.0, min(260.0, float(get_rate())))
            except (TypeError, ValueError):
                pass
        return 160.0

    def _read_until_for_event_locked(self, raw_event: Any) -> int:
        unit = self._first_attr(raw_event, ("unit",))
        span = self._first_attr(unit, ("span", "source_span")) if unit is not None else None
        end = self._first_attr(span, ("end",)) if span is not None else None
        try:
            self._playback_read_until = max(self._playback_read_until, int(end))
        except (TypeError, ValueError):
            pass
        return self._playback_read_until

    def _reset_playback_progress_view(self) -> None:
        reset_progress = getattr(self.view, "reset_playback_progress", None)
        if callable(reset_progress):
            reset_progress()

    def _find_playback_method(self):
        for method_name in ("play", "play_plan", "speak", "read"):
            method = getattr(self._engine, method_name, None)
            if callable(method):
                return method
        raise AttributeError("speech engine does not expose a supported playback method")

    def _request_stop(self, status_message: str) -> None:
        self._stop_requested.set()
        self.view.set_status(status_message)
        stop_method = None
        if self._engine is not None:
            for method_name in ("stop", "stop_playback", "cancel"):
                candidate = getattr(self._engine, method_name, None)
                if callable(candidate):
                    stop_method = candidate
                    break
        if stop_method is not None:
            threading.Thread(
                target=self._call_stop_method,
                args=(stop_method,),
                daemon=True,
                name="spell-reader-stop",
            ).start()

    def _call_stop_method(self, stop_method: Any) -> None:
        try:
            stop_method()
        except Exception as exc:
            self.event_queue.put(_QueuedEvent("error", exc))

    def _shutdown_engine(self) -> None:
        if self._engine is None:
            return

        for method_name in ("shutdown", "close"):
            method = getattr(self._engine, method_name, None)
            if callable(method):
                method()
                break

    def _schedule_poll(self) -> None:
        self.root.after(self._poll_interval_ms, self._poll_event_queue)

    def _poll_event_queue(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_queued_event(event)

        if not self._closing:
            self._schedule_poll()

    def _handle_queued_event(self, event: _QueuedEvent) -> None:
        if event.kind == "status":
            self.view.set_status(str(event.payload))
            return

        if event.kind == "engine_ready":
            payload = event.payload or {}
            self._dependencies = payload.get("dependencies")
            self._engine = payload.get("engine")
            self._voices = list(payload.get("voices") or [])
            self._engine_loading = False
            self.view.set_voices(
                list(payload.get("labels") or []),
                list(payload.get("labels") or []),
                int(payload.get("english_index") or 0),
                int(payload.get("chinese_index") or 0),
            )
            self.view.set_status("就绪")
            return

        if event.kind == "engine_init_error":
            self._dependencies = None
            self._engine = None
            self._engine_loading = False
            message = f"初始化语音引擎失败：{event.payload}"
            self.view.set_status(message)
            self.view.show_error("初始化失败", message)
            return

        if event.kind == "error":
            message = str(event.payload)
            self.view.set_status(f"发生错误：{message}")
            self.view.show_error("播放失败", message)
            return

        if event.kind == "progress":
            payload = event.payload or {}
            set_progress = getattr(self.view, "set_playback_progress", None)
            if callable(set_progress):
                set_progress(
                    payload.get("completed", 0),
                    payload.get("total", 0),
                    token=payload.get("token", ""),
                    eta_seconds=payload.get("eta_seconds"),
                    state=payload.get("state", "playing"),
                )
            read_until = payload.get("read_until")
            if read_until is not None:
                mark_read = getattr(self.view, "mark_text_read_until", None)
                if callable(mark_read):
                    mark_read(read_until)
            return

        if event.kind == "progress_reset":
            self._reset_playback_progress_view()
            return

        if event.kind == "engine_event":
            self._apply_engine_event(*event.payload)
            return

        if event.kind == "playback_finished":
            self._set_playing(False)

    def _apply_engine_event(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        raw_event = kwargs.get("event")
        if raw_event is None and args:
            raw_event = args[0]
        if raw_event is None:
            return

        event_type = self._extract_event_type(raw_event)
        if event_type in {"start", "started", "begin"}:
            self.view.set_status("开始播放...")
        elif event_type in {"stop", "stopped", "cancelled", "canceled"}:
            self.view.set_status("播放已停止。")
        elif event_type in {"finish", "finished", "complete", "completed", "done"}:
            self.view.set_status("播放完成。")
        elif event_type == "error":
            message = self._extract_event_message(raw_event) or "语音引擎返回了错误事件。"
            self.view.set_status(f"发生错误：{message}")

    def _extract_event_type(self, raw_event: Any) -> str:
        dependencies = self._dependencies
        event_type = self._first_attr(raw_event, ("event_type", "type", "kind"))
        if event_type is None:
            return ""

        if dependencies is not None:
            for candidate_name in (
                "STARTED",
                "UNIT_STARTED",
                "UNIT_FINISHED",
                "STOPPED",
                "FINISHED",
                "COMPLETED",
                "ERROR",
            ):
                candidate = getattr(dependencies.PlaybackEventType, candidate_name, None)
                if candidate is not None and event_type == candidate:
                    return candidate_name.lower()

        return getattr(event_type, "name", str(event_type)).lower()

    def _extract_event_message(self, raw_event: Any) -> str | None:
        value = self._first_attr(raw_event, ("message", "detail", "error"))
        return str(value) if value else None

    def _session_state_name(self, state: Any) -> str:
        if state is None:
            return ""
        name = getattr(state, "name", None)
        if isinstance(name, str) and name:
            return name.lower()
        value = getattr(state, "value", state)
        return str(value).strip().lower()

    def _session_error_message(self, session: Any) -> str | None:
        value = self._first_attr(session, ("error_message", "message", "error"))
        if value is None:
            return None
        message = str(value).strip()
        return message or None

    def _set_playing(self, is_playing: bool) -> None:
        self._is_playing = is_playing
        self.view.set_playback_state(is_playing)

    def _ensure_ready(self) -> bool:
        if self._dependencies is None or self._engine is None:
            if getattr(self, "_engine_loading", False):
                self.view.set_status("语音正在加载，请稍等。")
            else:
                message = "语音依赖尚未就绪，请检查 speech engine、parser 和 models 模块。"
                self.view.set_status(message)
                self.view.show_error("依赖不可用", message)
            return False
        return True

    def _require_dependencies(self) -> _DependencyBundle:
        if self._dependencies is None:
            raise RuntimeError("应用依赖尚未初始化。")
        return self._dependencies

    def _get_selected_voice(self, index: int) -> Any:
        if not self._voices:
            return None
        bounded_index = max(0, min(index, len(self._voices) - 1))
        return self._voices[bounded_index]

    def _voice_identifier(self, voice: Any) -> Any:
        if voice is None:
            return None
        return self._first_attr(voice, ("id", "voice_id", "identifier", "name")) or str(voice)

    def _resolve_enum_member(self, enum_cls: Any, raw_value: str) -> Any:
        normalized_value = getattr(raw_value, "value", raw_value)
        normalized_text = normalized_value if isinstance(normalized_value, str) else str(normalized_value)
        if hasattr(enum_cls, "__members__"):
            for member in enum_cls.__members__.values():
                member_value = getattr(member, "value", None)
                member_name = getattr(member, "name", "")
                if member_value == normalized_text or member_name.lower() == normalized_text.lower():
                    return member
        if hasattr(enum_cls, normalized_text):
            return getattr(enum_cls, normalized_text)
        return enum_cls(normalized_text)

    def _construct_with_fallbacks(
        self,
        factory: Any,
        kwargs: dict[str, Any],
        fallback_args: list[tuple[Any, ...]],
    ) -> Any:
        signature = self._safe_signature(factory)
        if signature is not None:
            supported_kwargs = {name: value for name, value in kwargs.items() if name in signature.parameters}
            if supported_kwargs:
                try:
                    return factory(**supported_kwargs)
                except TypeError as exc:
                    if not self._looks_like_signature_mismatch(exc):
                        raise

        for args in fallback_args:
            try:
                return factory(*args)
            except TypeError as exc:
                if not self._looks_like_signature_mismatch(exc):
                    raise

        raise TypeError(f"Could not construct {factory!r} with supported arguments")

    def _call_with_supported_signature(
        self,
        callable_obj: Any,
        kwargs: dict[str, Any],
        fallback_args: list[tuple[Any, ...]],
    ) -> Any:
        signature = self._safe_signature(callable_obj)
        if signature is not None:
            supported_kwargs = {name: value for name, value in kwargs.items() if name in signature.parameters}
            if supported_kwargs:
                try:
                    return callable_obj(**supported_kwargs)
                except TypeError as exc:
                    if not self._looks_like_signature_mismatch(exc):
                        raise

        for args in fallback_args:
            try:
                return callable_obj(*args)
            except TypeError as exc:
                if not self._looks_like_signature_mismatch(exc):
                    raise

        raise TypeError(f"Could not invoke {callable_obj!r} with a supported signature")

    def _safe_signature(self, callable_obj: Any):
        try:
            return inspect.signature(callable_obj)
        except (TypeError, ValueError):
            return None

    def _embed_voice_selection_in_settings(self, settings: Any, voice_selection: Any) -> Any:
        if settings is None or voice_selection is None:
            return settings

        for attr_name in ("voice_selection", "voices"):
            self._set_attr_if_possible(settings, attr_name, voice_selection)
        return settings

    def _set_attr_if_possible(self, target: Any, name: str, value: Any) -> None:
        try:
            setattr(target, name, value)
            return
        except (AttributeError, TypeError):
            pass

        try:
            object.__setattr__(target, name, value)
        except (AttributeError, TypeError):
            return

    def _looks_like_signature_mismatch(self, exc: TypeError) -> bool:
        message = str(exc)
        return any(
            token in message
            for token in (
                "unexpected keyword",
                "missing ",
                "positional argument",
                "required positional",
                "takes ",
                "got an unexpected",
            )
        )

    def _first_attr(self, obj: Any, names: tuple[str, ...]) -> Any:
        if obj is None:
            return None
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    def _enumish_text(self, value: Any) -> str:
        if value is None:
            return ""
        name = getattr(value, "name", None)
        if isinstance(name, str) and name:
            return name.strip().lower()
        raw_value = getattr(value, "value", value)
        return str(raw_value).strip().lower()

    def _coerce_languages(self, raw_languages: Any) -> list[str]:
        if raw_languages is None:
            return []
        if isinstance(raw_languages, (str, bytes)):
            return [raw_languages.decode() if isinstance(raw_languages, bytes) else raw_languages]

        languages: list[str] = []
        for item in raw_languages:
            if isinstance(item, bytes):
                languages.append(item.decode(errors="ignore"))
            else:
                languages.append(str(item))
        return languages
