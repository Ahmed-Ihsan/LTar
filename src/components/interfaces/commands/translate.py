"""``translate`` command — translate a single text or file (task 4.1.1).

Moved from ``cli.py`` (Change 5 task 4.3).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from src.components.interfaces import cli as _cli
from src.components.interfaces.models import Adapters
from src.components.interfaces.orchestration import (
    Direction,
    StdinHumanReviewer,
    _render_provenance,
    _resolve_input,
)
from src.utils.cli_errors import handle_pipeline_errors


@_cli.app.command()
@handle_pipeline_errors
def translate(
    input_arg: Annotated[
        str,
        typer.Option("--input", help="Text to translate, or path to a file."),
    ],
    direction: Annotated[
        Direction,
        typer.Option(
            "--direction",
            help="Translation direction: ar-en, en-ar, or auto "
                 "(auto-detect by script dominance).",
        ),
    ],
    out: Annotated[
        str,
        typer.Option("--out", help="Output destination: file path or 'stdout'."),
    ] = "stdout",
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = _cli._DEFAULT_CONFIG,
) -> None:
    """Translate a single text or file and print output + provenance."""
    cfg = _cli.load_or_exit(config_path)

    root: Path = _cli._project_root(cfg)
    if Path(input_arg).exists():
        _cli.validate_path_in_root(Path(input_arg), root)
    input_text: str = _resolve_input(input_arg)

    if not input_text.strip():
        typer.secho("input text is empty.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    # Resolve `auto` direction by script dominance (once, for the whole input).
    from src.components.interfaces.orchestration import detect_direction
    effective_direction: str = (
        detect_direction(input_text) if direction is Direction.auto
        else direction.value
    )

    adapters: Adapters = _cli._construct_adapters(cfg)

    try:
        with _cli._new_run_logger(cfg) as run_logger:
            state = _cli.run_translation(
                input_text, effective_direction, cfg,
                llm=adapters.llm, embedder=adapters.embedder,
                glossary_index=adapters.glossary_index,
                persist_dir=adapters.persist_dir,
                run_logger=run_logger,
                tm=adapters.tm,
                reviewer=StdinHumanReviewer() if cfg.hitl_enabled else None,
            )
    finally:
        if adapters.tm is not None:
            adapters.tm.close()

    final_output: str = state.get("final_output") or ""
    provenance: str = _render_provenance(state)
    output_text: str = f"{final_output}\n\n{provenance}\n"

    if out.lower() == "stdout":
        typer.echo(output_text)
    else:
        Path(out).write_text(output_text, encoding="utf-8")
        typer.secho(f"output written to {out}", fg=typer.colors.GREEN)
