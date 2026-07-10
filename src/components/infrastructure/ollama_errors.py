"""Shared Ollama engine error translation (DRY, clean-code §3.2).

Both :mod:`llm` and :mod:`embeddings` translate Ollama/httpx exceptions to
domain exceptions. The logic was duplicated nearly verbatim in both modules;
this module provides a single :func:`translate_engine_error` that maps engine
exceptions to the correct domain hierarchy based on the ``kind`` parameter.

``kind="llm"``      → ``LLMRuntimeError`` subclasses (incl. 404 model-not-found)
``kind="embedding"`` → ``EmbeddingError`` subclasses
"""
from __future__ import annotations

import ollama

from src.components.translation_pipeline.exceptions import (
    EmbeddingConnectionError,
    EmbeddingError,
    EmbeddingTimeoutError,
    LLMRuntimeError,
    OllamaConnectionError,
    OllamaModelNotLoadedError,
    OllamaTimeoutError,
)

# HTTP 404 from Ollama indicates the requested model is not pulled locally.
_MODEL_NOT_FOUND_STATUS: int = 404

# Supported engine kinds for error translation.
_KIND_LLM: str = "llm"
_KIND_EMBEDDING: str = "embedding"


def translate_engine_error(
    err: BaseException, *, model: str, host: str, kind: str
) -> Exception:
    """Map an Ollama/httpx engine exception to a domain exception.

    Implements the catch matrix (clean-code §3.2). The ``kind`` parameter
    selects the target exception hierarchy:

    - ``"llm"``: 404 → :class:`OllamaModelNotLoadedError`, other
      ``ResponseError`` → :class:`OllamaConnectionError`, timeout →
      :class:`OllamaTimeoutError`, connection →
      :class:`OllamaConnectionError`, fallback → :class:`LLMRuntimeError`.
    - ``"embedding"``: timeout → :class:`EmbeddingTimeoutError`, connection →
      :class:`EmbeddingConnectionError`, fallback → :class:`EmbeddingError`.

    Args:
        err: The caught engine exception.
        model: The model name used in the failing call (for diagnostics).
        host: The Ollama daemon host URL (for diagnostics).
        kind: Either ``"llm"`` or ``"embedding"``.

    Returns:
        The mapped domain exception (caller should ``raise … from err``).
    """
    msg: str = str(err).lower()
    is_timeout: bool = isinstance(err, TimeoutError) or "timeout" in msg or "timed out" in msg
    is_connection: bool = isinstance(err, (ConnectionError, OSError))

    if kind == _KIND_LLM:
        return _translate_llm_error(err, model=model, host=host, is_timeout=is_timeout,
                                    is_connection=is_connection)
    if kind == _KIND_EMBEDDING:
        return _translate_embedding_error(err, model=model, host=host,
                                          is_timeout=is_timeout, is_connection=is_connection)
    raise ValueError(f"unknown engine kind {kind!r}; expected 'llm' or 'embedding'")


def _translate_llm_error(
    err: BaseException, *, model: str, host: str, is_timeout: bool, is_connection: bool
) -> LLMRuntimeError:
    """Map an engine exception to an ``LLMRuntimeError`` subclass."""
    if isinstance(err, ollama.ResponseError):
        if err.status_code == _MODEL_NOT_FOUND_STATUS:
            return OllamaModelNotLoadedError(
                f"model '{model}' not loaded on Ollama at {host}: {err}"
            )
        return OllamaConnectionError(
            f"Ollama response error (status={err.status_code}) at {host}: {err}"
        )
    if is_timeout:
        return OllamaTimeoutError(
            f"Ollama request to {host} timed out (model={model}): {err}"
        )
    if is_connection:
        return OllamaConnectionError(
            f"cannot reach Ollama daemon at {host} (model={model}): {err}"
        )
    return LLMRuntimeError(
        f"unexpected Ollama error (model={model}, host={host}): {err}"
    )


def _translate_embedding_error(
    err: BaseException, *, model: str, host: str, is_timeout: bool, is_connection: bool
) -> EmbeddingError:
    """Map an engine exception to an ``EmbeddingError`` subclass."""
    if is_timeout:
        return EmbeddingTimeoutError(
            f"embedding request to {host} timed out (model={model}): {err}"
        )
    if is_connection:
        return EmbeddingConnectionError(
            f"cannot reach embedding engine at {host} (model={model}): {err}"
        )
    return EmbeddingError(
        f"embedding engine error (model={model}, host={host}): {err}"
    )
