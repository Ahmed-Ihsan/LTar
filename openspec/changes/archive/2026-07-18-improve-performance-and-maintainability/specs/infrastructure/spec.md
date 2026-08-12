## MODIFIED Requirements

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
