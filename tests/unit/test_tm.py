"""Tests for the TranslationMemory class (task 3)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from src.components.knowledge_sources.tm import TranslationMemory

pytestmark = pytest.mark.unit


def _write_corpus(corpus_dir: Path) -> None:
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون المدني العراقي\nLANG: ar\n---\n\n"
        "ARTICLE 1\nعقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.\n\n"
        "ARTICLE 2\nالأهلية هي صلاحية الشخص لاكتساب الحقوق.\n",
        encoding="utf-8",
    )
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Iraqi Civil Code\nLANG: en\n---\n\n"
        "ARTICLE 1\nA contract of sale is an agreement to transfer ownership "
        "of a thing in exchange for a price.\n\n"
        "ARTICLE 2\nLegal capacity is the fitness of a person to acquire rights.\n",
        encoding="utf-8",
    )


def test_build_from_corpus_aligns_articles(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    hits = tm.list_all()
    assert len(hits) == 4
    assert all("source_sentence" in h and "target_sentence" in h for h in hits)
    tm.close()


def test_lookup_exact_match_returns_hit(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    hit = tm.lookup("عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.", "ar-en")
    assert hit is not None
    assert hit["source_sentence"] == "عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن."
    assert "contract of sale" in hit["target_sentence"].lower()
    assert hit["similarity"] == pytest.approx(1.0)
    tm.close()


def test_lookup_below_threshold_returns_none(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    hit = tm.lookup("هذا نص قانوني مختلف تماماً عن أي شيء مخزن.", "ar-en")
    assert hit is None
    tm.close()


def test_lookup_empty_tm_returns_none(tmp_path: Path):
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    hit = tm.lookup("أي نص", "ar-en")
    assert hit is None
    tm.close()


def test_lookup_en_ar_direction(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    hit = tm.lookup(
        "A contract of sale is an agreement to transfer ownership "
        "of a thing in exchange for a price.",
        "en-ar",
    )
    assert hit is not None
    assert "عقد البيع" in hit["target_sentence"]
    tm.close()


# ---------------------------------------------------------------------------
# Task 1.7 — context manager + thread safety tests
# ---------------------------------------------------------------------------


def test_tm_context_manager_closes_connection(tmp_path: Path):
    """Using ``with TranslationMemory(...)`` closes the connection on exit."""
    with TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98
    ) as tm:
        tm.build_from_corpus(_make_corpus(tmp_path))
        assert tm.list_all()
    # After context exit, the connection is closed — further use raises.
    with pytest.raises((sqlite3.ProgrammingError, AttributeError)):
        tm.list_all()


def test_tm_close_is_idempotent(tmp_path: Path):
    """Calling ``close()`` twice is safe (no error on second call)."""
    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98
    )
    tm.close()
    tm.close()  # second close must not raise


def test_tm_thread_safe_under_concurrent_writes(tmp_path: Path):
    """Two threads each inserting 50 rows concurrently must not raise
    ``sqlite3.ProgrammingError`` and all 100 rows must be present."""
    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98
    )
    errors: list[Exception] = []

    def worker(start: int) -> None:
        try:
            pairs = [
                (f"src {i}", f"tgt {i}", "ar", "en")
                for i in range(start, start + 50)
            ]
            tm.add_parallel(pairs)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1000,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors, f"concurrent writes raised: {errors}"
    assert len(tm.list_all()) == 100
    tm.close()


def _make_corpus(corpus_dir_parent: Path) -> Path:
    corpus_dir = corpus_dir_parent / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    _write_corpus(corpus_dir)
    return corpus_dir
