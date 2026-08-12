## 1. Exception hierarchy (foundation)

- [ ] 1.1 Add `LLMConnectionError(LLMRuntimeError)` and `LLMTimeoutError(LLMConnectionError)` to `src/components/translation_pipeline/exceptions.py`
- [ ] 1.2 Add `GeminiAuthError(LLMRuntimeError)` and `GeminiQuotaError(LLMRuntimeError)` to the same module
- [ ] 1.3 Re-export all four new exceptions from `src/components/translation_pipeline/__init__.py`
- [ ] 1.4 Verify: `python -c "from src.components.translation_pipeline import LLMConnectionError, LLMTimeoutError, GeminiAuthError, GeminiQuotaError"` succeeds
- [ ] 1.5 Verify: `pytest -q tests/test_exceptions.py` (or the existing exception-hierarchy test) passes; add `issubclass` assertions for the four new classes if no such test exists
- [ ] 1.6 Verify: existing `OllamaConnectionError`, `OllamaTimeoutError`, `LlamaCppConnectionError`, `LlamaCppTimeoutError` base classes are unchanged (grep confirms no reparenting)

## 2. Config additions

- [ ] 2.1 In `src/config/config.py`, change `llm_backend: str = "ollama"` to `llm_backend: Literal["ollama", "llamacpp", "gemini"] = "ollama"` (import `Literal` from `typing`)
- [ ] 2.2 Add fields to `AppConfig`: `gemini_model: str = "gemini-2.0-flash"`, `gemini_embed_model: str = "text-embedding-004"`, `gemini_timeout: float = 120.0`, `gemini_rpm: int = 15`, `gemini_api_key: str | None = None`
- [ ] 2.3 Add validators: `gemini_timeout` non-negative float (extend `_non_negative_float`); `gemini_rpm` positive int (add to `_positive_int` or a new validator)
- [ ] 2.4 In `load_config`, read `os.environ.get("GEMINI_API_KEY")`; reject a `gemini_api_key` key present in the YAML with `ConfigError`; when `llm_backend == "gemini"` and the env var is unset/empty, raise `ConfigError`; otherwise populate `cfg.gemini_api_key` via `model_copy(update=...)`
- [ ] 2.5 Mask `gemini_api_key` in `AppConfig` repr (Pydantic field config or a custom `__repr__`) so the `config load` Typer command never prints the key in cleartext
- [ ] 2.6 Verify: `python -c "from src.config import load_config; load_config()"` succeeds with the default `ollama` config and `GEMINI_API_KEY` unset
- [ ] 2.7 Verify: a unit test asserting `llm_backend: gemini` + valid `GEMINI_API_KEY` loads; `gemini` + unset key raises `ConfigError`; `ollama` + unset key succeeds; a `gemini_api_key` key in YAML raises `ConfigError`; an unknown `llm_backend` raises `ConfigError` listing the three valid values

## 3. Gemini adapter

- [ ] 3.1 Create `src/components/infrastructure/gemini.py` with `GeminiEngineAdapter` constructed via `(*, model, embed_model, api_key, timeout, rpm)` keyword-only args; lazily `import google.genai` inside `__init__` (not at module top level)
- [ ] 3.2 Implement `generate(system_prompt, user_prompt, *, model, temperature, max_tokens, timeout) -> str` satisfying `LLMEngineAdapter`; do NOT call `check_ram_guard()`; acquire/release the rate-limiter permit in a `try/finally`
- [ ] 3.3 Implement `embed(text) -> list[float]` and `embed_batch(texts, batch_size) -> list[list[float]]` satisfying `EmbeddingAdapter`; delegate `batch_size` validation to `src.utils.batch_size.validate_batch_size`; enforce `EMBED_DIM` (768) on every vector, raising `EmbeddingError` on mismatch
- [ ] 3.4 Implement the context-manager protocol (`__enter__`/`__exit__`) and an idempotent `close()`; implement `__repr__` masking `_api_key`
- [ ] 3.5 Implement `_translate_gemini_error(err, *, model, kind) -> Exception` mapping: 401/403/PermissionDenied → `GeminiAuthError`; 429/ResourceExhausted → `GeminiQuotaError`; timeout/deadline-exceeded → `LLMTimeoutError`; connection/service-unavailable → `LLMConnectionError`; fallback → `LLMRuntimeError` (kind="llm") or `EmbeddingError`/`EmbeddingConnectionError` (kind="embedding"). Never include `api_key` in the message.
- [ ] 3.6 Implement the `threading.Semaphore`-based rate limiter (`rpm` permits); when exhausted raise `GeminiQuotaError` without contacting the API; release the permit in a `finally` block on all paths
- [ ] 3.7 Re-export `GeminiEngineAdapter` from `src/components/infrastructure/__init__.py`
- [ ] 3.8 Verify: `python -c "import src.components.infrastructure.gemini"` succeeds with `google-genai` NOT installed (lazy import)
- [ ] 3.9 Verify: `isinstance(GeminiEngineAdapter(...), LLMEngineAdapter)` and `isinstance(..., EmbeddingAdapter)` are both `True` (runtime-checkable protocols) with a mocked client

## 4. Gemini adapter tests (mocked — no real cloud calls)

- [ ] 4.1 Create `tests/test_gemini_adapter.py` with a mocked `google.genai` client (monkeypatch the lazy import target)
- [ ] 4.2 Test `generate` returns the mocked completion string; test `embed`/`embed_batch` return 768-dim vectors; test `embed_batch` enforces 768-dim (raises `EmbeddingError` on a 512-dim mock) and rejects `batch_size <= 0`
- [ ] 4.3 Test exception mapping: 401/403 → `GeminiAuthError`; 429 → `GeminiQuotaError`; timeout → `LLMTimeoutError`; connection error → `LLMConnectionError`; unknown → `LLMRuntimeError`; embedding connection error → `EmbeddingConnectionError`
- [ ] 4.4 Test the rate limiter: calls within budget succeed; exceeding `rpm` raises `GeminiQuotaError` without an API call; a failed call still releases its permit
- [ ] 4.5 Test the context manager closes the adapter exactly once; test `close()` is idempotent
- [ ] 4.6 Test security: `repr(adapter)` does not contain the `api_key` value; a raised mapped exception's message does not contain the `api_key` value
- [ ] 4.7 Test `generate` does NOT call `check_ram_guard` (monkeypatch `check_ram_guard` and assert it was not called)
- [ ] 4.8 Verify: `pytest -q tests/test_gemini_adapter.py` passes; no test makes a real network call (assert via a `socket` guard / `monkeypatch` of the client)

## 5. Composition root wiring

- [ ] 5.1 In `src/components/interfaces/cli.py::_construct_adapters`, branch on `cfg.llm_backend`: when `"gemini"`, lazily import `GeminiEngineAdapter` and construct it with `model=cfg.gemini_model, embed_model=cfg.gemini_embed_model, api_key=cfg.gemini_api_key, timeout=cfg.gemini_timeout, rpm=cfg.gemini_rpm`; bind the same instance to both `Adapters.llm` and `Adapters.embedder`
- [ ] 5.2 When `cfg.llm_backend == "gemini"` and `cfg.gemini_api_key is None`, print an error naming `GEMINI_API_KEY` and `raise typer.Exit(code=1)` without constructing any adapter (defensive — `load_config` already rejects this)
- [ ] 5.3 Keep the `"ollama"` path exactly as today (no behavioral regression)
- [ ] 5.4 Verify: a test asserting `_construct_adapters(cfg_gemini)` returns an `Adapters` whose `llm` and `embedder` are the same `GeminiEngineAdapter` instance; a test asserting `_construct_adapters(cfg_ollama)` still constructs `OllamaEngineAdapter` + `Embedder`
- [ ] 5.5 Verify: a test asserting `google.genai` is NOT in `sys.modules` after `_construct_adapters` runs on the `ollama` path

## 6. Doctor command branch

- [ ] 6.1 In `src/components/interfaces/diagnostics.py`, add `_check_gemini_api_key(cfg) -> CheckResult` (OK iff `cfg.gemini_api_key` is non-None and non-empty) and `_check_gemini_reachable(cfg) -> CheckResult` (construct a `GeminiEngineAdapter` and issue a minimal list-models ping; map errors to a FAIL `CheckResult`)
- [ ] 6.2 In `src/components/interfaces/commands/doctor.py`, branch on `cfg.llm_backend`: when `"gemini"`, run `_check_gemini_api_key` + `_check_gemini_reachable` + the existing ChromaDB/glossary/TM checks, and SKIP `_check_ollama_reachable`, `_check_models_present`, and the LLM-RAM-budget portion of `_check_ram_headroom`; when `"ollama"`, run the existing checks unchanged
- [ ] 6.3 A failed `_check_gemini_api_key` or `_check_gemini_reachable` SHALL cause `doctor` to exit with code 2 (matching the Ollama-failed exit code)
- [ ] 6.4 Verify: a mocked `doctor` test with `llm_backend: gemini` renders "Gemini API key present" and "Gemini API reachable" CheckResults and does NOT render "Ollama daemon reachable" or "Required models present"
- [ ] 6.5 Verify: a mocked `doctor` test with `llm_backend: ollama` renders the existing Ollama checks unchanged (no regression)

## 7. Dependency + packaging

- [ ] 7.1 Add `google-genai>=1.0,<2` to `requirements.txt` (alphabetically in the appropriate section)
- [ ] 7.2 Add `"google-genai>=1.0,<2"` to `pyproject.toml [project.dependencies]`
- [ ] 7.3 Add a mypy override in `pyproject.toml`: `[[tool.mypy.overrides]] module = "google.genai.*" ignore_missing_imports = true`
- [ ] 7.4 Add a ruff per-file-ignore in `pyproject.toml`: `"src/components/infrastructure/gemini.py" = ["PLR0913"]` (mirrors the `llm.py` precedent for the 6-arg protocol signature)
- [ ] 7.5 Confirm the pinned `google-genai` version was published >7 days ago (check PyPI release date); do not use `latest` or an unbounded range
- [ ] 7.6 Verify: `pip install -r requirements.txt` succeeds and `python -c "import google.genai"` works
- [ ] 7.7 Verify: `pip install -e .` succeeds and `python -c "import src.app"` works

## 8. CLI tests

- [ ] 8.1 Update `tests/test_cli.py` to add a test: with `llm_backend: gemini` + a mocked `GeminiEngineAdapter`, `_construct_adapters` returns an `Adapters` with `isinstance(adapters.llm, GeminiEngineAdapter)` and `adapters.llm is adapters.embedder`
- [ ] 8.2 Add a test: a Gemini auth/quota/connection exception raised by the pipeline maps to CLI exit code 2 (connection/auth family) via `handle_pipeline_errors`
- [ ] 8.3 Verify: `pytest -q tests/test_cli.py` passes

## 9. Documentation

- [ ] 9.1 Update `config.yaml`: change the `llm_backend` comment to `# ollama | llamacpp | gemini` (default stays `ollama`); add commented `gemini_*` keys with a note that `GEMINI_API_KEY` is read from the env var and must NOT be placed in this file
- [ ] 9.2 Update `README.md` §3 (stack): document the Gemini backend as an opt-in cloud alternative; note `ollama` remains the default
- [ ] 9.3 Update `README.md` §5.4 (configure): document `llm_backend: gemini`, the `gemini_*` config keys, the `GEMINI_API_KEY` env var, and the `pip install -r requirements.txt` step to get `google-genai`
- [ ] 9.4 Update `AGENTS.md` §3 (constraints): note that `gemini` is the **only** backend that makes cloud calls, that it requires `GEMINI_API_KEY`, and that the offline-first default (`ollama`) is unchanged
- [ ] 9.5 Verify: grep `AGENTS.md` and `README.md` to confirm no contradiction between "offline-first default" and the Gemini documentation

## 10. Final verification

- [ ] 10.1 Run `ruff check src/ tests/` — must be clean (including the new `gemini.py` and `test_gemini_adapter.py`)
- [ ] 10.2 Run `mypy src/` — must be clean in strict mode (the `google.genai.*` override suppresses missing-imports only)
- [ ] 10.3 Run `pytest --tb=short -q` — full suite green (excluding `slow`); Gemini tests are mocked, no network
- [ ] 10.4 Run `openspec validate add-gemini-api-backend` — must pass
- [ ] 10.5 Run `openspec validate --all` — must pass
- [ ] 10.6 Run `openspec status --change add-gemini-api-backend` — should report 4/4 artifacts complete (proposal, design, specs, tasks)
- [ ] 10.7 Verify: with `llm_backend: ollama` and `google-genai` installed, `iraqi-translate doctor` runs the Ollama checks and never imports `google.genai` (assert via `sys.modules` in a test)
- [ ] 10.8 Verify: with `llm_backend: gemini` + `GEMINI_API_KEY` set + mocked client, `iraqi-translate doctor` renders the Gemini checks and exits 0 on success / 2 on a mocked auth failure
