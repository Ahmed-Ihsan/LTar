## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: LLM engine adapter protocol

`LLMEngineAdapter` SHALL be a PEP 544 Protocol with a `generate(system_prompt, user_prompt, *, model, temperature, max_tokens, timeout) -> str` method. `OllamaEngineAdapter` is the concrete implementation using the Ollama Python client. It is constructed with `(client, *, model, host)` and exposes a `model` property. The constructor SHALL NOT call `load_config()` — all configuration MUST be passed as keyword-only arguments by the caller. The 6-argument generate signature is the mandated adapter contract (ARCHITECTURE.md §5.3).

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

#### Scenario: Constructor does not call load_config
- **GIVEN** the `OllamaEngineAdapter.__init__` source is inspected
- **WHEN** its body is read
- **THEN** it does not contain any call to `load_config()`; all config values are received as keyword-only constructor arguments

### Requirement: Embedding adapter protocol

`EmbeddingAdapter` SHALL be a PEP 544 Protocol with `embed(text) -> list[float]` and `embed_batch(texts, batch_size) -> list[list[float]]`. `Embedder` is the concrete Ollama implementation constructed with `(client, *, model, host)` and exposes a `model` property. The constructor SHALL NOT call `load_config()` — all configuration MUST be passed as keyword-only arguments by the caller. `EMBED_DIM` = 768 (nomic-embed-text dimension). `DEFAULT_BATCH_SIZE` = 32.

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

#### Scenario: Constructor does not call load_config
- **GIVEN** the `Embedder.__init__` source is inspected
- **WHEN** its body is read
- **THEN** it does not contain any call to `load_config()`; all config values are received as keyword-only constructor arguments

### Requirement: Structured run logging

`RunLogger` SHALL write JSON lines per node execution to a JSONL file. It is constructed with `(log_dir, run_id)`, exposes `run_id` and `path` properties, and has a `log_node(node_name, latency_ms, state)` method. The `log_node` method SHALL be decomposed: `_extract_state_snapshot(state) -> dict` handles state field extraction, `_serialize_record(node_name, latency_ms, snapshot) -> str` handles JSON serialization. `log_node` SHALL orchestrate these helpers and be ≤ 20 lines. It supports context manager protocol (`__enter__`/`__exit__`) and a `close()` method.

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

#### Scenario: log_node is ≤ 20 lines
- **GIVEN** the `log_node` method
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 20 lines, delegating to `_extract_state_snapshot` and `_serialize_record`
