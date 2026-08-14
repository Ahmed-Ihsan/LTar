"""Unit tests for ``src.utils.cli_errors.handle_pipeline_errors``.

Verifies that the decorator maps every domain exception type to the correct
CLI exit code per the AGENTS.md exit-code table:

    0 = success
    1 = generic / unhandled
    2 = LLM / embedding connection / auth (Ollama, Gemini, embedding)
    3 = RAM guard
    4 = path containment
    5 = JSONL / input validation
    6 = I/O (OSError)

The tests are split into three groups:
1. **Already-mapped** exceptions — regression coverage for the original 6
   exception families (exit codes 2-6).
2. **Newly-mapped** exceptions — the 10 domain exception types that previously
   fell through to generic exit code 1.
3. **Subclass coverage** — verifies that subclasses of newly-mapped base
   exceptions are caught via inheritance.
"""
from __future__ import annotations

import pytest
import typer

from src.components.translation_pipeline.exceptions import (
    AdapterError,
    AuditParseError,
    ChromaDBCorruptionError,
    CorpusEncodingError,
    CorpusError,
    CorpusParseError,
    EmbeddingConnectionError,
    EmbeddingError,
    EmbeddingTimeoutError,
    GeminiAuthError,
    GeminiQuotaError,
    GlossaryConflictError,
    GlossaryError,
    GlossaryValidationError,
    InputValidationError,
    LegalSearchBlockedError,
    LlamaCppConnectionError,
    LlamaCppTimeoutError,
    LLMConnectionError,
    LLMRuntimeError,
    LLMTimeoutError,
    OllamaConnectionError,
    OllamaModelNotLoadedError,
    OllamaTimeoutError,
    PathContainmentError,
    RAMGuardError,
    RetrievalError,
)
from src.utils.cli_errors import handle_pipeline_errors

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_exit_code(exc_type: type[Exception], expected_code: int) -> None:
    """Decorate a function that raises *exc_type* and assert the Typer exit code."""

    @handle_pipeline_errors
    def _func() -> None:
        raise exc_type("test error")

    with pytest.raises(typer.Exit) as exc_info:
        _func()
    assert exc_info.value.exit_code == expected_code


# ---------------------------------------------------------------------------
# Successful calls pass through unchanged
# ---------------------------------------------------------------------------


class TestSuccessfulCall:
    @pytest.mark.unit
    def test_success_returns_value(self) -> None:
        @handle_pipeline_errors
        def _func() -> str:
            return "ok"

        assert _func() == "ok"

    @pytest.mark.unit
    def test_success_returns_none(self) -> None:
        @handle_pipeline_errors
        def _func() -> None:
            pass

        assert _func() is None

    @pytest.mark.unit
    def test_success_with_args(self) -> None:
        @handle_pipeline_errors
        def _func(x: int, y: int) -> int:
            return x + y

        assert _func(2, 3) == 5


# ---------------------------------------------------------------------------
# Already-mapped exceptions (regression coverage, exit codes 2-6)
# ---------------------------------------------------------------------------


class TestAlreadyMappedExceptions:
    """Regression coverage for exceptions mapped before this change."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "exc_type",
        [
            OllamaConnectionError,
            EmbeddingConnectionError,
            GeminiAuthError,
            GeminiQuotaError,
            LLMConnectionError,
            LLMTimeoutError,
        ],
    )
    def test_connection_auth_family_exit_2(self, exc_type: type[Exception]) -> None:
        _assert_exit_code(exc_type, 2)

    @pytest.mark.unit
    def test_ram_guard_exit_3(self) -> None:
        _assert_exit_code(RAMGuardError, 3)

    @pytest.mark.unit
    def test_path_containment_exit_4(self) -> None:
        _assert_exit_code(PathContainmentError, 4)

    @pytest.mark.unit
    def test_input_validation_exit_5(self) -> None:
        _assert_exit_code(InputValidationError, 5)

    @pytest.mark.unit
    def test_oserror_exit_6(self) -> None:
        _assert_exit_code(OSError, 6)


# ---------------------------------------------------------------------------
# Newly-mapped exceptions (the 10 previously unmapped domain types)
# ---------------------------------------------------------------------------


class TestNewlyMappedExceptions:
    """The 10 domain exception types that previously fell through to exit 1."""

    # --- Exit 2: LLM / embedding connection / auth family -------------------

    @pytest.mark.unit
    def test_adapter_error_exit_2(self) -> None:
        _assert_exit_code(AdapterError, 2)

    @pytest.mark.unit
    def test_ollama_model_not_loaded_exit_2(self) -> None:
        _assert_exit_code(OllamaModelNotLoadedError, 2)

    @pytest.mark.unit
    def test_llamacpp_connection_exit_2(self) -> None:
        _assert_exit_code(LlamaCppConnectionError, 2)

    @pytest.mark.unit
    def test_llm_runtime_error_exit_2(self) -> None:
        _assert_exit_code(LLMRuntimeError, 2)

    @pytest.mark.unit
    def test_embedding_error_exit_2(self) -> None:
        _assert_exit_code(EmbeddingError, 2)

    # --- Exit 5: input validation family ------------------------------------

    @pytest.mark.unit
    def test_glossary_error_exit_5(self) -> None:
        _assert_exit_code(GlossaryError, 5)

    @pytest.mark.unit
    def test_legal_search_blocked_exit_5(self) -> None:
        _assert_exit_code(LegalSearchBlockedError, 5)

    # --- Exit 6: I/O family --------------------------------------------------

    @pytest.mark.unit
    def test_corpus_error_exit_6(self) -> None:
        _assert_exit_code(CorpusError, 6)

    @pytest.mark.unit
    def test_retrieval_error_exit_6(self) -> None:
        _assert_exit_code(RetrievalError, 6)

    # --- Exit 1: generic / unhandled -----------------------------------------

    @pytest.mark.unit
    def test_audit_parse_error_exit_1(self) -> None:
        _assert_exit_code(AuditParseError, 1)


# ---------------------------------------------------------------------------
# Subclass coverage — subclasses caught via newly-mapped parent exceptions
# ---------------------------------------------------------------------------


class TestSubclassCoverage:
    """Subclasses of newly-mapped base exceptions are caught via inheritance."""

    @pytest.mark.unit
    def test_glossary_conflict_error_exit_5(self) -> None:
        _assert_exit_code(GlossaryConflictError, 5)

    @pytest.mark.unit
    def test_glossary_validation_error_exit_5(self) -> None:
        _assert_exit_code(GlossaryValidationError, 5)

    @pytest.mark.unit
    def test_corpus_parse_error_exit_6(self) -> None:
        _assert_exit_code(CorpusParseError, 6)

    @pytest.mark.unit
    def test_corpus_encoding_error_exit_6(self) -> None:
        _assert_exit_code(CorpusEncodingError, 6)

    @pytest.mark.unit
    def test_chromadb_corruption_error_exit_6(self) -> None:
        _assert_exit_code(ChromaDBCorruptionError, 6)

    @pytest.mark.unit
    def test_llamacpp_timeout_exit_2(self) -> None:
        _assert_exit_code(LlamaCppTimeoutError, 2)


# ---------------------------------------------------------------------------
# Already-caught subclass coverage (via existing parent handlers)
# ---------------------------------------------------------------------------


class TestExistingSubclassCoverage:
    """Subclasses caught via already-mapped parent exceptions (regression)."""

    @pytest.mark.unit
    def test_ollama_timeout_exit_2(self) -> None:
        _assert_exit_code(OllamaTimeoutError, 2)

    @pytest.mark.unit
    def test_embedding_timeout_exit_2(self) -> None:
        _assert_exit_code(EmbeddingTimeoutError, 2)
