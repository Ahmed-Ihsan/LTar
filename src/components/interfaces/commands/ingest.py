"""``ingest`` command — wrapper around ``src.ingestion`` (task 4.1.3).

Moved from ``cli.py`` (Change 5 task 4.5).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.components.interfaces import cli as _cli
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
def ingest(
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
    ] = _cli._DEFAULT_CONFIG,
) -> None:
    """Ingest glossary and/or corpus into local stores (wrapper around src.ingestion)."""
    from src.components.knowledge_sources.ingestion import run_ingestion

    cfg = _cli.load_or_exit(config_path)

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
