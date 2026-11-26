"""Timing helpers for user-facing pause controls."""

from __future__ import annotations

MAX_LETTER_PAUSE_MS = 100
LETTER_PAUSE_LEVEL_TO_MS = tuple(range(MAX_LETTER_PAUSE_MS + 1))
MAX_LETTER_PAUSE_LEVEL = len(LETTER_PAUSE_LEVEL_TO_MS) - 1
MAX_CUSTOM_LETTER_PAUSE_MS = 1000


def clamp_letter_pause_level(value: object) -> int:
    """Clamp a user-facing letter pause millisecond value to the supported range."""

    try:
        level = int(round(float(value)))
    except (TypeError, ValueError):
        level = 0
    return max(0, min(MAX_LETTER_PAUSE_LEVEL, level))


def letter_pause_level_to_ms(level: object) -> int:
    """Convert the user-facing millisecond control into the parser pause."""

    return LETTER_PAUSE_LEVEL_TO_MS[clamp_letter_pause_level(level)]


def custom_letter_pause_ms_or_none(value: object) -> int | None:
    """Return a bounded custom millisecond pause, or None when left blank."""

    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        pause_ms = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    if pause_ms < 0:
        return None
    return min(pause_ms, MAX_CUSTOM_LETTER_PAUSE_MS)


def resolve_letter_pause_ms(level: object, custom_ms: object) -> int:
    """Resolve the effective parser pause, with custom milliseconds taking priority."""

    custom_pause = custom_letter_pause_ms_or_none(custom_ms)
    if custom_pause is not None:
        return custom_pause
    return letter_pause_level_to_ms(level)


def legacy_letter_pause_ms_to_level(value: object) -> int:
    """Normalize older saved values into the current millisecond control."""

    try:
        pause_ms = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return clamp_letter_pause_level(pause_ms)
