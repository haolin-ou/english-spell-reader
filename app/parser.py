"""Pure tokenization and speech-plan construction logic."""

from __future__ import annotations

from .models import (
    NumberMode,
    ParseOptions,
    ReadingMode,
    SourceSpan,
    SpeakAction,
    SpeechPlan,
    SpeechUnit,
    Token,
    TokenKind,
    VoiceRole,
    WhitespaceMode,
)
from .symbol_map import SYMBOL_TO_CHINESE

_DIGIT_TO_CHINESE = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}
_SMALL_UNITS = ["千", "百", "十", ""]
_GROUP_UNITS = ["", "万", "亿", "兆", "京", "垓"]
_CONTEXTUAL_MINUS_SYMBOLS = frozenset({"-", "–", "—", "－"})


def tokenize(text: str) -> list[Token]:
    """Split source text into deterministic token kinds."""

    tokens: list[Token] = []
    index = 0
    length = len(text)

    while index < length:
        start = index
        char = text[index]

        if _is_ascii_letter(char):
            index += 1
            while index < length and _is_ascii_letter(text[index]):
                index += 1
            tokens.append(
                Token(TokenKind.ENGLISH_WORD, text[start:index], SourceSpan(start, index))
            )
            continue

        if _is_ascii_digit(char):
            index += 1
            while index < length and _is_ascii_digit(text[index]):
                index += 1
            tokens.append(Token(TokenKind.NUMBER, text[start:index], SourceSpan(start, index)))
            continue

        if char in SYMBOL_TO_CHINESE:
            index += 1
            tokens.append(Token(TokenKind.SYMBOL, char, SourceSpan(start, index)))
            continue

        if char in " \t":
            index += 1
            while index < length and text[index] in " \t":
                index += 1
            tokens.append(
                Token(TokenKind.WHITESPACE, text[start:index], SourceSpan(start, index))
            )
            continue

        if char in "\r\n":
            index = _consume_newlines(text, index)
            tokens.append(Token(TokenKind.NEWLINE, text[start:index], SourceSpan(start, index)))
            continue

        index += 1
        tokens.append(Token(TokenKind.OTHER, char, SourceSpan(start, index)))

    return tokens


def build_speech_plan(text: str, options: ParseOptions) -> SpeechPlan:
    """Convert text into speech-ready units without side effects."""

    tokens = tokenize(text)
    units: list[SpeechUnit] = []
    special_words = _normalize_special_words(options.special_words)
    custom_symbol_readings = options.custom_symbol_readings or {}
    custom_letter_readings = _normalize_custom_letter_readings(
        options.custom_letter_readings
    )
    custom_letter_audio_paths = _normalize_custom_letter_audio_paths(
        options.custom_letter_audio_paths
    )
    spell_chunk_size = _normalize_spell_chunk_size(
        getattr(options, "spell_chunk_size", 1)
    )
    spell_chunk_pause_ms = _normalize_pause_ms(
        getattr(options, "spell_chunk_pause_ms", 300)
    )

    for index, token in enumerate(tokens):
        previous_token = tokens[index - 1] if index > 0 else None
        if _should_insert_word_gap(
            previous_token, token, options.word_pause_ms, custom_symbol_readings
        ):
            units.append(_pause_unit(units, token, options.word_pause_ms))

        if token.kind is TokenKind.ENGLISH_WORD:
            if token.text.lower() in special_words:
                units.append(
                    _make_unit(
                        units,
                        source_text=token.text,
                        span=token.span,
                        action=SpeakAction.READ_WORD,
                        voice_role=VoiceRole.ENGLISH,
                        speak_text=token.text,
                        pause_ms=0,
                    )
                )
            else:
                _append_word_units(
                    units,
                    token,
                    options.reading_mode,
                    options.word_pause_ms,
                    options.letter_pause_ms,
                    spell_chunk_size,
                    spell_chunk_pause_ms,
                    custom_letter_readings,
                    custom_letter_audio_paths,
                )
        elif token.kind is TokenKind.NUMBER:
            units.append(
                _make_unit(
                    units,
                    source_text=token.text,
                    span=token.span,
                    action=SpeakAction.READ_NUMBER,
                    voice_role=VoiceRole.CHINESE,
                    speak_text=number_to_chinese(token.text, options.number_mode),
                    pause_ms=0,
                )
            )
        elif token.kind is TokenKind.SYMBOL:
            chinese = _symbol_reading_for_token(
                tokens,
                index,
                token,
                custom_symbol_readings,
            )
            if chinese is not None:
                units.append(
                    _make_unit(
                        units,
                        source_text=token.text,
                        span=token.span,
                        action=SpeakAction.READ_SYMBOL,
                        voice_role=VoiceRole.CHINESE,
                        speak_text=chinese,
                        pause_ms=0,
                    )
                )
        elif token.kind is TokenKind.WHITESPACE:
            _append_whitespace_unit(units, token, options)
        elif token.kind is TokenKind.NEWLINE:
            units.append(_pause_unit(units, token, 300))
        else:
            custom_reading = custom_symbol_readings.get(token.text)
            if custom_reading is not None:
                units.append(
                    _make_unit(
                        units,
                        source_text=token.text,
                        span=token.span,
                        action=SpeakAction.READ_SYMBOL,
                        voice_role=VoiceRole.CHINESE,
                        speak_text=custom_reading,
                        pause_ms=0,
                    )
                )
            else:
                units.append(_pause_unit(units, token, 120))

    return SpeechPlan(source_text=text, options=options, tokens=tokens, units=units)


def number_to_chinese(digits: str, mode: NumberMode) -> str:
    """Convert an ASCII digit string into spoken Chinese text."""

    if not digits:
        return ""

    if mode is NumberMode.DIGIT_BY_DIGIT:
        return "".join(_DIGIT_TO_CHINESE[digit] for digit in digits)

    if len(digits) > 1 and digits[0] == "0":
        return "".join(_DIGIT_TO_CHINESE[digit] for digit in digits)

    number = int(digits)
    if number == 0:
        return _DIGIT_TO_CHINESE["0"]

    return _int_to_chinese(number)


def symbol_to_chinese(
    symbol: str, custom_symbol_readings: dict[str, str] | None = None
) -> str | None:
    """Return the configured reading for a supported one-character symbol."""

    if custom_symbol_readings and symbol in custom_symbol_readings:
        return custom_symbol_readings[symbol]
    return SYMBOL_TO_CHINESE.get(symbol)


def _symbol_reading_for_token(
    tokens: list[Token],
    index: int,
    token: Token,
    custom_symbol_readings: dict[str, str],
) -> str | None:
    if token.text in custom_symbol_readings:
        return custom_symbol_readings[token.text]
    if token.text in _CONTEXTUAL_MINUS_SYMBOLS and _is_between_number_tokens(tokens, index):
        return "减号"
    return symbol_to_chinese(token.text)


def _is_between_number_tokens(tokens: list[Token], index: int) -> bool:
    return _nearest_non_whitespace_token(tokens, index, -1) is TokenKind.NUMBER and (
        _nearest_non_whitespace_token(tokens, index, 1) is TokenKind.NUMBER
    )


def _nearest_non_whitespace_token(
    tokens: list[Token],
    index: int,
    direction: int,
) -> TokenKind | None:
    cursor = index + direction
    while 0 <= cursor < len(tokens):
        kind = tokens[cursor].kind
        if kind is not TokenKind.WHITESPACE:
            return kind
        cursor += direction
    return None


def _append_whitespace_unit(
    units: list[SpeechUnit], token: Token, options: ParseOptions
) -> None:
    whitespace_mode = _whitespace_mode_value(options.whitespace_mode)
    if whitespace_mode == WhitespaceMode.READ_SPACE.value:
        speak_text = "空格"
    elif whitespace_mode == WhitespaceMode.READ_BLANK.value:
        speak_text = "空"
    else:
        units.append(_pause_unit(units, token, options.word_pause_ms))
        return

    units.append(
        _make_unit(
            units,
            source_text=token.text,
            span=token.span,
            action=SpeakAction.READ_SYMBOL,
            voice_role=VoiceRole.CHINESE,
            speak_text=speak_text,
            pause_ms=0,
        )
    )


def _whitespace_mode_value(value: WhitespaceMode | str) -> str:
    raw_value = getattr(value, "value", value)
    return raw_value if isinstance(raw_value, str) else str(raw_value)


def _append_word_units(
    units: list[SpeechUnit],
    token: Token,
    reading_mode: ReadingMode,
    word_pause_ms: int,
    letter_pause_ms: int,
    spell_chunk_size: int,
    spell_chunk_pause_ms: int,
    custom_letter_readings: dict[str, str],
    custom_letter_audio_paths: dict[str, str],
) -> None:
    actions = _word_mode_actions(token.text, reading_mode)
    if not actions:
        return

    for index, action in enumerate(actions):
        if index > 0 and word_pause_ms > 0:
            units.append(_pause_unit(units, token, word_pause_ms))

        _append_word_action_units(
            units,
            token,
            action,
            letter_pause_ms,
            spell_chunk_size,
            spell_chunk_pause_ms,
            custom_letter_readings,
            custom_letter_audio_paths,
        )


def _append_word_action_units(
    units: list[SpeechUnit],
    token: Token,
    action: SpeakAction,
    letter_pause_ms: int,
    spell_chunk_size: int,
    spell_chunk_pause_ms: int,
    custom_letter_readings: dict[str, str],
    custom_letter_audio_paths: dict[str, str],
) -> None:
    if action is not SpeakAction.SPELL_LETTER:
        units.append(
            _word_unit(
                units,
                token,
                action,
                spell_chunk_size,
                custom_letter_readings,
                custom_letter_audio_paths,
            )
        )
        return

    if _should_split_spelling_unit(
        token.text,
        letter_pause_ms,
        spell_chunk_size,
        custom_letter_audio_paths,
    ):
        _append_split_spelling_units(
            units,
            token,
            letter_pause_ms,
            spell_chunk_size,
            spell_chunk_pause_ms,
            custom_letter_readings,
            custom_letter_audio_paths,
        )
        return

    units.append(
        _word_unit(
            units,
            token,
            action,
            spell_chunk_size,
            custom_letter_readings,
            custom_letter_audio_paths,
        )
    )


def _should_split_spelling_unit(
    word: str,
    letter_pause_ms: int,
    spell_chunk_size: int,
    custom_letter_audio_paths: dict[str, str],
) -> bool:
    if len(word) <= 1:
        return bool(custom_letter_audio_paths.get(word.upper()))
    return spell_chunk_size > 1 or letter_pause_ms > 0 or any(
        letter.upper() in custom_letter_audio_paths for letter in word
    )


def _append_split_spelling_units(
    units: list[SpeechUnit],
    token: Token,
    letter_pause_ms: int,
    spell_chunk_size: int,
    spell_chunk_pause_ms: int,
    custom_letter_readings: dict[str, str],
    custom_letter_audio_paths: dict[str, str],
) -> None:
    cursor = 0
    chunk_size = _normalize_spell_chunk_size(spell_chunk_size)
    chunks = _spelling_chunks(token.text, chunk_size, custom_letter_readings)
    use_chunk_pause = chunk_size > 1

    for chunk_index, (source_text, speak_text) in enumerate(chunks):
        if chunk_index > 0 and use_chunk_pause and spell_chunk_pause_ms > 0:
            units.append(
                _pause_unit(
                    units,
                    Token(
                        TokenKind.WHITESPACE,
                        "",
                        SourceSpan(token.span.start + cursor, token.span.start + cursor),
                    ),
                    spell_chunk_pause_ms,
                )
            )
        elif chunk_index > 0 and not use_chunk_pause and letter_pause_ms > 0:
            units.append(
                _pause_unit(
                    units,
                    Token(
                        TokenKind.WHITESPACE,
                        "",
                        SourceSpan(token.span.start + cursor, token.span.start + cursor),
                    ),
                    letter_pause_ms,
                )
            )
        part_length = len(source_text)
        if _should_split_chunk_letters(
            source_text,
            letter_pause_ms,
            custom_letter_audio_paths,
        ):
            _append_chunk_letter_units(
                units,
                token,
                source_text,
                cursor,
                letter_pause_ms,
                custom_letter_readings,
                custom_letter_audio_paths,
            )
        else:
            units.append(
                _make_unit(
                    units,
                    source_text=source_text,
                    span=SourceSpan(
                        token.span.start + cursor,
                        token.span.start + cursor + part_length,
                    ),
                    action=SpeakAction.SPELL_LETTER,
                    voice_role=VoiceRole.ENGLISH,
                    speak_text=speak_text,
                    pause_ms=0,
                    audio_path=_single_letter_audio_path(source_text, custom_letter_audio_paths),
                )
            )
        cursor += part_length


def _should_split_chunk_letters(
    source_text: str,
    letter_pause_ms: int,
    custom_letter_audio_paths: dict[str, str],
) -> bool:
    return letter_pause_ms > 0 or any(
        letter.upper() in custom_letter_audio_paths for letter in source_text
    )


def _append_chunk_letter_units(
    units: list[SpeechUnit],
    token: Token,
    source_text: str,
    chunk_start: int,
    letter_pause_ms: int,
    custom_letter_readings: dict[str, str],
    custom_letter_audio_paths: dict[str, str],
) -> None:
    for offset, letter in enumerate(source_text):
        absolute_offset = chunk_start + offset
        if offset > 0 and letter_pause_ms > 0:
            units.append(
                _pause_unit(
                    units,
                    Token(
                        TokenKind.WHITESPACE,
                        "",
                        SourceSpan(
                            token.span.start + absolute_offset,
                            token.span.start + absolute_offset,
                        ),
                    ),
                    letter_pause_ms,
                )
            )
        units.append(
            _make_unit(
                units,
                source_text=letter,
                span=SourceSpan(
                    token.span.start + absolute_offset,
                    token.span.start + absolute_offset + 1,
                ),
                action=SpeakAction.SPELL_LETTER,
                voice_role=VoiceRole.ENGLISH,
                speak_text=_letter_reading(letter, custom_letter_readings),
                pause_ms=0,
                audio_path=_single_letter_audio_path(letter, custom_letter_audio_paths),
            )
        )


def _word_mode_actions(word: str, reading_mode: ReadingMode) -> tuple[SpeakAction, ...]:
    if reading_mode is ReadingMode.SPELL_ONLY:
        return (SpeakAction.SPELL_LETTER,)
    if reading_mode is ReadingMode.READ_ONLY:
        return (SpeakAction.READ_WORD,)
    if reading_mode is ReadingMode.READ_THEN_SPELL:
        return (SpeakAction.READ_WORD, SpeakAction.SPELL_LETTER)
    if reading_mode is ReadingMode.READ_THEN_SPELL_THEN_READ:
        return (
            SpeakAction.READ_WORD,
            SpeakAction.SPELL_LETTER,
            SpeakAction.READ_WORD,
        )
    if len(word) == 1:
        return (SpeakAction.SPELL_LETTER,)
    return (SpeakAction.SPELL_LETTER, SpeakAction.READ_WORD)


def _word_unit(
    units: list[SpeechUnit],
    token: Token,
    action: SpeakAction,
    spell_chunk_size: int,
    custom_letter_readings: dict[str, str],
    custom_letter_audio_paths: dict[str, str],
) -> SpeechUnit:
    if action is SpeakAction.READ_WORD:
        return _make_unit(
            units,
            source_text=token.text,
            span=token.span,
            action=SpeakAction.READ_WORD,
            voice_role=VoiceRole.ENGLISH,
            speak_text=token.text,
            pause_ms=0,
        )
    return _make_unit(
        units,
        source_text=token.text,
        span=token.span,
        action=SpeakAction.SPELL_LETTER,
        voice_role=VoiceRole.ENGLISH,
        speak_text=_spelling_text(token.text, spell_chunk_size, custom_letter_readings),
        pause_ms=0,
        audio_path=_single_letter_audio_path(token.text, custom_letter_audio_paths),
    )


def _spelling_text(
    word: str,
    spell_chunk_size: int,
    custom_letter_readings: dict[str, str],
) -> str:
    return " ".join(
        speak_text
        for _, speak_text in _spelling_chunks(
            word,
            spell_chunk_size,
            custom_letter_readings,
        )
    )


def _spelling_chunks(
    word: str,
    spell_chunk_size: int,
    custom_letter_readings: dict[str, str],
) -> list[tuple[str, str]]:
    chunk_size = _normalize_spell_chunk_size(spell_chunk_size)
    if chunk_size <= 1:
        return [
            (letter, _letter_reading(letter, custom_letter_readings))
            for letter in word
        ]
    return [
        (
            word[index : index + chunk_size],
            " ".join(
                _letter_reading(letter, custom_letter_readings)
                for letter in word[index : index + chunk_size]
            ),
        )
        for index in range(0, len(word), chunk_size)
    ]


def _letter_reading(letter: str, custom_letter_readings: dict[str, str]) -> str:
    normalized = letter.upper()
    return custom_letter_readings.get(normalized, normalized)


def _letter_audio_path(letter: str, custom_letter_audio_paths: dict[str, str]) -> str | None:
    return custom_letter_audio_paths.get(letter.upper())


def _single_letter_audio_path(
    text: str,
    custom_letter_audio_paths: dict[str, str],
) -> str | None:
    if len(text) != 1:
        return None
    return _letter_audio_path(text, custom_letter_audio_paths)


def _pause_unit(units: list[SpeechUnit], token: Token, pause_ms: int) -> SpeechUnit:
    return _make_unit(
        units,
        source_text=token.text,
        span=token.span,
        action=SpeakAction.PAUSE,
        voice_role=VoiceRole.NONE,
        speak_text="",
        pause_ms=pause_ms,
    )


def _normalize_pause_ms(value: object) -> int:
    try:
        pause_ms = int(round(float(value)))
    except (TypeError, ValueError):
        pause_ms = 0
    return max(0, min(5000, pause_ms))


def _make_unit(
    units: list[SpeechUnit],
    *,
    source_text: str,
    span: SourceSpan,
    action: SpeakAction,
    voice_role: VoiceRole,
    speak_text: str,
    pause_ms: int,
    audio_path: str | None = None,
) -> SpeechUnit:
    return SpeechUnit(
        index=len(units),
        source_text=source_text,
        span=span,
        action=action,
        voice_role=voice_role,
        speak_text=speak_text,
        pause_ms=pause_ms,
        audio_path=audio_path,
    )


def _is_ascii_letter(char: str) -> bool:
    return ("A" <= char <= "Z") or ("a" <= char <= "z")


def _is_ascii_digit(char: str) -> bool:
    return "0" <= char <= "9"


def _normalize_special_words(
    special_words: frozenset[str] | set[str] | None,
) -> frozenset[str]:
    if not special_words:
        return frozenset()
    return frozenset(word.lower() for word in special_words)


def _normalize_custom_letter_readings(
    custom_letter_readings: dict[str, str] | None,
) -> dict[str, str]:
    if not custom_letter_readings:
        return {}

    normalized: dict[str, str] = {}
    for letter, reading in custom_letter_readings.items():
        if not isinstance(letter, str) or not isinstance(reading, str):
            continue
        key = letter.strip().upper()
        value = reading.strip()
        if len(key) == 1 and key.isascii() and key.isalpha() and value:
            normalized[key] = value
    return normalized


def _normalize_custom_letter_audio_paths(
    custom_letter_audio_paths: dict[str, str] | None,
) -> dict[str, str]:
    if not custom_letter_audio_paths:
        return {}

    normalized: dict[str, str] = {}
    for letter, audio_path in custom_letter_audio_paths.items():
        if not isinstance(letter, str) or not isinstance(audio_path, str):
            continue
        key = letter.strip().upper()
        value = audio_path.strip()
        if len(key) == 1 and key.isascii() and key.isalpha() and value:
            normalized[key] = value
    return normalized


def _normalize_spell_chunk_size(value: object) -> int:
    try:
        chunk_size = int(round(float(value)))
    except (TypeError, ValueError):
        chunk_size = 1
    return max(1, min(10, chunk_size))


def _should_insert_word_gap(
    previous_token: Token | None,
    current_token: Token,
    word_pause_ms: int,
    custom_symbol_readings: dict[str, str],
) -> bool:
    if previous_token is None or word_pause_ms <= 0:
        return False
    if previous_token.span.end != current_token.span.start:
        return False
    return _is_spoken_group(previous_token, custom_symbol_readings) and _is_spoken_group(
        current_token, custom_symbol_readings
    )


def _is_spoken_group(token: Token, custom_symbol_readings: dict[str, str]) -> bool:
    if token.kind in (TokenKind.ENGLISH_WORD, TokenKind.NUMBER, TokenKind.SYMBOL):
        return True
    if token.kind is TokenKind.OTHER:
        return token.text in custom_symbol_readings
    return False


def _consume_newlines(text: str, index: int) -> int:
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\r":
            index += 2 if index + 1 < length and text[index + 1] == "\n" else 1
            continue
        if char == "\n":
            index += 1
            continue
        break
    return index


def _int_to_chinese(number: int) -> str:
    groups: list[int] = []
    remaining = number
    while remaining > 0:
        groups.append(remaining % 10000)
        remaining //= 10000

    group_parts: list[str] = []
    zero_between_groups = False

    for group_index in range(len(groups) - 1, -1, -1):
        group_value = groups[group_index]
        if group_value == 0:
            zero_between_groups = bool(group_parts)
            continue

        if group_parts and (zero_between_groups or group_value < 1000):
            group_parts.append("零")

        group_text = _four_digit_group_to_chinese(group_value)
        group_unit = _GROUP_UNITS[group_index] if group_index < len(_GROUP_UNITS) else ""
        group_parts.append(group_text + group_unit)
        zero_between_groups = False

    result = "".join(group_parts)
    if result.startswith("一十"):
        return result[1:]
    return result


def _four_digit_group_to_chinese(number: int) -> str:
    digits = f"{number:04d}"
    parts: list[str] = []
    zero_pending = False

    for digit_char, unit in zip(digits, _SMALL_UNITS):
        digit = int(digit_char)
        if digit == 0:
            zero_pending = bool(parts)
            continue

        if zero_pending:
            parts.append("零")
            zero_pending = False

        parts.append(_DIGIT_TO_CHINESE[digit_char] + unit)

    return "".join(parts)
