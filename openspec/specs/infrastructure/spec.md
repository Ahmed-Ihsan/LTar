## Purpose

The adapter layer: LLM engine adapter (Ollama), embedding adapter, system memory / RAM guard, and structured run logging. This component wraps all external runtime dependencies (Ollama daemon, OS memory APIs, filesystem logging) behind protocols so the pipeline and interfaces depend on abstractions, not concretions (DIP).
## Requirements
### Requirement: LLM engine adapter protocol

`LLMEngineAdapter` SHALL be a PEP 544 Protocol with a `generate(system_prompt, user_prompt, *, model, temperature, max_tokens, timeout) -> str` method. `OllamaEngineAdapter` is the concrete implementation using the Ollama Python client. It is constructed with `(client, *, model, host)` and exposes a `model` property. The 6-argument generate signature is the mandated adapter contract (ARCHITECTURE.md §5.3). Timeout detection in `OllamaEngineAdapter.generate` and in `ollama_errors.translate_engine_error` SHALL be performed primarily via `isinstance(err, (httpx.TimeoutException, TimeoutError))`; string-matching on `"timeout" in str(err).lower()` is permitted ONLY as a documented fallback for ollama-py client versions that wrap timeouts in a custom exception not subclassing `httpx.TimeoutException`.

#### Scenario: OllamaEngineAdapter implements the protocol
- **GIVEN** an OllamaEngineAdapter instance
- **WHEN** it is checked against the LLMEngineAdapter protocol
- **THEN** it satisfies the protocol (structural subtyping)

#### Scenario: Generate returns a translation string
- **GIVEN** an OllamaEngineAdapter with a connected client and model "qwen2.5:7b-instruct-q5_K_M"
- **WHEN** generate is called with system and user prompts
- **THEN** a string translation is returned from the Ollama chat completion API

#### Scenario: Ollama connection error
- **GIVEN** the Ollama daemon is not reachable
- **WHEN** generate is called
- **THEN** an OllamaConnectionError is raised (a subclass of LLMRuntimeError)

#### Scenario: Ollama model not loaded
- **GIVEN** the requested model is not present in Ollama
- **WHEN** generate is called
- **THEN** an OllamaModelNotLoadedError is raised

#### Scenario: an httpx.TimeoutException is detected as a timeout
- **GIVEN** `OllamaEngineAdapter.generate` catches an `httpx.TimeoutException`
- **WHEN** the exception is classified
- **THEN** it is mapped to `LLMTimeoutError` via `isinstance(err, (httpx.TimeoutException, TimeoutError))` — no string-matching is required for this case

#### Scenario: a builtin TimeoutError is detected as a timeout
- **GIVEN** `translate_engine_error` receives a builtin `TimeoutError`
- **WHEN** the exception is classified
- **THEN** it is mapped to `LLMTimeoutError` via the isinstance check

### Requirement: Embedding adapter protocol

`EmbeddingAdapter` SHALL be a PEP 544 Protocol with `embed(text) -> list[float]` and `embed_batch(texts, batch_size) -> list[list[float]]`. `Embedder` is the concrete Ollama implementation constructed with `(client, *, model, host)` and exposes a `model` property. `EMBED_DIM` = 768 (nomic-embed-text dimension). `DEFAULT_BATCH_SIZE` = 32. Batch-size validation SHALL be performed via `src.utils.batch_size.validate_batch_size` (single source of truth); the duplicated inline `if batch_size <= 0: raise ValueError(...)` checks SHALL be removed.

#### Scenario: Embedder implements the protocol
- **GIVEN** an Embedder instance
- **WHEN** it is checked against the EmbeddingAdapter protocol
- **THEN** it satisfies the protocol

#### Scenario: Embed returns 768-dim vector
- **GIVEN** an Embedder with a connected Ollama client and model "nomic-embed-text"
- **WHEN** embed is called with a text string
- **THEN** a list of 768 floats is returned

#### Scenario: Embed batch respects batch size cap
- **GIVEN** 100 texts and DEFAULT_BATCH_SIZE=32
- **WHEN** embed_batch is called
- **THEN** texts are embedded in batches of ≤ 32

#### Scenario: Embedding connection error
- **GIVEN** the Ollama daemon is not reachable
- **WHEN** embed is called
- **THEN** an EmbeddingConnectionError is raised (a subclass of EmbeddingError)

#### Scenario: batch-size validation uses the shared helper
- **GIVEN** the `embeddings.py` source
- **WHEN** its batch-size validation is inspected
- **THEN** it calls `src.utils.batch_size.validate_batch_size(batch_size)` and does NOT contain an inline `if batch_size <= 0:` check (the validation is delegated to the shared helper)

### Requirement: System memory and RAM guard

`read_memory_info() -> MemoryInfo | None` SHALL read total and available system RAM. `available_ram_gb() -> float | None` returns available RAM in GiB. `check_ram_guard(min_gb: float = RAM_GUARD_MIN_GB) -> None` raises `RAMGuardError` if available RAM is below the threshold. `RAM_GUARD_MIN_GB` = 1.5. `MemoryInfo` is a dataclass with total_bytes and available_bytes. `check_ram_guard` SHALL cache its result for 5 seconds (via `time.monotonic()`) so that calling it on every `OllamaEngineAdapter.generate` call does not perform a syscall per call; the cache SHALL be invalidated after 5 seconds so a long-running process picks up memory-pressure changes.

#### Scenario: RAM guard passes with sufficient memory
- **GIVEN** available RAM is 3.0 GB and min_gb is 1.5
- **WHEN** check_ram_guard is called
- **THEN** no exception is raised

#### Scenario: RAM guard fails with insufficient memory
- **GIVEN** available RAM is 1.0 GB and min_gb is 1.5
- **WHEN** check_ram_guard is called
- **THEN** a RAMGuardError is raised

#### Scenario: read_memory_info returns None on unsupported platform
- **GIVEN** a platform where memory reading is not supported
- **WHEN** read_memory_info is called
- **THEN** None is returned (no crash)

#### Scenario: repeated calls within 5 seconds use the cache
- **GIVEN** `check_ram_guard()` has been called once
- **WHEN** it is called again 2 seconds later
- **THEN** the cached result is returned without a syscall to read memory info

#### Scenario: calls after 5 seconds re-read memory
- **GIVEN** `check_ram_guard()` has been called once and 6 seconds have elapsed
- **WHEN** it is called again
- **THEN** a fresh memory-info read is performed (the cache entry has expired)

### Requirement: Structured run logging

`RunLogger` SHALL write JSON lines per node execution to a JSONL file. It is constructed with `(log_dir, run_id)`, exposes `run_id` and `path` properties, and has a `log_node(node_name, latency_ms, state)` method. It supports context manager protocol (`__enter__`/`__exit__`) and an idempotent `close()` method that flushes and closes the file handle. `log_node` SHALL be non-fatal: if `self._fh.write` or `self._fh.flush` raises `OSError`, the logger SHALL emit a `logging.getLogger(__name__).warning(...)` with the error, set `self._disabled = True`, and return without propagating the exception; subsequent `log_node` calls SHALL be no-ops while `self._disabled` is true.

#### Scenario: RunLogger writes one JSON line per node
- **GIVEN** a RunLogger with a valid log_dir and run_id
- **WHEN** log_node is called with node_name="translate", latency_ms=1500, and a TranslationState
- **THEN** one JSON line is appended to the log file containing the node name, latency, and state snapshot

#### Scenario: RunLogger as context manager
- **GIVEN** a RunLogger used in a `with` statement
- **WHEN** the context exits
- **THEN** the file handle is closed automatically via __exit__

#### Scenario: RunLogger path property
- **GIVEN** a RunLogger with log_dir="logs/" and run_id="abc123"
- **WHEN** the path property is accessed
- **THEN** it returns the full path to the JSONL log file

#### Scenario: RunLogger close is idempotent
- **GIVEN** a RunLogger whose `close()` has already been called
- **WHEN** `close()` is called again
- **THEN** no exception is raised and no double-close occurs

#### Scenario: RunLogger survives a disk-full error
- **GIVEN** a RunLogger whose `self._fh.write` raises `OSError` (simulated disk full)
- **WHEN** `log_node` is called
- **THEN** no exception is propagated to the caller, a warning is emitted via the standard `logging` module, and subsequent `log_node` calls are no-ops

#### Scenario: RunLogger disabled mode skips further writes
- **GIVEN** a RunLogger with `self._disabled = True`
- **WHEN** `log_node` is called
- **THEN** the method returns immediately without attempting any file I/O

### Requirement: Infrastructure component folder

The infrastructure adapters SHALL reside in `src/components/infrastructure/` as a bounded-context component. The folder SHALL contain: `__init__.py` (re-exports), `models.py`, `llm.py`, `embeddings.py`, `memory.py`, and `run_logging.py`.

#### Scenario: Component folder structure
- **GIVEN** the refactored project structure
- **WHEN** the `src/components/infrastructure/` directory is inspected
- **THEN** it contains `__init__.py`, `models.py`, `llm.py`, `embeddings.py`, `memory.py`, and `run_logging.py`

### Requirement: Infrastructure models module

Infrastructure-specific data models SHALL reside in `src/components/infrastructure/models.py`. This includes `MemoryInfo` (total_bytes, available_bytes) and `RunLogEntry` if applicable. Protocol definitions (`LLMEngineAdapter`, `EmbeddingAdapter`) MAY reside in their respective implementation modules or in models.py.

#### Scenario: Import MemoryInfo from component models
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.models import MemoryInfo` is executed
- **THEN** MemoryInfo is imported successfully

### Requirement: Infrastructure LLM module

`LLMEngineAdapter` (Protocol), `OllamaEngineAdapter`, and `_translate_engine_error` SHALL reside in `src/components/infrastructure/llm.py`.

#### Scenario: Import LLM adapter from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.llm import LLMEngineAdapter, OllamaEngineAdapter` is executed
- **THEN** both the Protocol and concrete adapter are imported successfully

### Requirement: Infrastructure embeddings module

`EmbeddingAdapter` (Protocol), `Embedder`, `embed_batch`, `EMBED_DIM`, and `DEFAULT_BATCH_SIZE` SHALL reside in `src/components/infrastructure/embeddings.py`.

#### Scenario: Import embedding adapter from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.embeddings import Embedder, EmbeddingAdapter, EMBED_DIM` is executed
- **THEN** all symbols are imported successfully

### Requirement: Infrastructure memory module

`read_memory_info`, `available_ram_gb`, `check_ram_guard`, `RAM_GUARD_MIN_GB`, and `MemoryInfo` SHALL reside in `src/components/infrastructure/memory.py`.

#### Scenario: Import memory API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.memory import read_memory_info, check_ram_guard, RAM_GUARD_MIN_GB` is executed
- **THEN** all symbols are imported successfully

### Requirement: Infrastructure run logging module

`RunLogger` SHALL reside in `src/components/infrastructure/run_logging.py`.

#### Scenario: Import RunLogger from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.run_logging import RunLogger` is executed
- **THEN** RunLogger is imported successfully

### Requirement: Infrastructure public API re-export

`src/components/infrastructure/__init__.py` SHALL re-export the component's public API so that `from src.components.infrastructure import LLMEngineAdapter, Embedder, RunLogger` works without specifying the submodule.

#### Scenario: Re-exported public API
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure import LLMEngineAdapter, Embedder, RunLogger, check_ram_guard` is executed
- **THEN** all symbols are imported successfully via the package __init__

### Requirement: Infrastructure intra-component imports

Modules within `infrastructure/` SHALL import from sibling modules within the same component using component paths (e.g., `from src.components.infrastructure.memory import check_ram_guard`), not from the old flat `src.memory` paths.

#### Scenario: llm.py imports from component memory
- **GIVEN** the refactored llm.py
- **WHEN** its imports are inspected
- **THEN** it imports check_ram_guard from `src.components.infrastructure.memory`, not from `src.memory`

### Requirement: Shared Ollama error translation

The `infrastructure/ollama_errors.py` module SHALL provide a shared `_translate_engine_error(err: Exception, model: str) -> Exception` function that maps Ollama client exceptions to the domain exception hierarchy (`OllamaConnectionError`, `OllamaModelNotLoadedError`, `LLMRuntimeError`, `EmbeddingConnectionError`, `EmbeddingError`). Both `llm.py` and `embeddings.py` SHALL import and use this shared function instead of maintaining their own copies.

#### Scenario: Timeout error is mapped to connection error
- **GIVEN** an exception whose message contains "timeout" or "timed out"
- **WHEN** `_translate_engine_error` is called
- **THEN** an `OllamaConnectionError` (or `EmbeddingConnectionError` for embeddings) is returned

#### Scenario: Model not loaded error is mapped
- **GIVEN** an exception indicating the model is not present in Ollama
- **WHEN** `_translate_engine_error` is called
- **THEN** an `OllamaModelNotLoadedError` is returned

#### Scenario: Generic error is mapped to runtime error
- **GIVEN** an unrecognized exception
- **WHEN** `_translate_engine_error` is called
- **THEN** an `LLMRuntimeError` (or `EmbeddingError`) is returned wrapping the original exception

#### Scenario: Both llm.py and embeddings.py use the shared function
- **GIVEN** the `llm.py` and `embeddings.py` modules are inspected
- **WHEN** their imports are checked
- **THEN** both import `_translate_engine_error` from `ollama_errors.py`; neither defines its own copy

### Requirement: Platform registry for memory reading

`memory.py` SHALL use a `_PLATFORM_READERS: dict[str, Callable[[], MemoryInfo | None]]` registry for platform dispatch instead of if-else chains. `read_memory_info()` SHALL dispatch via `_PLATFORM_READERS.get(sys.platform)` with a fallback that returns `None`. Adding a new platform SHALL require only registering a new entry in `_PLATFORM_READERS`, not modifying `read_memory_info()`.

#### Scenario: RAM guard passes with sufficient memory
- **GIVEN** available RAM is 3.0 GB and min_gb is 1.5
- **WHEN** check_ram_guard is called
- **THEN** no exception is raised

#### Scenario: RAM guard fails with insufficient memory
- **GIVEN** available RAM is 1.0 GB and min_gb is 1.5
- **WHEN** check_ram_guard is called
- **THEN** a RAMGuardError is raised

#### Scenario: read_memory_info returns None on unsupported platform
- **GIVEN** a platform where memory reading is not supported
- **WHEN** read_memory_info is called
- **THEN** None is returned (no crash)

#### Scenario: New platform is added without modifying read_memory_info
- **GIVEN** a new `_read_memory_info_macos` function is registered in `_PLATFORM_READERS`
- **WHEN** `read_memory_info()` is called on macOS
- **THEN** the macOS reader is dispatched without any changes to the `read_memory_info()` function body

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

