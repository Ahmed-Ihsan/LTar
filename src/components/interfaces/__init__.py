"""Interfaces component — CLI, HITL, web/Tkinter UI, and MCP server.

Re-exports the CLI app and HITL seam so callers can use the short form::

    from src.components.interfaces import app, human_review

The UI modules (``web_ui``, ``tk_ui``) and ``mcp_server`` are imported
explicitly by callers that need them — they pull in heavy GUI / MCP
dependencies not required for the core CLI path.

Imports are lazy (PEP 562 ``__getattr__``) to avoid circular imports between
component ``__init__`` files.
"""
import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "Adapters": f"{__name__}.models",
    "CheckResult": f"{__name__}.models",
    "KnowledgeAdapters": f"{__name__}.models",
    "LLMAdapters": f"{__name__}.models",
    "UiTranslationResult": f"{__name__}.models",
    "HumanReviewer": f"{__name__}.hitl",
    "human_review": f"{__name__}.hitl",
    # config_loader (extracted from cli.py — SRP)
    "config_loader": f"{__name__}.config_loader",
    "load_or_exit": f"{__name__}.config_loader",
    # diagnostics (extracted from cli.py — SRP)
    "diagnostics": f"{__name__}.diagnostics",
    # orchestration (extracted from cli.py — SRP)
    "orchestration": f"{__name__}.orchestration",
    # tm_commands (extracted from cli.py — SRP)
    "tm_commands": f"{__name__}.tm_commands",
    # web_frontend (extracted from web_ui.py — SRP)
    "web_frontend": f"{__name__}.web_frontend",
    # cli — app, main callback, and orchestration re-exports stay in cli.py;
    # per-command modules live under .commands (Change 5 task 4).
    "app": f"{__name__}.cli",
    "batch": f"{__name__}.commands.batch",
    "doctor": f"{__name__}.commands.doctor",
    "ingest": f"{__name__}.commands.ingest",
    "main": f"{__name__}.cli",
    "run_translation": f"{__name__}.cli",
    "run_translation_streamed": f"{__name__}.cli",
    "tm_add_parallel": f"{__name__}.tm_commands",
    "tm_build": f"{__name__}.tm_commands",
    "tm_build_parallel": f"{__name__}.tm_commands",
    "translate": f"{__name__}.commands.translate",
    "ui": f"{__name__}.commands.ui",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name])
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY)
