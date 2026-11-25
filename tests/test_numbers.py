from __future__ import annotations

from app.models import NumberMode
from app.parser import number_to_chinese


def test_digit_by_digit_reads_each_digit_in_chinese():
    assert number_to_chinese("123", NumberMode.DIGIT_BY_DIGIT) == "一二三"


def test_whole_number_reads_compact_integer_in_chinese():
    assert number_to_chinese("123", NumberMode.WHOLE_NUMBER) == "一百二十三"


def test_whole_number_falls_back_for_leading_zero():
    assert number_to_chinese("007", NumberMode.WHOLE_NUMBER) == "零零七"
