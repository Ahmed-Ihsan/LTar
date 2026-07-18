"""Structured logging setup for the Iraqi Legal Translation Agent.

Single responsibility: configure the root logger with a stderr
``StreamHandler`` and an optional ``FileHandler`` (``<log_dir>/app.log``).
Idempotent — repeated calls do not add duplicate handlers.

Called once at entry points (CLI ``app.callback``, ``web_ui.launch_ui``,
``tk_ui.launch_ui``) before any component runs.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_LOG_FORMAT: str = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(
    level: str = "INFO",
    log_dir: Path | None = None,
) -> None:
    """Configure the root logger with stderr + optional file handler.

    Idempotent: if the root logger already has a handler tagged with
    ``_iraqi_translate``, handlers are not re-added (prevents duplicate
    output on repeated calls).

    Args:
        level: Logging level name (``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
            ``"ERROR"``, ``"CRITICAL"``). Defaults to ``"INFO"``.
        log_dir: If provided, a ``FileHandler`` writes to
            ``<log_dir>/app.log``. The directory is created if missing.
    """
    root: logging.Logger = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Idempotency: check if we already configured the root logger.
    has_stream: bool = False
    has_file: bool = False
    for h in root.handlers:
        if getattr(h, "_iraqi_translate", None) == "stream":
            has_stream = True
        elif getattr(h, "_iraqi_translate", None) == "file":
            has_file = True

    formatter: logging.Formatter = logging.Formatter(_LOG_FORMAT)

    if not has_stream:
        stream_handler: logging.StreamHandler[Any] = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler._iraqi_translate = "stream"  # type: ignore[attr-defined]
        root.addHandler(stream_handler)

    if log_dir is not None and not has_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler: logging.FileHandler = logging.FileHandler(
            log_dir / "app.log", encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler._iraqi_translate = "file"  # type: ignore[attr-defined]
        root.addHandler(file_handler)
