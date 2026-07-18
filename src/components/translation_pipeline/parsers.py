"""JSON parsing helpers for the translation pipeline (SRP).

Extracted from ``nodes.py`` so the node functions focus on orchestration.
The ``parse_verdict`` function defensively parses the Auditor Agent's JSON
output per PROMPTS.md §3.3: markdown fences are stripped, a parse failure or
missing/invalid verdict defaults to ``REVISE`` with ``confidence = 0.0``
(forcing another translator pass rather than silently approving).
"""
from __future__ import annotations

import json
import re
from typing import cast

from src.components.translation_pipeline.constants import VERDICT_REVISE
from src.components.translation_pipeline.exceptions import AuditParseError
from src.components.translation_pipeline.models import AuditVerdict, Verdict

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


def parse_verdict(raw: str) -> AuditVerdict:
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
        return _unparseable_verdict()
    if not isinstance(parsed, dict):
        return _unparseable_verdict()

    verdict_raw: object = parsed.get("verdict", VERDICT_REVISE)
    verdict: Verdict = (
        cast(Verdict, verdict_raw)
        if isinstance(verdict_raw, str) and verdict_raw in _VALID_VERDICTS
        else VERDICT_REVISE
    )

    violations_raw: object = parsed.get("violations", [])
    violations: list[str] = (
        [str(v) for v in violations_raw]
        if isinstance(violations_raw, list)
        else []
    )

    confidence_raw: object = parsed.get("confidence", 0.0)
    try:
        confidence: float = float(str(confidence_raw))
    except (TypeError, ValueError):
        confidence = 0.0
    if not 0.0 <= confidence <= 1.0:
        raise AuditParseError(
            f"confidence must be in [0.0, 1.0], got {confidence}"
        )

    critique: str = str(parsed.get("critique", ""))

    return {
        "verdict": verdict,
        "critique": critique,
        "violations": violations,
        "confidence": confidence,
    }


def _unparseable_verdict() -> AuditVerdict:
    """Return the default REVISE verdict for unparseable Auditor output."""
    return {
        "verdict": VERDICT_REVISE,
        "critique": _UNPARSEABLE_CRITIQUE,
        "violations": [],
        "confidence": 0.0,
    }
