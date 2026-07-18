"""Graph assembly tests for tasks 3.3.x (``src/graph.py``).

Covers:
- 3.3.1: ``build_graph`` compiles; the compiled graph exposes the expected
  topology (preprocess -> translate -> audit -> {finalize | translate} ->
  END).
- 3.3.2: ``route_audit`` enforces the max-revision cap; a graph whose auditor
  always returns REVISE terminates with ``revision_count == max_revisions``
  and a max-revision warning; a graph whose auditor approves terminates on
  the first pass.
- 3.3.3: state-mutation-ownership assertions inside each node —
  ``finalize_node`` with a state missing ``draft`` raises ``AssertionError``.

The full-pipeline tests inject the deterministic ``mock_llm`` /
``mock_embedder`` / in-memory ``GlossaryIndex`` / a temp ChromaDB collection
(testing-verification §3.4) — no Ollama daemon, no network.
"""
from __future__ import annotations

import json

import pytest

from src.components.knowledge_sources.ingestion import Chunk
from src.components.knowledge_sources.retrieval import build_chroma_collection
from src.components.translation_pipeline.graph import build_graph, route_audit
from src.components.translation_pipeline.models import TranslationState
from src.components.translation_pipeline.nodes import finalize_node

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _fixture_chunks() -> list[Chunk]:
    """A minimal bilingual fixture corpus for graph-flow tests."""
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


def _initial_state(input_text: str = "المادة 148: عقد البيع") -> TranslationState:
    """Minimal LangGraph input: only the caller-supplied fields."""
    return {
        "input_text": input_text,
        "direction": "ar-en",
        "glossary_hits": [],
        "context_chunks": [],
        "tm_hits": [],
        "web_search_results": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
    }


def _build_test_graph(
    *,
    mock_llm,
    mock_embedder,
    glossary_index,
    tmp_path,
    config,
):
    """Build a compiled graph wired with deterministic test adapters."""
    build_chroma_collection(
        _fixture_chunks(),
        persist_dir=tmp_path / "chroma",
        embedder=mock_embedder,
        cfg=config,
    )
    return build_graph(
        llm=mock_llm,
        cfg=config,
        glossary_index=glossary_index,
        embedder=mock_embedder,
        persist_dir=str(tmp_path / "chroma"),
    )


# ---------------------------------------------------------------------------
# 3.3.1 graph compiles + topology
# ---------------------------------------------------------------------------


class TestGraphCompiles:
    def test_build_graph_returns_compiled_runnable(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        graph = _build_test_graph(
            mock_llm=mock_llm,
            mock_embedder=mock_embedder,
            glossary_index=glossary_index,
            tmp_path=tmp_path,
            config=config,
        )
        # A compiled LangGraph runnable exposes `invoke` (runs the pipeline).
        assert hasattr(graph, "invoke")
        assert hasattr(graph, "builder")  # the underlying StateGraph

    def test_expected_topology_nodes_present(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        graph = _build_test_graph(
            mock_llm=mock_llm,
            mock_embedder=mock_embedder,
            glossary_index=glossary_index,
            tmp_path=tmp_path,
            config=config,
        )
        # `compiled.nodes` maps node name -> Node; LangGraph adds __start__.
        node_ids: set[str] = set(graph.nodes.keys())
        # The four real nodes must all be present (ARCHITECTURE.md §4.2). The
        # Auditor Agent node is named ``auditor`` (not ``audit``) to avoid
        # colliding with the ``audit`` state key under LangGraph 0.2.x.
        assert {"preprocess", "web_search", "translate", "auditor",
                "finalize"}.issubset(node_ids)

    def test_expected_topology_edges(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        graph = _build_test_graph(
            mock_llm=mock_llm,
            mock_embedder=mock_embedder,
            glossary_index=glossary_index,
            tmp_path=tmp_path,
            config=config,
        )
        edges: dict[str, str] = dict(graph.builder.edges)
        # Static edges: START->preprocess, preprocess->web_search,
        # web_search->tm_lookup, translate->auditor, tm_bypass->finalize,
        # finalize->END.
        assert edges["__start__"] == "preprocess"
        assert edges["preprocess"] == "web_search"
        assert edges["web_search"] == "tm_lookup"
        assert edges["translate"] == "auditor"
        assert edges["tm_bypass"] == "finalize"
        assert edges["finalize"] == "__end__"
        # The tm_lookup->? and audit->? edges are conditional, so they live in
        # `branches`, not `edges`: tm_lookup forks (route_after_tm) to
        # {tm_bypass | translate}, and auditor forks (route_audit) to
        # {finalize | translate}.
        assert "tm_lookup" in graph.builder.branches
        assert "auditor" in graph.builder.branches


# ---------------------------------------------------------------------------
# 3.3.2 route_audit unit tests
# ---------------------------------------------------------------------------


class TestRouteAudit:
    def test_approve_routes_to_finalize(self) -> None:
        state: TranslationState = _initial_state()
        state["audit"] = {
            "verdict": "APPROVE",
            "critique": "",
            "violations": [],
            "confidence": 0.95,
        }
        assert route_audit(state, max_revisions=3) == "finalize"

    def test_revise_under_cap_routes_to_translate(self) -> None:
        state: TranslationState = _initial_state()
        state["draft"] = "draft"
        state["revision_count"] = 1
        state["audit"] = {
            "verdict": "REVISE",
            "critique": "fix",
            "violations": ["v"],
            "confidence": 0.5,
        }
        assert route_audit(state, max_revisions=3) == "translate"

    def test_revise_at_cap_routes_to_finalize(self) -> None:
        state: TranslationState = _initial_state()
        state["draft"] = "draft"
        state["revision_count"] = 3
        state["audit"] = {
            "verdict": "REVISE",
            "critique": "still wrong",
            "violations": ["v"],
            "confidence": 0.5,
        }
        assert route_audit(state, max_revisions=3) == "finalize"

    def test_cap_respects_configured_max(self) -> None:
        state: TranslationState = _initial_state()
        state["draft"] = "draft"
        state["revision_count"] = 5
        state["audit"] = {
            "verdict": "REVISE",
            "critique": "",
            "violations": [],
            "confidence": 0.0,
        }
        assert route_audit(state, max_revisions=5) == "finalize"


# ---------------------------------------------------------------------------
# 3.3.2 full revision loop (mocked LLM)
# ---------------------------------------------------------------------------


class TestRevisionLoop:
    def test_terminates_on_approve_first_pass(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        mock_llm.set_response(
            "translator", "Contract of sale is a nominate contract."
        )
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE",
                "critique": "",
                "violations": [],
                "confidence": 0.95,
            }),
        )
        graph = _build_test_graph(
            mock_llm=mock_llm,
            mock_embedder=mock_embedder,
            glossary_index=glossary_index,
            tmp_path=tmp_path,
            config=config,
        )
        result = graph.invoke(_initial_state())
        assert result["audit"]["verdict"] == "APPROVE"
        assert result["revision_count"] == 0
        assert result["final_output"] is not None
        assert result["final_output"] == "Contract of sale is a nominate contract."

    def test_caps_at_max_revisions_when_auditor_always_revise(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        mock_llm.set_response("translator", "Bad translation attempt.")
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "REVISE",
                "critique": "Glossary term missing.",
                "violations": ["missing term"],
                "confidence": 0.8,
            }),
        )
        graph = _build_test_graph(
            mock_llm=mock_llm,
            mock_embedder=mock_embedder,
            glossary_index=glossary_index,
            tmp_path=tmp_path,
            config=config,
        )
        result = graph.invoke(_initial_state())
        # The cap is cfg.max_revisions (3). The loop emits a best-effort draft.
        assert result["revision_count"] == config.max_revisions
        assert result["final_output"] is not None
        assert any(
            "max" in w.lower() or "revision" in w.lower()
            for w in result["warnings"]
        )
        assert result["audit"]["verdict"] == "REVISE"

    def test_glossary_term_appears_verbatim_in_output(
        self, mock_llm, mock_embedder, glossary_index, tmp_path, config
    ) -> None:
        """Phase 3 exit-criterion slice: a glossary term in the source must
        appear verbatim in the final output when the auditor approves."""
        mock_llm.set_response(
            "translator", "The contract of sale transfers ownership."
        )
        mock_llm.set_response(
            "auditor",
            json.dumps({
                "verdict": "APPROVE",
                "critique": "",
                "violations": [],
                "confidence": 0.95,
            }),
        )
        graph = _build_test_graph(
            mock_llm=mock_llm,
            mock_embedder=mock_embedder,
            glossary_index=glossary_index,
            tmp_path=tmp_path,
            config=config,
        )
        result = graph.invoke(_initial_state("المادة 148: عقد البيع"))
        # The source contains the glossary term "عقد البيع" -> "contract of
        # sale"; the approved draft must contain the canonical target term.
        assert "contract of sale" in result["final_output"].lower()


# ---------------------------------------------------------------------------
# 3.3.3 state-mutation-ownership assertions
# ---------------------------------------------------------------------------


class TestStateMutationOwnership:
    def test_finalize_missing_draft_raises_assertion(self, config) -> None:
        state: dict = {
            "input_text": "عقد البيع",
            "direction": "ar-en",
            "glossary_hits": [],
            "context_chunks": [],
            "audit": None,
            "revision_count": 0,
            "final_output": None,
            "warnings": [],
        }
        with pytest.raises(AssertionError):
            finalize_node(state, cfg=config)  # type: ignore[arg-type]

    def test_finalize_with_draft_does_not_raise(self, config) -> None:
        state: TranslationState = _initial_state()
        state["draft"] = "contract of sale"
        state["audit"] = {
            "verdict": "APPROVE",
            "critique": "",
            "violations": [],
            "confidence": 0.95,
        }
        result = finalize_node(state, cfg=config)
        assert result["final_output"] == "contract of sale"


# ---------------------------------------------------------------------------
# 3.3.4 tm_lookup node wiring (task 6)
# ---------------------------------------------------------------------------


def test_graph_includes_tm_lookup_node_when_enabled(
    config, mock_llm, mock_embedder, glossary_index, tmp_path
):
    from src.components.translation_pipeline.graph import build_graph
    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(_fixture_chunks(), persist_dir=persist_dir, embedder=mock_embedder)
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون\nLANG: ar\n---\n\nARTICLE 1\nعقد البيع\n", encoding="utf-8")
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Code\nLANG: en\n---\n\nARTICLE 1\nContract of sale\n", encoding="utf-8")
    from src.components.knowledge_sources.tm import TranslationMemory
    tm = TranslationMemory(db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    graph = build_graph(
        llm=mock_llm, cfg=config, glossary_index=glossary_index,
        embedder=mock_embedder, persist_dir=persist_dir, tm=tm)
    state = _initial_state("عقد البيع")
    result = graph.invoke(state)
    assert "tm_hits" in result
    tm.close()


def test_graph_skips_tm_lookup_when_tm_is_none(
    config, mock_llm, mock_embedder, glossary_index, tmp_path
):
    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(_fixture_chunks(), persist_dir=persist_dir, embedder=mock_embedder)
    graph = build_graph(
        llm=mock_llm, cfg=config, glossary_index=glossary_index,
        embedder=mock_embedder, persist_dir=persist_dir, tm=None)
    state = _initial_state("المادة 148: عقد البيع")
    result = graph.invoke(state)
    assert result["tm_hits"] == []


# ---------------------------------------------------------------------------
# TM bypass: a >= threshold hit skips the LLM entirely (spec §5.4)
# ---------------------------------------------------------------------------


def _build_tm(tmp_path):
    """Build a small TM whose ARTICLE 1 pair is عقد البيع -> Contract of sale."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون\nLANG: ar\n---\n\nARTICLE 1\nعقد البيع\n", encoding="utf-8")
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Code\nLANG: en\n---\n\nARTICLE 1\nContract of sale\n",
        encoding="utf-8")
    from src.components.knowledge_sources.tm import TranslationMemory
    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"), similarity_threshold=0.98)
    tm.build_from_corpus(corpus_dir)
    return tm


def test_tm_hit_bypasses_the_llm(
    config, mock_llm, mock_embedder, glossary_index, tmp_path
):
    """A >= threshold TM hit emits the stored translation without any LLM call."""
    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(_fixture_chunks(), persist_dir=persist_dir, embedder=mock_embedder)
    tm = _build_tm(tmp_path)
    graph = build_graph(
        llm=mock_llm, cfg=config, glossary_index=glossary_index,
        embedder=mock_embedder, persist_dir=persist_dir, tm=tm)
    result = graph.invoke(_initial_state("عقد البيع"))
    assert result["final_output"] == "Contract of sale"
    # Neither the translator nor the auditor was called.
    assert mock_llm.call_log == []
    assert result["audit"]["verdict"] == "APPROVE"
    tm.close()


def test_tm_miss_invokes_the_llm(
    config, mock_llm, mock_embedder, glossary_index, tmp_path
):
    """A below-threshold input falls through to the normal translate/audit path."""
    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(_fixture_chunks(), persist_dir=persist_dir, embedder=mock_embedder)
    tm = _build_tm(tmp_path)
    graph = build_graph(
        llm=mock_llm, cfg=config, glossary_index=glossary_index,
        embedder=mock_embedder, persist_dir=persist_dir, tm=tm)
    result = graph.invoke(
        _initial_state("نص قانوني مختلف تماماً لا يطابق أي شيء في الذاكرة."))
    assert result["tm_hits"] == []
    assert result["final_output"] == "[Mock translation output]"
    # The LLM ran for both the translator and the auditor.
    assert len(mock_llm.call_log) >= 2
    tm.close()


class TestRouteAfterTm:
    def test_hit_above_threshold_routes_to_bypass(self) -> None:
        from src.components.translation_pipeline.graph import route_after_tm
        state = _initial_state()
        state["tm_hits"] = [{
            "source_sentence": "s", "target_sentence": "t",
            "similarity": 1.0, "char_start": 0, "char_end": 1,
        }]
        assert route_after_tm(state, threshold=0.98) == "tm_bypass"

    def test_no_hit_routes_to_translate(self) -> None:
        from src.components.translation_pipeline.graph import route_after_tm
        state = _initial_state()
        state["tm_hits"] = []
        assert route_after_tm(state, threshold=0.98) == "translate"
