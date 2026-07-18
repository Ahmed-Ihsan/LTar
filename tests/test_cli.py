"""CLI command tests for Phase 4 tasks 4.1.x (``src/cli.py``).

Covers:
- 4.1.1: ``translate`` command — ``run_translation`` orchestration with mocked
  adapters, ``_render_provenance`` pure rendering, and CLI error paths via
  ``CliRunner`` (invalid direction, missing input file).
- 4.1.2: ``batch`` command — ``_process_batch`` writes JSONL with
  ``final_output`` non-null per record; CLI error paths via ``CliRunner``.
- 4.1.3: ``ingest`` wrapper — ``--help`` exits 0; delegates to
  ``src.ingestion.run_ingestion``.

The orchestration tests inject the deterministic ``mock_llm`` / ``mock_embedder``
/ in-memory ``GlossaryIndex`` / a temp ChromaDB collection
(testing-verification §3.4) — no Ollama daemon, no network.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from src.components.interfaces.cli import (
    _audit_trace_markdown,
    _initial_state,
    _provenance_markdown,
    _render_provenance,
    _translate_for_ui,
    app,
    run_translation,
    run_translation_streamed,
)
from src.components.knowledge_sources.ingestion import Chunk
from src.components.knowledge_sources.retrieval import build_chroma_collection
from src.components.translation_pipeline.exceptions import (
    EmbeddingConnectionError,
    OllamaConnectionError,
)
from src.components.translation_pipeline.models import TranslationState

pytestmark = pytest.mark.integration

runner = CliRunner()


# ---------------------------------------------------------------------------
# Shared helpers (mirror tests/test_graph.py fixtures)
# ---------------------------------------------------------------------------


def _fixture_chunks() -> list[Chunk]:
    """A minimal bilingual fixture corpus for CLI flow tests."""
    return [
        Chunk(
            chunk_id="civil_code_ar_148_0",
            text=(
                "المادة 148: عقد البيع هو agreement يقتضي نقل ملكية شيء مقابل "
                "ثمن. والتزام البائع ببذل العناية."
            ),
            law="Civil Code",
            article="148",
            lang="ar",
            law_slug="civil_code",
            chunk_idx=0,
            char_start=0,
            char_end=120,
        ),
        Chunk(
            chunk_id="civil_code_en_5_0",
            text=(
                "Article 5 of the Iraqi Civil Code governs the contract of "
                "sale, defining the transfer of ownership in exchange for a "
                "price and the warranty against latent defects."
            ),
            law="Civil Code",
            article="5",
            lang="en",
            law_slug="civil_code",
            chunk_idx=0,
            char_start=0,
            char_end=180,
        ),
    ]


def _build_chroma(tmp_path: Path, mock_embedder, config) -> str:
    """Build a temp ChromaDB collection and return its persist dir path."""
    persist_dir: str = str(tmp_path / "chroma")
    build_chroma_collection(
        _fixture_chunks(),
        persist_dir=persist_dir,
        embedder=mock_embedder,
        cfg=config,
    )
    return persist_dir


# ---------------------------------------------------------------------------
# 4.1.1 translate — _render_provenance (pure function)
# ---------------------------------------------------------------------------


class TestRenderProvenance:
    def test_includes_glossary_terms_applied(self) -> None:
        state: TranslationState = _initial_state("عقد البيع", "ar-en")
        state["glossary_hits"] = [
            {
                "source_term": "عقد البيع",
                "target_term": "contract of sale",
                "law_ref": "Civil Code",
                "article_ref": "148",
                "note": "",
                "char_start": 0,
                "char_end": 9,
            }
        ]
        state["final_output"] = "contract of sale"
        state["audit"] = {
            "verdict": "APPROVE",
            "critique": "",
            "violations": [],
            "confidence": 0.95,
        }
        out: str = _render_provenance(state)
        assert "عقد البيع" in out
        assert "contract of sale" in out
        assert "Civil Code" in out

    def test_includes_source_chunks_cited(self) -> None:
        state: TranslationState = _initial_state("test", "ar-en")
        state["context_chunks"] = [
            {"text": "chunk text", "law": "Civil Code", "article": "148",
             "score": 0.92}
        ]
        state["final_output"] = "output"
        state["audit"] = {
            "verdict": "APPROVE", "critique": "", "violations": [],
            "confidence": 0.9,
        }
        out: str = _render_provenance(state)
        assert "Civil Code" in out
        assert "148" in out

    def test_includes_audit_verdict_and_revision_count(self) -> None:
        state: TranslationState = _initial_state("test", "ar-en")
        state["final_output"] = "output"
        state["draft"] = "output"
        state["revision_count"] = 2
        state["audit"] = {
            "verdict": "APPROVE", "critique": "ok", "violations": [],
            "confidence": 0.88,
        }
        out: str = _render_provenance(state)
        assert "APPROVE" in out
        assert "2" in out

    def test_includes_warnings_when_present(self) -> None:
        state: TranslationState = _initial_state("test", "ar-en")
        state["final_output"] = "output"
        state["audit"] = {
            "verdict": "REVISE", "critique": "", "violations": [],
            "confidence": 0.5,
        }
        state["revision_count"] = 3
        state["warnings"] = ["Max revisions reached; emitting best-effort draft."]
        out: str = _render_provenance(state)
        assert "Max revisions" in out


# ---------------------------------------------------------------------------
# 4.1.1 translate — run_translation (mocked adapters)
# ---------------------------------------------------------------------------


class TestRunTranslation:
    def test_returns_state_with_final_output(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
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
        state = run_translation(
            "المادة 148: عقد البيع", "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert state["final_output"] is not None
        assert state["final_output"] == "The contract of sale transfers ownership."
        assert state["audit"]["verdict"] == "APPROVE"
        assert state["revision_count"] == 0

    def test_glossary_hits_populated_from_source(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        mock_llm.set_response("translator", "contract of sale")
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE", "critique": "", "violations": [],
                "confidence": 0.95,
            }),
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        state = run_translation(
            "المادة 148: عقد البيع", "ar-en", config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        terms = [h["source_term"] for h in state["glossary_hits"]]
        assert "عقد البيع" in terms


# ---------------------------------------------------------------------------
# 4.1.1 translate — CLI error paths (CliRunner)
# ---------------------------------------------------------------------------


class TestTranslateCommand:
    def test_invalid_direction_exits_nonzero(self) -> None:
        result = runner.invoke(app, [
            "translate", "--input", "test", "--direction", "fr-en",
        ])
        # Click/Typer returns exit code 2 for invalid option values.
        assert result.exit_code != 0

    def test_empty_input_exits_1(self) -> None:
        result = runner.invoke(app, [
            "translate", "--input", "   ", "--direction", "ar-en",
        ])
        assert result.exit_code == 1

    def test_help_exits_0(self) -> None:
        result = runner.invoke(app, ["translate", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.stdout
        assert "--direction" in result.stdout
        assert "--out" in result.stdout


# ---------------------------------------------------------------------------
# 4.1.2 batch — _process_batch (mocked adapters)
# ---------------------------------------------------------------------------


class TestProcessBatch:
    def test_output_has_final_output_per_record(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        from src.components.interfaces.cli import _process_batch

        mock_llm.set_response("translator", "contract of sale")
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE", "critique": "", "violations": [],
                "confidence": 0.95,
            }),
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)

        input_path: Path = tmp_path / "batch_in.jsonl"
        records = [
            {"input": "المادة 148: عقد البيع", "direction": "ar-en"},
            {"input": "contract of sale", "direction": "en-ar"},
        ]
        input_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
        output_path: Path = tmp_path / "batch_out.jsonl"

        count = _process_batch(
            input_path, output_path, config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert count == 2

        lines = output_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            rec = json.loads(line)
            assert rec["final_output"] is not None
            assert "audit_verdict" in rec
            assert "revision_count" in rec

    def test_ten_records_all_have_final_output(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        from src.components.interfaces.cli import _process_batch

        mock_llm.set_response("translator", "contract of sale")
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE", "critique": "", "violations": [],
                "confidence": 0.95,
            }),
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)

        input_path: Path = tmp_path / "batch10_in.jsonl"
        records = [
            {"input": "المادة 148: عقد البيع", "direction": "ar-en"}
            for _ in range(10)
        ]
        input_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
        output_path: Path = tmp_path / "batch10_out.jsonl"

        count = _process_batch(
            input_path, output_path, config,
            llm=mock_llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert count == 10
        lines = output_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 10
        for line in lines:
            rec = json.loads(line)
            assert rec["final_output"] is not None


# ---------------------------------------------------------------------------
# 4.1.2 batch — CLI error paths (CliRunner)
# ---------------------------------------------------------------------------


class TestBatchCommand:
    def test_missing_input_file_exits_1(self, tmp_path: Path) -> None:
        missing: Path = tmp_path / "nonexistent.jsonl"
        output: Path = tmp_path / "out.jsonl"
        result = runner.invoke(app, [
            "batch", "--input", str(missing), "--out", str(output),
        ])
        assert result.exit_code == 1

    def test_help_exits_0(self) -> None:
        result = runner.invoke(app, ["batch", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.stdout
        assert "--out" in result.stdout


# ---------------------------------------------------------------------------
# 4.1.3 ingest wrapper (CliRunner)
# ---------------------------------------------------------------------------


class TestIngestCommand:
    def test_help_exits_0(self) -> None:
        result = runner.invoke(app, ["ingest", "--help"])
        assert result.exit_code == 0
        assert "--rebuild" in result.stdout or "--glossary-only" in result.stdout

    def test_delegates_to_run_ingestion(self) -> None:
        """The CLI ``ingest`` command should call ``src.ingestion.run_ingestion``."""
        from src.components.knowledge_sources.ingestion import IngestionResult

        fake_result = IngestionResult(
            glossary=None,
            corpus=None,
            chroma_embeddings=0,
            duration_seconds=0.01,
            file_hashes=[],
        )
        with patch(
            "src.components.knowledge_sources.ingestion.run_ingestion", return_value=fake_result
        ) as mock_run:
            result = runner.invoke(app, [
                "ingest", "--glossary-only",
            ])
        assert mock_run.called
        # The wrapper should exit 0 when run_ingestion returns no errors.
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# 4.2 Gradio UI — shared sequence mock for REVISE-then-APPROVE scenarios
# ---------------------------------------------------------------------------


class _SequenceMockLLM:
    """Mock LLM that returns successive responses per prompt signature.

    The shared ``mock_llm`` fixture returns one fixed response per signature;
    the audit-trace verification (task 4.2.2) needs a REVISE-then-APPROVE
    sequence (different verdicts on successive auditor calls). This local mock
    implements the ``LLMEngineAdapter`` protocol and pops one response per
    ``generate`` call from a per-signature queue (testing-verification §3.4:
    deterministic, no Ollama, no network).
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[str]] = {}

    def set_response_sequence(
        self, signature: str, responses: list[str]
    ) -> None:
        """Queue successive responses returned in order for a signature."""
        self._queues[signature] = list(responses)

    @staticmethod
    def _signature(prompt: str) -> str:
        if "JSON" in prompt and "verdict" in prompt:
            return "auditor"
        if "Produce the translation" in prompt:
            return "translator"
        return "default"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 120.0,
    ) -> str:
        sig: str = self._signature(user_prompt)
        queue: list[str] = self._queues.get(sig, [])
        if queue:
            return queue.pop(0)
        # Fallback: approve a translator default so a missing queue is loud.
        if sig == "auditor":
            return (
                '{"verdict": "APPROVE", "critique": "", "violations": [], '
                '"confidence": 0.9}'
            )
        return "[Mock translation output]"


# ---------------------------------------------------------------------------
# 4.2.1 / 4.2.2 — _provenance_markdown (pure function)
# ---------------------------------------------------------------------------


class TestProvenanceMarkdown:
    def test_includes_glossary_hits_as_markdown(self) -> None:
        state: TranslationState = _initial_state("عقد البيع", "ar-en")
        state["glossary_hits"] = [
            {
                "source_term": "عقد البيع",
                "target_term": "contract of sale",
                "law_ref": "Civil Code",
                "article_ref": "148",
                "note": "",
                "char_start": 0,
                "char_end": 9,
            }
        ]
        state["final_output"] = "contract of sale"
        state["audit"] = {
            "verdict": "APPROVE", "critique": "", "violations": [],
            "confidence": 0.95,
        }
        md: str = _provenance_markdown(state)
        assert "عقد البيع" in md
        assert "contract of sale" in md
        assert "Civil Code" in md
        assert "148" in md

    def test_includes_chunks_and_audit_verdict(self) -> None:
        state: TranslationState = _initial_state("test", "ar-en")
        state["context_chunks"] = [
            {"text": "chunk", "law": "Civil Code", "article": "5",
             "score": 0.91}
        ]
        state["final_output"] = "output"
        state["audit"] = {
            "verdict": "REVISE", "critique": "fix term", "violations": ["v1"],
            "confidence": 0.6,
        }
        state["revision_count"] = 1
        md: str = _provenance_markdown(state)
        assert "REVISE" in md
        assert "Civil Code" in md
        assert "0.91" in md or "0.9" in md


# ---------------------------------------------------------------------------
# 4.2.2 — _audit_trace_markdown (pure function)
# ---------------------------------------------------------------------------


class TestAuditTraceMarkdown:
    def test_empty_history_shows_placeholder(self) -> None:
        md: str = _audit_trace_markdown([])
        assert "No audit trace" in md or "no audit" in md.lower()

    def test_two_steps_show_two_drafts_and_two_verdicts(self) -> None:
        history = [
            {
                "draft": "First draft.",
                "verdict": "REVISE",
                "critique": "Missing glossary term.",
                "violations": ["missing term"],
                "confidence": 0.8,
            },
            {
                "draft": "Second draft with contract of sale.",
                "verdict": "APPROVE",
                "critique": "",
                "violations": [],
                "confidence": 0.95,
            },
        ]
        md: str = _audit_trace_markdown(history)
        assert "First draft." in md
        assert "Second draft with contract of sale." in md
        assert md.count("REVISE") >= 1
        assert md.count("APPROVE") >= 1
        assert "Missing glossary term." in md


# ---------------------------------------------------------------------------
# 4.2.1 / 4.2.2 — run_translation_streamed (mocked adapters)
# ---------------------------------------------------------------------------


class TestRunTranslationStreamed:
    def test_approve_first_pass_one_draft_one_verdict(
        self, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        llm = _SequenceMockLLM()
        llm.set_response_sequence("translator", ["The contract of sale."])
        llm.set_response_sequence(
            "auditor",
            [json.dumps({
                "verdict": "APPROVE", "critique": "", "violations": [],
                "confidence": 0.95,
            })],
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        state, history = run_translation_streamed(
            "المادة 148: عقد البيع", "ar-en", config,
            llm=llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert state["final_output"] == "The contract of sale."
        assert state["audit"]["verdict"] == "APPROVE"
        assert len(history) == 1
        assert history[0]["draft"] == "The contract of sale."
        assert history[0]["verdict"] == "APPROVE"

    def test_revise_then_approve_two_drafts_two_verdicts(
        self, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        """4.2.2 verify step: REVISE-then-APPROVE -> 2 drafts and 2 verdicts."""
        llm = _SequenceMockLLM()
        llm.set_response_sequence(
            "translator",
            ["Bad draft missing term.", "Good draft with contract of sale."],
        )
        llm.set_response_sequence(
            "auditor",
            [
                json.dumps({
                    "verdict": "REVISE", "critique": "Missing term.",
                    "violations": ["missing term"], "confidence": 0.7,
                }),
                json.dumps({
                    "verdict": "APPROVE", "critique": "",
                    "violations": [], "confidence": 0.95,
                }),
            ],
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        state, history = run_translation_streamed(
            "المادة 148: عقد البيع", "ar-en", config,
            llm=llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert state["final_output"] == "Good draft with contract of sale."
        assert state["audit"]["verdict"] == "APPROVE"
        assert state["revision_count"] == 1
        # The audit trace must contain 2 drafts and 2 verdicts.
        assert len(history) == 2
        drafts = [step["draft"] for step in history]
        verdicts = [step["verdict"] for step in history]
        assert drafts == [
            "Bad draft missing term.", "Good draft with contract of sale."
        ]
        assert verdicts == ["REVISE", "APPROVE"]
        assert history[0]["critique"] == "Missing term."


# ---------------------------------------------------------------------------
# 4.2.1 — _translate_for_ui (mocked adapters)
# ---------------------------------------------------------------------------


class TestTranslateForUi:
    def test_returns_translation_provenance_and_trace(
        self, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        llm = _SequenceMockLLM()
        llm.set_response_sequence(
            "translator",
            ["Bad draft.", "Good draft with contract of sale."],
        )
        llm.set_response_sequence(
            "auditor",
            [
                json.dumps({
                    "verdict": "REVISE", "critique": "fix", "violations": [],
                    "confidence": 0.7,
                }),
                json.dumps({
                    "verdict": "APPROVE", "critique": "",
                    "violations": [], "confidence": 0.95,
                }),
            ],
        )
        persist_dir = _build_chroma(tmp_path, mock_embedder, config)
        result = _translate_for_ui(
            "المادة 148: عقد البيع", "ar-en", config,
            llm=llm, embedder=mock_embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
        )
        assert result.translation == "Good draft with contract of sale."
        assert "contract of sale" in result.provenance_md
        # The trace reflects the full revision history.
        assert "Bad draft." in result.audit_trace_md
        assert "Good draft with contract of sale." in result.audit_trace_md
        assert "REVISE" in result.audit_trace_md
        assert "APPROVE" in result.audit_trace_md


# ---------------------------------------------------------------------------
# 4.2.1 — ui command (CliRunner, --help only; launch not CI-testable)
# ---------------------------------------------------------------------------


class TestUiCommand:
    def test_help_exits_0(self) -> None:
        result = runner.invoke(app, ["ui", "--help"])
        assert result.exit_code == 0
        assert "Tkinter" in result.stdout or "--config" in result.stdout


# ---------------------------------------------------------------------------
# 4.3.2 — graceful Ollama-daemon-down handling (exit code 2, no traceback)
# ---------------------------------------------------------------------------


class TestOllamaDownHandling:
    """The CLI must exit 2 with a human-readable message when the Ollama daemon
    is unreachable, and must not dump a traceback (task 4.3.2 verify step)."""

    def test_translate_ollama_down_exits_2(self, tmp_path: Path) -> None:
        with patch(
            "src.components.interfaces.cli.run_translation",
            side_effect=OllamaConnectionError(
                "cannot reach Ollama daemon at http://localhost:11434"
            ),
        ), patch(
            "src.components.knowledge_sources.glossary.load_glossary_index",
            return_value=None,
        ):
            result = runner.invoke(app, [
                "translate", "--input", "المادة 148", "--direction", "ar-en",
            ])
        assert result.exit_code == 2
        combined: str = (result.stdout or "") + (result.output or "")
        assert "Traceback" not in combined
        assert "ollama" in combined.lower()

    def test_translate_embedding_engine_down_exits_2(
        self, tmp_path: Path
    ) -> None:
        with patch(
            "src.components.interfaces.cli.run_translation",
            side_effect=EmbeddingConnectionError(
                "cannot reach embedding engine at http://localhost:11434"
            ),
        ), patch(
            "src.components.knowledge_sources.glossary.load_glossary_index",
            return_value=None,
        ):
            result = runner.invoke(app, [
                "translate", "--input", "المادة 148", "--direction", "ar-en",
            ])
        assert result.exit_code == 2
        combined = (result.stdout or "") + (result.output or "")
        assert "Traceback" not in combined

    def test_batch_ollama_down_exits_2(self, tmp_path: Path) -> None:
        input_path: Path = tmp_path / "in.jsonl"
        input_path.write_text(
            json.dumps({"input": "x", "direction": "ar-en"}) + "\n",
            encoding="utf-8",
        )
        output_path: Path = tmp_path / "out.jsonl"
        with patch(
            "src.components.interfaces.cli._process_batch",
            side_effect=OllamaConnectionError("daemon down"),
        ), patch(
            "src.components.knowledge_sources.glossary.load_glossary_index",
            return_value=None,
        ), patch(
            "src.components.interfaces.cli.validate_path_in_root",
            side_effect=lambda p, r: p,
        ):
            result = runner.invoke(app, [
                "batch", "--input", str(input_path), "--out", str(output_path),
            ])
        assert result.exit_code == 2
        combined = (result.stdout or "") + (result.output or "")
        assert "Traceback" not in combined
        assert "ollama" in combined.lower()

    def test_translate_generic_error_still_exits_1(self) -> None:
        """Non-connection errors keep the existing exit-code-1 behaviour."""
        with patch(
            "src.components.interfaces.cli.run_translation",
            side_effect=RuntimeError("unexpected boom"),
        ), patch(
            "src.components.knowledge_sources.glossary.load_glossary_index",
            return_value=None,
        ):
            result = runner.invoke(app, [
                "translate", "--input", "المادة 148", "--direction", "ar-en",
            ])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# 4.3.3 — RAM guard CLI handling (clear abort message, no traceback)
# ---------------------------------------------------------------------------


class TestRamGuardCli:
    def test_translate_low_ram_aborts_with_clear_message(self) -> None:
        from src.components.translation_pipeline.exceptions import RAMGuardError

        with patch(
            "src.components.interfaces.cli.run_translation",
            side_effect=RAMGuardError(
                "Only 0.40 GB of RAM available (minimum 1.5 GB required)."
            ),
        ), patch(
            "src.components.knowledge_sources.glossary.load_glossary_index",
            return_value=None,
        ):
            result = runner.invoke(app, [
                "translate", "--input", "المادة 148", "--direction", "ar-en",
            ])
        assert result.exit_code == 3
        combined: str = (result.stdout or "") + (result.output or "")
        assert "Traceback" not in combined
        assert "ram" in combined.lower()

    def test_batch_low_ram_aborts_with_clear_message(
        self, tmp_path: Path
    ) -> None:
        from src.components.translation_pipeline.exceptions import RAMGuardError

        input_path: Path = tmp_path / "in.jsonl"
        input_path.write_text(
            json.dumps({"input": "x", "direction": "ar-en"}) + "\n",
            encoding="utf-8",
        )
        output_path: Path = tmp_path / "out.jsonl"
        with patch(
            "src.components.interfaces.cli._process_batch",
            side_effect=RAMGuardError("low RAM"),
        ), patch(
            "src.components.knowledge_sources.glossary.load_glossary_index",
            return_value=None,
        ), patch(
            "src.components.interfaces.cli.validate_path_in_root",
            side_effect=lambda p, r: p,
        ):
            result = runner.invoke(app, [
                "batch", "--input", str(input_path), "--out", str(output_path),
            ])
        assert result.exit_code == 3
        combined = (result.stdout or "") + (result.output or "")
        assert "Traceback" not in combined


# ---------------------------------------------------------------------------
# 4.1.4 tm-build command (task 8)
# ---------------------------------------------------------------------------


class TestTmBuildCommand:
    def test_tm_build_command_creates_db(self, tmp_path: Path) -> None:
        import sqlite3

        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        (corpus_dir / "civil_code_ar.txt").write_text(
            "LAW: قانون\nLANG: ar\n---\n\nARTICLE 1\nعقد البيع\n",
            encoding="utf-8",
        )
        (corpus_dir / "civil_code_en.txt").write_text(
            "LAW: Code\nLANG: en\n---\n\nARTICLE 1\nContract of sale\n",
            encoding="utf-8",
        )
        tm_db = str(tmp_path / "tm.sqlite")

        result = runner.invoke(
            app, ["tm-build", "--corpus-dir", str(corpus_dir), "--tm-db", tm_db]
        )
        assert result.exit_code == 0
        conn = sqlite3.connect(tm_db)
        count = conn.execute("SELECT COUNT(*) FROM tm_entries").fetchone()[0]
        conn.close()
        assert count > 0

    def test_help_exits_0(self) -> None:
        result = runner.invoke(app, ["tm-build", "--help"])
        assert result.exit_code == 0
        assert "--corpus-dir" in result.stdout
