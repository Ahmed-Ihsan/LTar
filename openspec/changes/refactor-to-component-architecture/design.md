## Context

The Iraqi Legal Translation Agent currently uses a flat `src/` layout with 21 Python modules. An architecture analysis (Event Storming + import-graph mapping) revealed a strictly acyclic 5-level dependency hierarchy that maps cleanly onto four bounded contexts plus a config package:

- **Level 0 (Foundation):** state, exceptions, config, prompts, decision, legal_search, memory
- **Level 1 (Adapters):** glossary, embeddings, llm, run_logging, tm
- **Level 2 (Data stores):** retrieval, ingestion
- **Level 3 (Orchestration):** nodes, graph, hitl
- **Level 4 (Interfaces):** cli, web_ui, tk_ui, mcp_server

No circular dependencies exist. This design reorganizes these modules into a component + models architecture where each bounded context is a folder with a `models.py` for its domain types.

## Goals / Non-Goals

**Goals:**
- Make bounded-context boundaries explicit in the file system
- Co-locate each component's domain models in a `models.py`
- Provide backward-compatible re-exports via `__init__.py` files
- Introduce `src/app.py` as a single DI entry point
- Preserve 100% of existing behavior — zero test regressions, zero API changes beyond import paths
- Keep the refactor mechanically safe (one file move per task, foundation-first ordering)

**Non-Goals:**
- No behavior changes to any node, command, prompt, or adapter
- No new features (no new CLI commands, no new graph nodes)
- No dependency version changes
- No changes to `data/`, `db/`, `config.yaml`, or any non-Python file
- No splitting of the project into multiple packages or repos

## Decisions

### D1: Four components + config package

| Component | Path | Modules moved in |
|---|---|---|
| config | `src/config/` | config.py → config.py + models.py |
| translation_pipeline | `src/components/translation_pipeline/` | state, graph, nodes, decision, prompts, exceptions |
| knowledge_sources | `src/components/knowledge_sources/` | glossary, retrieval, tm, legal_search, ingestion |
| infrastructure | `src/components/infrastructure/` | llm, embeddings, memory, run_logging |
| interfaces | `src/components/interfaces/` | cli, web_ui, tk_ui, mcp_server, hitl |

**Rationale:** The import graph shows these five groupings have high internal cohesion and low cross-boundary coupling. The translation_pipeline owns the state machine and domain types. Knowledge sources own all external knowledge access. Infrastructure owns all runtime adapters. Interfaces own all user-facing delivery. Config is split out because it is imported by every other component.

### D2: models.py per component

Each component gets a `models.py` for its domain types:

| Component | models.py contents |
|---|---|
| config | `PathsConfig`, `ChromaConfig` (Pydantic models) |
| translation_pipeline | `TranslationState`, `GlossaryHit`, `ContextChunk`, `AuditVerdict`, `TmHit`, `WebSearchResult`, `Direction`, `Verdict` (TypedDicts + type aliases) |
| knowledge_sources | `Term`, `Article`, `Chunk`, `TmEntry`, `SearchHit`, `ContextChunk` (dataclasses internal to this component) |
| infrastructure | `MemoryInfo`, `RunLogEntry` (dataclasses); protocols may stay in their implementation modules |
| interfaces | `CheckResult`, `Adapters`, `UiTranslationResult` (dataclasses for CLI/UI) |

**Rationale:** Co-locating domain models with their component makes the component self-describing. A reader opening `translation_pipeline/models.py` immediately sees the state schema. This also prevents cross-component model coupling — a component must import another component's models explicitly, making the dependency visible.

**Note on duplicate type names:** `GlossaryHit` and `ContextChunk` exist in both `translation_pipeline/models.py` (as TypedDicts for state) and `knowledge_sources/glossary.py` / `retrieval.py` (as dataclasses for internal use). The current code already has this duality (state.py TypedDicts vs glossary.py/retrieval.py dataclasses). The refactor preserves this as-is — no merging or renaming. The state TypedDicts are projections of the internal dataclasses, and the `_hit_to_state` / `_chunk_to_state` helpers in nodes.py handle the conversion.

### D3: __init__.py re-exports for backward compatibility

Each component's `__init__.py` re-exports the public API. This allows both:
- Short imports: `from src.components.translation_pipeline import TranslationState`
- Direct submodule imports: `from src.components.translation_pipeline.models import TranslationState`

The config package re-exports `AppConfig`, `load_config`, `ConfigError`, `PathsConfig`, `ChromaConfig` so `from src.config import AppConfig` continues to work (it was `from src.config import AppConfig` before, but `src/config.py` → `src/config/__init__.py` re-export).

### D4: app.py as DI entry point

`src/app.py` wires all components together and exposes `main()`:

```
src/app.py
  ├── from src.config import load_config
  ├── from src.components.interfaces.cli import app as cli_app
  └── def main(): cli_app()
```

The console script changes from `iraqi-translate = "src.cli:app"` to `iraqi-translate = "src.app:main"`. The `main()` function delegates to the Typer app. This creates a single seam where DI wiring could be expanded in the future (e.g., constructing adapters once and passing them to the CLI).

### D5: File-by-file migration, foundation-first

Migration follows the dependency graph bottom-up so that at each step, the already-migrated modules have their dependencies satisfied:

1. **Config** (Level 0 — no internal deps)
2. **Translation pipeline** (Level 0-3 — depends on config only at first, then self-contained)
3. **Knowledge sources** (Level 0-2 — depends on config + exceptions from translation_pipeline)
4. **Infrastructure** (Level 0-1 — depends on config + exceptions from translation_pipeline)
5. **Interfaces** (Level 4 — depends on all other components)

Each file move is a separate task. After each component migration, run smoke-check imports. After all moves, update all intra- and inter-component imports, then test imports, then run the full suite.

### D6: Exception hierarchy placement

The exception hierarchy (`exceptions.py`) is placed in `translation_pipeline/` because:
- It is part of the domain model (LegalTranslationError and its subtypes are domain concepts)
- It is imported by knowledge_sources (glossary, retrieval, ingestion) and infrastructure (llm, embeddings, memory)
- Placing it in translation_pipeline makes the dependency direction clear: knowledge_sources and infrastructure depend on translation_pipeline for domain errors

**Alternative considered:** A separate `src/components/shared/` or `src/components/foundation/` component for exceptions. Rejected because it would add a 6th package for a single file, and the current import graph shows exceptions are naturally consumed by the pipeline's domain logic.

## Target Directory Structure

```
src/
├── __init__.py
├── app.py                              # DI entry point, exposes main()
├── config/
│   ├── __init__.py                     # re-exports: AppConfig, load_config, ConfigError, PathsConfig, ChromaConfig
│   ├── config.py                       # AppConfig, load_config, ConfigError, Typer `app`, DEFAULT_CONFIG_PATH
│   └── models.py                       # PathsConfig, ChromaConfig
└── components/
    ├── __init__.py
    ├── translation_pipeline/
    │   ├── __init__.py                 # re-exports: TranslationState, build_graph, route_tm, LegalTranslationError, ...
    │   ├── models.py                   # TranslationState, GlossaryHit, ContextChunk, AuditVerdict, TmHit, WebSearchResult, Direction, Verdict
    │   ├── graph.py                    # build_graph, route_audit, route_after_tm, PREPROCESS_NODE, ..., FINALIZE_NODE
    │   ├── nodes.py                    # preprocess_node, web_search_node, tm_lookup_node, tm_bypass_node, translate_node, audit_node, finalize_node + helpers
    │   ├── decision.py                 # route_tm
    │   ├── prompts.py                  # SHARED_SYSTEM_RULES_V1-V4, TRANSLATOR_SYSTEM_V1-V4, ..., ALL_PROMPT_CONSTANTS
    │   └── exceptions.py               # LegalTranslationError + full hierarchy
    ├── knowledge_sources/
    │   ├── __init__.py                 # re-exports: GlossaryIndex, TranslationMemory, retrieve_context_chunks, ...
    │   ├── models.py                   # Term, Article, Chunk, TmEntry, SearchHit, ContextChunk (internal dataclasses)
    │   ├── glossary.py                 # GlossaryIndex, load_glossary_index, scan_glossary_hits, normalize_arabic, normalize_english, normalize
    │   ├── retrieval.py                # retrieve_context_chunks, ChromaStore, DEFAULT_COLLECTION, DEFAULT_ADD_BATCH
    │   ├── tm.py                       # TranslationMemory, TmEntry
    │   ├── legal_search.py             # search_all_sources, search_dijlex, search_moj, search_ur_portal, search_national_library, SearchHit
    │   └── ingestion.py                # ingest_corpus, iter_articles, chunk_article, parse_corpus_file, approx_token_count, Article, Chunk
    ├── infrastructure/
    │   ├── __init__.py                 # re-exports: LLMEngineAdapter, OllamaEngineAdapter, Embedder, RunLogger, ...
    │   ├── models.py                   # MemoryInfo, RunLogEntry
    │   ├── llm.py                      # LLMEngineAdapter (Protocol), OllamaEngineAdapter, _translate_engine_error
    │   ├── embeddings.py               # EmbeddingAdapter (Protocol), Embedder, embed_batch, EMBED_DIM, DEFAULT_BATCH_SIZE
    │   ├── memory.py                   # read_memory_info, available_ram_gb, check_ram_guard, RAM_GUARD_MIN_GB, MemoryInfo
    │   └── run_logging.py              # RunLogger
    └── interfaces/
        ├── __init__.py                 # re-exports: app, launch_ui, human_review, ...
        ├── models.py                   # CheckResult, Adapters, UiTranslationResult
        ├── cli.py                      # Typer `app`, all commands, helper functions
        ├── web_ui.py                   # launch_ui, Api, _UiHumanReviewer
        ├── tk_ui.py                    # launch_ui, UiWidgets, builder functions
        ├── mcp_server.py               # mcp (FastMCP), tools, main()
        └── hitl.py                     # HumanReviewer (Protocol), human_review, _save_correction, _save_to_tm
```

## Component Dependency Diagram

```
                    ┌─────────┐
                    │  config  │   (Pydantic models, load_config)
                    └────┬─────┘
                         │ imported by all
        ┌────────────────┼────────────────┐
        ▼                ▼                 ▼
┌───────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│ translation_      │  │ knowledge_sources    │  │ infrastructure   │
│ pipeline          │  │                      │  │                  │
│  models.py        │  │  models.py           │  │  models.py       │
│  exceptions.py ◄──┼──┼── imports exceptions  │  │  llm.py          │
│  prompts.py       │  │  glossary.py          │  │  embeddings.py   │
│  decision.py      │  │  retrieval.py         │  │  memory.py       │
│  nodes.py ────────┼──┼──► imports glossary,  │  │  run_logging.py  │
│  graph.py ────────┼──┼──► retrieval, llm     │  │                  │
│                   │  │  tm.py                │  │  imports:        │
│  imports:         │  │  legal_search.py      │  │   config,        │
│   config,         │  │  ingestion.py         │  │   exceptions     │
│   knowledge_src,  │  │                       │  │   (from TP)      │
│   infrastructure  │  │  imports:             │  │                  │
│                   │  │   config,             │  └────────┬─────────┘
│                   │  │   exceptions (from TP)│           │
│                   │  │   embeddings (from IF)│           │
│                   │  └───────────┬───────────┘           │
│                   │              │                       │
└───────────────────┘              │                       │
         ▲                         │                       │
         │                         │                       │
         └─────────────┬───────────┴───────────────────────┘
                       │
              ┌────────┴─────────┐
              │   interfaces     │
              │   models.py      │
              │   cli.py ────────┼──► imports ALL components
              │   web_ui.py      │
              │   tk_ui.py       │
              │   mcp_server.py  │──► imports knowledge_sources
              │   hitl.py ───────┼──► imports translation_pipeline
              └──────────────────┘

TP = translation_pipeline
IF = infrastructure

Dependency direction: interfaces → all; TP → knowledge_sources + infrastructure;
knowledge_sources → TP (exceptions); infrastructure → TP (exceptions).
```

**Key dependency notes:**
- `knowledge_sources` imports `exceptions` from `translation_pipeline` (GlossaryError, CorpusError, RetrievalError, etc.)
- `knowledge_sources/retrieval.py` imports `embeddings` from `infrastructure`
- `knowledge_sources/ingestion.py` imports `glossary` from `knowledge_sources` (intra-component) and `config`
- `infrastructure/llm.py` imports `memory` from `infrastructure` (intra-component) and `exceptions` from `translation_pipeline`
- `interfaces/cli.py` imports from all four other components
- `interfaces/hitl.py` imports `nodes` from `translation_pipeline`
- `interfaces/mcp_server.py` imports `legal_search` from `knowledge_sources`

## Inter-Component Communication Protocol

Components communicate exclusively via **Python imports** (no event bus, no message passing). The protocol is:

1. **Public API only:** Components import only what is re-exported in another component's `__init__.py`. Internal helpers (prefixed with `_`) are not part of the public API.
2. **Protocols for adapter seams:** `LLMEngineAdapter`, `EmbeddingAdapter`, and `HumanReviewer` are PEP 544 Protocols. Components depend on the protocol, not the concrete class. Concrete classes (`OllamaEngineAdapter`, `Embedder`) are constructed in `interfaces/cli.py` and injected via keyword-only args.
3. **TypedDicts for state:** `TranslationState` and its sub-TypedDicts are defined in `translation_pipeline/models.py` and imported by any component that reads or writes state (nodes, hitl, run_logging).
4. **Exceptions as domain contracts:** The exception hierarchy in `translation_pipeline/exceptions.py` is the shared error vocabulary. Components raise and catch these exceptions across boundaries.
5. **Config as shared kernel:** `AppConfig` from `src.config` is imported by every component that needs runtime parameters. It is the shared kernel.

## Migration Strategy

**Approach:** File-by-file, one move per task, foundation-first. Each task is atomic and independently verifiable.

**Phase 4 — Scaffold:** Create all directories and empty placeholder files. Commit.

**Phase 5 — Migrate content:** Move each module's content to its new location. For each file:
1. Copy content to the new location
2. Update the new file's internal imports to point to new component paths (for dependencies that have already been migrated) or old flat paths (for dependencies not yet migrated — these will be fixed in Phase 6)
3. Add re-exports to the component's `__init__.py`
4. Delete the old flat file
5. Run a smoke-check import

**Phase 6 — Update all imports:** After all files are moved, do a global search-replace of all remaining old flat imports (`from src.state` → `from src.components.translation_pipeline.models`, etc.) across all src/ and tests/ files.

**Phase 7 — Update tests:** Rewrite all test imports to component paths. Run the full test suite.

**Phase 8 — Lint and type-check:** Update ruff per-file-ignores paths. Run ruff, mypy, radon.

**Why not big-bang?** A big-bang move would create a single massive commit where every import is broken simultaneously, making it impossible to bisect or verify incrementally. The file-by-file approach allows smoke-checking after each move and produces a clear git history.

## app.py Entry Point Design

```python
"""Application entry point — wires all components and delegates to the CLI."""
from src.components.interfaces.cli import app


def main() -> None:
    """Console script entry point for `iraqi-translate`."""
    app()


if __name__ == "__main__":
    main()
```

**Future expansion:** The `main()` function is the natural seam for expanding DI wiring — constructing adapters once and passing them to the CLI, adding lifecycle hooks, or selecting an interface (CLI vs UI vs MCP) based on arguments. For now, it delegates directly to the Typer app to preserve existing behavior.

## pyproject.toml Changes

### [project.scripts]
```toml
# Before
iraqi-translate = "src.cli:app"

# After
iraqi-translate = "src.app:main"
```

### [tool.setuptools]
```toml
# Before
packages = ["src"]

# After
packages = [
    "src",
    "src.config",
    "src.components",
    "src.components.translation_pipeline",
    "src.components.knowledge_sources",
    "src.components.infrastructure",
    "src.components.interfaces",
]
```

### [tool.ruff.lint.per-file-ignores]
```toml
# Before → After (path migrations)
"src/prompts.py" = ["E501"]
→ "src/components/translation_pipeline/prompts.py" = ["E501"]

"src/web_ui.py" = ["E501"]
→ "src/components/interfaces/web_ui.py" = ["E501"]

"src/llm.py" = ["PLR0913"]
→ "src/components/infrastructure/llm.py" = ["PLR0913"]

"src/cli.py" = ["B008", "PLR0913"]
→ "src/components/interfaces/cli.py" = ["B008", "PLR0913"]

"src/graph.py" = ["PLR0913"]
→ "src/components/translation_pipeline/graph.py" = ["PLR0913"]

"src/run_logging.py" = ["UP017"]
→ "src/components/infrastructure/run_logging.py" = ["UP017"]

# Test file ignores — paths unchanged (tests/ stay flat)
"tests/conftest.py" = ["PLR0913"]   # unchanged
"tests/test_nodes.py" = ["PLR0913"] # unchanged
"tests/test_cli.py" = ["PLR0913"]   # unchanged
```

## Risks / Trade-offs

**Risk: Import path churn.** Every `from src.*` import in src/ and tests/ changes. This is a large diff but mechanically safe (search-replace). Mitigated by `__init__.py` re-exports providing short paths and by running the full test suite after migration.

**Risk: Duplicate type names across components.** `GlossaryHit` and `ContextChunk` exist as both TypedDicts (translation_pipeline/models.py) and dataclasses (knowledge_sources/). This is already the case in the current code. The refactor preserves the duality rather than merging, to avoid behavior changes. Future work could unify these.

**Risk: Exception hierarchy in translation_pipeline creates a cross-component dependency.** knowledge_sources and infrastructure import exceptions from translation_pipeline. This is a conscious decision (D6) — the alternative (a shared/foundation component) was rejected as over-engineering for a single file. If the exception hierarchy grows, this decision can be revisited.

**Trade-off: More files, more boilerplate.** The component structure adds `__init__.py` files and `models.py` files. This is offset by clearer boundaries and self-describing components.

**Trade-off: Longer import paths.** `from src.components.translation_pipeline.models import TranslationState` is longer than `from src.state import TranslationState`. Mitigated by `__init__.py` re-exports allowing `from src.components.translation_pipeline import TranslationState`.
