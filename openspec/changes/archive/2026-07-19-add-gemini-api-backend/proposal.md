## Why

The Iraqi Legal Translation Agent is engineered as **offline-first** with a
hard constraint of *no cloud LLM calls*. That constraint exists so the system
runs on an 8 GB RAM machine with no internet — and it must stay the default.
However, not every user is on that machine. A user who **has** internet access
and a Google Gemini API key may prefer a hosted model such as
`gemini-2.0-flash` or `gemini-2.5-pro` for higher-quality Arabic⇄English legal
translation **without provisioning a local GPU** or fitting a quantized model
into 8 GB. Today that user has no path: the only fully-wired backend is
`ollama` (the `llamacpp` backend has exception stubs but no adapter
implementation — verified in `src/components/interfaces/cli.py::_construct_adapters`,
which constructs `OllamaEngineAdapter` unconditionally).

This change adds **Google Gemini API** as an **opt-in, cloud-based** backend
selectable via `config.yaml`. The offline-first guarantee is preserved because
`ollama` remains the default `llm_backend`; Gemini is only activated when the
user explicitly sets `llm_backend: gemini` and provides `GEMINI_API_KEY`.

The change is **additive at the protocol seam**: the translation pipeline,
glossary, retrieval, TM, and UI layers depend on the `LLMEngineAdapter` and
`EmbeddingAdapter` protocols (PEP 544), not on concretions. A new
`GeminiEngineAdapter` that satisfies both protocols slots in at the composition
root (`_construct_adapters`) with **zero changes to nodes, graph, prompts, or
UIs** (DIP, AGENTS.md §5). This is the textbook OCP extension the architecture
was designed for.

## What Changes

1. **New backend: `gemini`.** Add `gemini` as a valid `llm_backend` value
   (alongside `ollama` and `llamacpp`). `ollama` stays the default.
2. **New adapter: `GeminiEngineAdapter`** in
   `src/components/infrastructure/gemini.py`. It implements **both** the
   `LLMEngineAdapter` protocol (`generate`) and the `EmbeddingAdapter`
   protocol (`embed`, `embed_batch`) so a single backend selection wires both
   the LLM and the embedder through the existing `Adapters` bundle.
3. **New domain exceptions** in the existing hierarchy:
   `LLMConnectionError`, `LLMTimeoutError` (backend-agnostic, under
   `LLMRuntimeError`), plus `GeminiAuthError` and `GeminiQuotaError` for
   Gemini-specific failure modes (invalid API key, rate-limit/quota
   exhausted). Gemini API errors are mapped to these so nodes and the CLI
   only ever see domain exceptions (AGENTS.md §5, clean-code §3.2).
4. **Config additions** (`AppConfig`): `gemini_model` (default
   `gemini-2.0-flash`), `gemini_embed_model` (default `text-embedding-004`),
   `gemini_timeout` (default `120.0`), `gemini_rpm` (default `15`, free-tier
   RPM cap). `gemini_api_key` is read from the `GEMINI_API_KEY` environment
   variable only — **never** stored in `config.yaml`. `llm_backend` is
   narrowed from `str` to `Literal["ollama", "llamacpp", "gemini"]`.
5. **Composition-root branch**: `_construct_adapters` in
   `src/components/interfaces/cli.py` constructs `GeminiEngineAdapter` for
   both `llm` and `embedder` when `cfg.llm_backend == "gemini"`; otherwise the
   existing Ollama path is unchanged.
6. **`doctor` command branch**: when `llm_backend == "gemini"`, the doctor
   command checks `GEMINI_API_KEY` presence and pings the Gemini API (list
   models) instead of checking Ollama reachability / local model presence /
   LLM RAM budget. ChromaDB / glossary / TM checks remain unchanged.
7. **Rate limiting**: a `threading.Semaphore`-based limiter in
   `GeminiEngineAdapter` enforces the configured `gemini_rpm` to stay within
   the Gemini free-tier quota.
8. **Dependency**: add `google-genai>=1.0,<2` (the unified Google GenAI SDK)
   to `requirements.txt` and `pyproject.toml [project.dependencies]`, pinned
   to a version published >7 days ago. The SDK is **lazily imported** inside
   `gemini.py` so offline users who never select `gemini` do not need it
   installed for the package to import. A mypy `ignore_missing_imports`
   override is added for `google.genai.*`.
9. **Docs**: `README.md` §3 (stack) and §5.4 (configure) document the Gemini
   backend, the `GEMINI_API_KEY` env var, and model options. `AGENTS.md` §3
   (constraints) notes that `gemini` is the **only** backend that makes cloud
   calls and requires `GEMINI_API_KEY`, and that the offline-first default is
   unchanged.

**No breaking changes.** Existing `ollama` and `llamacpp` configurations and
code paths are untouched. No pipeline, node, prompt, graph, glossary,
retrieval, TM, or UI code is modified.

## Capabilities

### New Capabilities

None. No new bounded-context capability is introduced — Gemini is a new
**concrete adapter** behind the existing `infrastructure` capability's
`LLMEngineAdapter` / `EmbeddingAdapter` protocols.

### Modified Capabilities

- **`infrastructure`** — ADD a requirement for the `GeminiEngineAdapter`
  (dual-protocol: `LLMEngineAdapter` + `EmbeddingAdapter`), its exception
  mapping (Gemini API errors → `LLMConnectionError` / `LLMTimeoutError` /
  `GeminiAuthError` / `GeminiQuotaError` / `LLMRuntimeError` /
  `EmbeddingError` family), its rate limiter, its context-manager + idempotent
  close, and the rule that it SHALL NOT call the RAM guard (cloud inference).
  ADD a requirement for the new backend-agnostic and Gemini-specific
  exception classes in the existing hierarchy.
- **`config`** — MODIFY the `AppConfig` requirement to narrow `llm_backend`
  to `Literal["ollama", "llamacpp", "gemini"]` and ADD the Gemini config
  fields (`gemini_model`, `gemini_embed_model`, `gemini_timeout`,
  `gemini_rpm`, `gemini_api_key` from env). ADD a requirement that
  `gemini_api_key` MUST be read from the `GEMINI_API_KEY` env var and MUST
  NOT be read from `config.yaml`, and that `load_config` raises `ConfigError`
  when `llm_backend == "gemini"` and the key is absent.
- **`interfaces`** — MODIFY the `doctor` command requirement to branch on
  `llm_backend`: when `gemini`, check API-key presence + Gemini API
  connectivity instead of Ollama reachability / local model presence / LLM
  RAM budget. MODIFY the CLI dependency-injection requirement so
  `_construct_adapters` builds `GeminiEngineAdapter` for both `llm` and
  `embedder` when `cfg.llm_backend == "gemini"`.

## Impact

**Affected files (old path → new path):**

| Old path | New path | Change |
|---|---|---|
| `src/components/infrastructure/gemini.py` | (new) | NEW — `GeminiEngineAdapter` + rate limiter + error mapper |
| `src/components/infrastructure/__init__.py` | same | MODIFIED — re-export `GeminiEngineAdapter` |
| `src/components/translation_pipeline/exceptions.py` | same | MODIFIED — add `LLMConnectionError`, `LLMTimeoutError`, `GeminiAuthError`, `GeminiQuotaError` |
| `src/components/translation_pipeline/__init__.py` | same | MODIFIED — re-export new exceptions |
| `src/config/config.py` | same | MODIFIED — `llm_backend` Literal, Gemini fields, env-var read, validation |
| `config.yaml` | same | MODIFIED — document `gemini` in `llm_backend` comment (default stays `ollama`); no key stored |
| `src/components/interfaces/cli.py` | same | MODIFIED — `_construct_adapters` branches on `llm_backend` |
| `src/components/interfaces/diagnostics.py` | same | MODIFIED — add `_check_gemini_reachable` + `_check_gemini_api_key` |
| `src/components/interfaces/commands/doctor.py` | same | MODIFIED — branch checks on `llm_backend == "gemini"` |
| `requirements.txt` | same | MODIFIED — add `google-genai>=1.0,<2` |
| `pyproject.toml` | same | MODIFIED — add `google-genai` dep + mypy override for `google.genai.*` |
| `tests/test_gemini_adapter.py` | (new) | NEW — mocked-API tests |
| `tests/test_cli.py` | same | MODIFIED — assert `gemini` constructs `GeminiEngineAdapter` |
| `README.md` | same | MODIFIED — §3 stack, §5.4 configure |
| `AGENTS.md` | same | MODIFIED — §3 constraints note |

**APIs:** No public API change. `GeminiEngineAdapter` is a new concrete class
satisfying existing protocols. `AppConfig` gains new optional fields with
defaults (additive). `llm_backend` is narrowed from `str` to a 3-valued
`Literal` — this is a **non-breaking** tightening (any of the three strings
still validates; an unknown backend now fails fast with a clear `ConfigError`
instead of silently falling through to the Ollama path).

**Dependencies:** + `google-genai>=1.0,<2` (runtime, lazily imported). No
removals. The SDK is only exercised when `llm_backend == "gemini"`.

**Specs:** Delta specs modify `infrastructure`, `config`, and `interfaces`.
No source-of-truth requirement is REMOVED. The existing
`LLMEngineAdapter` / `EmbeddingAdapter` protocol requirements are preserved
unchanged — Gemini is an additional concretion, not a protocol change.

**Migration path:**
- **Users who want Gemini:** set `llm_backend: gemini` and
  `gemini_model: gemini-2.0-flash` in `config.yaml`, export
  `GEMINI_API_KEY=...`, run `pip install -r requirements.txt` to pick up
  `google-genai`, then run `iraqi-translate doctor` to verify connectivity.
- **Users who want to stay offline:** do nothing. `ollama` remains the
  default; `google-genai` is never imported on the Ollama code path.
- **No data migration, no DB schema changes.** The existing ChromaDB
  collection is 768-dim cosine; Gemini's `text-embedding-004` outputs 768-dim
  by default, so the existing collection is reusable. (If a user selects a
  Gemini embed model with a different dimension, the adapter SHALL reject it
  at construction with a clear error — see design.)

**Rollback plan:**
- Set `llm_backend: ollama` in `config.yaml`. The Gemini code path is never
  entered; `google-genai` is never imported. To fully remove the feature,
  `git revert` the change commit — all modifications are additive (new file +
  new exception subclasses + new config fields with defaults + a branch in
  the composition root). No irreversible state is created.

**Build impact:**
- `pip install -r requirements.txt` pulls `google-genai` (~a few MB). Offline
  users who never select `gemini` pay only the install cost; runtime import
  is lazy.
- `ruff`, `mypy --strict`, and `pytest` must remain green. Gemini tests mock
  the SDK — no real cloud calls in CI.

## Scope

**In scope:**
- `GeminiEngineAdapter` (LLM + embeddings, dual-protocol).
- New domain exceptions (`LLMConnectionError`, `LLMTimeoutError`,
  `GeminiAuthError`, `GeminiQuotaError`) and Gemini error mapping.
- `AppConfig` Gemini fields + `GEMINI_API_KEY` env-var loading + validation.
- `_construct_adapters` branch for `llm_backend == "gemini"`.
- `doctor` command branch for `llm_backend == "gemini"`.
- Rate limiter (semaphore, `gemini_rpm`).
- `google-genai` dependency (lazy import, mypy override).
- Mocked tests for the adapter, error mapping, rate limiting, context
  manager, idempotent close, and CLI construction.
- `README.md` and `AGENTS.md` documentation updates.

**Out of scope:**
- Implementing the `llamacpp` adapter (it has exception stubs only; that is
  a separate change).
- Re-parenting the existing `OllamaConnectionError` / `LlamaCppConnectionError`
  under the new `LLMConnectionError` (avoid breaking-change risk and test
  churn; the new base classes are additive siblings).
- Streaming generation via Gemini (the pipeline's streaming seam is
  backend-agnostic; a follow-up change can wire Gemini streaming if needed).
- A Gemini-specific token counter (the existing `approx_token_count`
  heuristic is tokenizer-agnostic and stays as-is).
- Multi-key / key-rotation support (single `GEMINI_API_KEY` env var).
- Automatic fallback from Gemini to Ollama on failure (out of scope; the
  pipeline already retries within a backend via the audit loop).

## Event Storming / bounded-context basis

This change is a **pure adapter extension** within the `infrastructure`
bounded context (AGENTS.md §2, openspec/config.yaml target architecture).
The event-storming analysis that produced the four bounded contexts
(`infrastructure`, `knowledge_sources`, `translation_pipeline`,
`interfaces`) deliberately isolated all external runtime dependencies behind
protocols so that swapping an engine is a composition-root change, not a
pipeline change. The dependency graph remains strictly acyclic:

```
interfaces  ──▶  infrastructure  (GeminiEngineAdapter is a new concretion here)
interfaces  ──▶  config           (AppConfig gains gemini fields)
translation_pipeline  ──▶  infrastructure  (unchanged — depends on the protocol, not Gemini)
config  ◀──  all components
```

No new inter-component edge is introduced. `GeminiEngineAdapter` is wired at
the single composition root (`_construct_adapters`), preserving the rule that
concrete engines are only referenced in `interfaces` + `infrastructure`, never
in `translation_pipeline`.
