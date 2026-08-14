"""Tests for ``src.components.infrastructure.ollama_errors.translate_engine_error``.

Verifies the isinstance-first timeout / connection detection added in Change 4
(``fix-error-handling-and-logging``): httpx exception types are mapped to the
correct domain exceptions without relying on string matching alone.
"""
from __future__ import annotations

import httpx
import ollama
import pytest

from src.components.infrastructure.ollama_errors import translate_engine_error
from src.components.translation_pipeline.exceptions import (
    EmbeddingConnectionError,
    EmbeddingTimeoutError,
    OllamaConnectionError,
    OllamaModelNotLoadedError,
    OllamaTimeoutError,
)

pytestmark = pytest.mark.adapter

# ---------------------------------------------------------------------------
# LLM kind
# ---------------------------------------------------------------------------


class TestTranslateLlmError:
    def test_httpx_connect_timeout_maps_to_ollama_timeout(self) -> None:
        err = httpx.ConnectTimeout("connect timed out")
        out = translate_engine_error(err, model="gemma3:4b", host="http://x", kind="llm")
        assert isinstance(out, OllamaTimeoutError)

    def test_httpx_read_timeout_maps_to_ollama_timeout(self) -> None:
        err = httpx.ReadTimeout("read timed out")
        out = translate_engine_error(err, model="gemma3:4b", host="http://x", kind="llm")
        assert isinstance(out, OllamaTimeoutError)

    def test_httpx_pool_timeout_maps_to_ollama_timeout(self) -> None:
        err = httpx.PoolTimeout("pool timed out")
        out = translate_engine_error(err, model="gemma3:4b", host="http://x", kind="llm")
        assert isinstance(out, OllamaTimeoutError)

    def test_httpx_connect_error_maps_to_ollama_connection(self) -> None:
        err = httpx.ConnectError("cannot reach host")
        out = translate_engine_error(err, model="gemma3:4b", host="http://x", kind="llm")
        assert isinstance(out, OllamaConnectionError)

    def test_ollama_response_error_404_maps_to_model_not_loaded(self) -> None:
        err = ollama.ResponseError("not found", status_code=404)  # type: ignore[arg-type]
        out = translate_engine_error(err, model="gemma3:4b", host="http://x", kind="llm")
        assert isinstance(out, OllamaModelNotLoadedError)

    def test_string_match_fallback_still_works_for_timeout(self) -> None:
        # An exception that is NOT a httpx/TimeoutError but mentions "timeout"
        # in its message should still be detected as a timeout (backwards
        # compatibility with ollama-py wrappers).
        err = RuntimeError("request timeout exceeded")
        out = translate_engine_error(err, model="gemma3:4b", host="http://x", kind="llm")
        assert isinstance(out, OllamaTimeoutError)


# ---------------------------------------------------------------------------
# Embedding kind
# ---------------------------------------------------------------------------


class TestTranslateEmbeddingError:
    def test_httpx_connect_timeout_maps_to_embedding_timeout(self) -> None:
        err = httpx.ConnectTimeout("connect timed out")
        out = translate_engine_error(err, model="nomic-embed", host="http://x", kind="embedding")
        assert isinstance(out, EmbeddingTimeoutError)

    def test_httpx_connect_error_maps_to_embedding_connection(self) -> None:
        err = httpx.ConnectError("cannot reach host")
        out = translate_engine_error(err, model="nomic-embed", host="http://x", kind="embedding")
        assert isinstance(out, EmbeddingConnectionError)

    def test_unknown_kind_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown engine kind"):
            translate_engine_error(RuntimeError("x"), model="m", host="h", kind="bogus")
