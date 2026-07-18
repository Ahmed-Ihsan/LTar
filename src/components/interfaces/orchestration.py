"""Translation orchestration seam between the CLI/UI and the LangGraph pipeline.

Extracted from ``cli.py`` (engineering-principles §1.1 single-responsibility).
This module owns the pure orchestration logic: building the graph with
injected adapters, running a translation (synchronous or streamed), and
rendering provenance / audit-trace output. The CLI and UI modules are thin
wrappers over these functions (testing-verification §3.4).
"""
from __future__ import annotations

import enum
import json
import logging
from pathlib import Path
from typing import Any, TypedDict, cast

import typer
from pydantic import ValidationError

from src.components.infrastructure.embeddings import EmbeddingAdapter
from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.infrastructure.run_logging import RunLogger
from src.components.interfaces.hitl import HumanReviewer, human_review
from src.components.interfaces.models import UiTranslationResult
from src.components.knowledge_sources.glossary import GlossaryIndex
from src.components.knowledge_sources.tm import TranslationMemory
from src.components.translation_pipeline.graph import build_graph
from src.components.translation_pipeline.models import TranslationState
from src.config import AppConfig
from src.utils.jsonl_schema import BatchRecord
from src.utils.paths import validate_path_in_root

logger = logging.getLogger(__name__)


class Direction(enum.Enum):
    """Translation direction (closed set, clean-code §1.1)."""

    ar_en = "ar-en"
    en_ar = "en-ar"


def _initial_state(input_text: str, direction: str) -> TranslationState:
    """Build the minimal LangGraph input state from caller-supplied fields."""
    return {
        "input_text": input_text,
        "direction": cast(Any, direction),
        "glossary_hits": [],
        "context_chunks": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
        "tm_hits": [],
        "web_search_results": [],
    }


# ---------------------------------------------------------------------------
# 4.2.0 Human-in-the-loop (HITL) — CLI stdin reviewer
# ---------------------------------------------------------------------------


class StdinHumanReviewer:
    """CLI human reviewer: prints the draft and reads an edit from stdin.

    Implements :class:`src.hitl.HumanReviewer`. The human can:
    - Press Enter to approve the draft as-is (no edit).
    - Type replacement text, then Enter to submit an edited draft.

    For multi-line edits, the human types ``<<<`` to start a multi-line block
    and ``>>>`` to end it (rare for legal sentences, which are typically one
    paragraph).
    """

    def review(self, state: TranslationState) -> str:
        draft: str = state.get("draft", "")
        typer.secho("\n--- Human Review (HITL) ---", fg=typer.colors.CYAN)
        typer.secho(f"Source: {state.get('input_text', '')}", fg=typer.colors.WHITE)
        typer.secho(f"Draft:  {draft}", fg=typer.colors.YELLOW)
        typer.echo(
            "\nApprove as-is: press Enter.\n"
            "Edit: type the replacement text and press Enter.\n"
            "Multi-line: start with <<< and end with >>>."
        )
        first: str = input("> ")
        if not first.strip():
            return draft  # approve as-is
        if first.strip() == "<<<":
            lines: list[str] = []
            while True:
                line: str = input()
                if line.strip() == ">>>":
                    break
                lines.append(line)
            return "\n".join(lines)
        return first


def run_translation(
    input_text: str,
    direction: str,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: EmbeddingAdapter,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: TranslationMemory | None = None,
    reviewer: HumanReviewer | None = None,
) -> TranslationState:
    """Build the graph with the given adapters and run one translation.

    This is the orchestration seam between the CLI and the LangGraph pipeline.
    The CLI constructs concrete adapters (engineering-principles §3.6) and
    calls this function; tests inject deterministic mocks
    (testing-verification §3.4). Returns the final ``TranslationState``.

    ``run_logger`` (task 4.3.1), when supplied, emits one structured JSON line
    per node execution to ``logs/run_<id>.jsonl``; when ``None`` the pipeline
    runs unchanged.

    ``tm`` (task 7), when supplied, is bound into the ``tm_lookup`` node so
    sentences with a ≥ threshold TM match bypass the LLM; when ``None`` the
    ``tm_lookup`` node is a no-op pass-through.

    ``reviewer`` (HITL), when supplied AND ``cfg.hitl_enabled`` is True, pauses
    after the autonomous translate→audit loop for human review. The human can
    approve the draft or edit it; edits are re-audited and saved to the JSONL
    feedback file for future fine-tuning. When ``None`` or ``hitl_enabled`` is
    False, the pipeline runs fully autonomous (default).
    """
    state: TranslationState = _initial_state(input_text, direction)
    graph = build_graph(
        llm=llm,
        cfg=cfg,
        glossary_index=glossary_index,
        embedder=embedder,
        persist_dir=persist_dir,
        run_logger=run_logger,
        tm=tm,
    )
    result: TranslationState = graph.invoke(state)

    # HITL: human reviews the draft after the autonomous loop, before finalize
    # emits final_output. The graph already ran finalize, so we re-run
    # finalize on the post-review state if the human edited the draft.
    if reviewer is not None and cfg.hitl_enabled:
        reviewed: TranslationState = human_review(
            result, cfg, llm=llm, reviewer=reviewer, tm=tm
        )
        if reviewed is not result:
            from src.components.translation_pipeline.nodes import finalize_node

            reviewed = finalize_node(reviewed, cfg=cfg)
            return reviewed

    return result


# ---------------------------------------------------------------------------
# 4.2.1 / 4.2.2 streamed orchestration — captures the full revision history
# ---------------------------------------------------------------------------

# A single (draft, verdict) pair captured from one translate->audit pass. The
# audit trace (task 4.2.2) shows the full revision history, but the
# ``TranslationState`` only retains the latest ``draft`` / ``audit`` (they are
# overwritten each revision pass). Rather than mutating the state schema
# (engineering-principles §1.2 OCP: existing code is closed for modification),
# the history is captured here by streaming per-node state updates from
# LangGraph — a pure orchestration concern owned by the CLI seam.
class RevisionStep(TypedDict):
    """One revision pass: the draft produced and the auditor's verdict on it."""

    draft: str
    verdict: str
    critique: str
    violations: list[str]
    confidence: float


def _step_from_audit(draft: str, audit: object) -> RevisionStep:
    """Project an auditor verdict dict into a :class:`RevisionStep`."""
    if isinstance(audit, dict):
        return {
            "draft": draft,
            "verdict": str(audit.get("verdict", "N/A")),
            "critique": str(audit.get("critique", "")),
            "violations": list(audit.get("violations", [])),
            "confidence": float(audit.get("confidence", 0.0)),
        }
    return {
        "draft": draft,
        "verdict": "N/A",
        "critique": "",
        "violations": [],
        "confidence": 0.0,
    }


def run_translation_streamed(
    input_text: str,
    direction: str,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: EmbeddingAdapter,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: TranslationMemory | None = None,
    reviewer: HumanReviewer | None = None,
) -> tuple[TranslationState, list[RevisionStep]]:
    """Run one translation, streaming per-node updates to capture revisions.

    Like :func:`run_translation` but uses ``graph.stream(stream_mode="updates")``
    so each ``translate`` node's draft and each ``auditor`` node's verdict is
    captured in order. Returns ``(final_state, revision_history)`` where the
    history holds one :class:`RevisionStep` per translate->audit pass — the
    full revision history required by the Audit Trace tab (task 4.2.2).

    The final state is reconstructed by merging the per-node update dicts
    (each node returns ``{**state, ...}``, so sequential merge reproduces the
    final state regardless of whether LangGraph emits full or partial diffs).

    ``reviewer`` (HITL), when supplied AND ``cfg.hitl_enabled`` is True, pauses
    after the autonomous loop for human review. See :func:`run_translation`.
    """
    coordinator = _HITLStreamCoordinator(
        cfg=cfg,
        llm=llm,
        embedder=embedder,
        glossary_index=glossary_index,
        persist_dir=persist_dir,
        run_logger=run_logger,
        tm=tm,
        reviewer=reviewer,
    )
    return coordinator.run(input_text, direction)


class _HITLStreamCoordinator:
    """Encapsulates the streamed graph loop + HITL review (Change 5 task 7.1).

    Extracted from :func:`run_translation_streamed` to keep the orchestration
    logic testable and isolated. The coordinator:
    1. Builds the LangGraph with injected adapters.
    2. Streams per-node updates, capturing revision history (translate→audit).
    3. Optionally pauses for human review (HITL) after the autonomous loop.
    """

    def __init__(
        self,
        *,
        cfg: AppConfig,
        llm: LLMEngineAdapter,
        embedder: EmbeddingAdapter,
        glossary_index: GlossaryIndex | None = None,
        persist_dir: str | None = None,
        run_logger: RunLogger | None = None,
        tm: TranslationMemory | None = None,
        reviewer: HumanReviewer | None = None,
    ) -> None:
        self._cfg = cfg
        self._llm = llm
        self._embedder = embedder
        self._glossary_index = glossary_index
        self._persist_dir = persist_dir
        self._run_logger = run_logger
        self._tm = tm
        self._reviewer = reviewer

    def run(
        self, input_text: str, direction: str
    ) -> tuple[TranslationState, list[RevisionStep]]:
        """Execute the streamed translation + optional HITL review."""
        from src.components.translation_pipeline.graph import AUDIT_NODE, TRANSLATE_NODE

        state: TranslationState = _initial_state(input_text, direction)
        graph = build_graph(
            llm=self._llm,
            cfg=self._cfg,
            glossary_index=self._glossary_index,
            embedder=self._embedder,
            persist_dir=self._persist_dir,
            run_logger=self._run_logger,
            tm=self._tm,
        )

        history: list[RevisionStep] = []
        merged: TranslationState = state
        pending_draft: str | None = None
        for chunk in graph.stream(state, stream_mode="updates"):
            for node_name, diff in chunk.items():
                if not isinstance(diff, dict):
                    continue
                merged = {**merged, **diff}
                if node_name == TRANSLATE_NODE and "draft" in diff:
                    pending_draft = str(diff["draft"])
                elif node_name == AUDIT_NODE and "audit" in diff:
                    history.append(
                        _step_from_audit(pending_draft or "", diff["audit"])
                    )
                    pending_draft = None

        # HITL: human reviews the draft after the autonomous loop.
        if self._reviewer is not None and self._cfg.hitl_enabled:
            reviewed: TranslationState = human_review(
                merged, self._cfg, llm=self._llm, reviewer=self._reviewer, tm=self._tm
            )
            if reviewed is not merged:
                from src.components.translation_pipeline.nodes import finalize_node

                reviewed = finalize_node(reviewed, cfg=self._cfg)
                return reviewed, history

        return merged, history


def _render_provenance(state: TranslationState) -> str:
    """Render the provenance block from the final translation state.

    Includes: glossary terms applied, source chunks cited, audit verdict,
    revision count, and any warnings. Pure function — no I/O.
    """
    lines: list[str] = ["--- Provenance ---"]

    # Glossary terms applied
    hits: list[Any] = state.get("glossary_hits", [])
    lines.append(f"Glossary terms applied ({len(hits)}):")
    if hits:
        for hit in hits:
            article: str = hit.get("article_ref", "") or ""
            lines.append(
                f'  - "{hit["source_term"]}" -> "{hit["target_term"]}"'
                f'   [Law: {hit["law_ref"]}, Art: {article}]'
            )
    else:
        lines.append("  (none)")

    # Source chunks cited
    chunks: list[Any] = state.get("context_chunks", [])
    lines.append(f"Source chunks cited ({len(chunks)}):")
    if chunks:
        for i, chunk in enumerate(chunks, start=1):
            score: float = float(chunk.get("score", 0.0))
            lines.append(
                f"  - [{i}] Law: {chunk['law']}, Article: {chunk['article']}"
                f" (score: {score:.2f})"
            )
    else:
        lines.append("  (none)")

    # Audit verdict + revision count
    audit: object = state.get("audit")
    verdict: str = "N/A"
    confidence: float = 0.0
    if isinstance(audit, dict):
        verdict = str(audit.get("verdict", "N/A"))
        try:
            confidence = float(audit.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
    revision_count: int = int(state.get("revision_count", 0))
    lines.append(
        f"Audit verdict: {verdict} (confidence: {confidence:.2f}, "
        f"revisions: {revision_count})"
    )

    # Warnings
    warnings: list[str] = list(state.get("warnings", []))
    if warnings:
        lines.append("Warnings:")
        for w in warnings:
            lines.append(f"  - {w}")
    else:
        lines.append("Warnings: none")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4.2.1 / 4.2.2 Gradio UI — pure Markdown formatters (no Gradio import)
# ---------------------------------------------------------------------------


def _provenance_markdown(state: TranslationState) -> str:
    """Render the provenance block as Markdown for the UI output panel.

    Mirrors :func:`_render_provenance` but in Markdown so it renders in the
    collapsible Gradio ``Accordion``. Pure function — no I/O.

    Uses ``## `` sub-headers so the JS ``renderProvenance`` function can split
    on ``^## `` and create collapsible sections per block.
    """
    lines: list[str] = []

    hits: list[Any] = state.get("glossary_hits", [])
    lines.append(f"## Glossary terms applied ({len(hits)})")
    if hits:
        for hit in hits:
            article: str = hit.get("article_ref", "") or ""
            lines.append(
                f'- `{hit["source_term"]}` → `{hit["target_term"]}`'
                f"  — Law: {hit['law_ref']}, Art: {article}"
            )
    else:
        lines.append("- (none)")

    chunks: list[Any] = state.get("context_chunks", [])
    lines.append(f"\n## Source chunks cited ({len(chunks)})")
    if chunks:
        for i, chunk in enumerate(chunks, start=1):
            score: float = float(chunk.get("score", 0.0))
            lines.append(
                f"- [{i}] Law: {chunk['law']}, Article: {chunk['article']}"
                f" (score: {score:.2f})"
            )
    else:
        lines.append("- (none)")

    audit: object = state.get("audit")
    verdict: str = "N/A"
    confidence: float = 0.0
    critique: str = ""
    if isinstance(audit, dict):
        verdict = str(audit.get("verdict", "N/A"))
        try:
            confidence = float(audit.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        critique = str(audit.get("critique", ""))
    revision_count: int = int(state.get("revision_count", 0))
    lines.append(
        f"\n## Audit verdict: {verdict} "
        f"(confidence: {confidence:.2f}, revisions: {revision_count})"
    )
    if critique:
        lines.append(f"\n> {critique}")

    warnings: list[str] = list(state.get("warnings", []))
    if warnings:
        lines.append("\n## Warnings")
        for w in warnings:
            lines.append(f"- {w}")

    return "\n".join(lines)


def _audit_trace_markdown(history: list[RevisionStep]) -> str:
    """Render the full revision history as Markdown for the Audit Trace tab.

    Each entry shows one draft and the auditor's verdict on it. Pure function.
    """
    if not history:
        return (
            "### Audit Trace\n\n"
            "No audit trace available. Run a translation first."
        )
    lines: list[str] = [
        f"### Audit Trace ({len(history)} pass"
        f"{'es' if len(history) != 1 else ''})"
    ]
    for i, step in enumerate(history, start=1):
        lines.append(f"\n---\n\n#### Pass {i}")
        lines.append(f"**Verdict:** {step['verdict']}  ")
        lines.append(f"**Confidence:** {step['confidence']:.2f}")
        lines.append(f"\n**Draft:**\n\n```\n{step['draft']}\n```")
        if step["critique"]:
            lines.append(f"\n**Critique:** {step['critique']}")
        if step["violations"]:
            lines.append("\n**Violations:**")
            for v in step["violations"]:
                lines.append(f"- {v}")
    return "\n".join(lines)


def _translate_for_ui(
    input_text: str,
    direction: str,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: EmbeddingAdapter,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: TranslationMemory | None = None,
    reviewer: HumanReviewer | None = None,
) -> UiTranslationResult:
    """Run one streamed translation and build the three UI outputs.

    The testable core behind the Gradio "Translate" button: it calls
    :func:`run_translation_streamed` (capturing the full revision history) and
    projects the final state + history into the translation text, a Markdown
    provenance block, and a Markdown audit trace. The Gradio handler is a thin
    closure over this so the logic is unit-testable without Gradio
    (testing-verification §3.4).

    ``reviewer`` (HITL), when supplied AND ``cfg.hitl_enabled`` is True, pauses
    for human review after the autonomous loop.
    """
    state, history = run_translation_streamed(
        input_text, direction, cfg,
        llm=llm, embedder=embedder,
        glossary_index=glossary_index, persist_dir=persist_dir,
        run_logger=run_logger, tm=tm,
        reviewer=reviewer,
    )
    return UiTranslationResult(
        translation=state.get("final_output") or "",
        provenance_md=_provenance_markdown(state),
        audit_trace_md=_audit_trace_markdown(history),
    )


def _resolve_input(input_arg: str) -> str:
    """Resolve ``--input`` to text: read from file if it's an existing path,
    otherwise treat as literal text."""
    path: Path = Path(input_arg)
    if path.is_file():
        root: Path = Path(__file__).resolve().parent.parent.parent.parent
        validate_path_in_root(path, root)
        return path.read_text(encoding="utf-8")
    return input_arg


# ---------------------------------------------------------------------------
# 4.1.2 batch helpers
# ---------------------------------------------------------------------------


def _state_to_batch_record(state: TranslationState) -> dict[str, object]:
    """Project a final ``TranslationState`` into a JSONL batch output record."""
    audit: object = state.get("audit")
    verdict: str | None = None
    confidence: float = 0.0
    if isinstance(audit, dict):
        verdict = str(audit.get("verdict")) if audit.get("verdict") else None
        try:
            confidence = float(audit.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
    return {
        "final_output": state.get("final_output"),
        "direction": state.get("direction"),
        "glossary_terms_applied": [
            {
                "source_term": h["source_term"],
                "target_term": h["target_term"],
                "law_ref": h["law_ref"],
                "article_ref": h.get("article_ref", ""),
            }
            for h in state.get("glossary_hits", [])
        ],
        "source_chunks_cited": [
            {
                "law": c["law"],
                "article": c["article"],
                "score": c.get("score", 0.0),
            }
            for c in state.get("context_chunks", [])
        ],
        "audit_verdict": verdict,
        "audit_confidence": confidence,
        "revision_count": state.get("revision_count", 0),
        "warnings": list(state.get("warnings", [])),
    }


def _process_batch(
    input_path: Path,
    output_path: Path,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: EmbeddingAdapter,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: TranslationMemory | None = None,
) -> int:
    """Process a JSONL batch sequentially (concurrency = 1 per RAM rule).

    Each input line is a JSON object ``{"input": ..., "direction": ...}``.
    Writes one JSON output line per record with translation + provenance.
    Returns the number of records processed.
    """
    count: int = 0
    line_no: int = 0
    with open(input_path, encoding="utf-8") as fin, \
            open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line_no += 1
            line = line.strip()
            if not line:
                continue
            try:
                record = BatchRecord.model_validate_json(line)
            except ValidationError:
                # Skip malformed records (harden-untrusted-input-surfaces §6.1).
                fout.write(
                    json.dumps(
                        {"error": f"malformed record at line {line_no}"},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                continue
            state = run_translation(
                record.input, record.direction, cfg,
                llm=llm, embedder=embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
                run_logger=run_logger, tm=tm,
            )
            output_record: dict[str, object] = _state_to_batch_record(state)
            fout.write(json.dumps(output_record, ensure_ascii=False) + "\n")
            count += 1
    return count
