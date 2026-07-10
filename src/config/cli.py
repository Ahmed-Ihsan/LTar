"""Config CLI — Typer app and ``load`` command (extracted from config.py — SRP).

Keeps the config-loading logic in ``config.py`` and the CLI presentation here.
Run ``python -m src.config.cli load`` to print the parsed configuration.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.config.config import DEFAULT_CONFIG_PATH, AppConfig, ConfigError, load_config

app = typer.Typer(
    add_completion=False,
    rich_markup_mode=None,  # plain Click help; rich panels break on piped Windows stdout
    help="Configuration utilities.",
)


@app.callback()
def _config_main(ctx: typer.Context) -> None:
    """Configuration utilities for loading and validating config.yaml."""
    _ = ctx


@app.command()
def load(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """Load and print the parsed configuration as JSON."""
    try:
        cfg: AppConfig = load_config(config_path)
    except ConfigError as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    typer.echo(cfg.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
