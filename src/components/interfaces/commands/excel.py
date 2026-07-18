"""``excel`` command — translate an Excel (.xlsx) workbook in place.

Moved from ``cli.py`` (Change 5 task 4.9 — all commands split into per-command
modules).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.components.interfaces import cli as _cli
from src.components.interfaces.excel import translate_excel
from src.components.interfaces.models import Adapters
from src.components.interfaces.orchestration import Direction
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
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
    ] = _cli._DEFAULT_CONFIG,
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

    cfg = _cli.load_or_exit(config_path)

    root: Path = _cli._project_root(cfg)
    _cli.validate_path_in_root(input_arg, root)
    _cli.validate_path_in_root(out, root)

    adapters: Adapters = _cli._construct_adapters(cfg)

    try:
        with _cli._new_run_logger(cfg) as run_logger:
            report = translate_excel(
                str(input_arg), str(out), direction.value, cfg,
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
