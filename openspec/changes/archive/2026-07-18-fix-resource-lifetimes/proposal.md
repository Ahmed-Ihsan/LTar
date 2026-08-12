## Why

A production-grade audit (2026-07-18) found that the project's resource
lifetimes are not enforced. SQLite connections in `tm.py` and
`RunLogger` are opened in `__init__` and stored as instance attributes
with no `close()` method and no context-manager protocol; the
`ollama.Client` HTTP clients in `Embedder` and `OllamaEngineAdapter` have
the same problem; `ChromaStore` holds a ChromaDB client and collection
that are only cleaned up via an explicit `_close_handles()` call that is
not guaranteed to run on exceptions. On an 8 GB RAM target, every leaked
handle is both a file-descriptor and a memory cost.

Worse, `tm.py:152` uses `sqlite3.connect(db_path, check_same_thread=False)`
with no threading story. The pywebview `Api.translate` spawns a worker
thread, and `tm_lookup_node` runs in the LangGraph thread. SQLite's
default thread check exists for a reason — disabling it without a
serialization layer is a latent data-corruption bug.

These are not theoretical: a long-running desktop UI session that
translates many sentences will accumulate TM connections, RunLogger
file handles, and ChromaDB clients until the process exhausts file
descriptors or OOMs.

## What Changes

1. **`TranslationMemory` (`tm.py`):**
   - Add `__enter__`/`__exit__` returning `self` and calling `close()`.
   - Add `close()` that closes `self._conn` idempotently.
   - Remove `check_same_thread=False`; instead guard every connection
     access with a `threading.RLock` so the TM is safe to call from the
     LangGraph thread and the UI thread serially (concurrency = 1 is
     already a project rule, so the lock is uncontended).
   - Add a `weakref.finalize(self, self._conn.close)` safety net so a
     forgotten `close()` still releases the connection on GC.

2. **`RunLogger` (`run_logging.py`):**
   - Add `__enter__`/`__exit__` and `close()`.
   - Make `close()` idempotent and flush + close `self._fh`.
   - Wrap `log_node`'s `self._fh.write`/`flush` in `try/except OSError`
     so a logging failure never crashes the pipeline; on failure, log to
     stderr via the standard `logging` module and disable further
     logging for this instance.

3. **`Embedder` (`embeddings.py`) and `OllamaEngineAdapter` (`llm.py`):**
   - Add `close()` that calls `self._client.close()` if the `ollama.Client`
     exposes a `close` (it does — `httpx.Client`-based), guarded by
     `hasattr` for safety.
   - Add `__enter__`/`__exit__`.
   - Remove the module-level `_default_embedder` global in
     `embeddings.py`; require callers to pass an `Embedder` instance
     (DIP). The CLI's `_construct_adapters` already does this; the
     module-level convenience functions `embed_batch`/`embed_text` are
     updated to require an explicit `embedder` arg.

4. **`ChromaStore` (`retrieval.py`):**
   - Add `__enter__`/`__exit__` that call `_close_handles()`.
   - Wrap `_write_collection` and `add_chunks` in `try/finally` that
     calls `_close_handles()` on exception, so a failed embedding run
     does not leak the ChromaDB client.
   - Remove one of the two `gc.collect()` calls in `_close_handles`
     (keep one as the existing RAM-pressure release for the 8 GB
     target; the second is redundant).

5. **`ingestion.py:iter_articles`:**
   - Open the file directly inside the `with` statement instead of
     `handle = open(...)` then later `with handle:`. Closes the
     leak window between `open` and `with`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `infrastructure`: `Embedder`, `OllamaEngineAdapter`, and `RunLogger`
  gain context-manager protocol, `close()`, and (for `RunLogger`)
  non-fatal logging on I/O failure.
- `knowledge_sources`: `TranslationMemory` gains context-manager
  protocol, `close()`, a `threading.RLock`, and removes
  `check_same_thread=False`. `ChromaStore` gains context-manager
  protocol and exception-safe handle cleanup. `ingestion.py:iter_articles`
  opens files inline.
- `interfaces`: callers of `TranslationMemory`, `RunLogger`, `Embedder`,
  and `ChromaStore` are updated to use `with` where the lifetime is
  bounded (CLI commands); long-lived adapters (UI session) call `close()`
  on shutdown.

## Impact

**Affected code:**
- `src/components/knowledge_sources/tm.py` (context manager, lock,
  remove `check_same_thread=False`, `weakref.finalize`)
- `src/components/knowledge_sources/retrieval.py` (`ChromaStore`
  context manager, `try/finally` in `_write_collection`/`add_chunks`,
  drop one `gc.collect()`)
- `src/components/knowledge_sources/ingestion.py` (`iter_articles`
  inline `with open`)
- `src/components/infrastructure/run_logging.py` (context manager,
  `close()`, non-fatal `log_node`)
- `src/components/infrastructure/embeddings.py` (context manager,
  `close()`, remove `_default_embedder` global)
- `src/components/infrastructure/llm.py` (context manager, `close()`)
- `src/components/interfaces/cli.py` (use `with` for `RunLogger` and
  `TranslationMemory` in `translate`/`batch`/`excel`/`tm-build`)
- `src/components/interfaces/web_ui.py` (call `close()` on adapters
  on window close)

**APIs:**
- `TranslationMemory`, `RunLogger`, `Embedder`, `OllamaEngineAdapter`,
  and `ChromaStore` gain `__enter__`/`__exit__`/`close()`. Existing
  constructors are unchanged.
- The module-level `embed_batch(texts, *, model, host, batch_size)` and
  `embed_text(text, *, model, host)` convenience functions in
  `embeddings.py` are **removed** (or, if backward compat is required,
  changed to require an `embedder` argument). The CLI already passes
  explicit embedders, so no caller breaks.
- `tm.py` no longer accepts `check_same_thread=False`; the constructor
  signature is unchanged.

**Specs:**
- `infrastructure/spec.md` MODIFIED requirements for the LLM adapter,
  embeddings adapter, and run logger (context-manager protocol).
- `knowledge_sources/spec.md` MODIFIED requirements for TM and
  retrieval (context-manager protocol, thread safety, no
  `check_same_thread=False`).

**Migration path:**
- All callers that already construct these objects and use them for the
  duration of a command are updated to `with` in the same change.
- The UI session's long-lived adapters gain a shutdown hook
  (`web_ui.py:Api.__del__` or an `on_close` pywebview callback) that
  calls `close()` on each adapter.
- No data migration; no DB schema changes.

**Rollback plan:**
- `git revert`. No persistent state is touched. Reverting re-introduces
  the leaks and `check_same_thread=False`, which is the current state.

**Security/performance impact:**
- Closes audit findings SEC-13 (Critical: `check_same_thread=False`),
  W2 (resource lifetimes), and the `RunLogger` file-handle leak
  (Finding 22, High). Removes one redundant `gc.collect()` (PERF-7).
