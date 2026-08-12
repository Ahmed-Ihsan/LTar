## Why

On an 8 GB VRAM GPU (e.g. NVIDIA RTX 4060 Laptop), the Ollama daemon cannot
simultaneously hold `nomic-embed-text` (~567 MiB VRAM) and `gemma3:4b`
(3.3 GB, 35 layers) when `gemma3:4b` auto-selects `num_ctx=4096`. The KV
cache + cuBLAS GEMM workspace overflow the remaining ~6.7 GiB, causing a
CUDA memory allocation failure inside the llama runner:

```
fatal   : Memory allocation failure
CUDA error: the requested functionality is not supported
  cublasGemmEx(... CUBLAS_COMPUTE_16F ...)
llama runner terminated (exit status 1)
model failed to load, this may be due to resource limitations
```

The `OllamaEngineAdapter` currently passes only `temperature` and
`num_predict` in the Ollama `options` dict — it never sends `num_ctx`, so
Ollama auto-picks a context size based on total VRAM (4096 on an 8 GB
card). With the embed model resident, that auto-selected size is too
large. A configurable `ollama_num_ctx` (default 2048) caps the KV-cache
footprint so both models coexist within the 8 GB ceiling, while keeping
the pipeline-level `context_window: 8192` (prompt-truncation budget)
unchanged and independent.

## What Changes

- **ADDED:** `AppConfig.ollama_num_ctx` — a positive-int config field
  (default 2048) that controls the Ollama KV-cache context size
  (`num_ctx` in the Ollama `options` dict). Validated as a positive
  integer by the existing `_positive_int` field validator.
- **MODIFIED:** `config.yaml` — new top-level `ollama_num_ctx: 2048`
  key with a comment explaining its purpose and the distinction from
  `context_window`.
- **MODIFIED:** `OllamaEngineAdapter.__init__` — accepts a new
  keyword-only `num_ctx: int | None = None` parameter. When non-None,
  the adapter includes `"num_ctx": self._num_ctx` in the `options` dict
  passed to `client.chat`. When None (the constructor default for
  backward-compatible direct construction), `num_ctx` is omitted and
  Ollama auto-selects (current behavior).
- **MODIFIED:** `src/components/interfaces/cli.py` `_construct_adapters`
  — passes `num_ctx=cfg.ollama_num_ctx` to `OllamaEngineAdapter` on the
  Ollama/llamacpp path. The Gemini path is unaffected (Gemini manages
  context differently).
- No changes to the `LLMEngineAdapter` protocol `generate` signature, the
  `MockEngineAdapter`, `GeminiEngineAdapter`, LangGraph nodes, prompts,
  or any pipeline behavior. The `context_window` field remains the
  pipeline-level prompt-truncation budget and is unrelated to
  `ollama_num_ctx`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `config`: ADDED `ollama_num_ctx` field to `AppConfig` with positive-int
  validation and a 2048 default.
- `infrastructure`: MODIFIED `OllamaEngineAdapter` to accept and forward
  `num_ctx` in the Ollama `options` dict.

## Impact

- **Affected code:**
  `src/config/config.py` (new field + validator entry),
  `src/components/infrastructure/llm.py` (constructor + `__slots__` +
  options dict),
  `src/components/interfaces/cli.py` (`_construct_adapters` wiring),
  `config.yaml` (new key).
- **APIs:** No protocol signature changes. The `generate` contract is
  unchanged; `num_ctx` is an adapter-construction parameter, not a
  per-call parameter.
- **Dependencies:** None added or changed.
- **Tests:** New unit tests for the config field validation, adapter
  options-dict construction, and CLI wiring; existing adapter tests
  remain green (constructor default of None preserves current behavior
  for direct construction).
- **Runtime behavior:** On the 8 GB target profile, `gemma3:4b` now
  loads with a 2048-token KV cache alongside the resident embed model,
  eliminating the CUDA OOM. Users with larger VRAM can raise
  `ollama_num_ctx` in `config.yaml`.

## Scope

### In scope

- `AppConfig.ollama_num_ctx` field, validator, and `config.yaml` default.
- `OllamaEngineAdapter` constructor change + options-dict forwarding.
- `_construct_adapters` wiring on the Ollama/llamacpp path.
- Unit tests for all three layers.

### Out of scope

- Changing the `LLMEngineAdapter.generate` protocol signature.
- Changing `context_window` (pipeline prompt-truncation budget).
- `GeminiEngineAdapter` (Gemini manages context server-side).
- `Embedder` (embedding model context is not tunable via this field).
- GPU layer offload tuning (`num_gpu`) — a separate future change if
  needed.

## Migration path

1. Add `ollama_num_ctx` to `AppConfig` with default 2048.
2. Add `ollama_num_ctx: 2048` to `config.yaml`.
3. Add `num_ctx` parameter to `OllamaEngineAdapter.__init__` and forward
   it in the options dict.
4. Update `_construct_adapters` to pass `cfg.ollama_num_ctx`.
5. Add tests.
6. Run full verification suite.

No data migration, no schema migration, no breaking changes. Existing
`config.yaml` files without the key get the Pydantic default (2048).

## Rollback plan

Revert the four code/config changes. The adapter constructor default of
None restores the original Ollama auto-select behavior. No persistent
state is affected.

## Affected files

| Old path | New path |
|---|---|
| `src/config/config.py` | `src/config/config.py` (modified) |
| `src/components/infrastructure/llm.py` | `src/components/infrastructure/llm.py` (modified) |
| `src/components/interfaces/cli.py` | `src/components/interfaces/cli.py` (modified) |
| `config.yaml` | `config.yaml` (modified) |
| `tests/test_config.py` | `tests/test_config.py` (modified) |
| `tests/test_memory.py` | `tests/test_memory.py` (modified) |
| `tests/test_cli.py` | `tests/test_cli.py` (modified) |
