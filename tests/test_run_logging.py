"""Structured run-logging tests for task 4.3.1 (``src/run_logging.py``).

Covers:
- ``RunLogger`` writes one JSON line per ``log_node`` call to
  ``logs/run_<run_id>.jsonl`` with the mandated metric fields (input length,
  glossary hit count, chunk count, draft length, audit verdict, revision
  count, latency per node).
- ``run_translation`` wired with a ``RunLogger`` emits one JSON line per node
  execution (preprocess, translate, audit, finalize) for an APPROVE-first-pass
  run — the 4.3.1 verify step.
- ``run_translation`` without a logger does not create a log file and does not
  error (backward compatible with the existing mock-LLM test suite).

The orchestration tests inject the deterministic ``mock_llm`` / ``mock_embedder``
/ in-memory ``GlossaryIndex`` / a temp ChromaDB collection
(testing-verification §3.4) — no Ollama daemon, no network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.run_logging import RunLogger
from src.state import TranslationState

pytestmark = pytest.mark.integration


def _state_with_metrics() -> TranslationState:
    """A state populated with non-zero metrics for field-assertion tests."""
    return {
        "input_text": "المادة 148: عقد البيع",
        "direction": "ar-en",
        "glossary_hits": [
            {
                "source_term": "عقد البيع", "target_term": "contract of sale",
                "law_ref": "Civil Code", "article_ref": "148", "note": "",
                "char_start": 0, "char_end": 9,
            }
        ],
        "context_chunks": [
            {"text": "chunk", "law": "Civil Code", "article": "148",
             "score": 0.92}
        ],
        "draft": "The contract of sale transfers ownership.",
        "audit": {
            "verdict": "APPROVE", "critique": "", "violations": [],
            "confidence": 0.95,
        },
        "revision_count": 0,
        "final_output": "The contract of sale transfers ownership.",
        "warnings": [],
    }


class TestRunLogger:
    def test_log_node_writes_one_json_line_per_call(
        self, tmp_path: Path
    ) -> None:
        logger = RunLogger(log_dir=tmp_path, run_id="r1")
        logger.log_node("preprocess", 1.5, _state_with_metrics())
        logger.log_node("translate", 2.5, _state_with_metrics())
        logger.close()

        log_file: Path = tmp_path / "run_r1.jsonl"
        assert log_file.is_file()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_log_node_records_all_mandated_metrics(
        self, tmp_path: Path
    ) -> None:
        logger = RunLogger(log_dir=tmp_path, run_id="r2")
        logger.log_node("translate", 12.3, _state_with_metrics())
        logger.close()

        log_file: Path = tmp_path / "run_r2.jsonl"
        record: dict = json.loads(
            log_file.read_text(encoding="utf-8").strip()
        )
        # Mandated fields per TODO 4.3.1.
        assert record["node"] == "translate"
        assert record["latency_ms"] == 12.3
        assert record["input_length"] == len("المادة 148: عقد البيع")
        assert record["glossary_hit_count"] == 1
        assert record["chunk_count"] == 1
        assert record["draft_length"] == len(
            "The contract of sale transfers ownership."
        )
        assert record["audit_verdict"] == "APPROVE"
        assert record["revision_count"] == 0
        # Every line carries the run id and an ISO timestamp for provenance.
        assert record["run_id"] == "r2"
        assert "ts" in record

    def test_log_node_handles_empty_state_without_error(
        self, tmp_path: Path
    ) -> None:
        """A node that has not yet populated a field must not crash logging."""
        empty: TranslationState = {
            "input_text": "", "direction": "ar-en",
            "glossary_hits": [], "context_chunks": [], "draft": "",
            "audit": None, "revision_count": 0, "final_output": None,
            "warnings": [],
        }
        logger = RunLogger(log_dir=tmp_path, run_id="r3")
        logger.log_node("preprocess", 0.1, empty)
        logger.close()

        record: dict = json.loads(
            (tmp_path / "run_r3.jsonl").read_text(encoding="utf-8").strip()
        )
        assert record["input_length"] == 0
        assert record["glossary_hit_count"] == 0
        assert record["chunk_count"] == 0
        assert record["draft_length"] == 0
        assert record["audit_verdict"] is None

    def test_creates_log_dir_if_missing(self, tmp_path: Path) -> None:
        nested: Path = tmp_path / "deep" / "logs"
        logger = RunLogger(log_dir=nested, run_id="r4")
        logger.log_node("finalize", 0.2, _state_with_metrics())
        logger.close()
        assert (nested / "run_r4.jsonl").is_file()


# ---------------------------------------------------------------------------
# 4.3.1 verify step — run_translation emits one JSON line per node execution
# ---------------------------------------------------------------------------


def _build_chroma(tmp_path: Path, mock_embedder, config) -> str:
    from src.ingestion import Chunk
    from src.retrieval import build_chroma_collection

    chunks: list[Chunk] = [
        Chunk(
            chunk_id="civil_code_ar_148_0",
            text=(
                "المادة 148: عقد البيع هو agreement يقتضي نقل ملكية شيء مقابل "
                "ثمن. والتزام البائع ببذل العناية."
            ),
            law="Civil Code", article="148", lang="ar",
            law_slug="civil_code", chunk_idx=0, char_start=0, char_end=120,
        ),
    ]
    persist_dir: str = str(tmp_path / "chroma")
    build_chroma_collection(
        chunks, persist_dir=persist_dir, embedder=mock_embedder, cfg=config,
    )
    return persist_dir


class TestRunTranslationLogging:
    def test_approve_first_pass_logs_one_line_per_node(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        """4.3.1 verify: one JSON line per node execution (4 nodes)."""
        from src.cli import run_translation

        mock_llm.set_response(
            "translator", "The contract of sale transfers ownership."
        )
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE", "critique": "", "violations": [],
                "confidence": 0.95,
            }),
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)

        log_dir: Path = tmp_path / "logs"
        logger = RunLogger(log_dir=log_dir, run_id="verify")
        try:
            state = run_translation(
                "المادة 148: عقد البيع", "ar-en", config,
                llm=mock_llm, embedder=mock_embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
                run_logger=logger,
            )
        finally:
            logger.close()

        assert state["final_output"] == "The contract of sale transfers ownership."

        log_file: Path = log_dir / "run_verify.jsonl"
        assert log_file.is_file()
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        # preprocess + translate + audit + finalize == 4 node executions.
        assert len(lines) == 4
        nodes = [json.loads(line)["node"] for line in lines]
        assert nodes == ["preprocess", "translate", "auditor", "finalize"]
        # The audit node line carries the verdict.
        audit_line = json.loads(lines[2])
        assert audit_line["audit_verdict"] == "APPROVE"

    def test_without_logger_no_log_file_and_no_error(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        """Backward compat: omitting run_logger must not create logs or raise."""
        from src.cli import run_translation

        mock_llm.set_response("translator", "contract of sale")
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE", "critique": "", "violations": [],
                "confidence": 0.95,
            }),
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        log_dir: Path = tmp_path / "logs"

        state = run_translation(
            "المادة 148: عقد البيع", "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert state["final_output"] == "contract of sale"
        assert not log_dir.exists()
