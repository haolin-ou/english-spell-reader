from __future__ import annotations

from app.models import (
    NumberMode,
    ParseOptions,
    ReadingMode,
    SpeakAction,
    WhitespaceMode,
)
from app.parser import build_speech_plan, tokenize


def _token_texts(text: str) -> list[str]:
    return [token.text for token in tokenize(text)]


def _spoken_units(text: str, reading_mode: ReadingMode) -> list[str]:
    plan = build_speech_plan(
        text,
        ParseOptions(
            reading_mode=reading_mode,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
        ),
    )
    return [
        unit.speak_text
        for unit in plan.units
        if unit.action is not SpeakAction.PAUSE
    ]


def test_tokenize_splits_words_punctuation_and_numbers():
    assert _token_texts("Hello, world! I have 123 apples.") == [
        "Hello",
        ",",
        " ",
        "world",
        "!",
        " ",
        "I",
        " ",
        "have",
        " ",
        "123",
        " ",
        "apples",
        ".",
    ]


def test_spell_then_read_word_expands_multi_letter_word():
    assert _spoken_units("hello", ReadingMode.SPELL_THEN_READ_WORD) == ["H E L L O", "hello"]


def test_spell_then_read_word_spells_single_letter_i_once():
    assert _spoken_units("I", ReadingMode.SPELL_THEN_READ_WORD) == ["I"]


def test_spell_only_does_not_include_whole_word():
    assert _spoken_units("hello", ReadingMode.SPELL_ONLY) == ["H E L L O"]


def test_spell_chunk_size_groups_spelling_parts():
    plan = build_speech_plan(
        "hello",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            spell_chunk_size=3,
            spell_chunk_pause_ms=420,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE] == [
        "H E L",
        "L O",
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [420]


def test_spell_chunk_size_two_groups_remainder():
    plan = build_speech_plan(
        "hello",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            spell_chunk_size=2,
            spell_chunk_pause_ms=260,
        ),
    )

    assert [unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE] == [
        "H E",
        "L L",
        "O",
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [
        260,
        260,
    ]


def test_spell_chunk_uses_letter_pause_inside_chunks_and_chunk_pause_between_chunks():
    plan = build_speech_plan(
        "hello",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            spell_chunk_size=3,
            letter_pause_ms=15,
            spell_chunk_pause_ms=400,
        ),
    )

    assert [unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE] == [
        "H",
        "E",
        "L",
        "L",
        "O",
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [
        15,
        15,
        400,
        15,
    ]


def test_read_then_spell_reads_whole_word_before_spelling():
    plan = build_speech_plan(
        "hello",
        ParseOptions(
            reading_mode=ReadingMode.READ_THEN_SPELL,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=275,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.READ_WORD,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [275]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["hello", "H E L L O"]


def test_read_then_spell_then_read_wraps_spelling_with_read_groups():
    plan = build_speech_plan(
        "hello",
        ParseOptions(
            reading_mode=ReadingMode.READ_THEN_SPELL_THEN_READ,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=180,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.READ_WORD,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_WORD,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [180, 180]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["hello", "H E L L O", "hello"]


def test_read_only_reads_whole_word_without_spelling():
    plan = build_speech_plan(
        "hello",
        ParseOptions(
            reading_mode=ReadingMode.READ_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
        ),
    )

    assert [unit.action for unit in plan.units] == [SpeakAction.READ_WORD]
    assert [unit.speak_text for unit in plan.units] == ["hello"]


def test_special_word_reads_as_whole_word_without_spelling():
    plan = build_speech_plan(
        "and",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            special_words=frozenset({"and"}),
        ),
    )

    assert [unit.action for unit in plan.units] == [SpeakAction.READ_WORD]
    assert [unit.speak_text for unit in plan.units] == ["and"]


def test_special_word_matching_is_case_insensitive_and_preserves_text():
    plan = build_speech_plan(
        "And",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            special_words=frozenset({"and"}),
        ),
    )

    assert [unit.action for unit in plan.units] == [SpeakAction.READ_WORD]
    assert [unit.speak_text for unit in plan.units] == ["And"]


def test_custom_letter_reading_replaces_only_spelling_units():
    plan = build_speech_plan(
        "apple",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            custom_letter_readings={"P": "puh"},
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_WORD,
    ]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["A puh puh L E", "apple"]


def test_custom_letter_reading_matching_is_case_insensitive():
    plan = build_speech_plan(
        "Pp",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            custom_letter_readings={"p": "puh"},
        ),
    )

    assert [unit.action for unit in plan.units] == [SpeakAction.SPELL_LETTER]
    assert [unit.speak_text for unit in plan.units] == ["puh puh"]


def test_custom_letter_audio_splits_spelling_and_attaches_audio_path():
    plan = build_speech_plan(
        "apple",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            custom_letter_audio_paths={"p": "/voice/p.wav"},
        ),
    )

    spoken_units = [unit for unit in plan.units if unit.action is not SpeakAction.PAUSE]

    assert [unit.speak_text for unit in spoken_units] == ["A", "P", "P", "L", "E", "apple"]
    assert [unit.audio_path for unit in spoken_units] == [
        None,
        "/voice/p.wav",
        "/voice/p.wav",
        None,
        None,
        None,
    ]


def test_special_word_overrides_custom_letter_reading():
    plan = build_speech_plan(
        "and",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            special_words=frozenset({"and"}),
            custom_letter_readings={"A": "ah"},
        ),
    )

    assert [unit.action for unit in plan.units] == [SpeakAction.READ_WORD]
    assert [unit.speak_text for unit in plan.units] == ["and"]


def test_non_special_word_still_uses_selected_reading_mode():
    plan = build_speech_plan(
        "ant",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            special_words=frozenset({"and"}),
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_WORD,
    ]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["A N T", "ant"]


def test_custom_symbol_reading_overrides_builtin_symbol_map():
    plan = build_speech_plan(
        "&!",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            custom_symbol_readings={"&": "and symbol", "!": "bang"},
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.READ_SYMBOL,
        SpeakAction.PAUSE,
        SpeakAction.READ_SYMBOL,
    ]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["and symbol", "bang"]


def test_custom_symbol_reading_supports_symbol_not_in_builtin_map():
    plan = build_speech_plan(
        "~",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            custom_symbol_readings={"~": "tilde"},
        ),
    )

    assert [unit.action for unit in plan.units] == [SpeakAction.READ_SYMBOL]
    assert [unit.speak_text for unit in plan.units] == ["tilde"]


def test_dash_variants_are_spoken_as_symbols_by_default():
    for text in ("a–b", "a—b", "a－b"):
        plan = build_speech_plan(
            text,
            ParseOptions(
                reading_mode=ReadingMode.SPELL_ONLY,
                number_mode=NumberMode.DIGIT_BY_DIGIT,
            ),
        )

        assert [unit.action for unit in plan.units] == [
            SpeakAction.SPELL_LETTER,
            SpeakAction.PAUSE,
            SpeakAction.READ_SYMBOL,
            SpeakAction.PAUSE,
            SpeakAction.SPELL_LETTER,
        ]
        assert [
            unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
        ] == ["A", "连字符", "B"]


def test_custom_symbol_reading_overrides_dash_variant():
    plan = build_speech_plan(
        "a–b",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            custom_symbol_readings={"–": "dash"},
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_SYMBOL,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["A", "dash", "B"]


def test_ascii_hyphen_between_numbers_is_spoken_as_minus():
    plan = build_speech_plan(
        "1-2",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
        ),
    )

    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["一", "减号", "二"]


def test_hyphen_between_words_stays_spoken_as_hyphen():
    plan = build_speech_plan(
        "A-B",
        ParseOptions(
            reading_mode=ReadingMode.READ_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
        ),
    )

    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["A", "连字符", "B"]


def test_spaced_hyphen_between_numbers_is_spoken_as_minus():
    plan = build_speech_plan(
        "1 - 2",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
        ),
    )

    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["一", "减号", "二"]


def test_unicode_minus_sign_is_spoken_as_minus():
    plan = build_speech_plan(
        "1−2",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
        ),
    )

    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["一", "减号", "二"]


def test_custom_symbol_reading_overrides_numeric_minus_context():
    plan = build_speech_plan(
        "1-2",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            custom_symbol_readings={"-": "dash"},
        ),
    )

    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["一", "dash", "二"]


def test_word_pause_setting_controls_whitespace_but_not_newline_pause():
    plan = build_speech_plan(
        "a b\nc",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=450,
        ),
    )

    pauses = [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE]
    assert pauses == [450, 300]


def test_default_whitespace_mode_keeps_pause_behavior():
    plan = build_speech_plan(
        "a b",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=450,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [450]


def test_whitespace_mode_read_space_reads_kongge_without_pause():
    plan = build_speech_plan(
        "a b",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            whitespace_mode=WhitespaceMode.READ_SPACE,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.READ_SYMBOL,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == []
    assert [unit.speak_text for unit in plan.units] == ["A", "空格", "B"]


def test_read_space_between_words_matches_user_requested_sequence():
    plan = build_speech_plan(
        "want eat food",
        ParseOptions(
            reading_mode=ReadingMode.READ_THEN_SPELL,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            whitespace_mode=WhitespaceMode.READ_SPACE,
        ),
    )

    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == [
        "want",
        "W A N T",
        "空格",
        "eat",
        "E A T",
        "空格",
        "food",
        "F O O D",
    ]


def test_whitespace_mode_read_blank_reads_kong_without_pause():
    plan = build_speech_plan(
        "a b",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            whitespace_mode=WhitespaceMode.READ_BLANK,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.READ_SYMBOL,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == []
    assert [unit.speak_text for unit in plan.units] == ["A", "空", "B"]


def test_newline_keeps_300ms_pause_even_when_whitespace_is_read():
    plan = build_speech_plan(
        "a\nb",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=450,
            whitespace_mode=WhitespaceMode.READ_SPACE,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [300]


def test_word_pause_is_between_groups_not_letters_in_read_then_spell_mode():
    plan = build_speech_plan(
        "go",
        ParseOptions(
            reading_mode=ReadingMode.READ_THEN_SPELL,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=333,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.READ_WORD,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [333]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["go", "G O"]


def test_letter_pause_setting_splits_spelled_letters_with_pauses():
    plan = build_speech_plan(
        "go",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            letter_pause_ms=90,
            word_pause_ms=333,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [90]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["G", "O"]


def test_tiny_letter_pause_splits_spelled_letters_with_precise_pause():
    plan = build_speech_plan(
        "go",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            letter_pause_ms=1,
            word_pause_ms=333,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.SPELL_LETTER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [1]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["G", "O"]


def test_spell_then_read_word_inserts_pause_before_whole_word_readback():
    plan = build_speech_plan(
        "hello",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_THEN_READ_WORD,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=275,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_WORD,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [275]
    assert [
        unit.speak_text for unit in plan.units if unit.action is not SpeakAction.PAUSE
    ] == ["H E L L O", "hello"]


def test_adjacent_english_and_number_groups_get_word_pause():
    plan = build_speech_plan(
        "a1",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=260,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_NUMBER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [260]


def test_adjacent_english_and_symbol_groups_get_word_pause():
    plan = build_speech_plan(
        "a!",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=310,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_SYMBOL,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [310]


def test_newline_keeps_only_newline_pause_without_extra_adjacent_word_pause():
    plan = build_speech_plan(
        "a\n1",
        ParseOptions(
            reading_mode=ReadingMode.SPELL_ONLY,
            number_mode=NumberMode.DIGIT_BY_DIGIT,
            word_pause_ms=500,
        ),
    )

    assert [unit.action for unit in plan.units] == [
        SpeakAction.SPELL_LETTER,
        SpeakAction.PAUSE,
        SpeakAction.READ_NUMBER,
    ]
    assert [unit.pause_ms for unit in plan.units if unit.action is SpeakAction.PAUSE] == [300]
