## 1. TranslationMemory context manager + thread safety

- [x] 1.1 In `tm.py:TranslationMemory.__init__`, remove `check_same_thread=False` from `sqlite3.connect`; add `self._lock = threading.RLock()`
- [x] 1.2 Wrap every `self._conn.execute(...)` and `self._conn.commit()` call in `with self._lock:` (use `replace_all` carefully; verify each site)
- [x] 1.3 Add `TranslationMemory.close()` that closes `self._conn` idempotently (guard with `if self._conn is not None: self._conn.close(); self._conn = None`)
- [x] 1.4 Add `__enter__` returning `self` and `__exit__` calling `close()`
- [x] 1.5 Add `weakref.finalize(self, self._conn.close)` in `__init__` as a safety net (note: `close()` must be idempotent so finalizer + explicit close is safe)
- [x] 1.6 Verify: `pytest tests/test_tm.py -q` passes
- [x] 1.7 Add new tests: `test_tm_context_manager_closes_connection`, `test_tm_close_is_idempotent`, `test_tm_thread_safe_under_concurrent_writes` (spawn 2 threads, each inserts 50 rows; assert no `sqlite3.ProgrammingError` and all 100 rows present)

## 2. RunLogger context manager + non-fatal logging

- [x] 2.1 In `run_logging.py:RunLogger`, add `close()` that flushes and closes `self._fh` idempotently (guard with `if self._fh is not None`)
- [x] 2.2 Add `__enter__`/`__exit__`
- [x] 2.3 In `log_node`, wrap `self._fh.write(line + "\n"); self._fh.flush()` in `try/except OSError`; on failure, `logging.getLogger(__name__).warning("RunLogger disabled: %s", e)` and set `self._disabled = True`
- [x] 2.4 At the top of `log_node`, `if self._disabled: return`
- [x] 2.5 Add `import logging` and a module-level `logger = logging.getLogger(__name__)`
- [x] 2.6 Verify: `pytest tests/test_run_logging.py -q` passes
- [x] 2.7 Add new tests: `test_run_logger_context_manager_closes_file`, `test_run_logger_non_fatal_on_disk_full` (mock `self._fh.write` to raise `OSError`; assert `log_node` does not propagate and subsequent calls are no-ops)

## 3. Embedder + OllamaEngineAdapter context managers

- [x] 3.1 In `embeddings.py:Embedder`, add `close()` that calls `self._client.close()` if `hasattr(self._client, "close")` else no-op
- [x] 3.2 Add `__enter__`/`__exit__` to `Embedder`
- [x] 3.3 Remove `_default_embedder` global and `_get_default_embedder` from `embeddings.py`; update `embed_batch`/`embed_text` to require an `embedder` argument (or remove them if no caller uses them)
- [x] 3.4 Grep for callers of `embed_batch(` and `embed_text(` without an `embedder` arg; update each
- [x] 3.5 In `llm.py:OllamaEngineAdapter`, add `close()` that calls `self._client.close()` if `hasattr(self._client, "close")` else no-op
- [x] 3.6 Add `__enter__`/`__exit__` to `OllamaEngineAdapter`
- [x] 3.7 Verify: `pytest tests/test_embeddings.py tests/test_llm.py -q` passes
- [x] 3.8 Add new tests: `test_embedder_context_manager_closes_client`, `test_llm_adapter_context_manager_closes_client`

## 4. ChromaStore context manager + exception-safe cleanup

- [x] 4.1 In `retrieval.py:ChromaStore`, add `__enter__` returning `self` and `__exit__` calling `_close_handles()`
- [x] 4.2 Wrap `_write_collection` body in `try/finally` where `finally` calls `_close_handles()` only on exception (on success, leave the collection open for `add_chunks` callers that re-use the store)
- [x] 4.3 In `_close_handles`, remove the second `gc.collect()` call (keep one)
- [x] 4.4 Verify: `pytest tests/test_retrieval.py -q` passes
- [x] 4.5 Add new tests: `test_chroma_store_context_manager_closes_handles`, `test_chroma_store_closes_handles_on_exception` (mock `add_chunks` to raise; assert `_close_handles` was called)

## 5. ingestion.py inline file open

- [x] 5.1 In `ingestion.py:iter_articles`, replace `handle = open(path, ...)` followed later by `with handle:` with `with open(path, ...) as handle:` directly
- [x] 5.2 Verify: `pytest tests/test_ingestion.py -q` passes

## 6. CLI + UI callers updated to use context managers

- [x] 6.1 In `cli.py:translate`, wrap `RunLogger` construction in `with ... as run_logger:`
- [x] 6.2 In `cli.py:batch`, wrap `RunLogger` and `TranslationMemory` in `with`
- [x] 6.3 In `cli.py:excel`, wrap `RunLogger` and `TranslationMemory` in `with`
- [x] 6.4 In `cli.py:tm_build` and `tm_build_parallel`, wrap `TranslationMemory` in `with`
- [x] 6.5 In `web_ui.py:launch_ui`, register an `on_closing` (or `Api.__del__`) that calls `close()` on `adapters.llm`, `adapters.embedder`, `adapters.tm`
- [x] 6.6 Verify: `pytest tests/test_cli.py tests/test_web_ui_excel.py -q` passes

## 7. Documentation + final verification

- [x] 7.1 Update `AGENTS.md` §11 (Resource Management) to document the context-manager protocol as the standard for all resource-owning classes
- [x] 7.2 Run `ruff check src/ tests/` — must be clean
- [x] 7.3 Run `mypy src/` — must not introduce new errors
- [x] 7.4 Run `pytest --tb=short -q` — full suite green (excluding `slow`)
- [x] 7.5 Run `openspec validate fix-resource-lifetimes` — must pass
- [x] 7.6 Run `openspec validate --all` — must pass
