"""Tests for incremental ChromaDB addition (add_chunks_to_collection)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion import Chunk
from src.retrieval import (
    add_chunks_to_collection,
    build_chroma_collection,
    query_chroma,
)

pytestmark = pytest.mark.integration


def _base_chunks() -> list[Chunk]:
    """Original corpus chunks (simulating Iraqi-law corpus)."""
    return [
        Chunk(
            chunk_id="civil_code_1_0",
            text="Article 1 of the Iraqi Civil Code defines contracts.",
            law="Civil Code", article="1", lang="en",
            law_slug="civil_code", chunk_idx=0,
            char_start=0, char_end=55,
        ),
    ]


def _extra_chunks() -> list[Chunk]:
    """Additional chunks from MultiUN import."""
    return [
        Chunk(
            chunk_id="multiun_000001",
            text="The Court of Cassation is the highest judicial body.",
            law="UN parallel corpus (MultiUN)", article="", lang="ar",
            law_slug="multiun", chunk_idx=0,
            char_start=0, char_end=52,
        ),
        Chunk(
            chunk_id="multiun_000002",
            text="The contract is the law of the contracting parties.",
            law="UN parallel corpus (MultiUN)", article="", lang="ar",
            law_slug="multiun", chunk_idx=1,
            char_start=0, char_end=53,
        ),
    ]


def test_add_chunks_increments_count(tmp_path: Path, mock_embedder) -> None:
    """build creates 1 chunk, add_chunks adds 2 more → total 3."""
    persist_dir: Path = tmp_path / "chroma"
    build_chroma_collection(_base_chunks(), persist_dir, embedder=mock_embedder)

    added: int = add_chunks_to_collection(
        _extra_chunks(), persist_dir, embedder=mock_embedder
    )
    assert added == 2

    # Query should find both base and extra chunks.
    results = query_chroma(
        "contract", n_results=5, persist_dir=persist_dir, embedder=mock_embedder
    )
    assert len(results) == 3


def test_add_chunks_preserves_existing(tmp_path: Path, mock_embedder) -> None:
    """add_chunks must not drop existing chunks (non-destructive)."""
    persist_dir: Path = tmp_path / "chroma"
    build_chroma_collection(_base_chunks(), persist_dir, embedder=mock_embedder)

    add_chunks_to_collection(_extra_chunks(), persist_dir, embedder=mock_embedder)

    # The original chunk should still be retrievable.
    results = query_chroma(
        "Iraqi Civil Code defines contracts",
        n_results=5, persist_dir=persist_dir, embedder=mock_embedder
    )
    ids = [r.chunk_id for r in results]
    assert "civil_code_1_0" in ids


def test_add_empty_chunks_is_noop(tmp_path: Path, mock_embedder) -> None:
    """Adding zero chunks should return 0 and not error."""
    persist_dir: Path = tmp_path / "chroma"
    build_chroma_collection(_base_chunks(), persist_dir, embedder=mock_embedder)
    added: int = add_chunks_to_collection([], persist_dir, embedder=mock_embedder)
    assert added == 0
