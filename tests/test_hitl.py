"""Unit tests for human-in-the-loop (HITL) review and correction persistence.

Tests the :mod:`src.hitl` module:
- :func:`human_review` with approve (no edit) and edit paths.
- :func:`_save_correction` writes a valid JSONL record.
- The :class:`HumanReviewer` protocol is satisfied by a mock.

Uses the :class:`MockEngineAdapter` fixture (no Ollama daemon) and a temp
directory for the feedback JSONL file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.components.interfaces.hitl import HumanReviewer, _save_correction, human_review
from src.components.translation_pipeline.models import TranslationState
from src.config import AppConfig

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _state(
    input_text: str = "According to Article 6 of the Civil Procedure Code.",
    direction: str = "en-ar",
    draft: str = "المادة 6 من قانون المرافعات المدنية.",
    audit: object = None,
    revision_count: int = 1,
    **overrides: object,
) -> TranslationState:
    base: TranslationState = {
        "input_text": input_text,
        "direction": direction,  # type: ignore[arg-type]
        "glossary_hits": overrides.get("glossary_hits", []),  # type: ignore[arg-type]
        "context_chunks": [],
        "tm_hits": [],
        "web_search_results": [],
        "draft": draft,
        "audit": audit,  # type: ignore[arg-type]
        "revision_count": revision_count,
        "final_output": None,  # type: ignore[arg-type]
        "warnings": overrides.get("warnings", []),  # type: ignore[arg-type]
    }
    return base


class _ApproveReviewer:
    """Reviewer that always approves the draft as-is (no edit)."""

    def review(self, state: TranslationState) -> str:
        return state.get("draft", "")


class _EditReviewer:
    """Reviewer that always returns a fixed edited draft."""

    def __init__(self, edited: str) -> None:
        self._edited = edited

    def review(self, state: TranslationState) -> str:
        return self._edited


def _hitl_cfg(tmp_path: Path) -> AppConfig:
    """Build an AppConfig with HITL enabled and feedback dir in tmp_path."""
    cfg: AppConfig = AppConfig()
    cfg.hitl_enabled = True
    cfg.hitl_feedback_dir = str(tmp_path / "feedback")
    return cfg


# ---------------------------------------------------------------------------
# 1. human_review — approve path (no edit)
# ---------------------------------------------------------------------------


class TestHumanReviewApprove:
    def test_approve_returns_state_unchanged(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        state: TranslationState = _state(
            audit={"verdict": "APPROVE", "critique": "", "violations": [],
                   "confidence": 0.95},
        )
        result: TranslationState = human_review(
            state, cfg, llm=mock_llm, reviewer=_ApproveReviewer()
        )
        assert result is state  # same object — no edit, no re-audit

    def test_approve_does_not_call_llm(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        state: TranslationState = _state()
        human_review(state, cfg, llm=mock_llm, reviewer=_ApproveReviewer())
        assert mock_llm.call_log == []  # no re-audit on approve

    def test_approve_does_not_write_correction(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        state: TranslationState = _state()
        human_review(state, cfg, llm=mock_llm, reviewer=_ApproveReviewer())
        feedback_path: Path = Path(cfg.hitl_feedback_dir) / "human_corrections.jsonl"
        assert not feedback_path.exists()


# ---------------------------------------------------------------------------
# 2. human_review — edit path
# ---------------------------------------------------------------------------


class TestHumanReviewEdit:
    def test_edit_updates_draft(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        mock_llm.set_response(
            "auditor",
            '{"verdict": "APPROVE", "critique": "", "violations": [], '
            '"confidence": 0.9}',
        )
        original: str = "المادة 6 من قانون المسطرة المدنية."
        edited: str = "المادة 6 من قانون المرافعات المدنية."
        state: TranslationState = _state(
            draft=original,
            audit={"verdict": "REVISE", "critique": "fix", "violations": [],
                   "confidence": 0.8},
        )
        result: TranslationState = human_review(
            state, cfg, llm=mock_llm, reviewer=_EditReviewer(edited)
        )
        assert result["draft"] == edited

    def test_edit_calls_auditor_for_re_audit(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        mock_llm.set_response(
            "auditor",
            '{"verdict": "APPROVE", "critique": "", "violations": [], '
            '"confidence": 0.9}',
        )
        state: TranslationState = _state()
        human_review(
            state, cfg, llm=mock_llm, reviewer=_EditReviewer("edited draft")
        )
        # The auditor was called at least once for the re-audit.
        assert len(mock_llm.call_log) >= 1

    def test_edit_writes_correction_jsonl(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        mock_llm.set_response(
            "auditor",
            '{"verdict": "APPROVE", "critique": "", "violations": [], '
            '"confidence": 0.9}',
        )
        original: str = "المسطرة"
        edited: str = "المرافعات"
        state: TranslationState = _state(
            draft=original,
            audit={"verdict": "REVISE", "critique": "fix term",
                   "violations": ["v1"], "confidence": 0.7},
            glossary_hits=[
                {"source_term": "Civil Procedure Code",
                 "target_term": "قانون المرافعات المدنية",
                 "law_ref": "Civil Procedure Code", "article_ref": "",
                 "note": "", "char_start": 0, "char_end": 22},
            ],  # type: ignore[arg-type]
        )
        human_review(
            state, cfg, llm=mock_llm, reviewer=_EditReviewer(edited)
        )
        feedback_path: Path = Path(cfg.hitl_feedback_dir) / "human_corrections.jsonl"
        assert feedback_path.exists()
        lines: list[str] = feedback_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        record: dict = json.loads(lines[0])
        assert record["input_text"] == state["input_text"]
        assert record["original_draft"] == original
        assert record["edited_draft"] == edited
        assert record["audit_verdict"] == "REVISE"
        assert record["direction"] == "en-ar"
        assert record["model"] == cfg.llm_model
        assert len(record["glossary_hits"]) == 1
        assert record["glossary_hits"][0]["source_term"] == "Civil Procedure Code"

    def test_edit_re_audit_revise_appends_warning(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        mock_llm.set_response(
            "auditor",
            '{"verdict": "REVISE", "critique": "still wrong", "violations": '
            '["v1"], "confidence": 0.6}',
        )
        state: TranslationState = _state()
        result: TranslationState = human_review(
            state, cfg, llm=mock_llm, reviewer=_EditReviewer("edited")
        )
        # The human edit is retained even though the auditor said REVISE.
        assert result["draft"] == "edited"
        # A warning was appended about the advisory re-audit.
        assert any("human edit is retained" in w.lower() or "human-edited" in w.lower()
                   for w in result["warnings"])

    def test_empty_edit_treated_as_approve(self, mock_llm, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        state: TranslationState = _state(draft="original draft")
        result: TranslationState = human_review(
            state, cfg, llm=mock_llm, reviewer=_EditReviewer("   ")
        )
        assert result is state  # no edit, no re-audit


# ---------------------------------------------------------------------------
# 3. _save_correction — JSONL persistence
# ---------------------------------------------------------------------------


class TestSaveCorrection:
    def test_creates_feedback_dir_if_missing(self, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        state: TranslationState = _state()
        _save_correction(state, cfg, original_draft="a", edited_draft="b")
        assert Path(cfg.hitl_feedback_dir).is_dir()

    def test_appends_to_existing_file(self, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        state: TranslationState = _state()
        _save_correction(state, cfg, original_draft="a1", edited_draft="b1")
        _save_correction(state, cfg, original_draft="a2", edited_draft="b2")
        feedback_path: Path = Path(cfg.hitl_feedback_dir) / "human_corrections.jsonl"
        lines: list[str] = feedback_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        r1: dict = json.loads(lines[0])
        r2: dict = json.loads(lines[1])
        assert r1["original_draft"] == "a1"
        assert r2["original_draft"] == "a2"

    def test_record_has_timestamp(self, tmp_path) -> None:
        cfg: AppConfig = _hitl_cfg(tmp_path)
        state: TranslationState = _state()
        _save_correction(state, cfg, original_draft="a", edited_draft="b")
        feedback_path: Path = Path(cfg.hitl_feedback_dir) / "human_corrections.jsonl"
        record: dict = json.loads(feedback_path.read_text(encoding="utf-8").strip())
        assert "timestamp" in record
        assert "T" in record["timestamp"]  # ISO format


# ---------------------------------------------------------------------------
# 4. HumanReviewer protocol conformance
# ---------------------------------------------------------------------------


class TestReviewerProtocol:
    def test_approve_reviewer_satisfies_protocol(self) -> None:
        r: HumanReviewer = _ApproveReviewer()  # type: ignore[assignment]
        assert hasattr(r, "review")

    def test_edit_reviewer_satisfies_protocol(self) -> None:
        r: HumanReviewer = _EditReviewer("edited")  # type: ignore[assignment]
        assert hasattr(r, "review")


# ---------------------------------------------------------------------------
# 5. TM insertion — human corrections saved for immediate reuse
# ---------------------------------------------------------------------------


class TestTmInsertion:
    def test_edit_inserts_pair_into_tm(self, mock_llm, tmp_path) -> None:
        """A human edit inserts (source→edited) into the TM for future reuse."""
        from src.components.knowledge_sources.tm import TranslationMemory

        cfg: AppConfig = _hitl_cfg(tmp_path)
        mock_llm.set_response(
            "auditor",
            '{"verdict": "APPROVE", "critique": "", "violations": [], '
            '"confidence": 0.9}',
        )
        tm: TranslationMemory = TranslationMemory(
            db_path=str(tmp_path / "test_tm.sqlite"),
            similarity_threshold=0.98,
        )
        try:
            source: str = "According to Article 6 of the Civil Procedure Code."
            original: str = "المادة 6 من قانون المسطرة المدنية."
            edited: str = "المادة 6 من قانون المرافعات المدنية."
            state: TranslationState = _state(
                input_text=source, draft=original,
            )
            human_review(
                state, cfg, llm=mock_llm,
                reviewer=_EditReviewer(edited), tm=tm,
            )
            # The TM should now contain the source→edited pair.
            entries: list[dict] = tm.list_all()
            sources: list[str] = [e["source_sentence"] for e in entries]
            assert source in sources
            # And the reverse direction (edited→source) for bidirectional reuse.
            assert edited in sources
        finally:
            tm.close()

    def test_approve_does_not_insert_into_tm(self, mock_llm, tmp_path) -> None:
        """Approving without editing does not touch the TM."""
        from src.components.knowledge_sources.tm import TranslationMemory

        cfg: AppConfig = _hitl_cfg(tmp_path)
        tm: TranslationMemory = TranslationMemory(
            db_path=str(tmp_path / "test_tm.sqlite"),
            similarity_threshold=0.98,
        )
        try:
            state: TranslationState = _state()
            human_review(
                state, cfg, llm=mock_llm,
                reviewer=_ApproveReviewer(), tm=tm,
            )
            entries: list[dict] = tm.list_all()
            assert entries == []
        finally:
            tm.close()

    def test_edit_without_tm_does_not_error(self, mock_llm, tmp_path) -> None:
        """Passing tm=None should work (no TM insertion, no error)."""
        cfg: AppConfig = _hitl_cfg(tmp_path)
        mock_llm.set_response(
            "auditor",
            '{"verdict": "APPROVE", "critique": "", "violations": [], '
            '"confidence": 0.9}',
        )
        state: TranslationState = _state()
        result: TranslationState = human_review(
            state, cfg, llm=mock_llm,
            reviewer=_EditReviewer("edited draft"), tm=None,
        )
        assert result["draft"] == "edited draft"

    def test_tm_hit_after_human_correction(self, mock_llm, tmp_path) -> None:
        """After a human correction is saved to TM, a lookup for the same
        source sentence returns the human-edited translation (bypasses LLM)."""
        from src.components.knowledge_sources.tm import TranslationMemory

        cfg: AppConfig = _hitl_cfg(tmp_path)
        mock_llm.set_response(
            "auditor",
            '{"verdict": "APPROVE", "critique": "", "violations": [], '
            '"confidence": 0.9}',
        )
        tm: TranslationMemory = TranslationMemory(
            db_path=str(tmp_path / "test_tm.sqlite"),
            similarity_threshold=0.98,
        )
        try:
            source: str = "According to Article 6 of the Civil Procedure Code."
            original: str = "المادة 6 من قانون المسطرة المدنية."
            edited: str = "المادة 6 من قانون المرافعات المدنية."
            state: TranslationState = _state(
                input_text=source, draft=original,
            )
            human_review(
                state, cfg, llm=mock_llm,
                reviewer=_EditReviewer(edited), tm=tm,
            )
            # Now look up the same source — should return the human edit.
            hit = tm.lookup(source, "en-ar")
            assert hit is not None
            assert hit["target_sentence"] == edited
        finally:
            tm.close()
