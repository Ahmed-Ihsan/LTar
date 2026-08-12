"""Command-line interface for the Iraqi Legal Translation Agent.

Entry point: ``python -m src.app`` or the ``iraqi-translate`` console script.

This module is the thin composition root that owns the Typer ``app``, the
shared adapter-construction helpers, and re-exports of orchestration /
diagnostics symbols used by tests and UI modules. Each CLI command lives in
its own module under :mod:`src.components.interfaces.commands` and registers
itself on ``app`` at import time (engineering-principles §1.1, §3.6).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from src.components.infrastructure.run_logging import RunLogger
from src.components.interfaces.config_loader import load_or_exit  # noqa: F401
from src.components.interfaces.diagnostics import (
    _list_ollama_models,  # noqa: F401  — re-exported for web_ui / tk_ui
)
from src.components.interfaces.models import Adapters
from src.components.interfaces.orchestration import (
    RevisionStep,  # noqa: F401  — re-exported for tests / UI
    _audit_trace_markdown,  # noqa: F401  — re-exported for tests / UI
    _initial_state,  # noqa: F401  — re-exported for tests
    _process_batch,  # noqa: F401  — re-exported for tests / command modules
    _provenance_markdown,  # noqa: F401  — re-exported for tests / UI
    _render_provenance,  # noqa: F401  — re-exported for tests / command modules
    _translate_for_ui,  # noqa: F401  — re-exported for tests / UI
    run_translation,  # noqa: F401  — re-exported for tests / command modules
    run_translation_streamed,  # noqa: F401  — re-exported for tests / UI
)
from src.config import AppConfig
from src.utils.paths import (
    validate_path_in_root,  # noqa: F401  — re-exported for command modules / patching
)

if TYPE_CHECKING:
    from src.components.knowledge_sources.tm import TranslationMemory

__all__ = [
    "_audit_trace_markdown",
    "_construct_adapters",
    "_DEFAULT_CONFIG",
    "_initial_state",
    "_list_ollama_models",
    "_new_run_logger",
    "_process_batch",
    "_project_root",
    "_provenance_markdown",
    "_render_provenance",
    "_resolve_path",
    "_translate_for_ui",
    "app",
    "load_or_exit",
    "main",
    "RevisionStep",
    "run_translation",
    "run_translation_streamed",
    "validate_path_in_root",
]

app = typer.Typer(
    add_completion=False,
    rich_markup_mode=None,  # plain Click help; rich panels break on piped Windows stdout
    help="Iraqi Legal Translation Agent — local offline Arabic<->English "
         "translation of Iraqi legal texts.",
)

_DEFAULT_CONFIG: Path = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml"


def _project_root(cfg: AppConfig) -> Path:
    """Return the project root (parent of the ``src`` package)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _resolve_path(cfg: AppConfig, rel: str) -> Path:
    """Resolve a config-relative path against the project root.

    Thin delegate to :func:`src.utils.paths.resolve_path` (Change 5 task 1.1).
    Kept for backwards compatibility with callers that import ``_resolve_path``
    from this module.
    """
    from src.utils.paths import resolve_path
    return resolve_path(rel, cfg=cfg)


def _new_run_logger(cfg: AppConfig) -> RunLogger:
    """Build a :class:`RunLogger` writing to ``<project_root>/logs`` (task 4.3.1).

    One JSONL file per run (``run_<timestamp>.jsonl``). The handle is flushed
    after every node line, so a crash mid-run still leaves the preceding node
    lines on disk; the OS reclaims the handle when the CLI process exits.
    """
    return RunLogger(log_dir=_resolve_path(cfg, "logs"))


def _new_tm(cfg: AppConfig) -> TranslationMemory | None:
    """Construct a :class:`TranslationMemory` when TM is enabled (task 7).

    Returns ``None`` when ``cfg.tm_enabled`` is False so the ``tm_lookup``
    node becomes a no-op pass-through. The DB path is resolved against the
    project root (single source of truth: ``cfg.tm_db``).
    """
    if not cfg.tm_enabled:
        return None
    from src.components.knowledge_sources.tm import TranslationMemory

    return TranslationMemory(
        db_path=str(_resolve_path(cfg, cfg.tm_db)),
        similarity_threshold=cfg.tm_similarity_threshold,
    )


def _construct_adapters(cfg: AppConfig) -> Adapters:
    """Construct the concrete LLM/embedding/ChromaDB/Glossary/TM adapters (DI seam).

    The single place concrete adapters are built (engineering-principles
    §3.6). Branches on ``cfg.llm_backend``:

    - ``"ollama"`` (default) and ``"llamacpp"``: construct
      :class:`OllamaEngineAdapter` + :class:`Embedder` exactly as before
      this change (no behavioral regression).
    - ``"gemini"``: construct a single :class:`GeminiEngineAdapter` and use
      it for **both** the ``llm`` and ``embedder`` fields of
      :class:`Adapters` (the Gemini backend serves LLM and embeddings from
      the same provider under one API key — design D1). The
      ``google-genai`` SDK is lazily imported inside ``gemini.py``, so the
      Ollama path never imports it.

    Raises :class:`typer.Exit` (code 1) on a glossary load failure or when
    ``llm_backend == "gemini"`` and ``cfg.gemini_api_key`` is ``None``
    (defensive — ``load_config`` already rejects this case).
    """
    from src.components.knowledge_sources.glossary import load_glossary_index

    persist_dir: str = str(_resolve_path(cfg, cfg.paths.chroma_dir))

    llm: object
    embedder: object
    if cfg.llm_backend == "gemini":
        # Lazy import so the Ollama path never imports google-genai.
        from src.components.infrastructure.gemini import GeminiEngineAdapter

        api_key: str | None = cfg.gemini_api_key
        if not api_key:
            typer.secho(
                "GEMINI_API_KEY environment variable not set "
                "(required when llm_backend='gemini').",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(code=1)
        gemini = GeminiEngineAdapter(
            model=cfg.gemini_model,
            embed_model=cfg.gemini_embed_model,
            api_key=api_key,
            timeout=cfg.gemini_timeout,
            rpm=cfg.gemini_rpm,
        )
        llm = gemini
        embedder = gemini
    else:
        from src.components.infrastructure.embeddings import Embedder
        from src.components.infrastructure.llm import OllamaEngineAdapter

        llm = OllamaEngineAdapter(
            model=cfg.llm_model, host=cfg.ollama_host, num_ctx=cfg.ollama_num_ctx,
        )
        embedder = Embedder(model=cfg.embed_model, host=cfg.ollama_host)

    try:
        glossary_index = load_glossary_index(
            _resolve_path(cfg, cfg.paths.glossary_db)
        )
    except Exception as e:
        typer.secho(
            f"glossary index error: {e}", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1) from e

    return Adapters(
        llm=llm,
        embedder=embedder,
        glossary_index=glossary_index,
        persist_dir=persist_dir,
        tm=_new_tm(cfg),
    )


@app.callback()
def main(
    ctx: typer.Context,
) -> None:
    """Iraqi Legal Translation Agent CLI."""
    _ = ctx
    from src.utils.logging_setup import configure_logging

    configure_logging()


# ---------------------------------------------------------------------------
# Register all commands from the commands/ subpackage.
# Importing the package triggers each command module to register itself on
# ``app`` via ``app.command()`` (engineering-principles §3.6 — cli is the
# single composition root).
# ---------------------------------------------------------------------------
from src.components.interfaces import commands as _commands  # noqa: E402, F401

if __name__ == "__main__":
    app()
