"""``ui`` command — launch the web-based desktop UI (task 4.2.1/4.2.2).

Moved from ``cli.py`` (Change 5 task 4.8). Uses the :class:`UiBackend` protocol
from :mod:`src.components.interfaces.ui_backend` and selects the backend from
``cfg.ui.backend`` (Change 5 task 6.5).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.components.interfaces import cli as _cli
from src.components.interfaces.ui_backend import UiBackend
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
def ui(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = _cli._DEFAULT_CONFIG,
) -> None:
    """Launch a web-based desktop UI for interactive translation + audit trace.

    Tab "Translate": source text box, direction + model dropdowns, Translate
    button, and an output panel with the translation plus a provenance block
    (glossary hits, retrieved chunks, audit verdict).

    Tab "Audit Trace": the full revision history (each draft + critique) for
    the last run (task 4.2.2).
    """
    cfg = _cli.load_or_exit(config_path)

    adapters = _cli._construct_adapters(cfg)

    if cfg.ui.backend == "tk":
        from src.components.interfaces.tk_ui import launch_ui
        typer.secho("Launching Tkinter desktop UI…", fg=typer.colors.CYAN)
    else:
        from src.components.interfaces.web_ui import launch_ui
        typer.secho("Launching web desktop UI…", fg=typer.colors.CYAN)

    backend: UiBackend = launch_ui
    backend(cfg, adapters)
