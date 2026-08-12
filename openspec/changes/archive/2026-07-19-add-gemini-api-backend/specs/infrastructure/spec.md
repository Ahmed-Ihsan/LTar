## ADDED Requirements

### Requirement: Gemini engine adapter

A `GeminiEngineAdapter` class SHALL reside in `src/components/infrastructure/gemini.py` and SHALL implement **both** the `LLMEngineAdapter` protocol (`generate(system_prompt, user_prompt, *, model, temperature, max_tokens, timeout) -> str`) and the `EmbeddingAdapter` protocol (`embed(text) -> list[float]`, `embed_batch(texts, batch_size) -> list[list[float]]`). It SHALL be constructed with `(*, model, embed_model, api_key, timeout, rpm)` as keyword-only args (DIP — no `load_config()` fallback). It SHALL expose a `model` property returning the configured Gemini chat model name. The `google-genai` SDK SHALL be lazily imported inside `gemini.py` so that the module imports successfully even when the SDK is not installed (offline users on the Ollama path never import it). `GeminiEngineAdapter` SHALL support the context-manager protocol (`__enter__`/`__exit__`) and an idempotent `close()` method. `GeminiEngineAdapter.generate` SHALL NOT call `check_ram_guard()` (cloud inference does not consume local RAM for model weights; the 8 GB ceiling is irrelevant to hosted inference). `embed_batch` SHALL validate `batch_size` via `src.utils.batch_size.validate_batch_size` (single source of truth, matching the Ollama `Embedder`). `embed_batch` SHALL enforce `EMBED_DIM` (768) on every returned vector and SHALL raise `EmbeddingError` on a dimension mismatch — matching the Ollama `Embedder` contract so the existing 768-dim cosine ChromaDB collection is reusable.

#### Scenario: GeminiEngineAdapter satisfies the LLMEngineAdapter protocol
- **GIVEN** a `GeminiEngineAdapter` instance
- **WHEN** it is checked against `LLMEngineAdapter` via `isinstance(adapter, LLMEngineAdapter)`
- **THEN** it satisfies the protocol (structural subtyping, `@runtime_checkable`)

#### Scenario: GeminiEngineAdapter satisfies the EmbeddingAdapter protocol
- **GIVEN** a `GeminiEngineAdapter` instance
- **WHEN** it is checked against `EmbeddingAdapter` via `isinstance(adapter, EmbeddingAdapter)`
- **THEN** it satisfies the protocol (structural subtyping, `@runtime_checkable`)

#### Scenario: generate returns a translation string
- **GIVEN** a `GeminiEngineAdapter` with a valid `api_key` and model `gemini-2.0-flash`, with the Gemini client mocked to return "Contract of Sale"
- **WHEN** `generate` is called with an Arabic system + user prompt
- **THEN** the string "Contract of Sale" is returned

#### Scenario: module imports without the google-genai SDK installed
- **GIVEN** the `google-genai` package is not installed
- **WHEN** `import src.components.infrastructure.gemini` is executed
- **THEN** the import succeeds (the SDK is imported lazily inside `__init__`/methods, not at module top level)

#### Scenario: generate does not invoke the RAM guard
- **GIVEN** a `GeminiEngineAdapter` and a monkeypatched `check_ram_guard` that records calls
- **WHEN** `generate` is called
- **THEN** `check_ram_guard` is NOT called (cloud inference does not consume local RAM for weights)

#### Scenario: embed_batch enforces the 768-dim contract
- **GIVEN** a `GeminiEngineAdapter` with `embed_model="text-embedding-004"` and a mocked client returning a 512-dim vector
- **WHEN** `embed_batch` is called
- **THEN** an `EmbeddingError` is raised indicating the dimension mismatch (the existing 768-dim ChromaDB collection must not be corrupted)

#### Scenario: embed_batch rejects a non-positive batch size
- **GIVEN** a `GeminiEngineAdapter`
- **WHEN** `embed_batch` is called with `batch_size=0`
- **THEN** `validate_batch_size` raises `ValueError` (delegated to the shared helper, matching the Ollama `Embedder`)

#### Scenario: close is idempotent
- **GIVEN** a `GeminiEngineAdapter` whose `close()` has already been called
- **WHEN** `close()` is called again
- **THEN** no exception is raised and no double-close occurs

#### Scenario: context manager closes the adapter
- **GIVEN** a `GeminiEngineAdapter` used in a `with` statement
- **WHEN** the context exits
- **THEN** `close()` is invoked exactly once via `__exit__`

### Requirement: Gemini exception mapping

`GeminiEngineAdapter` SHALL map Google GenAI SDK exceptions to the domain exception hierarchy so that nodes and the CLI only ever see domain exceptions (AGENTS.md §5, clean-code §3.2). A shared `_translate_gemini_error(err, *, model, kind) -> Exception` helper SHALL reside in `gemini.py` and SHALL map: authentication errors (HTTP 401/403 / `PermissionDenied`) → `GeminiAuthError`; quota/rate-limit errors (HTTP 429 / `ResourceExhausted`) → `GeminiQuotaError`; timeouts (`TimeoutError`, SDK deadline-exceeded) → `LLMTimeoutError`; connection errors (`ConnectionError`, `OSError`, SDK service-unavailable) → `LLMConnectionError`; and any other unrecognized error → `LLMRuntimeError` (for `kind="llm"`) or `EmbeddingError` (for `kind="embedding"`). The `kind` parameter SHALL select the target hierarchy exactly as `ollama_errors.translate_engine_error` does. The API key SHALL NEVER appear in any exception message or in the adapter's `repr` (security — AGENTS.md §12).

#### Scenario: invalid API key maps to GeminiAuthError
- **GIVEN** the Gemini client raises a 401/403 `PermissionDenied`-style error
- **WHEN** `_translate_gemini_error` classifies it with `kind="llm"`
- **THEN** a `GeminiAuthError` is returned (a subclass of `LLMRuntimeError`)

#### Scenario: quota exhausted maps to GeminiQuotaError
- **GIVEN** the Gemini client raises a 429 `ResourceExhausted`-style error
- **WHEN** `_translate_gemini_error` classifies it with `kind="llm"`
- **THEN** a `GeminiQuotaError` is returned (a subclass of `LLMRuntimeError`)

#### Scenario: timeout maps to LLMTimeoutError
- **GIVEN** the Gemini client raises a `TimeoutError` or deadline-exceeded error
- **WHEN** `_translate_gemini_error` classifies it with `kind="llm"`
- **THEN** an `LLMTimeoutError` is returned

#### Scenario: connection error maps to LLMConnectionError
- **GIVEN** the Gemini client raises a `ConnectionError` or service-unavailable error
- **WHEN** `_translate_gemini_error` classifies it with `kind="llm"`
- **THEN** an `LLMConnectionError` is returned

#### Scenario: unrecognized error maps to LLMRuntimeError
- **GIVEN** the Gemini client raises an unrecognized exception
- **WHEN** `_translate_gemini_error` classifies it with `kind="llm"`
- **THEN** an `LLMRuntimeError` wrapping the original error is returned

#### Scenario: embedding error maps to the EmbeddingError family
- **GIVEN** the Gemini embedding call raises a connection error
- **WHEN** `_translate_gemini_error` classifies it with `kind="embedding"`
- **THEN** an `EmbeddingConnectionError` is returned

#### Scenario: the API key is never leaked in an exception message
- **GIVEN** a `GeminiEngineAdapter` whose `generate` raises a mapped domain exception
- **WHEN** the exception message is inspected
- **THEN** the `api_key` value does not appear anywhere in the message

#### Scenario: the API key is never leaked in repr
- **GIVEN** a constructed `GeminiEngineAdapter`
- **WHEN** `repr(adapter)` is evaluated
- **THEN** the `api_key` value does not appear in the output

### Requirement: Gemini rate limiting

`GeminiEngineAdapter` SHALL enforce a per-instance RPM cap using a `threading.Semaphore`-based rate limiter initialized from the `rpm` constructor argument. Each `generate` and `embed`/`embed_batch` call SHALL acquire a permit before contacting the Gemini API and SHALL release it after the call returns or raises. When the configured RPM budget is exhausted, the adapter SHALL raise `GeminiQuotaError` (so the caller sees a domain exception, not a SDK 429). The default `rpm` SHALL be `15` (Gemini free-tier). The limiter SHALL be process-local (single-user, single-session per AGENTS.md — no distributed coordination is required).

#### Scenario: a call within the RPM budget succeeds
- **GIVEN** a `GeminiEngineAdapter` with `rpm=15` and fewer than 15 calls in the current minute window
- **WHEN** `generate` is called
- **THEN** the call proceeds and a permit is released on completion

#### Scenario: exceeding the RPM budget raises GeminiQuotaError
- **GIVEN** a `GeminiEngineAdapter` with `rpm=15` and the rate limiter budget exhausted
- **WHEN** `generate` is called
- **THEN** a `GeminiQuotaError` is raised without contacting the Gemini API

#### Scenario: a failed call still releases its permit
- **GIVEN** a `GeminiEngineAdapter` whose `generate` raises a mapped domain exception
- **WHEN** the exception propagates
- **THEN** the rate-limiter permit has been released (no permit leak across retries)

### Requirement: Backend-agnostic and Gemini-specific LLM exceptions

The domain exception hierarchy in `src/components/translation_pipeline/exceptions.py` SHALL add backend-agnostic connection and timeout exceptions: `LLMConnectionError` (a subclass of `LLMRuntimeError`) and `LLMTimeoutError` (a subclass of `LLMConnectionError`). It SHALL also add `GeminiAuthError` (a subclass of `LLMRuntimeError`, raised when the Gemini API key is missing/invalid) and `GeminiQuotaError` (a subclass of `LLMRuntimeError`, raised when the Gemini RPM/quota budget is exhausted). The existing `OllamaConnectionError`, `OllamaTimeoutError`, `LlamaCppConnectionError`, and `LlamaCppTimeoutError` classes SHALL remain unchanged (their base classes are NOT reparented — this change is additive only). All new classes SHALL be re-exported from `src/components/translation_pipeline/__init__.py`.

#### Scenario: LLMConnectionError is an LLMRuntimeError
- **GIVEN** the exception hierarchy
- **WHEN** `issubclass(LLMConnectionError, LLMRuntimeError)` is checked
- **THEN** it is `True`

#### Scenario: LLMTimeoutError is an LLMConnectionError
- **GIVEN** the exception hierarchy
- **WHEN** `issubclass(LLMTimeoutError, LLMConnectionError)` is checked
- **THEN** it is `True`

#### Scenario: GeminiAuthError is an LLMRuntimeError
- **GIVEN** the exception hierarchy
- **WHEN** `issubclass(GeminiAuthError, LLMRuntimeError)` is checked
- **THEN** it is `True`

#### Scenario: GeminiQuotaError is an LLMRuntimeError
- **GIVEN** the exception hierarchy
- **WHEN** `issubclass(GeminiQuotaError, LLMRuntimeError)` is checked
- **THEN** it is `True`

#### Scenario: existing Ollama exceptions are unchanged
- **GIVEN** the exception hierarchy after the change
- **WHEN** the base classes of `OllamaConnectionError` are inspected
- **THEN** its direct base is still `LLMRuntimeError` (not reparented to `LLMConnectionError`)

#### Scenario: new exceptions are re-exported from the package
- **GIVEN** the refactored `translation_pipeline` package
- **WHEN** `from src.components.translation_pipeline import LLMConnectionError, LLMTimeoutError, GeminiAuthError, GeminiQuotaError` is executed
- **THEN** all four are imported successfully via the package `__init__` re-export

### Requirement: Infrastructure public API re-export for Gemini

`src/components/infrastructure/__init__.py` SHALL re-export `GeminiEngineAdapter` so that `from src.components.infrastructure import GeminiEngineAdapter` works without specifying the submodule, matching the existing re-export pattern for `OllamaEngineAdapter` and `Embedder`.

#### Scenario: GeminiEngineAdapter is re-exported from the package
- **GIVEN** the refactored `infrastructure` package
- **WHEN** `from src.components.infrastructure import GeminiEngineAdapter` is executed
- **THEN** `GeminiEngineAdapter` is imported successfully via the package `__init__` re-export
