"""Tests for TM parallel import (build_from_parallel) and trigram two-stage lookup."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tm import TranslationMemory

pytestmark = pytest.mark.unit


def _sample_pairs() -> list[tuple[str, str, str, str]]:
    """Return a small set of ar/en parallel sentence pairs."""
    return [
        (
            "محكمة النقض هي أعلى هيئة قضائية",
            "The Court of Cassation is the highest judicial body",
            "ar", "en",
        ),
        (
            "القانون ينظم العلاقة بين الأفراد",
            "The law regulates the relationship between individuals",
            "ar", "en",
        ),
        (
            "العقد شريعة المتعاقدين",
            "The contract is the law of the contracting parties",
            "ar", "en",
        ),
        (
            "المسؤولية المدنية تنشأ عن الفعل الضار",
            "Civil liability arises from a harmful act",
            "ar", "en",
        ),
        (
            "حق الملكية مصون لا ينزع إلا للمنفعة العامة",
            "The right of ownership is protected and is not taken except for public utility",
            "ar", "en",
        ),
    ]


def test_build_from_parallel_inserts_pairs(tmp_path: Path):
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"))
    tm.build_from_parallel(_sample_pairs())
    entries = tm.list_all()
    assert len(entries) == 5
    tm.close()


def test_parallel_lookup_exact_match(tmp_path: Path):
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_parallel(_sample_pairs())
    hit = tm.lookup("العقد شريعة المتعاقدين", "ar-en")
    assert hit is not None
    assert hit["similarity"] == pytest.approx(1.0)
    assert "contract" in hit["target_sentence"].lower()
    tm.close()


def test_parallel_lookup_near_match(tmp_path: Path):
    """Trigram index should find a near-match that differs by a few words."""
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.5)
    tm.build_from_parallel(_sample_pairs())
    # Same sentence with one word changed — trigram index should still find it.
    hit = tm.lookup("العقد هو شريعة المتعاقدين", "ar-en")
    assert hit is not None
    assert hit["similarity"] > 0.5
    tm.close()


def test_parallel_lookup_below_threshold_returns_none(tmp_path: Path):
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_parallel(_sample_pairs())
    hit = tm.lookup("هذا نص مختلف تماماً عن أي شيء مخزن", "ar-en")
    assert hit is None
    tm.close()


def test_parallel_build_is_idempotent(tmp_path: Path):
    """build_from_parallel clears existing entries first."""
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"))
    tm.build_from_parallel(_sample_pairs())
    assert len(tm.list_all()) == 5
    # Rebuild with different pairs — old ones should be gone.
    tm.build_from_parallel([("نص جديد", "new text", "ar", "en")])
    assert len(tm.list_all()) == 1
    tm.close()


def test_trigram_lookup_faster_than_full_scan(tmp_path: Path):
    """With many entries, trigram lookup should still find the right match."""
    pairs = [
        (f"جملة قانونية رقم {i}", f"legal sentence number {i}", "ar", "en")
        for i in range(500)
    ]
    pairs.append(("جملة خاصة للبحث", "special sentence for search", "ar", "en"))
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_parallel(pairs)
    hit = tm.lookup("جملة خاصة للبحث", "ar-en")
    assert hit is not None
    assert hit["similarity"] == pytest.approx(1.0)
    assert hit["target_sentence"] == "special sentence for search"
    tm.close()


# ---------------------------------------------------------------------------
# add_parallel() — non-destructive incremental addition
# ---------------------------------------------------------------------------


def test_add_parallel_preserves_existing_entries(tmp_path: Path):
    """add_parallel must NOT clear existing entries (non-destructive)."""
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"))
    # Build with 3 pairs.
    base = _sample_pairs()[:3]
    tm.build_from_parallel(base)
    assert len(tm.list_all()) == 3

    # Add 2 more — existing 3 must survive.
    extra = _sample_pairs()[3:]
    added = tm.add_parallel(extra)
    assert added == 2
    assert len(tm.list_all()) == 5
    tm.close()


def test_add_parallel_empty_is_noop(tmp_path: Path):
    """Adding zero pairs should return 0 and not error."""
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"))
    tm.build_from_parallel(_sample_pairs()[:2])
    added = tm.add_parallel([])
    assert added == 0
    assert len(tm.list_all()) == 2
    tm.close()


def test_add_parallel_lookup_finds_both_old_and_new(tmp_path: Path):
    """After add_parallel, lookup must find entries from both batches."""
    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98
    )
    base = [("عقد البيع هو اتفاق", "A sale contract is an agreement", "ar", "en")]
    tm.build_from_parallel(base)

    extra = [("محكمة النقض هي هيئة", "The Court of Cassation is a body", "ar", "en")]
    tm.add_parallel(extra)

    # Lookup old entry.
    hit1 = tm.lookup("عقد البيع هو اتفاق", "ar-en")
    assert hit1 is not None
    assert hit1["similarity"] == pytest.approx(1.0)

    # Lookup new entry.
    hit2 = tm.lookup("محكمة النقض هي هيئة", "ar-en")
    assert hit2 is not None
    assert hit2["similarity"] == pytest.approx(1.0)
    tm.close()


def test_add_parallel_trigram_index_covers_new_entries(tmp_path: Path):
    """The trigram index must be augmented for newly added entries."""
    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98
    )
    tm.build_from_parallel([("جملة اولى", "first sentence", "ar", "en")])

    # Add a very different sentence that wouldn't share trigrams with the first.
    tm.add_parallel([("نص قانوني مختلف تماما", "completely different legal text", "ar", "en")])

    # Lookup the new entry — trigram index must find it.
    hit = tm.lookup("نص قانوني مختلف تماما", "ar-en")
    assert hit is not None
    assert hit["similarity"] == pytest.approx(1.0)
    tm.close()
