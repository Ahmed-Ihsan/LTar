"""``batch`` command — translate a JSONL batch sequentially (task 4.1.2).

Moved from ``cli.py`` (Change 5 task 4.4).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.components.interfaces import cli as _cli
from src.components.interfaces.models import Adapters
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
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
    ] = _cli._DEFAULT_CONFIG,
) -> None:
    """Translate a JSONL batch sequentially and write JSONL output."""
    if not input_arg.is_file():
        typer.secho(
            f"input file not found: {input_arg}", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    cfg = _cli.load_or_exit(config_path)

    root: Path = _cli._project_root(cfg)
    _cli.validate_path_in_root(input_arg, root)
    _cli.validate_path_in_root(out, root)

    adapters: Adapters = _cli._construct_adapters(cfg)

    count: int = 0
    try:
        with _cli._new_run_logger(cfg) as run_logger:
            count = _cli._process_batch(
                input_arg, out, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index,
                persist_dir=adapters.persist_dir,
                run_logger=run_logger,
                tm=adapters.tm,
            )
    finally:
        if adapters.tm is not None:
            adapters.tm.close()

    typer.secho(
        f"batch complete: {count} record(s) written to {out}",
        fg=typer.colors.GREEN,
    )
