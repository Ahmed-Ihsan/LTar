# Prompt: Integrate Excel Translation Feature into pywebview GUI

## Role
You are a senior full-stack Python engineer working on the **Iraqi Legal Translation Agent** — a local, offline-first Agentic RAG system for translating Iraqi legal texts (Arabic ⇄ English). Your task is to extend the existing **pywebview desktop UI** (`src/components/interfaces/web_ui.py`) so the newly implemented Excel (.xlsx) translation feature is fully accessible from the GUI, alongside the existing single-sentence translation flow.

## Project Context (read these files before writing any code)

- `AGENTS.md` — authoritative development guide (architecture, conventions, hard constraints).
- `openspec/specs/interfaces/spec.md` — the interfaces spec; the `pywebview desktop UI` requirement documents the current `Api` contract (`get_models`, `get_default_model`, `get_examples`, `get_store_counts`, `get_history`, `translate`, `submit_review`, `approve_review`) and the `_UiHumanReviewer` thread-safety requirement.
- `openspec/specs/interfaces/spec.md` — the **Excel translation** requirements (search for `Requirement: Excel translation command`, `Requirement: Excel translation orchestration`, `Requirement: ExcelTranslationReport model`, `Requirement: ExcelConfig`, `Requirement: Excel XML extraction and patching`, `Requirement: Non-translatable token protection`).
- `src/components/interfaces/web_ui.py` — the current pywebview UI (HTML/CSS/JS embedded asset + `Api` class + `_UiHumanReviewer` + `launch_ui`). This is the file you will modify.
- `src/components/interfaces/web_frontend.py` — embedded HTML/CSS/JS asset (if split); mirror any changes there too.
- `src/components/interfaces/excel.py` — the Excel feature you are exposing. Public API:
  - `translate_excel(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> ExcelTranslationReport`
  - `ProgressCallback` protocol: `(completed: int, total: int, current: str) -> None`
  - `StringSegment`, `extract_translatable_strings`, `patch_strings`, `protect_non_translatable`, `restore_protected`.
- `src/components/interfaces/models.py` — `ExcelTranslationReport` (frozen dataclass: `total_segments`, `translated`, `skipped`, `failed`, `cancelled`, `warnings`), `Adapters`, `UiTranslationResult`.
- `src/components/interfaces/cli.py` — the `excel` CLI command; mirror its error→exit-code mapping as error→UI-message mapping.
- `src/config/config.py` / `src/config/models.py` — `AppConfig.excel: ExcelConfig` (`translate_comments`, `translate_headers_footers`, `translate_chart_titles`, `max_segment_chars`).
- `src/components/translation_pipeline/exceptions.py` — `OllamaConnectionError`, `EmbeddingConnectionError`, `RAMGuardError`, `LLMRuntimeError`, `LegalTranslationError`.

## Goal

Make the Excel translation feature fully usable from the pywebview desktop UI, with progress reporting, cancellation, per-segment failure visibility, and Excel-config toggles — without breaking any existing UI behavior (single-sentence Translate tab, Audit Trace tab, HITL review).

## Requirements (all MUST be met)

### 1. New "Excel" tab
Add a third tab alongside the existing "Translate" and "Audit Trace" tabs. The Excel tab contains:

- **Input file picker**: a button that opens a native file dialog (`.xlsx` filter). Show the selected path.
- **Output file picker**: a button that opens a native save dialog (`.xlsx` filter, default name = input name with `_translated` suffix). Show the selected path.
- **Direction dropdown**: `ar-en` / `en-ar` (reuse the existing direction selector styling).
- **Excel options** (bound to `cfg.excel`, editable per-run; persist back to `cfg` in-memory only — do NOT write `config.yaml`):
  - checkboxes for `translate_comments`, `translate_headers_footers`, `translate_chart_titles`;
  - a number field for `max_segment_chars` (min 16).
- **Translate Excel button**: starts the run. Disabled while running.
- **Cancel button**: visible only while a run is in progress; sets the `cancel_event`.
- **Progress bar + live counter**: `translated / total` and a progress bar `0–100%`. Updated via the `progress` callback. Also show the current segment's source text (truncated to 80 chars) while translating.
- **Report panel**: after the run, render the `ExcelTranslationReport` — `total_segments`, `translated`, `skipped`, `failed`, `cancelled`, and a scrollable warnings list.
- **Open output button**: after a successful run, a button that opens the output folder in the OS file explorer (Windows: `explorer /select,"<path>"`).

### 2. Thread safety
The Excel run MUST execute in a **background thread** (it is long-running and calls the local LLM). The `Api` methods exposed to JS must be thread-safe — reuse the same locking/queue pattern already used by `_UiHumanReviewer` and the existing translate flow. The pywebview JS bridge calls must never block the UI thread. Progress updates must be pushed to the JS frontend via `window.pywebview.api...` callbacks or a polling endpoint — match whatever pattern the existing UI already uses for async results.

### 3. Cancellation
Wire a `threading.Event` to the `cancel_event` parameter of `translate_excel`. The Cancel button sets it. After cancellation, the UI shows the partial `ExcelTranslationReport` (with `cancelled=True`) and the output file (with already-translated segments patched, remaining segments keeping original text) is still written — communicate this to the user.

### 4. Error handling
Map domain exceptions to user-friendly messages (mirror the CLI's mapping):
- `OllamaConnectionError` / `EmbeddingConnectionError` → "Cannot reach the Ollama daemon. Is `ollama serve` running?"
- `RAMGuardError` → "RAM guard aborted the run. Free up memory and retry."
- `LegalTranslationError` (other) → show the message.
- Per-segment failures are already captured in `ExcelTranslationReport.warnings` — render them in the warnings list, not as modal errors.
- Invalid input (missing file, wrong extension) → inline error message, no run started.

### 5. Api surface (new JS-callable methods on `Api`)
Add these methods to the `Api` class (keep existing methods intact):
- `pick_excel_input() -> str | None` — opens a native open-file dialog, returns the path or `None`.
- `pick_excel_output(default_name: str) -> str | None` — opens a native save-file dialog.
- `translate_excel(input_path: str, output_path: str, direction: str, options: dict) -> dict` — starts the run in a background thread; returns immediately with a job id (do NOT block). The result is delivered via a separate `get_excel_status(job_id) -> dict` polling method or a JS callback — match the existing UI's async pattern.
- `get_excel_status(job_id) -> dict` — returns `{state: "running"|"done"|"cancelled"|"error", completed, total, current, report}` where `report` is the `ExcelTranslationReport` as a dict (or `None` while running).
- `cancel_excel(job_id) -> None` — sets the cancel event for that job.
- `open_in_explorer(path: str) -> None` — opens the OS file explorer at the output file.
- `get_excel_options() -> dict` — returns the current `cfg.excel` values so the UI can render the toggles in their saved state.

`options` passed to `translate_excel` is a dict with keys `translate_comments`, `translate_headers_footers`, `translate_chart_titles`, `max_segment_chars`; apply them to a **copy** of `cfg` (use `cfg.model_copy(deep=True)` then `cfg.excel = cfg.excel.model_copy(update=...)`) so the run uses the UI-selected values without mutating the global config.

### 6. Single-user, single-session constraint
Only **one** Excel job may run at a time (the project enforces concurrency = 1). If a job is already running, `translate_excel` returns an error state immediately ("An Excel run is already in progress"). The single-sentence Translate tab should also be disabled while an Excel run is in progress (and vice versa) — they share the same LLM daemon.

### 7. Hard constraints (do NOT violate)
- No cloud calls, no telemetry, no third-party network calls.
- 8 GB RAM ceiling; no new model loaded.
- No new runtime dependencies — use only what `web_ui.py` already imports plus stdlib (`threading`, `pathlib`, `subprocess` for the explorer call).
- Reuse the existing `Adapters` bundle constructed at launch (`launch_ui(cfg, adapters)`) — do NOT construct new adapters in the UI; pass `adapters.llm`, `adapters.embedder`, `adapters.glossary_index`, `adapters.persist_dir`, `adapters.tm` into `translate_excel`.
- Reuse `RunLogger` if the existing UI uses one; otherwise pass `None`.

### 8. Code standards (from AGENTS.md — follow strictly)
- SOLID / DRY / KISS / YAGNI / DIP.
- DI via keyword-only args for any new helper functions.
- `ruff` line-length 100; `mypy strict` clean.
- Do NOT reformat the existing versioned prompt constants or the embedded HTML/CSS/JS asset's existing lines (the file has an `E501` per-file-ignore for a reason — long inline SVG/CSS lines are intentional).
- Docstrings on public `Api` methods; comments only where logic is non-obvious.
- Conventional commits if you commit: `feat: add Excel translation tab to pywebview UI`.

### 9. Frontend (HTML/CSS/JS)
- Match the existing UI's visual style (colors, fonts, button styles, tab styling). Do not introduce a new CSS framework.
- The Excel tab's layout: two-column form on top (pickers + options), action row (Translate / Cancel), progress section, report section.
- All text labels in English; the UI is for legal translators who handle Arabic ⇄ English.
- Disable the Translate Excel button until both input and output paths are set and a direction is chosen.
- Show a confirmation dialog before overwriting an existing output file.

### 10. Tests
Add `tests/test_web_ui_excel.py` (or extend the existing web UI test file if one exists) covering:
- `Api.translate_excel` starts a job and `get_excel_status` reports progress then a final report (use the deterministic `mock_llm` / `mock_embedder` / in-memory `GlossaryIndex` / temp ChromaDB from `tests/conftest.py`, and a programmatically-built `.xlsx` fixture — reuse the builder pattern from `tests/test_excel.py`).
- Cancellation: `cancel_excel` stops the run and the final report has `cancelled=True`.
- Concurrent-job guard: a second `translate_excel` call while one is running returns an error state.
- Invalid input (missing file) returns an error state without starting a job.
- Options override: passing `translate_comments=False` is respected (the report's segment count differs from the default run).
- Thread safety: the JS-bridge methods do not block the UI thread (assert the background thread is used).
- Use the `integration` pytest marker; never hit the real Ollama daemon.

### 11. Verification (run before claiming done — show actual output)
- `pytest tests/test_web_ui_excel.py -q --tb=short` — all green.
- `pytest --tb=short -q` — no regressions (the 4 pre-existing Ollama env-dependent failures in `test_graph.py` are acceptable).
- `ruff check src/ tests/` — clean.
- `mypy src/` — clean (strict).
- `openspec validate --all` — 0 failures.
- If behavior changed (new Api methods, new tab), create an OpenSpec change proposal `add-excel-ui` first (`openspec new change add-excel-ui --goal "Expose the Excel translation feature in the pywebview desktop UI"`), write the delta spec for `interfaces`, validate, implement, then archive. Follow `openspec/config.yaml` per-artifact rules (Given/When/Then scenarios, bilingual where applicable).

### 12. Rollback
The change is isolated to `web_ui.py` (and `web_frontend.py` if split), `tests/test_web_ui_excel.py`, and the OpenSpec change. Revert the commit to roll back. No data files or `db/` artifacts are touched.

## Deliverables
1. OpenSpec change proposal `add-excel-ui` (proposal + delta spec + design + tasks), validated.
2. Modified `src/components/interfaces/web_ui.py` (and `web_frontend.py` if split) with the new Excel tab, `Api` methods, background-thread execution, progress, cancellation, error mapping, and Excel-options overrides.
3. `tests/test_web_ui_excel.py` with the tests listed in §10.
4. Verification summary with actual command output for: pytest, ruff, mypy, openspec validate --all.
5. Archive the OpenSpec change after verification passes.

## Out of scope
- Do NOT modify `excel.py`, the CLI, the LangGraph pipeline, nodes, prompts, glossary, TM, or config models.
- Do NOT add the Excel tab to the Tkinter UI (`tk_ui.py`) — that is a separate task.
- Do NOT add new runtime dependencies.
- Do NOT change the single-sentence Translate tab or the Audit Trace tab behavior.
