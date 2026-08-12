## Context

The `infrastructure` bounded context wraps all external runtime dependencies
behind PEP 544 protocols. Today the only fully-wired LLM backend is
`OllamaEngineAdapter` (`src/components/infrastructure/llm.py`); the
`llamacpp` backend has exception stubs (`LlamaCppConnectionError`,
`LlamaCppTimeoutError`) but no adapter and no wiring in
`_construct_adapters`. The composition root
(`src/components/interfaces/cli.py::_construct_adapters`) constructs
`OllamaEngineAdapter` + `Embedder` unconditionally, and the `doctor` command
(`src/components/interfaces/commands/doctor.py` + `diagnostics.py`) hardcodes
`ollama.Client`.

The pipeline (`translation_pipeline`) and UIs (`interfaces`) depend on the
`LLMEngineAdapter` and `EmbeddingAdapter` protocols, never on concretions
(DIP). This makes adding a new backend a **composition-root + adapter**
change: no node, graph, prompt, glossary, retrieval, TM, or UI code needs to
move. This change adds `GeminiEngineAdapter` as a second concrete backend,
selectable via `config.yaml`, with `ollama` remaining the default.

## Goals / Non-Goals

**Goals:**
- A `GeminiEngineAdapter` that satisfies both `LLMEngineAdapter` and
  `EmbeddingAdapter`, so a single backend selection wires both roles.
- Backend selection via `config.yaml` (`llm_backend: gemini`), with the
  offline-first default (`ollama`) preserved.
- API key loaded from the `GEMINI_API_KEY` env var only — never in
  `config.yaml`, never logged, never in `repr`.
- Gemini SDK errors mapped to the domain exception hierarchy so nodes and the
  CLI only see domain exceptions.
- A `doctor` command that checks Gemini connectivity when `gemini` is
  selected.
- A rate limiter to stay within the Gemini free-tier RPM cap.
- Lazy SDK import so offline users never pay an import cost or a hard
  dependency at runtime.

**Non-Goals:**
- Implementing the `llamacpp` adapter (separate change).
- Re-parenting existing Ollama/LlamaCpp exceptions under the new
  `LLMConnectionError` (additive-only; avoid test churn).
- Gemini streaming generation (follow-up; the streaming seam is
  backend-agnostic).
- A Gemini-specific token counter (the `approx_token_count` heuristic is
  tokenizer-agnostic and unchanged).
- Multi-key / key rotation (single `GEMINI_API_KEY` env var).
- Automatic Gemini→Ollama fallback (the audit loop already retries within a
  backend).
- Distributed rate limiting (single-user, single-session per AGENTS.md).

## Decisions

### D1: One adapter class implements both protocols

**Decision:** `GeminiEngineAdapter` implements **both** `LLMEngineAdapter`
(`generate`) and `EmbeddingAdapter` (`embed`, `embed_batch`). The composition
root uses the same instance for `Adapters.llm` and `Adapters.embedder`.

**Rationale:** The Gemini backend serves both chat and embeddings from one
provider under one API key. `Adapters` types `llm: LLMEngineAdapter` and
`embedder: EmbeddingAdapter` as protocols, so a dual-protocol class is
LSP-compatible with both fields. This avoids a separate `GeminiEmbedder`
class and a second SDK client. The Ollama path keeps its two distinct classes
(`OllamaEngineAdapter` + `Embedder`) unchanged.

### D2: API key from env var, loaded in `load_config`

**Decision:** `load_config` reads `os.environ.get("GEMINI_API_KEY")` and
stores it on `AppConfig.gemini_api_key: str | None`. A `gemini_api_key` key
in `config.yaml` is rejected with `ConfigError`. When
`llm_backend == "gemini"` and the env var is unset/empty, `load_config`
raises `ConfigError`.

**Rationale:** Reading the key in `load_config` (rather than inside the
adapter) lets the `doctor` command validate key presence via `cfg` without
re-reading the environment, and centralizes the "key required when gemini"
rule in one place. The adapter still receives the key as a keyword-only
constructor arg (DIP — no `load_config()` call inside the adapter). The key
is never written to logs; `AppConfig.__repr__`/`__str__` must mask it (Pydantic
`SecretStr` is one option, but `str | None` with an explicit masked repr is
simpler and avoids a `SecretStr`→`str` unwrap at every call site — see D6).

### D3: New backend-agnostic + Gemini-specific exceptions (additive only)

**Decision:** Add `LLMConnectionError(LLMRuntimeError)` and
`LLMTimeoutError(LLMConnectionError)` as backend-agnostic bases, plus
`GeminiAuthError(LLMRuntimeError)` and `GeminiQuotaError(LLMRuntimeError)`.
Do **not** reparent `OllamaConnectionError`/`OllamaTimeoutError`/
`LlamaCppConnectionError`/`LlamaCppTimeoutError`.

**Rationale:** Reparenting would be a MODIFIED requirement on existing
exceptions and risks breaking tests that assert exact MROs. The new bases are
additive siblings; Gemini maps to them. A future change can reparent the
Ollama/LlamaCpp classes under `LLMConnectionError` if unified `isinstance`
handling is wanted — that is explicitly out of scope here.

### D4: Lazy `google-genai` import + mypy override

**Decision:** `import google.genai` lives inside `GeminiEngineAdapter.__init__`
(and/or methods), not at module top level. `pyproject.toml` gains a mypy
override `[[tool.mypy.overrides]] module = "google.genai.*"
ignore_missing_imports = true`. `google-genai>=1.0,<2` is added to both
`requirements.txt` and `pyproject.toml [project.dependencies]` (pinned to a
version published >7 days ago).

**Rationale:** Offline users on the Ollama path never import the SDK; the
package must import cleanly without it. Making it a runtime (not optional)
dependency keeps the two install paths in sync (per the
`build-and-packaging` capability) and lets `pip install -r requirements.txt`
produce a working `gemini` environment. The mypy override handles the SDK's
missing type stubs.

### D5: Rate limiter via `threading.Semaphore`, process-local

**Decision:** A `threading.Semaphore`-based limiter in `GeminiEngineAdapter`
enforces `gemini_rpm` (default 15). Each `generate`/`embed`/`embed_batch`
call acquires a permit before contacting the API and releases it in a
`finally` block. When the budget is exhausted, `GeminiQuotaError` is raised
without contacting the API.

**Rationale:** Single-user, single-session (AGENTS.md) means a process-local
limiter is sufficient — no Redis, no distributed coordination. A semaphore
with a refill discipline (or a simple token-bucket variant) keeps the
implementation small. Raising `GeminiQuotaError` locally gives the caller a
domain exception and avoids a raw SDK 429 leaking out.

### D6: `gemini_api_key` as `str | None` with a masked repr, not `SecretStr`

**Decision:** `AppConfig.gemini_api_key: str | None = None`. `AppConfig`
gains a `__repr__` (or Pydantic field config) that masks the key. The adapter
stores the key in a private `_api_key` attribute and excludes it from
`__repr__`.

**Rationale:** `pydantic.SecretStr` would force `.get_secret_value()` at
every use site (adapter construction, doctor ping), adding noise. A plain
`str | None` with an explicit masked repr is simpler and still satisfies
"never log the key" as long as logging paths use the masked repr. The
`config load` Typer command must print the masked form.

### D7: Embedding dimension must be 768 to reuse the existing ChromaDB collection

**Decision:** `GeminiEngineAdapter.embed_batch` enforces `EMBED_DIM` (768)
on every returned vector, matching the Ollama `Embedder`. The default
`gemini_embed_model` is `text-embedding-004` (768-dim by default). If a user
configures a Gemini embed model that returns a different dimension, the
adapter raises `EmbeddingError` at the first batch — it does **not** silently
create a mismatched collection.

**Rationale:** The existing ChromaDB collection is 768-dim cosine
(`EMBED_DIM = 768`). `text-embedding-004` happens to be 768-dim by default,
so the existing collection is reusable when switching backends. A dimension
mismatch would corrupt retrieval; failing fast is the safe choice. A
follow-up change could support per-backend collections if other dimensions
are needed.

### D8: Gemini adapter does NOT call the RAM guard

**Decision:** `GeminiEngineAdapter.generate` does not call
`check_ram_guard()`. The Ollama adapter's RAM guard exists because a local
model load can OOM the 8 GB machine; cloud inference has no local weight
footprint.

**Rationale:** The 8 GB ceiling (AGENTS.md §3) is about *local* model RAM.
Gemini inference happens on Google's servers. The general RAM-headroom
doctor check still runs (ChromaDB/embedding cache live locally), but the
LLM-RAM-budget line item is skipped on the `gemini` doctor path.

### D9: `llm_backend` narrowed to a 3-valued `Literal`

**Decision:** `llm_backend: Literal["ollama", "llamacpp", "gemini"] = "ollama"`.

**Rationale:** Today `llm_backend: str` silently accepts any typo and falls
through to the Ollama path. A `Literal` fails fast on unknown backends with
a clear `ConfigError` listing the valid values. This is a non-breaking
tightening (the three existing valid string values still validate).

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Cloud calls violate the "no cloud LLM calls" constraint if a user accidentally selects `gemini` | `ollama` is the default; `gemini` requires explicit opt-in **and** `GEMINI_API_KEY`. `doctor` clearly reports which backend is active. `AGENTS.md` §3 notes `gemini` is the only cloud backend. |
| API key leaked via logs / `repr` / exception messages | D2 + D6: key read in `load_config`, masked in `AppConfig` repr, excluded from adapter repr, never included in mapped exception messages. A test asserts the key is absent from `repr(adapter)` and from raised exception messages. |
| `google-genai` SDK adds install weight for offline users | Lazy import (D4): offline users never import it at runtime. Install cost is a few MB; accepted to keep the two install paths in sync. |
| Gemini free-tier 429s mid-translation | D5: process-local rate limiter raises `GeminiQuotaError` *before* the API call when the budget is exhausted, so the caller sees a clean domain exception. The audit loop's retry does not retry quota errors (they are not transient timeouts). |
| Embedding dimension mismatch corrupts ChromaDB | D7: `embed_batch` enforces 768-dim and raises `EmbeddingError` on mismatch; no silent collection corruption. |
| Reparenting exceptions breaks existing tests | D3: additive-only; existing exception base classes are unchanged. |
| `llm_backend` `Literal` tightening rejects a user's existing config | The three valid values (`ollama`, `llamacpp`, `gemini`) cover all documented backends. An unknown value today already silently misbehaves; failing fast with a clear message is an improvement. |
| Gemini SDK API/SDK version drift | Pin `google-genai>=1.0,<2`; the error mapper inspects exception types/HTTP status defensively (isinstance + status-code checks, not string matching on SDK-internal messages). |

## Target directory tree (new + modified files only)

```
src/
  components/
    infrastructure/
      gemini.py                 # NEW — GeminiEngineAdapter + _translate_gemini_error + rate limiter
      __init__.py               # MODIFIED — re-export GeminiEngineAdapter
    translation_pipeline/
      exceptions.py             # MODIFIED — + LLMConnectionError, LLMTimeoutError, GeminiAuthError, GeminiQuotaError
      __init__.py               # MODIFIED — re-export the four new exceptions
    interfaces/
      cli.py                    # MODIFIED — _construct_adapters branches on llm_backend
      diagnostics.py            # MODIFIED — + _check_gemini_api_key, _check_gemini_reachable
      commands/
        doctor.py               # MODIFIED — branch checks on llm_backend == "gemini"
  config/
    config.py                   # MODIFIED — llm_backend Literal, gemini_* fields, env-var read, validation
config.yaml                     # MODIFIED — llm_backend comment lists gemini; no key stored
requirements.txt                # MODIFIED — + google-genai>=1.0,<2
pyproject.toml                  # MODIFIED — + google-genai dep, + mypy override for google.genai.*
tests/
  test_gemini_adapter.py        # NEW — mocked-API tests (generate, embed_batch, errors, rate limit, ctx mgr, close)
  test_cli.py                   # MODIFIED — assert gemini constructs GeminiEngineAdapter for both roles
README.md                       # MODIFIED — §3 stack, §5.4 configure (gemini backend + GEMINI_API_KEY)
AGENTS.md                       # MODIFIED — §3 constraints note (gemini is the only cloud backend)
```

## Component dependency diagram (showing the new edge is confined to the composition root)

```
src/app.py  ──▶  interfaces  (Typer entry point)

interfaces               ──▶  translation_pipeline   (build_graph, TranslationState)   [unchanged]
interfaces               ──▶  infrastructure         (LLMEngineAdapter, EmbeddingAdapter,
interfaces                                              OllamaEngineAdapter, Embedder,
                                                        GeminiEngineAdapter  ← NEW concretion)
interfaces               ──▶  knowledge_sources      (GlossaryIndex, TranslationMemory) [unchanged]
interfaces               ──▶  config                 (AppConfig)                        [unchanged + gemini fields]

translation_pipeline     ──▶  infrastructure         (protocols only — NEVER GeminiEngineAdapter)  [unchanged]
translation_pipeline     ──▶  knowledge_sources      [unchanged]
translation_pipeline     ──▶  config                 [unchanged]

config                   ◀──  all components          [unchanged]

NEW edges:  interfaces ──▶ infrastructure.gemini   (composition root wires the new concretion)
            config      ──▶ (stdlib os)             (load_config reads GEMINI_API_KEY env var)
No new edge touches translation_pipeline. The graph remains strictly acyclic.
```

## models.py contents (per component) — deltas only

### `src/components/translation_pipeline/exceptions.py` (MODIFIED — additions only)

```python
# existing classes unchanged: LegalTranslationError, AdapterError, ...,
# LLMRuntimeError, OllamaConnectionError, OllamaTimeoutError,
# OllamaModelNotLoadedError, LlamaCppConnectionError, LlamaCppTimeoutError, ...

class LLMConnectionError(LLMRuntimeError):
    """Backend-agnostic: cannot reach an LLM backend (Ollama, llama.cpp, Gemini, ...)."""

class LLMTimeoutError(LLMConnectionError):
    """Backend-agnostic: an LLM request exceeded the configured timeout."""

class GeminiAuthError(LLMRuntimeError):
    """The Gemini API key is missing or invalid (HTTP 401/403)."""

class GeminiQuotaError(LLMRuntimeError):
    """The Gemini RPM/quota budget is exhausted (HTTP 429 / local limiter)."""
```

### `src/config/config.py` (MODIFIED — `AppConfig` additions)

```python
from typing import Literal

class AppConfig(BaseModel):
    llm_backend: Literal["ollama", "llamacpp", "gemini"] = "ollama"
    # ... existing fields unchanged ...
    gemini_model: str = "gemini-2.0-flash"
    gemini_embed_model: str = "text-embedding-004"
    gemini_timeout: float = 120.0
    gemini_rpm: int = 15
    gemini_api_key: str | None = None  # populated from GEMINI_API_KEY env var in load_config

    # validators: gemini_timeout non-negative float; gemini_rpm positive int
```

`load_config` additions:
```python
import os
# after Pydantic validation, before caching:
raw_key_in_yaml = "gemini_api_key" in raw  # reject if present in YAML
if raw_key_in_yaml:
    raise ConfigError("gemini_api_key must be set via the GEMINI_API_KEY env var, not config.yaml")
api_key = os.environ.get("GEMINI_API_KEY") or None
if cfg.llm_backend == "gemini" and not api_key:
    raise ConfigError("llm_backend='gemini' requires GEMINI_API_KEY to be set in the environment")
cfg = cfg.model_copy(update={"gemini_api_key": api_key})
```

### `src/components/interfaces/models.py` (UNCHANGED)

`Adapters.llm: LLMEngineAdapter` and `Adapters.embedder: EmbeddingAdapter`
are protocol-typed — a `GeminiEngineAdapter` (dual-protocol) is already
LSP-compatible. No change.

### `src/components/infrastructure/gemini.py` (NEW — illustrative signatures only)

```python
class GeminiEngineAdapter:
    """Dual-protocol adapter (LLMEngineAdapter + EmbeddingAdapter) for Google Gemini."""

    __slots__ = ("_client", "_model", "_embed_model", "_api_key", "_timeout",
                 "_limiter", "_closed")

    def __init__(self, *, model: str, embed_model: str, api_key: str,
                 timeout: float = 120.0, rpm: int = 15) -> None: ...
    @property
    def model(self) -> str: ...
    def generate(self, system_prompt: str, user_prompt: str, *,
                 model: str, temperature: float = 0.0,
                 max_tokens: int = 2048, timeout: float = 120.0) -> str: ...
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str],
                    batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]: ...
    def close(self) -> None: ...          # idempotent
    def __enter__(self) -> "GeminiEngineAdapter": ...
    def __exit__(self, *exc: object) -> None: ...
    def __repr__(self) -> str: ...        # masks _api_key

def _translate_gemini_error(err: BaseException, *, model: str,
                            kind: str) -> Exception: ...
```

## Inter-component communication protocol (imports / DI seams)

- `interfaces.cli._construct_adapters` imports `GeminiEngineAdapter` from
  `src.components.infrastructure.gemini` (lazy import inside the function, so
  the Ollama path never imports the SDK) and constructs it with
  `model=cfg.gemini_model, embed_model=cfg.gemini_embed_model,
  api_key=cfg.gemini_api_key, timeout=cfg.gemini_timeout, rpm=cfg.gemini_rpm`
  when `cfg.llm_backend == "gemini"`. The same instance is bound to both
  `Adapters.llm` and `Adapters.embedder`.
- `interfaces.diagnostics` imports `GeminiEngineAdapter` (lazy) for the
  `_check_gemini_reachable` ping.
- `infrastructure.gemini` imports `EMBED_DIM`, `DEFAULT_BATCH_SIZE`,
  `EmbeddingAdapter` from `src.components.infrastructure.embeddings`; the
  `LLMEngineAdapter` protocol from `src.components.infrastructure.llm`;
  `validate_batch_size` from `src.utils.batch_size`; and the new exception
  classes from `src.components.translation_pipeline.exceptions`. It does
  **not** import `ollama`, `httpx`, or any Ollama-specific module.
- `translation_pipeline` imports **no** Gemini symbol — it depends on the
  protocols only (unchanged).
- `config.config.load_config` reads `os.environ` (stdlib only); it imports
  no Gemini symbol.

## Migration strategy (file-by-file, one concern per task)

1. **Exceptions first** (foundation): add the four new exception classes +
   re-exports. No behavior change; verifiable by import + `issubclass` tests.
2. **Config next**: narrow `llm_backend` to `Literal`, add Gemini fields,
   env-var read, validation. Verifiable by `load_config` unit tests.
3. **Adapter**: create `gemini.py` with the dual-protocol class, error
   mapper, and rate limiter. Verifiable by mocked unit tests (no network).
4. **Composition root**: branch `_construct_adapters`. Verifiable by a CLI
   construction test with `llm_backend: gemini`.
5. **Doctor**: add the two Gemini check helpers + branch the `doctor`
   command. Verifiable by a mocked doctor test.
6. **Dependency + packaging**: add `google-genai` to `requirements.txt` +
   `pyproject.toml`, add the mypy override. Verifiable by `pip install` +
   `mypy src/`.
7. **Docs**: update `README.md` + `AGENTS.md` + `config.yaml` comment.
8. **Final verification**: `ruff`, `mypy --strict`, `pytest`, `openspec
   validate --all`.

Each task is independently verifiable (import check, unit test, or lint).
The dependency graph stays satisfiable: exceptions → config → adapter →
composition root → doctor → packaging → docs → final verification.

## app.py / entry point design

`src/app.py` is **unchanged**. It delegates to the CLI Typer app from
`src.components.interfaces.cli`; the new backend is wired inside
`_construct_adapters`, which `app.py` never references directly. The console
script `iraqi-translate = "src.app:main"` is unchanged.

## pyproject.toml changes

- `[project.dependencies]`: add `"google-genai>=1.0,<2"`.
- `[[tool.mypy.overrides]]`: add
  ```toml
  [[tool.mypy.overrides]]
  module = "google.genai.*"
  ignore_missing_imports = true
  ```
- `[tool.setuptools] packages`: **unchanged** — `gemini.py` is a new module
  inside the already-listed `src.components.infrastructure` package; no new
  package is introduced.
- `[project.scripts]`: **unchanged**.

## ruff per-file-ignores path migrations

None. `gemini.py` is a new file. Its `generate` method mirrors the mandated
6-argument `LLMEngineAdapter` protocol signature (AGENTS.md §5.3), so it
will trip `PLR0913` (too-many-arguments) — add a per-file ignore matching the
existing precedent for `llm.py`:

```toml
# GeminiEngineAdapter.generate mirrors the mandated LLMEngineAdapter
# protocol signature (6 args, AGENTS.md §5.3) — same precedent as llm.py.
"src/components/infrastructure/gemini.py" = ["PLR0913"]
```

No existing per-file-ignore path is migrated.
