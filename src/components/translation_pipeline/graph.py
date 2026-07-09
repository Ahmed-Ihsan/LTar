"""LangGraph orchestration: wire nodes into the compiled state machine.

Single responsibility (per ARCHITECTURE.md §1.1 / engineering-principles §1.1):
define the graph topology
``preprocess -> translate -> audit -> [approve | revise] -> finalize -> END``
with a bounded revision loop (``max_revisions`` from ``config.yaml``). This
module is the ONLY place the topology lives; node behaviour lives in
``src.nodes`` and engines live behind adapters (engineering-principles §1.1).

Decoupled from the Ollama runtime: the four node functions receive their
engines (LLM, glossary index, embedder, persist dir, config) via dependency
injection. ``build_graph`` binds those dependencies with ``functools.partial``
so LangGraph — which only passes ``state`` to a node — calls fully-wired
closures (DIP, engineering-principles §1.5 / §3.1). No concrete engine is
imported here (engineering-principles §3.7 rule 4).

Implemented in Phase 3 (tasks 3.3.x).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph

from src.config import AppConfig
from src.components.translation_pipeline.decision import route_tm
from src.glossary import GlossaryIndex
from src.llm import LLMEngineAdapter
from src.components.translation_pipeline.nodes import (
    audit_node,
    finalize_node,
    preprocess_node,
    tm_bypass_node,
    tm_lookup_node,
    translate_node,
    web_search_node,
)
from src.run_logging import RunLogger
from src.components.translation_pipeline.models import TranslationState

# A node callable after dependency binding: ``(state) -> state``.
_NodeCallable = Callable[[TranslationState], TranslationState]

# Node identifiers — a closed set shared by the graph and its tests (DRY,
# clean-code §1.1: closed string sets as constants).
PREPROCESS_NODE: str = "preprocess"
WEB_SEARCH_NODE: str = "web_search"
TM_LOOKUP_NODE: str = "tm_lookup"
TM_BYPASS_NODE: str = "tm_bypass"
TRANSLATE_NODE: str = "translate"
# LangGraph 0.2.x forbids a node name that collides with a state key. The
# state field that holds the verdict is ``audit`` (ARCHITECTURE.md §4.1), so
# the Auditor Agent node is named ``auditor`` — its agent name per
# engineering-principles §1.1 (Agent SRP) — to avoid the collision. The
# ARCHITECTURE.md §4.2 pseudocode uses ``"audit"`` illustratively; this is the
# necessary, documented deviation for the installed LangGraph version.
AUDIT_NODE: str = "auditor"
FINALIZE_NODE: str = "finalize"

# Conditional-edge return values (route_audit / route_after_tm outcomes). These
# double as the target node names, so the path map is the identity mapping.
_ROUTE_FINALIZE: str = "finalize"
_ROUTE_TRANSLATE: str = "translate"
_ROUTE_TM_BYPASS: str = "tm_bypass"


def route_after_tm(state: TranslationState, *, threshold: float) -> str:
    """Conditional edge after ``tm_lookup`` — TM bypass gate (spec §5.4).

    A pure routing function (it MUST NOT mutate state). Delegates the accept /
    reject decision to :func:`decision.route_tm`, the single source of truth
    for threshold gating:

    - a ``tm_hits`` entry with similarity ``>= threshold`` -> ``tm_bypass``
      (emit the stored translation, skipping the Translator and Auditor);
    - no hit, or a below-threshold hit -> ``translate`` (normal LLM path).

    ``threshold`` is bound at graph-build time from
    ``config.tm_similarity_threshold`` via ``functools.partial`` (DRY, no magic
    numbers). ``tm_lookup`` already gates at the store level; routing through
    ``route_tm`` here keeps the decision explicit, testable, and independent of
    the store implementation.
    """
    hits = state.get("tm_hits") or []
    hit = hits[0] if hits else None
    if route_tm(hit, threshold=threshold):
        return _ROUTE_TM_BYPASS
    return _ROUTE_TRANSLATE


def route_audit(state: TranslationState, *, max_revisions: int) -> str:
    """Conditional edge after the ``audit`` node (ARCHITECTURE.md §4.2/§4.3).

    A pure routing function — it MUST NOT mutate state. LangGraph does not
    persist mutations made inside a conditional-edge callable, and the
    max-revision warning is owned by ``finalize_node`` (ARCHITECTURE.md §4.4:
    finalize appends to ``warnings``). Routing is therefore verdict- and
    revision-count-driven only:

    - ``APPROVE`` -> ``finalize`` (terminate).
    - ``REVISE`` and ``revision_count < max_revisions`` -> ``translate``
      (another revision pass).
    - ``REVISE`` and ``revision_count >= max_revisions`` -> ``finalize``
      (cap reached; finalize emits the best-effort draft + warning).

    ``max_revisions`` is bound at graph-build time from ``config.yaml`` (DRY,
    engineering-principles §2.2.4: no magic numbers) via ``functools.partial``.
    """
    audit: Any = state.get("audit")
    verdict: str | None = (
        audit.get("verdict") if isinstance(audit, dict) else None
    )
    if verdict == "APPROVE":
        return _ROUTE_FINALIZE
    if state["revision_count"] >= max_revisions:
        return _ROUTE_FINALIZE
    return _ROUTE_TRANSLATE


def _wrap_with_logging(
    node_name: str, fn: _NodeCallable, logger: RunLogger
) -> _NodeCallable:
    """Wrap a node callable to emit one structured log line per execution.

    The wrapper times the node call and records the post-state metrics via
    :meth:`RunLogger.log_node` (task 4.3.1). It is applied here, in the
    orchestration module, so the node functions in ``src.nodes`` stay
    unmodified (OCP, engineering-principles §1.2).

    The inner callable deliberately carries no parameter annotations: LangGraph
    resolves node type hints via ``get_type_hints`` in ``add_node``, and a
    ``functools.wraps``-copied annotation string (e.g. ``"TranslationState"``)
    would be evaluated against this wrapper's globals and raise ``NameError``.
    An annotation-free wrapper makes ``get_type_hints`` return ``{}`` so the
    state schema declared on the :class:`StateGraph` is used instead.
    """
    def _logged(state):  # type: ignore[no-untyped-def]
        start: float = time.perf_counter()
        result = fn(state)
        latency_ms: float = (time.perf_counter() - start) * 1000.0
        logger.log_node(node_name, latency_ms, result)
        return result

    _logged.__name__ = f"{node_name}_logged"
    _logged.__qualname__ = _logged.__name__
    return _logged


def build_graph(
    *,
    llm: LLMEngineAdapter,
    cfg: AppConfig,
    glossary_index: GlossaryIndex | None = None,
    embedder: object | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: object | None = None,
) -> Any:
    """Wire the four nodes into a compiled :class:`StateGraph` and return it.

    Dependencies are injected and bound with ``functools.partial`` so each
    node closure has the signature ``(state) -> state`` that LangGraph
    requires, while still receiving its engines (DIP,
    engineering-principles §1.5). ``glossary_index`` / ``embedder`` /
    ``persist_dir`` default to ``None`` — ``preprocess_node`` then falls back
    to the real SQLite/ChromaDB stores (production); tests pass deterministic
    fakes (testing-verification §3.4).

    ``run_logger`` (task 4.3.1), when supplied, wraps every node so one
    structured JSON line is emitted per node execution to
    ``logs/run_<id>.jsonl``. When ``None`` the pipeline runs unchanged —
    logging is opt-in at the orchestration seam.

    Returns:
        The compiled LangGraph runnable (``.invoke(state)`` runs the pipeline).
    """
    graph: StateGraph = StateGraph(TranslationState)

    def _bind(name: str, fn: _NodeCallable) -> _NodeCallable:
        """Bind a node name to a (possibly logged) callable for add_node."""
        if run_logger is not None:
            return _wrap_with_logging(name, fn, run_logger)
        return fn

    graph.add_node(
        PREPROCESS_NODE,
        _bind(
            PREPROCESS_NODE,
            partial(
                preprocess_node,
                glossary_index=glossary_index,
                embedder=embedder,
                persist_dir=persist_dir,
                cfg=cfg,
            ),
        ),
    )
    graph.add_node(
        WEB_SEARCH_NODE,
        _bind(WEB_SEARCH_NODE, partial(web_search_node, cfg=cfg)),
    )
    graph.add_node(
        TM_LOOKUP_NODE,
        _bind(TM_LOOKUP_NODE, partial(tm_lookup_node, tm=tm, cfg=cfg)),
    )
    graph.add_node(
        TM_BYPASS_NODE,
        _bind(TM_BYPASS_NODE, tm_bypass_node),
    )
    graph.add_node(
        TRANSLATE_NODE,
        _bind(TRANSLATE_NODE, partial(translate_node, llm=llm, cfg=cfg)),
    )
    graph.add_node(
        AUDIT_NODE,
        _bind(AUDIT_NODE, partial(audit_node, llm=llm, cfg=cfg)),
    )
    graph.add_node(
        FINALIZE_NODE,
        _bind(FINALIZE_NODE, partial(finalize_node, cfg=cfg)),
    )

    graph.set_entry_point(PREPROCESS_NODE)
    graph.add_edge(PREPROCESS_NODE, WEB_SEARCH_NODE)
    graph.add_edge(WEB_SEARCH_NODE, TM_LOOKUP_NODE)
    # A >= threshold TM hit bypasses the LLM (tm_bypass -> finalize); a miss
    # falls through to the normal translate/audit path (spec §5.4).
    graph.add_conditional_edges(
        TM_LOOKUP_NODE,
        partial(route_after_tm, threshold=cfg.tm_similarity_threshold),
        {_ROUTE_TM_BYPASS: _ROUTE_TM_BYPASS, _ROUTE_TRANSLATE: _ROUTE_TRANSLATE},
    )
    graph.add_edge(TM_BYPASS_NODE, FINALIZE_NODE)
    graph.add_edge(TRANSLATE_NODE, AUDIT_NODE)

    graph.add_conditional_edges(
        AUDIT_NODE,
        partial(route_audit, max_revisions=cfg.max_revisions),
        {_ROUTE_FINALIZE: _ROUTE_FINALIZE, _ROUTE_TRANSLATE: _ROUTE_TRANSLATE},
    )
    graph.add_edge(FINALIZE_NODE, END)

    return graph.compile()
