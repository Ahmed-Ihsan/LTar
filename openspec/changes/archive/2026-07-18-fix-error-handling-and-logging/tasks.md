## 1. Structured logging setup

- [x] 1.1 Create `src/utils/logging_setup.py` with `configure_logging(level: str = "INFO", log_dir: Path | None = None) -> None` that installs a `StreamHandler` (stderr) with format `%(asctime)s %(levelname)s %(name)s %(message)s` and, if `log_dir` is provided, a `FileHandler` to `<log_dir>/app.log`
- [x] 1.2 Make `configure_logging` idempotent (guard against duplicate handlers on repeated calls)
- [x] 1.3 Verify: `python -c "from src.utils.logging_setup import configure_logging; configure_logging(); import logging; logging.getLogger('test').info('ok')"` prints a formatted line to stderr
- [x] 1.4 Add `src.utils.logging_setup` to `pyproject.toml` packages if needed (already covered by `harden-untrusted-input-surfaces` task 1.8)

## 2. CLI + UI entry points call configure_logging

- [x] 2.1 In `cli.py:app.callback`, call `configure_logging(level=cfg.logging.level if hasattr(cfg, 'logging') else "INFO", log_dir=cfg.paths.log_dir)` (guard for missing `cfg`)
- [x] 2.2 In `web_ui.py:launch_ui`, call `configure_logging(log_dir=cfg.paths.log_dir)` before building the window
- [x] 2.3 In `tk_ui.py:launch_ui`, call `configure_logging(log_dir=cfg.paths.log_dir)` before building the window
- [x] 2.4 Verify: `pytest tests/test_cli.py -q` passes; running `iraqi-translate doctor` produces an `app.log` line

## 3. Add per-module loggers

- [x] 3.1 Add `import logging; logger = logging.getLogger(__name__)` to: `nodes.py`, `legal_search.py`, `retrieval.py`, `ingestion_runner.py`, `llm.py`, `embeddings.py`, `ollama_errors.py`, `web_ui.py`, `tk_ui.py`, `excel.py`, `orchestration.py`, `tm.py`, `glossary.py`, `run_logging.py`
- [x] 3.2 Verify: `ruff check src/` is clean (no unused imports)

## 4. Narrow bare `except Exception` blocks

- [x] 4.1 In `nodes.py:428-432`, replace `except Exception:` with `except (httpx.HTTPError, ValueError, LegalSearchError) as e:` and add `logger.warning("web_search failed for query=%r: %s", query, e)` before `results = []`
- [x] 4.2 In `legal_search.py:68-92`, replace `except Exception: return ""` with `except (httpx.HTTPError, ValueError) as e: logger.warning("legal_search fetch failed: %s", e); return ""`
- [x] 4.3 In `retrieval.py:192-208`, replace `except Exception: pass` with two blocks: `except OSError as e: logger.warning("ChromaStore close OSError: %s", e)` and `except Exception as e: logger.warning("ChromaStore close unexpected: %s", e)` (no silent pass)
- [x] 4.4 In `ingestion_runner.py:44-72`, add `logger.warning("Glossary conflict in %s: %s", file_path, e)` inside the `except GlossaryConflictError` block (capture the file path)
- [x] 4.5 In `ingestion_runner.py:75-116`, add `logger.warning("Corpus parse/encoding error in %s: %s", file_path, e)` inside the `except (CorpusParseError, CorpusEncodingError)` block
- [x] 4.6 Verify: `pytest tests/test_nodes.py tests/test_legal_search.py tests/test_retrieval.py tests/test_ingestion_runner.py -q` passes
- [x] 4.7 Add new tests: `test_web_search_failure_logs_warning` (mock searcher to raise `httpx.HTTPError`; assert logger.warning called and `results == []`), `test_legal_search_failure_logs_and_returns_empty`, `test_close_handles_logs_on_oserror`

## 5. UI-boundary catches log before surfacing

- [x] 5.1 In `web_ui.py:315, 476, 538`, inside each `except Exception as e:` block, add `logger.exception("Api.<method_name> failed")` before the existing error-handling code; update the `# noqa: BLE001` comment to `# noqa: BLE001 -- UI boundary: log + surface to user`
- [x] 5.2 In `tk_ui.py:135-136`, inside the `except Exception as e:` block, add `logger.exception("Tk translation worker failed")` before `result_queue.put(("error", str(e)))`
- [x] 5.3 Verify: `pytest tests/test_web_ui_excel.py tests/test_tk_ui.py -q` passes
- [x] 5.4 Add new tests: `test_api_translate_logs_exception_on_failure` (mock pipeline to raise; assert `logger.exception` called), `test_tk_worker_logs_exception_on_failure`

## 6. Timeout detection via isinstance

- [x] 6.1 In `llm.py:157-167`, replace `if "timeout" in str(err).lower() or "timed out" in str(err).lower():` with `if isinstance(err, (httpx.TimeoutException, TimeoutError)):`; keep the string-match as a fallback `or "timeout" in str(err).lower()` only if a code comment documents why (verify ollama-py's exception hierarchy first)
- [x] 6.2 In `ollama_errors.py:57-67`, apply the same isinstance-first pattern
- [x] 6.3 Verify: `pytest tests/test_llm.py tests/test_ollama_errors.py -q` passes
- [x] 6.4 Add new tests: `test_timeout_detected_via_isinstance` (raise `httpx.TimeoutException`; assert it maps to `LLMTimeoutError`), `test_timeout_detected_via_timeouterror_builtin`

## 7. Collapse duplicate embeddings.py except blocks

- [x] 7.1 In `embeddings.py:129-136`, collapse the two `except` blocks (one specific, one bare `Exception`) into a single `except Exception as e: raise translate_engine_error(e, kind="embedding") from e` block
- [x] 7.2 Verify: `pytest tests/test_embeddings.py -q` passes

## 8. Documentation + final verification

- [x] 8.1 Update `README.md` §5.7 to document `logs/app.log` and the logging level
- [x] 8.2 Update `AGENTS.md` §8 (Coding Standards) to mandate `logging.getLogger(__name__)` per module and forbid bare `except Exception` without a `logger.exception` call
- [x] 8.3 Run `ruff check src/ tests/` — must be clean
- [x] 8.4 Run `mypy src/` — must not introduce new errors
- [x] 8.5 Run `pytest --tb=short -q` — full suite green (excluding `slow`)
- [x] 8.6 Run `openspec validate fix-error-handling-and-logging` — must pass
- [x] 8.7 Run `openspec validate --all` — must pass
