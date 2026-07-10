"""System memory reading and the pre-LLM-call RAM guard (task 4.3.3).

Single responsibility (per ARCHITECTURE.md / engineering-principles §1.1): read
available system RAM via stdlib only (no ``psutil`` dependency) and enforce the
RAM guard that aborts an LLM call when free RAM is below the safe threshold,
so the process stops with a clear message instead of risking an out-of-memory
kill on the 8 GB target machine (offline-architecture §1.1).

This module is the single source of truth for memory reading (DRY,
engineering-principles §2.1): the ``doctor`` command and the LLM adapter both
import :func:`read_memory_info` / :func:`check_ram_guard` from here.

Implemented in Phase 4 (task 4.3.3).
"""
from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

from src.components.infrastructure.models import MemoryInfo as MemoryInfo
from src.components.translation_pipeline.exceptions import RAMGuardError

__all__ = [
    "MemoryInfo",
    "RAM_GUARD_MIN_GB",
    "available_ram_gb",
    "check_ram_guard",
    "read_memory_info",
]

# Minimum free RAM (GB) required before an LLM call. Below this the guard
# aborts to avoid OOM (TODO 4.3.3). The 7B q5 model + KV cache can spike
# several GB during inference; 1.5 GB leaves room to finish a request already
# in flight but refuses to start one that would push the process over the edge.
RAM_GUARD_MIN_GB: float = 1.5

_GIB: float = float(1024 ** 3)


class _MEMORYSTATUSEX(ctypes.Structure):
    """Windows ``GlobalMemoryStatusEx`` structure (stdlib ctypes)."""

    _fields_: list[tuple[str, object]] = [  # type: ignore[misc,assignment]  # ctypes Structure._fields_ type is incompatible with list[tuple[str, object]]
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _read_memory_info_windows() -> MemoryInfo | None:
    """Read RAM via ``GlobalMemoryStatusEx`` on Windows (stdlib ctypes)."""
    stat: _MEMORYSTATUSEX = _MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)) == 0:
        return None
    return MemoryInfo(
        total_bytes=int(stat.ullTotalPhys),
        available_bytes=int(stat.ullAvailPhys),
    )


def _read_memory_info_linux() -> MemoryInfo | None:
    """Read RAM from ``/proc/meminfo`` on Linux (stdlib only)."""
    try:
        info: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition(":")
                info[key.strip()] = int(value.strip().split()[0]) * 1024
        return MemoryInfo(
            total_bytes=info["MemTotal"],
            available_bytes=info.get("MemAvailable", info["MemFree"]),
        )
    except (OSError, KeyError, ValueError):
        return None


# Platform reader registry (OCP — add a new platform by registering a new
# reader, not by modifying ``read_memory_info``).
_PLATFORM_READERS: dict[str, Callable[[], MemoryInfo | None]] = {
    "win32": _read_memory_info_windows,
    "linux": _read_memory_info_linux,
}


def read_memory_info() -> MemoryInfo | None:
    """Read total and available system RAM. Returns ``None`` if unsupported.

    Dispatches to the platform-specific reader via the ``_PLATFORM_READERS``
    registry. On any other platform, or if the OS call fails, returns ``None``
    so callers can degrade gracefully (the RAM guard treats ``None`` as
    "cannot measure — proceed").
    """
    reader: Callable[[], MemoryInfo | None] | None = _PLATFORM_READERS.get(sys.platform)
    return reader() if reader is not None else None


def available_ram_gb() -> float | None:
    """Return available system RAM in GiB, or ``None`` if unreadable."""
    mem: MemoryInfo | None = read_memory_info()
    if mem is None:
        return None
    return mem.available_bytes / _GIB


def check_ram_guard(min_gb: float = RAM_GUARD_MIN_GB) -> None:
    """Abort with :class:`RAMGuardError` if free RAM is below ``min_gb``.

    Called before each LLM call (task 4.3.3) so the process stops with a clear
    message rather than risking an OOM kill mid-inference. When RAM cannot be
    measured (``read_memory_info`` returns ``None``) the guard is a no-op: it
    cannot prove RAM is low, so it does not block the call (the ``doctor``
    command surfaces unreadable RAM separately).
    """
    mem: MemoryInfo | None = read_memory_info()
    if mem is None:
        return
    free_gb: float = mem.available_bytes / _GIB
    if free_gb < min_gb:
        raise RAMGuardError(
            f"Only {free_gb:.2f} GB of RAM available (minimum {min_gb:.1f} GB "
            f"required). Aborting before the LLM call to avoid an out-of-memory "
            f"crash. Close other applications and retry."
        )
