"""TM routing decision — pure function, no LLM, no side effects.

Single responsibility: decide whether a sentence should use a TM hit
(bypass the LLM) or go to the LLM. The decision is threshold-gated:
a hit with similarity >= threshold uses the TM; anything below goes to
the LLM. This is the conservative gate that prevents silent legal errors
from near-matches (spec §5.4 / §7.2).
"""
from __future__ import annotations

from src.state import TmHit


def route_tm(hit: TmHit | None, *, threshold: float) -> bool:
    """Return True if the sentence should use the TM (bypass the LLM).

    A None hit (no TM match at all) always returns False. A hit with
    similarity >= threshold returns True; below the threshold returns
    False. The comparison is >= so a hit exactly at the threshold is
    accepted (spec §7.2: "≥ 98% similarity").
    """
    if hit is None:
        return False
    return hit["similarity"] >= threshold
