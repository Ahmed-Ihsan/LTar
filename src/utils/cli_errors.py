"""CLI error-handling decorator — maps domain exceptions to exit codes.

Exit-code table (AGENTS.md §11):
    0 = success
    1 = generic / unhandled
    2 = LLM / embedding connection / auth (Ollama, Gemini, embedding)
    3 = RAM guard
    4 = path containment
    5 = JSONL / input validation
    6 = I/O (OSError)
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import TypeVar

import typer

from src.components.translation_pipeline.exceptions import (
    AdapterError,
    AuditParseError,
    CorpusError,
    EmbeddingConnectionError,
    EmbeddingError,
    GeminiAuthError,
    GeminiQuotaError,
    GlossaryError,
    InputValidationError,
    LegalSearchBlockedError,
    LlamaCppConnectionError,
    LLMConnectionError,
    LLMRuntimeError,
    LLMTimeoutError,
    OllamaConnectionError,
    OllamaModelNotLoadedError,
    PathContainmentError,
    RAMGuardError,
    RetrievalError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

_EXIT_OK = 0
_EXIT_GENERIC = 1
_EXIT_OLLAMA = 2
_EXIT_RAM_GUARD = 3
_EXIT_PATH = 4
_EXIT_VALIDATION = 5
_EXIT_IO = 6


def handle_pipeline_errors(func: Callable[..., T]) -> Callable[..., T]:
    """Decorate a CLI command to catch domain exceptions and exit with the right code.

    Catches:
        OllamaConnectionError / EmbeddingConnectionError → exit 2
        GeminiAuthError / GeminiQuotaError / LLMConnectionError /
        LLMTimeoutError → exit 2 (connection / auth family — same code as
        the Ollama connection family; no new exit code is introduced per
        the `add-gemini-api-backend` interfaces spec delta)
        AdapterError / OllamaModelNotLoadedError / LlamaCppConnectionError /
        LLMRuntimeError / EmbeddingError → exit 2 (engine / LLM / embedding
        family — adapter failures, model-not-loaded, llama.cpp connection,
        and catch-all bases for any unmapped LLM/embedding subclass)
        RAMGuardError → exit 3
        PathContainmentError → exit 4
        InputValidationError / GlossaryError / LegalSearchBlockedError →
        exit 5 (input validation family — glossary schema/validation failures
        and legal-search URL allowlist violations are input-validation issues)
        OSError / CorpusError / RetrievalError → exit 6 (I/O family — corpus
        file ingestion and vector-store retrieval failures are I/O-related)
        AuditParseError → exit 1 (generic — auditor output parse failure has
        no more specific exit code; mapped explicitly for a clear message)
    All other exceptions propagate (exit 1 via Typer).
    """
    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> T:
        try:
            return func(*args, **kwargs)
        except (
            OllamaConnectionError,
            EmbeddingConnectionError,
            GeminiAuthError,
            GeminiQuotaError,
            LLMConnectionError,
            LLMTimeoutError,
            OllamaModelNotLoadedError,
            LlamaCppConnectionError,
            LLMRuntimeError,
            EmbeddingError,
            AdapterError,
        ) as e:
            logger.error("Engine connection/auth error: %s", e)
            typer.echo(f"Error: cannot reach LLM/embedding backend: {e}", err=True)
            raise typer.Exit(code=_EXIT_OLLAMA) from e
        except RAMGuardError as e:
            logger.error("RAM guard exceeded: %s", e)
            typer.echo(f"Error: RAM guard exceeded: {e}", err=True)
            raise typer.Exit(code=_EXIT_RAM_GUARD) from e
        except PathContainmentError as e:
            logger.error("Path containment violation: %s", e)
            typer.echo(f"Error: path outside allowed root: {e}", err=True)
            raise typer.Exit(code=_EXIT_PATH) from e
        except (
            InputValidationError,
            GlossaryError,
            LegalSearchBlockedError,
        ) as e:
            logger.error("Input validation error: %s", e)
            typer.echo(f"Error: invalid input: {e}", err=True)
            raise typer.Exit(code=_EXIT_VALIDATION) from e
        except (
            OSError,
            CorpusError,
            RetrievalError,
        ) as e:
            logger.error("I/O error: %s", e)
            typer.echo(f"Error: I/O failure: {e}", err=True)
            raise typer.Exit(code=_EXIT_IO) from e
        except AuditParseError as e:
            logger.error("Audit parse error: %s", e)
            typer.echo(f"Error: auditor output could not be parsed: {e}", err=True)
            raise typer.Exit(code=_EXIT_GENERIC) from e

    return wrapper


__all__ = ["handle_pipeline_errors"]
