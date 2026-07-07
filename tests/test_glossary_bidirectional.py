"""Tests for bidirectional glossary reverse-derivation (EN→AR optimization).

When glossary JSON files contain only one direction (e.g. ar→en), the loader
auto-derives the reverse (en→ar) so EN→AR translation gets the same mandatory
terminology coverage as AR→EN. Explicit entries always win; derived entries
reuse the authored pair (no invented translations).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.glossary import (
    GlossaryIndex,
    Term,
    _derive_reverse_terms,
    load_glossary_files,
    scan_glossary_hits,
)

pytestmark = pytest.mark.unit


def _ar_only_file(tmp_path: Path) -> Path:
    """Write a glossary JSON with ar→en entries only (no explicit en→ar)."""
    glossary_dir: Path = tmp_path / "glossary"
    glossary_dir.mkdir()
    payload: dict[str, object] = {
        "domain": "civil_code",
        "version": "1.0.0",
        "last_updated": "2026-07-07",
        "terms": [
            {
                "source_term": "عقد البيع",
                "source_lang": "ar",
                "target_term": "contract of sale",
                "target_lang": "en",
                "law_ref": "Civil Code",
                "article_ref": "148",
                "priority": 10,
            },
            {
                "source_term": "محكمة البداية",
                "source_lang": "ar",
                "target_term": "Court of First Instance",
                "target_lang": "en",
                "law_ref": "Civil Procedure Code",
                "article_ref": "5",
                "priority": 9,
            },
        ],
    }
    path: Path = glossary_dir / "civil_code.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestReverseDerivation:
    def test_ar_only_fixture_derives_en_to_ar_entries(self, tmp_path: Path) -> None:
        file_path = _ar_only_file(tmp_path)
        terms: list[Term] = load_glossary_files(file_path.parent / "*.json")
        # 2 explicit ar→en + 2 derived en→ar = 4.
        assert len(terms) == 4
        en_terms = [t for t in terms if t.source_lang == "en"]
        assert len(en_terms) == 2
        en_sources = {t.source_term for t in en_terms}
        assert en_sources == {"contract of sale", "Court of First Instance"}
        # Derived entries point back to the original Arabic.
        by_en = {t.source_term: t.target_term for t in en_terms}
        assert by_en["contract of sale"] == "عقد البيع"
        assert by_en["Court of First Instance"] == "محكمة البداية"

    def test_derived_entries_ground_english_source_scan(self, tmp_path: Path) -> None:
        file_path = _ar_only_file(tmp_path)
        terms: list[Term] = load_glossary_files(file_path.parent / "*.json")
        index: GlossaryIndex = GlossaryIndex(terms)
        # Scanning English text now yields Arabic target bindings.
        hits = scan_glossary_hits(
            "The contract of sale was filed at the Court of First Instance.",
            lang="en",
            index=index,
        )
        assert len(hits) == 2
        targets = {h.target_term for h in hits}
        assert targets == {"عقد البيع", "محكمة البداية"}

    def test_explicit_reverse_is_not_duplicated(self, tmp_path: Path) -> None:
        """When JSON already declares both directions, no derived copy is added."""
        glossary_dir: Path = tmp_path / "glossary"
        glossary_dir.mkdir()
        payload: dict[str, object] = {
            "domain": "civil_code",
            "version": "1.0.0",
            "last_updated": "2026-07-07",
            "terms": [
                {
                    "source_term": "عقد البيع",
                    "source_lang": "ar",
                    "target_term": "contract of sale",
                    "target_lang": "en",
                    "law_ref": "Civil Code",
                    "priority": 10,
                },
                {
                    "source_term": "contract of sale",
                    "source_lang": "en",
                    "target_term": "عقد البيع",
                    "target_lang": "ar",
                    "law_ref": "Civil Code",
                    "priority": 10,
                },
            ],
        }
        path: Path = glossary_dir / "civil_code.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        terms: list[Term] = load_glossary_files(path.parent / "*.json")
        assert len(terms) == 2  # explicit both-directions → no derivation

    def test_explicit_reverse_wins_conflict(self) -> None:
        """An explicit en→ar entry blocks derivation of a conflicting reverse.

        Explicit ar→en ``عقد``→``contract`` would derive ``contract``→``عقد``,
        but an explicit en→ar ``contract``→``عقد المبيعات`` already covers the
        ``(contract, en)→ar`` direction, so that derivation is suppressed. The
        explicit en→ar entry's *own* reverse (``عقد المبيعات``→``contract``) is
        still derived because no explicit ar→en covers it.
        """
        explicit_ar_en = Term(
            source_term="عقد", source_lang="ar", target_term="contract",
            target_lang="en", law_ref="Civil Code", domain="civil_code",
            source_term_norm="عقد", file_path="f.json", file_order=0, priority=10,
        )
        explicit_en_ar = Term(
            source_term="contract", source_lang="en", target_term="عقد المبيعات",
            target_lang="ar", law_ref="Civil Code", domain="civil_code",
            source_term_norm="contract", file_path="f.json", file_order=1, priority=10,
        )
        derived = _derive_reverse_terms([explicit_ar_en, explicit_en_ar])
        # No derived entry maps (contract, en) -> ar (explicit already does).
        en_contract = [d for d in derived
                       if d.source_lang == "en" and d.source_term == "contract"]
        assert en_contract == []
        # The explicit en->ar's own reverse (ar->en for عقد المبيعات) is derived.
        ar_rev = [d for d in derived
                  if d.source_lang == "ar" and d.source_term == "عقد المبيعات"]
        assert len(ar_rev) == 1
        assert ar_rev[0].target_term == "contract"

    def test_derive_dedups_among_themselves(self) -> None:
        """Two ar→en terms sharing the same English target derive one en→ar."""
        t1 = Term(
            source_term="عقد1", source_lang="ar", target_term="contract",
            target_lang="en", law_ref="L", domain="d",
            source_term_norm="عقد1", file_path="f.json", file_order=0, priority=5,
        )
        t2 = Term(
            source_term="عقد2", source_lang="ar", target_term="contract",
            target_lang="en", law_ref="L", domain="d",
            source_term_norm="عقد2", file_path="f.json", file_order=1, priority=5,
        )
        derived = _derive_reverse_terms([t1, t2])
        # Only one en→ar reverse for "contract" (first wins).
        assert len(derived) == 1
        assert derived[0].source_term == "contract"
