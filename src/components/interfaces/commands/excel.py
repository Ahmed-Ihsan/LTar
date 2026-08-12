"""``excel`` command — translate an Excel (.xlsx) workbook in place.

Moved from ``cli.py`` (Change 5 task 4.9 — all commands split into per-command
modules).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.components.interfaces import cli as _cli
from src.components.interfaces._doc_common import (
    render_document_report,
    run_document_command,
)
from src.components.interfaces.excel import translate_excel
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
        typer.Option(
            "--direction",
            help="Translation direction: ar-en, en-ar, or auto "
                 "(auto-detect per cell by script dominance).",
        ),
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
    report = run_document_command(
        input_arg, out, ".xlsx", config_path, direction.value, translate_excel,
        suffix_article="an",
    )
    render_document_report(
        report,
        f"excel complete: {report.translated}/{report.total_segments} "
        f"segment(s) translated -> {out}",
    )
