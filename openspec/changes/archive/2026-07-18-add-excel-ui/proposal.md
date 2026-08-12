## Why

The Excel translation feature (`src/components/interfaces/excel.py`) is fully
implemented and exposed via the CLI `excel` subcommand, but it is **not
reachable from the pywebview desktop UI**. Users who prefer the GUI must drop
to the terminal to translate a workbook, which breaks the single-entry-point
UX the desktop UI is meant to provide. A workbook run is long-running
(seconds-to-minutes per segment), so it cannot reuse the single-sentence
`translate` flow — it needs its own background-thread execution, live
progress reporting, cancellation, per-segment failure visibility, and the
Excel-config toggles (`translate_comments`, `translate_headers_footers`,
`translate_chart_titles`, `max_segment_chars`). This change adds a dedicated
**Excel tab** to the pywebview UI so the feature is fully usable from the GUI
without breaking any existing UI behavior (Translate, Audit Trace, History,
HITL review).

## What Changes

- **ADDED:** A new **"Excel" tab** in the pywebview desktop UI
  (`src/components/interfaces/web_frontend.py` embedded HTML/CSS/JS) with:
  input/output file pickers, a direction dropdown, Excel-option toggles bound
  to `cfg.excel`, a Translate Excel button, a Cancel button (visible only
  while running), a progress bar + live counter + current-segment preview, a
  report panel rendering `ExcelTranslationReport`, and an "Open output"
  button that opens the OS file explorer at the output file.
- **ADDED:** New JS-callable `Api` methods in
  `src/components/interfaces/web_ui.py`: `pick_excel_input`,
  `pick_excel_output`, `translate_excel`, `get_excel_status`,
  `cancel_excel`, `open_in_explorer`, `get_excel_options`. Existing `Api`
  methods are preserved unchanged.
- **ADDED:** A background-thread execution model for Excel runs that mirrors
  the existing single-sentence async pattern (start → poll). Progress updates
  are pushed via a `get_excel_status(job_id)` polling endpoint (matches the
  existing `get_result` polling pattern).
- **ADDED:** A `threading.Event`-based cancellation wired to
  `translate_excel(cancel_event=...)`.
- **ADDED:** Domain-exception → user-friendly-message mapping mirroring the
  CLI `excel` command (`OllamaConnectionError`/`EmbeddingConnectionError` →
  daemon-reachability message; `RAMGuardError` → RAM-guard message; other
  `LegalTranslationError` → its message; per-segment failures → warnings
  list, not modal errors).
- **ADDED:** A single-job concurrency guard — only one Excel job may run at a
  time, and the single-sentence Translate button is disabled while an Excel
  run is in progress (and vice versa), honoring the project's concurrency = 1
  constraint.
- **MODIFIED:** The `Api` class gains Excel-job state (a single in-flight job
  slot, a cancel event, a progress snapshot, a final report) protected by the
  existing `_lock`.
- **ADDED:** `tests/test_web_ui_excel.py` covering job start/progress/report,
  cancellation, concurrent-job guard, invalid-input rejection, options
  override, and thread-safety (background thread used).
- No changes to `excel.py`, the CLI, the LangGraph pipeline, nodes, prompts,
  glossary, TM, or config models. No new runtime dependencies.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `interfaces`: The pywebview desktop UI requirement is extended to expose
  the Excel translation feature through a new tab and new `Api` methods, with
  background-thread execution, progress reporting, cancellation, error
  mapping, Excel-options overrides, and a single-job concurrency guard. All
  existing `Api` methods and UI behavior are preserved.

## Impact

**Affected code:**
- `src/components/interfaces/web_ui.py` — new `Api` methods, Excel-job state,
  background-thread worker, error mapping.
- `src/components/interfaces/web_frontend.py` — new Excel tab markup, CSS,
  and JS (file pickers, options, progress, report, open-output).
- `tests/test_web_ui_excel.py` — new test module.
- `pyproject.toml` — `[tool.ruff.lint.per-file-ignores]` gains
  `"tests/test_web_ui_excel.py" = ["E501"]` (single-line OOXML fixture
  literals, mirroring `tests/test_excel.py`).

**Affected APIs:**
- The pywebview JS bridge gains new `pywebview.api.*` methods. No existing
  method signature changes.

**Dependencies:** No new runtime dependencies. Uses only `web_ui.py`'s
existing imports plus stdlib (`threading`, `pathlib`, `subprocess`,
`webview` file dialogs).

**Systems affected:**
- pywebview desktop UI (`iraqi-translate ui`).
- Test suite (one new test file).

**Migration path:** Additive only. The new tab and `Api` methods are
introduced alongside the existing UI; no existing behavior is altered. The
single-job guard adds a cross-tab disablement rule that is the only behavior
change to existing UI (Translate button disabled during an Excel run) — this
is required by the concurrency = 1 hard constraint and is documented in the
delta spec.

**Rollback plan:** The change is isolated to `web_ui.py`,
`web_frontend.py`, `tests/test_web_ui_excel.py`, the OpenSpec change, and one
`pyproject.toml` per-file-ignore line. Revert the commit to roll back. No
data files, no `db/` artifacts, no config models are touched.

**Affected files (old → new):**

| Old path | New path |
|---|---|
| `src/components/interfaces/web_ui.py` | `src/components/interfaces/web_ui.py` (modified) |
| `src/components/interfaces/web_frontend.py` | `src/components/interfaces/web_frontend.py` (modified) |
| — | `tests/test_web_ui_excel.py` (new) |
| `pyproject.toml` | `pyproject.toml` (one per-file-ignore line added) |

**Scope:**

_In scope:_
- New Excel tab in the pywebview UI.
- New `Api` methods for file pickers, Excel run, status polling,
  cancellation, explorer-open, and Excel-options retrieval.
- Background-thread execution with progress + cancellation.
- Domain-exception → UI-message mapping (mirrors CLI).
- Single-job concurrency guard with cross-tab disablement.
- `tests/test_web_ui_excel.py`.
- OpenSpec change `add-excel-ui` (this proposal + delta spec + design +
  tasks), validated and archived after verification.

_Out of scope:_
- Modifying `excel.py`, the CLI `excel` command, the LangGraph pipeline,
  nodes, prompts, glossary, TM, or config models.
- Adding the Excel tab to the Tkinter UI (`tk_ui.py`) — separate task.
- New runtime dependencies.
- Changing the single-sentence Translate tab, Audit Trace tab, or History
  tab behavior (the only cross-tab effect is the disablement rule from the
  concurrency guard).
- Persisting Excel-option edits to `config.yaml` (in-memory only).

**Event Storming / bounded-context basis:** This change is internal to the
`interfaces` bounded context (the delivery layer). It wires the existing
`excel.py` orchestration seam (already in `interfaces`) into the existing
`web_ui.py` presentation seam (also in `interfaces`). No cross-context
boundary is crossed; the dependency graph stays acyclic
(`interfaces → translation_pipeline`, never the reverse).
