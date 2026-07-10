## Purpose

The adapter layer: LLM engine adapter (Ollama), embedding adapter, system memory / RAM guard, and structured run logging. This component wraps all external runtime dependencies (Ollama daemon, OS memory APIs, filesystem logging) behind protocols so the pipeline and interfaces depend on abstractions, not concretions (DIP).

## Requirements

### Requirement: LLM engine adapter protocol

`LLMEngineAdapter` SHALL be a PEP 544 Protocol with a `generate(system_prompt, user_prompt, *, model, temperature, max_tokens, timeout) -> str` method. `OllamaEngineAdapter` is the concrete implementation using the Ollama Python client. It is constructed with `(client, *, model, host)` and exposes a `model` property. The 6-argument generate signature is the mandated adapter contract (ARCHITECTURE.md §5.3).

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

### Requirement: Embedding adapter protocol

`EmbeddingAdapter` SHALL be a PEP 544 Protocol with `embed(text) -> list[float]` and `embed_batch(texts, batch_size) -> list[list[float]]`. `Embedder` is the concrete Ollama implementation constructed with `(client, *, model, host)` and exposes a `model` property. `EMBED_DIM` = 768 (nomic-embed-text dimension). `DEFAULT_BATCH_SIZE` = 32.

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

### Requirement: System memory and RAM guard

`read_memory_info() -> MemoryInfo | None` SHALL read total and available system RAM. `available_ram_gb() -> float | None` returns available RAM in GiB. `check_ram_guard(min_gb: float = RAM_GUARD_MIN_GB) -> None` raises `RAMGuardError` if available RAM is below the threshold. `RAM_GUARD_MIN_GB` = 1.5. `MemoryInfo` is a dataclass with total_bytes and available_bytes.

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

### Requirement: Structured run logging

`RunLogger` SHALL write JSON lines per node execution to a JSONL file. It is constructed with `(log_dir, run_id)`, exposes `run_id` and `path` properties, and has a `log_node(node_name, latency_ms, state)` method. It supports context manager protocol (`__enter__`/`__exit__`) and a `close()` method.

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
