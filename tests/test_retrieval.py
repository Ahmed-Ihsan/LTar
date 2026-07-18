"""Integration tests for ChromaDB retrieval (task 2.3.2).

Uses a real ChromaDB ``PersistentClient`` in a ``tmp_path`` directory with a
deterministic mock embedder (testing-verification skill §2.2 / §3.2). No
Ollama daemon is required. The real-Ollama path is marked ``slow``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.components.knowledge_sources.ingestion import Chunk
from src.components.knowledge_sources.retrieval import (
    build_chroma_collection,
    query_chroma,
)
from src.components.translation_pipeline.exceptions import ChromaDBCorruptionError

pytestmark = pytest.mark.integration


def _make_chunks(n: int = 10) -> list[Chunk]:
    """Build ``n`` deterministic chunks with a distinct target article."""
    topics: list[str] = [
        "contract of sale",
        "lease agreement",
        "mortgage of property",
        "commercial partnership",
        "penalty for theft",
        "civil procedure jurisdiction",
        "appeal deadline",
        "bankruptcy",
        "inheritance share",
        "custody of minors",
    ]
    chunks: list[Chunk] = []
    for i in range(n):
        topic: str = topics[i % len(topics)]
        text: str = (
            f"Article {i + 1} of the Iraqi Civil Code governs the {topic}. "
            f"This provision sets out the obligations of the parties."
        )
        if i == 4:
            text = (
                "Article 5 of the Iraqi Civil Code governs the contract of "
                "sale, defining the transfer of ownership in exchange for a "
                "price and the warranty against latent defects."
            )
        chunks.append(
            Chunk(
                chunk_id=f"civil_code_en_{i + 1}_0",
                text=text,
                law="Civil Code",
                article=str(i + 1),
                lang="en",
                law_slug="civil_code",
                chunk_idx=0,
                char_start=0,
                char_end=len(text),
            )
        )
    return chunks


@pytest.fixture
def populated_store(tmp_path: Path, mock_embedder) -> Path:
    """Build a ChromaDB store with 10 chunks in a tmp_path directory."""
    persist_dir: Path = tmp_path / "chroma"
    chunks: list[Chunk] = _make_chunks(10)
    n: int = build_chroma_collection(
        chunks, persist_dir, embedder=mock_embedder
    )
    assert n == 10
    return persist_dir


class TestRetrieval:
    def test_build_returns_chunk_count(self, tmp_path: Path, mock_embedder) -> None:
        chunks: list[Chunk] = _make_chunks(5)
        n: int = build_chroma_collection(
            chunks, tmp_path / "chroma", embedder=mock_embedder
        )
        assert n == 5

    def test_top1_returns_relevant_chunk(self, populated_store: Path, mock_embedder) -> None:
        # The mock embedder is hash-based (no semantic similarity), so querying
        # with the exact text of the target chunk yields distance 0 (a perfect
        # self-match), verifying the store round-trips stored vectors correctly.
        target_text: str = (
            "Article 5 of the Iraqi Civil Code governs the contract of "
            "sale, defining the transfer of ownership in exchange for a "
            "price and the warranty against latent defects."
        )
        results = query_chroma(
            target_text,
            n_results=3,
            persist_dir=populated_store,
            embedder=mock_embedder,
        )
        assert len(results) > 0
        assert results[0].chunk_id == "civil_code_en_5_0"
        assert results[0].article == "5"
        assert results[0].distance == pytest.approx(0.0, abs=1e-6)

    def test_empty_query_returns_empty(self, populated_store: Path, mock_embedder) -> None:
        results = query_chroma(
            "", n_results=5, persist_dir=populated_store, embedder=mock_embedder
        )
        assert results == []

    def test_n_results_capped_by_collection_size(
        self, populated_store: Path, mock_embedder
    ) -> None:
        results = query_chroma(
            "contract", n_results=100, persist_dir=populated_store,
            embedder=mock_embedder,
        )
        assert len(results) <= 10

    def test_where_filter_restricts_article(
        self, populated_store: Path, mock_embedder
    ) -> None:
        results = query_chroma(
            "contract",
            n_results=10,
            where={"article": "5"},
            persist_dir=populated_store,
            embedder=mock_embedder,
        )
        assert all(r.article == "5" for r in results)

    def test_query_missing_dir_raises_corruption_error(self, tmp_path: Path, mock_embedder) -> None:
        with pytest.raises(ChromaDBCorruptionError):
            query_chroma(
                "x", n_results=3, persist_dir=tmp_path / "nonexistent",
                embedder=mock_embedder,
            )

    def test_context_chunk_has_provenance_fields(
        self, populated_store: Path, mock_embedder
    ) -> None:
        results = query_chroma(
            "contract", n_results=1, persist_dir=populated_store,
            embedder=mock_embedder,
        )
        chunk = results[0]
        assert chunk.chunk_id != ""
        assert chunk.text != ""
        assert chunk.law == "Civil Code"
        assert chunk.lang == "en"
        assert chunk.law_slug == "civil_code"
        assert isinstance(chunk.distance, float)

    def test_rebuild_is_idempotent_count(
        self, tmp_path: Path, mock_embedder
    ) -> None:
        """Re-building the same chunks produces the same count (no dupes)."""
        persist_dir: Path = tmp_path / "chroma"
        chunks: list[Chunk] = _make_chunks(10)
        n1: int = build_chroma_collection(chunks, persist_dir, embedder=mock_embedder)
        n2: int = build_chroma_collection(chunks, persist_dir, embedder=mock_embedder)
        assert n1 == n2 == 10


@pytest.mark.slow
class TestRealOllamaRetrieval:
    """Real Ollama embedding + ChromaDB — requires a running daemon.

    Excluded from default CI (marked ``slow``).
    """

    def test_50_chunks_top1_is_correct_article(self, tmp_path: Path) -> None:
        from src.components.infrastructure.embeddings import Embedder

        chunks: list[Chunk] = []
        topics: list[str] = [
            "contract of sale", "lease agreement", "mortgage",
            "commercial partnership", "penalty for theft",
        ]
        for i in range(50):
            topic = topics[i % len(topics)]
            text = (
                f"Article {i + 1} of the Iraqi Civil Code governs the "
                f"{topic}. This provision sets out obligations of parties."
            )
            if i == 24:
                text = (
                    "Article 25 of the Iraqi Civil Code governs the commercial "
                    "partnership between merchants, defining profit sharing, "
                    "liability of partners, and dissolution procedures."
                )
            chunks.append(
                Chunk(
                    chunk_id=f"civil_code_en_{i + 1}_0",
                    text=text, law="Civil Code", article=str(i + 1),
                    lang="en", law_slug="civil_code", chunk_idx=0,
                    char_start=0, char_end=len(text),
                )
            )
        embedder = Embedder(model="nomic-embed-text", host="http://localhost:11434")
        n: int = build_chroma_collection(
            chunks, tmp_path / "chroma", embedder=embedder
        )
        assert n == 50
        results = query_chroma(
            "commercial partnership between merchants, profit sharing",
            n_results=8,
            persist_dir=tmp_path / "chroma",
            embedder=embedder,
        )
        assert results[0].chunk_id == "civil_code_en_25_0"


# ---------------------------------------------------------------------------
# Task 4.5 — context manager + exception-safe cleanup tests
# ---------------------------------------------------------------------------


class TestChromaStoreContextManager:
    def test_context_manager_closes_handles(
        self, mock_embedder, config, tmp_path: Path
    ) -> None:
        """Using ``with ChromaStore(...)`` closes handles on exit."""
        from src.components.knowledge_sources.retrieval import ChromaStore

        store = ChromaStore(
            tmp_path / "chroma", embedder=mock_embedder, cfg=config
        )
        chunks = _make_chunks(3)
        with store:
            store.build(chunks)
        # After context exit, handles are closed — _client and _collection are None.
        assert store._client is None
        assert store._collection is None

    def test_closes_handles_on_exception(
        self, mock_embedder, config, tmp_path: Path
    ) -> None:
        """If an exception occurs during ``_write_collection``, handles are
        released via the ``except`` block in ``_write_collection``."""
        from src.components.knowledge_sources.retrieval import ChromaStore

        store = ChromaStore(
            tmp_path / "chroma", embedder=mock_embedder, cfg=config
        )
        chunks = _make_chunks(3)

        # Mock embed_batch to raise on the second batch.
        original_embed_batch = mock_embedder.embed_batch
        call_count = 0

        def failing_embed_batch(texts, batch_size=32):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise RuntimeError("simulated embedding failure")
            return original_embed_batch(texts, batch_size=batch_size)

        mock_embedder.embed_batch = failing_embed_batch  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="simulated"):
            store.build(chunks)

        # Handles were released by the except block in _write_collection.
        assert store._client is None
        assert store._collection is None
