"""Config loading helper for CLI commands (DRY).

Extracted from ``cli.py`` so every command uses the same load-or-exit pattern
instead of duplicating try/except/load_config (engineering-principles §2.1).
"""
from __future__ import annotations

from pathlib import Path

import typer

from src.config import AppConfig, load_config


def load_or_exit(path: Path | None = None) -> AppConfig:
    """Load config from ``path`` or exit with a Typer error.

    Wraps :func:`load_config` with the standard error handling used by every
    CLI command: on failure, print the error in red and exit with code 1.
    """
    try:
        return load_config(path) if path is not None else load_config()
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
