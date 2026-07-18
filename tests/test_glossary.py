"""Tests for the Aho-Corasick glossary matcher (task group 9).

Verifies the ``pyahocorasick``-backed scanner produces hits identical to the
regex fallback, and that the regex fallback is used when the optional
dependency is unavailable.
"""
from __future__ import annotations

import pytest

from src.components.knowledge_sources import glossary as g
from src.components.knowledge_sources.glossary import (
    GlossaryHit,
    GlossaryIndex,
    Term,
    normalize_arabic,
)

pytestmark = pytest.mark.unit


def _term(source: str, target: str, *, priority: int = 0, order: int = 0) -> Term:
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


def _en_term(source: str, target: str, *, priority: int = 0, order: int = 0) -> Term:
    return Term(
        source_term=source,
        source_lang="en",
        target_term=target,
        target_lang="ar",
        law_ref="Civil Code",
        domain="civil_code",
        source_term_norm=source.lower(),
        file_path="fixture.json",
        file_order=order,
        priority=priority,
    )


TERMS: list[Term] = [
    _term("عقد البيع", "contract of sale", priority=10, order=0),
    _term("عقد", "contract", priority=5, order=1),
    _term("الالتزام ببذل العناية", "obligation of means", priority=9, order=2),
    _term("عقد الإيجار", "lease contract", order=3),
    _term("محكمة الاستئناف", "court of appeal", order=4),
    _en_term("contract of sale", "عقد البيع", priority=10, order=5),
    _en_term("court", "المحكمة", priority=10, order=6),
]

CASES: list[tuple[str, str]] = [
    ("هذا عقد البيع المنصوص عليه", "ar"),
    ("عقد البيع والالتزام ببذل العناية", "ar"),
    ("المادة 148: عقد البيع", "ar"),
    ("هذا العَقْد المنصوص", "ar"),
    ("العقدة كبيرة", "ar"),
    ("هذا عقد الإيجار المنصوص", "ar"),
    ("محكمة الاستئناف العليا", "ar"),
    ("See the contract of sale here.", "en"),
    ("The Court ruled today.", "en"),
    ("لا يوجد أي مصطلح هنا", "ar"),
]


def _hit_key(h: GlossaryHit) -> tuple[str, int, int]:
    return (h.source_term, h.char_start, h.char_end)


@pytest.mark.parametrize("text,lang", CASES)
def test_glossary_ahocorasick_matches_regex_results(text: str, lang: str) -> None:
    """The Aho-Corasick scanner must yield the same hits as the regex fallback."""
    if not g._HAS_AHOCORASICK:
        pytest.skip("pyahocorasick not installed; AC path unavailable")
    ac_index = GlossaryIndex(TERMS)
    ac_hits = [_hit_key(h) for h in ac_index.scan(text, lang)]

    original = g._HAS_AHOCORASICK
    g._HAS_AHOCORASICK = False
    try:
        regex_index = GlossaryIndex(TERMS)
        assert regex_index._by_lang[lang].automaton is None
        regex_hits = [_hit_key(h) for h in regex_index.scan(text, lang)]
    finally:
        g._HAS_AHOCORASICK = original

    assert ac_hits == regex_hits


def test_glossary_falls_back_to_regex_without_ahocorasick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``pyahocorasick`` unavailable, the regex fallback is used and correct."""
    monkeypatch.setattr(g, "_HAS_AHOCORASICK", False)
    index = GlossaryIndex(TERMS)
    lang_index = index._by_lang["ar"]
    assert lang_index.automaton is None
    assert lang_index.pattern is not None

    text = "هذا عقد البيع المنصوص عليه"
    hits = index.scan(text, "ar")
    assert len(hits) == 1
    assert hits[0].source_term == "عقد البيع"
    assert text[hits[0].char_start : hits[0].char_end] == "عقد البيع"
