## Context

The codebase is clean but has medium-impact performance and
maintainability issues: streaming/materialization problems that threaten
the 8 GB RAM budget, duplicated helpers across `interfaces`, SRP
violations in `cli.py` and `web_ui.py:Api`, inconsistent CLI exit codes,
a glossary regex with ReDoS risk, and a handful of minor code smells.
None are Critical, but together they erode the DRY/SRP principles the
project claims to follow.

## Goals / Non-Goals

**Goals:**
- Stream embeddings and trigram builds so large imports do not OOM.
- Extract shared helpers to `src/utils/` (shared with
  `harden-untrusted-input-surfaces` and `fix-error-handling-and-logging`).
- Split `cli.py` into per-command modules and `web_ui.py:Api` into
  facades.
- Add a `UiBackend` protocol for OCP.
- Standardize CLI exit codes.
- Switch the glossary matcher to Aho-Corasick.
- Clean up minor code smells (dead params, redundant GC, etc.).

**Non-Goals:**
- Rewriting the LangGraph topology — that is correct.
- Changing the public CLI surface or JS-facing API names.
- Adding async I/O — LangGraph is synchronous.
- Replacing `typer.secho` with `logging` for user-facing output (that
  is `fix-error-handling-and-logging`).

## Decisions

### D1: Aho-Corasick with regex fallback

**Decision:** Switch the glossary matcher to `pyahocorasick.Automaton`,
built once at index load. If `pyahocorasick` is not installed, fall
back to the existing regex matcher (graceful degradation).

**Rationale:** Aho-Corasick is O(n) in the input length regardless of
glossary size, vs. regex alternation which is O(n·m) in the worst case
and vulnerable to ReDoS. The fallback preserves the "no new hard
dependency" property for users who cannot install the C extension.

**Trade-off:** Adds `pyahocorasick` as a runtime dependency. Accepted:
it has wheels for all major platforms and is ~100 KB.

### D2: Per-command modules, not a single mega-file

**Decision:** Split `cli.py` into `src/components/interfaces/commands/`
with one module per command. `cli.py` becomes a thin Typer app.

**Rationale:** `cli.py` is 539 lines with 8 commands, mixing argument
parsing, adapter construction, error handling, and output rendering.
Per-command modules make each command independently testable and
editable.

### D3: `Api` facades, not a single class

**Decision:** Split `web_ui.py:Api` into `TranslationApi`, `ExcelApi`,
and `SystemApi`. `Api` becomes a thin facade that composes them and
exposes the same method names to JS.

**Rationale:** `Api` has 15+ methods spanning translation, Excel, HITL,
file dialogs, history, and store counts. Facades make each concern
independently testable. The JS-facing names are unchanged, so the
frontend does not need updates.

### D4: `UiBackend` protocol, config-driven selection

**Decision:** `src/components/interfaces/ui_backend.py` defines a
`UiBackend` protocol with `launch(cfg, adapters) -> None`. `cli.py:ui`
selects the backend from `cfg.ui.backend` (default `"web"`).

**Rationale:** The current `cli.py:ui` hard-imports `web_ui.launch_ui`,
violating OCP. A protocol + config key lets users choose `tk` without
code changes.

### D5: CLI exit-code table documented in AGENTS.md

**Decision:** Document a standard exit-code table in `AGENTS.md` §11:
0 = success, 1 = generic error, 2 = Ollama/embedding connection, 3 =
RAM guard, 4 = path-containment violation, 5 = JSONL validation, 6 =
I/O error. Update all commands to use the appropriate codes.

**Rationale:** Inconsistent exit codes make scripting unreliable. A
documented table is the fix.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Splitting `cli.py` and `Api` is a large diff that could introduce regressions | Each split is a mechanical move; run the full test suite after each split. |
| `pyahocorasick` C extension may not build on some platforms | Wheels exist for Windows/Linux/macOS; fallback to regex preserves functionality. |
| `cfg.ui.backend` is a new config key | Defaults to `"web"`; existing configs without it continue to work. |
| Streaming embeddings changes the order of ChromaDB inserts | ChromaDB order does not affect query results (ANN is order-independent); verified by existing tests. |

## Target directory tree (new and modified files)

```
src/utils/                          # shared with other changes
  paths.py                          # resolve_path (replaces 3 _resolve_path copies)
  cli_errors.py                     # handle_pipeline_errors decorator
  jsonl_schema.py                   # load_parallel_pairs (already created by harden change)
  batch_size.py                     # validate_batch_size
  terms.py                          # create_term_with_order
src/components/
  interfaces/
    cli.py                          # MODIFIED: thin Typer app, imports commands/
    commands/                       # NEW
      __init__.py
      doctor.py
      translate.py
      batch.py
      ingest.py
      tm_build.py
      tm_add.py
      ui.py
    ui_backend.py                   # NEW: UiBackend protocol
    web_ui.py                       # MODIFIED: Api → TranslationApi + ExcelApi + SystemApi facade
    orchestration.py                # MODIFIED: extract _HITLStreamCoordinator
    excel.py                        # MODIFIED: remove dead segments/cfg params
    diagnostics.py                  # MODIFIED: use utils.paths.resolve_path
    tm_commands.py                  # MODIFIED: use utils.paths.resolve_path + utils.jsonl_schema.load_parallel_pairs
  knowledge_sources/
    retrieval.py                    # MODIFIED: stream embeddings in batches
    tm.py                           # MODIFIED: stream trigram builds, use lastrowid
    glossary.py                     # MODIFIED: Aho-Corasick matcher, dataclasses.replace, remove glossary_scan alias
    legal_search.py                 # MODIFIED: dict-based dedup, TTL cache
    ingestion.py                    # MODIFIED: cache approx_token_count
    ingestion_runner.py             # MODIFIED: remove dead rebuild param
  infrastructure/
    embeddings.py                   # MODIFIED: use utils.batch_size.validate_batch_size
    llm.py                          # MODIFIED: cache check_ram_guard
    memory.py                       # MODIFIED: cache check_ram_guard result
  translation_pipeline/
    parsers.py                      # MODIFIED: validate confidence in [0.0, 1.0]
    prompts.py                      # MODIFIED: auto-generate ALL_PROMPT_CONSTANTS
config.yaml                         # MODIFIED: ui.backend default
requirements.txt                    # MODIFIED: + pyahocorasick>=2.0,<3
pyproject.toml                      # MODIFIED: + pyahocorasick>=2.0,<3
AGENTS.md                           # MODIFIED: §11 exit-code table
```
