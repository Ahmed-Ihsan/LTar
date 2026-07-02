"""Structured per-run JSONL logging for the translation pipeline (task 4.3.1).

Single responsibility (per ARCHITECTURE.md / engineering-principles §1.1):
write one JSON line per node execution to ``logs/run_<run_id>.jsonl`` carrying
the mandated run metrics — input length, glossary hit count, chunk count, draft
length, audit verdict, revision count, and per-node latency — so a translation
run leaves a complete, machine-parseable provenance trail on disk.

The logger is injected into ``build_graph`` (DIP, engineering-principles §1.5)
and wraps each node from the orchestration seam (``src.graph``); the node
functions in ``src.nodes`` are not modified (OCP, engineering-principles §1.2:
existing code is closed for modification). When no logger is supplied, the
pipeline runs exactly as before — logging is opt-in at the seam.

Implemented in Phase 4 (task 4.3.1).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

from src.state import TranslationState

# Mandated metric fields per TODO 4.3.1 — the closed set this logger emits.
_LOG_FIELDS: tuple[str, ...] = (
    "input_length",
    "glossary_hit_count",
    "chunk_count",
    "draft_length",
    "audit_verdict",
    "revision_count",
)


def _new_run_id() -> str:
    """A filesystem-safe run id from the current UTC timestamp."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


class RunLogger:
    """Append one JSON line per node execution to ``logs/run_<run_id>.jsonl``.

    The log directory is created idempotently. The file is opened in append
    mode and flushed after every line so a crash mid-run still leaves the
    preceding node lines on disk. Use :meth:`close` (or the context manager)
    to release the file handle.

    ``run_id`` defaults to a UTC timestamp; tests pass an explicit id for a
    deterministic filename (``run_<id>.jsonl``).
    """

    __slots__ = ("_log_dir", "_run_id", "_path", "_fh")

    def __init__(
        self, log_dir: Path | str, run_id: str | None = None
    ) -> None:
        self._log_dir: Path = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._run_id: str = run_id if run_id is not None else _new_run_id()
        self._path: Path = self._log_dir / f"run_{self._run_id}.jsonl"
        self._fh: IO[str] = self._path.open("a", encoding="utf-8")

    @property
    def run_id(self) -> str:
        """The run id used in the log filename and every emitted record."""
        return self._run_id

    @property
    def path(self) -> Path:
        """The absolute path of the ``run_<id>.jsonl`` file being written."""
        return self._path

    def log_node(
        self,
        node_name: str,
        latency_ms: float,
        state: TranslationState,
    ) -> None:
        """Emit one JSON line for a single node execution.

        Metric fields are projected defensively from ``state``: a field that a
        node has not yet populated is recorded as ``0`` / ``None`` rather than
        raising, so the preprocess node (which runs before ``draft`` / ``audit``
        exist) logs cleanly.
        """
        audit: object = state.get("audit")
        verdict: str | None = (
            audit.get("verdict")  # type: ignore[union-attr]
            if isinstance(audit, dict) else None
        )
        record: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self._run_id,
            "node": node_name,
            "latency_ms": round(float(latency_ms), 3),
            "input_length": len(state.get("input_text") or ""),
            "glossary_hit_count": len(state.get("glossary_hits") or []),
            "chunk_count": len(state.get("context_chunks") or []),
            "draft_length": len(state.get("draft") or ""),
            "audit_verdict": verdict,
            "revision_count": int(state.get("revision_count") or 0),
        }
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        """Close the underlying file handle. Idempotent."""
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> RunLogger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
