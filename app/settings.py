"""Persistence for user-defined reader rules."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .timing import (
    clamp_letter_pause_level,
    custom_letter_pause_ms_or_none,
)

DEFAULT_SPACE_BEHAVIOR = "pause"
VALID_SPACE_BEHAVIORS = frozenset({"pause", "read_space", "read_blank"})
DEFAULT_READING_MODE = "spell_then_read_word"
VALID_READING_MODES = frozenset(
    {
        "spell_then_read_word",
        "read_then_spell",
        "read_then_spell_then_read",
        "spell_only",
        "read_only",
    }
)
DEFAULT_NUMBER_MODE = "digit_by_digit"
VALID_NUMBER_MODES = frozenset({"digit_by_digit", "whole_number"})
DEFAULT_RATE = 160
MIN_RATE = 80
MAX_RATE = 260
DEFAULT_VOLUME = 100
MIN_VOLUME = 0
MAX_VOLUME = 100
DEFAULT_SPELL_CHUNK_SIZE = 1
MIN_SPELL_CHUNK_SIZE = 1
MAX_SPELL_CHUNK_SIZE = 10
DEFAULT_SPELL_CHUNK_PAUSE_MS = 300
MAX_SPELL_CHUNK_PAUSE_MS = 5000


@dataclass(frozen=True)
class ReaderRules:
    """Serializable user rules that affect parsing behavior."""

    special_words: frozenset[str] = field(default_factory=frozenset)
    custom_symbol_readings: dict[str, str] = field(default_factory=dict)
    custom_letter_readings: dict[str, str] = field(default_factory=dict)
    custom_letter_audio_paths: dict[str, str] = field(default_factory=dict)
    word_pause_ms: int = 120
    letter_pause_ms: int = 0
    spell_chunk_size: int = DEFAULT_SPELL_CHUNK_SIZE
    spell_chunk_pause_ms: int = DEFAULT_SPELL_CHUNK_PAUSE_MS
    custom_letter_pause_ms: int | None = None
    space_behavior: str = DEFAULT_SPACE_BEHAVIOR
    reading_mode: str = DEFAULT_READING_MODE
    number_mode: str = DEFAULT_NUMBER_MODE
    rate: int = DEFAULT_RATE
    volume: int = DEFAULT_VOLUME
    english_voice_id: str | None = None
    chinese_voice_id: str | None = None


def load_rules(path: str | Path | None = None) -> ReaderRules:
    """Load rules from disk, falling back to defaults on invalid data."""

    rules_path = _resolve_rules_path(path)
    if not rules_path.exists():
        return ReaderRules()

    try:
        payload = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ReaderRules()

    if not isinstance(payload, dict):
        return ReaderRules()

    return ReaderRules(
        special_words=_sanitize_special_words(payload.get("special_words")),
        custom_symbol_readings=_sanitize_custom_symbol_readings(
            payload.get("custom_symbol_readings")
        ),
        custom_letter_readings=_sanitize_custom_letter_readings(
            payload.get("custom_letter_readings")
        ),
        custom_letter_audio_paths=_sanitize_custom_letter_audio_paths(
            payload.get("custom_letter_audio_paths")
        ),
        word_pause_ms=_sanitize_word_pause_ms(payload.get("word_pause_ms")),
        letter_pause_ms=_sanitize_letter_pause_ms(payload.get("letter_pause_ms")),
        spell_chunk_size=_sanitize_spell_chunk_size(payload.get("spell_chunk_size")),
        spell_chunk_pause_ms=_sanitize_spell_chunk_pause_ms(
            payload.get("spell_chunk_pause_ms")
        ),
        custom_letter_pause_ms=_sanitize_custom_letter_pause_ms(
            payload.get("custom_letter_pause_ms")
        ),
        space_behavior=_sanitize_space_behavior(payload.get("space_behavior")),
        reading_mode=_sanitize_reading_mode(payload.get("reading_mode")),
        number_mode=_sanitize_number_mode(payload.get("number_mode")),
        rate=_sanitize_rate(payload.get("rate")),
        volume=_sanitize_volume(payload.get("volume")),
        english_voice_id=_sanitize_voice_id(payload.get("english_voice_id")),
        chinese_voice_id=_sanitize_voice_id(payload.get("chinese_voice_id")),
    )


def save_rules(rules: ReaderRules, path: str | Path | None = None) -> Path:
    """Persist rules to deterministic JSON and return the path written."""

    rules_path = _resolve_rules_path(path)
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = ReaderRules(
        special_words=_sanitize_special_words(rules.special_words),
        custom_symbol_readings=_sanitize_custom_symbol_readings(
            rules.custom_symbol_readings
        ),
        custom_letter_readings=_sanitize_custom_letter_readings(
            rules.custom_letter_readings
        ),
        custom_letter_audio_paths=_sanitize_custom_letter_audio_paths(
            rules.custom_letter_audio_paths
        ),
        word_pause_ms=_sanitize_word_pause_ms(rules.word_pause_ms),
        letter_pause_ms=_sanitize_letter_pause_ms(rules.letter_pause_ms),
        spell_chunk_size=_sanitize_spell_chunk_size(
            getattr(rules, "spell_chunk_size", DEFAULT_SPELL_CHUNK_SIZE)
        ),
        spell_chunk_pause_ms=_sanitize_spell_chunk_pause_ms(
            getattr(rules, "spell_chunk_pause_ms", DEFAULT_SPELL_CHUNK_PAUSE_MS)
        ),
        custom_letter_pause_ms=_sanitize_custom_letter_pause_ms(
            rules.custom_letter_pause_ms
        ),
        space_behavior=_sanitize_space_behavior(rules.space_behavior),
        reading_mode=_sanitize_reading_mode(rules.reading_mode),
        number_mode=_sanitize_number_mode(rules.number_mode),
        rate=_sanitize_rate(rules.rate),
        volume=_sanitize_volume(rules.volume),
        english_voice_id=_sanitize_voice_id(rules.english_voice_id),
        chinese_voice_id=_sanitize_voice_id(rules.chinese_voice_id),
    )
    payload = {
        "special_words": sorted(normalized.special_words),
        "custom_symbol_readings": dict(sorted(normalized.custom_symbol_readings.items())),
        "custom_letter_readings": dict(sorted(normalized.custom_letter_readings.items())),
        "custom_letter_audio_paths": dict(
            sorted(normalized.custom_letter_audio_paths.items())
        ),
        "word_pause_ms": normalized.word_pause_ms,
        "letter_pause_ms": normalized.letter_pause_ms,
        "spell_chunk_size": normalized.spell_chunk_size,
        "spell_chunk_pause_ms": normalized.spell_chunk_pause_ms,
        "custom_letter_pause_ms": normalized.custom_letter_pause_ms,
        "space_behavior": normalized.space_behavior,
        "reading_mode": normalized.reading_mode,
        "number_mode": normalized.number_mode,
        "rate": normalized.rate,
        "volume": normalized.volume,
        "english_voice_id": normalized.english_voice_id,
        "chinese_voice_id": normalized.chinese_voice_id,
    }
    rules_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return rules_path


def _resolve_rules_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path).expanduser()

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata).expanduser() / "EnglishSpellReader" / "rules.json"

    return Path("~/.english_spell_reader_rules.json").expanduser()


def _sanitize_special_words(value: object) -> frozenset[str]:
    if not isinstance(value, list | tuple | set | frozenset):
        return frozenset()

    sanitized = {
        item.strip().lower()
        for item in value
        if isinstance(item, str) and item.strip().isascii() and item.strip().isalpha()
    }
    return frozenset(sanitized)


def _sanitize_custom_symbol_readings(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    sanitized: dict[str, str] = {}
    for key, reading in value.items():
        if not isinstance(key, str) or not isinstance(reading, str):
            continue
        normalized_key = key.strip()
        normalized_reading = reading.strip()
        if len(normalized_key) != 1 or not normalized_reading:
            continue
        sanitized[normalized_key] = normalized_reading
    return sanitized


def _sanitize_custom_letter_readings(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    sanitized: dict[str, str] = {}
    for key, reading in value.items():
        if not isinstance(key, str) or not isinstance(reading, str):
            continue
        normalized_key = key.strip().upper()
        normalized_reading = reading.strip()
        if (
            len(normalized_key) != 1
            or not normalized_key.isascii()
            or not normalized_key.isalpha()
            or not normalized_reading
        ):
            continue
        sanitized[normalized_key] = normalized_reading
    return sanitized


def _sanitize_custom_letter_audio_paths(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    sanitized: dict[str, str] = {}
    for key, audio_path in value.items():
        if not isinstance(key, str) or not isinstance(audio_path, str):
            continue
        normalized_key = key.strip().upper()
        normalized_path = audio_path.strip()
        if (
            len(normalized_key) != 1
            or not normalized_key.isascii()
            or not normalized_key.isalpha()
            or not normalized_path
        ):
            continue
        sanitized[normalized_key] = normalized_path
    return sanitized


def _sanitize_word_pause_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 120
    if value < 0:
        return 120
    return value


def _sanitize_letter_pause_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0:
        return 0
    return clamp_letter_pause_level(value)


def _sanitize_spell_chunk_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_SPELL_CHUNK_SIZE
    return max(MIN_SPELL_CHUNK_SIZE, min(MAX_SPELL_CHUNK_SIZE, value))


def _sanitize_spell_chunk_pause_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_SPELL_CHUNK_PAUSE_MS
    return max(0, min(MAX_SPELL_CHUNK_PAUSE_MS, value))


def _sanitize_custom_letter_pause_ms(value: object) -> int | None:
    return custom_letter_pause_ms_or_none(value)


def _sanitize_space_behavior(value: object) -> str:
    if not isinstance(value, str):
        return DEFAULT_SPACE_BEHAVIOR

    normalized = value.strip()
    if normalized not in VALID_SPACE_BEHAVIORS:
        return DEFAULT_SPACE_BEHAVIOR
    return normalized


def _sanitize_reading_mode(value: object) -> str:
    if not isinstance(value, str):
        return DEFAULT_READING_MODE

    normalized = value.strip()
    if normalized not in VALID_READING_MODES:
        return DEFAULT_READING_MODE
    return normalized


def _sanitize_number_mode(value: object) -> str:
    if not isinstance(value, str):
        return DEFAULT_NUMBER_MODE

    normalized = value.strip()
    if normalized not in VALID_NUMBER_MODES:
        return DEFAULT_NUMBER_MODE
    return normalized


def _sanitize_rate(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_RATE
    return max(MIN_RATE, min(MAX_RATE, value))


def _sanitize_volume(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_VOLUME
    return max(MIN_VOLUME, min(MAX_VOLUME, value))


def _sanitize_voice_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None
    return normalized
