## Context

The project's resource lifetimes are managed by GC and luck. SQLite
connections, HTTP clients, file handles, and ChromaDB clients are opened
in `__init__` and stored as instance attributes with no `close()` and no
context-manager protocol. On an 8 GB RAM target with a long-running
desktop UI, this leaks file descriptors and memory until the process
crashes. `tm.py` additionally disables SQLite's thread-safety check
without providing a serialization layer — a latent corruption bug now
that the UI spawns worker threads.

## Goals / Non-Goals

**Goals:**
- Make every resource-owning class a context manager with an idempotent
  `close()`.
- Remove `check_same_thread=False` from `tm.py` and replace it with a
  `threading.RLock` that serializes access (concurrency = 1 is already
  a project rule, so the lock is uncontended in practice).
- Guarantee cleanup on exceptions via `try/finally` in the ChromaStore
  write paths.
- Make `RunLogger` non-fatal: a logging I/O failure must never crash
  the pipeline.

**Non-Goals:**
- Connection pooling — the project is single-user, single-session;
  pooling adds complexity for no gain.
- Async I/O — out of scope; LangGraph is synchronous.
- Removing the module-level `_default_embedder` is in scope, but
  introducing a full DI container is not (the CLI's
  `_construct_adapters` is sufficient).

## Decisions

### D1: `threading.RLock` over `check_same_thread=False`

**Decision:** Replace `check_same_thread=False` with a `threading.RLock`
guarding every `self._conn.execute(...)` call in `TranslationMemory`.

**Rationale:** `check_same_thread=False` silently disables SQLite's
thread-safety check. The pywebview `Api.translate` spawns a worker
thread; `tm_lookup_node` runs in the LangGraph thread. Without
serialization, concurrent writes corrupt the database. `RLock` allows
re-entrant access from the same thread (some TM methods call other TM
methods) while serializing cross-thread access. Concurrency = 1 is a
project rule, so the lock is uncontended in practice — the cost is zero
on the happy path.

**Alternatives considered:**
- Keep `check_same_thread=False` and document "single-thread only" —
  rejected; the UI already violates this.
- Use a `threading.Lock` (non-reentrant) — rejected; TM methods call
  each other (e.g., `add_parallel` calls `_build_trigram_index`).

### D2: `weakref.finalize` as a safety net, not a primary cleanup

**Decision:** Add `weakref.finalize(self, self._conn.close)` in
`TranslationMemory.__init__` so a forgotten `close()` still releases
the connection on GC.

**Rationale:** Context managers are the primary cleanup mechanism, but
the UI session's long-lived TM may outlive any single `with` block. The
finalizer is a safety net, not a replacement for explicit `close()`.

**Trade-off:** Finalizers run at GC time, which is non-deterministic.
Accepted: the alternative (leak forever) is worse.

### D3: Remove the `_default_embedder` module-level global

**Decision:** Remove `_default_embedder` and `_get_default_embedder`
from `embeddings.py`. The module-level `embed_batch`/`embed_text`
convenience functions either are removed or require an explicit
`embedder` argument.

**Rationale:** The global is a testability hazard (state shared across
tests) and a DIP violation (the module depends on a concrete embedder
constructed from `load_config()`). The CLI already passes explicit
embedders; no caller breaks.

### D4: `RunLogger` non-fatal logging

**Decision:** Wrap `self._fh.write`/`flush` in `try/except OSError`. On
failure, emit a `logging.getLogger(__name__).warning(...)` and set
`self._disabled = True` so further `log_node` calls are no-ops.

**Rationale:** Logging is observability, not correctness. A full disk
must not crash a translation run.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| `RLock` adds overhead | Uncontended `RLock` is ~50ns; negligible vs. SQLite I/O. |
| `weakref.finalize` runs at unpredictable times | Documented as a safety net; explicit `close()` is the primary path. |
| Removing `_default_embedder` breaks an undiscovered caller | Grep for `embed_batch(` / `embed_text(` calls without an `embedder` arg; update them. |
| `RunLogger` non-fatal mode hides disk-full conditions | The `logging.warning` surfaces it; the `doctor` command checks disk headroom separately. |

## Target directory tree (modified files only)

```
src/components/
  knowledge_sources/
    tm.py            # MODIFIED: __enter__/__exit__, close(), RLock, weakref.finalize, remove check_same_thread=False
    retrieval.py     # MODIFIED: ChromaStore __enter__/__exit__, try/finally in _write_collection/add_chunks, drop one gc.collect()
    ingestion.py     # MODIFIED: iter_articles opens inline with open(...) as handle:
  infrastructure/
    run_logging.py   # MODIFIED: __enter__/__exit__, close(), non-fatal log_node
    embeddings.py    # MODIFIED: __enter__/__exit__, close(), remove _default_embedder global
    llm.py           # MODIFIED: __enter__/__exit__, close()
  interfaces/
    cli.py           # MODIFIED: use `with` for RunLogger and TranslationMemory in translate/batch/excel/tm-build
    web_ui.py        # MODIFIED: close() adapters on window close
```
