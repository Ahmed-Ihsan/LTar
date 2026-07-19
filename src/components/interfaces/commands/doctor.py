"""``doctor`` command — environment diagnostics (task 1.3.3).

Moved from ``cli.py`` (Change 5 task 4.2). The check helpers live in
:mod:`src.components.interfaces.diagnostics`; this module is the thin Typer
command that coordinates them and renders the summary.

The check set branches on ``cfg.llm_backend`` (add-gemini-api-backend):
when ``"gemini"`` is selected, the cloud-backend checks (API-key presence
+ Gemini API reachability + backend-independent RAM headroom) run instead
of the Ollama reachability / local-model-presence / LLM-RAM-budget
checks. ChromaDB / glossary / TM checks always run (backend-independent).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import ollama
import typer

from src.components.interfaces import cli as _cli
from src.components.interfaces.diagnostics import (
    _check_chroma_dir,
    _check_gemini_api_key,
    _check_gemini_reachable,
    _check_glossary_db,
    _check_models_present,
    _check_ollama_reachable,
    _check_ram_headroom,
    _check_ram_headroom_gemini,
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
    """Run environment diagnostics for the configured backend.

    When ``llm_backend == "ollama"`` (default) or ``"llamacpp"``: checks
    Ollama daemon reachability, required local models, ChromaDB directory,
    glossary SQLite, and the full RAM-headroom estimate (LLM weight budget
    included).

    When ``llm_backend == "gemini"``: checks the Gemini API key presence,
    Gemini API reachability (list-models ping), ChromaDB directory, glossary
    SQLite, and a reduced RAM-headroom estimate (cloud LLM — no local
    weights). Skips the Ollama-reachability / local-model-presence checks.
    """
    cfg = _cli.load_or_exit(config_path)
    typer.secho("doctor: running environment checks", fg=typer.colors.CYAN)

    if cfg.llm_backend == "gemini":
        checks: list[CheckResult] = [
            _check_gemini_api_key(cfg),
            _check_gemini_reachable(cfg),
            _check_chroma_dir(cfg),
            _check_glossary_db(cfg),
            _check_ram_headroom_gemini(cfg),
        ]
    else:
        client: ollama.Client = ollama.Client(host=cfg.ollama_host)
        checks = [
            _check_ollama_reachable(client),
            _check_models_present(client, cfg),
            _check_chroma_dir(cfg),
            _check_glossary_db(cfg),
            _check_ram_headroom(client, cfg),
        ]

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
        # A failed backend-connectivity check (Ollama or Gemini) exits 2;
        # any other failed check exits 1.
        backend_failed: bool = any(
            not r.ok
            and (
                "ollama" in r.name.lower()
                or "gemini" in r.name.lower()
            )
            for r in checks
        )
        raise typer.Exit(code=2 if backend_failed else 1)
