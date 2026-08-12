"""Embedding generation via the Ollama embedding model.

Single responsibility (per ARCHITECTURE.md / engineering-principles §1.1):
call the embedding model (``nomic-embed-text``) through the Ollama client to
turn text into 768-dim vectors. Bounded batches of 32 texts (RAM cap,
README.md §3 / offline-architecture §1.4). Engine-specific exceptions are
translated to domain ``EmbeddingError`` subclasses inside this adapter
(clean-code §3.2) so nodes and the CLI never see ``ollama.RequestError`` /
``httpx.ConnectError``.

This module is the single source of truth for embedding calls. ``retrieval.py``
and the ingestion CLI depend on the :class:`Embedder` adapter (or the
:func:`embed_batch` convenience function) and never call the Ollama client
directly (DRY, engineering-principles §2.1).

Implemented in Phase 2 (task 2.3.1).
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import ollama

from src.components.infrastructure.ollama_errors import translate_engine_error
from src.components.translation_pipeline.exceptions import EmbeddingError

logger = logging.getLogger(__name__)

# ``nomic-embed-text`` produces 768-dimensional vectors. Kept here as the
# single source of truth for the expected embedding dimension (DRY).
EMBED_DIM: int = 768

# Default batch size cap per README.md §3 / offline-architecture §1.4.
DEFAULT_BATCH_SIZE: int = 32


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Adapter contract for embedding engines (engineering-principles §1.5).

    Any class implementing this protocol (the real :class:`Embedder`, the
    deterministic mock used in CI) is substitutable everywhere an embedder is
    accepted (LSP, engineering-principles §1.3).
    """

    def embed(self, text: str) -> list[float]:
        """Embed a single text into a fixed-dim vector."""
        ...

    def embed_batch(
        self, texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE
    ) -> list[list[float]]:
        """Embed a list of texts in bounded batches."""
        ...


class Embedder:
    """Real Ollama embedding adapter (clean-code §2.4: manages client state).

    Wraps a single :class:`ollama.Client` instance (reused across calls —
    clean-code §4.1: never create a new httpx connection per request) and
    translates engine exceptions to the domain hierarchy.
    """

    __slots__ = ("_client", "_model", "_host", "_closed")

    def __init__(
        self,
        client: ollama.Client | None = None,
        *,
        model: str,
        host: str,
    ) -> None:
        """Build an embedder.

        ``model`` and ``host`` are mandatory (DIP — no ``load_config()``
        fallback). If ``client`` is omitted, a new :class:`ollama.Client` is
        created from ``host``. Callers resolve config values and pass them
        explicitly.
        """
        self._model: str = model
        self._host: str = host
        self._client: ollama.Client = (
            client if client is not None else ollama.Client(host=self._host)
        )
        self._closed: bool = False

    @property
    def model(self) -> str:
        """The embedding model name used for all calls."""
        return self._model

    def close(self) -> None:
        """Close the underlying Ollama client if it supports ``close()``.

        Idempotent — safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True
        client_close = getattr(self._client, "close", None)
        if callable(client_close):
            client_close()

    def __enter__(self) -> Embedder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def embed(self, text: str) -> list[float]:
        """Embed a single ``text`` into a 768-dim vector.

        Raises:
            EmbeddingConnectionError: cannot reach the Ollama daemon.
            EmbeddingTimeoutError: the request exceeded the timeout.
            EmbeddingError: any other engine failure.
        """
        return self.embed_batch([text], batch_size=1)[0]

    def embed_batch(
        self, texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE
    ) -> list[list[float]]:
        """Embed ``texts`` in bounded batches of ``batch_size``.

        Batching caps peak memory (offline-architecture §1.4: 32 texts/batch)
        and reduces request count. Each batch is one ``client.embed`` call; the
        per-batch vectors are concatenated in input order. Empty input returns
        an empty list without contacting the engine.

        Raises:
            EmbeddingConnectionError: cannot reach the Ollama daemon.
            EmbeddingTimeoutError: a batch request exceeded the timeout.
            EmbeddingError: any other engine failure, or a dimension mismatch.
        """
        if not texts:
            return []
        if batch_size <= 0:
            raise EmbeddingError(
                f"batch_size must be positive, got {batch_size}"
            )
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch: list[str] = texts[start:start + batch_size]
            try:
                response = self._client.embed(
                    model=self._model, input=batch
                )
            except Exception as err:  # noqa: BLE001 -- single boundary; translate_engine_error classifies
                raise translate_engine_error(
                    err, model=self._model, host=self._host, kind="embedding"
                ) from err
            batch_vectors: list[list[float]] = [
                list(vec) for vec in response.embeddings
            ]
            if len(batch_vectors) != len(batch):
                raise EmbeddingError(
                    f"embedding count mismatch: sent {len(batch)} texts, "
                    f"got {len(batch_vectors)} vectors (model={self._model})"
                )
            for vec in batch_vectors:
                if len(vec) != EMBED_DIM:
                    raise EmbeddingError(
                        f"unexpected embedding dimension: expected "
                        f"{EMBED_DIM}, got {len(vec)} (model={self._model})"
                    )
            vectors.extend(batch_vectors)
        return vectors


def embed_batch(
    texts: list[str],
    batch_size: int,
    *,
    embedder: EmbeddingAdapter,
) -> list[list[float]]:
    """Embed ``texts`` in bounded batches using the given ``embedder``.

    Convenience wrapper around the :class:`Embedder` adapter. The
    ``embedder`` argument is mandatory (DIP — no module-level default).

    Raises:
        EmbeddingConnectionError: cannot reach the Ollama daemon.
        EmbeddingTimeoutError: a batch request exceeded the timeout.
        EmbeddingError: any other engine failure, a dimension mismatch, or
            ``batch_size`` is not positive.
    """
    if batch_size <= 0:
        raise EmbeddingError(f"batch_size must be positive, got {batch_size}")
    return embedder.embed_batch(texts, batch_size=batch_size)


def embed_text(
    text: str,
    *,
    embedder: EmbeddingAdapter,
) -> list[float]:
    """Embed a single ``text`` (convenience wrapper around :func:`embed_batch`)."""
    return embedder.embed(text)
