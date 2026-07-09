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

import json
import re
from typing import Any

from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.knowledge_sources.glossary import GlossaryIndex, scan_glossary_hits
from src.components.knowledge_sources.legal_search import search_all_sources
from src.components.knowledge_sources.retrieval import retrieve_context_chunks
from src.components.translation_pipeline.models import (
    AuditVerdict as StateAuditVerdict,
)
from src.components.translation_pipeline.models import (
    ContextChunk as StateContextChunk,
)
from src.components.translation_pipeline.models import (
    GlossaryHit as StateGlossaryHit,
)
from src.components.translation_pipeline.models import (
    TmHit as StateTmHit,
)
from src.components.translation_pipeline.models import (
    TranslationState,
    Verdict,
)
from src.components.translation_pipeline.prompts import (
    AUDITOR_SYSTEM_V4,
    AUDITOR_USER_TEMPLATE_V4,
    TRANSLATOR_REVISION_ADDENDUM_V4,
    TRANSLATOR_SYSTEM_V4,
    TRANSLATOR_USER_TEMPLATE_V4,
)
from src.config import AppConfig

# Source/target language labels per direction (closed set, clean-code §1.1).
_DIR_LANGS: dict[str, tuple[str, str]] = {
    "ar-en": ("ar", "en"),
    "en-ar": ("en", "ar"),
}

# Markdown fence pattern (```json ... ``` or ``` ... ```), stripped before
# parsing the Auditor's JSON verdict (PROMPTS.md §3.3 rule 1).
_FENCE_RE: re.Pattern[str] = re.compile(
    r"^\s*```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL
)

_VALID_VERDICTS: frozenset[str] = frozenset({"APPROVE", "REVISE"})

# Synthesized critique when the Auditor output cannot be parsed
# (PROMPTS.md §3.3 rule 2).
_UNPARSEABLE_CRITIQUE: str = (
    "Auditor output unparseable; forcing revision."
)


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
# Direction / prompt-formatting helpers (shared by translate + audit, DRY)
# ---------------------------------------------------------------------------


def _langs(direction: str) -> tuple[str, str]:
    """Resolve ``(source_lang, target_lang)`` from a translation direction."""
    return _DIR_LANGS[direction]


def _augment_query_for_retrieval(
    input_text: str,
    source_lang: str,
    target_lang: str,
    hits: list[StateGlossaryHit],
) -> str:
    """Augment the retrieval query with target-language glossary anchors.

    The RAG corpus is predominantly Arabic (see the corpus build in
    ``src/ingestion.py``), so an English query embeds poorly against it and
    EN→AR retrieval returns weakly-relevant chunks. For EN→AR, the
    glossary-bound Arabic target terms are appended to the query as anchors so
    the Arabic corpus returns chunks the translator can mimic for register and
    phrasing. AR→EN retrieval is already monolingual (Arabic query → Arabic
    corpus) and is left unchanged to avoid regressing the strong direction.
    """
    if source_lang != "en" or target_lang != "ar" or not hits:
        return input_text
    anchors: list[str] = [
        h["target_term"] for h in hits if h.get("target_term")
    ]
    if not anchors:
        return input_text
    return input_text + "\n" + " ".join(anchors)


def _format_glossary_bindings(hits: list[StateGlossaryHit]) -> str:
    """Format glossary hits as the prompt bindings list (PROMPTS.md §2.2).

    One line per hit:
    ``"{source_term}"  ->  "{target_term}"   [Law: {law_ref}, Art: {article_ref}]``
    """
    if not hits:
        return "N/A"
    lines: list[str] = []
    for hit in hits:
        article: str = hit.get("article_ref", "") or ""
        lines.append(
            f'"{hit["source_term"]}"  ->  "{hit["target_term"]}"'
            f'   [Law: {hit["law_ref"]}, Art: {article}]'
        )
    return "\n".join(lines)


def _format_context_chunks(chunks: list[StateContextChunk]) -> str:
    """Format context chunks with provenance headers (PROMPTS.md §2.2)."""
    if not chunks:
        return "N/A"
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(
            f"[Chunk {i} | Law: {chunk['law']} | Article: {chunk['article']}]\n"
            f"{chunk['text']}"
        )
    return "\n\n".join(lines)


def _format_web_search_results(results: list[dict[str, str]]) -> str:
    """Format web search hits for the translator/auditor prompt.

    Each hit is rendered as:
    ``[Source: {source}] {title} — {snippet} ({url})``
    """
    if not results:
        return "N/A"
    lines: list[str] = []
    for i, r in enumerate(results, start=1):
        title: str = r.get("title", "")
        url: str = r.get("url", "")
        snippet: str = r.get("snippet", "")
        source: str = r.get("source", "")
        lines.append(
            f"[{i} | Source: {source}] {title}\n"
            f"  URL: {url}\n"
            f"  Snippet: {snippet}" if snippet else
            f"[{i} | Source: {source}] {title}\n"
            f"  URL: {url}"
        )
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Type-conversion helpers (dataclass -> state TypedDict)
# ---------------------------------------------------------------------------


def _hit_to_state(hit: Any) -> StateGlossaryHit:
    """Project a :class:`glossary.GlossaryHit` into the state TypedDict."""
    return {
        "source_term": hit.source_term,
        "target_term": hit.target_term,
        "law_ref": hit.law_ref,
        "article_ref": hit.article_ref if hit.article_ref is not None else "",
        "note": hit.note if hit.note is not None else "",
        "char_start": hit.char_start,
        "char_end": hit.char_end,
    }


def _chunk_to_state(chunk: Any) -> StateContextChunk:
    """Project a :class:`retrieval.ContextChunk` into the state TypedDict.

    The retrieval adapter reports a cosine ``distance`` (lower = more
    similar); the state stores a similarity ``score`` (higher = more
    similar), so ``score = 1.0 - distance``.
    """
    return {
        "text": chunk.text,
        "law": chunk.law,
        "article": chunk.article,
        "score": 1.0 - float(chunk.distance),
    }


# ---------------------------------------------------------------------------
# 3.2.1 preprocess_node
# ---------------------------------------------------------------------------


def preprocess_node(
    state: TranslationState,
    *,
    glossary_index: GlossaryIndex | None = None,
    embedder: object | None = None,
    persist_dir: str | None = None,
    cfg: AppConfig | None = None,
) -> TranslationState:
    """Normalize input, scan the glossary, retrieve context, populate state.

    Reads: ``input_text``, ``direction``.
    Writes: ``glossary_hits``, ``context_chunks``; appends to ``warnings`` when
    retrieval returns no chunks (PROMPTS.md §4: empty context -> literal
    translation + warning flag).

    The glossary scan is the single source of truth
    (``glossary.scan_glossary_hits``, engineering-principles §2.1.2) and
    retrieval is the single source of truth
    (``retrieval.retrieve_context_chunks``, engineering-principles §2.1.3).
    Both are injected (index / embedder / persist_dir / cfg) for deterministic
    tests; defaults hit the real SQLite/ChromaDB stores.
    """
    _require_fields(state, ("input_text", "direction"))
    input_text: str = state["input_text"].strip()
    source_lang, target_lang = _langs(state["direction"])

    hits: list[StateGlossaryHit] = [
        _hit_to_state(h)
        for h in scan_glossary_hits(input_text, source_lang, index=glossary_index)
    ]

    # For EN→AR, anchor the retrieval query with the glossary-bound Arabic
    # target terms so the predominantly-Arabic corpus returns relevant chunks.
    retrieval_query: str = _augment_query_for_retrieval(
        input_text, source_lang, target_lang, hits,
    )
    chunks: list[StateContextChunk] = [
        _chunk_to_state(c)
        for c in retrieve_context_chunks(
            retrieval_query,
            persist_dir=persist_dir,
            embedder=embedder,  # type: ignore[arg-type]
            cfg=cfg,
        )
    ]

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
    source_lang, target_lang = _langs(state["direction"])
    prior_audit: object = state.get("audit")
    is_revision: bool = (
        prior_audit is not None
        and isinstance(prior_audit, dict)
        and prior_audit.get("verdict") == "REVISE"
    )

    system_prompt: str = (
        _TRANSLATOR_SYSTEM(source_lang, target_lang)
        if not is_revision
        else _TRANSLATOR_SYSTEM(source_lang, target_lang)
        + "\n"
        + _REVISION_ADDENDUM
    )

    prior_draft: str = state["draft"] if is_revision else "N/A"
    critique: str = (
        prior_audit["critique"]  # type: ignore[index]
        if is_revision and prior_audit is not None
        else "N/A"
    )

    user_prompt: str = _TRANSLATOR_USER.format(
        source_lang=source_lang,
        target_lang=target_lang,
        input_text=state["input_text"],
        glossary_bindings=_format_glossary_bindings(state["glossary_hits"]),
        context_chunks=_format_context_chunks(state["context_chunks"]),
        web_search_results=_format_web_search_results(
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


# ---------------------------------------------------------------------------
# 3.2.3 audit_node
# ---------------------------------------------------------------------------


def audit_node(
    state: TranslationState,
    *,
    llm: LLMEngineAdapter,
    cfg: AppConfig,
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
    source_lang, target_lang = _langs(state["direction"])
    user_prompt: str = _AUDITOR_USER.format(
        source_lang=source_lang,
        target_lang=target_lang,
        input_text=state["input_text"],
        draft=state["draft"],
        glossary_bindings=_format_glossary_bindings(state["glossary_hits"]),
        context_chunks=_format_context_chunks(state["context_chunks"]),
        web_search_results=_format_web_search_results(
            state.get("web_search_results", [])
        ),
    )

    raw: str = llm.generate(
        _AUDITOR_SYSTEM,
        user_prompt,
        model=cfg.llm_model,
        temperature=cfg.auditor_temperature,
        max_tokens=cfg.auditor_max_tokens,
        timeout=cfg.llm_timeout,
    )

    verdict: dict[str, object] = _parse_verdict(raw)
    return {**state, "audit": verdict}  # type: ignore[return-value]


def _parse_verdict(raw: str) -> dict[str, object]:
    """Defensively parse the Auditor output into a verdict dict (PROMPTS §3.3).

    1. Strip markdown fences.
    2. ``json.loads``; on failure -> REVISE / confidence 0.0 / unparseable
       critique.
    3. Missing or invalid ``verdict`` -> default REVISE.
    4. Coerce ``violations`` to a list and ``confidence`` to a float.
    """
    stripped: str = _FENCE_RE.sub(r"\1", raw.strip())
    try:
        parsed: object = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return {
            "verdict": "REVISE",
            "critique": _UNPARSEABLE_CRITIQUE,
            "violations": [],
            "confidence": 0.0,
        }
    if not isinstance(parsed, dict):
        return {
            "verdict": "REVISE",
            "critique": _UNPARSEABLE_CRITIQUE,
            "violations": [],
            "confidence": 0.0,
        }

    verdict_raw: object = parsed.get("verdict", "REVISE")
    verdict: Verdict = (
        verdict_raw  # type: ignore[assignment]
        if isinstance(verdict_raw, str) and verdict_raw in _VALID_VERDICTS
        else "REVISE"
    )

    violations_raw: object = parsed.get("violations", [])
    violations: list[str] = (
        [str(v) for v in violations_raw]
        if isinstance(violations_raw, list)
        else []
    )

    confidence_raw: object = parsed.get("confidence", 0.0)
    try:
        confidence: float = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0

    critique: str = str(parsed.get("critique", ""))

    return {
        "verdict": verdict,
        "critique": critique,
        "violations": violations,
        "confidence": confidence,
    }


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
        isinstance(audit, dict) and audit.get("verdict") == "APPROVE"
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
    tm: object | None = None,
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
    hit: StateTmHit | None = tm.lookup(  # type: ignore[attr-defined]
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
        "verdict": "APPROVE",
        "critique": (
            f"Pre-approved: Translation Memory match "
            f"(similarity={hit['similarity']:.4f})."
        ),
        "violations": [],
        "confidence": hit["similarity"],
    }
    return {**state, "draft": hit["target_sentence"], "audit": verdict}


# ---------------------------------------------------------------------------
# Prompt constants — the versioned templates in prompts.py are the single
# source of truth (DRY, engineering-principles §2.1.3). The translator system
# role carries runtime {source_lang}/{target_lang} placeholders, so it is
# formatted per call; the auditor system role has no placeholders.
# ---------------------------------------------------------------------------

_AUDITOR_SYSTEM: str = AUDITOR_SYSTEM_V4
_REVISION_ADDENDUM: str = TRANSLATOR_REVISION_ADDENDUM_V4
_TRANSLATOR_USER: str = TRANSLATOR_USER_TEMPLATE_V4
_AUDITOR_USER: str = AUDITOR_USER_TEMPLATE_V4


def _TRANSLATOR_SYSTEM(source_lang: str, target_lang: str) -> str:
    """Format the translator system role with the runtime language pair."""
    return TRANSLATOR_SYSTEM_V4.format(
        source_lang=source_lang, target_lang=target_lang
    )


# ---------------------------------------------------------------------------
# web_search_node — search Iraqi legal sources for additional context
# ---------------------------------------------------------------------------


def web_search_node(
    state: TranslationState,
    *,
    cfg: AppConfig,
) -> TranslationState:
    """Search Iraqi legal sources and populate ``web_search_results``.

    Reads: ``input_text``.
    Writes: ``web_search_results``.

    When ``cfg.web_search_enabled`` is False, this node is a no-op
    pass-through (returns ``web_search_results: []``). When enabled, it
    searches the Ministry of Justice and National Library for the input
    text keywords and stores the hits in state. The translator and auditor
    prompts read ``web_search_results`` as additional grounding context.

    Network errors are swallowed — the pipeline must not crash on a web
    search failure. A warning is appended if the search returns no results.
    """
    _require_fields(state, ("input_text",))
    if not cfg.web_search_enabled:
        return {**state, "web_search_results": []}

    query: str = state["input_text"].strip()
    if not query:
        return {**state, "web_search_results": []}

    try:
        hits = search_all_sources(
            query, max_results_per_source=cfg.web_search_max_results
        )
    except Exception:
        # Web search must never crash the pipeline.
        hits = []

    results: list[dict[str, str]] = [h.to_dict() for h in hits]

    warnings: list[str] = list(state.get("warnings", []))
    if not results:
        warnings.append(
            "Web search returned no results from Iraqi legal sources."
        )

    return {**state, "web_search_results": results, "warnings": warnings}
