"""Type-conversion helpers for the translation pipeline (SRP).

Extracted from ``nodes.py`` so the node functions focus on orchestration.
These helpers project dataclass instances from the knowledge layer
(``glossary.GlossaryHit``, ``retrieval.ContextChunk``) into the state
TypedDicts (``StateGlossaryHit``, ``StateContextChunk``) that flow through
the LangGraph state machine.
"""
from __future__ import annotations

from typing import Any

from src.components.translation_pipeline.models import (
    ContextChunk as StateContextChunk,
)
from src.components.translation_pipeline.models import (
    GlossaryHit as StateGlossaryHit,
)


def hit_to_state(hit: Any) -> StateGlossaryHit:
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


def chunk_to_state(chunk: Any) -> StateContextChunk:
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
