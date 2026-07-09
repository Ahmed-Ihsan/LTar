"""Domain models for the infrastructure component.

Co-locates the runtime-adapter dataclasses. ``MemoryInfo`` is the system
memory snapshot used by the RAM guard and the ``doctor`` command.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MemoryInfo:
    """System memory snapshot in bytes."""

    total_bytes: int
    available_bytes: int
