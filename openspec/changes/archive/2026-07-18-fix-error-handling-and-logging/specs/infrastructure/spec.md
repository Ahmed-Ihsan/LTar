## MODIFIED Requirements

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

`EmbeddingAdapter` SHALL be a PEP 544 Protocol with `embed(text) -> list[float]` and `embed_batch(texts, batch_size) -> list[list[float]]`. `Embedder` is the concrete Ollama implementation constructed with `(client, *, model, host)` and exposes a `model` property. `EMBED_DIM` = 768 (nomic-embed-text dimension). `DEFAULT_BATCH_SIZE` = 32. `Embedder.embed` and `Embedder.embed_batch` SHALL catch exceptions in a single `except Exception as e: raise translate_engine_error(e, kind="embedding") from e` block — duplicate `except` blocks that both delegate to `translate_engine_error` SHALL be collapsed into one.

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

#### Scenario: a single except block delegates to translate_engine_error
- **GIVEN** the `Embedder.embed` source
- **WHEN** its exception handling is inspected
- **THEN** there is exactly one `except Exception as e:` block that delegates to `translate_engine_error(e, kind="embedding")` — no duplicate blocks
