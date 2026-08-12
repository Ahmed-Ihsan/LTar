"""``word`` command — translate a Word (.docx) document in place.

Mirrors ``commands/excel.py`` (add-pdf-word-translation change). Registers
the ``word`` subcommand on the Typer ``app``.
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
from src.components.interfaces.orchestration import Direction
from src.components.interfaces.word import translate_word
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
def word(
    input_arg: Annotated[
        Path,
        typer.Option("--input", help="Path to the input .docx document."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Path to the output .docx document."),
    ],
    direction: Annotated[
        Direction,
        typer.Option(
            "--direction",
            help="Translation direction: ar-en, en-ar, or auto "
                 "(auto-detect per paragraph by script dominance).",
        ),
    ],
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = _cli._DEFAULT_CONFIG,
) -> None:
    """Translate a Word (.docx) document, preserving all non-text artifacts.

    Translates human-readable text (body paragraphs, comments, headers,
    footers, footnotes, endnotes) through the translation pipeline and writes
    a new .docx with styles, tables, images, tracked changes, hyperlinks, and
    structure preserved exactly.
    """
    report = run_document_command(
        input_arg, out, ".docx", config_path, direction.value, translate_word,
    )
    render_document_report(
        report,
        f"word complete: {report.translated}/{report.total_segments} "
        f"segment(s) translated -> {out}",
    )
