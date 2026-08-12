## Why

A production-grade audit (2026-07-18) found two systemic problems in the
project's error handling:

1. **Bare `except Exception` blocks** swallow all errors — including
   `KeyboardInterrupt`, `SystemExit`, and `MemoryError` — and several do
   so silently with no log line. The audit identified six High-severity
   sites:
   - `nodes.py:428-432` — `try: results = searcher.search(query) except
     Exception: results = []` (silently drops web-search failures)
   - `legal_search.py:68-92` — `except Exception: return ""` (silently
     drops network/parse errors)
   - `web_ui.py:315, 476, 538` — `except Exception as e: # noqa: BLE001`
     in three `Api` methods
   - `tk_ui.py:135-136` — bare `except Exception` in worker thread
   - `retrieval.py:192-208` — `except Exception: pass` in `_close_handles`
   - `ingestion_runner.py:44-72, 75-116` — `except GlossaryConflictError`/
     `except (CorpusParseError, CorpusEncodingError):` swallow errors
     without logging which file failed

2. **No structured application-level logging.** The project has only
   `typer.secho` (user-facing CLI output) and `RunLogger` (per-node
   JSONL). There is no `logging.getLogger(__name__)` anywhere, so
   adapter errors, retries, swallowed exceptions, and HTTP failures are
   invisible to anyone debugging a failed run. The `RunLogger` records
   *what the graph did*, not *what the infrastructure did*.

These combine to make production incidents undebuggable: a swallowed
`OSError` in `_close_handles` or a silent web-search failure leaves no
trace anywhere.

## What Changes

1. **Replace every bare `except Exception`** with the narrowest
   practical exception type, and ensure each handler logs the exception
   via `logging.getLogger(__name__).exception(...)` (or `.warning(...)`
   for expected failures):

   - `nodes.py:428-432`: catch `(httpx.HTTPError, ValueError,
     LegalSearchError)` instead of `Exception`; log a warning and set
     `results = []`.
   - `legal_search.py:68-92`: catch `(httpx.HTTPError,
     defusedxml.DefusedXmlException, ValueError)`; log and return `""`.
   - `web_ui.py:315, 476, 538`: keep the broad catch (UI must not crash)
     but change `# noqa: BLE001` to `# noqa: BLE001  -- UI boundary:
     log + surface to user` and add
     `logger.exception("Api.<method> failed")` before returning the
     error to JS.
   - `tk_ui.py:135-136`: same pattern — log via `logger.exception` and
     put the error on the queue.
   - `retrieval.py:192-208`: catch `OSError` and `Exception` separately;
     log each via `logger.warning` (do not silently `pass`).
   - `ingestion_runner.py:44-72, 75-116`: log the file path and error
     for each swallowed `GlossaryConflictError`/`CorpusParseError`/
     `CorpusEncodingError` so the user knows which file failed.

2. **Add a structured `logging` setup**:
   - Create `src/utils/logging_setup.py` with
     `configure_logging(level: str = "INFO", log_dir: Path | None =
     None) -> None` that installs a `StreamHandler` (to stderr) and,
     if `log_dir` is provided, a `FileHandler` writing to
     `<log_dir>/app.log`. The format is
     `%(asctime)s %(levelname)s %(name)s %(message)s`.
   - Call `configure_logging` once at CLI entry (`cli.py:app.callback`)
     and once at UI entry (`web_ui.py:launch_ui`, `tk_ui.py:launch_ui`).
   - Add `logger = logging.getLogger(__name__)` at the top of every
     module that currently uses `print`/`typer.secho` for non-user-facing
     diagnostics. User-facing CLI output stays `typer.secho`; internal
     diagnostics move to `logger`.

3. **Replace string-matching timeout detection** with exception types:
   - `llm.py:157-167` and `ollama_errors.py:57-67`: replace
     `if "timeout" in str(err).lower()` with
     `isinstance(err, (httpx.TimeoutException, TimeoutError))`. Keep the
     string-match as a fallback only if the Ollama client wraps timeouts
     in a custom exception (verify by reading the ollama-py source).

4. **Consolidate duplicated `embeddings.py` exception handling**:
   - `embeddings.py:129-136`: the two `except` blocks (one specific, one
     bare `Exception`) both call `translate_engine_error(...)`; collapse
     into one block that catches `Exception` and delegates to
     `translate_engine_error`, which already maps specific types.

## Capabilities

### New Capabilities

- `application-logging`: A structured `logging` setup shared by all
  components. Lives in `src/utils/logging_setup.py` (same package as
  the `input-validation` capability from
  `harden-untrusted-input-surfaces`).

### Modified Capabilities

- `translation_pipeline`: `nodes.py` web-search error handling narrows
  from `Exception` to specific types + log.
- `knowledge_sources`: `legal_search.py` and `retrieval.py` error
  handling narrows + logs. `ingestion_runner.py` logs the failing file
  path.
- `infrastructure`: `llm.py` and `embeddings.py` timeout detection
  switches from string-matching to exception types; `embeddings.py`
  duplicate `except` blocks collapse.
- `interfaces`: `web_ui.py` and `tk_ui.py` UI-boundary catches log via
  `logger.exception` before surfacing the error. `cli.py` calls
  `configure_logging` at startup.

## Impact

**Affected code:**
- `src/components/translation_pipeline/nodes.py` (web-search catch)
- `src/components/knowledge_sources/legal_search.py` (HTTP/parse catch)
- `src/components/knowledge_sources/retrieval.py` (`_close_handles` catch)
- `src/components/knowledge_sources/ingestion_runner.py` (file-error
  logging)
- `src/components/infrastructure/llm.py` (timeout detection)
- `src/components/infrastructure/embeddings.py` (duplicate catch
  collapse)
- `src/components/infrastructure/ollama_errors.py` (timeout detection)
- `src/components/interfaces/cli.py` (`configure_logging` at startup)
- `src/components/interfaces/web_ui.py` (UI-boundary catch + log)
- `src/components/interfaces/tk_ui.py` (UI-boundary catch + log)
- New: `src/utils/logging_setup.py`

**APIs:**
- New public function `configure_logging(level, log_dir) -> None` in
  `src/utils/logging_setup.py`.
- No existing public API changes.

**Specs:**
- `translation_pipeline/spec.md` MODIFIED requirement for web-search
  node error handling.
- `knowledge_sources/spec.md` MODIFIED requirement for legal-search and
  ingestion error handling.
- `infrastructure/spec.md` MODIFIED requirement for LLM/embeddings
  timeout detection.
- `interfaces/spec.md` MODIFIED requirement for UI error boundaries.
- New `application-logging/spec.md` describes `configure_logging`.

**Migration path:**
- No data migration. No config changes (logging level defaults to
  INFO; a `logging.level` config key may be added later).
- Users will start seeing `app.log` files in `logs/` — document in
  README §5.7.

**Rollback plan:**
- `git revert`. Reverting re-introduces the silent swallows and removes
  `app.log`; no persistent state is touched.

**Debuggability impact:**
- Closes audit findings CS-1 through CS-6 (High), CS-7/CS-8 (Medium:
  string-matching timeouts), CS-9 (Medium: duplicate catch), and W6
  (no structured logging). This is the single highest-leverage change
  for production debuggability.
