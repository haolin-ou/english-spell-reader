from __future__ import annotations

from app.timing import (
    LETTER_PAUSE_LEVEL_TO_MS,
    clamp_letter_pause_level,
    custom_letter_pause_ms_or_none,
    letter_pause_level_to_ms,
    legacy_letter_pause_ms_to_level,
    resolve_letter_pause_ms,
)


def test_letter_pause_levels_cover_normal_to_very_slow_range() -> None:
    assert len(LETTER_PAUSE_LEVEL_TO_MS) == 101
    assert LETTER_PAUSE_LEVEL_TO_MS[0] == 0
    assert LETTER_PAUSE_LEVEL_TO_MS[-1] == 100
    assert LETTER_PAUSE_LEVEL_TO_MS == tuple(sorted(LETTER_PAUSE_LEVEL_TO_MS))


def test_low_letter_pause_levels_are_finely_grained() -> None:
    assert LETTER_PAUSE_LEVEL_TO_MS[:11] == tuple(range(11))


def test_first_nonzero_letter_pause_level_is_more_precise_than_five_ms() -> None:
    assert letter_pause_level_to_ms(1) < 5


def test_letter_pause_level_to_ms_clamps_to_supported_range() -> None:
    assert letter_pause_level_to_ms(-1) == LETTER_PAUSE_LEVEL_TO_MS[0]
    assert letter_pause_level_to_ms(0) == 0
    assert letter_pause_level_to_ms(5) == LETTER_PAUSE_LEVEL_TO_MS[5]
    assert letter_pause_level_to_ms(99) == 99
    assert letter_pause_level_to_ms(1200) == LETTER_PAUSE_LEVEL_TO_MS[100]


def test_clamp_letter_pause_level_accepts_numeric_strings() -> None:
    assert clamp_letter_pause_level("4") == 4
    assert clamp_letter_pause_level("bad") == 0
    assert clamp_letter_pause_level(1200) == 100


def test_legacy_letter_pause_ms_converts_to_nearest_level() -> None:
    assert legacy_letter_pause_ms_to_level(0) == 0
    assert legacy_letter_pause_ms_to_level(15) == 15
    assert legacy_letter_pause_ms_to_level(1200) == 100


def test_custom_letter_pause_ms_accepts_blank_or_precise_values() -> None:
    assert custom_letter_pause_ms_or_none("") is None
    assert custom_letter_pause_ms_or_none(None) is None
    assert custom_letter_pause_ms_or_none("33") == 33
    assert custom_letter_pause_ms_or_none(1200) == 1000


def test_custom_letter_pause_ms_overrides_level_mapping() -> None:
    assert resolve_letter_pause_ms(5, None) == 5
    assert resolve_letter_pause_ms(5, 33) == 33
