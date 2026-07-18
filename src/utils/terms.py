"""Glossary Term helpers."""
from __future__ import annotations

import dataclasses

from src.components.knowledge_sources.models import Term


def create_term_with_order(term: Term, file_order: int) -> Term:
    """Create a copy of *term* with an updated ``file_order``.

    Uses :func:`dataclasses.replace` so the frozen dataclass is not mutated.

    Args:
        term: The source :class:`Term`.
        file_order: The new ``file_order`` value.

    Returns:
        A new :class:`Term` with ``file_order`` set to *file_order*.
    """
    return dataclasses.replace(term, file_order=file_order)


__all__ = ["create_term_with_order"]
