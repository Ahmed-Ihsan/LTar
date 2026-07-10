"""Pydantic configuration models for the Iraqi Legal Translation Agent.

Holds the sub-models (``PathsConfig``, ``ChromaConfig``) used by
:class:`src.config.config.AppConfig`. Splitting the models into their own
module keeps :mod:`src.config.config` focused on loading/validation logic.
"""
from __future__ import annotations

from pydantic import BaseModel, field_validator


class PathsConfig(BaseModel):
    """Filesystem paths, all relative to the project root."""

    data_dir: str = "data"
    corpus_dir: str = "data/corpus"
    glossary_dir: str = "data/glossary"
    raw_dir: str = "data/raw"
    db_dir: str = "db"
    glossary_db: str = "db/glossary.sqlite"
    chroma_dir: str = "db/chroma"

    @field_validator("data_dir", "corpus_dir", "glossary_dir", "raw_dir",
                     "db_dir", "glossary_db", "chroma_dir")
    @classmethod
    def _non_empty_path(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("path must not be empty or whitespace-only")
        return v


class ChromaConfig(BaseModel):
    """ChromaDB HNSW index tuning for a small corpus on low-RAM hardware."""

    space: str = "cosine"
    hnsw_M: int = 8
    construction_ef: int = 64
    search_ef: int = 32

    @field_validator("hnsw_M")
    @classmethod
    def _hnsw_m_min(cls, v: int) -> int:
        if v < 2:
            raise ValueError(f"hnsw_M must be >= 2, got {v}")
        return v

    @field_validator("construction_ef", "search_ef")
    @classmethod
    def _ef_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"ef must be >= 1, got {v}")
        return v
