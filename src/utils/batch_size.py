"""Batch-size validation helper."""
from __future__ import annotations


def validate_batch_size(n: int) -> int:
    """Validate that *n* is a positive integer suitable for batching.

    Args:
        n: The batch size to validate.

    Returns:
        *n* unchanged if valid.

    Raises:
        ValueError: If *n* <= 0.
    """
    if n <= 0:
        raise ValueError(f"batch_size must be positive, got {n}")
    return n


__all__ = ["validate_batch_size"]
