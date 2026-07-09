"""Pydantic configuration models for the Iraqi Legal Translation Agent.

Holds the sub-models (``PathsConfig``, ``ChromaConfig``) used by
:class:`src.config.config.AppConfig`. Splitting the models into their own
module keeps :mod:`src.config.config` focused on loading/validation logic.
"""
from __future__ import annotations

from pydantic import BaseModel


class PathsConfig(BaseModel):
    """Filesystem paths, all relative to the project root."""

    data_dir: str = "data"
    corpus_dir: str = "data/corpus"
    glossary_dir: str = "data/glossary"
    raw_dir: str = "data/raw"
    db_dir: str = "db"
    glossary_db: str = "db/glossary.sqlite"
    chroma_dir: str = "db/chroma"


class ChromaConfig(BaseModel):
    """ChromaDB HNSW index tuning for a small corpus on low-RAM hardware."""

    space: str = "cosine"
    hnsw_M: int = 8
    construction_ef: int = 64
    search_ef: int = 32
