"""Human-in-the-loop (HITL) review and correction persistence.

Single responsibility: provide the orchestration seam for human review of the
translator's draft *after* the autonomous translate→audit loop completes and
*before* finalize. The human can approve the draft as-is or edit it; an edited
draft is re-audited, and every human correction is saved to a JSONL file for
future fine-tuning / TM enrichment.

This module is deliberately NOT a LangGraph node. The HITL pause happens at the
CLI / UI orchestration seam (engineering-principles §3.6: the CLI is the only
place concrete adapters are constructed and orchestration decisions are made).
The graph topology is unchanged — ``run_translation`` / ``run_translation_streamed``
run the graph to completion first, then call :func:`human_review` here, then
optionally re-invoke the auditor on the edited draft.

Conforms to the adapter boundary: no engine types are imported here. The
auditor is called via the injected ``llm`` adapter + :func:`audit_node` from
``src.nodes`` (which only sees domain exceptions).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path
from typing import Protocol

from src.config import AppConfig
from src.components.translation_pipeline.nodes import audit_node
from src.components.translation_pipeline.models import TranslationState


class HumanReviewer(Protocol):
    """Interface for a human review callback.

    The CLI implements this with a stdin prompt; the web UI implements it with
    an editable text area + approve/edit buttons. Both return the reviewed
    draft text — identical to the original if approved, or the edited text.
    Returning an empty string is treated as "approve as-is" (no edit).
    """

    def review(self, state: TranslationState) -> str:
        """Present the draft to the human and return the (possibly edited) text.

        Returns the edited draft, or the original draft if the human approves
        without changes.
        """
        ...


def human_review(
    state: TranslationState,
    cfg: AppConfig,
    *,
    llm: object,
    reviewer: HumanReviewer,
    tm: object | None = None,
) -> TranslationState:
    """Run the human review step and re-audit if the draft was edited.

    1. Present the current draft to the human via ``reviewer.review(state)``.
    2. If the human approved without changes → return state unchanged.
    3. If the human edited the draft:
       a. Save the correction to the JSONL feedback file (for fine-tuning).
       b. Insert the (source → edited) pair into the TM (if ``tm`` is supplied)
          so future translations of the same source sentence bypass the LLM.
       c. Re-run the auditor on the edited draft.
       d. If the auditor approves → use the edited draft.
       e. If the auditor revokes → keep the edited draft (best-effort) and
          append a warning. The human is the final authority; the re-audit
          is advisory, not blocking.
    """
    original_draft: str = state.get("draft", "")
    edited: str = reviewer.review(state)

    # No edit (or empty return = approve as-is).
    if not edited.strip() or edited.strip() == original_draft.strip():
        return state

    # Human edited the draft — save the correction for teaching.
    _save_correction(state, cfg, original_draft=original_draft, edited_draft=edited)

    # Insert the human-corrected pair into the TM for immediate reuse.
    # Future translations of the same source sentence will hit the TM and
    # bypass the LLM entirely — no retraining needed.
    if tm is not None:
        _save_to_tm(state, cfg, edited_draft=edited, tm=tm)

    # Re-audit the edited draft (advisory — human is final authority).
    edited_state: TranslationState = {**state, "draft": edited}
    re_audited: TranslationState = audit_node(
        edited_state, llm=llm, cfg=cfg  # type: ignore[arg-type]
    )

    audit: object = re_audited.get("audit")
    is_approve: bool = (
        isinstance(audit, dict) and audit.get("verdict") == "APPROVE"
    )
    if not is_approve:
        warnings: list[str] = list(re_audited.get("warnings", []))
        warnings.append(
            "Human-edited draft was re-audited; auditor found issues but "
            "the human edit is retained (human is final authority)."
        )
        re_audited = {**re_audited, "warnings": warnings}

    return re_audited


def _save_correction(
    state: TranslationState,
    cfg: AppConfig,
    *,
    original_draft: str,
    edited_draft: str,
) -> None:
    """Append a human correction record to the JSONL feedback file.

    The record captures full context for future fine-tuning: source text,
    direction, original (AI) draft, human-edited draft, audit verdict, and
    glossary hits. The file is created if it does not exist; records are
    appended (never overwritten) so the file accumulates a training dataset.
    """
    feedback_dir: Path = Path(cfg.hitl_feedback_dir)
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path: Path = feedback_dir / "human_corrections.jsonl"

    audit: object = state.get("audit")
    verdict: str = "N/A"
    critique: str = ""
    if isinstance(audit, dict):
        verdict = str(audit.get("verdict", "N/A"))
        critique = str(audit.get("critique", ""))

    record: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        "input_text": state.get("input_text", ""),
        "direction": state.get("direction", ""),
        "original_draft": original_draft,
        "edited_draft": edited_draft,
        "audit_verdict": verdict,
        "audit_critique": critique,
        "revision_count": state.get("revision_count", 0),
        "glossary_hits": [
            {
                "source_term": h.get("source_term", ""),
                "target_term": h.get("target_term", ""),
                "law_ref": h.get("law_ref", ""),
            }
            for h in state.get("glossary_hits", [])
        ],
        "model": cfg.llm_model,
    }

    with feedback_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _save_to_tm(
    state: TranslationState,
    cfg: AppConfig,
    *,
    edited_draft: str,
    tm: object,
) -> None:
    """Insert the human-corrected (source → target) pair into the TM.

    Uses :meth:`TranslationMemory.add_parallel` (non-destructive — does not
    clear existing entries). The pair is stored in both directions so the TM
    can serve both AR→EN and EN→AR lookups for this sentence.

    The ``law_slug`` is ``"human_correction"`` and ``article`` is ``""`` to
    distinguish human-sourced entries from corpus-sourced ones.
    """
    source_text: str = state.get("input_text", "")
    direction: str = state.get("direction", "ar-en")
    source_lang: str = direction.split("-")[0]
    target_lang: str = direction.split("-")[1]

    # Insert both directions for bidirectional reuse.
    pairs: list[tuple[str, str, str, str]] = [
        (source_text, edited_draft, source_lang, target_lang),
        (edited_draft, source_text, target_lang, source_lang),
    ]
    # add_parallel is a method on TranslationMemory; it accepts a list of
    # (source, target, source_lang, target_lang) tuples.
    tm.add_parallel(pairs)  # type: ignore[attr-defined]
