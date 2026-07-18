"""``doctor`` command — environment diagnostics (task 1.3.3).

Moved from ``cli.py`` (Change 5 task 4.2). The check helpers live in
:mod:`src.components.interfaces.diagnostics`; this module is the thin Typer
command that coordinates them and renders the summary.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import ollama
import typer

from src.components.interfaces import cli as _cli
from src.components.interfaces.diagnostics import (
    _check_chroma_dir,
    _check_glossary_db,
    _check_models_present,
    _check_ollama_reachable,
    _check_ram_headroom,
    _render_result,
)
from src.components.interfaces.models import CheckResult
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
def doctor(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = _cli._DEFAULT_CONFIG,
) -> None:
    """Run environment diagnostics: Ollama, models, DB stores, RAM headroom."""
    cfg = _cli.load_or_exit(config_path)
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
        ollama_failed: bool = any(
            not r.ok and "ollama" in r.name.lower() for r in checks
        )
        raise typer.Exit(code=2 if ollama_failed else 1)
