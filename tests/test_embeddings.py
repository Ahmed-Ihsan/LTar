"""Unit + adapter tests for the embedding adapter (task 2.3.1).

The mock-embedder path is deterministic and runs in CI with no Ollama daemon
(testing-verification skill §3.2). The real-Ollama path is marked ``slow`` so
it is excluded from the default CI run but available for local verification.
"""
from __future__ import annotations

import pytest

from src.components.infrastructure.embeddings import EMBED_DIM, Embedder, embed_batch, embed_text
from src.components.translation_pipeline.exceptions import EmbeddingConnectionError, EmbeddingError

pytestmark = pytest.mark.adapter


class TestMockEmbedder:
    """Deterministic mock embedder (no Ollama, no network)."""

    def test_mock_embed_dim_is_768(self, mock_embedder) -> None:
        vec: list[float] = mock_embedder.embed("hello")
        assert len(vec) == EMBED_DIM

    def test_mock_embed_is_deterministic(self, mock_embedder) -> None:
        a: list[float] = mock_embedder.embed("contract of sale")
        b: list[float] = mock_embedder.embed("contract of sale")
        assert a == b

    def test_mock_embed_batch_returns_one_per_input(self, mock_embedder) -> None:
        texts: list[str] = [f"text {i}" for i in range(40)]
        vecs: list[list[float]] = mock_embedder.embed_batch(texts, batch_size=32)
        assert len(vecs) == 40
        assert all(len(v) == EMBED_DIM for v in vecs)

    def test_embed_batch_empty_returns_empty(self, mock_embedder) -> None:
        assert mock_embedder.embed_batch([], batch_size=32) == []

    def test_embed_batch_via_module_function_with_adapter(self, mock_embedder) -> None:
        vecs = embed_batch(["a", "b"], batch_size=2, embedder=mock_embedder)
        assert len(vecs) == 2
        assert all(len(v) == EMBED_DIM for v in vecs)

    def test_embed_text_via_module_function_with_adapter(self, mock_embedder) -> None:
        vec = embed_text("a", embedder=mock_embedder)
        assert len(vec) == EMBED_DIM


class TestEmbedderErrorTranslation:
    """The real :class:`Embedder` translates engine errors to domain errors."""

    def test_connection_error_becomes_embedding_connection_error(self) -> None:
        import ollama

        bad_client = ollama.Client(host="http://localhost:9999")
        embedder = Embedder(
            client=bad_client,
            model="nomic-embed-text",
            host="http://localhost:9999",
        )
        with pytest.raises(EmbeddingConnectionError):
            embedder.embed("test")

    def test_embed_batch_invalid_batch_size_raises(self, mock_embedder) -> None:
        with pytest.raises(ValueError, match="batch_size"):
            embed_batch(["a"], batch_size=0, embedder=mock_embedder)


@pytest.mark.slow
class TestRealOllamaEmbedder:
    """Real Ollama embedding — requires a running daemon with nomic-embed-text.

    Excluded from default CI (marked ``slow``). Run locally with:
    ``pytest tests/test_embeddings.py -m slow``.
    """

    def test_real_embed_32_strings_all_768_dim(self) -> None:
        texts: list[str] = [
            f"sample legal text number {i} about contract and sale"
            for i in range(16)
        ] + [f"sample arabic text {i}" for i in range(16)]
        vecs: list[list[float]] = embed_batch(texts, batch_size=32)
        assert len(vecs) == 32
        assert all(len(v) == EMBED_DIM for v in vecs)

    def test_real_embed_empty_returns_empty(self) -> None:
        embedder = Embedder()
        assert embedder.embed_batch([], batch_size=32) == []
