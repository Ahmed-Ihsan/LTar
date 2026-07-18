"""Path containment validation — rejects path traversal outside a root."""

from __future__ import annotations

from pathlib import Path

from src.components.translation_pipeline.exceptions import PathContainmentError


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
