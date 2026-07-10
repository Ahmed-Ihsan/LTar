"""Named constants for the translation pipeline (clean-code §3.3).

Replaces magic strings scattered across modules with named constants so the
closed sets (directions, languages, verdicts, placeholders) have a single
source of truth (DRY, engineering-principles §2.2).
"""
from __future__ import annotations

from typing import Literal

DIRECTION_AR_EN: str = "ar-en"
"""Translation direction: Arabic → English."""

DIRECTION_EN_AR: str = "en-ar"
"""Translation direction: English → Arabic."""

LANG_AR: str = "ar"
"""Source/target language label: Arabic."""

LANG_EN: str = "en"
"""Source/target language label: English."""

VERDICT_APPROVE: Literal["APPROVE"] = "APPROVE"
"""Auditor verdict: approve the draft."""

VERDICT_REVISE: Literal["REVISE"] = "REVISE"
"""Auditor verdict: send the draft back for revision."""

NA_PLACEHOLDER: str = "N/A"
"""Placeholder for empty/missing prompt sections (PROMPTS.md §2.2)."""
