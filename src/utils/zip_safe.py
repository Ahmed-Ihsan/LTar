"""Zip-slip validation — rejects unsafe zip entry paths."""

from __future__ import annotations

from src.components.translation_pipeline.exceptions import InputValidationError


def validate_zip_path(name: str) -> str:
    """Validate a zip entry filename against zip-slip and path traversal.

    Args:
        name: The filename inside a zip archive entry.

    Returns:
        The validated filename.

    Raises:
        InputValidationError: If the name is absolute, contains ``..``
            segments, or uses backslash path separators.
    """
    if not name:
        raise InputValidationError("Zip entry has an empty filename")
    if name.startswith("/"):
        raise InputValidationError(f"Zip entry has an absolute path: '{name}'")
    if "\\" in name:
        raise InputValidationError(
            f"Zip entry contains backslash path separator: '{name}'"
        )
    parts = name.split("/")
    if ".." in parts:
        raise InputValidationError(
            f"Zip entry contains parent-directory traversal: '{name}'"
        )
    return name
