## 1. OpenSpec change proposal

- [x] 1.1 Create change `add-excel-ui` via `openspec new change`
- [x] 1.2 Write `proposal.md` (Why, What Changes, Capabilities, Impact, Scope, Migration path, Rollback plan, Affected files)
- [x] 1.3 Write delta spec `specs/interfaces/spec.md` (ADDED requirements with Given/When/Then scenarios)
- [x] 1.4 Write `design.md` (Context, Goals/Non-Goals, Decisions, Risks, Target tree, Dependency diagram, models, Migration strategy, pyproject changes)
- [x] 1.5 Write `tasks.md` (this file)
- [x] 1.6 `openspec validate add-excel-ui` — 0 failures

## 2. Backend — `Api` methods in `web_ui.py`

- [x] 2.1 Add `_ExcelJob` dataclass (job_id, state, completed, total, current, report, error, cancel_event) and Excel-job slot + helper accessors on `Api`, all under `_lock`.
- [x] 2.2 Add `pick_excel_input() -> str | None` and `pick_excel_output(default_name: str) -> str | None` using `webview` native file dialogs with a `.xlsx` filter.
- [x] 2.3 Add `get_excel_options() -> dict` returning the current `cfg.excel` values.
- [x] 2.4 Add `translate_excel(input_path, output_path, direction, options) -> dict`: validate input (exists + `.xlsx` extension), enforce single-job guard, deep-copy cfg with options override, start background worker, return job descriptor immediately.
- [x] 2.5 Implement the background worker: call `excel.translate_excel` with injected adapters, a progress closure that updates `_ExcelJob` under `_lock`, and the `cancel_event`; map domain exceptions to user messages; on completion set `state` + `report`; clear the job slot on exit.
- [x] 2.6 Add `get_excel_status(job_id) -> dict` returning `{state, completed, total, current, report}` under `_lock`.
- [x] 2.7 Add `cancel_excel(job_id) -> None` setting the job's `cancel_event` under `_lock`.
- [x] 2.8 Add `open_in_explorer(path: str) -> None` using `subprocess` on Windows / `os.startfile` fallback.
- [x] 2.9 Add a `is_busy()` helper (single-sentence or Excel run in progress) for cross-tab disablement; disable single-sentence `translate` start while an Excel job is running (server-side reject).

## 3. Frontend — Excel tab in `web_frontend.py`

- [x] 3.1 Add the "Excel" tab button to the `.tabs` row.
- [x] 3.2 Add the `#tab-excel` content: input/output picker buttons + path displays, direction dropdown, Excel-option checkboxes + `max_segment_chars` number field, Translate Excel + Cancel buttons, progress bar + counter + current-segment preview, report panel, Open output button.
- [x] 3.3 Add CSS for the Excel tab (reuse existing tokens; file-picker rows, progress bar, report grid, warnings scroll list).
- [x] 3.4 Add JS: `initExcel()` to load `get_excel_options` into the toggles; `pickExcelInput` / `pickExcelOutput` calling the `Api` pickers; `updateExcelButtonState` to enable/disable Translate Excel based on inputs + busy state; `doTranslateExcel` (overwrite confirmation → call `translate_excel` → start polling); `pollExcelStatus` (update progress + report + open-output button); `cancelExcel`; `openOutput`; cross-tab disablement of the single-sentence Translate button while an Excel run is in progress.
- [x] 3.5 Wire `initExcel()` into the existing `init()` and `switchTab` handlers.

## 4. Tests — `tests/test_web_ui_excel.py`

- [x] 4.1 Build an `Api` with `mock_llm` / `mock_embedder` / in-memory `GlossaryIndex` / temp ChromaDB / a programmatically-built `.xlsx` fixture (reuse `test_excel.py`'s `_build_workbook` pattern).
- [x] 4.2 Test: `translate_excel` starts a job and `get_excel_status` reports progress then a final report (state `done`, `report.translated == report.total_segments`).
- [x] 4.3 Test: `cancel_excel` stops the run and the final report has `cancelled=True`.
- [x] 4.4 Test: a second `translate_excel` call while one is running returns an error state without starting a second thread.
- [x] 4.5 Test: invalid input (missing file) returns an error state without starting a job.
- [x] 4.6 Test: options override — `translate_comments=False` is respected (segment count differs from the default run).
- [x] 4.7 Test: thread safety — the JS-bridge methods do not block the UI thread (assert the background thread is used; `translate_excel` returns before the run completes).
- [x] 4.8 Marker: `pytestmark = pytest.mark.integration`; never hit the real Ollama daemon.

## 5. Config — `pyproject.toml`

- [x] 5.1 Add `"tests/test_web_ui_excel.py" = ["E501"]` to `[tool.ruff.lint.per-file-ignores]`.

## 6. Verification

- [x] 6.1 `pytest tests/test_web_ui_excel.py -q --tb=short` — all green.
- [x] 6.2 `pytest --tb=short -q` — no regressions (the 4 pre-existing Ollama env-dependent failures in `test_graph.py` are acceptable).
- [x] 6.3 `ruff check src/ tests/` — clean.
- [x] 6.4 `mypy src/` — clean (strict).
- [x] 6.5 `openspec validate --all` — 0 failures.
- [x] 6.6 `openspec archive add-excel-ui` — change archived into source-of-truth specs.
