## Context

The project has two error-handling pathologies: (1) bare `except Exception`
blocks that silently swallow errors (including `KeyboardInterrupt` and
`MemoryError`), and (2) no structured `logging` — only `typer.secho`
(user-facing) and `RunLogger` (per-node JSONL). The combination means a
swallowed `OSError` or a silent web-search failure leaves no trace
anywhere. The audit found six High-severity bare-catch sites and three
Medium-severity string-matching timeout detectors.

## Goals / Non-Goals

**Goals:**
- Replace every bare `except Exception` with the narrowest practical
  type, and log each swallowed exception via `logging`.
- Add a `configure_logging` setup function and call it once at every
  entry point (CLI, web UI, Tk UI).
- Switch timeout detection from string-matching to `httpx.TimeoutException`
  / `TimeoutError` isinstance checks.
- Collapse the duplicated `except` blocks in `embeddings.py`.

**Non-Goals:**
- Removing the broad UI-boundary catch in `web_ui.py`/`tk_ui.py` — the UI
  must not crash on unexpected errors. The fix is to *log* before
  surfacing, not to narrow the catch.
- Replacing `typer.secho` with `logging` for user-facing CLI output —
  `typer.secho` is correct for the user; `logging` is for the developer.
- Adding a `logging.level` config key — defaults to INFO; configurable
  later if needed.
- Structured (JSON) logging — plain text is sufficient for a
  single-user desktop app.

## Decisions

### D1: Narrowest practical catch + log, not "no broad catches"

**Decision:** For internal modules (`nodes.py`, `legal_search.py`,
`retrieval.py`, `ingestion_runner.py`), narrow the catch to the specific
exception types that can actually occur. For UI boundaries
(`web_ui.py`, `tk_ui.py`), keep `except Exception` but add
`logger.exception(...)` before surfacing the error to the user.

**Rationale:** Internal modules know what they call; narrowing catches
`KeyboardInterrupt`/`SystemExit`/`MemoryError` correctly. UI boundaries
genuinely cannot enumerate every failure mode (the UI calls the whole
pipeline), so a broad catch is correct — but it must log.

### D2: `logging.getLogger(__name__)` per module, not a global logger

**Decision:** Each module gets its own `logger =
logging.getLogger(__name__)`. `configure_logging` installs the root
handler once at startup.

**Rationale:** Per-module loggers give us the module name in every log
line for free, with no manual `logger = logging.getLogger("excel")`
boilerplate. This is the Python idiom.

### D3: `configure_logging` in `src/utils/`, not `src/config/`

**Decision:** `configure_logging` lives in `src/utils/logging_setup.py`.

**Rationale:** Same rationale as the `input-validation` capability in
`harden-untrusted-input-surfaces` — `utils` is a leaf in the dependency
graph and can be imported by every component without cycles.

### D4: Keep string-matching timeout detection as a fallback

**Decision:** Primary timeout detection is
`isinstance(err, (httpx.TimeoutException, TimeoutError))`. The existing
`if "timeout" in str(err).lower()` check is kept as a secondary fallback
*only if* the ollama-py client is known to wrap timeouts in a custom
exception that does not subclass `httpx.TimeoutException`.

**Rationale:** String-matching is fragile (locale, message changes), but
removing it entirely could regress timeout detection if ollama-py
changes its exception hierarchy. The isinstance check is primary; the
string-match is a documented fallback.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| Narrowing catches surfaces previously-hidden exceptions as crashes | This is the desired behavior — a hidden `MemoryError` should crash, not be swallowed. The new `logger.exception` lines make the previously-invisible failures visible. |
| `app.log` grows unbounded on a long UI session | Document rotation in a follow-up; for now, the file is per-session and the `doctor` command can warn on large logs. |
| String-matching fallback gives a false positive on a non-timeout error containing "timeout" | Accepted; the isinstance check is primary and the fallback only runs if the isinstance check fails. |

## Target directory tree

```
src/utils/
  logging_setup.py        # NEW: configure_logging(level, log_dir)
src/components/
  translation_pipeline/
    nodes.py              # MODIFIED: narrow web-search catch + log
  knowledge_sources/
    legal_search.py       # MODIFIED: narrow HTTP/parse catch + log
    retrieval.py          # MODIFIED: _close_handles logs instead of pass
    ingestion_runner.py   # MODIFIED: log file path on swallowed errors
  infrastructure/
    llm.py                # MODIFIED: isinstance timeout detection
    embeddings.py         # MODIFIED: collapse duplicate except blocks
    ollama_errors.py      # MODIFIED: isinstance timeout detection
  interfaces/
    cli.py                # MODIFIED: configure_logging at startup
    web_ui.py             # MODIFIED: logger.exception at UI boundary
    tk_ui.py              # MODIFIED: logger.exception at UI boundary
```
