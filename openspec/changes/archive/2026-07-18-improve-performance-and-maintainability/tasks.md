## 1. `src/utils/` shared helpers

- [x] 1.1 Create `src/utils/paths.py:resolve_path(path_str: str, *, cfg: AppConfig) -> Path` (replaces the 3 `_resolve_path` copies)
- [x] 1.2 Create `src/utils/cli_errors.py:handle_pipeline_errors` decorator that catches `OllamaConnectionError`/`EmbeddingConnectionError` (→ exit 2), `RAMGuardError` (→ exit 3), `PathContainmentError` (→ exit 4), `InputValidationError` (→ exit 5), `OSError` (→ exit 6), and prints a clear error for each
- [x] 1.3 Create `src/utils/batch_size.py:validate_batch_size(n: int) -> int` that raises `ValueError` if `n <= 0`
- [x] 1.4 Create `src/utils/terms.py:create_term_with_order(term: Term, file_order: int) -> Term` using `dataclasses.replace`
- [x] 1.5 Add `load_parallel_pairs(path: Path, max_pairs: int | None = None) -> list[ParallelPair]` to `src/utils/jsonl_schema.py` (shared with `harden-untrusted-input-surfaces`)
- [x] 1.6 Verify: `ruff check src/utils/` is clean; `python -c "import src.utils.paths, src.utils.cli_errors, src.utils.batch_size, src.utils.terms"` succeeds

## 2. Streaming embeddings + trigram builds

- [x] 2.1 In `retrieval.py:_write_collection`, replace `texts = [c.text for c in chunks]` with a generator that yields `embedding_batch_size` chunks at a time, embedding and inserting each batch before materializing the next
- [x] 2.2 In `retrieval.py:add_chunks`, apply the same streaming pattern
- [x] 2.3 In `tm.py:build_from_corpus`, use `executemany` with chunked generators instead of `fetchall()` + unbounded list
- [x] 2.4 In `tm.py:_build_trigram_index`, insert trigrams in batches of 1000 via `executemany` instead of building an unbounded `trigram_rows` list
- [x] 2.5 Verify: `pytest tests/test_retrieval.py tests/test_tm.py -q` passes
- [x] 2.6 Add new tests: `test_retrieval_streams_large_corpus_without_oom` (mock 10 000 chunks; assert peak memory < 2x baseline), `test_tm_build_streams_trigrams`

## 3. Cache `approx_token_count`

- [x] 3.1 In `ingestion.py`, add a `dict[tuple[int, int], int]` cache keyed by span offsets alongside the spans
- [x] 3.2 Update `chunk_article` and `_pack_units_with_overlap` to check the cache before calling `approx_token_count`
- [x] 3.3 Verify: `pytest tests/test_ingestion.py -q` passes
- [x] 3.4 Add new test: `test_approx_token_count_cached` (mock `approx_token_count` to count calls; assert it is called once per unique span)

## 4. Split `cli.py` into per-command modules

- [x] 4.1 Create `src/components/interfaces/commands/__init__.py`
- [x] 4.2 Create `commands/doctor.py` with the `doctor` command (move from `cli.py`)
- [x] 4.3 Create `commands/translate.py` with the `translate` command
- [x] 4.4 Create `commands/batch.py` with the `batch` command
- [x] 4.5 Create `commands/ingest.py` with the `ingest` command
- [x] 4.6 Create `commands/tm_build.py` with the `tm-build` and `tm-build-parallel` commands
- [x] 4.7 Create `commands/tm_add.py` with the `tm-add-parallel` command
- [x] 4.8 Create `commands/ui.py` with the `ui` command (uses `UiBackend` from task 6)
- [x] 4.9 Rewrite `cli.py` as a thin Typer app that imports and registers the commands; apply `handle_pipeline_errors` decorator to each
- [x] 4.10 Move `import ollama` into `commands/doctor.py` (CS-20)
- [x] 4.11 Verify: `pytest tests/test_cli.py -q` passes; `iraqi-translate --help` lists all 8 commands

## 5. Split `web_ui.py:Api` into facades

- [x] 5.1 Create `TranslationApi` with `translate`, `submit_review`, `approve_review`, `get_history`
- [x] 5.2 Create `ExcelApi` with `translate_excel`, `pick_excel_input`, `pick_excel_output`, `open_in_explorer`
- [x] 5.3 Create `SystemApi` with `get_models`, `get_default_model`, `get_examples`, `get_store_counts`
- [x] 5.4 Rewrite `Api` as a thin facade that composes the three and exposes the same method names to JS
- [x] 5.5 Verify: `pytest tests/test_web_ui_excel.py -q` passes; JS-facing method names unchanged

## 6. `UiBackend` protocol + config-driven selection

- [x] 6.1 Create `src/components/interfaces/ui_backend.py` with a `UiBackend` protocol (`launch(cfg, adapters) -> None`)
- [x] 6.2 Verify `web_ui.launch_ui` and `tk_ui.launch_ui` satisfy the protocol
- [x] 6.3 Add `UiConfig` with `backend: Literal["web", "tk"] = "web"` to `src/config/models.py`; expose as `cfg.ui`
- [x] 6.4 Add `ui.backend: web` default to `config.yaml`
- [x] 6.5 Update `commands/ui.py` to select the backend from `cfg.ui.backend`
- [x] 6.6 Verify: `pytest tests/test_cli.py -q` passes; `iraqi-translate ui` launches the web UI by default

## 7. Extract `_HITLStreamCoordinator` from `run_translation_streamed`

- [x] 7.1 In `orchestration.py`, extract the HITL stream-loop + history-capture logic into a `_HITLStreamCoordinator` class
- [x] 7.2 `run_translation_streamed` becomes a thin wrapper that constructs the coordinator and runs it
- [x] 7.3 Verify: `pytest tests/test_orchestration.py -q` passes

## 8. Standardize CLI exit codes

- [x] 8.1 Document the exit-code table in `AGENTS.md` §11 (0=success, 1=generic, 2=Ollama/embedding, 3=RAM guard, 4=path-containment, 5=JSONL validation, 6=I/O)
- [x] 8.2 Update `commands/doctor.py` to use exit code 2 for Ollama connection failure (currently 1)
- [x] 8.3 Update `commands/ingest.py` to use exit code 2 for Ollama/embedding connection, 3 for RAM guard (currently 1 for both)
- [x] 8.4 Verify: `pytest tests/test_cli.py -q` passes; update tests that assert exit code 1 for connection errors

## 9. Aho-Corasick glossary matcher

- [x] 9.1 Add `pyahocorasick>=2.0,<3` to `requirements.txt` and `pyproject.toml`
- [x] 9.2 `pip install pyahocorasick` and verify import works
- [x] 9.3 In `glossary.py`, build an `ahocorasick.Automaton` at index load instead of the regex alternation
- [x] 9.4 Add a fallback to the regex matcher if `pyahocorasick` is not installed (`try: import ahocorasick except ImportError: ...`)
- [x] 9.5 Verify: `pytest tests/test_glossary.py -q` passes
- [x] 9.6 Add new tests: `test_glossary_ahocorasick_matches_regex_results` (same hits for same input), `test_glossary_falls_back_to_regex_without_ahocorasick` (mock `import ahocorasick` to raise `ImportError`)

## 10. Minor cleanups

- [x] 10.1 Remove `glossary_scan` alias in `glossary.py` (CS-16); grep for callers and update
- [x] 10.2 Remove dead `segments` param from `excel.py:extract_translatable_strings` and `cfg` param (CS-17/18); update callers
- [x] 10.3 Remove dead `rebuild` param from `ingestion_runner.py` (CS-19); update callers
- [x] 10.4 Deduplicate `formatters.py` snippet branch (CS-21)
- [x] 10.5 Auto-generate `ALL_PROMPT_CONSTANTS` in `prompts.py` via introspection of module-level `_*` constants (CS-22)
- [x] 10.6 Validate `confidence` in `[0.0, 1.0]` range in `parsers.py` (CS-23); raise `ParserError` on out-of-range
- [x] 10.7 Use `dataclasses.replace` in `glossary.py:load_glossary_files` (PERF-9)
- [x] 10.8 Cache `check_ram_guard` result for 5 seconds in `memory.py` (PERF-5)
- [x] 10.9 Remove redundant `gc.collect()` in `retrieval.py:_close_handles` (PERF-7) and `ingestion_runner.py` (PERF-8)
- [x] 10.10 Add in-memory TTL cache (5 min) to `legal_search.py` search functions (PERF-11)
- [x] 10.11 Use `lastrowid` in `tm.py:add_parallel` (PERF-12)
- [x] 10.12 Use `dict[url, SearchHit]` in `legal_search.py` dedup (PERF-4)
- [x] 10.13 Cache config load with mtime check in `config.py:load_config` (PERF-10)
- [x] 10.14 Verify: `pytest --tb=short -q` passes (full suite excluding `slow`)

## 11. Documentation + final verification

- [x] 11.1 Update `AGENTS.md` §11 with the exit-code table and the `UiBackend` protocol
- [x] 11.2 Update `README.md` §5 to mention `pyahocorasick` and the `ui.backend` config key
- [x] 11.3 Run `ruff check src/ tests/` — must be clean
- [x] 11.4 Run `mypy src/` — must not introduce new errors
- [x] 11.5 Run `pytest --tb=short -q` — full suite green (excluding `slow`)
- [x] 11.6 Run `openspec validate improve-performance-and-maintainability` — must pass
- [x] 11.7 Run `openspec validate --all` — must pass
