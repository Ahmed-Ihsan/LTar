## Why

The `src/` directory has grown to 21 flat modules with no structural boundaries. As the system added Translation Memory, web search, HITL review, MCP server, and two desktop UIs, the flat layout stopped communicating intent: a contributor cannot tell which modules form a cohesive bounded context, where domain models live, or which layers may depend on which. This raises onboarding cost, invites accidental cross-boundary coupling, and blocks any future extraction of a component into its own package. Refactoring into a **component + models** architecture — one folder per bounded context, each with a `models.py` for its domain types — makes the system's boundaries explicit and aligns the code structure with the Event Storming analysis.

## What Changes

- **BREAKING (import paths only):** Every `from src.<module>` import changes to `from src.components.<context>.<module>` (or `from src.config.<module>`). All 21 flat modules move into 4 components + 1 config package. Public APIs are preserved via `__init__.py` re-exports, so `from src.config import AppConfig` continues to work.
- **ADDED:** `src/config/` package with `config.py` (loader + `AppConfig` + `ConfigError` + Typer `app`) and `models.py` (`PathsConfig`, `ChromaConfig`).
- **ADDED:** `src/components/translation_pipeline/` — `models.py` (all TypedDicts + `Direction`/`Verdict`), `graph.py`, `nodes.py`, `decision.py`, `prompts.py`, `exceptions.py`.
- **ADDED:** `src/components/knowledge_sources/` — `models.py` (domain models), `glossary.py`, `retrieval.py`, `tm.py`, `legal_search.py`, `ingestion.py`.
- **ADDED:** `src/components/infrastructure/` — `models.py` (`MemoryInfo`, `RunLogEntry`), `llm.py`, `embeddings.py`, `memory.py`, `run_logging.py`.
- **ADDED:** `src/components/interfaces/` — `models.py` (`CheckResult`, `Adapters`, `UiTranslationResult`), `cli.py`, `web_ui.py`, `tk_ui.py`, `mcp_server.py`, `hitl.py`.
- **ADDED:** `src/app.py` — dependency-injection entry point that wires all components and exposes `main()` for the console script.
- **MODIFIED:** `pyproject.toml` — `[project.scripts]` entry point → `src.app:main`; `[tool.setuptools]` packages list expanded; `[tool.ruff.lint.per-file-ignores]` paths updated to new locations.
- **REMOVED:** All 21 flat `src/*.py` modules (after content is moved and imports updated).
- No behavior changes: every test, every CLI command, every graph node, every prompt constant, and every exception class is preserved exactly. This is a pure structural refactor.

## Capabilities

### New Capabilities

- `translation_pipeline`: The LangGraph translation state machine — state schema, graph wiring, node functions, TM routing decision, versioned prompts, and the domain exception hierarchy. (Spec documents current behavior as source of truth; delta adds component-structure requirements.)
- `knowledge_sources`: The knowledge layer — exact-match glossary, ChromaDB retrieval, Translation Memory, Iraqi legal-source web search, and corpus ingestion/chunking. (Spec documents current behavior; delta adds component-structure requirements.)
- `infrastructure`: The adapter layer — LLM engine adapter (Ollama), embedding adapter, system memory / RAM guard, and structured run logging. (Spec documents current behavior; delta adds component-structure requirements.)
- `interfaces`: The delivery layer — CLI (Typer), pywebview desktop UI, Tkinter desktop UI, MCP server, and human-in-the-loop review. (Spec documents current behavior; delta adds component-structure requirements.)
- `config`: Configuration loading and validation from `config.yaml` via Pydantic models. (Spec documents current behavior; delta adds the config-package split into `config.py` + `models.py`.)

### Modified Capabilities

_None at the behavior level._ All five capabilities above are new as spec'd capabilities (no prior specs exist in `openspec/specs/`). The delta specs for this change add structural requirements (component folders, `models.py` per component, `__init__.py` re-exports, `app.py` entry point) on top of the behavior requirements captured in the source-of-truth specs.

## Impact

**Affected code:**
- All 21 modules in `src/` are moved (content relocated, old files deleted).
- All 31 test files in `tests/` have their `from src.*` imports rewritten.
- `tests/conftest.py` fixtures updated.
- `pyproject.toml` — packages, scripts, ruff ignores.
- `src/__init__.py` — may need adjustment if it re-exports anything.

**Affected APIs:**
- Import paths change for every public symbol. Re-exports via `__init__.py` files provide backward-compatible short paths (e.g., `from src.config import AppConfig`).
- The console entry point changes from `src.cli:app` to `src.app:main`.

**Dependencies:** No new runtime dependencies. No dependency version changes.

**Systems affected:**
- CLI invocation (`iraqi-translate` script, `python -m src.cli`).
- Web UI launch (`python -m src.cli ui`).
- Tkinter UI launch.
- MCP server (`python -m src.mcp_server`).
- Test suite (31 test files).
- Linting (ruff per-file-ignores paths).
- Type-checking (mypy paths).

**Migration path:** File-by-file, one move per task, foundation-first ordering (config → translation_pipeline → knowledge_sources → infrastructure → interfaces). After each component migration, run `python -c "import ..."` smoke checks. After all moves, update all intra- and inter-component imports, then test imports, then run the full suite. See `design.md` for the complete strategy and `tasks.md` for the ordered task list.

**Rollback plan:** The refactor is performed on a dedicated git branch (`refactor/component-architecture`). Each phase is committed separately (scaffold, migrate, import-fix, test-fix, lint-fix). To roll back, abandon the branch and return to `main`. No data files, no `db/`, no `data/` directories are touched — only Python source, tests, and `pyproject.toml`.

**Affected files (old → new):**

| Old path | New path |
|---|---|
| `src/config.py` | `src/config/config.py` (+ `src/config/models.py` for `PathsConfig`, `ChromaConfig`) |
| `src/state.py` | `src/components/translation_pipeline/models.py` |
| `src/graph.py` | `src/components/translation_pipeline/graph.py` |
| `src/nodes.py` | `src/components/translation_pipeline/nodes.py` |
| `src/decision.py` | `src/components/translation_pipeline/decision.py` |
| `src/prompts.py` | `src/components/translation_pipeline/prompts.py` |
| `src/exceptions.py` | `src/components/translation_pipeline/exceptions.py` |
| `src/glossary.py` | `src/components/knowledge_sources/glossary.py` |
| `src/retrieval.py` | `src/components/knowledge_sources/retrieval.py` |
| `src/tm.py` | `src/components/knowledge_sources/tm.py` |
| `src/legal_search.py` | `src/components/knowledge_sources/legal_search.py` |
| `src/ingestion.py` | `src/components/knowledge_sources/ingestion.py` |
| `src/llm.py` | `src/components/infrastructure/llm.py` |
| `src/embeddings.py` | `src/components/infrastructure/embeddings.py` |
| `src/memory.py` | `src/components/infrastructure/memory.py` |
| `src/run_logging.py` | `src/components/infrastructure/run_logging.py` |
| `src/cli.py` | `src/components/interfaces/cli.py` |
| `src/web_ui.py` | `src/components/interfaces/web_ui.py` |
| `src/tk_ui.py` | `src/components/interfaces/tk_ui.py` |
| `src/mcp_server.py` | `src/components/interfaces/mcp_server.py` |
| `src/hitl.py` | `src/components/interfaces/hitl.py` |
| _(new)_ | `src/app.py` |
| _(new)_ | `src/config/__init__.py` |
| _(new)_ | `src/config/models.py` |
| _(new)_ | `src/components/__init__.py` |
| _(new)_ | `src/components/translation_pipeline/__init__.py` |
| _(new)_ | `src/components/translation_pipeline/models.py` |
| _(new)_ | `src/components/knowledge_sources/__init__.py` |
| _(new)_ | `src/components/knowledge_sources/models.py` |
| _(new)_ | `src/components/infrastructure/__init__.py` |
| _(new)_ | `src/components/infrastructure/models.py` |
| _(new)_ | `src/components/interfaces/__init__.py` |
| _(new)_ | `src/components/interfaces/models.py` |
| `pyproject.toml` | `pyproject.toml` (modified) |
| `tests/*.py` (31 files) | `tests/*.py` (imports rewritten) |
| `tests/conftest.py` | `tests/conftest.py` (imports rewritten) |

**Basis:** This proposal is grounded in the Event Storming and bounded-context analysis of the existing `src/` modules. The import graph is strictly acyclic with a clear 5-level dependency hierarchy (Foundation → Adapters → Data Stores → Orchestration → Interfaces), which maps directly onto four bounded contexts plus a config package. No circular dependencies exist, so the reorganization is mechanically safe.
