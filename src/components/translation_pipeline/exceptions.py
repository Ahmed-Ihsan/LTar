"""Domain exception hierarchy for the Iraqi Legal Translation Agent.

Authoritative hierarchy per the ``clean-code`` skill §3.1. Engine-specific
exceptions (``ollama.ResponseError``, ``httpx.ConnectError``, …) are caught
inside adapters and re-raised as the domain exceptions defined here. Nodes
and the CLI only ever see these domain exceptions — never engine types.

Design notes:
- Every error descends from :class:`LegalTranslationError` so a single
  ``except LegalTranslationError`` catches any domain failure.
- Adapter errors share :class:`AdapterError` so a caller can distinguish
  "an engine failed generically" from a more specific mapped error.
- Connection/timeout pairs (Ollama, llama.cpp, embedding) descend from a
  shared connection base so retry logic can target the right family.
"""
from __future__ import annotations


class LegalTranslationError(Exception):
    """Base for all domain errors raised by this system."""


class AdapterError(LegalTranslationError):
    """Base for errors raised by the adapter layer when an engine fails in a
    way that cannot be mapped to a more specific domain error."""


# --- Glossary ---------------------------------------------------------------

class GlossaryError(LegalTranslationError):
    """Base for glossary loading / scanning errors."""


class GlossaryConflictError(GlossaryError):
    """Two glossary terms collide on a uniqueness constraint."""


class GlossaryValidationError(GlossaryError):
    """A glossary file failed schema / semantic validation at ingestion."""


# --- Corpus -----------------------------------------------------------------

class CorpusError(LegalTranslationError):
    """Base for corpus ingestion errors."""


class CorpusParseError(CorpusError):
    """A corpus file could not be parsed."""


class CorpusEncodingError(CorpusParseError):
    """A corpus file is not valid UTF-8 (strict decoding failed)."""


# --- Retrieval --------------------------------------------------------------

class RetrievalError(LegalTranslationError):
    """Base for vector-store retrieval errors."""


class ChromaDBCorruptionError(RetrievalError):
    """The ChromaDB store is missing, unreadable, or internally corrupt."""


# --- LLM runtime ------------------------------------------------------------

class LLMRuntimeError(LegalTranslationError):
    """Base for LLM engine failures."""


class OllamaConnectionError(LLMRuntimeError):
    """Cannot reach the Ollama daemon."""


class OllamaTimeoutError(OllamaConnectionError):
    """An Ollama request exceeded the configured timeout."""


class OllamaModelNotLoadedError(LLMRuntimeError):
    """The requested model is not present on the Ollama instance."""


class LlamaCppConnectionError(LLMRuntimeError):
    """Cannot reach the llama.cpp server."""


class LlamaCppTimeoutError(LlamaCppConnectionError):
    """A llama.cpp request exceeded the configured timeout."""


# --- Embedding --------------------------------------------------------------

class EmbeddingError(LegalTranslationError):
    """Base for embedding-engine failures."""


class EmbeddingConnectionError(EmbeddingError):
    """Cannot reach the embedding engine."""


class EmbeddingTimeoutError(EmbeddingConnectionError):
    """An embedding request exceeded the configured timeout."""


# --- Audit ------------------------------------------------------------------

class AuditParseError(LegalTranslationError):
    """The Auditor Agent returned output that could not be parsed into a
    structured :class:`AuditVerdict`."""


# --- Resource guards --------------------------------------------------------

class RAMGuardError(LegalTranslationError):
    """Available system RAM is below the safe threshold for an LLM call.

    Raised by the RAM guard (task 4.3.3) before contacting the Ollama daemon
    when free RAM is under ``RAM_GUARD_MIN_GB`` (1.5 GB), so the process aborts
    with a clear message instead of risking an out-of-memory kill mid-run.
    """
