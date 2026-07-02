"""Unit tests for glossary scanning (DATA_SPEC §2.4, task 2.1.3).

Longest-match-first, offset tracking, and the ``glossary_scan`` alias.
"""
from __future__ import annotations

import pytest

from src.glossary import (
    GlossaryIndex,
    Term,
    glossary_scan,
    normalize_arabic,
    scan_glossary_hits,
)

pytestmark = pytest.mark.unit


def _term(source: str, target: str, priority: int = 0, order: int = 0) -> Term:
    return Term(
        source_term=source,
        source_lang="ar",
        target_term=target,
        target_lang="en",
        law_ref="Civil Code",
        domain="civil_code",
        source_term_norm=source,  # already normalized fixtures
        file_path="fixture.json",
        file_order=order,
        priority=priority,
    )


def _norm_term(source: str, target: str, priority: int = 0, order: int = 0) -> Term:
    """Like ``_term`` but normalizes the source term for ``source_term_norm``.

    Use for terms containing Alef variants (أإآ) or Alif Maqsura (ى) that
    need proper normalization to match the real ingestion pipeline.
    """
    return Term(
        source_term=source,
        source_lang="ar",
        target_term=target,
        target_lang="en",
        law_ref="Civil Code",
        domain="civil_code",
        source_term_norm=normalize_arabic(source),
        file_path="fixture.json",
        file_order=order,
        priority=priority,
    )


class TestLongestMatch:
    def test_longest_match_wins_over_substring(
        self, glossary_index: GlossaryIndex
    ) -> None:
        # 'عقد البيع' (contract of sale) must win over 'عقد' (contract) alone.
        hits = scan_glossary_hits("هذا عقد البيع المنصوص عليه", lang="ar", index=glossary_index)
        spans = [h.source_term for h in hits]
        assert "عقد البيع" in spans
        assert "عقد" not in spans  # the standalone short term is shadowed

    def test_multiple_non_overlapping_hits(
        self, glossary_index: GlossaryIndex
    ) -> None:
        hits = scan_glossary_hits(
            "عقد البيع والالتزام ببذل العناية", lang="ar", index=glossary_index
        )
        assert len(hits) == 2
        assert {h.source_term for h in hits} == {"عقد البيع", "الالتزام ببذل العناية"}

    def test_char_offsets_are_correct(
        self, glossary_index: GlossaryIndex
    ) -> None:
        text = "المادة 148: عقد البيع"
        hits = scan_glossary_hits(text, lang="ar", index=glossary_index)
        assert len(hits) == 1
        hit = hits[0]
        assert text[hit.char_start:hit.char_end] == "عقد البيع"

    def test_offsets_span_diacritics_in_source(self) -> None:
        # Source text carries tashkeel; the verbatim slice must include it.
        idx = GlossaryIndex([_term("العقد", "the contract")])
        text = "هذا العَقْد المنصوص"
        hits = scan_glossary_hits(text, lang="ar", index=idx)
        assert len(hits) == 1
        assert text[hits[0].char_start:hits[0].char_end] == "العَقْد"

    def test_no_match_returns_empty(self, glossary_index: GlossaryIndex) -> None:
        assert scan_glossary_hits("مرحبا بالعالم", lang="ar", index=glossary_index) == []

    def test_no_substring_match_inside_larger_word(self) -> None:
        # 'عقد' must NOT match the substring inside 'العقدة' (different token).
        idx = GlossaryIndex([_term("عقد", "contract")])
        hits = scan_glossary_hits("العقدة كبيرة", lang="ar", index=idx)
        assert hits == []

    def test_english_direction_scan(self, glossary_index: GlossaryIndex) -> None:
        hits = scan_glossary_hits(
            "See the contract of sale here.", lang="en", index=glossary_index
        )
        assert len(hits) == 1
        assert hits[0].source_term == "contract of sale"
        assert hits[0].target_term == "عقد البيع"

    def test_hits_ordered_by_char_start(
        self, glossary_index: GlossaryIndex
    ) -> None:
        hits = scan_glossary_hits(
            "عقد البيع والالتزام ببذل العناية", lang="ar", index=glossary_index
        )
        starts = [h.char_start for h in hits]
        assert starts == sorted(starts)


class TestAlefVariantMatching:
    """The scan regex must match Alef variants (أإآ) and Alif Maqsura (ى)
    in the *original* text even though the pattern is built from the
    *normalized* form (where they all collapse to ا / ي).

    Regression: ``عقد الإيجار`` in source text failed to match the glossary
    term ``عقد الإيجار`` because the regex used the normalized ``ا``
    (U+0627) literally, but the text has ``إ`` (U+0625) at that position.
    """

    def test_hamza_below_alef_matches(self) -> None:
        # Term stored with إ (U+0625); text also has إ — but the regex
        # is built from the normalized form where إ→ا. Must still match.
        idx = GlossaryIndex([_norm_term("عقد الإيجار", "lease contract")])
        hits = scan_glossary_hits("هذا عقد الإيجار المنصوص", lang="ar", index=idx)
        assert len(hits) == 1
        assert hits[0].source_term == "عقد الإيجار"

    def test_hamza_above_alef_matches(self) -> None:
        idx = GlossaryIndex([_norm_term("الإثبات", "the proof")])
        hits = scan_glossary_hits("الإثبات واجب", lang="ar", index=idx)
        assert len(hits) == 1
        assert hits[0].source_term == "الإثبات"

    def test_madda_alef_matches(self) -> None:
        idx = GlossaryIndex([_norm_term("آخر", "last")])
        hits = scan_glossary_hits("آخر أجل", lang="ar", index=idx)
        assert len(hits) == 1
        assert hits[0].source_term == "آخر"

    def test_alif_maqsura_matches(self) -> None:
        # ى (U+0649) normalizes to ي (U+064A); the regex must match both.
        idx = GlossaryIndex([_norm_term("محكمة الاستئناف", "court of appeal")])
        # If the source text uses ى instead of ي, it must still match.
        hits = scan_glossary_hits("محكمة الاستئناف العليا", lang="ar", index=idx)
        assert len(hits) == 1
        assert hits[0].source_term == "محكمة الاستئناف"

    def test_mixed_alef_variants_in_multiline_text(self) -> None:
        """Reproduces the original bug: multi-article text where one
        article contains إ and another contains ا — both must match."""
        idx = GlossaryIndex([
            _norm_term("عقد البيع", "contract of sale"),
            _norm_term("عقد الإيجار", "lease contract"),
        ])
        text = (
            "المادة 5: عقد البيع هو اتفاق.\n\n"
            "المادة 8: عقد الإيجار هو اتفاق."
        )
        hits = scan_glossary_hits(text, lang="ar", index=idx)
        assert len(hits) == 2
        terms = {h.source_term for h in hits}
        assert terms == {"عقد البيع", "عقد الإيجار"}


class TestGlossaryScanAlias:
    def test_alias_matches_canonical(self, glossary_index: GlossaryIndex) -> None:
        text = "هذا عقد البيع المنصوص عليه"
        assert glossary_scan(text, "ar", index=glossary_index) == scan_glossary_hits(
            text, "ar", index=glossary_index
        )
