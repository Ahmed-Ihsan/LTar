"""Pydantic schemas for validating JSONL batch and parallel-pair records."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
