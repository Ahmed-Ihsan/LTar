"""``pdf`` command — translate a PDF (.pdf) document to a sidecar file.

Mirrors ``commands/excel.py`` and ``commands/word.py`` (add-pdf-word-translation
change). Registers the ``pdf`` subcommand on the Typer ``app``. The output
format (``.docx`` or ``.txt``) is selected by ``cfg.pdf.out_format``.
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
from src.components.interfaces.pdf import translate_pdf
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
def pdf(
    input_arg: Annotated[
        Path,
        typer.Option("--input", help="Path to the input .pdf document."),
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="Path to the output sidecar (.docx or .txt)."),
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
    """Translate a PDF (.pdf) document to a sidecar .docx or .txt file.

    Extracts text per page, translates each paragraph through the translation
    pipeline, and writes a new sidecar file (``.docx`` by default, or ``.txt``
    per ``cfg.pdf.out_format``). The original PDF is not modified.
    """
    report = run_document_command(
        input_arg, out, ".pdf", config_path, direction.value, translate_pdf,
    )
    render_document_report(
        report,
        f"pdf complete: {report.translated}/{report.total_segments} "
        f"segment(s) translated across {report.total_pages} page(s) -> {out}",
    )
