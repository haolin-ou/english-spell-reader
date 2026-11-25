"""Core parser models for speech planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReadingMode(str, Enum):
    """Controls how English words are spoken."""

    spell_then_read_word = "spell_then_read_word"
    read_then_spell = "read_then_spell"
    read_then_spell_then_read = "read_then_spell_then_read"
    spell_only = "spell_only"
    read_only = "read_only"
    SPELL_THEN_READ_WORD = spell_then_read_word
    READ_THEN_SPELL = read_then_spell
    READ_THEN_SPELL_THEN_READ = read_then_spell_then_read
    SPELL_ONLY = spell_only
    READ_ONLY = read_only


class NumberMode(str, Enum):
    """Controls how numeric text is verbalized."""

    digit_by_digit = "digit_by_digit"
    whole_number = "whole_number"
    DIGIT_BY_DIGIT = digit_by_digit
    WHOLE_NUMBER = whole_number


class TokenKind(str, Enum):
    """High-level lexical token categories."""

    english_word = "english_word"
    number = "number"
    symbol = "symbol"
    whitespace = "whitespace"
    newline = "newline"
    other = "other"
    ENGLISH_WORD = english_word
    NUMBER = number
    SYMBOL = symbol
    WHITESPACE = whitespace
    NEWLINE = newline
    OTHER = other


class SpeakAction(str, Enum):
    """Speech actions produced by the parser."""

    spell_letter = "spell_letter"
    read_word = "read_word"
    read_number = "read_number"
    read_symbol = "read_symbol"
    pause = "pause"
    SPELL_LETTER = spell_letter
    READ_WORD = read_word
    READ_NUMBER = read_number
    READ_SYMBOL = read_symbol
    PAUSE = pause


class WhitespaceMode(str, Enum):
    """Controls how whitespace tokens are spoken."""

    pause = "pause"
    read_space = "read_space"
    read_blank = "read_blank"
    PAUSE = pause
    READ_SPACE = read_space
    READ_BLANK = read_blank


class VoiceRole(str, Enum):
    """Voice selection hint for downstream TTS."""

    english = "english"
    chinese = "chinese"
    none = "none"
    ENGLISH = english
    CHINESE = chinese
    NONE = none


@dataclass(frozen=True)
class SourceSpan:
    """Half-open character offsets into the source text."""

    start: int
    end: int


@dataclass(frozen=True)
class ParseOptions:
    """Options controlling speech-plan generation."""

    reading_mode: ReadingMode
    number_mode: NumberMode
    special_words: frozenset[str] | set[str] | None = field(default_factory=frozenset)
    custom_symbol_readings: dict[str, str] | None = field(default_factory=dict)
    custom_letter_readings: dict[str, str] | None = field(default_factory=dict)
    custom_letter_audio_paths: dict[str, str] | None = field(default_factory=dict)
    word_pause_ms: int = 120
    letter_pause_ms: int = 0
    spell_chunk_size: int = 1
    spell_chunk_pause_ms: int = 300
    whitespace_mode: WhitespaceMode = WhitespaceMode.PAUSE


@dataclass(frozen=True)
class Token:
    """A lexical token extracted from the source text."""

    kind: TokenKind
    text: str
    span: SourceSpan


@dataclass(frozen=True)
class SpeechUnit:
    """One deterministic speech or pause instruction."""

    index: int
    source_text: str
    span: SourceSpan
    action: SpeakAction
    voice_role: VoiceRole
    speak_text: str
    pause_ms: int
    audio_path: str | None = None


@dataclass(frozen=True)
class SpeechPlan:
    """The full parser output for a source string."""

    source_text: str
    options: ParseOptions
    tokens: list[Token]
    units: list[SpeechUnit]
