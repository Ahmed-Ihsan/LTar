## 1. Config foundation

- [x] 1.1 Add `ExcelConfig` Pydantic model to `src/config/models.py` (`translate_comments`, `translate_headers_footers`, `translate_chart_titles`, `max_segment_chars` with defaults)
- [x] 1.2 Wire `excel: ExcelConfig` into `AppConfig` in `src/config/config.py` with `default_factory=ExcelConfig`
- [x] 1.3 Add `excel:` section to `config.yaml` with documented defaults
- [x] 1.4 Verify: `python -c "from src.config import AppConfig, ExcelConfig; ..."` defaults apply when section absent

## 2. Pure XML helpers (no pipeline dependency)

- [x] 2.1 Create `src/components/interfaces/excel.py` with namespace registration + `StringSegment` dataclass
- [x] 2.2 Implement `protect_non_translatable` / `restore_protected` (URLs, emails, numbers, article IDs, `{...}`/`<...>`/`%...%` placeholders)
- [x] 2.3 Implement `extract_translatable_strings` (sharedStrings, inline strings, comments, headers/footers, chart titles; dedupe by text; skip empty + oversized)
- [x] 2.4 Implement `patch_strings` (copy zip part-by-part; re-serialize allowlisted parts with translated `<t>`/`<a:t>`; leave everything else byte-for-byte)
- [x] 2.5 Verify: unit tests for protect/restore, extraction, and patching round-trip (no pipeline)

## 3. Orchestration

- [x] 3.1 Add `ExcelTranslationReport` frozen dataclass to `src/components/interfaces/models.py`
- [x] 3.2 Implement `translate_excel(...)` in `excel.py` (DI keyword-only args; per-unique-string `run_translation`; progress callback; cancel_event; per-segment error handling; protect/restore around each call)
- [x] 3.3 Verify: integration test with `mock_llm`/`mock_embedder` over a programmatically-built `.xlsx`

## 4. CLI

- [x] 4.1 Add `excel` subcommand to `src/components/interfaces/cli.py` (mirror `batch` error mapping; print `ExcelTranslationReport`)
- [x] 4.2 Add `src/components/interfaces/excel.py` per-file-ignore to `pyproject.toml` (`PLR0913`)
- [x] 4.3 Verify: `python -m src.app excel --help` exits 0; CliRunner test for missing input file

## 5. Tests

- [x] 5.1 `tests/test_excel.py` — unit tests for protect/restore (placeholders, URLs, numbers, article IDs)
- [x] 5.2 `tests/test_excel.py` — unit tests for extract/patch (shared strings, inline strings, comments, headers/footers, chart titles; formulas/merged/conditional-formatting preserved byte-for-byte)
- [x] 5.3 `tests/test_excel.py` — integration test for `translate_excel` with mock adapters (deduplication, progress, cancel, per-segment failure)
- [x] 5.4 `tests/test_excel.py` — e2e round-trip fixture (programmatically-built `.xlsx` with formatting/formulas/merged cells/comments/chart) asserting non-text artifacts identical

## 6. Final verification

- [x] 6.1 `pytest --tb=short -q` — 421 passed, 4 failed (pre-existing Ollama env-dependent), 3 deselected
- [x] 6.2 `ruff check src/ tests/` — All checks passed
- [x] 6.3 `mypy src/` — Success: no issues found in 49 source files
- [x] 6.4 `openspec validate --all` — 9 passed, 0 failed
- [x] 6.5 Archive: `openspec archive add-excel-translation`
