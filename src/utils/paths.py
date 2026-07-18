"""Path containment validation + config-relative path resolution."""

from __future__ import annotations

from pathlib import Path

from src.components.translation_pipeline.exceptions import PathContainmentError


def resolve_path(path_str: str, *, cfg: object) -> Path:
    """Resolve a config-relative path against the project root.

    Args:
        path_str: A relative path string (e.g. ``"logs"``, ``"db/tm.sqlite"``).
        cfg: The :class:`AppConfig` (used only to find the project root; the
            root is the parent of the ``src`` package).

    Returns:
        The resolved absolute path.
    """
    # Project root = parent of the ``src`` package (4 levels up from this file:
    # src/utils/paths.py → src/utils/ → src/ → <root>)
    root = Path(__file__).resolve().parent.parent.parent
    return root / path_str


def validate_path_in_root(path: Path, root: Path) -> Path:
    """Resolve *path* and assert it is inside *root*.

    Args:
        path: The path to validate (may be relative or absolute).
        root: The root directory that *path* must be inside.

    Returns:
        The resolved absolute path.

    Raises:
        PathContainmentError: If the resolved path is not inside *root*.
    """
    resolved = path.resolve()
    root_resolved = root.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise PathContainmentError(
            f"Path '{resolved}' is outside the allowed root '{root_resolved}'"
        )
    return resolved
