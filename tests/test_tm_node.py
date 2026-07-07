"""Tests for the tm_lookup node (task 5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config import AppConfig
from src.nodes import tm_bypass_node, tm_lookup_node
from src.state import TmHit, TranslationState
from src.tm import TranslationMemory

pytestmark = pytest.mark.unit


def _write_corpus(corpus_dir: Path) -> None:
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون المدني العراقي\nLANG: ar\n---\n\n"
        "ARTICLE 1\nعقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.\n",
        encoding="utf-8",
    )
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Iraqi Civil Code\nLANG: en\n---\n\n"
        "ARTICLE 1\nA contract of sale is an agreement to transfer ownership "
        "of a thing in exchange for a price.\n",
        encoding="utf-8",
    )


def _state(input_text: str, direction: str = "ar-en") -> TranslationState:
    return {
        "input_text": input_text,
        "direction": direction,
        "glossary_hits": [],
        "context_chunks": [],
        "tm_hits": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
    }


def test_tm_lookup_exact_match_populates_tm_hits(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    cfg = AppConfig()
    state = _state("عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.")
    result = tm_lookup_node(state, tm=tm, cfg=cfg)
    assert len(result["tm_hits"]) == 1
    assert "contract of sale" in result["tm_hits"][0]["target_sentence"].lower()
    tm.close()


def test_tm_lookup_no_match_leaves_empty_tm_hits(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    cfg = AppConfig()
    state = _state("نص قانوني مختلف تماماً لا يطابق أي شيء.")
    result = tm_lookup_node(state, tm=tm, cfg=cfg)
    assert result["tm_hits"] == []
    tm.close()


def test_tm_lookup_none_tm_leaves_empty(tmp_path: Path):
    cfg = AppConfig()
    state = _state("أي نص")
    result = tm_lookup_node(state, tm=None, cfg=cfg)
    assert result["tm_hits"] == []


def _hit(target: str = "Contract of sale", similarity: float = 1.0) -> TmHit:
    return {
        "source_sentence": "عقد البيع",
        "target_sentence": target,
        "similarity": similarity,
        "char_start": 0,
        "char_end": 9,
    }


def test_tm_bypass_writes_stored_translation_to_draft():
    """tm_bypass_node copies the stored target translation into ``draft``."""
    state = _state("عقد البيع")
    state["tm_hits"] = [_hit()]
    result = tm_bypass_node(state)
    assert result["draft"] == "Contract of sale"


def test_tm_bypass_pre_approves_the_output():
    """TM output bypasses the Auditor: a synthetic APPROVE verdict is set."""
    state = _state("عقد البيع")
    state["tm_hits"] = [_hit(similarity=0.99)]
    result = tm_bypass_node(state)
    assert result["audit"] is not None
    assert result["audit"]["verdict"] == "APPROVE"
    assert result["audit"]["confidence"] == 0.99


def test_tm_bypass_preserves_other_state_fields():
    """The node only writes ``draft`` / ``audit``; other fields are preserved."""
    state = _state("عقد البيع")
    state["tm_hits"] = [_hit()]
    state["warnings"] = ["pre-existing"]
    result = tm_bypass_node(state)
    assert result["warnings"] == ["pre-existing"]
    assert result["tm_hits"] == state["tm_hits"]
    assert result["input_text"] == state["input_text"]


def test_tm_lookup_preserves_other_state_fields(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    cfg = AppConfig()
    state = _state("عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.")
    state["glossary_hits"] = [{"source_term": "x", "target_term": "y",
        "law_ref": "", "article_ref": "", "note": "",
        "char_start": 0, "char_end": 1}]
    result = tm_lookup_node(state, tm=tm, cfg=cfg)
    assert result["glossary_hits"] == state["glossary_hits"]
    assert result["input_text"] == state["input_text"]
    tm.close()
