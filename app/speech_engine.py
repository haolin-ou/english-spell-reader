from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Sequence
import html
import io
import importlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Optional
import wave

try:
    from app.models import SpeechPlan, SpeechUnit, VoiceRole  # type: ignore
    from app.symbol_map import SYMBOL_TO_CHINESE  # type: ignore
except Exception:
    SpeechPlan = Any  # type: ignore[assignment]
    SpeechUnit = Any  # type: ignore[assignment]
    SYMBOL_TO_CHINESE = {}  # type: ignore[assignment]

    class VoiceRole(str, Enum):
        ENGLISH = "english"
        CHINESE = "chinese"


class PlaybackState(str, Enum):
    IDLE = "idle"
    QUEUED = "queued"
    PLAYING = "playing"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class PlaybackEventType(str, Enum):
    STARTED = "started"
    UNIT_STARTED = "unit_started"
    UNIT_FINISHED = "unit_finished"
    STOPPED = "stopped"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass(frozen=True)
class VoiceDescriptor:
    id: str
    name: str
    languages: tuple[str, ...] = ()
    gender: Optional[str] = None


@dataclass(frozen=True)
class VoiceSelection:
    english_voice_id: Optional[str] = None
    chinese_voice_id: Optional[str] = None
    english_voice: Any = None
    chinese_voice: Any = None


@dataclass(frozen=True, init=False)
class PlaybackSettings:
    voices: VoiceSelection = field(default_factory=VoiceSelection)
    rate: int = 200
    volume: float = 1.0

    def __init__(
        self,
        *args: Any,
        voices: Optional[VoiceSelection] = None,
        rate: int = 200,
        volume: float = 1.0,
        voice_selection: Optional[VoiceSelection] = None,
    ) -> None:
        resolved_voices = voices
        resolved_rate = rate
        resolved_volume = volume

        if len(args) > 3:
            raise TypeError("PlaybackSettings accepts at most 3 positional arguments.")

        if len(args) == 1:
            if self._is_voice_selection_like(args[0]):
                resolved_voices = args[0]
            else:
                resolved_rate = args[0]
        elif len(args) == 2:
            if self._is_voice_selection_like(args[0]):
                resolved_voices = args[0]
                resolved_rate = args[1]
            else:
                resolved_rate, resolved_volume = args
        elif len(args) == 3:
            if self._is_voice_selection_like(args[0]):
                resolved_voices, resolved_rate, resolved_volume = args
            else:
                resolved_rate, resolved_volume, resolved_voices = args

        if voice_selection is not None and resolved_voices is None:
            resolved_voices = voice_selection
        if resolved_voices is None:
            resolved_voices = VoiceSelection()

        object.__setattr__(self, "voices", resolved_voices)
        object.__setattr__(self, "rate", resolved_rate)
        object.__setattr__(self, "volume", resolved_volume)

    @property
    def voice_selection(self) -> VoiceSelection:
        return self.voices

    @staticmethod
    def _is_voice_selection_like(value: Any) -> bool:
        return any(
            hasattr(value, attr)
            for attr in (
                "english_voice_id",
                "chinese_voice_id",
                "english_id",
                "chinese_id",
                "english_voice",
                "chinese_voice",
                "english",
                "chinese",
            )
        )


@dataclass
class PlaybackSession:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: PlaybackState = PlaybackState.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error_message: Optional[str] = None
    total_units: int = 0

    @property
    def playback_id(self) -> str:
        return self.session_id

    @playback_id.setter
    def playback_id(self, value: str) -> None:
        self.session_id = value


@dataclass(frozen=True)
class PlaybackEvent:
    event_type: PlaybackEventType
    session: PlaybackSession
    state: PlaybackState
    unit: Optional[SpeechUnit] = None
    unit_index: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def type(self) -> PlaybackEventType:
        return self.event_type

    @property
    def playback_id(self) -> str:
        return self.session.playback_id


@dataclass(frozen=True)
class _PlayRequest:
    plan: SpeechPlan
    units: tuple[SpeechUnit, ...]
    settings: PlaybackSettings
    session: PlaybackSession
    on_event: Optional[Callable[[PlaybackEvent], None]]


class PiperSpeechEngine:
    """Piper-backed engine that renders a whole speech plan to one WAV."""

    VOICE_ID = "piper:en_US-lessac-medium"
    VOICE_NAME = "Piper English (US Lessac Medium)"
    MODEL_BASENAME = "en_US-lessac-medium.onnx"
    DEFAULT_MODEL_STEM = "en_US-lessac-medium"
    DEFAULT_WAV_PARAMS = (1, 2, 22050)
    THREADS_ENV_VAR = "ENGLISH_SPELL_READER_PIPER_THREADS"
    DEFAULT_CPU_THREADS = 1
    CHINESE_READING_ENGLISH_NAMES = {
        "空格": "space",
        "空": "blank",
        "连字符": "hyphen",
        "减号": "minus sign",
    }
    SYMBOL_ENGLISH_NAMES = {
        ".": "period",
        ",": "comma",
        "!": "exclamation mark",
        "?": "question mark",
        ":": "colon",
        ";": "semicolon",
        "(": "left parenthesis",
        ")": "right parenthesis",
        "[": "left bracket",
        "]": "right bracket",
        "{": "left brace",
        "}": "right brace",
        "+": "plus",
        "-": "hyphen",
        "*": "asterisk",
        "/": "slash",
        "\\": "backslash",
        "=": "equals",
        "_": "underscore",
        "@": "at sign",
        "#": "hash sign",
        "$": "dollar sign",
        "%": "percent sign",
        "&": "ampersand",
        '"': "double quote",
        "'": "single quote",
        "<": "less than",
        ">": "greater than",
        " ": "space",
        "\t": "tab",
    }
    LETTER_NAMES = {
        "A": "ay",
        "B": "bee",
        "C": "see",
        "D": "dee",
        "E": "ee",
        "F": "eff",
        "G": "gee",
        "H": "aitch",
        "I": "eye",
        "J": "jay",
        "K": "kay",
        "L": "ell",
        "M": "em",
        "N": "en",
        "O": "oh",
        "P": "pee",
        "Q": "cue",
        "R": "are",
        "S": "ess",
        "T": "tee",
        "U": "you",
        "V": "vee",
        "W": "double you",
        "X": "ex",
        "Y": "why",
        "Z": "zee",
    }

    def __init__(
        self,
        *,
        model_dir: str | Path | None = None,
        voice_loader: Optional[Callable[[Path], Any]] = None,
        wav_player: Optional[Callable[[str | Path, threading.Event], None]] = None,
        render_in_subprocess: Optional[bool] = None,
    ) -> None:
        self._condition = threading.Condition()
        self._state = PlaybackState.IDLE
        self._stop_event = threading.Event()
        self._model_dir = self._resolve_model_dir(model_dir)
        model_pairs = self._discover_model_pairs()
        if not model_pairs:
            raise RuntimeError(
                "Piper model files were not found. Expected .onnx and .onnx.json pairs "
                f"in {self._model_dir}."
            )
        default_stem = (
            self.DEFAULT_MODEL_STEM
            if self.DEFAULT_MODEL_STEM in model_pairs
            else sorted(model_pairs)[0]
        )
        self._model_path = model_pairs[default_stem][0]
        self._config_path = model_pairs[default_stem][1]
        self._voice_loader = voice_loader
        self._wav_player = wav_player
        self._render_in_subprocess = (
            render_in_subprocess
            if render_in_subprocess is not None
            else sys.platform.startswith("win")
            and voice_loader is None
        )
        self._espeak_data_dir: Path | None = None
        self._piper_voice_class = None
        self._voices_by_model_path: dict[Path, Any] = {}

    def list_voices(self) -> list[VoiceDescriptor]:
        voices: list[VoiceDescriptor] = []
        for stem, (_, config_path) in sorted(self._discover_model_pairs().items()):
            voices.append(
                VoiceDescriptor(
                    id=self._voice_id_for_stem(stem),
                    name=self._voice_name_for_stem(stem, config_path),
                    languages=self._languages_for_stem(stem, config_path),
                )
            )
        return voices

    def _discover_model_pairs(self) -> dict[str, tuple[Path, Path]]:
        pairs: dict[str, tuple[Path, Path]] = {}
        if not self._model_dir.exists():
            return pairs
        for model_path in self._model_dir.glob("*.onnx"):
            config_path = model_path.with_name(f"{model_path.name}.json")
            if config_path.exists():
                pairs[model_path.stem] = (model_path, config_path)
        return pairs

    def _voice_id_for_stem(self, stem: str) -> str:
        return f"piper:{stem}"

    def _stem_for_voice_id(self, voice_id: str | None) -> str | None:
        if not voice_id:
            return None
        prefix = "piper:"
        if not voice_id.startswith(prefix):
            return None
        stem = voice_id[len(prefix) :].strip()
        return stem or None

    def _voice_name_for_stem(self, stem: str, config_path: Path) -> str:
        if stem == self.DEFAULT_MODEL_STEM:
            return self.VOICE_NAME
        metadata = self._read_voice_metadata(config_path)
        name = self._metadata_text(metadata, ("name", "voice", "speaker"))
        if name:
            return f"Piper {name}"
        return "Piper " + stem.replace("_", " ").replace("-", " ").title()

    def _languages_for_stem(self, stem: str, config_path: Path) -> tuple[str, ...]:
        metadata = self._read_voice_metadata(config_path)
        language = metadata.get("language")
        if isinstance(language, dict):
            language_code = self._metadata_text(language, ("code", "name"))
            if language_code:
                return (language_code,)
        elif isinstance(language, str) and language.strip():
            return (language.strip(),)

        match = re.match(r"^([a-z]{2}_[A-Z]{2})\b", stem)
        if match:
            return (match.group(1),)
        match = re.match(r"^([a-z]{2})\b", stem)
        if match:
            return (match.group(1),)
        return ()

    def _read_voice_metadata(self, config_path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _metadata_text(self, metadata: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = metadata.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def play(
        self,
        plan: SpeechPlan,
        settings: PlaybackSettings,
        on_event: Optional[Callable[[PlaybackEvent], None]] = None,
    ) -> PlaybackSession:
        units = tuple(self._iter_units(plan))
        session = PlaybackSession(total_units=len(units))
        request = _PlayRequest(
            plan=plan,
            units=units,
            settings=settings,
            session=session,
            on_event=on_event,
        )

        self._mark_session(session, PlaybackState.PLAYING, started=True)
        self._emit_event(request, PlaybackEventType.STARTED, PlaybackState.PLAYING)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            output_path = Path(temp_file.name)

        try:
            if self._stop_event.is_set():
                self._finish_stopped(request, "Playback was stopped before synthesis.")
                self._stop_event.clear()
                return session

            finished_units = self._write_plan_wav(request, output_path)
            if self._stop_event.is_set():
                self._finish_stopped(request, "Playback was stopped before audio playback.")
                self._stop_event.clear()
                return session

            self._play_wav(output_path, self._stop_event)
            if self._stop_event.is_set():
                self._finish_stopped(request, "Playback was stopped.")
                self._stop_event.clear()
                return session

            self._emit_finished_units(request, finished_units)
            self._mark_session(session, PlaybackState.COMPLETED, finished=True)
            self._emit_event(request, PlaybackEventType.COMPLETED, PlaybackState.COMPLETED)
            with self._condition:
                self._state = PlaybackState.COMPLETED
            return session
        except Exception as exc:
            message = self._format_error(exc)
            self._mark_session(
                session,
                PlaybackState.ERROR,
                finished=True,
                error_message=message,
            )
            self._emit_event(
                request,
                PlaybackEventType.ERROR,
                PlaybackState.ERROR,
                message=message,
                error=message,
            )
            with self._condition:
                self._state = PlaybackState.ERROR
            return session
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass

    def wait_until_finished(
        self,
        session: PlaybackSession,
        timeout: Optional[float] = None,
    ) -> PlaybackState:
        return session.state

    def stop(self) -> None:
        self._stop_event.set()
        if sys.platform.startswith("win"):
            try:
                winsound = importlib.import_module("winsound")
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        with self._condition:
            if self._state != PlaybackState.SHUTDOWN:
                self._state = PlaybackState.STOPPING
            self._condition.notify_all()

    def get_state(self) -> PlaybackState:
        with self._condition:
            return self._state

    def shutdown(self) -> None:
        self.stop()
        with self._condition:
            self._state = PlaybackState.SHUTDOWN
            self._condition.notify_all()

    def _write_plan_wav(
        self,
        request: _PlayRequest,
        output_path: Path,
    ) -> list[tuple[int, SpeechUnit]]:
        if self._render_in_subprocess:
            return self._write_plan_wav_in_subprocess(request, output_path)

        segments: list[tuple[int, SpeechUnit, tuple[int, int, int], bytes]] = []
        finished_units: list[tuple[int, SpeechUnit]] = []
        speech_params: tuple[int, int, int] | None = None

        for index, unit in enumerate(request.units):
            if self._stop_event.is_set():
                self._finish_stopped(request, "Playback was stopped during synthesis.")
                return finished_units
            self._emit_event(
                request,
                PlaybackEventType.UNIT_STARTED,
                PlaybackState.PLAYING,
                unit=unit,
                unit_index=index,
            )
            if self._is_pause_unit(unit):
                segments.append(
                    (
                        index,
                        unit,
                        self.DEFAULT_WAV_PARAMS,
                        self._pause_marker_bytes(unit),
                    )
                )
            elif self._audio_path_for_unit(unit):
                params, frames = self._read_wav_frames(self._audio_path_for_unit(unit))
                segments.append((index, unit, params, frames))
            else:
                unit_parts: list[bytes] = []
                unit_params: tuple[int, int, int] | None = None
                for synth_text in self._iter_synthesis_texts(unit, request.settings):
                    if self._stop_event.is_set():
                        self._finish_stopped(request, "Playback was stopped during synthesis.")
                        return finished_units
                    params, frames = self._synthesize_text(synth_text, request.settings, unit)
                    if unit_params is None:
                        unit_params = params
                    elif params != unit_params:
                        raise RuntimeError("Piper returned incompatible WAV parameters.")
                    if speech_params is None:
                        speech_params = params
                    elif params != speech_params:
                        raise RuntimeError("Piper returned incompatible WAV parameters.")
                    unit_parts.append(frames)
                if unit_params is None:
                    unit_params = speech_params or self.DEFAULT_WAV_PARAMS
                segments.append((index, unit, unit_params, b"".join(unit_parts)))
            finished_units.append((index, unit))

        output_params = speech_params or self._first_segment_params(segments)
        with wave.open(str(output_path), "wb") as output_wav:
            channels, sample_width, frame_rate = output_params
            output_wav.setnchannels(channels)
            output_wav.setsampwidth(sample_width)
            output_wav.setframerate(frame_rate)
            for _, unit, params, frames in segments:
                if self._is_pause_unit(unit):
                    output_wav.writeframes(self._silence_frames(unit, output_params))
                else:
                    output_wav.writeframes(
                        self._convert_wav_frames(frames, params, output_params)
                    )
        return finished_units

    def _write_plan_wav_in_subprocess(
        self,
        request: _PlayRequest,
        output_path: Path,
    ) -> list[tuple[int, SpeechUnit]]:
        finished_units: list[tuple[int, SpeechUnit]] = []
        for index, unit in enumerate(request.units):
            if self._stop_event.is_set():
                return finished_units
            self._emit_event(
                request,
                PlaybackEventType.UNIT_STARTED,
                PlaybackState.PLAYING,
                unit=unit,
                unit_index=index,
            )
            finished_units.append((index, unit))

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as job_file:
            job_path = Path(job_file.name)
            json.dump(self._subprocess_render_job(request, output_path), job_file)

        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                self._piper_render_command(job_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=self._subprocess_startupinfo(),
            )
            while process.poll() is None:
                if self._stop_event.is_set():
                    self._terminate_process(process)
                    return finished_units
                time.sleep(0.05)

            stdout, stderr = process.communicate()
            if process.returncode != 0:
                detail = (stderr or stdout or "").strip()
                message = f"Piper render process failed with exit code {process.returncode}."
                if detail:
                    message += f" {detail}"
                raise RuntimeError(message)
            if not output_path.exists() or output_path.stat().st_size <= 0:
                raise RuntimeError("Piper render process produced an empty WAV.")
            return finished_units
        finally:
            if process is not None and process.poll() is None:
                self._terminate_process(process)
            try:
                job_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _subprocess_render_job(self, request: _PlayRequest, output_path: Path) -> dict[str, Any]:
        english_voice_id, chinese_voice_id = self._selected_voice_ids(request.settings)
        return {
            "model_dir": str(self._model_dir),
            "output_path": str(output_path),
            "source_text": str(getattr(request.plan, "source_text", "")),
            "rate": getattr(request.settings, "rate", 200),
            "volume": getattr(request.settings, "volume", 1.0),
            "english_voice_id": english_voice_id,
            "chinese_voice_id": chinese_voice_id,
            "units": [self._unit_payload(unit, request.settings) for unit in request.units],
        }

    def _unit_payload(
        self,
        unit: SpeechUnit,
        settings: PlaybackSettings | None = None,
    ) -> dict[str, Any]:
        span = getattr(unit, "span", None)
        return {
            "index": getattr(unit, "index", 0),
            "source_text": str(getattr(unit, "source_text", "")),
            "span": {
                "start": getattr(span, "start", 0),
                "end": getattr(span, "end", 0),
            },
            "action": self._enumish_text(getattr(unit, "action", None)),
            "voice_role": self._enumish_text(self._get_voice_role(unit)),
            "speak_text": self._piper_speak_text(settings, unit),
            "pause_ms": getattr(unit, "pause_ms", 0),
            "audio_path": self._audio_path_for_unit(unit),
        }

    def _piper_render_command(self, job_path: Path) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--piper-render", str(job_path)]
        return [sys.executable, "-m", "app.main", "--piper-render", str(job_path)]

    def _subprocess_startupinfo(self) -> Any:
        startupinfo_class = getattr(subprocess, "STARTUPINFO", None)
        startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        if startupinfo_class is None or not sys.platform.startswith("win"):
            return None
        startupinfo = startupinfo_class()
        startupinfo.dwFlags |= startf_use_showwindow
        return startupinfo

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _emit_finished_units(
        self,
        request: _PlayRequest,
        finished_units: Sequence[tuple[int, SpeechUnit]],
    ) -> None:
        for unit_index, unit in finished_units:
            self._emit_event(
                request,
                PlaybackEventType.UNIT_FINISHED,
                PlaybackState.PLAYING,
                unit=unit,
                unit_index=unit_index,
            )

    def _synthesize_text(
        self,
        text: str,
        settings: PlaybackSettings,
        unit: SpeechUnit | None = None,
    ) -> tuple[tuple[int, int, int], bytes]:
        buffer = io.BytesIO()
        voice = self._load_voice(self._model_path_for_unit(settings, unit))
        try:
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(
                    text,
                    wav_file,
                    syn_config=self._build_synthesis_config(settings),
                )
        except TypeError:
            buffer.seek(0)
            buffer.truncate(0)
            with wave.open(buffer, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
        buffer.seek(0)
        with wave.open(buffer, "rb") as wav_file:
            params = (
                wav_file.getnchannels(),
                wav_file.getsampwidth(),
                wav_file.getframerate(),
            )
            return params, wav_file.readframes(wav_file.getnframes())

    def _read_wav_frames(self, audio_path: str | Path | None) -> tuple[tuple[int, int, int], bytes]:
        if audio_path is None:
            raise RuntimeError("Missing custom audio file path.")
        resolved_path = Path(str(audio_path)).expanduser()
        with wave.open(str(resolved_path), "rb") as wav_file:
            params = (
                wav_file.getnchannels(),
                wav_file.getsampwidth(),
                wav_file.getframerate(),
            )
            return params, wav_file.readframes(wav_file.getnframes())

    def _first_segment_params(
        self,
        segments: Sequence[tuple[int, SpeechUnit, tuple[int, int, int], bytes]],
    ) -> tuple[int, int, int]:
        for _, unit, params, _ in segments:
            if not self._is_pause_unit(unit):
                return params
        return self.DEFAULT_WAV_PARAMS

    def _convert_wav_frames(
        self,
        frames: bytes,
        source_params: tuple[int, int, int],
        target_params: tuple[int, int, int],
    ) -> bytes:
        if source_params == target_params:
            return frames
        raise RuntimeError(
            "Custom WAV files must use the same audio format as the selected Piper voice."
        )

    def _iter_synthesis_texts(
        self,
        unit: SpeechUnit,
        settings: PlaybackSettings | None = None,
    ) -> list[str]:
        text = self._piper_speak_text(settings, unit).strip()
        if not text:
            return []
        if self._enumish_text(getattr(unit, "action", None)) == "spell_letter":
            parts = [part for part in text.split() if part]
            if parts:
                return [self._letter_name(part) for part in parts]
        parts = [part for part in re.split(r"\s+", text) if part]
        if len(parts) > 1:
            return parts
        return [text]

    def _piper_speak_text(
        self,
        settings: PlaybackSettings | None,
        unit: SpeechUnit,
    ) -> str:
        text = self._get_speak_text(unit)
        if settings is None or not self._piper_needs_english_safe_text(settings, unit, text):
            return text
        return self._english_safe_text(unit, text)

    def _piper_needs_english_safe_text(
        self,
        settings: PlaybackSettings,
        unit: SpeechUnit,
        text: str,
    ) -> bool:
        if text.isascii():
            return False
        if not self._is_chinese_role(self._get_voice_role(unit)):
            return False
        model_path = self._model_path_for_unit(settings, unit)
        return not self._piper_model_looks_chinese(model_path)

    def _piper_model_looks_chinese(self, model_path: Path) -> bool:
        pair = self._discover_model_pairs().get(model_path.stem)
        config_path = pair[1] if pair is not None else Path(f"{model_path}.json")
        metadata = self._read_voice_metadata(config_path)
        values = [
            model_path.stem,
            self._metadata_text(metadata, ("name", "voice", "speaker")),
        ]
        language = metadata.get("language")
        if isinstance(language, dict):
            values.append(self._metadata_text(language, ("code", "name")))
        elif isinstance(language, str):
            values.append(language)
        normalized = " ".join(values).lower().replace("-", "_")
        return any(marker in normalized for marker in ("zh", "chinese", "mandarin"))

    def _english_safe_text(self, unit: SpeechUnit, text: str) -> str:
        action = self._enumish_text(getattr(unit, "action", None))
        source_text = str(getattr(unit, "source_text", "") or "")
        if action == "read_number" and source_text.isdigit():
            return " ".join(source_text)
        if action == "read_symbol":
            reading_name = self.CHINESE_READING_ENGLISH_NAMES.get(text)
            if reading_name:
                return reading_name
            if text == SYMBOL_TO_CHINESE.get(source_text):
                symbol_name = self.SYMBOL_ENGLISH_NAMES.get(source_text)
                if symbol_name:
                    return symbol_name
            return text
        return source_text if source_text.isascii() and source_text.strip() else text

    def _letter_name(self, text: str) -> str:
        if len(text) == 1 and text.isascii() and text.isalpha():
            return self.LETTER_NAMES.get(text.upper(), text)
        return text

    def _load_voice(self, model_path: Path | None = None) -> Any:
        resolved_model_path = model_path or self._model_path
        if resolved_model_path in self._voices_by_model_path:
            return self._voices_by_model_path[resolved_model_path]
        if self._voice_loader is not None:
            voice = self._voice_loader(resolved_model_path)
            self._voices_by_model_path[resolved_model_path] = voice
            return voice
        piper_voice = self._piper_voice_class or self._load_piper_voice_class()
        self._piper_voice_class = piper_voice
        espeak_data_dir = self._resolve_espeak_data_dir()
        self._prepare_espeak_runtime(espeak_data_dir)
        voice = self._load_real_piper_voice(
            piper_voice,
            resolved_model_path,
            espeak_data_dir,
        )
        self._voices_by_model_path[resolved_model_path] = voice
        return voice

    def _load_real_piper_voice(
        self,
        piper_voice: Any,
        model_path: Path,
        espeak_data_dir: Path,
    ) -> Any:
        try:
            return self._load_piper_voice_with_limited_cpu(
                piper_voice,
                model_path,
                espeak_data_dir,
            )
        except Exception:
            return piper_voice.load(
                str(model_path),
                espeak_data_dir=espeak_data_dir,
            )

    def _load_piper_voice_with_limited_cpu(
        self,
        piper_voice: Any,
        model_path: Path,
        espeak_data_dir: Path,
    ) -> Any:
        config_path = Path(f"{model_path}.json")
        config_payload = json.loads(config_path.read_text(encoding="utf-8"))
        config_module = importlib.import_module("piper.config")
        onnxruntime = importlib.import_module("onnxruntime")

        session_options = onnxruntime.SessionOptions()
        cpu_threads = self._piper_cpu_threads()
        session_options.intra_op_num_threads = cpu_threads
        session_options.inter_op_num_threads = 1
        execution_mode = getattr(onnxruntime, "ExecutionMode", None)
        if execution_mode is not None and hasattr(execution_mode, "ORT_SEQUENTIAL"):
            session_options.execution_mode = execution_mode.ORT_SEQUENTIAL
        self._disable_onnx_spinning(session_options)

        return piper_voice(
            config=config_module.PiperConfig.from_dict(config_payload),
            session=onnxruntime.InferenceSession(
                str(model_path),
                sess_options=session_options,
                providers=["CPUExecutionProvider"],
            ),
            espeak_data_dir=Path(espeak_data_dir),
            download_dir=Path.cwd(),
        )

    def _disable_onnx_spinning(self, session_options: Any) -> None:
        add_entry = getattr(session_options, "add_session_config_entry", None)
        if not callable(add_entry):
            return
        for key in (
            "session.intra_op.allow_spinning",
            "session.inter_op.allow_spinning",
        ):
            try:
                add_entry(key, "0")
            except Exception:
                pass

    def _piper_cpu_threads(self) -> int:
        raw_value = os.environ.get(self.THREADS_ENV_VAR)
        if raw_value:
            try:
                requested_threads = int(raw_value)
            except ValueError:
                requested_threads = self.DEFAULT_CPU_THREADS
        else:
            requested_threads = self.DEFAULT_CPU_THREADS
        return max(1, min(4, requested_threads))

    def _model_path_for_unit(
        self,
        settings: PlaybackSettings,
        unit: SpeechUnit | None,
    ) -> Path:
        english_voice_id, chinese_voice_id = self._selected_voice_ids(settings)
        selected_voice_id = english_voice_id
        if unit is not None and self._is_chinese_role(self._get_voice_role(unit)):
            selected_voice_id = chinese_voice_id or english_voice_id
        stem = self._stem_for_voice_id(selected_voice_id)
        if stem is None:
            return self._model_path
        pair = self._discover_model_pairs().get(stem)
        if pair is None:
            return self._model_path
        return pair[0]

    def _selected_voice_ids(
        self,
        settings: PlaybackSettings,
    ) -> tuple[Optional[str], Optional[str]]:
        selection = getattr(settings, "voice_selection", None)
        if selection is None:
            selection = getattr(settings, "voices", None)
        if selection is None:
            return (None, None)
        return (
            getattr(selection, "english_voice_id", getattr(selection, "english_id", None)),
            getattr(selection, "chinese_voice_id", getattr(selection, "chinese_id", None)),
        )

    def _get_voice_role(self, unit: SpeechUnit) -> Any:
        for attr in ("voice_role", "role", "language_role"):
            value = getattr(unit, attr, None)
            if value is not None:
                return value
        return getattr(VoiceRole, "ENGLISH", "english")

    def _is_chinese_role(self, role: Any) -> bool:
        normalized = self._enumish_text(role)
        return normalized in {"chinese", "zh", "zh_cn", "mandarin"}

    def _load_piper_voice_class(self) -> Any:
        try:
            piper_module = importlib.import_module("piper")
            piper_voice = getattr(piper_module, "PiperVoice", None)
            if piper_voice is not None:
                return piper_voice
        except ImportError:
            pass
        try:
            voice_module = importlib.import_module("piper.voice")
            return getattr(voice_module, "PiperVoice")
        except ImportError as exc:
            raise RuntimeError(
                "piper-tts is required for Piper playback. Install piper-tts or use fallback SAPI."
            ) from exc

    def _build_synthesis_config(self, settings: PlaybackSettings) -> Any:
        length_scale = self._rate_to_length_scale(getattr(settings, "rate", 200))
        try:
            config_module = importlib.import_module("piper.config")
            synthesis_config = getattr(config_module, "SynthesisConfig", None)
            if synthesis_config is not None:
                return synthesis_config(length_scale=length_scale)
        except Exception:
            return None
        return None

    def _rate_to_length_scale(self, rate: Any) -> float:
        try:
            numeric_rate = float(rate)
        except (TypeError, ValueError):
            numeric_rate = 200.0
        numeric_rate = max(80.0, min(260.0, numeric_rate))
        return max(0.6, min(1.6, 200.0 / numeric_rate))

    def _play_wav(self, path: Path, stop_event: threading.Event) -> None:
        if self._wav_player is not None:
            self._wav_player(path, stop_event)
            return
        if stop_event.is_set():
            return
        if sys.platform.startswith("win"):
            winsound = importlib.import_module("winsound")
            winsound.PlaySound(str(path), winsound.SND_FILENAME)

    def _silence_frames(self, unit: SpeechUnit, params: tuple[int, int, int]) -> bytes:
        channels, sample_width, frame_rate = params
        frame_count = int(round(self._get_pause_seconds(unit) * frame_rate))
        return b"\x00" * frame_count * channels * sample_width

    def _pause_marker_bytes(self, unit: SpeechUnit) -> bytes:
        return str(self._get_pause_seconds(unit)).encode("ascii", errors="ignore")

    def _resolve_model_dir(self, model_dir: str | Path | None) -> Path:
        if model_dir is not None:
            return Path(model_dir)
        candidates = [
            Path(getattr(sys, "_MEIPASS", "")) / "app" / "voices" / "piper",
            Path(__file__).resolve().parent / "voices" / "piper",
            Path.cwd() / "app" / "voices" / "piper",
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate
        return Path(__file__).resolve().parent / "voices" / "piper"

    def _resolve_espeak_data_dir(self) -> Path:
        if self._espeak_data_dir is not None:
            return self._espeak_data_dir

        candidates = [
            Path(getattr(sys, "_MEIPASS", "")) / "piper" / "espeak-ng-data",
            Path(sys.executable).resolve().parent / "piper" / "espeak-ng-data",
            Path.cwd() / "piper" / "espeak-ng-data",
        ]
        try:
            phonemize_module = importlib.import_module("piper.phonemize_espeak")
            espeak_data_dir = getattr(phonemize_module, "ESPEAK_DATA_DIR", None)
            if espeak_data_dir is not None:
                candidates.append(Path(espeak_data_dir))
        except Exception:
            pass

        for candidate in candidates:
            if candidate and (candidate / "phondata").exists():
                self._espeak_data_dir = self._stage_espeak_data_dir(candidate)
                return self._espeak_data_dir

        checked = ", ".join(str(candidate) for candidate in candidates if candidate)
        raise RuntimeError("Bundled Piper espeak-ng-data was not found. Checked: " + checked)

    def _stage_espeak_data_dir(self, source_dir: Path) -> Path:
        source_dir = source_dir.resolve()
        if not sys.platform.startswith("win") and self._is_ascii_path(source_dir):
            return source_dir

        target_dir = (
            Path(tempfile.gettempdir())
            / "EnglishSpellReader"
            / "piper-espeak-ng-data"
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
        staged_dir = target_dir.resolve()
        short_path = self._windows_short_path(staged_dir)
        if short_path is not None and (short_path / "phondata").exists():
            return short_path
        return staged_dir

    def _is_ascii_path(self, path: Path) -> bool:
        try:
            str(path).encode("ascii")
        except UnicodeEncodeError:
            return False
        return True

    def _windows_short_path(self, path: Path) -> Path | None:
        if not sys.platform.startswith("win"):
            return None
        try:
            import ctypes
            from ctypes import wintypes

            get_short_path_name = ctypes.windll.kernel32.GetShortPathNameW
            get_short_path_name.argtypes = [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                wintypes.DWORD,
            ]
            get_short_path_name.restype = wintypes.DWORD

            buffer_length = get_short_path_name(str(path), None, 0)
            if buffer_length == 0:
                return None
            buffer = ctypes.create_unicode_buffer(buffer_length)
            result = get_short_path_name(str(path), buffer, buffer_length)
            if result == 0:
                return None
            short_path = Path(buffer.value)
            if self._is_ascii_path(short_path):
                return short_path
        except Exception:
            return None
        return None

    def _prepare_espeak_runtime(self, espeak_data_dir: Path) -> None:
        os.environ["ESPEAK_DATA_PATH"] = str(espeak_data_dir)
        try:
            phonemize_module = importlib.import_module("piper.phonemize_espeak")
            setattr(phonemize_module, "ESPEAK_DATA_DIR", espeak_data_dir)
        except Exception:
            pass

    def _iter_units(self, plan: SpeechPlan) -> Sequence[SpeechUnit]:
        units = getattr(plan, "units", None)
        if units is None and isinstance(plan, Sequence):
            return plan
        if units is None:
            return ()
        return units

    def _is_pause_unit(self, unit: SpeechUnit) -> bool:
        candidates = (
            getattr(unit, "action", None),
            getattr(unit, "unit_type", None),
            getattr(unit, "kind", None),
            getattr(unit, "type", None),
        )
        return any(self._enumish_text(candidate) == "pause" for candidate in candidates)

    def _get_pause_seconds(self, unit: SpeechUnit) -> float:
        pause_ms = getattr(unit, "pause_ms", None)
        if pause_ms is not None:
            try:
                return max(0.0, float(pause_ms) / 1000.0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _get_speak_text(self, unit: SpeechUnit) -> str:
        text = getattr(unit, "speak_text", None)
        if text is None:
            text = getattr(unit, "text", "")
        return str(text)

    def _audio_path_for_unit(self, unit: SpeechUnit) -> str | None:
        audio_path = getattr(unit, "audio_path", None)
        if audio_path is None:
            audio_path = getattr(unit, "audio_wav_path", None)
        if audio_path is None:
            return None
        normalized = str(audio_path).strip()
        return normalized or None

    def _mark_session(
        self,
        session: PlaybackSession,
        state: PlaybackState,
        *,
        started: bool = False,
        finished: bool = False,
        error_message: Optional[str] = None,
    ) -> None:
        with self._condition:
            session.state = state
            if started and session.started_at is None:
                session.started_at = time.time()
            if finished:
                session.finished_at = time.time()
            if error_message is not None:
                session.error_message = error_message
            self._condition.notify_all()

    def _finish_stopped(self, request: _PlayRequest, message: str) -> None:
        self._mark_session(request.session, PlaybackState.STOPPED, finished=True)
        self._emit_event(
            request,
            PlaybackEventType.STOPPED,
            PlaybackState.STOPPED,
            message=message,
        )
        with self._condition:
            self._state = PlaybackState.STOPPED

    def _emit_event(
        self,
        request: _PlayRequest,
        event_type: PlaybackEventType,
        state: PlaybackState,
        *,
        unit: Optional[SpeechUnit] = None,
        unit_index: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        callback = request.on_event
        if callback is None:
            return
        event = PlaybackEvent(
            event_type=event_type,
            session=request.session,
            state=state,
            unit=unit,
            unit_index=unit_index,
            message=message,
            error=error,
        )
        try:
            callback(event)
        except Exception:
            logging.getLogger(__name__).debug("Playback event callback failed.", exc_info=True)

    def _format_error(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__

    def _enumish_text(self, value: Any) -> str:
        if value is None:
            return ""
        name = getattr(value, "name", None)
        if isinstance(name, str) and name:
            return name.strip().lower()
        raw_value = getattr(value, "value", value)
        return str(raw_value).strip().lower()


class MicrosoftEdgeSpeechEngine:
    """Microsoft neural voice playback through edge-tts."""

    VOICE_PREFIX = "edge:"
    CLEAR_VOICES = (("en-US-RogerNeural", "Microsoft Clear Roger"),)
    CHINESE_READING_ENGLISH_NAMES = PiperSpeechEngine.CHINESE_READING_ENGLISH_NAMES
    SYMBOL_ENGLISH_NAMES = PiperSpeechEngine.SYMBOL_ENGLISH_NAMES
    LETTER_NAMES = PiperSpeechEngine.LETTER_NAMES

    def __init__(
        self,
        *,
        temp_dir: str | Path | None = None,
        audio_player: Optional[Callable[[str | Path, threading.Event], None]] = None,
    ) -> None:
        self._condition = threading.Condition()
        self._state = PlaybackState.IDLE
        self._stop_event = threading.Event()
        self._temp_dir = Path(temp_dir) if temp_dir is not None else None
        self._audio_player = audio_player

    def list_voices(self) -> list[VoiceDescriptor]:
        return [
            VoiceDescriptor(
                id=self._voice_id(short_name),
                name=display_name,
                languages=("en-US",),
            )
            for short_name, display_name in self.CLEAR_VOICES
        ]

    def play(
        self,
        plan: SpeechPlan,
        settings: PlaybackSettings,
        on_event: Optional[Callable[[PlaybackEvent], None]] = None,
    ) -> PlaybackSession:
        units = tuple(self._iter_units(plan))
        session = PlaybackSession(total_units=len(units))
        request = _PlayRequest(
            plan=plan,
            units=units,
            settings=settings,
            session=session,
            on_event=on_event,
        )

        self._mark_session(session, PlaybackState.PLAYING, started=True)
        self._emit_event(request, PlaybackEventType.STARTED, PlaybackState.PLAYING)
        with self._condition:
            self._state = PlaybackState.PLAYING

        try:
            self._run_request(request)
            if self._stop_event.is_set():
                self._finish_stopped(request, "Playback was stopped.")
                self._stop_event.clear()
                return session

            self._mark_session(session, PlaybackState.COMPLETED, finished=True)
            self._emit_event(request, PlaybackEventType.COMPLETED, PlaybackState.COMPLETED)
            with self._condition:
                self._state = PlaybackState.COMPLETED
            return session
        except Exception as exc:
            message = self._format_error(exc)
            self._mark_session(
                session,
                PlaybackState.ERROR,
                finished=True,
                error_message=message,
            )
            self._emit_event(
                request,
                PlaybackEventType.ERROR,
                PlaybackState.ERROR,
                message=message,
                error=message,
            )
            with self._condition:
                self._state = PlaybackState.ERROR
            return session

    def wait_until_finished(
        self,
        session: PlaybackSession,
        timeout: Optional[float] = None,
    ) -> PlaybackState:
        return session.state

    def stop(self) -> None:
        self._stop_event.set()
        with self._condition:
            if self._state != PlaybackState.SHUTDOWN:
                self._state = PlaybackState.STOPPING
            self._condition.notify_all()

    def shutdown(self) -> None:
        self.stop()
        with self._condition:
            self._state = PlaybackState.SHUTDOWN
            self._condition.notify_all()

    def get_state(self) -> PlaybackState:
        with self._condition:
            return self._state

    def _run_request(self, request: _PlayRequest) -> None:
        for index, unit in enumerate(request.units):
            if self._stop_event.is_set():
                return
            self._emit_event(
                request,
                PlaybackEventType.UNIT_STARTED,
                PlaybackState.PLAYING,
                unit=unit,
                unit_index=index,
            )
            if self._is_pause_unit(unit):
                self._sleep_pause(self._get_pause_seconds(unit), self._stop_event)
            elif self._audio_path_for_unit(unit):
                self._play_audio_file(self._audio_path_for_unit(unit), self._stop_event)
            else:
                self._render_and_play_unit(unit, request.settings)
            if self._stop_event.is_set():
                return
            self._emit_event(
                request,
                PlaybackEventType.UNIT_FINISHED,
                PlaybackState.PLAYING,
                unit=unit,
                unit_index=index,
            )

    def _render_and_play_unit(self, unit: SpeechUnit, settings: PlaybackSettings) -> None:
        for text in self._iter_synthesis_texts(settings, unit):
            if self._stop_event.is_set():
                return
            suffix = ".mp3"
            temp_kwargs: dict[str, Any] = {"suffix": suffix, "delete": False}
            if self._temp_dir is not None:
                self._temp_dir.mkdir(parents=True, exist_ok=True)
                temp_kwargs["dir"] = str(self._temp_dir)
            with tempfile.NamedTemporaryFile(**temp_kwargs) as temp_file:
                audio_path = Path(temp_file.name)
            try:
                self._run_async(self._communicate(text, settings).save(str(audio_path)))
                self._play_audio_file(str(audio_path), self._stop_event)
            finally:
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _communicate(self, text: str, settings: PlaybackSettings) -> Any:
        edge_tts = self._load_edge_tts()
        return edge_tts.Communicate(
            text,
            self._selected_edge_voice(settings),
            rate=self._edge_rate(getattr(settings, "rate", 200)),
            volume=self._edge_volume(getattr(settings, "volume", 1.0)),
            pitch="+0Hz",
        )

    def _selected_edge_voice(self, settings: PlaybackSettings) -> str:
        english_voice_id, _ = self._selected_voice_ids(settings)
        if isinstance(english_voice_id, str) and english_voice_id.startswith(self.VOICE_PREFIX):
            short_name = english_voice_id[len(self.VOICE_PREFIX) :].strip()
            if short_name:
                return short_name
        return self.CLEAR_VOICES[0][0]

    def _load_edge_tts(self) -> Any:
        try:
            return importlib.import_module("edge_tts")
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is required for Microsoft neural voice playback."
            ) from exc

    def _play_audio_file(self, audio_path: str | Path | None, stop_event: threading.Event) -> None:
        if audio_path is None or stop_event.is_set():
            return
        if self._audio_player is not None:
            self._audio_player(audio_path, stop_event)
            return
        if sys.platform.startswith("win"):
            self._play_windows_media_file(Path(audio_path).expanduser(), stop_event)

    def _play_windows_media_file(self, audio_path: Path, stop_event: threading.Event) -> None:
        import ctypes

        alias = f"edge_tts_{uuid.uuid4().hex}"
        winmm = ctypes.windll.winmm

        def send(command: str) -> None:
            buffer = ctypes.create_unicode_buffer(512)
            result = winmm.mciSendStringW(command, buffer, len(buffer), None)
            if result != 0:
                raise RuntimeError(f"Windows media playback failed: {command}")

        try:
            send(f'open "{audio_path}" type mpegvideo alias {alias}')
            send(f"play {alias}")
            while not stop_event.is_set():
                status_buffer = ctypes.create_unicode_buffer(128)
                result = winmm.mciSendStringW(
                    f"status {alias} mode",
                    status_buffer,
                    len(status_buffer),
                    None,
                )
                if result != 0 or status_buffer.value.lower() not in {"playing", "seeking"}:
                    break
                time.sleep(0.05)
            if stop_event.is_set():
                try:
                    send(f"stop {alias}")
                except Exception:
                    pass
        finally:
            try:
                send(f"close {alias}")
            except Exception:
                pass

    def _sleep_pause(self, seconds: float, stop_event: threading.Event) -> None:
        remaining = max(0.0, seconds)
        while remaining > 0 and not stop_event.is_set():
            chunk = min(0.05, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _run_async(self, awaitable: Any) -> Any:
        import asyncio

        return asyncio.run(awaitable)

    def _voice_id(self, short_name: str) -> str:
        return f"{self.VOICE_PREFIX}{short_name}"

    def _edge_rate(self, rate: Any) -> str:
        try:
            numeric_rate = int(round(float(rate)))
        except (TypeError, ValueError):
            numeric_rate = 200
        percent = int(round(((max(80, min(260, numeric_rate)) - 200) / 200) * 100))
        return f"{percent:+d}%"

    def _edge_volume(self, volume: Any) -> str:
        try:
            numeric_volume = float(volume)
        except (TypeError, ValueError):
            numeric_volume = 1.0
        if numeric_volume > 1.0:
            numeric_volume = numeric_volume / 100.0
        percent = int(round((max(0.0, min(1.0, numeric_volume)) - 1.0) * 100))
        return f"{percent:+d}%"

    def _iter_units(self, plan: SpeechPlan) -> Sequence[SpeechUnit]:
        units = getattr(plan, "units", None)
        if units is None and isinstance(plan, Sequence):
            return plan
        if units is None:
            return ()
        return units

    def _is_pause_unit(self, unit: SpeechUnit) -> bool:
        candidates = (
            getattr(unit, "action", None),
            getattr(unit, "unit_type", None),
            getattr(unit, "kind", None),
            getattr(unit, "type", None),
        )
        return any(self._enumish_text(candidate) == "pause" for candidate in candidates)

    def _get_pause_seconds(self, unit: SpeechUnit) -> float:
        pause_ms = getattr(unit, "pause_ms", None)
        if pause_ms is not None:
            try:
                return max(0.0, float(pause_ms) / 1000.0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _audio_path_for_unit(self, unit: SpeechUnit) -> str | None:
        audio_path = getattr(unit, "audio_path", None)
        if audio_path is None:
            audio_path = getattr(unit, "audio_wav_path", None)
        if audio_path is None:
            return None
        normalized = str(audio_path).strip()
        return normalized or None

    def _get_speak_text(self, unit: SpeechUnit) -> str:
        text = getattr(unit, "speak_text", None)
        if text is None:
            text = getattr(unit, "text", "")
        return str(text)

    def _get_driver_speak_text(self, settings: PlaybackSettings, unit: SpeechUnit) -> str:
        text = self._get_speak_text(unit)
        if not self._needs_english_safe_text(unit, text):
            return text
        return self._english_safe_text(unit, text)

    def _iter_synthesis_texts(
        self,
        settings: PlaybackSettings,
        unit: SpeechUnit,
    ) -> list[str]:
        text = self._get_driver_speak_text(settings, unit).strip()
        if not text:
            return []
        if self._enumish_text(getattr(unit, "action", None)) == "spell_letter":
            parts = [part for part in text.split() if part]
            if parts:
                return [self._letter_name(part) for part in parts]
        return [text]

    def _letter_name(self, text: str) -> str:
        if len(text) == 1 and text.isascii() and text.isalpha():
            return self.LETTER_NAMES.get(text.upper(), text)
        return text

    def _needs_english_safe_text(self, unit: SpeechUnit, text: str) -> bool:
        return not text.isascii() and self._is_chinese_role(self._get_voice_role(unit))

    def _english_safe_text(self, unit: SpeechUnit, text: str) -> str:
        action = self._enumish_text(getattr(unit, "action", None))
        source_text = str(getattr(unit, "source_text", "") or "")
        if action == "read_number" and source_text.isdigit():
            return " ".join(source_text)
        if action == "read_symbol":
            reading_name = self.CHINESE_READING_ENGLISH_NAMES.get(text)
            if reading_name:
                return reading_name
            if text == SYMBOL_TO_CHINESE.get(source_text):
                symbol_name = self.SYMBOL_ENGLISH_NAMES.get(source_text)
                if symbol_name:
                    return symbol_name
            return text
        return source_text if source_text.isascii() and source_text.strip() else text

    def _selected_voice_ids(self, settings: PlaybackSettings) -> tuple[Optional[str], Optional[str]]:
        selection = getattr(settings, "voice_selection", None)
        if selection is None:
            selection = getattr(settings, "voices", None)
        if selection is None:
            return (None, None)
        return (
            getattr(selection, "english_voice_id", getattr(selection, "english_id", None)),
            getattr(selection, "chinese_voice_id", getattr(selection, "chinese_id", None)),
        )

    def _get_voice_role(self, unit: SpeechUnit) -> Any:
        for attr in ("voice_role", "role", "language_role"):
            value = getattr(unit, attr, None)
            if value is not None:
                return value
        return getattr(VoiceRole, "ENGLISH", "english")

    def _is_chinese_role(self, role: Any) -> bool:
        normalized = self._enumish_text(role)
        return normalized in {"chinese", "zh", "zh_cn", "mandarin"}

    def _mark_session(
        self,
        session: PlaybackSession,
        state: PlaybackState,
        *,
        started: bool = False,
        finished: bool = False,
        error_message: Optional[str] = None,
    ) -> None:
        with self._condition:
            session.state = state
            if started and session.started_at is None:
                session.started_at = time.time()
            if finished:
                session.finished_at = time.time()
            if error_message is not None:
                session.error_message = error_message
            self._condition.notify_all()

    def _finish_stopped(self, request: _PlayRequest, message: str) -> None:
        self._mark_session(request.session, PlaybackState.STOPPED, finished=True)
        self._emit_event(
            request,
            PlaybackEventType.STOPPED,
            PlaybackState.STOPPED,
            message=message,
        )
        with self._condition:
            self._state = PlaybackState.STOPPED

    def _emit_event(
        self,
        request: _PlayRequest,
        event_type: PlaybackEventType,
        state: PlaybackState,
        *,
        unit: Optional[SpeechUnit] = None,
        unit_index: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        callback = request.on_event
        if callback is None:
            return
        event = PlaybackEvent(
            event_type=event_type,
            session=request.session,
            state=state,
            unit=unit,
            unit_index=unit_index,
            message=message,
            error=error,
        )
        try:
            callback(event)
        except Exception:
            logging.getLogger(__name__).debug("Playback event callback failed.", exc_info=True)

    def _format_error(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__

    def _enumish_text(self, value: Any) -> str:
        if value is None:
            return ""
        name = getattr(value, "name", None)
        if isinstance(name, str) and name:
            return name.strip().lower()
        raw_value = getattr(value, "value", value)
        return str(raw_value).strip().lower()


class SpeechEngine:
    INLINE_LETTER_PAUSE_MAX_MS = 100
    SAPI_SPEAK_XML = 8

    SYMBOL_ENGLISH_NAMES = {
        ".": "period",
        ",": "comma",
        "!": "exclamation mark",
        "?": "question mark",
        ":": "colon",
        ";": "semicolon",
        "(": "left parenthesis",
        ")": "right parenthesis",
        "[": "left bracket",
        "]": "right bracket",
        "{": "left brace",
        "}": "right brace",
        "+": "plus",
        "-": "hyphen",
        "*": "asterisk",
        "/": "slash",
        "\\": "backslash",
        "=": "equals",
        "_": "underscore",
        "@": "at sign",
        "#": "hash sign",
        "$": "dollar sign",
        "%": "percent sign",
        "&": "ampersand",
        '"': "double quote",
        "'": "single quote",
        "<": "less than",
        ">": "greater than",
        " ": "space",
        "\t": "tab",
    }
    CHINESE_READING_ENGLISH_NAMES = {
        "空格": "space",
        "空": "blank",
        "连字符": "hyphen",
        "减号": "hyphen",
    }

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._shutdown = False
        self._state = PlaybackState.IDLE
        self._active_request: Optional[_PlayRequest] = None
        self._pending_request: Optional[_PlayRequest] = None
        self._active_stop_event: Optional[threading.Event] = None
        self._active_driver: Any = None
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="speech-engine-worker",
            daemon=True,
        )
        self._worker.start()

    def list_voices(self) -> list[VoiceDescriptor]:
        driver = self._init_driver()
        try:
            raw_voices = driver.getProperty("voices") or []
            voices: list[VoiceDescriptor] = []
            for raw_voice in raw_voices:
                voice_id = self._safe_str(getattr(raw_voice, "id", None)) or ""
                name = self._safe_str(getattr(raw_voice, "name", None)) or voice_id
                languages = self._normalize_languages(getattr(raw_voice, "languages", None))
                gender = self._safe_str(getattr(raw_voice, "gender", None))
                voices.append(
                    VoiceDescriptor(
                        id=voice_id,
                        name=name or voice_id,
                        languages=languages,
                        gender=gender,
                    )
                )
            return voices
        finally:
            self._stop_driver(driver)

    def play(
        self,
        plan: SpeechPlan,
        settings: PlaybackSettings,
        on_event: Optional[Callable[[PlaybackEvent], None]] = None,
    ) -> PlaybackSession:
        units = tuple(self._iter_units(plan))
        session = PlaybackSession(total_units=len(units))
        request = _PlayRequest(
            plan=plan,
            units=units,
            settings=settings,
            session=session,
            on_event=on_event,
        )

        try:
            validation_error = self._validate_selected_voices(settings)
        except Exception as exc:
            validation_error = self._format_error(exc)
        if validation_error is not None:
            self._mark_session(session, PlaybackState.ERROR, error_message=validation_error)
            self._emit_event(
                request,
                PlaybackEventType.ERROR,
                PlaybackState.ERROR,
                message=validation_error,
                error=validation_error,
            )
            return session

        replaced_request: Optional[_PlayRequest] = None
        driver_to_stop: Any = None
        with self._condition:
            if self._shutdown:
                message = "Speech engine has been shut down."
                self._mark_session(session, PlaybackState.ERROR, error_message=message)
                self._emit_event(
                    request,
                    PlaybackEventType.ERROR,
                    PlaybackState.ERROR,
                    message=message,
                    error=message,
                )
                return session

            replaced_request = self._pending_request
            self._pending_request = request
            self._state = PlaybackState.QUEUED
            if self._active_request is not None and self._active_stop_event is not None:
                self._active_stop_event.set()
                self._state = PlaybackState.STOPPING
                driver_to_stop = self._active_driver
            self._condition.notify_all()

        if replaced_request is not None:
            self._mark_session(replaced_request.session, PlaybackState.STOPPED)
            self._emit_event(
                replaced_request,
                PlaybackEventType.STOPPED,
                PlaybackState.STOPPED,
                message="Queued playback was replaced by a newer request.",
            )

        self._stop_driver(driver_to_stop)
        return session

    def wait_until_finished(
        self,
        session: PlaybackSession,
        timeout: Optional[float] = None,
    ) -> PlaybackState:
        terminal_states = {
            PlaybackState.STOPPED,
            PlaybackState.COMPLETED,
            PlaybackState.ERROR,
        }
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)

        with self._condition:
            while session.state not in terminal_states:
                if deadline is None:
                    self._condition.wait()
                    continue

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return session.state
                self._condition.wait(remaining)

            return session.state

    def stop(self) -> None:
        pending_request: Optional[_PlayRequest] = None
        driver_to_stop: Any = None
        with self._condition:
            pending_request = self._pending_request
            self._pending_request = None
            if pending_request is not None:
                self._mark_session(pending_request.session, PlaybackState.STOPPED)
                self._state = PlaybackState.STOPPED

            if self._active_request is not None and self._active_stop_event is not None:
                self._active_stop_event.set()
                self._state = PlaybackState.STOPPING
                driver_to_stop = self._active_driver
            elif pending_request is None and self._state != PlaybackState.SHUTDOWN:
                self._state = PlaybackState.IDLE
            self._condition.notify_all()

        if pending_request is not None:
            self._emit_event(
                pending_request,
                PlaybackEventType.STOPPED,
                PlaybackState.STOPPED,
                message="Queued playback was stopped before it started.",
            )

        self._stop_driver(driver_to_stop)

    def get_state(self) -> PlaybackState:
        with self._condition:
            return self._state

    def shutdown(self) -> None:
        self.stop()
        with self._condition:
            self._shutdown = True
            self._state = PlaybackState.SHUTDOWN
            self._condition.notify_all()
        self._worker.join(timeout=5.0)

    def _worker_loop(self) -> None:
        while True:
            with self._condition:
                while not self._shutdown and self._pending_request is None:
                    self._condition.wait()

                if self._shutdown:
                    return

                request = self._pending_request
                self._pending_request = None
                stop_event = threading.Event()
                self._active_request = request
                self._active_stop_event = stop_event
                self._state = PlaybackState.PLAYING

            assert request is not None
            self._run_request(request, stop_event)

            with self._condition:
                if self._active_request is request:
                    self._active_request = None
                if self._active_stop_event is stop_event:
                    self._active_stop_event = None
                self._active_driver = None
                if self._shutdown:
                    self._state = PlaybackState.SHUTDOWN
                elif self._pending_request is not None:
                    self._state = PlaybackState.QUEUED
                elif self._state not in {
                    PlaybackState.ERROR,
                    PlaybackState.STOPPED,
                    PlaybackState.COMPLETED,
                }:
                    self._state = PlaybackState.IDLE

    def _run_request(self, request: _PlayRequest, stop_event: threading.Event) -> None:
        self._mark_session(request.session, PlaybackState.PLAYING, started=True)
        self._emit_event(request, PlaybackEventType.STARTED, PlaybackState.PLAYING)

        com_cleanup = self._initialize_worker_com()
        try:
            queued_units: list[tuple[int, SpeechUnit]] = []

            def flush_queued_units() -> bool:
                if not queued_units:
                    return True
                if not self._run_segment(request, request.settings, queued_units, stop_event):
                    return False
                queued_units.clear()
                return True

            for index, unit in enumerate(request.units):
                if stop_event.is_set():
                    self._finish_stopped(request, "Playback was stopped.")
                    return

                audio_path = self._audio_path_for_unit(unit)
                if audio_path is not None:
                    if not flush_queued_units():
                        return
                    self._emit_event(
                        request,
                        PlaybackEventType.UNIT_STARTED,
                        PlaybackState.PLAYING,
                        unit=unit,
                        unit_index=index,
                    )
                    self._play_audio_file(audio_path, stop_event)
                    if stop_event.is_set():
                        self._finish_stopped(request, "Playback was stopped during audio playback.")
                        return
                    self._emit_event(
                        request,
                        PlaybackEventType.UNIT_FINISHED,
                        PlaybackState.PLAYING,
                        unit=unit,
                        unit_index=index,
                    )
                elif self._is_pause_unit(unit):
                    if queued_units and self._is_inline_letter_pause(unit):
                        self._emit_event(
                            request,
                            PlaybackEventType.UNIT_STARTED,
                            PlaybackState.PLAYING,
                            unit=unit,
                            unit_index=index,
                        )
                        queued_units.append((index, unit))
                        continue
                    if not flush_queued_units():
                        return
                    self._emit_event(
                        request,
                        PlaybackEventType.UNIT_STARTED,
                        PlaybackState.PLAYING,
                        unit=unit,
                        unit_index=index,
                    )
                    self._sleep_pause(self._get_pause_seconds(unit), stop_event)
                    if stop_event.is_set():
                        self._finish_stopped(request, "Playback was stopped during a pause.")
                        return
                    self._emit_event(
                        request,
                        PlaybackEventType.UNIT_FINISHED,
                        PlaybackState.PLAYING,
                        unit=unit,
                        unit_index=index,
                    )
                else:
                    if queued_units and self._should_flush_before_unit(
                        queued_units[-1][1], unit
                    ):
                        if not flush_queued_units():
                            return
                    self._emit_event(
                        request,
                        PlaybackEventType.UNIT_STARTED,
                        PlaybackState.PLAYING,
                        unit=unit,
                        unit_index=index,
                    )
                    queued_units.append((index, unit))

            if not flush_queued_units():
                return

            self._mark_session(request.session, PlaybackState.COMPLETED, finished=True)
            self._emit_event(
                request,
                PlaybackEventType.COMPLETED,
                PlaybackState.COMPLETED,
            )
            with self._condition:
                self._state = PlaybackState.COMPLETED
        except Exception as exc:
            message = self._format_error(exc)
            self._mark_session(request.session, PlaybackState.ERROR, finished=True, error_message=message)
            self._emit_event(
                request,
                PlaybackEventType.ERROR,
                PlaybackState.ERROR,
                message=message,
                error=message,
            )
            with self._condition:
                self._state = PlaybackState.ERROR
        finally:
            com_cleanup()

    def _run_segment(
        self,
        request: _PlayRequest,
        settings: PlaybackSettings,
        queued_units: Sequence[tuple[int, SpeechUnit]],
        stop_event: threading.Event,
    ) -> bool:
        driver = None
        try:
            driver = self._init_driver()
            with self._condition:
                self._active_driver = driver

            if self._try_run_sapi_xml_segment(driver, request, settings, queued_units):
                return True

            for _, unit in queued_units:
                if self._is_pause_unit(unit):
                    self._sleep_pause(self._get_pause_seconds(unit), stop_event)
                    if stop_event.is_set():
                        self._finish_stopped(request, "Playback was stopped during a pause.")
                        return False
                    continue
                self._configure_driver_for_unit(driver, settings, unit)
                driver.say(self._get_driver_speak_text(settings, unit))

            driver.runAndWait()
            if stop_event.is_set():
                self._finish_stopped(request, "Playback was stopped.")
                return False

            for queued_index, queued_unit in queued_units:
                self._emit_event(
                    request,
                    PlaybackEventType.UNIT_FINISHED,
                    PlaybackState.PLAYING,
                    unit=queued_unit,
                    unit_index=queued_index,
                )
            return True
        finally:
            self._stop_driver(driver)
            with self._condition:
                if self._active_driver is driver:
                    self._active_driver = None

    def _play_audio_file(self, audio_path: str, stop_event: threading.Event) -> None:
        if stop_event.is_set():
            return
        if sys.platform.startswith("win"):
            winsound = importlib.import_module("winsound")
            winsound.PlaySound(str(Path(audio_path).expanduser()), winsound.SND_FILENAME)

    def _should_flush_before_unit(self, previous_unit: SpeechUnit, unit: SpeechUnit) -> bool:
        if self._is_inline_letter_pause(previous_unit):
            return False
        return self._enumish_text(self._get_voice_role(previous_unit)) != self._enumish_text(
            self._get_voice_role(unit)
        )

    def _is_inline_letter_pause(self, unit: SpeechUnit) -> bool:
        if not self._is_pause_unit(unit):
            return False
        if str(getattr(unit, "source_text", "")) != "":
            return False
        try:
            pause_ms = int(round(self._get_pause_seconds(unit) * 1000))
        except (TypeError, ValueError):
            return False
        return 0 <= pause_ms <= self.INLINE_LETTER_PAUSE_MAX_MS

    def _try_run_sapi_xml_segment(
        self,
        driver: Any,
        request: _PlayRequest,
        settings: PlaybackSettings,
        queued_units: Sequence[tuple[int, SpeechUnit]],
    ) -> bool:
        if not any(self._is_inline_letter_pause(unit) for _, unit in queued_units):
            return False
        sapi_driver = getattr(getattr(driver, "proxy", None), "_driver", None)
        sapi_voice = getattr(sapi_driver, "_tts", None)
        if sapi_driver is None or sapi_voice is None:
            return False
        first_spoken_unit = next(
            (unit for _, unit in queued_units if not self._is_pause_unit(unit)),
            None,
        )
        if first_spoken_unit is None:
            return False

        self._configure_sapi_driver_directly(sapi_driver, settings, first_spoken_unit)
        sapi_voice.Speak(self._sapi_xml_for_units(settings, queued_units), self.SAPI_SPEAK_XML)
        for queued_index, queued_unit in queued_units:
            self._emit_event(
                request,
                PlaybackEventType.UNIT_FINISHED,
                PlaybackState.PLAYING,
                unit=queued_unit,
                unit_index=queued_index,
            )
        return True

    def _configure_sapi_driver_directly(
        self,
        sapi_driver: Any,
        settings: PlaybackSettings,
        unit: SpeechUnit,
    ) -> None:
        english_voice_id, chinese_voice_id = self._selected_voice_ids(settings)
        role = self._get_voice_role(unit)
        selected_voice_id = chinese_voice_id if self._is_chinese_role(role) else english_voice_id
        if selected_voice_id:
            sapi_driver.setProperty("voice", selected_voice_id)
        sapi_driver.setProperty("rate", int(getattr(settings, "rate", 200)))
        sapi_driver.setProperty("volume", self._clamp_volume(getattr(settings, "volume", 1.0)))

    def _sapi_xml_for_units(
        self,
        settings: PlaybackSettings,
        queued_units: Sequence[tuple[int, SpeechUnit]],
    ) -> str:
        parts: list[str] = []
        for _, unit in queued_units:
            if self._is_inline_letter_pause(unit):
                pause_ms = int(round(self._get_pause_seconds(unit) * 1000))
                parts.append(f'<silence msec="{pause_ms}"/>')
                continue
            parts.append(html.escape(self._get_driver_speak_text(settings, unit), quote=False))
        return "".join(parts)

    def _initialize_worker_com(self) -> Callable[[], None]:
        if not sys.platform.startswith("win"):
            return lambda: None
        try:
            pythoncom = importlib.import_module("pythoncom")
        except ImportError:
            return lambda: None

        try:
            pythoncom.CoInitialize()
        except Exception:
            return lambda: None

        def cleanup() -> None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

        return cleanup

    def _finish_stopped(self, request: _PlayRequest, message: str) -> None:
        self._mark_session(request.session, PlaybackState.STOPPED, finished=True)
        self._emit_event(
            request,
            PlaybackEventType.STOPPED,
            PlaybackState.STOPPED,
            message=message,
        )
        with self._condition:
            self._state = PlaybackState.STOPPED

    def _validate_selected_voices(self, settings: PlaybackSettings) -> Optional[str]:
        selected_ids = [voice_id for voice_id in self._selected_voice_ids(settings) if voice_id]
        if not selected_ids:
            return None

        available_voices = self.list_voices()
        if not available_voices:
            return None

        available_ids = {voice.id for voice in available_voices if voice.id}
        invalid_ids = [voice_id for voice_id in selected_ids if voice_id not in available_ids]
        if invalid_ids:
            return "Selected voice id(s) not found: " + ", ".join(invalid_ids)
        return None

    def _selected_voice_ids(self, settings: PlaybackSettings) -> tuple[Optional[str], Optional[str]]:
        selection = getattr(settings, "voice_selection", None)
        if selection is None:
            selection = getattr(settings, "voices", None)
        if selection is None:
            return (None, None)
        return (
            getattr(selection, "english_voice_id", getattr(selection, "english_id", None)),
            getattr(selection, "chinese_voice_id", getattr(selection, "chinese_id", None)),
        )

    def _configure_driver_for_unit(
        self,
        driver: Any,
        settings: PlaybackSettings,
        unit: SpeechUnit,
    ) -> None:
        english_voice_id, chinese_voice_id = self._selected_voice_ids(settings)
        role = self._get_voice_role(unit)
        selected_voice_id = chinese_voice_id if self._is_chinese_role(role) else english_voice_id

        if selected_voice_id:
            driver.setProperty("voice", selected_voice_id)

        driver.setProperty("rate", int(getattr(settings, "rate", 200)))
        driver.setProperty("volume", self._clamp_volume(getattr(settings, "volume", 1.0)))

    def _init_driver(self) -> Any:
        pyttsx3 = self._load_pyttsx3()
        try:
            if sys.platform.startswith("win"):
                return pyttsx3.init(driverName="sapi5")
            return pyttsx3.init()
        except Exception as exc:
            raise RuntimeError(
                "Unable to initialize the offline speech engine. "
                "Windows playback requires a working pyttsx3/SAPI setup."
            ) from exc

    def _load_pyttsx3(self) -> Any:
        try:
            return importlib.import_module("pyttsx3")
        except ImportError as exc:
            raise RuntimeError(
                "pyttsx3 is required for offline speech playback. "
                "Install it with `pip install pyttsx3`."
            ) from exc

    def _iter_units(self, plan: SpeechPlan) -> Sequence[SpeechUnit]:
        units = getattr(plan, "units", None)
        if units is None and isinstance(plan, Sequence):
            return plan
        if units is None:
            return ()
        return units

    def _is_pause_unit(self, unit: SpeechUnit) -> bool:
        candidates = (
            getattr(unit, "action", None),
            getattr(unit, "unit_type", None),
            getattr(unit, "kind", None),
            getattr(unit, "type", None),
        )
        for candidate in candidates:
            normalized = self._enumish_text(candidate)
            if normalized == "pause":
                return True
        return False

    def _get_pause_seconds(self, unit: SpeechUnit) -> float:
        pause_ms = getattr(unit, "pause_ms", None)
        if pause_ms is not None:
            try:
                return max(0.0, float(pause_ms) / 1000.0)
            except (TypeError, ValueError):
                pass

        for attr in ("duration_seconds", "pause_seconds", "seconds", "duration"):
            value = getattr(unit, attr, None)
            if value is None:
                continue
            try:
                return max(0.0, float(value))
            except (TypeError, ValueError):
                continue

        duration_ms = getattr(unit, "duration_ms", None)
        if duration_ms is not None:
            try:
                return max(0.0, float(duration_ms) / 1000.0)
            except (TypeError, ValueError):
                pass

        return 0.0

    def _sleep_pause(self, seconds: float, stop_event: threading.Event) -> None:
        remaining = max(0.0, seconds)
        while remaining > 0 and not stop_event.is_set():
            chunk = min(0.05, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _get_speak_text(self, unit: SpeechUnit) -> str:
        text = getattr(unit, "speak_text", None)
        if text is None:
            text = getattr(unit, "text", "")
        return str(text)

    def _audio_path_for_unit(self, unit: SpeechUnit) -> str | None:
        audio_path = getattr(unit, "audio_path", None)
        if audio_path is None:
            audio_path = getattr(unit, "audio_wav_path", None)
        if audio_path is None:
            return None
        normalized = str(audio_path).strip()
        return normalized or None

    def _get_driver_speak_text(self, settings: PlaybackSettings, unit: SpeechUnit) -> str:
        text = self._get_speak_text(unit)
        if not self._needs_english_safe_text(settings, unit, text):
            return text
        return self._english_safe_text(unit, text)

    def _needs_english_safe_text(
        self,
        settings: PlaybackSettings,
        unit: SpeechUnit,
        text: str,
    ) -> bool:
        if text.isascii():
            return False
        if not self._is_chinese_role(self._get_voice_role(unit)):
            return False
        english_voice_id, chinese_voice_id = self._selected_voice_ids(settings)
        _, chinese_voice = self._selected_voice_objects(settings)
        if self._voice_metadata_looks_chinese(chinese_voice):
            return False
        if (
            self._enumish_text(getattr(unit, "action", None)) == "read_symbol"
            and chinese_voice_id
            and chinese_voice_id != english_voice_id
        ):
            return False
        return (
            not chinese_voice_id
            or chinese_voice_id == english_voice_id
            or not self._voice_id_looks_chinese(chinese_voice_id)
        )

    def _selected_voice_objects(self, settings: PlaybackSettings) -> tuple[Any, Any]:
        selection = getattr(settings, "voice_selection", None)
        if selection is None:
            selection = getattr(settings, "voices", None)
        if selection is None:
            return (None, None)
        return (
            getattr(selection, "english_voice", getattr(selection, "english", None)),
            getattr(selection, "chinese_voice", getattr(selection, "chinese", None)),
        )

    def _voice_metadata_looks_chinese(self, voice: Any) -> bool:
        if voice is None:
            return False
        values = self._voice_metadata_values(voice)
        normalized_values = [
            value.lower().replace("-", "_").replace(" ", "_") for value in values
        ]
        return any(
            marker in value
            for value in normalized_values
            for marker in (
                "zh",
                "chinese",
                "mandarin",
                "huihui",
                "yaoyao",
                "kangkang",
                "tracy",
                "hanhan",
            )
        )

    def _voice_metadata_values(self, voice: Any) -> list[str]:
        raw_values: list[Any] = []
        for attr in ("name", "display_name", "id", "voice_id", "identifier", "gender"):
            raw_values.append(getattr(voice, attr, None))
        raw_values.extend(self._coerce_metadata_sequence(getattr(voice, "languages", None)))
        raw_values.extend(self._coerce_metadata_sequence(getattr(voice, "language", None)))
        raw_values.extend(self._coerce_metadata_sequence(getattr(voice, "locale", None)))
        return [str(value) for value in raw_values if value]

    def _coerce_metadata_sequence(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)):
            return [value]
        try:
            return list(value)
        except TypeError:
            return [value]

    def _voice_id_looks_chinese(self, voice_id: str) -> bool:
        normalized = voice_id.lower().replace("-", "_").replace(" ", "_")
        return any(
            marker in normalized
            for marker in (
                "zh",
                "chinese",
                "mandarin",
                "huihui",
                "yaoyao",
                "kangkang",
                "tracy",
                "hanhan",
            )
        )

    def _english_safe_text(self, unit: SpeechUnit, text: str) -> str:
        action = self._enumish_text(getattr(unit, "action", None))
        source_text = str(getattr(unit, "source_text", "") or "")
        if action == "read_number" and source_text.isdigit():
            return " ".join(source_text)
        if action == "read_symbol":
            reading_name = self.CHINESE_READING_ENGLISH_NAMES.get(text)
            if reading_name:
                return reading_name
            if text == SYMBOL_TO_CHINESE.get(source_text):
                symbol_name = self.SYMBOL_ENGLISH_NAMES.get(source_text)
                if symbol_name:
                    return symbol_name
            return text
        return source_text if source_text.isascii() and source_text.strip() else text

    def _get_voice_role(self, unit: SpeechUnit) -> Any:
        for attr in ("voice_role", "role", "language_role"):
            value = getattr(unit, attr, None)
            if value is not None:
                return value
        return getattr(VoiceRole, "ENGLISH", "english")

    def _is_chinese_role(self, role: Any) -> bool:
        normalized = self._enumish_text(role)
        return normalized in {"chinese", "zh", "zh_cn", "mandarin"}

    def _normalize_languages(self, raw_languages: Any) -> tuple[str, ...]:
        if raw_languages is None:
            return ()
        if isinstance(raw_languages, (str, bytes)):
            raw_values = [raw_languages]
        else:
            try:
                raw_values = list(raw_languages)
            except TypeError:
                raw_values = [raw_languages]

        normalized: list[str] = []
        for raw in raw_values:
            if isinstance(raw, bytes):
                text = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore")
            else:
                text = str(raw)
            text = text.strip()
            if text:
                normalized.append(text)
        return tuple(normalized)

    def _mark_session(
        self,
        session: PlaybackSession,
        state: PlaybackState,
        *,
        started: bool = False,
        finished: bool = False,
        error_message: Optional[str] = None,
    ) -> None:
        with self._condition:
            session.state = state
            if started and session.started_at is None:
                session.started_at = time.time()
            if finished:
                session.finished_at = time.time()
            if error_message is not None:
                session.error_message = error_message
            self._condition.notify_all()

    def _emit_event(
        self,
        request: _PlayRequest,
        event_type: PlaybackEventType,
        state: PlaybackState,
        *,
        unit: Optional[SpeechUnit] = None,
        unit_index: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        callback = request.on_event
        if callback is None:
            return
        event = PlaybackEvent(
            event_type=event_type,
            session=request.session,
            state=state,
            unit=unit,
            unit_index=unit_index,
            message=message,
            error=error,
        )
        try:
            callback(event)
        except Exception:
            logging.getLogger(__name__).debug("Playback event callback failed.", exc_info=True)

    def _stop_driver(self, driver: Any) -> None:
        if driver is None:
            return
        try:
            driver.stop()
        except Exception:
            pass

    def _format_error(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message or exc.__class__.__name__

    def _enumish_text(self, value: Any) -> str:
        if value is None:
            return ""
        name = getattr(value, "name", None)
        if isinstance(name, str) and name:
            return name.strip().lower()
        raw_value = getattr(value, "value", value)
        return str(raw_value).strip().lower()

    def _safe_str(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _clamp_volume(self, value: Any) -> float:
        try:
            volume = float(value)
        except (TypeError, ValueError):
            volume = 1.0
        return max(0.0, min(1.0, volume))
