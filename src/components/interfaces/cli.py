"""Command-line interface for the Iraqi Legal Translation Agent.

Entry point: ``python -m src.cli`` or the ``iraqi-translate`` console script.

Subcommands:
- ``doctor``  — environment diagnostics (task 1.3.3).
- ``translate`` — translate a single text or file (task 4.1.1).
- ``batch``   — translate a JSONL batch sequentially (task 4.1.2).
- ``ingest``  — wrapper around ``src.ingestion`` (task 4.1.3).
- ``tm-build`` / ``tm-build-parallel`` / ``tm-add-parallel`` — TM management (task 8).
- ``ui``      — launch the web-based desktop UI (task 4.2.1/4.2.2).

Responsibility (engineering-principles §1.1): parse CLI args, construct
concrete adapters (the CLI is the only place adapters are constructed,
engineering-principles §3.6), and render output. Diagnostics, orchestration,
and TM commands live in dedicated modules (:mod:`diagnostics`,
:mod:`orchestration`, :mod:`tm_commands`); this module is the thin
composition root that wires them onto the Typer ``app``.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import ollama
import typer

from src.components.infrastructure.run_logging import RunLogger
from src.components.interfaces.config_loader import load_or_exit
from src.components.interfaces.diagnostics import (
    _check_chroma_dir,
    _check_glossary_db,
    _check_models_present,
    _check_ollama_reachable,
    _check_ram_headroom,
    _list_ollama_models,  # noqa: F401  — re-exported for web_ui / tk_ui
    _render_result,
)
from src.components.interfaces.excel import translate_excel
from src.components.interfaces.models import Adapters, CheckResult
from src.components.interfaces.orchestration import (
    Direction,
    RevisionStep,  # noqa: F401  — re-exported for tests / UI
    StdinHumanReviewer,
    _audit_trace_markdown,  # noqa: F401  — re-exported for tests / UI
    _initial_state,  # noqa: F401  — re-exported for tests
    _process_batch,
    _provenance_markdown,  # noqa: F401  — re-exported for tests / UI
    _render_provenance,  # noqa: F401  — re-exported for tests
    _resolve_input,
    _translate_for_ui,  # noqa: F401  — re-exported for tests / UI
    run_translation,
    run_translation_streamed,  # noqa: F401  — re-exported for tests / UI
)
from src.components.interfaces.tm_commands import (
    tm_add_parallel,
    tm_build,
    tm_build_parallel,
)
from src.components.translation_pipeline.exceptions import (
    EmbeddingConnectionError,
    OllamaConnectionError,
    PathContainmentError,
    RAMGuardError,
)
from src.config import AppConfig
from src.utils.paths import validate_path_in_root

if TYPE_CHECKING:
    from src.components.knowledge_sources.tm import TranslationMemory

app = typer.Typer(
    add_completion=False,
    rich_markup_mode=None,  # plain Click help; rich panels break on piped Windows stdout
    help="Iraqi Legal Translation Agent — local offline Arabic<->English "
         "translation of Iraqi legal texts.",
)


def _project_root(cfg: AppConfig) -> Path:
    """Return the project root (parent of the ``src`` package)."""
    return Path(__file__).resolve().parent.parent.parent.parent


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


def _new_tm(cfg: AppConfig) -> TranslationMemory | None:
    """Construct a :class:`TranslationMemory` when TM is enabled (task 7).

    Returns ``None`` when ``cfg.tm_enabled`` is False so the ``tm_lookup``
    node becomes a no-op pass-through. The DB path is resolved against the
    project root (single source of truth: ``cfg.tm_db``).
    """
    if not cfg.tm_enabled:
        return None
    from src.components.knowledge_sources.tm import TranslationMemory

    return TranslationMemory(
        db_path=str(_resolve_path(cfg, cfg.tm_db)),
        similarity_threshold=cfg.tm_similarity_threshold,
    )


def _construct_adapters(cfg: AppConfig) -> Adapters:
    """Construct the concrete Ollama/ChromaDB/Glossary/TM adapters (DI seam).

    The single place concrete adapters are built (engineering-principles
    §3.6). Raises :class:`typer.Exit` (code 1) on a glossary load failure.
    """
    from src.components.infrastructure.embeddings import Embedder
    from src.components.infrastructure.llm import OllamaEngineAdapter
    from src.components.knowledge_sources.glossary import load_glossary_index

    persist_dir: str = str(_resolve_path(cfg, cfg.paths.chroma_dir))
    llm = OllamaEngineAdapter(model=cfg.llm_model, host=cfg.ollama_host)
    embedder = Embedder(model=cfg.embed_model, host=cfg.ollama_host)
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
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Run environment diagnostics: Ollama, models, DB stores, RAM headroom."""
    cfg: AppConfig = load_or_exit(config_path)
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
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Translate a single text or file and print output + provenance."""
    cfg: AppConfig = load_or_exit(config_path)

    root: Path = _project_root(cfg)
    input_text: str
    try:
        if Path(input_arg).exists():
            validate_path_in_root(Path(input_arg), root)
        input_text = _resolve_input(input_arg)
    except PathContainmentError as e:
        typer.secho(f"path not allowed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from e
    except OSError as e:
        typer.secho(f"cannot read input file: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    if not input_text.strip():
        typer.secho("input text is empty.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Construct concrete adapters (engineering-principles §3.6).
    adapters: Adapters = _construct_adapters(cfg)

    try:
        with _new_run_logger(cfg) as run_logger:
            state = run_translation(
                input_text, direction.value, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index, persist_dir=adapters.persist_dir,
                run_logger=run_logger,
                tm=adapters.tm,
                reviewer=StdinHumanReviewer() if cfg.hitl_enabled else None,
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
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Translate a JSONL batch sequentially and write JSONL output."""
    if not input_arg.is_file():
        typer.secho(
            f"input file not found: {input_arg}", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    cfg: AppConfig = load_or_exit(config_path)

    root: Path = _project_root(cfg)
    try:
        validate_path_in_root(input_arg, root)
        validate_path_in_root(out, root)
    except PathContainmentError as e:
        typer.secho(f"path not allowed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from e

    # Construct concrete adapters (engineering-principles §3.6).
    adapters: Adapters = _construct_adapters(cfg)

    try:
        with _new_run_logger(cfg) as run_logger:
            count: int = _process_batch(
                input_arg, out, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index, persist_dir=adapters.persist_dir,
                run_logger=run_logger,
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
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Ingest glossary and/or corpus into local stores (wrapper around src.ingestion)."""
    from src.components.knowledge_sources.ingestion import run_ingestion

    cfg: AppConfig = load_or_exit(config_path)

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
# tm-build commands (task 8) — registered from tm_commands module
# ---------------------------------------------------------------------------

app.command("tm-build")(tm_build)
app.command("tm-build-parallel")(tm_build_parallel)
app.command("tm-add-parallel")(tm_add_parallel)


# ---------------------------------------------------------------------------
# 4.2.1 / 4.2.2 web-based desktop UI command
# ---------------------------------------------------------------------------


@app.command()
def ui(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Launch a web-based desktop UI for interactive translation + audit trace.

    Tab "Translate": source text box, direction + model dropdowns, Translate
    button, and an output panel with the translation plus a provenance block
    (glossary hits, retrieved chunks, audit verdict).

    Tab "Audit Trace": the full revision history (each draft + critique) for
    the last run (task 4.2.2).
    """
    cfg: AppConfig = load_or_exit(config_path)

    # Construct concrete adapters once at launch (engineering-principles §3.6).
    adapters: Adapters = _construct_adapters(cfg)

    from src.components.interfaces.web_ui import launch_ui

    typer.secho("Launching web desktop UI…", fg=typer.colors.CYAN)
    launch_ui(cfg, adapters)


# ---------------------------------------------------------------------------
# excel command — translate an Excel (.xlsx) workbook in place
# ---------------------------------------------------------------------------


@app.command()
def excel(
    input_arg: Annotated[
        Path,
        typer.Option("--input", help="Path to the input .xlsx workbook."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Path to the output .xlsx workbook."),
    ],
    direction: Annotated[
        Direction,
        typer.Option("--direction", help="Translation direction."),
    ],
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Translate an Excel (.xlsx) workbook, preserving all non-text artifacts.

    Translates human-readable text (cell strings, inline strings, comments,
    headers/footers, chart titles) through the translation pipeline and writes
    a new workbook with formulas, merged cells, charts, images, conditional
    formatting, data validation, hyperlinks, page layout, and structure
    preserved exactly.
    """
    if not input_arg.is_file():
        typer.secho(
            f"input file not found: {input_arg}", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)
    if input_arg.suffix.lower() != ".xlsx":
        typer.secho(
            f"input must be an .xlsx file, got: {input_arg.suffix}",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    cfg: AppConfig = load_or_exit(config_path)

    root: Path = _project_root(cfg)
    try:
        validate_path_in_root(input_arg, root)
        validate_path_in_root(out, root)
    except PathContainmentError as e:
        typer.secho(f"path not allowed: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from e

    # Construct concrete adapters (engineering-principles §3.6).
    adapters: Adapters = _construct_adapters(cfg)

    try:
        with _new_run_logger(cfg) as run_logger:
            report = translate_excel(
                str(input_arg), str(out), direction.value, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index,
                persist_dir=adapters.persist_dir,
                run_logger=run_logger,
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
            f"RAM guard aborted the Excel run: {e}\n"
            "Free up memory (close other applications) and retry.",
            fg=typer.colors.YELLOW, err=True,
        )
        raise typer.Exit(code=3) from e
    except Exception as e:
        typer.secho(f"excel error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    finally:
        if adapters.tm is not None:
            adapters.tm.close()

    typer.secho(
        f"excel complete: {report.translated}/{report.total_segments} "
        f"segment(s) translated -> {out}",
        fg=typer.colors.GREEN,
    )
    if report.failed:
        typer.secho(
            f"  {report.failed} segment(s) failed (original text preserved).",
            fg=typer.colors.YELLOW,
        )
    if report.skipped:
        typer.secho(
            f"  {report.skipped} segment(s) skipped.", fg=typer.colors.YELLOW,
        )
    if report.cancelled:
        typer.secho("  run was cancelled.", fg=typer.colors.YELLOW)
    for w in report.warnings:
        typer.secho(f"  warning: {w}", fg=typer.colors.YELLOW)


if __name__ == "__main__":
    app()
