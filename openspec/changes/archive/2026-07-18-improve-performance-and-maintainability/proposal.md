## Why

A production-grade audit (2026-07-18) found that the project's
performance and maintainability have several medium-impact issues that,
while not Critical, erode the 8 GB RAM budget and the DRY/SRP
principles the project claims to follow:

1. **Streaming / materialization issues (PERF-1, PERF-2, PERF-3):**
   - `retrieval.py:144-174, 212-237` materializes all chunk texts into
     a `list[str]` before embedding — for large imports, this holds
     hundreds of MB before embedding begins, violating the 8 GB budget.
   - `tm.py:187-217` `build_from_corpus` and `_build_trigram_index`
     load the entire TM into Python lists (`fetchall()` + unbounded
     `trigram_rows`).
   - `ingestion.py:409-436, 504-554` calls `approx_token_count` multiple
     times on the same spans (paragraph, then sentences, then again
     during packing/overlap) — O(n) redundant tokenization.

2. **Duplicated helpers (MAINT-1, MAINT-2, MAINT-3, MAINT-4, MAINT-5):**
   - `_resolve_path` is duplicated across `cli.py`, `diagnostics.py`,
     and `tm_commands.py` with lazy-import workarounds.
   - The `OllamaConnectionError`/`EmbeddingConnectionError`/`RAMGuardError`
     handler is duplicated 3× in `cli.py`.
   - JSONL parsing is duplicated between `tm_build_parallel` and
     `tm_add_parallel`.
   - `batch_size <= 0` validation is duplicated in `embeddings.py`.
   - `Term(...)` 12-field construction is duplicated in
     `load_glossary_files` and `_derive_reverse_terms`.

3. **SRP violations (MAINT-6, MAINT-7, MAINT-8, MAINT-9):**
   - `cli.py` (539 lines, 8 commands) mixes argument parsing, adapter
     construction, error handling, output rendering, and command
     registration.
   - `web_ui.py:Api` (15+ methods) mixes translation, Excel, HITL,
     file dialogs, history, and store counts.
   - `orchestration.py:run_translation_streamed` (68 lines) mixes graph
     build, stream loop, history capture, and HITL.
   - `cli.py:ui` command hard-imports `web_ui.launch_ui` — an OCP
     violation; selecting the UI backend should be config-driven.

4. **Inconsistent CLI exit codes (MAINT-10):** `doctor`/`ingest` use
   only exit code 1; `translate` uses 1/2/3. There is no documented
   standard.

5. **Glossary ReDoS risk (SEC-12):** `glossary.py:610-657` compiles all
   glossary terms into a single large regex alternation. For large
   glossaries, build time scales poorly and a crafted term can cause
   ReDoS. The fix is Aho-Corasick (`pyahocorasick`), which is O(n) in
   the input length regardless of glossary size.

6. **Minor code smells (CS-16 through CS-23, PERF-4 through PERF-12):**
   dead params, redundant `gc.collect()`, manual `Term` reconstruction
   instead of `dataclasses.replace`, O(n²) URL dedup, no result caching
   in `legal_search`, etc.

This change addresses the medium-priority items that were not covered
by the four Critical/High changes. It is the "polish" change that
brings the codebase from "works" to "maintainable."

## What Changes

1. **Stream embeddings in batches** (`retrieval.py`, `tm.py`):
   - `retrieval.py:_write_collection` and `add_chunks`: replace
     `texts = [c.text for c in chunks]` with a generator that yields
     `embedding_batch_size` chunks at a time, embedding and inserting
     each batch before materializing the next.
   - `tm.py:build_from_corpus` and `_build_trigram_index`: use
     `executemany` with chunked generators instead of `fetchall()` +
     unbounded `trigram_rows` list.

2. **Cache `approx_token_count`** (`ingestion.py`):
   - Add a `dict[tuple[int, int], int]` cache keyed by span offsets
     alongside the spans, so each span's token count is computed once.

3. **Extract `src/utils/` helpers** (shared with
   `harden-untrusted-input-surfaces` and `fix-error-handling-and-logging`):
   - `paths.py:resolve_path` (replaces the 3 duplicated `_resolve_path`
     copies in `cli.py`, `diagnostics.py`, `tm_commands.py`).
   - `cli_errors.py:handle_pipeline_errors` decorator (replaces the 3
     duplicated error handlers in `cli.py`).
   - `jsonl_schema.py:load_parallel_pairs` (replaces the duplicated
     JSONL parsing in `tm_commands.py`).
   - `batch_size.py:validate_batch_size` (replaces the duplicated
     validation in `embeddings.py`).
   - `terms.py:create_term_with_order` (replaces the duplicated `Term`
     construction in `glossary.py`).

4. **Split `cli.py` into per-command modules** (MAINT-6):
   - Create `src/components/interfaces/commands/` with one module per
     command: `doctor.py`, `translate.py`, `batch.py`, `ingest.py`,
     `tm_build.py`, `tm_add.py`, `ui.py`.
   - `cli.py` becomes a thin Typer app that imports and registers the
     commands.
   - Each command module owns its argument parsing, adapter
     construction, error handling, and output rendering.

5. **Split `web_ui.py:Api` into facades** (MAINT-7):
   - `TranslationApi` (translate, submit_review, approve_review,
     get_history)
   - `ExcelApi` (translate_excel, pick_excel_input, pick_excel_output,
     open_in_explorer)
   - `SystemApi` (get_models, get_default_model, get_examples,
     get_store_counts)
   - `Api` becomes a thin facade that composes the three.

6. **Extract HITL coordination from `run_translation_streamed`**
   (MAINT-8):
   - Move the HITL stream-loop + history-capture logic into a
     `_HITLStreamCoordinator` helper class.

7. **Add `UiBackend` protocol** (MAINT-9):
   - `src/components/interfaces/ui_backend.py` defines a
     `UiBackend` protocol with `launch(cfg, adapters) -> None`.
   - `web_ui.launch_ui` and `tk_ui.launch_ui` satisfy it.
   - `cli.py:ui` selects the backend from `cfg.ui.backend` (default
     `"web"`).

8. **Standardize CLI exit codes** (MAINT-10):
   - Document a standard exit-code table in `AGENTS.md` §11:
     0 = success, 1 = generic error, 2 = Ollama/embedding connection,
     3 = RAM guard, 4 = path-containment violation (from
     `harden-untrusted-input-surfaces`), 5 = JSONL validation error
     (from `harden-untrusted-input-surfaces`), 6 = input/output I/O
     error.
   - Update `doctor`/`ingest` to use the appropriate codes.

9. **Switch glossary matcher to Aho-Corasick** (SEC-12):
   - Add `pyahocorasick>=2.0,<3` to `requirements.txt` and
     `pyproject.toml`.
   - Replace the regex alternation in `glossary.py:610-657` with an
     `ahocorasick.Automaton` built once at index load.
   - Fallback to the regex matcher if `pyahocorasick` is not installed
     (graceful degradation).

10. **Minor cleanups:**
    - Remove `glossary_scan` alias (CS-16).
    - Remove dead params: `excel.py:segments`, `excel.py:cfg`,
      `ingestion_runner.py:rebuild` (CS-17/18/19).
    - Move `import ollama` into `doctor` command (CS-20).
    - Deduplicate `formatters.py` snippet branch (CS-21).
    - Auto-generate `ALL_PROMPT_CONSTANTS` via introspection (CS-22).
    - Validate `confidence` in `[0.0, 1.0]` range in `parsers.py`
      (CS-23).
    - Use `dataclasses.replace` in `glossary.py:load_glossary_files`
      (PERF-9).
    - Cache `check_ram_guard` result for N seconds (PERF-5).
    - Remove redundant `gc.collect()` calls (PERF-7/8).
    - Add in-memory TTL cache to `legal_search.py` (PERF-11).
    - Use `lastrowid` in `tm.py:add_parallel` (PERF-12).
    - Use `dict[url, SearchHit]` in `legal_search.py` dedup (PERF-4).
    - Cache config load with mtime check (PERF-10).

## Capabilities

### New Capabilities

- `cli-commands`: The per-command modules split out of `cli.py`. Each
  command is a separate module with its own argument parsing and
  error handling.
- `ui-backends`: The `UiBackend` protocol and its implementations
  (`web_ui`, `tk_ui`).

### Modified Capabilities

- `interfaces`: `cli.py` is split into per-command modules; `web_ui.py:Api`
  is split into facades; `orchestration.py:run_translation_streamed` is
  refactored; `ui` command selects backend via config.
- `knowledge_sources`: `retrieval.py` streams embeddings; `tm.py`
  streams trigram builds; `glossary.py` switches to Aho-Corasick;
  `legal_search.py` adds TTL cache and `dict`-based dedup.
- `infrastructure`: `embeddings.py` batch-size validation extracted;
  `llm.py` RAM-guard cached; `memory.py` `check_ram_guard` cached.
- `translation_pipeline`: `parsers.py` validates confidence range;
  `prompts.py` auto-generates `ALL_PROMPT_CONSTANTS`.

## Impact

**Affected code:** (extensive — see "What Changes" above for the full
list; ~20 files modified, ~10 new files created)

**New dependencies:**
- `pyahocorasick>=2.0,<3` (C extension with wheels for Windows/Linux/
  macOS; ~100 KB). Added to both `requirements.txt` and
  `pyproject.toml`.

**APIs:**
- `cli.py` internal structure changes (per-command modules), but the
  public CLI surface (`iraqi-translate doctor/translate/batch/...`)
  is unchanged.
- `web_ui.py:Api` internal structure changes (facades), but the JS-
  facing method names are unchanged.
- New `UiBackend` protocol; `cfg.ui.backend` config key (default
  `"web"`).

**Specs:**
- `interfaces/spec.md` MODIFIED requirements for CLI, web UI, and
  orchestration.
- `knowledge_sources/spec.md` MODIFIED requirements for retrieval, TM,
  glossary, and legal search.
- `infrastructure/spec.md` MODIFIED requirements for embeddings and
  RAM guard.
- `translation_pipeline/spec.md` MODIFIED requirement for parsers.
- New `cli-commands/spec.md` and `ui-backends/spec.md`.

**Migration path:**
- `pip install -r requirements.txt` picks up `pyahocorasick`.
- `cfg.ui.backend` defaults to `"web"`; existing configs without it
  continue to work.
- No data migration; no DB schema changes.

**Rollback plan:**
- `git revert`. The `src/utils/` helpers and per-command modules can
  be left in place (they are not imported by anything else) or removed
  in the same revert.

**Performance/maintainability impact:**
- Closes audit findings PERF-1/2/3/4/5/7/8/9/10/11/12, MAINT-1…10,
  CS-16…23, SEC-12. This is the largest change by file count but the
  lowest risk per file — each item is a small, isolated refactor.
