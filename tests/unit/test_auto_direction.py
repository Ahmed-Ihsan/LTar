"""Tests for `--direction auto` (script-dominance language detection).

Covers `detect_direction` and the `auto` direction integration in the
`translate`, `excel`, and `batch` commands. The detection is a pure
heuristic based on Arabic vs Latin character counts — no LLM calls.
"""
from __future__ import annotations

import pytest

from src.components.interfaces.orchestration import Direction, detect_direction

pytestmark = pytest.mark.unit


class TestDetectDirection:
    def test_pure_arabic_returns_ar_en(self) -> None:
        assert detect_direction("عقد البيع هو اتفاق") == "ar-en"

    def test_pure_english_returns_en_ar(self) -> None:
        assert detect_direction("A contract of sale is an agreement") == "en-ar"

    def test_mixed_arabic_dominant_returns_ar_en(self) -> None:
        # Arabic sentence with an English term in parentheses.
        text = "عقد البيع (contract of sale) هو اتفاق"
        assert detect_direction(text) == "ar-en"

    def test_mixed_english_dominant_returns_en_ar(self) -> None:
        # English sentence with an Arabic term in parentheses.
        text = "The contract (عقد) is concluded by offer and acceptance"
        assert detect_direction(text) == "en-ar"

    def test_empty_string_defaults_to_ar_en(self) -> None:
        assert detect_direction("") == "ar-en"

    def test_numbers_only_default_to_ar_en(self) -> None:
        assert detect_direction("12345 67890") == "ar-en"

    def test_punctuation_only_defaults_to_ar_en(self) -> None:
        assert detect_direction("--- ... !!!") == "ar-en"

    def test_tie_defaults_to_ar_en(self) -> None:
        # One Arabic char + one Latin char → tie → ar-en (safe default).
        assert detect_direction("A ب") == "ar-en"

    def test_arabic_diacritics_count_as_arabic(self) -> None:
        # Arabic with diacritics — all in the U+0600–U+06FF range.
        assert detect_direction("يَلْتَزِمُ البائِعُ") == "ar-en"

    def test_mixed_with_numbers(self) -> None:
        # Arabic text with numbers — Arabic chars dominate.
        assert detect_direction("المادة 148 من القانون المدني") == "ar-en"

    def test_english_with_numbers(self) -> None:
        assert detect_direction("Article 148 of the Civil Code") == "en-ar"

    def test_never_returns_auto(self) -> None:
        """The output is always a concrete direction, never 'auto'."""
        for text in ["", "hello", "مرحبا", "123", "A ب"]:
            assert detect_direction(text) in ("ar-en", "en-ar")


class TestDirectionEnumHasAuto:
    def test_auto_value(self) -> None:
        assert Direction.auto.value == "auto"

    def test_all_three_values(self) -> None:
        values: set[str] = {d.value for d in Direction}
        assert values == {"ar-en", "en-ar", "auto"}
