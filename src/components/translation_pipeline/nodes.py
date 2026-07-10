"""LangGraph node functions: preprocess, translate, audit, finalize.

Single responsibility (per ARCHITECTURE.md): implement the node functions
that mutate ``TranslationState``. The Translator and Auditor agents are
separate nodes with separate prompts and separate evaluation criteria
(engineering-principles §1.1) — they MUST NOT be merged. Nodes receive their
LLM engine via dependency injection (the ``LLMEngineAdapter`` protocol,
engineering-principles §1.5 / §3.1), never by importing the concrete Ollama
client directly (DIP; adapter boundary, engineering-principles §3.7 rule 4).

Field ownership (ARCHITECTURE.md §4.4) — each node reads/writes only the
fields declared in its docstring; this is enforced by unit tests:
- ``preprocess`` writes ``glossary_hits`` / ``context_chunks`` (and appends a
  warning on empty retrieval).
- ``translate`` reads ``glossary_hits`` / ``context_chunks`` / ``direction`` /
  ``input_text`` (and ``draft`` / ``audit`` on a revision pass); writes
  ``draft``; sets ``revision_count`` to 0 on the first pass and increments it
  on each re-entry.
- ``audit`` reads ``draft`` / ``glossary_hits`` / ``input_text``; writes
  ``audit``.
- ``finalize`` reads ``draft`` / ``audit`` / ``revision_count``; writes
  ``final_output`` and appends to ``warnings``.

Implemented in Phase 3 (tasks 3.2.x).
"""
from __future__ import annotations

from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.knowledge_sources.tm import TranslationMemory
from src.components.translation_pipeline.constants import (
    NA_PLACEHOLDER,
    VERDICT_APPROVE,
    VERDICT_REVISE,
)
from src.components.translation_pipeline.formatters import (
    augment_query_for_retrieval,
    format_context_chunks,
    format_glossary_bindings,
    format_web_search_results,
    langs,
)
from src.components.translation_pipeline.models import (
    AuditVerdict as StateAuditVerdict,
)
from src.components.translation_pipeline.models import (
    TmHit as StateTmHit,
)
from src.components.translation_pipeline.models import TranslationState
from src.components.translation_pipeline.parsers import parse_verdict
from src.components.translation_pipeline.prompts import (
    DEFAULT_PROMPT_VERSION,
    PromptVersion,
)
from src.components.translation_pipeline.protocols import (
    ContextRetriever,
    GlossaryScanner,
    WebSearcher,
)
from src.config import AppConfig


def _require_fields(state: TranslationState, fields: tuple[str, ...]) -> None:
    """Assert every name in ``fields`` is present in ``state`` (ARCHITECTURE
    §4.4 state-mutation ownership).

    Each node declares the fields it reads; this guard turns an accidental
    omission (a node called with an incompletely-initialised state) into a
    loud ``AssertionError`` at the boundary instead of a downstream
    ``KeyError`` deep inside the node. Presence is checked by key, not by
    truthiness — an empty ``draft`` or ``None`` ``audit`` is a valid value
    the node logic handles explicitly.
    """
    missing: list[str] = [f for f in fields if f not in state]
    assert not missing, (
        f"state is missing required fields for this node: {missing}"
    )


# ---------------------------------------------------------------------------
# 3.2.1 preprocess_node
# ---------------------------------------------------------------------------


def preprocess_node(
    state: TranslationState,
    *,
    scanner: GlossaryScanner,
    retriever: ContextRetriever,
) -> TranslationState:
    """Normalize input, scan the glossary, retrieve context, populate state.

    Reads: ``input_text``, ``direction``.
    Writes: ``glossary_hits``, ``context_chunks``; appends to ``warnings`` when
    retrieval returns no chunks (PROMPTS.md §4: empty context -> literal
    translation + warning flag).

    The glossary scanner and context retriever are injected as protocol-typed
    dependencies (DIP, engineering-principles §1.5). ``graph.py:build_graph``
    creates the concrete adapter instances and binds them via
    ``functools.partial``; tests pass deterministic fakes.
    """
    _require_fields(state, ("input_text", "direction"))
    input_text: str = state["input_text"].strip()
    source_lang, target_lang = langs(state["direction"])

    hits = scanner.scan(input_text, source_lang)

    # For EN→AR, anchor the retrieval query with the glossary-bound Arabic
    # target terms so the predominantly-Arabic corpus returns relevant chunks.
    retrieval_query: str = augment_query_for_retrieval(
        input_text, source_lang, target_lang, hits,
    )
    chunks = retriever.retrieve(retrieval_query, 0)

    warnings: list[str] = list(state["warnings"])
    if not chunks:
        warnings.append(
            "Context retrieval returned no chunks; translation will be "
            "ungrounded (translating literally per system rule 4)."
        )

    return {
        **state,
        "input_text": input_text,
        "glossary_hits": hits,
        "context_chunks": chunks,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 3.2.2 translate_node
# ---------------------------------------------------------------------------


def translate_node(
    state: TranslationState,
    *,
    llm: LLMEngineAdapter,
    cfg: AppConfig,
    prompts: PromptVersion = DEFAULT_PROMPT_VERSION,
) -> TranslationState:
    """Build the translator prompt, call the LLM, write ``draft``.

    Reads: ``glossary_hits``, ``context_chunks``, ``direction``,
    ``input_text``; on a revision pass also reads ``draft`` (prior) and
    ``audit`` (critique).
    Writes: ``draft``; sets ``revision_count`` to 0 on the first pass and
    increments it on each re-entry (ARCHITECTURE.md §4.4).

    A revision pass is detected by a prior ``audit`` verdict of ``REVISE``;
    the revision addendum (PROMPTS.md §2.3) is then appended to the system
    role and the prior draft + critique are injected into the user turn.
    ``LLMRuntimeError`` subclasses from the adapter propagate unchanged
    (clean-code §3.2: nodes never retry).
    """
    _require_fields(
        state, ("input_text", "direction", "glossary_hits", "context_chunks")
    )
    source_lang, target_lang = langs(state["direction"])
    is_revision, prior_draft, critique = _detect_revision(state)

    system_prompt: str = _build_translator_system(
        prompts, source_lang, target_lang, is_revision
    )
    user_prompt: str = prompts.translator_user_template.format(
        source_lang=source_lang,
        target_lang=target_lang,
        input_text=state["input_text"],
        glossary_bindings=format_glossary_bindings(state["glossary_hits"]),
        context_chunks=format_context_chunks(state["context_chunks"]),
        web_search_results=format_web_search_results(
            state.get("web_search_results", [])
        ),
        prior_draft=prior_draft,
        critique=critique,
    )

    draft: str = llm.generate(
        system_prompt,
        user_prompt,
        model=cfg.llm_model,
        temperature=cfg.translator_temperature,
        max_tokens=cfg.translator_max_tokens,
        timeout=cfg.llm_timeout,
    ).strip()

    revision_count: int = (
        state["revision_count"] + 1 if is_revision else 0
    )

    return {
        **state,
        "draft": draft,
        "revision_count": revision_count,
    }


def _detect_revision(
    state: TranslationState,
) -> tuple[bool, str, str]:
    """Check if this is a revision pass and extract prior draft / critique.

    Returns ``(is_revision, prior_draft, critique)``. On a first pass,
    ``prior_draft`` and ``critique`` are ``NA_PLACEHOLDER``.
    """
    prior_audit: object = state.get("audit")
    is_revision: bool = (
        prior_audit is not None
        and isinstance(prior_audit, dict)
        and prior_audit.get("verdict") == VERDICT_REVISE
    )
    prior_draft: str = state["draft"] if is_revision else NA_PLACEHOLDER
    critique: str = NA_PLACEHOLDER
    if is_revision and isinstance(prior_audit, dict):
        critique = str(prior_audit.get("critique", NA_PLACEHOLDER))
    return is_revision, prior_draft, critique


def _build_translator_system(
    prompts: PromptVersion,
    source_lang: str,
    target_lang: str,
    is_revision: bool,
) -> str:
    """Format the translator system role, appending the revision addendum if needed."""
    system: str = prompts.translator_system.format(
        source_lang=source_lang, target_lang=target_lang
    )
    if not is_revision:
        return system
    return system + "\n" + prompts.translator_revision_addendum


# ---------------------------------------------------------------------------
# 3.2.3 audit_node
# ---------------------------------------------------------------------------


def audit_node(
    state: TranslationState,
    *,
    llm: LLMEngineAdapter,
    cfg: AppConfig,
    prompts: PromptVersion = DEFAULT_PROMPT_VERSION,
) -> TranslationState:
    """Build the auditor prompt, call the LLM, write ``audit``.

    Reads: ``draft``, ``glossary_hits``, ``input_text``, ``direction``,
    ``context_chunks``.
    Writes: ``audit``.

    The verdict JSON is parsed defensively per PROMPTS.md §3.3: markdown fences
    are stripped, a parse failure or missing/invalid verdict defaults to
    ``REVISE`` with ``confidence = 0.0`` (forcing another translator pass
    rather than silently approving). ``LLMRuntimeError`` subclasses from the
    adapter propagate unchanged (clean-code §3.2: nodes never retry).
    """
    _require_fields(
        state,
        ("input_text", "direction", "draft", "glossary_hits", "context_chunks"),
    )
    source_lang, target_lang = langs(state["direction"])
    user_prompt: str = prompts.auditor_user_template.format(
        source_lang=source_lang,
        target_lang=target_lang,
        input_text=state["input_text"],
        draft=state["draft"],
        glossary_bindings=format_glossary_bindings(state["glossary_hits"]),
        context_chunks=format_context_chunks(state["context_chunks"]),
        web_search_results=format_web_search_results(
            state.get("web_search_results", [])
        ),
    )

    raw: str = llm.generate(
        prompts.auditor_system,
        user_prompt,
        model=cfg.llm_model,
        temperature=cfg.auditor_temperature,
        max_tokens=cfg.auditor_max_tokens,
        timeout=cfg.llm_timeout,
    )

    verdict: StateAuditVerdict = parse_verdict(raw)
    return {**state, "audit": verdict}


# ---------------------------------------------------------------------------
# 3.2.4 finalize_node
# ---------------------------------------------------------------------------


def finalize_node(
    state: TranslationState,
    *,
    cfg: AppConfig,
) -> TranslationState:
    """Set ``final_output`` and append terminal warnings.

    Reads: ``draft``, ``audit``, ``revision_count``.
    Writes: ``final_output``; appends to ``warnings``.

    On ``APPROVE`` the final output is the approved draft. On ``REVISE`` at the
    revision cap (``revision_count >= max_revisions``) the best-effort draft is
    emitted and a max-revision warning is appended (ARCHITECTURE.md §2.5).
    """
    _require_fields(state, ("draft", "audit", "revision_count"))
    audit: object = state.get("audit")
    is_approve: bool = (
        isinstance(audit, dict) and audit.get("verdict") == VERDICT_APPROVE
    )

    warnings: list[str] = list(state["warnings"])
    if not is_approve and state["revision_count"] >= cfg.max_revisions:
        warnings.append(
            "Max revisions reached; emitting best-effort draft."
        )

    return {
        **state,
        "final_output": state["draft"],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# tm_lookup_node (TM layer — spec §5)
# ---------------------------------------------------------------------------


def tm_lookup_node(
    state: TranslationState,
    *,
    tm: TranslationMemory | None = None,
    cfg: AppConfig,
) -> TranslationState:
    """Look up the input text in the Translation Memory; populate ``tm_hits``.

    Reads: ``input_text``, ``direction``.
    Writes: ``tm_hits``.

    When ``tm`` is ``None`` (TM disabled), ``tm_hits`` is set to an empty
    list and the node is a no-op pass-through. When the TM is enabled, the
    full input text is looked up; a hit at or above the configured
    threshold populates ``tm_hits`` with the stored target translation.
    """
    _require_fields(state, ("input_text", "direction"))
    if tm is None:
        return {**state, "tm_hits": []}

    input_text: str = state["input_text"].strip()
    hit: StateTmHit | None = tm.lookup(
        input_text, state["direction"]
    )
    if hit is None:
        return {**state, "tm_hits": []}

    return {**state, "tm_hits": [hit]}


# ---------------------------------------------------------------------------
# tm_bypass_node (TM layer — spec §5.4: pre-approved TM output)
# ---------------------------------------------------------------------------


def tm_bypass_node(state: TranslationState) -> TranslationState:
    """Emit a Translation Memory hit directly, bypassing the LLM (spec §5.4).

    Reads: ``tm_hits``.
    Writes: ``draft`` (the stored target translation) and a synthetic
    ``APPROVE`` ``audit`` verdict.

    Reached only via the ``route_after_tm`` conditional edge, when the first
    ``tm_hits`` entry is at or above the similarity threshold. Per spec §5.4 a
    TM match is *pre-approved*: it bypasses both the Translator and the
    Auditor. Writing a synthetic APPROVE verdict keeps ``finalize_node``'s
    contract satisfied (it reads ``audit``) and records provenance — the
    ``confidence`` carries the match similarity so the trace is auditable.
    """
    _require_fields(state, ("tm_hits",))
    hit: StateTmHit = state["tm_hits"][0]
    verdict: StateAuditVerdict = {
        "verdict": VERDICT_APPROVE,
        "critique": (
            f"Pre-approved: Translation Memory match "
            f"(similarity={hit['similarity']:.4f})."
        ),
        "violations": [],
        "confidence": hit["similarity"],
    }
    return {**state, "draft": hit["target_sentence"], "audit": verdict}


# ---------------------------------------------------------------------------
# web_search_node — search Iraqi legal sources for additional context
# ---------------------------------------------------------------------------


def web_search_node(
    state: TranslationState,
    *,
    cfg: AppConfig,
    searcher: WebSearcher | None = None,
) -> TranslationState:
    """Search Iraqi legal sources and populate ``web_search_results``.

    Reads: ``input_text``.
    Writes: ``web_search_results``.

    When ``searcher`` is ``None`` (web search disabled), this node is a no-op
    pass-through (returns ``web_search_results: []``). When a searcher is
    provided, it searches Iraqi legal sources for the input text keywords and
    stores the hits in state. The translator and auditor prompts read
    ``web_search_results`` as additional grounding context.

    Network errors are swallowed — the pipeline must not crash on a web
    search failure. A warning is appended if the search returns no results.
    """
    _require_fields(state, ("input_text",))
    if searcher is None:
        return {**state, "web_search_results": []}

    query: str = state["input_text"].strip()
    if not query:
        return {**state, "web_search_results": []}

    try:
        results = searcher.search(query)
    except Exception:
        # Web search must never crash the pipeline.
        results = []

    warnings: list[str] = list(state.get("warnings", []))
    if not results:
        warnings.append(
            "Web search returned no results from Iraqi legal sources."
        )

    return {**state, "web_search_results": results, "warnings": warnings}
