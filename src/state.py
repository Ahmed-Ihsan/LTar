"""LangGraph state schema: the ``TranslationState`` TypedDict and sub-types.

Single responsibility (per ARCHITECTURE.md §4.1): define the typed state
that flows between nodes. Uses ``TypedDict`` (not bare ``dict``) for all
structured dicts that cross function boundaries (clean-code §1.1).
Each node declares which fields it reads/writes in its docstring
(engineering-principles §1.4 ISP).

Implemented in Phase 3 (task 3.1.1).
"""
from __future__ import annotations

from typing import Literal, TypedDict

# Closed string sets exposed as type aliases so nodes, the graph, and tests
# share one definition (DRY, engineering-principles §2.2). ``Literal`` types
# for closed string sets are mandatory (clean-code §1.1).
Direction = Literal["ar-en", "en-ar"]
"""Translation direction: Arabic->English or English->Arabic."""

Verdict = Literal["APPROVE", "REVISE"]
"""Auditor decision: approve the draft or send it back for revision."""


class GlossaryHit(TypedDict):
    """A single glossary term match found in the source text.

    Produced by the ``preprocess`` node via ``glossary.scan_glossary_hits``
    (the single source of truth for scanning, engineering-principles §2.1.2).
    ``char_start`` / ``char_end`` let the translator prompt reference the
    match span precisely (ARCHITECTURE.md §2.1).
    """

    source_term: str
    target_term: str
    law_ref: str
    article_ref: str
    note: str
    char_start: int
    char_end: int


class ContextChunk(TypedDict):
    """A retrieved corpus chunk used to ground the translation.

    Produced by the ``preprocess`` node via ``retrieval.retrieve_context_chunks``
    (the single source of truth for vector queries, engineering-principles
    §2.1.3). ``score`` is the similarity score from the vector store.
    """

    text: str
    law: str
    article: str
    score: float


class AuditVerdict(TypedDict):
    """The Auditor Agent's structured verdict on a draft.

    Emitted by the ``audit`` node after defensively parsing the Auditor's
    JSON output (PROMPTS.md §3.3). Routing is purely ``verdict``-driven;
    ``confidence`` is logged but does not affect routing.
    """

    verdict: Verdict
    critique: str
    violations: list[str]
    confidence: float


class TmHit(TypedDict):
    """A Translation Memory match found in the source text.

    Produced by the ``tm_lookup`` node. When a sentence has ≥ 98% similarity
    to a stored bilingual pair, the stored target translation is used directly
    (bypassing the LLM).
    """

    source_sentence: str
    target_sentence: str
    similarity: float
    char_start: int
    char_end: int


class TranslationState(TypedDict):
    """The typed state that flows between LangGraph nodes.

    Field ownership (ARCHITECTURE.md §4.4) — no node may mutate a field it
    does not own, enforced by unit tests:

    - ``preprocess`` writes ``glossary_hits`` and ``context_chunks`` (only).
    - ``tm_lookup`` reads ``input_text`` / ``direction``; writes ``tm_hits``.
    - ``tm_bypass`` reads ``tm_hits``; writes ``draft`` and a pre-approved
      ``audit`` verdict (spec §5.4: a >= threshold TM match bypasses the LLM).
    - ``translate`` reads ``glossary_hits`` / ``context_chunks`` / ``direction``
      / ``input_text``; writes ``draft``; increments ``revision_count`` only
      on re-entry (first pass sets it to 0).
    - ``audit`` reads ``draft`` / ``glossary_hits`` / ``input_text``; writes
      ``audit``.
    - ``finalize`` reads ``draft`` / ``audit``; writes ``final_output`` and
      appends to ``warnings``.
    """

    input_text: str
    direction: Direction
    glossary_hits: list[GlossaryHit]
    context_chunks: list[ContextChunk]
    tm_hits: list[TmHit]
    draft: str
    audit: AuditVerdict | None
    revision_count: int
    final_output: str | None
    warnings: list[str]
