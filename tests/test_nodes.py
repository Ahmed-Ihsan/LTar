"""Unit/integration tests for the LangGraph node functions (tasks 3.2.x).

The ``preprocess`` node is tested with a real in-memory
:class:`GlossaryIndex` (deterministic) and a real ChromaDB ``PersistentClient``
in a ``tmp_path`` populated via the deterministic mock embedder — no Ollama
daemon, no network (testing-verification skill §2.2 / §3).

The ``translate`` / ``audit`` / ``finalize`` nodes are tested with the
:class:`MockEngineAdapter` fixture (testing-verification §3.1) so no real LLM
runs in CI.
"""
from __future__ import annotations

import json

import pytest

from src.components.translation_pipeline.exceptions import OllamaConnectionError, OllamaTimeoutError
from src.components.knowledge_sources.glossary import GlossaryIndex
from src.components.knowledge_sources.ingestion import Chunk
from src.components.translation_pipeline.nodes import (
    audit_node,
    finalize_node,
    preprocess_node,
    translate_node,
)
from src.components.knowledge_sources.retrieval import build_chroma_collection
from src.components.translation_pipeline.models import TranslationState

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _fixture_chunks() -> list[Chunk]:
    """Build deterministic chunks including the contract-of-sale article."""
    chunks: list[Chunk] = [
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
    return chunks


def _state(
    input_text: str = "المادة 148: عقد البيع",
    direction: str = "ar-en",
    draft: str = "",
    audit: object = None,
    revision_count: int = 0,
    glossary_hits: list | None = None,
    context_chunks: list | None = None,
    final_output: object = None,
    warnings: list | None = None,
) -> TranslationState:
    return {
        "input_text": input_text,
        "direction": direction,  # type: ignore[arg-type]
        "glossary_hits": glossary_hits if glossary_hits is not None else [],
        "context_chunks": context_chunks if context_chunks is not None else [],
        "tm_hits": [],
        "web_search_results": [],
        "draft": draft,
        "audit": audit,  # type: ignore[arg-type]
        "revision_count": revision_count,
        "final_output": final_output,  # type: ignore[arg-type]
        "warnings": warnings if warnings is not None else [],
    }


# ---------------------------------------------------------------------------
# 3.2.1 preprocess_node
# ---------------------------------------------------------------------------


class TestPreprocessNode:
    def test_populates_glossary_hits_and_context_chunks(
        self,
        glossary_index: GlossaryIndex,
        mock_embedder,
        tmp_path,
        config,
    ) -> None:
        build_chroma_collection(
            _fixture_chunks(),
            persist_dir=tmp_path / "chroma",
            embedder=mock_embedder,
            cfg=config,
        )
        state: TranslationState = _state("المادة 148: عقد البيع", "ar-en")
        result = preprocess_node(
            state,
            glossary_index=glossary_index,
            embedder=mock_embedder,
            persist_dir=tmp_path / "chroma",
            cfg=config,
        )
        assert len(result["glossary_hits"]) >= 1
        assert any(
            h["source_term"] == "عقد البيع" for h in result["glossary_hits"]
        )
        assert len(result["context_chunks"]) >= 1

    def test_empty_retrieval_appends_warning(
        self,
        glossary_index: GlossaryIndex,
        mock_embedder,
        tmp_path,
        config,
    ) -> None:
        # Build an empty collection so retrieval yields nothing.
        build_chroma_collection(
            [_fixture_chunks()[0]],
            persist_dir=tmp_path / "chroma",
            embedder=mock_embedder,
            cfg=config,
        )
        # Query with text that won't match the single chunk well; force empty
        # by using a persist dir with a freshly built collection of 1 chunk and
        # asking for n_results larger than the corpus is fine — we instead test
        # the warning path via a non-matching query is unreliable with the mock
        # embedder. Instead, point at a non-existent collection path to force
        # the empty path is not possible (it raises). So we assert the warning
        # is appended when context_chunks is empty after retrieval by using a
        # query that the mock embedder maps to no close neighbour is not
        # deterministic. Use a direct empty-retrieval simulation: build a
        # collection, then delete it so the dir is gone -> query returns empty
        # is not the contract. The cleanest deterministic empty path: an empty
        # query string returns [] from ChromaStore.query.
        state: TranslationState = _state("", "ar-en")
        result = preprocess_node(
            state,
            glossary_index=glossary_index,
            embedder=mock_embedder,
            persist_dir=tmp_path / "chroma",
            cfg=config,
        )
        assert result["context_chunks"] == []
        assert any("empty" in w.lower() or "context" in w.lower()
                   for w in result["warnings"])

    def test_preserves_input_text_and_direction(
        self,
        glossary_index: GlossaryIndex,
        mock_embedder,
        tmp_path,
        config,
    ) -> None:
        build_chroma_collection(
            _fixture_chunks(),
            persist_dir=tmp_path / "chroma",
            embedder=mock_embedder,
            cfg=config,
        )
        state: TranslationState = _state("عقد البيع", "ar-en")
        result = preprocess_node(
            state,
            glossary_index=glossary_index,
            embedder=mock_embedder,
            persist_dir=tmp_path / "chroma",
            cfg=config,
        )
        assert result["input_text"] == "عقد البيع"
        assert result["direction"] == "ar-en"


# ---------------------------------------------------------------------------
# 3.2.2 translate_node
# ---------------------------------------------------------------------------


class TestTranslateNode:
    def test_first_pass_produces_nonempty_draft(
        self, mock_llm, config
    ) -> None:
        mock_llm.set_response("translator", "Contract of sale transfers ownership.")
        state: TranslationState = _state("عقد البيع", "ar-en")
        result = translate_node(state, llm=mock_llm, cfg=config)
        assert result["draft"]
        assert result["draft"] == "Contract of sale transfers ownership."

    def test_first_pass_resets_revision_count_to_zero(
        self, mock_llm, config
    ) -> None:
        mock_llm.set_response("translator", "draft output")
        state: TranslationState = _state("عقد البيع", "ar-en", revision_count=0)
        result = translate_node(state, llm=mock_llm, cfg=config)
        assert result["revision_count"] == 0

    def test_revision_pass_injects_prior_draft_and_critique(
        self, mock_llm, config
    ) -> None:
        mock_llm.set_response("translator", "revised draft output")
        state: TranslationState = _state(
            "عقد البيع", "ar-en",
            draft="prior draft",
            revision_count=1,
            audit={
                "verdict": "REVISE",
                "critique": "Glossary term missing.",
                "violations": ["glossary: عقد البيع"],
                "confidence": 0.8,
            },
        )
        result = translate_node(state, llm=mock_llm, cfg=config)
        assert result["draft"] == "revised draft output"
        assert result["revision_count"] == 2
        # The revision addendum must be present in the system prompt sent.
        assert mock_llm.call_log
        system_prompt: str = mock_llm.call_log[-1][0]
        assert "REVISION" in system_prompt or "revision" in system_prompt

    def test_revision_pass_prior_draft_appears_in_user_prompt(
        self, mock_llm, config
    ) -> None:
        mock_llm.set_response("translator", "revised")
        state: TranslationState = _state(
            "عقد البيع", "ar-en",
            draft="PRIOR DRAFT TEXT",
            revision_count=1,
            audit={
                "verdict": "REVISE",
                "critique": "fix it",
                "violations": ["v1"],
                "confidence": 0.5,
            },
        )
        translate_node(state, llm=mock_llm, cfg=config)
        user_prompt: str = mock_llm.call_log[-1][1]
        assert "PRIOR DRAFT TEXT" in user_prompt
        assert "fix it" in user_prompt

    def test_propagates_connection_error(self, mock_llm, config) -> None:
        mock_llm.set_fail_mode("connection")
        state: TranslationState = _state("عقد البيع", "ar-en")
        with pytest.raises(OllamaConnectionError):
            translate_node(state, llm=mock_llm, cfg=config)

    def test_propagates_timeout_error(self, mock_llm, config) -> None:
        mock_llm.set_fail_mode("timeout")
        state: TranslationState = _state("عقد البيع", "ar-en")
        with pytest.raises(OllamaTimeoutError):
            translate_node(state, llm=mock_llm, cfg=config)


# ---------------------------------------------------------------------------
# 3.2.3 audit_node
# ---------------------------------------------------------------------------


class TestAuditNode:
    def test_approve_verdict_parsed(self, mock_llm, config) -> None:
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE",
                "critique": "ok",
                "violations": [],
                "confidence": 0.9,
            }),
        )
        state: TranslationState = _state(
            "عقد البيع", "ar-en", draft="contract of sale",
            glossary_hits=[{
                "source_term": "عقد البيع",
                "target_term": "contract of sale",
                "law_ref": "Civil Code",
                "article_ref": "148",
                "note": "",
                "char_start": 0,
                "char_end": 8,
            }],
        )
        result = audit_node(state, llm=mock_llm, cfg=config)
        assert result["audit"]["verdict"] == "APPROVE"
        assert result["audit"]["confidence"] == 0.9

    def test_glossary_violating_draft_returns_revise_with_violation(
        self, mock_llm, config
    ) -> None:
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "REVISE",
                "critique": "1. Glossary term 'عقد البيع' not rendered as "
                            "'contract of sale'.",
                "violations": [
                    "Glossary: 'عقد البيع' must be 'contract of sale'"
                ],
                "confidence": 0.7,
            }),
        )
        state: TranslationState = _state(
            "عقد البيع", "ar-en", draft="sale agreement",
            glossary_hits=[{
                "source_term": "عقد البيع",
                "target_term": "contract of sale",
                "law_ref": "Civil Code",
                "article_ref": "148",
                "note": "",
                "char_start": 0,
                "char_end": 8,
            }],
        )
        result = audit_node(state, llm=mock_llm, cfg=config)
        assert result["audit"]["verdict"] == "REVISE"
        assert len(result["audit"]["violations"]) >= 1

    def test_strips_markdown_fences_before_parse(self, mock_llm, config) -> None:
        verdict_json: str = json.dumps({
            "verdict": "APPROVE",
            "critique": "",
            "violations": [],
            "confidence": 0.95,
        })
        mock_llm.set_response("auditor", f"```json\n{verdict_json}\n```")
        state: TranslationState = _state(
            "عقد البيع", "ar-en", draft="contract of sale",
        )
        result = audit_node(state, llm=mock_llm, cfg=config)
        assert result["audit"]["verdict"] == "APPROVE"

    def test_unparseable_output_defaults_to_revise(
        self, mock_llm, config
    ) -> None:
        mock_llm.set_response("auditor", "This is not JSON at all.")
        state: TranslationState = _state(
            "عقد البيع", "ar-en", draft="contract of sale",
        )
        result = audit_node(state, llm=mock_llm, cfg=config)
        assert result["audit"]["verdict"] == "REVISE"
        assert result["audit"]["confidence"] == 0.0
        assert "unparseable" in result["audit"]["critique"].lower()

    def test_missing_verdict_field_defaults_to_revise(
        self, mock_llm, config
    ) -> None:
        mock_llm.set_response(
            "auditor",
            json.dumps({"critique": "no verdict", "confidence": 0.5}),
        )
        state: TranslationState = _state(
            "عقد البيع", "ar-en", draft="contract of sale",
        )
        result = audit_node(state, llm=mock_llm, cfg=config)
        assert result["audit"]["verdict"] == "REVISE"

    def test_propagates_connection_error(self, mock_llm, config) -> None:
        mock_llm.set_fail_mode("connection")
        state: TranslationState = _state(
            "عقد البيع", "ar-en", draft="contract of sale",
        )
        with pytest.raises(OllamaConnectionError):
            audit_node(state, llm=mock_llm, cfg=config)


# ---------------------------------------------------------------------------
# 3.2.4 finalize_node
# ---------------------------------------------------------------------------


class TestFinalizeNode:
    def test_final_output_equals_draft_on_approve(self, config) -> None:
        state: TranslationState = _state(
            "عقد البيع", "ar-en",
            draft="contract of sale",
            audit={
                "verdict": "APPROVE",
                "critique": "",
                "violations": [],
                "confidence": 0.95,
            },
        )
        result = finalize_node(state, cfg=config)
        assert result["final_output"] == "contract of sale"

    def test_revise_at_cap_emits_best_effort_and_warning(
        self, config
    ) -> None:
        state: TranslationState = _state(
            "عقد البيع", "ar-en",
            draft="best effort draft",
            audit={
                "verdict": "REVISE",
                "critique": "still wrong",
                "violations": ["v1"],
                "confidence": 0.5,
            },
            revision_count=3,
        )
        result = finalize_node(state, cfg=config)
        assert result["final_output"] == "best effort draft"
        assert any("max" in w.lower() or "revision" in w.lower()
                   for w in result["warnings"])

    def test_approve_does_not_add_cap_warning(self, config) -> None:
        state: TranslationState = _state(
            "عقد البيع", "ar-en",
            draft="contract of sale",
            audit={
                "verdict": "APPROVE",
                "critique": "",
                "violations": [],
                "confidence": 0.95,
            },
            revision_count=0,
        )
        result = finalize_node(state, cfg=config)
        assert result["warnings"] == []
