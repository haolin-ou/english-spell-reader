from __future__ import annotations

import json

from app.settings import ReaderRules, load_rules, save_rules


def test_rules_load_save_round_trip(tmp_path):
    path = tmp_path / "rules.json"
    rules = ReaderRules(
        special_words=frozenset({"and", "the"}),
        custom_symbol_readings={"&": "and symbol", "-": "hyphen"},
        custom_letter_readings={"P": "puh", "A": "ah"},
        custom_letter_audio_paths={"P": "/voice/p.wav"},
        word_pause_ms=250,
        letter_pause_ms=8,
        spell_chunk_size=3,
        spell_chunk_pause_ms=640,
        custom_letter_pause_ms=33,
        space_behavior="read_space",
        reading_mode="read_then_spell",
        number_mode="whole_number",
        rate=210,
        volume=55,
        english_voice_id="english-voice",
        chinese_voice_id="chinese-voice",
    )

    save_rules(rules, path)
    loaded = load_rules(path)

    assert loaded == rules


def test_load_rules_normalizes_custom_letter_readings(tmp_path):
    path = tmp_path / "letter-rules.json"
    path.write_text(
        json.dumps(
            {
                "custom_letter_readings": {
                    "p": " puh ",
                    "AA": "bad",
                    "1": "one",
                    "B": "",
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_rules(path).custom_letter_readings == {"P": "puh"}


def test_load_rules_normalizes_custom_letter_audio_paths(tmp_path):
    path = tmp_path / "letter-audio-rules.json"
    path.write_text(
        json.dumps(
            {
                "custom_letter_audio_paths": {
                    "p": " /voice/p.wav ",
                    "AA": "/voice/a.wav",
                    "1": "/voice/one.wav",
                    "B": "",
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_rules(path).custom_letter_audio_paths == {"P": "/voice/p.wav"}


def test_load_rules_defaults_space_behavior_for_missing_or_invalid_values(tmp_path):
    missing_path = tmp_path / "missing-space-behavior.json"
    missing_path.write_text(
        json.dumps(
            {
                "special_words": ["and"],
                "custom_symbol_readings": {"&": "and symbol"},
                "word_pause_ms": 200,
                "letter_pause_ms": 90,
                "custom_letter_pause_ms": 25,
            }
        ),
        encoding="utf-8",
    )

    invalid_path = tmp_path / "invalid-space-behavior.json"
    invalid_path.write_text(
        json.dumps(
            {
                "special_words": ["and"],
                "custom_symbol_readings": {"&": "and symbol"},
                "word_pause_ms": 200,
                "letter_pause_ms": 90,
                "custom_letter_pause_ms": -1,
                "space_behavior": "bad-value",
            }
        ),
        encoding="utf-8",
    )

    assert load_rules(missing_path).space_behavior == "pause"
    assert load_rules(invalid_path).space_behavior == "pause"
    assert load_rules(missing_path).letter_pause_ms == 90
    assert load_rules(missing_path).custom_letter_pause_ms == 25
    assert load_rules(invalid_path).custom_letter_pause_ms is None


def test_load_rules_defaults_invalid_letter_pause(tmp_path):
    path = tmp_path / "invalid-letter-pause.json"
    path.write_text(
        json.dumps(
            {
                "special_words": [],
                "custom_symbol_readings": {},
                "word_pause_ms": 200,
                "letter_pause_ms": -1,
                "space_behavior": "pause",
            }
        ),
        encoding="utf-8",
    )

    assert load_rules(path).letter_pause_ms == 0


def test_save_rules_sanitizes_invalid_space_behavior(tmp_path):
    path = tmp_path / "rules.json"

    save_rules(ReaderRules(space_behavior="bad-value"), path)
    loaded = load_rules(path)

    assert loaded.space_behavior == "pause"


def test_load_rules_defaults_invalid_reading_and_number_modes(tmp_path):
    path = tmp_path / "invalid-modes.json"
    path.write_text(
        json.dumps(
            {
                "reading_mode": "bad-reading-mode",
                "number_mode": "bad-number-mode",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_rules(path)

    assert loaded.reading_mode == "spell_then_read_word"
    assert loaded.number_mode == "digit_by_digit"


def test_load_rules_clamps_rate_and_volume(tmp_path):
    low_path = tmp_path / "low-values.json"
    low_path.write_text(
        json.dumps(
            {
                "rate": 10,
                "volume": -5,
            }
        ),
        encoding="utf-8",
    )
    high_path = tmp_path / "high-values.json"
    high_path.write_text(
        json.dumps(
            {
                "rate": 500,
                "volume": 500,
            }
        ),
        encoding="utf-8",
    )

    low_loaded = load_rules(low_path)
    high_loaded = load_rules(high_path)

    assert low_loaded.rate == 80
    assert low_loaded.volume == 0
    assert high_loaded.rate == 260
    assert high_loaded.volume == 100


def test_load_rules_normalizes_empty_voice_ids(tmp_path):
    path = tmp_path / "voice-ids.json"
    path.write_text(
        json.dumps(
            {
                "english_voice_id": "  ",
                "chinese_voice_id": " zh-voice  ",
            }
        ),
        encoding="utf-8",
    )

    loaded = load_rules(path)

    assert loaded.english_voice_id is None
    assert loaded.chinese_voice_id == "zh-voice"
