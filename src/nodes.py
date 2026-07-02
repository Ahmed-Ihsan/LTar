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

from src.config import AppConfig
from src.glossary import GlossaryIndex, scan_glossary_hits
from src.llm import LLMEngineAdapter
from src.prompts import (
    AUDITOR_SYSTEM_V1,
    AUDITOR_USER_TEMPLATE_V1,
    TRANSLATOR_REVISION_ADDENDUM_V1,
    TRANSLATOR_SYSTEM_V1,
    TRANSLATOR_USER_TEMPLATE_V1,
)
from src.retrieval import retrieve_context_chunks
from src.state import (
    ContextChunk as StateContextChunk,
)
from src.state import (
    GlossaryHit as StateGlossaryHit,
)
from src.state import (
    TranslationState,
    Verdict,
)

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
    source_lang, _target_lang = _langs(state["direction"])

    hits: list[StateGlossaryHit] = [
        _hit_to_state(h)
        for h in scan_glossary_hits(input_text, source_lang, index=glossary_index)
    ]

    chunks: list[StateContextChunk] = [
        _chunk_to_state(c)
        for c in retrieve_context_chunks(
            input_text,
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
# Prompt constants — the versioned templates in prompts.py are the single
# source of truth (DRY, engineering-principles §2.1.3). The translator system
# role carries runtime {source_lang}/{target_lang} placeholders, so it is
# formatted per call; the auditor system role has no placeholders.
# ---------------------------------------------------------------------------

_AUDITOR_SYSTEM: str = AUDITOR_SYSTEM_V1
_REVISION_ADDENDUM: str = TRANSLATOR_REVISION_ADDENDUM_V1
_TRANSLATOR_USER: str = TRANSLATOR_USER_TEMPLATE_V1
_AUDITOR_USER: str = AUDITOR_USER_TEMPLATE_V1


def _TRANSLATOR_SYSTEM(source_lang: str, target_lang: str) -> str:
    """Format the translator system role with the runtime language pair."""
    return TRANSLATOR_SYSTEM_V1.format(
        source_lang=source_lang, target_lang=target_lang
    )
