## Why

The component-architecture refactor successfully moved 21 flat modules into 4 bounded-context
components + a config package, but the code *inside* each component still carries significant
SOLID-principle violations and clean-code debt. A systematic analysis of all 33 source files
revealed:

- **SRP violations (god modules / god functions):** `cli.py` is 1,377 lines mixing CLI parsing,
  adapter construction, diagnostics, translation orchestration, batch processing, and TM commands.
  `web_ui.py` is 1,248 lines with 906 lines of embedded HTML/CSS/JS. `ingestion.py` is 938 lines
  mixing parsing, chunking, hashing, manifest writing, and CLI orchestration. `nodes.py` mixes
  node functions, prompt formatting, JSON parsing, and type-conversion mappers. `tm.py:lookup`
  is a 74-line god function with 4 levels of nesting.
- **OCP violations (hardcoded dispatch):** Prompt version is hardcoded to V4 in `nodes.py`,
  requiring source edits to switch versions. `normalize()` in `glossary.py` uses an if-else chain
  for language dispatch. `search_all_sources()` in `legal_search.py` hardcodes the list of search
  functions. Platform dispatch in `memory.py` uses if-else chains. Adding any new variant requires
  modifying existing code rather than extending it.
- **DIP violations (concretions at seams):** `OllamaEngineAdapter.__init__` and
  `Embedder.__init__` call `load_config()` internally instead of receiving config via injection.
  `ChromaStore.__init__` creates `Embedder()` directly. `nodes.py` imports concrete
  `GlossaryIndex`, `scan_glossary_hits`, `search_all_sources`, `retrieve_context_chunks` instead
  of depending on protocols. `graph.py:build_graph` types `embedder`, `persist_dir`, `tm` as
  `object | None` instead of proper protocols. `hitl.py` types `llm` and `tm` as `object`.
- **ISP violations (fat interfaces):** The `Adapters` dataclass bundles all 5 adapters together;
  consumers that only need the LLM must still accept the full bundle. `__init__.py` files export
  15–42 symbols in a flat list.
- **DRY violations:** `_translate_engine_error` is duplicated nearly verbatim in `llm.py` and
  `embeddings.py`. Error-handling and config-loading patterns are repeated across every CLI
  command. Term construction is duplicated in `glossary.py`. ChromaStore instantiation is
  duplicated in 4 module-level functions. Provenance rendering is duplicated between
  `_render_provenance` and `_provenance_markdown`.
- **Clean-code debt:** 12+ functions exceed 40 lines. 8+ functions have >3 levels of nesting.
  Magic strings ("ar-en", "en-ar", "APPROVE", "REVISE", "N/A") and magic numbers (0.999, 0.001,
  5.4, 200ms, 300ms, 10-item history limit) are scattered across modules. Multiple `# type: ignore`
  comments suppress type errors instead of fixing them. `app.py` imports `load_config` but never
  uses it (dead code).

These issues raise onboarding cost, invite bugs during future feature work, make testing harder
(hidden dependencies, broad exception swallowing), and block the project's stated convention of
"DI via keyword-only args (DIP)" and "Protocols for adapter seams." This change addresses them
systematically — splitting god modules, extracting protocols, eliminating duplication, and
enforcing DIP at every adapter seam — while preserving 100% of existing behavior.

## What Changes

### SRP — Split god modules and god functions

- **MODIFIED:** `interfaces/cli.py` (1,377 lines) SHALL be split into:
  - `cli.py` — Typer app + command definitions only (thin wrappers)
  - `diagnostics.py` — all `_check_*` doctor functions and `_detect_offload_mode`
  - `orchestration.py` — `_run_translation`, `_run_translation_streamed`, `_initial_state`,
    `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`, `_render_provenance`
  - `tm_commands.py` — `tm_build`, `tm_build_parallel`, `tm_add_parallel` command handlers
- **MODIFIED:** `interfaces/web_ui.py` (1,248 lines) SHALL be split into:
  - `web_ui.py` — `launch_ui`, `Api` class, `_UiHumanReviewer`, `_PendingResult`
  - `web_frontend.py` — the `_HTML` constant (embedded HTML/CSS/JS) extracted to a separate
    module
- **MODIFIED:** `knowledge_sources/ingestion.py` (938 lines) SHALL be split into:
  - `ingestion.py` — `ingest_corpus`, `iter_articles`, `chunk_article`, `approx_token_count`,
    `parse_corpus_file` (parsing + chunking)
  - `manifest.py` — `_write_manifest`, `_compute_file_hash`, file categorization logic
  - `ingestion_runner.py` — `run_ingestion` orchestration, `_iter_corpus_chunks`, progress
    reporting
- **MODIFIED:** `translation_pipeline/nodes.py` SHALL be split into:
  - `nodes.py` — pure node functions (`preprocess_node`, `translate_node`, `audit_node`,
    `finalize_node`, `tm_lookup_node`, `tm_bypass_node`, `web_search_node`)
  - `formatters.py` — `_format_glossary_bindings`, `_format_context_chunks`,
    `_format_web_search_results`, `_augment_query_for_retrieval`, `_langs`
  - `parsers.py` — `_parse_verdict` and any JSON parsing/validation logic
  - `mappers.py` — `_hit_to_state`, `_chunk_to_state` type-conversion helpers
- **MODIFIED:** `knowledge_sources/tm.py` — `TranslationMemory.lookup` (74 lines) SHALL be
  decomposed into `_extract_trigrams`, `_trigram_candidates`, `_full_scan_candidates`,
  `_verify_candidates` (each ≤ 30 lines).
- **MODIFIED:** `interfaces/hitl.py` — `human_review` (57 lines) SHALL be decomposed into
  `_handle_review_decision`, `_re_audit_if_edited` (each ≤ 25 lines).

### OCP — Replace hardcoded dispatch with extensible patterns

- **ADDED:** `PromptVersion` protocol in `translation_pipeline/prompts.py` — each prompt version
  (V1–V4) SHALL be a dataclass/NamedTuple implementing the protocol. `nodes.py` SHALL receive the
  prompt version as a keyword-only argument (default: V4) instead of importing V4 constants
  directly. Adding V5 requires adding a new version object, not modifying `nodes.py`.
- **ADDED:** `Normalizer` protocol in `knowledge_sources/glossary.py` — `normalize()` SHALL
  dispatch via a registry dict (`_NORMALIZERS: dict[Lang, Normalizer]`) instead of an if-else
  chain. Adding a new language requires registering a new normalizer, not modifying `normalize()`.
- **ADDED:** `SearchSource` protocol in `knowledge_sources/legal_search.py` — each search function
  SHALL be wrapped in a `SearchSource` dataclass with `name`, `search` callable.
  `search_all_sources` SHALL iterate over a `_SOURCES` registry list. Adding a new source requires
  registering a new `SearchSource`, not modifying `search_all_sources`.
- **ADDED:** Platform dispatch in `infrastructure/memory.py` SHALL use a registry dict
  (`_PLATFORM_READERS: dict[str, Callable[[], MemoryInfo | None]]`) instead of if-else chains.
  Adding a new platform requires registering a new reader, not modifying `read_memory_info`.

### DIP — Inject dependencies at all adapter seams

- **MODIFIED:** `OllamaEngineAdapter.__init__` SHALL NOT call `load_config()`. It SHALL accept
  `model`, `host`, and `timeout` as keyword-only constructor args (already does for model/host,
  but removes the internal `load_config()` fallback).
- **MODIFIED:** `Embedder.__init__` SHALL NOT call `load_config()`. It SHALL accept `model` and
  `host` as keyword-only constructor args (removes the internal `load_config()` fallback).
- **MODIFIED:** `ChromaStore.__init__` SHALL accept `embedder: EmbeddingAdapter` and
  `cfg: AppConfig` as keyword-only args instead of calling `load_config()` and `Embedder()`
  internally.
- **ADDED:** `GlossaryScanner` protocol in `translation_pipeline` — `nodes.py` SHALL depend on
  a `GlossaryScanner` protocol (`scan(text, lang) -> list[GlossaryHit]`) instead of importing the
  concrete `GlossaryIndex` + `scan_glossary_hits`.
- **ADDED:** `ContextRetriever` protocol in `translation_pipeline` — `nodes.py` SHALL depend on
  a `ContextRetriever` protocol (`retrieve(query, n) -> list[ContextChunk]`) instead of importing
  the concrete `retrieve_context_chunks`.
- **ADDED:** `WebSearcher` protocol in `translation_pipeline` — `nodes.py` SHALL depend on a
  `WebSearcher` protocol (`search(query) -> list[WebSearchResult]`) instead of importing the
  concrete `search_all_sources`.
- **MODIFIED:** `graph.py:build_graph` SHALL type `embedder` as `EmbeddingAdapter`, `tm` as
  `TranslationMemory` (or a `TranslationMemoryAdapter` protocol), and `persist_dir` as `Path`
  — not `object | None`.
- **MODIFIED:** `hitl.py:human_review` SHALL type `llm` as `LLMEngineAdapter` and `tm` as
  `TranslationMemory` (or protocol) — not `object`.

### ISP — Segregate fat interfaces

- **MODIFIED:** `Adapters` dataclass in `interfaces/models.py` SHALL be split into:
  - `LLMAdapters` — `llm`, `embedder` (for translation)
  - `KnowledgeAdapters` — `glossary_index`, `persist_dir`, `tm` (for knowledge access)
  - `Adapters` — retains all 5 fields for backward compatibility, but consumers SHALL depend on
    the narrowest interface they need.
- **ADDED:** `DiagnosticsChecker` protocol — the `doctor` command SHALL depend on a protocol with
  only `run_checks() -> list[CheckResult]` instead of importing individual `_check_*` functions.

### DRY — Eliminate duplicated code

- **ADDED:** `infrastructure/ollama_errors.py` — shared `_translate_engine_error` function
  extracted from `llm.py` and `embeddings.py`. Both modules SHALL import from this shared module.
- **ADDED:** `interfaces/config_loader.py` — shared `_load_or_exit()` helper that wraps
  `load_config()` + error printing + `typer.Exit(1)`. All CLI commands SHALL use this instead of
  duplicating the try/except/load pattern.
- **MODIFIED:** `glossary.py` — Term construction SHALL use a `Term.from_row()` classmethod and
  `Term.from_dict()` classmethod to eliminate duplicated construction logic.
- **MODIFIED:** `retrieval.py` — module-level functions (`build_chroma_collection`,
  `query_chroma`, etc.) SHALL use a shared `_create_store()` factory instead of duplicating
  `ChromaStore(persist_dir=...)` instantiation.

### Clean code — Extract constants, fix type ignores, remove dead code

- **ADDED:** `translation_pipeline/constants.py` — `DIRECTION_AR_EN`, `DIRECTION_EN_AR`,
  `LANG_AR`, `LANG_EN`, `VERDICT_APPROVE`, `VERDICT_REVISE`, `NA_PLACEHOLDER`. All modules SHALL
  import from here instead of using magic strings.
- **MODIFIED:** `app.py` — remove unused `load_config` import (dead code). Add `main()` return
  type annotation.
- **MODIFIED:** All `# type: ignore` comments SHALL be resolved by fixing the underlying type
  issue, not by suppressing it.
- **MODIFIED:** All functions >40 lines SHALL be decomposed to ≤40 lines (excluding docstrings).
- **MODIFIED:** All nesting >3 levels SHALL be flattened via early returns, guard clauses, or
  helper extraction.

### No behavior changes

This is a pure refactor. Every test, every CLI command, every graph node, every prompt constant,
and every exception class is preserved exactly. The public API surface (what consumers import
from `__init__.py` files) is preserved. Internal module splits are transparent to consumers via
re-exports.

## Capabilities

### New Capabilities

_None._ No new bounded contexts are created. All changes are within the existing 5 capabilities.

### Modified Capabilities

- **config:** AppConfig decomposition (SRP), CLI separation from loading logic, field validators.
- **translation_pipeline:** Node module split (SRP), PromptVersion protocol (OCP), adapter
  protocols for glossary/retrieval/web-search (DIP), constants extraction, function decomposition.
- **knowledge_sources:** Ingestion module split (SRP), TM lookup decomposition (SRP), normalizer
  registry (OCP), search source registry (OCP), ChromaStore DI (DIP), Term factory methods (DRY),
  shared ChromaStore factory (DRY).
- **infrastructure:** Remove `load_config()` from adapter constructors (DIP), shared error
  translation (DRY), platform registry (OCP), run_logging decomposition (SRP).
- **interfaces:** CLI module split (SRP), web_ui frontend extraction (SRP), shared config loader
  (DRY), Adapters segregation (ISP), DiagnosticsChecker protocol (ISP), HITL decomposition (SRP),
  proper protocol types for `llm`/`tm` (DIP).

## Impact

**Affected code:**
- All 5 components have files modified or split.
- `translation_pipeline/`: `nodes.py` split into 4 files; `prompts.py` adds `PromptVersion`;
  new `constants.py`; `graph.py` type annotations fixed.
- `knowledge_sources/`: `ingestion.py` split into 3 files; `tm.py` lookup decomposed;
  `glossary.py` normalizer registry + Term factory; `retrieval.py` DI + factory;
  `legal_search.py` source registry.
- `infrastructure/`: `llm.py` + `embeddings.py` remove `load_config()`, share error translation;
  `memory.py` platform registry; new `ollama_errors.py`.
- `interfaces/`: `cli.py` split into 4 files; `web_ui.py` frontend extracted; `hitl.py`
  decomposed; `models.py` Adapters segregated; new `config_loader.py`.
- `config/`: `config.py` CLI separated; `models.py` validators added.
- `app.py`: dead code removed, type annotations added.
- All `__init__.py` files: re-exports updated for new sub-modules.
- All test files: imports updated for split modules (re-exports maintain backward compatibility,
  but some internal imports may need updating).

**Affected APIs:**
- Public API surface (symbols exported from `__init__.py`) is preserved. No breaking changes for
  consumers using `from src.components.<context> import <symbol>`.
- Internal module paths change (e.g., `nodes.py` formatters move to `formatters.py`), but
  `__init__.py` re-exports maintain backward compatibility.
- Constructor signatures for `OllamaEngineAdapter`, `Embedder`, and `ChromaStore` change: they
  no longer call `load_config()` internally. Callers that relied on the auto-config behavior must
  pass config explicitly. This is a **BREAKING** change for direct instantiation, but the CLI's
  `_construct_adapters` already passes config explicitly, so the primary entry point is unaffected.

**Dependencies:** No new runtime dependencies. No dependency version changes.

**Systems affected:**
- CLI invocation (`iraqi-translate` script, `python -m src.cli`).
- Web UI launch (`python -m src.cli ui`).
- Tkinter UI launch.
- MCP server (`python -m src.mcp_server`).
- Test suite (import updates for split modules).
- Linting (ruff per-file-ignores paths for new files).
- Type-checking (mypy paths for new files; resolution of `type: ignore` comments).

**Migration path:** Module-by-module, one split or extraction per task, foundation-first ordering
(infrastructure → translation_pipeline → knowledge_sources → interfaces → config). After each
module split, run `python -c "import ..."` smoke checks and `pytest --tb=short -q`. After all
splits, update `__init__.py` re-exports, then update test imports, then run the full suite. See
`design.md` for the complete strategy and `tasks.md` for the ordered task list.

**Rollback plan:** The refactor is performed on a dedicated git branch
(`refactor/solid-clean-code`). Each phase is committed separately (infrastructure, pipeline,
knowledge, interfaces, config, cleanup). To roll back, abandon the branch and return to
`refactor/component-architecture`. No data files, no `db/`, no `data/` directories are touched —
only Python source, tests, and `pyproject.toml`.

**Affected files (old → new):**

| Old path | New path |
|---|---|
| `src/components/translation_pipeline/nodes.py` | `nodes.py` (slimmed) + `formatters.py` + `parsers.py` + `mappers.py` |
| `src/components/translation_pipeline/prompts.py` | `prompts.py` (modified: adds `PromptVersion` protocol) |
| `src/components/translation_pipeline/graph.py` | `graph.py` (modified: type annotations) |
| _(new)_ | `src/components/translation_pipeline/constants.py` |
| `src/components/knowledge_sources/ingestion.py` | `ingestion.py` (slimmed) + `manifest.py` + `ingestion_runner.py` |
| `src/components/knowledge_sources/tm.py` | `tm.py` (modified: lookup decomposed) |
| `src/components/knowledge_sources/glossary.py` | `glossary.py` (modified: normalizer registry + Term factory) |
| `src/components/knowledge_sources/retrieval.py` | `retrieval.py` (modified: DI + factory) |
| `src/components/knowledge_sources/legal_search.py` | `legal_search.py` (modified: source registry) |
| `src/components/infrastructure/llm.py` | `llm.py` (modified: removes `load_config()`, shared errors) |
| `src/components/infrastructure/embeddings.py` | `embeddings.py` (modified: removes `load_config()`, shared errors) |
| `src/components/infrastructure/memory.py` | `memory.py` (modified: platform registry) |
| `src/components/infrastructure/run_logging.py` | `run_logging.py` (modified: log_node decomposed) |
| _(new)_ | `src/components/infrastructure/ollama_errors.py` |
| `src/components/interfaces/cli.py` | `cli.py` (slimmed) + `diagnostics.py` + `orchestration.py` + `tm_commands.py` |
| `src/components/interfaces/web_ui.py` | `web_ui.py` (slimmed) + `web_frontend.py` |
| `src/components/interfaces/hitl.py` | `hitl.py` (modified: decomposed) |
| `src/components/interfaces/models.py` | `models.py` (modified: Adapters segregated) |
| _(new)_ | `src/components/interfaces/config_loader.py` |
| `src/config/config.py` | `config.py` (modified: CLI separated) |
| `src/config/models.py` | `models.py` (modified: validators added) |
| `src/app.py` | `app.py` (modified: dead code removed, types added) |
| `pyproject.toml` | `pyproject.toml` (modified: ruff per-file-ignores for new paths) |
| `tests/*.py` | `tests/*.py` (imports updated for split modules) |

**Basis:** This proposal is grounded in a systematic SOLID-principle analysis of all 33 source
files across the 5 components. The analysis identified 30+ SOLID violations (SRP: 15, OCP: 5,
DIP: 7, ISP: 3) and 25+ clean-code issues (god functions, deep nesting, magic values, duplicated
code, type-ignore suppressions, dead code). The refactor addresses each violation while preserving
the component boundaries established by the prior `refactor-to-component-architecture` change.
