## 1. Config layer

- [x] 1.1 Add `ollama_num_ctx: int = 2048` field to `AppConfig` in `src/config/config.py`, and add `"ollama_num_ctx"` to the `_positive_int` field validator's field list.
- [x] 1.2 Add `ollama_num_ctx: 2048` key with an explanatory comment to `config.yaml` (near the other LLM runtime settings, after `llm_timeout`).
- [x] 1.3 Verify: `python -c "from src.config import AppConfig; c = AppConfig(); assert c.ollama_num_ctx == 2048"`.

## 2. Infrastructure layer (adapter)

- [x] 2.1 Add `num_ctx: int | None = None` keyword-only parameter to `OllamaEngineAdapter.__init__` in `src/components/infrastructure/llm.py`; add `"_num_ctx"` to `__slots__`; store `self._num_ctx`.
- [x] 2.2 In `OllamaEngineAdapter.generate`, conditionally add `"num_ctx": self._num_ctx` to the `options` dict when `self._num_ctx is not None`.
- [x] 2.3 Verify: `python -c "from src.components.infrastructure.llm import OllamaEngineAdapter; a = OllamaEngineAdapter(model='m', host='h', num_ctx=2048); assert a._num_ctx == 2048"`.

## 3. Interface layer (composition root wiring)

- [x] 3.1 In `src/components/interfaces/cli.py` `_construct_adapters`, pass `num_ctx=cfg.ollama_num_ctx` to `OllamaEngineAdapter(...)` on the Ollama/llamacpp path.
- [x] 3.2 Verify: existing `test_ollama_backend_path_unchanged` test still passes (the adapter is still an `OllamaEngineAdapter`).

## 4. Tests

- [x] 4.1 Add config tests to `tests/test_config.py`: default is 2048, custom value accepted, zero/negative rejected, config.yaml override.
- [x] 4.2 Add adapter test to `tests/test_memory.py`: `generate` with `num_ctx=2048` includes `"num_ctx": 2048` in the options dict passed to `client.chat`; `num_ctx=None` omits it.
- [x] 4.3 Add CLI wiring test to `tests/test_cli.py`: `_construct_adapters` with `ollama_num_ctx=2048` produces an `OllamaEngineAdapter` whose `_num_ctx` is 2048.

## 5. Full verification

- [x] 5.1 Run `pytest --tb=short -q` — all tests pass (652 passed, 5 skipped, 3 deselected).
- [x] 5.2 Run `ruff check src/ tests/` — clean (All checks passed).
- [x] 5.3 Run `mypy src/` — 5 pre-existing errors in `mcp_server.py` (untyped decorators, unrelated to this change); changed files are clean.
- [x] 5.4 Run `openspec validate --all` — 0 failures (12 passed).
- [x] 5.5 Archive the change: `openspec archive add-ollama-num-ctx-config`.