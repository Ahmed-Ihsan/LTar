"""Interfaces component — CLI, HITL, web/Tkinter UI, and MCP server.

Re-exports the CLI app and HITL seam so callers can use the short form::

    from src.components.interfaces import app, human_review

The UI modules (``web_ui``, ``tk_ui``) and ``mcp_server`` are imported
explicitly by callers that need them — they pull in heavy GUI / MCP
dependencies not required for the core CLI path.
"""
from src.components.interfaces.cli import (
    app,
    batch,
    doctor,
    ingest,
    main,
    run_translation,
    run_translation_streamed,
    tm_add_parallel,
    tm_build,
    tm_build_parallel,
    translate,
    ui,
)
from src.components.interfaces.hitl import HumanReviewer, human_review
from src.components.interfaces.models import (
    Adapters,
    CheckResult,
    UiTranslationResult,
)

__all__ = [
    "Adapters",
    "CheckResult",
    "HumanReviewer",
    "UiTranslationResult",
    "app",
    "batch",
    "doctor",
    "human_review",
    "ingest",
    "main",
    "run_translation",
    "run_translation_streamed",
    "tm_add_parallel",
    "tm_build",
    "tm_build_parallel",
    "translate",
    "ui",
]
