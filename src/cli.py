"""Command-line interface for the Iraqi Legal Translation Agent.

Entry point: ``python -m src.cli`` or the ``iraqi-translate`` console script.

Subcommands:
- ``doctor``  — environment diagnostics (task 1.3.3).
- ``translate`` — translate a single text or file (task 4.1.1).
- ``batch``   — translate a JSONL batch sequentially (task 4.1.2).
- ``ingest``  — wrapper around ``src.ingestion`` (task 4.1.3).

Responsibility (engineering-principles §1.1): parse CLI args, construct
concrete adapters (the CLI is the only place adapters are constructed,
engineering-principles §3.6), and render output. The ``doctor`` command
coordinates a set of small, single-purpose check functions and renders a
green-check / red-failure summary.
"""
from __future__ import annotations

import enum
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, TypedDict

import ollama
import typer

from src.config import AppConfig, load_config
from src.exceptions import (
    EmbeddingConnectionError,
    OllamaConnectionError,
    RAMGuardError,
)
from src.glossary import GlossaryIndex
from src.graph import build_graph
from src.llm import LLMEngineAdapter
from src.memory import MemoryInfo, read_memory_info
from src.run_logging import RunLogger
from src.state import TranslationState

app = typer.Typer(
    add_completion=False,
    rich_markup_mode=None,  # plain Click help; rich panels break on piped Windows stdout
    help="Iraqi Legal Translation Agent — local offline Arabic<->English "
         "translation of Iraqi legal texts.",
)

# RAM budget per README.md §3 (GB). Sum = 8.0 GB, the hard ceiling.
_RAM_BUDGET_OS_GB: float = 1.8
_RAM_BUDGET_LLM_GB: float = 3.0
_RAM_BUDGET_EMBED_GB: float = 0.3
_RAM_BUDGET_CHROMA_GB: float = 0.5
_RAM_BUDGET_PYTHON_GB: float = 0.4
_RAM_BUDGET_TOTAL_GB: float = (
    _RAM_BUDGET_OS_GB
    + _RAM_BUDGET_LLM_GB
    + _RAM_BUDGET_EMBED_GB
    + _RAM_BUDGET_CHROMA_GB
    + _RAM_BUDGET_PYTHON_GB
)  # 6.0 GB of fixed components; 2.0 GB reserved as ingestion headroom


@dataclass(slots=True, frozen=True)
class CheckResult:
    """Outcome of a single ``doctor`` check."""

    name: str
    ok: bool
    detail: str


def _project_root(cfg: AppConfig) -> Path:
    """Return the project root (parent of the ``src`` package)."""
    return Path(__file__).resolve().parent.parent


def _resolve_path(cfg: AppConfig, rel: str) -> Path:
    """Resolve a config-relative path against the project root."""
    return _project_root(cfg) / rel


def _new_run_logger(cfg: AppConfig) -> RunLogger:
    """Build a :class:`RunLogger` writing to ``<project_root>/logs`` (task 4.3.1).

    One JSONL file per run (``run_<timestamp>.jsonl``). The handle is flushed
    after every node line, so a crash mid-run still leaves the preceding node
    lines on disk; the OS reclaims the handle when the CLI process exits.
    """
    return RunLogger(log_dir=_resolve_path(cfg, "logs"))


def _new_tm(cfg: AppConfig) -> object | None:
    """Construct a :class:`TranslationMemory` when TM is enabled (task 7).

    Returns ``None`` when ``cfg.tm_enabled`` is False so the ``tm_lookup``
    node becomes a no-op pass-through. The DB path is resolved against the
    project root (single source of truth: ``cfg.tm_db``).
    """
    if not cfg.tm_enabled:
        return None
    from src.tm import TranslationMemory

    return TranslationMemory(
        db_path=str(_resolve_path(cfg, cfg.tm_db)),
        similarity_threshold=cfg.tm_similarity_threshold,
    )


@dataclass(slots=True, frozen=True)
class Adapters:
    """Bundle of concrete adapters constructed by the CLI (engineering-principles §3.6).

    Built once per command invocation and passed into the orchestration seam.
    ``tm`` is ``None`` when TM is disabled.
    """

    llm: LLMEngineAdapter
    embedder: object
    glossary_index: GlossaryIndex | None
    persist_dir: str
    tm: object | None


def _construct_adapters(cfg: AppConfig) -> Adapters:
    """Construct the concrete Ollama/ChromaDB/Glossary/TM adapters (DI seam).

    The single place concrete adapters are built (engineering-principles
    §3.6). Raises :class:`typer.Exit` (code 1) on a glossary load failure.
    """
    from src.embeddings import Embedder
    from src.glossary import load_glossary_index
    from src.llm import OllamaEngineAdapter

    persist_dir: str = str(_resolve_path(cfg, cfg.paths.chroma_dir))
    llm = OllamaEngineAdapter(host=cfg.ollama_host)
    embedder = Embedder(host=cfg.ollama_host)
    try:
        glossary_index = load_glossary_index(
            _resolve_path(cfg, cfg.paths.glossary_db)
        )
    except Exception as e:
        typer.secho(
            f"glossary index error: {e}", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1) from e

    return Adapters(
        llm=llm,
        embedder=embedder,
        glossary_index=glossary_index,
        persist_dir=persist_dir,
        tm=_new_tm(cfg),
    )


def _check_ollama_reachable(client: ollama.Client) -> CheckResult:
    """Verify the Ollama daemon is reachable and responding."""
    try:
        client.list()
    except (ConnectionError, OSError) as e:
        return CheckResult(
            "Ollama daemon reachable",
            ok=False,
            detail=f"cannot connect to Ollama: {e}",
        )
    return CheckResult(
        "Ollama daemon reachable",
        ok=True,
        detail="connected, /api/tags responded",
    )


def _canonical_model_name(name: str) -> str:
    """Normalize an Ollama model name to its canonical tagged form.

    Ollama defaults an omitted tag to ``:latest`` (e.g. ``nomic-embed-text``
    is the same model as ``nomic-embed-text:latest``). This lets a config
    value without a tag match the tagged form reported by ``ollama list``.
    """
    if ":" in name:
        return name
    return f"{name}:latest"


def _check_models_present(client: ollama.Client, cfg: AppConfig) -> CheckResult:
    """Verify both the LLM and embedding models are present locally."""
    try:
        response = client.list()
    except (ConnectionError, OSError) as e:
        return CheckResult(
            "Required models present",
            ok=False,
            detail=f"could not list models: {e}",
        )
    installed: set[str] = {
        _canonical_model_name(m.model) for m in response.models
    }
    required: list[str] = [cfg.llm_model, cfg.embed_model]
    missing: list[str] = [
        name for name in required
        if _canonical_model_name(name) not in installed
    ]
    if missing:
        return CheckResult(
            "Required models present",
            ok=False,
            detail=f"missing: {', '.join(missing)} (run `ollama pull <name>`)",
        )
    return CheckResult(
        "Required models present",
        ok=True,
        detail=f"{cfg.llm_model} + {cfg.embed_model} both installed",
    )


def _check_chroma_dir(cfg: AppConfig) -> CheckResult:
    """Verify the ChromaDB persistent directory exists."""
    chroma_path: Path = _resolve_path(cfg, cfg.paths.chroma_dir)
    if chroma_path.is_dir():
        return CheckResult(
            "ChromaDB directory exists",
            ok=True,
            detail=str(chroma_path),
        )
    return CheckResult(
        "ChromaDB directory exists",
        ok=False,
        detail=f"not found: {chroma_path} (run `python -m src.ingestion --rebuild`)",
    )


def _check_glossary_db(cfg: AppConfig) -> CheckResult:
    """Verify the glossary SQLite DB exists and is non-empty."""
    db_path: Path = _resolve_path(cfg, cfg.paths.glossary_db)
    if not db_path.is_file():
        return CheckResult(
            "Glossary SQLite populated",
            ok=False,
            detail=f"not found: {db_path} (run `python -m src.ingestion --rebuild`)",
        )
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cursor: sqlite3.Cursor = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            )
            table_count: int = int(cursor.fetchone()[0])
    except sqlite3.DatabaseError as e:
        return CheckResult(
            "Glossary SQLite populated",
            ok=False,
            detail=f"cannot read {db_path}: {e}",
        )
    if table_count == 0:
        return CheckResult(
            "Glossary SQLite populated",
            ok=False,
            detail=f"{db_path} exists but contains no tables (ingestion not run)",
        )
    return CheckResult(
        "Glossary SQLite populated",
        ok=True,
        detail=f"{db_path} ({table_count} table{'s' if table_count != 1 else ''})",
    )


def _detect_offload_mode(client: ollama.Client) -> str:
    """Detect GPU-vs-CPU offload of the loaded LLM from ``ollama ps``.

    Returns one of: ``"100% GPU"``, ``"CPU-only"``, ``"partial GPU"``,
    or ``"not loaded"`` (no model currently resident).
    """
    try:
        proc = client.ps()
    except (ConnectionError, OSError):
        return "not loaded"
    if not proc.models:
        return "not loaded"
    loaded = next(
        (m for m in proc.models if m.size and m.size > 0),
        None,
    )
    if loaded is None:
        return "not loaded"
    size: int = int(loaded.size)
    vram: int = int(loaded.size_vram or 0)
    if size == 0:
        return "not loaded"
    ratio: float = vram / size
    if ratio >= 0.999:
        return "100% GPU"
    if ratio <= 0.001:
        return "CPU-only"
    return f"partial GPU ({ratio * 100:.0f}% in VRAM)"


def _check_ram_headroom(client: ollama.Client, cfg: AppConfig) -> CheckResult:
    """Estimate RAM headroom against the 8 GB budget (README.md §3).

    Reports total system RAM, the fixed-component budget, the effective
    headroom, and the LLM offload mode. On a CPU-only target the 7B q5
    model exceeds the 3.0 GB LLM budget line item, so a warning is raised
    (see docs/verification_log.md §1.2.3 caveat).
    """
    mem: MemoryInfo | None = read_memory_info()
    if mem is None:
        return CheckResult(
            "RAM headroom estimate",
            ok=False,
            detail="cannot read system memory on this platform",
        )
    total_gb: float = mem.total_bytes / (1024 ** 3)
    offload: str = _detect_offload_mode(client)

    # Effective system-RAM cost of the LLM depends on offload mode.
    if offload == "100% GPU":
        llm_system_cost_gb: float = 0.9  # runner overhead only; weights in VRAM
    elif offload == "not loaded":
        llm_system_cost_gb = _RAM_BUDGET_LLM_GB  # assume budgeted worst case
    else:
        llm_system_cost_gb = 5.4  # CPU-only / partial: full weights in system RAM

    fixed_cost_gb: float = (
        _RAM_BUDGET_OS_GB + llm_system_cost_gb + _RAM_BUDGET_EMBED_GB
        + _RAM_BUDGET_CHROMA_GB + _RAM_BUDGET_PYTHON_GB
    )
    headroom_gb: float = total_gb - fixed_cost_gb

    detail: str = (
        f"total {total_gb:.1f} GB; fixed budget {fixed_cost_gb:.1f} GB "
        f"(LLM {llm_system_cost_gb:.1f} GB, offload: {offload}); "
        f"headroom ~{headroom_gb:.1f} GB"
    )
    # Hard ceiling is 8 GB. CPU-only offload blows the LLM budget -> warn.
    is_ok: bool = total_gb >= 8.0 and not (
        offload in ("CPU-only",) and headroom_gb < 1.0
    )
    if total_gb < 8.0:
        detail += " [BELOW 8 GB hard ceiling]"
    elif offload == "CPU-only" and headroom_gb < 1.0:
        detail += " [CPU-only: 7B q5 exceeds 3.0 GB LLM budget]"
    return CheckResult("RAM headroom estimate", ok=is_ok, detail=detail)


def _render_result(result: CheckResult) -> None:
    """Render a single check result with a green check or red failure."""
    mark: str = "[OK]  " if result.ok else "[FAIL]"
    color: int = typer.colors.GREEN if result.ok else typer.colors.RED
    typer.secho(f"  {mark} {result.name}: {result.detail}", fg=color)


@app.callback()
def main(
    ctx: typer.Context,
) -> None:
    """Iraqi Legal Translation Agent CLI."""
    _ = ctx


@app.command()
def doctor(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent / "config.yaml",
) -> None:
    """Run environment diagnostics: Ollama, models, DB stores, RAM headroom."""
    try:
        cfg: AppConfig = load_config(config_path)
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    client: ollama.Client = ollama.Client(host=cfg.ollama_host)
    checks: list[CheckResult] = [
        _check_ollama_reachable(client),
        _check_models_present(client, cfg),
        _check_chroma_dir(cfg),
        _check_glossary_db(cfg),
        _check_ram_headroom(client, cfg),
    ]

    typer.secho("doctor: running environment checks", fg=typer.colors.CYAN)
    for result in checks:
        _render_result(result)

    all_ok: bool = all(r.ok for r in checks)
    if all_ok:
        typer.secho("\nAll checks passed.", fg=typer.colors.GREEN)
    else:
        failed: int = sum(1 for r in checks if not r.ok)
        typer.secho(
            f"\n{failed} check(s) failed.", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# 4.1.1 translate command
# ---------------------------------------------------------------------------

class Direction(enum.Enum):
    """Translation direction (closed set, clean-code §1.1)."""

    ar_en = "ar-en"
    en_ar = "en-ar"


def _initial_state(input_text: str, direction: str) -> TranslationState:
    """Build the minimal LangGraph input state from caller-supplied fields."""
    return {
        "input_text": input_text,
        "direction": direction,  # type: ignore[arg-type]
        "glossary_hits": [],
        "context_chunks": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
    }


def run_translation(
    input_text: str,
    direction: str,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: object,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: object | None = None,
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
    return graph.invoke(state)


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
    embedder: object,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: object | None = None,
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
    """
    from src.graph import AUDIT_NODE, TRANSLATE_NODE

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
    return merged, history


def _render_provenance(state: TranslationState) -> str:
    """Render the provenance block from the final translation state.

    Includes: glossary terms applied, source chunks cited, audit verdict,
    revision count, and any warnings. Pure function — no I/O.
    """
    lines: list[str] = ["--- Provenance ---"]

    # Glossary terms applied
    hits: list = state.get("glossary_hits", [])
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
    chunks: list = state.get("context_chunks", [])
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
    """
    lines: list[str] = ["### Provenance"]

    hits: list = state.get("glossary_hits", [])
    lines.append(f"**Glossary terms applied ({len(hits)}):**")
    if hits:
        for hit in hits:
            article: str = hit.get("article_ref", "") or ""
            lines.append(
                f'- `{hit["source_term"]}` → `{hit["target_term"]}`'
                f"  — Law: {hit['law_ref']}, Art: {article}"
            )
    else:
        lines.append("- (none)")

    chunks: list = state.get("context_chunks", [])
    lines.append(f"\n**Source chunks cited ({len(chunks)}):**")
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
        f"\n**Audit verdict:** {verdict} "
        f"(confidence: {confidence:.2f}, revisions: {revision_count})"
    )
    if critique:
        lines.append(f"\n> {critique}")

    warnings: list[str] = list(state.get("warnings", []))
    if warnings:
        lines.append("\n**Warnings:**")
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


@dataclass(slots=True, frozen=True)
class UiTranslationResult:
    """The three outputs a single UI translation produces (one per tab/panel)."""

    translation: str
    provenance_md: str
    audit_trace_md: str


def _translate_for_ui(
    input_text: str,
    direction: str,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: object,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: object | None = None,
) -> UiTranslationResult:
    """Run one streamed translation and build the three UI outputs.

    The testable core behind the Gradio "Translate" button: it calls
    :func:`run_translation_streamed` (capturing the full revision history) and
    projects the final state + history into the translation text, a Markdown
    provenance block, and a Markdown audit trace. The Gradio handler is a thin
    closure over this so the logic is unit-testable without Gradio
    (testing-verification §3.4).
    """
    state, history = run_translation_streamed(
        input_text, direction, cfg,
        llm=llm, embedder=embedder,
        glossary_index=glossary_index, persist_dir=persist_dir,
        run_logger=run_logger, tm=tm,
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
        return path.read_text(encoding="utf-8")
    return input_arg


@app.command()
def translate(
    input_arg: Annotated[
        str,
        typer.Option("--input", help="Text to translate, or path to a file."),
    ],
    direction: Annotated[
        Direction,
        typer.Option("--direction", help="Translation direction."),
    ],
    out: Annotated[
        str,
        typer.Option("--out", help="Output destination: file path or 'stdout'."),
    ] = "stdout",
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent / "config.yaml",
) -> None:
    """Translate a single text or file and print output + provenance."""
    try:
        cfg: AppConfig = load_config(config_path)
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    input_text: str
    try:
        input_text = _resolve_input(input_arg)
    except OSError as e:
        typer.secho(f"cannot read input file: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    if not input_text.strip():
        typer.secho("input text is empty.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Construct concrete adapters (engineering-principles §3.6).
    adapters: Adapters = _construct_adapters(cfg)

    try:
        state = run_translation(
            input_text, direction.value, cfg,
            llm=adapters.llm, embedder=adapters.embedder,
            glossary_index=adapters.glossary_index, persist_dir=adapters.persist_dir,
            run_logger=_new_run_logger(cfg),
            tm=adapters.tm,
        )
    except (OllamaConnectionError, EmbeddingConnectionError) as e:
        typer.secho(
            f"Cannot reach the Ollama daemon: {e}\n"
            "Is `ollama serve` running? Start it, then retry.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2) from e
    except RAMGuardError as e:
        typer.secho(
            f"RAM guard aborted the translation: {e}\n"
            "Free up memory (close other applications) and retry.",
            fg=typer.colors.YELLOW, err=True,
        )
        raise typer.Exit(code=3) from e
    except Exception as e:
        typer.secho(f"translation error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    finally:
        if adapters.tm is not None:
            adapters.tm.close()

    final_output: str = state.get("final_output") or ""
    provenance: str = _render_provenance(state)
    output_text: str = f"{final_output}\n\n{provenance}\n"

    if out.lower() == "stdout":
        typer.echo(output_text)
    else:
        try:
            Path(out).write_text(output_text, encoding="utf-8")
            typer.secho(f"output written to {out}", fg=typer.colors.GREEN)
        except OSError as e:
            typer.secho(f"cannot write output: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from e


# ---------------------------------------------------------------------------
# 4.1.2 batch command
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
    embedder: object,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: object | None = None,
) -> int:
    """Process a JSONL batch sequentially (concurrency = 1 per RAM rule).

    Each input line is a JSON object ``{"input": ..., "direction": ...}``.
    Writes one JSON output line per record with translation + provenance.
    Returns the number of records processed.
    """
    count: int = 0
    with open(input_path, encoding="utf-8") as fin, \
            open(output_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            record: dict = json.loads(line)
            state = run_translation(
                record["input"], record["direction"], cfg,
                llm=llm, embedder=embedder,
                glossary_index=glossary_index, persist_dir=persist_dir,
                run_logger=run_logger, tm=tm,
            )
            output_record: dict[str, object] = _state_to_batch_record(state)
            fout.write(json.dumps(output_record, ensure_ascii=False) + "\n")
            count += 1
    return count


@app.command()
def batch(
    input_arg: Annotated[
        Path,
        typer.Option("--input", help="Path to input JSONL file."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Path to output JSONL file."),
    ],
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent / "config.yaml",
) -> None:
    """Translate a JSONL batch sequentially and write JSONL output."""
    if not input_arg.is_file():
        typer.secho(
            f"input file not found: {input_arg}", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    try:
        cfg: AppConfig = load_config(config_path)
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    # Construct concrete adapters (engineering-principles §3.6).
    adapters: Adapters = _construct_adapters(cfg)

    try:
        count: int = _process_batch(
            input_arg, out, cfg,
            llm=adapters.llm, embedder=adapters.embedder,
            glossary_index=adapters.glossary_index, persist_dir=adapters.persist_dir,
            run_logger=_new_run_logger(cfg),
            tm=adapters.tm,
        )
    except (OllamaConnectionError, EmbeddingConnectionError) as e:
        typer.secho(
            f"Cannot reach the Ollama daemon: {e}\n"
            "Is `ollama serve` running? Start it, then retry.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2) from e
    except RAMGuardError as e:
        typer.secho(
            f"RAM guard aborted the batch: {e}\n"
            "Free up memory (close other applications) and retry.",
            fg=typer.colors.YELLOW, err=True,
        )
        raise typer.Exit(code=3) from e
    except Exception as e:
        typer.secho(f"batch error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    finally:
        if adapters.tm is not None:
            adapters.tm.close()

    typer.secho(
        f"batch complete: {count} record(s) written to {out}",
        fg=typer.colors.GREEN,
    )


# ---------------------------------------------------------------------------
# 4.1.3 ingest wrapper
# ---------------------------------------------------------------------------


@app.command()
def ingest(
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Drop existing stores and re-ingest."),
    ] = False,
    glossary_only: Annotated[
        bool,
        typer.Option("--glossary-only", help="Skip corpus; only load glossary."),
    ] = False,
    corpus_only: Annotated[
        bool,
        typer.Option("--corpus-only", help="Skip glossary; only embed corpus."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Process only the first N articles per file."),
    ] = None,
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent / "config.yaml",
) -> None:
    """Ingest glossary and/or corpus into local stores (wrapper around src.ingestion)."""
    from src.ingestion import run_ingestion

    try:
        cfg: AppConfig = load_config(config_path)
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    _ = rebuild  # run_ingestion always rebuilds atomically
    result = run_ingestion(
        cfg,
        glossary_only=glossary_only,
        corpus_only=corpus_only,
        limit=limit,
    )

    error_count: int = 0
    if result.glossary:
        error_count += (
            result.glossary.conflict_count
            + result.glossary.validation_error_count
        )
    if result.corpus:
        error_count += result.corpus.parse_error_count

    if error_count > 0:
        typer.secho(
            f"\n{error_count} error(s) during ingestion.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)
    typer.secho("\nIngestion complete (0 errors).", fg=typer.colors.GREEN)


# ---------------------------------------------------------------------------
# tm-build command (task 8) — build the Translation Memory SQLite DB
# ---------------------------------------------------------------------------


@app.command("tm-build")
def tm_build(
    corpus_dir: Annotated[
        Path | None,
        typer.Option("--corpus-dir", help="Path to the corpus directory."),
    ] = None,
    tm_db: Annotated[
        str | None,
        typer.Option("--tm-db", help="Path to the TM SQLite DB to create."),
    ] = None,
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent / "config.yaml",
) -> None:
    """Build the Translation Memory SQLite DB from the bilingual corpus."""
    try:
        cfg: AppConfig = load_config(config_path)
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    cdir: Path = corpus_dir if corpus_dir is not None else _resolve_path(cfg, cfg.paths.corpus_dir)
    dbpath: str = tm_db if tm_db is not None else str(_resolve_path(cfg, cfg.tm_db))

    from src.tm import TranslationMemory

    tm = TranslationMemory(
        db_path=dbpath, similarity_threshold=cfg.tm_similarity_threshold
    )
    tm.build_from_corpus(cdir)
    entries = tm.list_all()
    tm.close()
    typer.echo(f"TM built: {len(entries)} entries in {dbpath}")


# ---------------------------------------------------------------------------
# 4.2.1 / 4.2.2 Gradio UI command
# ---------------------------------------------------------------------------


@app.command()
def ui(
    host: Annotated[
        str,
        typer.Option("--host", help="Server bind address."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Server port."),
    ] = 7860,
    share: Annotated[
        bool,
        typer.Option("--share", help="Create a public Gradio share link."),
    ] = False,
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent / "config.yaml",
) -> None:
    """Launch a Gradio web UI for interactive translation + audit trace.

    Tab "Translate": source text box, direction dropdown, Translate button,
    and an output panel with the translation plus a collapsible provenance
    block (glossary hits, retrieved chunks, audit verdict).

    Tab "Audit Trace": the full revision history (each draft + critique) for
    the last run (task 4.2.2).
    """
    import gradio as gr

    try:
        cfg: AppConfig = load_config(config_path)
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    # Construct concrete adapters once at launch (engineering-principles §3.6).
    adapters: Adapters = _construct_adapters(cfg)

    def _translate(
        input_text: str, direction: str,
    ) -> tuple[str, str, str]:
        """Gradio button handler — thin closure over :func:`_translate_for_ui`."""
        if not input_text.strip():
            return (
                "",
                "Input text is empty.",
                _audit_trace_markdown([]),
            )
        try:
            result: UiTranslationResult = _translate_for_ui(
                input_text, direction, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index, persist_dir=adapters.persist_dir,
                run_logger=_new_run_logger(cfg),
                tm=adapters.tm,
            )
        except Exception as e:  # noqa: BLE001 — UI must not crash the server
            return (
                "",
                f"Translation error: {e}",
                _audit_trace_markdown([]),
            )
        return result.translation, result.provenance_md, result.audit_trace_md

    with gr.Blocks(title="Iraqi Legal Translation Agent") as demo:
        with gr.Tab("Translate"):
            input_box = gr.Textbox(
                label="Source text", lines=8, rtl=False,
                placeholder="Paste an Iraqi legal article…",
            )
            direction_dd = gr.Dropdown(
                choices=["ar-en", "en-ar"], value="ar-en",
                label="Direction",
            )
            btn = gr.Button("Translate", variant="primary")
            output_box = gr.Textbox(
                label="Translation", lines=8, interactive=False,
            )
            with gr.Accordion("Provenance", open=False):
                prov_md = gr.Markdown()
        with gr.Tab("Audit Trace"):
            gr.Markdown(
                "The full revision history (each draft + critique) for the "
                "last run."
            )
            trace_md = gr.Markdown(label="Audit Trace")
        btn.click(
            _translate,
            inputs=[input_box, direction_dd],
            outputs=[output_box, prov_md, trace_md],
        )

    typer.secho(
        f"Launching UI on http://{host}:{port}", fg=typer.colors.CYAN,
    )
    demo.launch(
        server_name=host, server_port=port, share=share,
        prevent_thread_lock=False,
    )


if __name__ == "__main__":
    app()
