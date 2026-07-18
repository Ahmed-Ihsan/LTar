"""UI backend protocol — config-driven selection between web and Tkinter UIs."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.components.interfaces.models import Adapters
from src.config.config import AppConfig


@runtime_checkable
class UiBackend(Protocol):
    """Protocol for UI launchers (web_ui.launch_ui, tk_ui.launch_ui).

    A :class:`UiBackend` is a callable that takes ``(cfg, adapters)`` and
    launches the desktop UI, blocking until the user closes the window.
    """

    def __call__(self, cfg: AppConfig, adapters: Adapters) -> None:
        """Launch the UI with the given config and adapters.

        Args:
            cfg: The application configuration.
            adapters: The wired adapter instances (LLM, embedder, glossary, etc.).
        """
        ...


__all__ = ["UiBackend"]
