"""Unit tests for ``approx_token_count`` (DATA_SPEC §3.4, task 2.2.3).

The token heuristic is the single source of truth for token estimation
(engineering-principles §2.1.1) and is pure + deterministic.
"""
from __future__ import annotations

import pytest

from src.ingestion import approx_token_count

pytestmark = pytest.mark.unit


class TestApproxTokenCount:
    def test_arabic_heavy_text_higher_than_same_length_english(self) -> None:
        # The exact assertion requested by TODO 2.2.3 verification.
        english_text: str = "A" * 100  # 100 non-Arabic chars -> 25 tokens
        arabic_text: str = "ع" * 100  # 100 Arabic chars -> 50 tokens
        assert approx_token_count(arabic_text) > approx_token_count(english_text)
        assert approx_token_count(english_text) == 25
        assert approx_token_count(arabic_text) == 50

    def test_blended_uses_script_ratio(self) -> None:
        # 40 Arabic chars (20 tokens) + 80 other chars (20 tokens) = 40.
        text: str = ("ع" * 40) + ("A" * 80)
        assert approx_token_count(text) == 40

    def test_empty_returns_one(self) -> None:
        # DATA_SPEC §3.4 formula: max(1, 0) == 1.
        assert approx_token_count("") == 1

    def test_pure_english_ratio(self) -> None:
        assert approx_token_count("word " * 4) == 5  # 20 chars -> 5 tokens

    def test_pure_arabic_ratio(self) -> None:
        assert approx_token_count("ع" * 16) == 8  # 16 Arabic chars -> 8 tokens

    def test_deterministic(self) -> None:
        text: str = "عقد البيع contract of sale"
        assert approx_token_count(text) == approx_token_count(text)
