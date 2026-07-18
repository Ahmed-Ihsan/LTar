"""Pydantic schemas for validating JSONL batch and parallel-pair records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class BatchRecord(BaseModel):
    """A single line in a JSONL batch translation file."""

    input: str = Field(..., max_length=10000, description="Source text to translate")
    direction: Literal["ar-en", "en-ar"] = Field(
        ..., description="Translation direction"
    )


class ParallelPair(BaseModel):
    """A single line in a JSONL parallel-pair (TM build) file."""

    source_sentence: str = Field(..., max_length=10000, description="Arabic source")
    target_sentence: str = Field(..., max_length=10000, description="English target")
    source_lang: str = Field(default="ar", description="Source language code")
    target_lang: str = Field(default="en", description="Target language code")


def load_parallel_pairs(path: Path, max_pairs: int | None = None) -> list[ParallelPair]:
    """Load and validate parallel-pair records from a JSONL file.

    Each line must be a JSON object matching :class:`ParallelPair`.

    Args:
        path: Path to the ``.jsonl`` file.
        max_pairs: Optional cap on the number of pairs to load.

    Returns:
        A list of validated :class:`ParallelPair` records.

    Raises:
        ValueError: If a line is not valid JSON or fails schema validation.
        OSError: If the file cannot be read.
    """
    pairs: list[ParallelPair] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {e}") from e
            try:
                pairs.append(ParallelPair.model_validate(obj))
            except ValidationError as e:
                raise ValueError(f"{path}:{lineno}: schema validation failed: {e}") from e
            if max_pairs is not None and len(pairs) >= max_pairs:
                break
    return pairs
