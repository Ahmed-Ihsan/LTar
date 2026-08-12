## MODIFIED Requirements

### Requirement: LLM engine adapter protocol

`LLMEngineAdapter` SHALL be a PEP 544 Protocol with a `generate(system_prompt, user_prompt, *, model, temperature, max_tokens, timeout) -> str` method. `OllamaEngineAdapter` is the concrete implementation using the Ollama Python client. It is constructed with `(client, *, model, host)` and exposes a `model` property. The 6-argument generate signature is the mandated adapter contract (ARCHITECTURE.md §5.3). `OllamaEngineAdapter` SHALL implement the context-manager protocol (`__enter__` returning `self`, `__exit__` calling `close()`) and an idempotent `close()` method that closes the underlying `ollama.Client` HTTP connection (guarded by `hasattr(self._client, "close")` for safety).

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

#### Scenario: OllamaEngineAdapter as context manager closes the client
- **GIVEN** an OllamaEngineAdapter used in a `with` statement
- **WHEN** the context exits
- **THEN** the underlying `ollama.Client` is closed via `close()` and the HTTP connection is released

#### Scenario: close is idempotent
- **GIVEN** an OllamaEngineAdapter whose `close()` has already been called
- **WHEN** `close()` is called again
- **THEN** no exception is raised and no double-close occurs

### Requirement: Embedding adapter protocol

`EmbeddingAdapter` SHALL be a PEP 544 Protocol with `embed(text) -> list[float]` and `embed_batch(texts, batch_size) -> list[list[float]]`. `Embedder` is the concrete Ollama implementation constructed with `(client, *, model, host)` and exposes a `model` property. `EMBED_DIM` = 768 (nomic-embed-text dimension). `DEFAULT_BATCH_SIZE` = 32. `Embedder` SHALL implement the context-manager protocol (`__enter__` returning `self`, `__exit__` calling `close()`) and an idempotent `close()` method that closes the underlying `ollama.Client` HTTP connection. The module-level `_default_embedder` global and `_get_default_embedder` helper SHALL NOT exist; callers MUST pass an explicit `Embedder` instance (DIP).

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

#### Scenario: Embedder as context manager closes the client
- **GIVEN** an Embedder used in a `with` statement
- **WHEN** the context exits
- **THEN** the underlying `ollama.Client` is closed via `close()` and the HTTP connection is released

#### Scenario: no module-level default embedder global
- **GIVEN** the `embeddings` module is imported
- **WHEN** its module-level attributes are inspected
- **THEN** there is no `_default_embedder` attribute and no `_get_default_embedder` function; every caller passes an explicit `Embedder` instance

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
