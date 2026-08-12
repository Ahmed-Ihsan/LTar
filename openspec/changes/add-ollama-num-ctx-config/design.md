## Context

The `OllamaEngineAdapter` (`src/components/infrastructure/llm.py`) wraps the
Ollama Python client's `chat` endpoint. It currently builds an `options` dict
containing only `temperature` and `num_predict`, then calls
`self._client.chat(model=..., messages=..., options=..., keep_alive=...)`.

Ollama auto-selects `num_ctx` (the KV-cache context window) based on available
VRAM when the caller does not specify it. On an 8 GB GPU with the embed model
already resident (~567 MiB), Ollama picks 4096 — too large for `gemma3:4b`'s
weights + KV cache + cuBLAS workspace in the remaining ~6.7 GiB, causing a
CUDA allocation failure and a 500 "model failed to load" error.

The pipeline-level `context_window: 8192` config field is a *prompt-truncation*
budget used by the nodes to limit assembled context before sending it to the
LLM. It is not the Ollama KV-cache size. These are distinct concerns and must
remain independent.

## Goals / Non-Goals

### Goals

- Allow the user to cap the Ollama KV-cache context size via `config.yaml`.
- Default to 2048 so the 8 GB target profile works out of the box with both
  the embed model and `gemma3:4b` resident on the GPU.
- Keep the `LLMEngineAdapter.generate` protocol signature unchanged.
- Keep `context_window` as the independent pipeline prompt-truncation budget.

### Non-Goals

- Tuning GPU layer offload (`num_gpu`).
- Changing the Gemini backend (server-side context management).
- Changing the embedding adapter.
- Changing prompt assembly or truncation logic.

## Decisions

### D1: Config field, not a generate parameter

`num_ctx` is passed to the adapter **constructor**, not to `generate`. This
keeps the `LLMEngineAdapter` protocol's `generate` signature unchanged (no
impact on `MockEngineAdapter`, `GeminiEngineAdapter`, or any node/pipeline
code). The adapter stores the value and includes it in every `options` dict.

### D2: Constructor default is None (backward compatible)

`OllamaEngineAdapter.__init__(..., num_ctx: int | None = None)`. When None,
`num_ctx` is omitted from the options dict — Ollama auto-selects (current
behavior). This preserves backward compatibility for code that constructs the
adapter directly (e.g. existing tests). The CLI always passes
`cfg.ollama_num_ctx` (an int, default 2048), so production behavior is fixed.

### D3: Config default is 2048

`AppConfig.ollama_num_ctx: int = 2048`. This is the safe value for the 8 GB
target profile (verified: `gemma3:4b` at `num_ctx=2048` loads successfully
alongside `nomic-embed-text` on an 8 GB RTX 4060 Laptop). Users with larger
VRAM can raise it. The existing `_positive_int` validator enforces > 0.

### D4: Separate from `context_window`

`ollama_num_ctx` and `context_window` are independent fields with different
semantics. `context_window` (8192) limits how much context the pipeline
assembles before truncation. `ollama_num_ctx` (2048) is the Ollama KV-cache
budget. The pipeline may assemble up to 8192 tokens of context, but Ollama
will only retain 2048 in its KV cache (truncating the rest server-side). This
is acceptable because the translator/auditor prompts are well under 2048
tokens for typical single-article translations.

## Risks / Trade-offs

- **Reduced context at the Ollama level:** With `num_ctx=2048`, very long
  prompts (> 2048 tokens) will be truncated by Ollama server-side. The
  pipeline's `context_window: 8192` truncation is a separate, earlier guard.
  For typical Iraqi legal article translations, the assembled prompt is well
  under 2048 tokens. Users with longer inputs can raise `ollama_num_ctx`.
- **No auto-detection of VRAM:** The field is static, not auto-tuned. A user
  moving from an 8 GB to a 16 GB machine must manually raise the value. This
  is consistent with the project's config-driven philosophy.

## Target directory tree

No new files. Modified files only:

```
src/config/config.py                          (modified — new field)
src/components/infrastructure/llm.py          (modified — constructor + options)
src/components/interfaces/cli.py              (modified — wiring)
config.yaml                                   (modified — new key)
tests/test_config.py                          (modified — new tests)
tests/test_memory.py                          (modified — new adapter test)
tests/test_cli.py                             (modified — new wiring test)
```

## Component dependency diagram

```
config.yaml
    │
    ▼
AppConfig (src/config/config.py)
    │  .ollama_num_ctx: int = 2048
    ▼
_construct_adapters (src/components/interfaces/cli.py)
    │  num_ctx=cfg.ollama_num_ctx
    ▼
OllamaEngineAdapter (src/components/infrastructure/llm.py)
    │  self._num_ctx → options["num_ctx"]
    ▼
ollama.Client.chat(options={..., "num_ctx": 2048})
```

No new inter-component dependencies. The dependency graph remains acyclic:
`cli.py → infrastructure.llm` (existing edge, no new imports).

## models.py contents

No new models. `AppConfig` gains one field:

```python
ollama_num_ctx: int = 2048   # Ollama KV-cache context size (VRAM budget)
```

Added to the `_positive_int` field validator's field list.

## Inter-component communication protocol

No new protocols. The `LLMEngineAdapter` protocol is unchanged. The only new
data flow is `cfg.ollama_num_ctx → OllamaEngineAdapter(num_ctx=...)`, which is
a constructor argument at the composition root (`_construct_adapters`).

## Migration strategy

1. `src/config/config.py`: add `ollama_num_ctx: int = 2048` field, add to
   `_positive_int` validator field list.
2. `config.yaml`: add `ollama_num_ctx: 2048` with a comment.
3. `src/components/infrastructure/llm.py`: add `num_ctx: int | None = None`
   to `__init__`, add `"_num_ctx"` to `__slots__`, store it, and conditionally
   add `"num_ctx": self._num_ctx` to the options dict in `generate`.
4. `src/components/interfaces/cli.py`: pass `num_ctx=cfg.ollama_num_ctx` to
   `OllamaEngineAdapter(...)` in `_construct_adapters`.
5. Tests: config field default + validation, adapter options dict, CLI wiring.

## app.py / entry point design

No changes to `src/app.py`. The composition root for adapters is
`_construct_adapters` in `cli.py`, which is the only place that needs the new
wiring.

## pyproject.toml changes

None.

## ruff per-file-ignores path migrations

None — no files moved or added.
