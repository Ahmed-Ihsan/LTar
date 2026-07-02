"""Unit tests for glossary normalization (DATA_SPEC §2.3, task 2.1.2).

Normalization is pure and deterministic — the deterministic backbone of the
exact-match glossary (testing-verification skill §2.1).
"""
from __future__ import annotations

import pytest

from src.glossary import normalize, normalize_arabic, normalize_english

pytestmark = pytest.mark.unit


class TestNormalizeArabic:
    def test_strips_tashkeel(self) -> None:
        assert normalize_arabic("العَقْدِ") == "العقد"

    def test_diacritics_vs_plain_are_equal(self) -> None:
        # The exact assertion requested by TODO 2.1.2 verification.
        assert normalize_arabic("العَقْد") == normalize_arabic("العقد")

    def test_strips_tatweel(self) -> None:
        assert normalize_arabic("العـــقد") == "العقد"

    def test_normalizes_alef_variants(self) -> None:
        assert normalize_arabic("أحمد") == normalize_arabic("احمد")
        assert normalize_arabic("إبراهيم") == normalize_arabic("ابراهيم")
        assert normalize_arabic("آية") == normalize_arabic("اية")

    def test_normalizes_ya_alif_maqsura(self) -> None:
        assert normalize_arabic("محامى") == normalize_arabic("محامي")

    def test_idempotent(self) -> None:
        term = "العَقْدِ"
        once = normalize_arabic(term)
        twice = normalize_arabic(once)
        assert once == twice

    @pytest.mark.parametrize("raw,expected", [
        ("عقد البيع", "عقد البيع"),
        ("القانون المدني", "القانون المدني"),
    ])
    def test_preserves_clean_text(self, raw: str, expected: str) -> None:
        assert normalize_arabic(raw) == expected


class TestNormalizeEnglish:
    def test_lowercases(self) -> None:
        assert normalize_english("Contract of Sale") == "contract of sale"

    def test_collapses_whitespace(self) -> None:
        assert normalize_english("contract   of\t sale") == "contract of sale"

    def test_strips_trailing_punctuation(self) -> None:
        assert normalize_english("contract of sale.") == "contract of sale"
        assert normalize_english("contract of sale,") == "contract of sale"

    def test_idempotent(self) -> None:
        term = "Contract of Sale."
        once = normalize_english(term)
        twice = normalize_english(once)
        assert once == twice


class TestNormalizeDispatch:
    def test_arabic_dispatch(self) -> None:
        assert normalize("العَقْد", "ar") == "العقد"

    def test_english_dispatch(self) -> None:
        assert normalize("Contract.", "en") == "contract"
