## Context

The Iraqi Legal Translation Agent was recently refactored from 21 flat `src/` modules into a
component + models architecture (4 bounded-context components + a config package). That refactor
established structural boundaries but did not address SOLID-principle violations *within* each
component. A systematic analysis of all 33 source files revealed:

- **15 SRP violations:** god modules (`cli.py` 1,377 lines, `web_ui.py` 1,248 lines,
  `ingestion.py` 938 lines, `nodes.py` 665 lines) and god functions (`tm.py:lookup` 74 lines,
  `ingestion.py:iter_articles` 83 lines, `web_ui.py:Api.translate` 92 lines).
- **5 OCP violations:** hardcoded prompt version, if-else language dispatch, hardcoded search
  source list, if-else platform dispatch, hardcoded chunking strategy.
- **7 DIP violations:** `load_config()` called inside adapter constructors, `ChromaStore`
  creating `Embedder()` internally, `nodes.py` importing concrete classes, `graph.py` typing
  dependencies as `object | None`, `hitl.py` typing `llm`/`tm` as `object`.
- **3 ISP violations:** `Adapters` fat dataclass, `__init__.py` flat export lists.
- **25+ clean-code issues:** duplicated error translation, duplicated config loading, magic
  strings/numbers, `# type: ignore` suppressions, dead code in `app.py`.

This design addresses each violation while preserving 100% of existing behavior and the component
boundaries established by the prior refactor.

## Goals / Non-Goals

**Goals:**
- Split every god module into focused sub-modules (each ≤ 400 lines)
- Decompose every god function into helpers (each ≤ 40 lines, ≤ 3 nesting levels)
- Replace hardcoded dispatch with registry/protocol patterns (OCP)
- Inject all dependencies at adapter seams — no `load_config()` inside constructors (DIP)
- Type all dependency parameters with protocols, not `object` (DIP)
- Segregate the `Adapters` bundle into focused interfaces (ISP)
- Extract shared code to eliminate duplication (DRY)
- Extract all magic strings/numbers to named constants
- Resolve all `# type: ignore` comments by fixing underlying type issues
- Preserve 100% of existing behavior — zero test regressions
- Preserve public API surface via `__init__.py` re-exports

**Non-Goals:**
- No new features (no new CLI commands, no new graph nodes, no new UI tabs)
- No new runtime dependencies
- No changes to `data/`, `db/`, `config.yaml`, or any non-Python file
- No changes to the component boundary structure (the 4 components + config package remain)
- No changes to prompt content (V1–V4 text is preserved exactly)
- No changes to the LangGraph state machine flow (nodes, edges, routing logic unchanged)
- No splitting of the project into multiple packages or repos

## Decisions

### D1: Module split strategy — extract, don't rewrite

Each god module is split by *extracting* helpers into new files, not by rewriting. The original
module keeps the public API and imports the extracted helpers. This ensures:
- `__init__.py` re-exports remain valid (the original module still exists)
- Test imports that reference the original module still work
- The split is verifiable: after extraction, `python -c "import ..."` and `pytest` must pass

| Original module | Lines | Split into |
|---|---|---|
| `interfaces/cli.py` | 1,377 | `cli.py` (commands) + `diagnostics.py` + `orchestration.py` + `tm_commands.py` |
| `interfaces/web_ui.py` | 1,248 | `web_ui.py` (Python API) + `web_frontend.py` (HTML constant) |
| `knowledge_sources/ingestion.py` | 938 | `ingestion.py` (parsing/chunking) + `manifest.py` + `ingestion_runner.py` |
| `translation_pipeline/nodes.py` | 665 | `nodes.py` (node functions) + `formatters.py` + `parsers.py` + `mappers.py` |

**Rationale:** Extraction is mechanically safe — the original module's public symbols don't move,
so re-exports and test imports don't break. Rewriting would require updating every import path
and risk introducing behavior changes.

### D2: Protocol-based adapter seams (DIP)

Three new protocols are added to `translation_pipeline` for the external dependencies that
`nodes.py` currently imports as concretions:

```
# translation_pipeline/protocols.py (new file)
class GlossaryScanner(Protocol):
    def scan(self, text: str, lang: Lang) -> list[GlossaryHit]: ...

class ContextRetriever(Protocol):
    def retrieve(self, query: str, n: int) -> list[ContextChunk]: ...

class WebSearcher(Protocol):
    def search(self, query: str) -> list[WebSearchResult]: ...
```

`nodes.py` imports these protocols and types its parameters accordingly. The concrete
implementations (`GlossaryIndex` + `scan_glossary_hits`, `retrieve_context_chunks`,
`search_all_sources`) are wired in `graph.py:build_graph` via small adapter wrappers.

**Rationale:** This makes `nodes.py` depend on abstractions, not concretions. A test can
substitute a mock `GlossaryScanner` without importing `GlossaryIndex`. The protocols are
structural (PEP 544), so existing classes that happen to have the right methods satisfy them
automatically.

**Adapter wrappers in graph.py:**
```python
# graph.py wraps concretions into protocol-satisfying objects
class _GlossaryScannerAdapter:
    def __init__(self, index: GlossaryIndex) -> None:
        self._index = index
    def scan(self, text: str, lang: Lang) -> list[GlossaryHit]:
        return scan_glossary_hits(text, self._index, lang)
```

### D3: PromptVersion protocol (OCP)

```python
# translation_pipeline/prompts.py
class PromptVersion(Protocol):
    shared_system_rules: str
    translator_system: str
    translator_revision_addendum: str
    translator_user_template: str
    auditor_system: str
    auditor_user_template: str

class PromptV4(NamedTuple):
    shared_system_rules: str = SHARED_SYSTEM_RULES_V4
    translator_system: str = TRANSLATOR_SYSTEM_V4
    # ... etc

DEFAULT_PROMPT_VERSION: PromptVersion = PromptV4()
```

`nodes.py` receives `prompts: PromptVersion = DEFAULT_PROMPT_VERSION` as a keyword-only arg.
Adding V5 requires adding `PromptV5` and updating `DEFAULT_PROMPT_VERSION` — no changes to
`nodes.py`.

### D4: Registry patterns for OCP

Three registries replace hardcoded if-else chains:

1. **Normalizer registry** (`glossary.py`):
   ```python
   _NORMALIZERS: dict[str, Normalizer] = {"ar": _ArabicNormalizer(), "en": _EnglishNormalizer()}
   def normalize(term: str, lang: str) -> str:
       return _NORMALIZERS[lang].normalize(term)
   ```

2. **Search source registry** (`legal_search.py`):
   ```python
   _SOURCES: list[SearchSource] = [
       SearchSource("dijlex", search_dijlex),
       SearchSource("moj", search_moj),
       # ...
   ]
   def search_all_sources(query: str, max_results_per_source: int = 5) -> list[SearchHit]:
       return [hit for src in _SOURCES for hit in src.search(query, max_results_per_source)]
   ```

3. **Platform reader registry** (`memory.py`):
   ```python
   _PLATFORM_READERS: dict[str, Callable[[], MemoryInfo | None]] = {
       "win32": _read_memory_info_windows,
       "linux": _read_memory_info_linux,
   }
   def read_memory_info() -> MemoryInfo | None:
       reader = _PLATFORM_READERS.get(sys.platform)
       return reader() if reader else None
   ```

### D5: Remove load_config() from adapter constructors (DIP)

`OllamaEngineAdapter.__init__` and `Embedder.__init__` currently call `load_config()` as a
fallback when `model`/`host` are not provided. This creates a hidden dependency on the config
module and makes testing hard. The fix:
- Remove the `load_config()` call from both constructors
- Require `model` and `host` as mandatory keyword-only args (no defaults)
- Update `_construct_adapters` in `cli.py` to pass these explicitly (it already does)

`ChromaStore.__init__` currently calls `load_config()` and `Embedder()` internally. The fix:
- Accept `embedder: EmbeddingAdapter` and `cfg: AppConfig` as keyword-only args
- Remove internal `load_config()` and `Embedder()` calls
- Update all callers to pass these explicitly

### D6: Shared error translation (DRY)

```
# infrastructure/ollama_errors.py (new)
def translate_engine_error(err: Exception, *, model: str, kind: str) -> Exception:
    """Map Ollama client exceptions to domain exceptions.
    kind: "llm" or "embedding"
    """
```

Both `llm.py` and `embeddings.py` import and use this function. The `kind` parameter
determines whether to raise `LLMRuntimeError`/`OllamaConnectionError` or
`EmbeddingError`/`EmbeddingConnectionError`.

### D7: Adapters interface segregation (ISP)

```python
# interfaces/models.py
@dataclass(slots=True)
class LLMAdapters:
    llm: LLMEngineAdapter
    embedder: EmbeddingAdapter

@dataclass(slots=True)
class KnowledgeAdapters:
    glossary_index: GlossaryIndex
    persist_dir: Path
    tm: TranslationMemory

@dataclass(slots=True)
class Adapters(LLMAdapters, KnowledgeAdapters):
    """Backward-compatible bundle of all adapters."""
    pass
```

Consumers that only need LLM access depend on `LLMAdapters`. Consumers that only need knowledge
access depend on `KnowledgeAdapters`. `Adapters` remains for backward compatibility.

### D8: Constants module (clean code)

```
# translation_pipeline/constants.py (new)
DIRECTION_AR_EN: str = "ar-en"
DIRECTION_EN_AR: str = "en-ar"
LANG_AR: str = "ar"
LANG_EN: str = "en"
VERDICT_APPROVE: str = "APPROVE"
VERDICT_REVISE: str = "REVISE"
NA_PLACEHOLDER: str = "N/A"
```

All modules within `translation_pipeline` import from `constants.py` instead of using bare
string literals.

## Risks / Trade-offs

### R1: Module proliferation

Splitting 4 god modules into 12+ focused modules increases the file count. This is a deliberate
trade-off: more files with clear single responsibilities are easier to navigate, test, and
maintain than fewer files with mixed concerns. The `__init__.py` re-exports ensure consumers
don't need to know the internal split.

**Mitigation:** Each new module has a clear name that communicates its responsibility. The
`__init__.py` re-exports provide a stable public API.

### R2: Adapter constructor breaking change

Removing `load_config()` from `OllamaEngineAdapter` and `Embedder` constructors is a breaking
change for any code that relies on the auto-config fallback. The primary entry point
(`_construct_adapters` in `cli.py`) already passes config explicitly, so it is unaffected. Any
test that constructs adapters without passing config will need updating.

**Mitigation:** The change is documented in the proposal. Tests that construct adapters directly
will be updated as part of the migration. The `app.py` DI entry point can be enhanced to provide
a single wiring point.

### R3: Protocol adapter wrappers add indirection

Wrapping `GlossaryIndex` in a `_GlossaryScannerAdapter` adds a layer of indirection. This is the
cost of DIP — the high-level module (`nodes.py`) depends on an abstraction, and the wiring
code (`graph.py`) creates the adapter.

**Mitigation:** The wrappers are thin (1–3 lines) and live in `graph.py`, which is the
composition root. They don't add runtime overhead beyond a method call.

### R4: Migration ordering risk

Splitting modules and changing constructor signatures simultaneously could introduce subtle
bugs if not done in the right order.

**Mitigation:** Tasks are ordered foundation-first (infrastructure → translation_pipeline →
knowledge_sources → interfaces → config). Each task is independently verifiable (import check +
pytest). The full suite is run after each component phase.

## Target Directory Tree

```
src/
├── __init__.py
├── app.py                              # modified: dead code removed, types added
├── config/
│   ├── __init__.py                     # modified: re-exports updated
│   ├── config.py                       # modified: CLI removed, loading only
│   ├── cli.py                          # NEW: Typer app + load command
│   └── models.py                       # modified: validators added
├── components/
│   ├── __init__.py
│   ├── translation_pipeline/
│   │   ├── __init__.py                 # modified: re-exports updated
│   │   ├── models.py                   # unchanged
│   │   ├── graph.py                    # modified: protocol types, adapter wrappers
│   │   ├── nodes.py                    # modified: slimmed, imports formatters/parsers/mappers
│   │   ├── decision.py                 # unchanged
│   │   ├── prompts.py                  # modified: adds PromptVersion protocol
│   │   ├── exceptions.py               # unchanged
│   │   ├── constants.py                # NEW: named constants
│   │   ├── protocols.py                # NEW: GlossaryScanner, ContextRetriever, WebSearcher
│   │   ├── formatters.py               # NEW: prompt formatting helpers
│   │   ├── parsers.py                  # NEW: JSON parsing helpers
│   │   └── mappers.py                  # NEW: type-conversion helpers
│   ├── knowledge_sources/
│   │   ├── __init__.py                 # modified: re-exports updated
│   │   ├── models.py                   # unchanged
│   │   ├── glossary.py                 # modified: normalizer registry, Term factory
│   │   ├── retrieval.py                # modified: DI, shared factory
│   │   ├── tm.py                       # modified: lookup decomposed
│   │   ├── legal_search.py             # modified: source registry
│   │   ├── ingestion.py                # modified: slimmed, parsing/chunking only
│   │   ├── manifest.py                 # NEW: manifest writing + hashing
│   │   └── ingestion_runner.py         # NEW: orchestration + progress
│   ├── infrastructure/
│   │   ├── __init__.py                 # modified: re-exports updated
│   │   ├── models.py                   # unchanged
│   │   ├── llm.py                      # modified: removes load_config, shared errors
│   │   ├── embeddings.py               # modified: removes load_config, shared errors
│   │   ├── memory.py                   # modified: platform registry
│   │   ├── run_logging.py              # modified: log_node decomposed
│   │   └── ollama_errors.py            # NEW: shared error translation
│   └── interfaces/
│       ├── __init__.py                 # modified: re-exports updated
│       ├── models.py                   # modified: Adapters segregated
│       ├── cli.py                      # modified: slimmed, commands only
│       ├── diagnostics.py              # NEW: doctor check functions
│       ├── orchestration.py            # NEW: translation orchestration
│       ├── tm_commands.py              # NEW: TM command handlers
│       ├── config_loader.py            # NEW: shared load_or_exit helper
│       ├── web_ui.py                   # modified: slimmed, Python API only
│       ├── web_frontend.py             # NEW: HTML/CSS/JS constant
│       ├── tk_ui.py                    # modified: proper protocol types
│       ├── mcp_server.py               # unchanged
│       └── hitl.py                     # modified: decomposed, protocol types
```

## Component Dependency Diagram

```
                    ┌─────────────────────────────────────────────────┐
                    │                   config                         │
                    │  config.py · cli.py · models.py                 │
                    └──────────────────┬──────────────────────────────┘
                                       │ AppConfig
                    ┌──────────────────▼──────────────────────────────┐
                    │              infrastructure                     │
                    │  llm.py · embeddings.py · memory.py             │
                    │  run_logging.py · ollama_errors.py · models.py  │
                    │  Protocols: LLMEngineAdapter, EmbeddingAdapter  │
                    └──────────────────┬──────────────────────────────┘
                                       │ adapters (injected)
                    ┌──────────────────▼──────────────────────────────┐
                    │            knowledge_sources                    │
                    │  glossary.py · retrieval.py · tm.py             │
                    │  legal_search.py · ingestion.py                 │
                    │  manifest.py · ingestion_runner.py · models.py  │
                    └──────────────────┬──────────────────────────────┘
                                       │ knowledge adapters (injected)
                    ┌──────────────────▼──────────────────────────────┐
                    │          translation_pipeline                   │
                    │  graph.py · nodes.py · decision.py              │
                    │  prompts.py · exceptions.py · constants.py      │
                    │  protocols.py · formatters.py · parsers.py      │
                    │  mappers.py · models.py                         │
                    │  Protocols: GlossaryScanner, ContextRetriever,  │
                    │  WebSearcher, PromptVersion                     │
                    └──────────────────┬──────────────────────────────┘
                                       │ graph (injected)
                    ┌──────────────────▼──────────────────────────────┐
                    │               interfaces                        │
                    │  cli.py · diagnostics.py · orchestration.py     │
                    │  tm_commands.py · config_loader.py              │
                    │  web_ui.py · web_frontend.py · tk_ui.py         │
                    │  mcp_server.py · hitl.py · models.py            │
                    │  Protocols: DiagnosticsChecker (future)         │
                    └─────────────────────────────────────────────────┘
```

**Key DIP seams (arrows show dependency direction, all via protocols):**
- `nodes.py` → `GlossaryScanner`, `ContextRetriever`, `WebSearcher` (protocols)
- `nodes.py` → `LLMEngineAdapter`, `EmbeddingAdapter` (protocols)
- `graph.py` wires concrete implementations into protocol-satisfying adapters
- `hitl.py` → `LLMEngineAdapter` (protocol), not `object`
- `cli.py` → `Adapters` (segregated: `LLMAdapters` + `KnowledgeAdapters`)

## models.py Contents (per component, after refactor)

| Component | models.py | Contents |
|---|---|---|
| config | `models.py` | `PathsConfig`, `ChromaConfig` (Pydantic, with validators) |
| translation_pipeline | `models.py` | `TranslationState`, `GlossaryHit`, `ContextChunk`, `AuditVerdict`, `TmHit`, `WebSearchResult`, `Direction`, `Verdict` (unchanged) |
| knowledge_sources | `models.py` | `Term`, `Article`, `Chunk`, `TmEntry`, `SearchHit`, `ContextChunk` (unchanged) |
| infrastructure | `models.py` | `MemoryInfo`, `RunLogEntry` (unchanged) |
| interfaces | `models.py` | `CheckResult`, `Adapters`, `LLMAdapters` (NEW), `KnowledgeAdapters` (NEW), `UiTranslationResult` |

**New protocol files:**
| File | Protocols |
|---|---|
| `translation_pipeline/protocols.py` | `GlossaryScanner`, `ContextRetriever`, `WebSearcher` |
| `translation_pipeline/prompts.py` | `PromptVersion` (added to existing file) |

## Inter-component Communication Protocol

### Dependency injection flow

```
app.py
  └─ cli.py (Typer app)
       └─ config_loader.load_or_exit() → AppConfig
       └─ _construct_adapters(cfg) → Adapters
            ├─ OllamaEngineAdapter(client, model=cfg.llm_model, host=cfg.ollama_host)
            ├─ Embedder(client, model=cfg.embedding_model, host=cfg.ollama_host)
            ├─ GlossaryIndex(db_path=cfg.paths.glossary_db)
            ├─ Path(cfg.paths.chroma_dir)
            └─ TranslationMemory(db_path=cfg.paths.tm_db)
       └─ build_graph(llm=adapters.llm, embedder=adapters.embedder, ...)
            └─ wraps concretions into protocol adapters:
               _GlossaryScannerAdapter(glossary_index)
               _ContextRetrieverAdapter(embedder, persist_dir, cfg)
               _WebSearcherAdapter()
            └─ passes protocol-typed deps to node functions
```

### Import rules (enforced by protocol seams)

1. `translation_pipeline/nodes.py` imports ONLY from:
   - `translation_pipeline/models.py`, `constants.py`, `protocols.py`, `prompts.py`
   - `translation_pipeline/formatters.py`, `parsers.py`, `mappers.py`
   - `infrastructure/models.py` (for `LLMRequest`, `LLMResponse` if needed)
   - It does NOT import from `knowledge_sources/*` or `infrastructure/llm.py`

2. `translation_pipeline/graph.py` is the composition root for the pipeline:
   - It imports concrete implementations from `knowledge_sources/*` and `infrastructure/*`
   - It wraps them in protocol-satisfying adapters
   - It passes protocol-typed dependencies to `nodes.py` functions

3. `interfaces/*` imports from all other components but always via `__init__.py` re-exports

## Migration Strategy

### Phase 1: Infrastructure (foundation, no upstream dependencies)

1. Create `ollama_errors.py` with shared `translate_engine_error`
2. Update `llm.py` to import from `ollama_errors.py`, remove `load_config()` from constructor
3. Update `embeddings.py` to import from `ollama_errors.py`, remove `load_config()` from constructor
4. Update `memory.py` with platform registry
5. Update `run_logging.py` with `log_node` decomposition
6. Verify: `pytest --tb=short -q`, `ruff check src/`, `mypy src/`

### Phase 2: Translation Pipeline

1. Create `constants.py` with named constants
2. Create `protocols.py` with `GlossaryScanner`, `ContextRetriever`, `WebSearcher`
3. Update `prompts.py` with `PromptVersion` protocol and version NamedTuples
4. Create `formatters.py` — extract formatting helpers from `nodes.py`
5. Create `parsers.py` — extract `_parse_verdict` from `nodes.py`
6. Create `mappers.py` — extract type-conversion helpers from `nodes.py`
7. Update `nodes.py` — import from new modules, use protocol types, use constants, accept `PromptVersion`
8. Update `graph.py` — add adapter wrappers, fix type annotations, pass `PromptVersion`
9. Verify: `pytest --tb=short -q`, `ruff check src/`, `mypy src/`

### Phase 3: Knowledge Sources

1. Create `manifest.py` — extract manifest logic from `ingestion.py`
2. Create `ingestion_runner.py` — extract orchestration from `ingestion.py`
3. Update `ingestion.py` — import from new modules, decompose `iter_articles`
4. Update `tm.py` — decompose `lookup` into helper methods
5. Update `glossary.py` — add normalizer registry, Term factory methods
6. Update `retrieval.py` — inject `embedder`/`cfg`, add `_create_store` factory
7. Update `legal_search.py` — add `SearchSource` registry
8. Verify: `pytest --tb=short -q`, `ruff check src/`, `mypy src/`

### Phase 4: Interfaces

1. Create `config_loader.py` with `load_or_exit`
2. Create `diagnostics.py` — extract `_check_*` functions from `cli.py`
3. Create `orchestration.py` — extract `_run_*` and `_provenance_*` from `cli.py`
4. Create `tm_commands.py` — extract TM command handlers from `cli.py`
5. Update `cli.py` — slim to command wrappers, use `load_or_exit`, use `diagnostics`/`orchestration`/`tm_commands`
6. Create `web_frontend.py` — extract `_HTML` from `web_ui.py`
7. Update `web_ui.py` — import `HTML` from `web_frontend.py`
8. Update `hitl.py` — decompose `human_review`, fix `llm`/`tm` types
9. Update `models.py` — add `LLMAdapters`, `KnowledgeAdapters`, segregate `Adapters`
10. Update `tk_ui.py` — fix protocol types
11. Verify: `pytest --tb=short -q`, `ruff check src/`, `mypy src/`

### Phase 5: Config

1. Create `config/cli.py` — extract Typer app from `config.py`
2. Update `config.py` — remove CLI, keep loading only
3. Update `models.py` — add validators
4. Update `app.py` — remove dead `load_config` import, add return type
5. Verify: `pytest --tb=short -q`, `ruff check src/`, `mypy src/`

### Phase 6: Cleanup

1. Update all `__init__.py` re-exports for new sub-modules
2. Update `pyproject.toml` ruff per-file-ignores for new paths
3. Resolve all remaining `# type: ignore` comments
4. Run full verification: `pytest --tb=short -q`, `ruff check src/ tests/`, `mypy src/`, `openspec validate --all`

## app.py / Entry Point Design

`app.py` remains the DI entry point. The dead `load_config` import is removed. `main()` gets a
return type annotation:

```python
def main() -> None:
    """Console script entry point — delegates to the CLI Typer app."""
    _app()
```

Future enhancement (out of scope for this change): `main()` could construct adapters once and
pass them to the CLI, making the DI wiring explicit at the entry point.

## pyproject.toml Changes

- `[tool.ruff.lint.per-file-ignores]` — add entries for new files:
  - `src/components/translation_pipeline/constants.py`
  - `src/components/translation_pipeline/protocols.py`
  - `src/components/translation_pipeline/formatters.py`
  - `src/components/translation_pipeline/parsers.py`
  - `src/components/translation_pipeline/mappers.py`
  - `src/components/knowledge_sources/manifest.py`
  - `src/components/knowledge_sources/ingestion_runner.py`
  - `src/components/infrastructure/ollama_errors.py`
  - `src/components/interfaces/diagnostics.py`
  - `src/components/interfaces/orchestration.py`
  - `src/components/interfaces/tm_commands.py`
  - `src/components/interfaces/config_loader.py`
  - `src/components/interfaces/web_frontend.py`
  - `src/config/cli.py`
- No new packages (all new files are within existing package directories)
- No new entry points

## ruff per-file-ignores Path Migrations

The existing per-file-ignores for `src/components/interfaces/cli.py` (if any) SHALL be reviewed.
If there are ignores for long functions or complexity, they SHALL be removed after the split
reduces function lengths. New files inherit the default ruff rules (line-length 100, no ignores).
