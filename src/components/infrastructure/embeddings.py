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

from typing import Protocol, runtime_checkable

import ollama

from src.components.translation_pipeline.exceptions import (
    EmbeddingConnectionError,
    EmbeddingError,
    EmbeddingTimeoutError,
)
from src.config import AppConfig, load_config

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


def _translate_engine_error(
    err: BaseException, model: str, host: str
) -> EmbeddingError:
    """Map an Ollama/httpx engine exception to a domain ``EmbeddingError``.

    Implements the catch matrix (clean-code §3.2): connection failures become
    :class:`EmbeddingConnectionError`, timeouts become
    :class:`EmbeddingTimeoutError`, anything else becomes a generic
    :class:`EmbeddingError` carrying the model name and host for diagnosis.
    """
    msg: str = str(err).lower()
    if isinstance(err, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return EmbeddingTimeoutError(
            f"embedding request to {host} timed out (model={model}): {err}"
        )
    if isinstance(err, (ConnectionError, OSError)):
        return EmbeddingConnectionError(
            f"cannot reach embedding engine at {host} (model={model}): {err}"
        )
    return EmbeddingError(
        f"embedding engine error (model={model}, host={host}): {err}"
    )


class Embedder:
    """Real Ollama embedding adapter (clean-code §2.4: manages client state).

    Wraps a single :class:`ollama.Client` instance (reused across calls —
    clean-code §4.1: never create a new httpx connection per request) and
    translates engine exceptions to the domain hierarchy.
    """

    __slots__ = ("_client", "_model", "_host")

    def __init__(
        self,
        client: ollama.Client | None = None,
        *,
        model: str | None = None,
        host: str | None = None,
    ) -> None:
        """Build an embedder.

        If ``client`` is omitted, a new :class:`ollama.Client` is created from
        the resolved ``host`` (defaults to the config ``ollama_host``). If
        ``model`` is omitted, the config ``embed_model`` is used. Resolving
        defaults from config keeps model names out of node/callers code (DRY,
        engineering-principles §2.2.4).
        """
        cfg: AppConfig = load_config()
        self._model: str = model if model is not None else cfg.embed_model
        self._host: str = host if host is not None else cfg.ollama_host
        self._client: ollama.Client = (
            client if client is not None else ollama.Client(host=self._host)
        )

    @property
    def model(self) -> str:
        """The embedding model name used for all calls."""
        return self._model

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
            raise ValueError(
                f"batch_size must be positive, got {batch_size}"
            )
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch: list[str] = texts[start:start + batch_size]
            try:
                response = self._client.embed(
                    model=self._model, input=batch
                )
            except (ConnectionError, OSError, TimeoutError) as err:
                raise _translate_engine_error(err, self._model, self._host) from err
            except Exception as err:  # ollama.RequestError / ResponseError / others
                raise _translate_engine_error(err, self._model, self._host) from err
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


# Module-level default embedder (lazy). The convenience functions below use it
# so callers that do not need dependency injection can call ``embed_batch``
# directly. Tests and the ingestion CLI inject an explicit :class:`Embedder`
# (or a mock) instead.
_default_embedder: Embedder | None = None


def _get_default_embedder() -> Embedder:
    """Return the lazily-created module-level default embedder."""
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = Embedder()
    return _default_embedder


def embed_batch(
    texts: list[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    *,
    embedder: EmbeddingAdapter | None = None,
) -> list[list[float]]:
    """Embed ``texts`` in bounded batches using ``nomic-embed-text``.

    Convenience wrapper around the :class:`Embedder` adapter (TODO 2.3.1
    signature). If ``embedder`` is given (real or mock), it is used directly —
    this is the dependency-injection seam for deterministic tests
    (engineering-principles §1.5). Otherwise the module-level default
    :class:`Embedder` is used lazily.

    Raises:
        EmbeddingConnectionError: cannot reach the Ollama daemon.
        EmbeddingTimeoutError: a batch request exceeded the timeout.
        EmbeddingError: any other engine failure or dimension mismatch.
        ValueError: ``batch_size`` is not positive.
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be positive, got {batch_size}")
    if embedder is not None:
        return embedder.embed_batch(texts, batch_size=batch_size)
    return _get_default_embedder().embed_batch(texts, batch_size=batch_size)


def embed_text(
    text: str,
    *,
    embedder: EmbeddingAdapter | None = None,
) -> list[float]:
    """Embed a single ``text`` (convenience wrapper around :func:`embed_batch`)."""
    if embedder is not None:
        return embedder.embed(text)
    return _get_default_embedder().embed(text)
