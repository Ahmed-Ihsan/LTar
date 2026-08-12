## Context

The Excel translation feature (`src/components/interfaces/excel.py`) is
fully implemented and exposed via the CLI `excel` subcommand, but not from
the pywebview desktop UI. The desktop UI (`web_ui.py` + `web_frontend.py`)
currently has three tabs (Translate, Audit Trace, History) and an `Api`
class with a single-sentence async pattern: `translate()` starts a
background thread and returns `"started"`; JS polls `get_result()` every
300ms until the status leaves `"translating"`. A `_UiHumanReviewer` provides
thread-safe HITL hand-off via a `threading.Event`.

This change adds a fourth tab ("Excel") and new `Api` methods that drive the
existing `translate_excel` orchestration seam, reusing the same adapters
bundle (`Adapters`) constructed at launch.

## Goals / Non-Goals

**Goals:**
- Make the Excel feature fully usable from the GUI: pick input/output,
  choose direction + Excel options, run, see progress, cancel, see the
  report, open the output.
- Reuse the existing async pattern (background thread + polling) so the UI
  thread never blocks.
- Honor the concurrency = 1 hard constraint (single-job guard with
  cross-tab disablement).
- Preserve all existing UI behavior.

**Non-Goals:**
- No changes to `excel.py`, the CLI, the pipeline, prompts, glossary, TM, or
  config models.
- No Tkinter Excel tab.
- No new runtime dependencies.
- No persistence of Excel-option edits to `config.yaml` (in-memory only).

## Decisions

1. **Polling over push.** Match the existing `get_result` polling pattern
   (JS polls every 300ms) rather than introducing JS callbacks. This keeps
   the frontend architecture uniform and avoids a second async channel.
   `get_excel_status(job_id)` returns `{state, completed, total, current,
   report}`.
2. **Single in-flight job slot.** Per the concurrency = 1 constraint, the
   `Api` holds one Excel-job slot (`_excel_job`). `translate_excel` returns
   an error descriptor immediately if the slot is occupied. The slot is
   cleared when the worker thread exits (done/cancelled/error).
3. **Cross-tab disablement via a shared busy flag.** The `Api` exposes a
   lightweight `is_busy() -> bool` (True when either a single-sentence
   translation or an Excel run is in progress). The frontend disables the
   Translate button while an Excel run is in progress and the Translate
   Excel button while a single-sentence run is in progress. This is enforced
   in JS by querying `get_excel_status` / `get_result` state and by the
   `Api` rejecting concurrent starts.
4. **Deep-copied cfg per run.** Excel-option overrides are applied to
   `cfg.model_copy(deep=True)` then `cfg.excel = cfg.excel.model_copy(
   update=...)`, so the global config is never mutated and `config.yaml` is
   never written.
5. **Native file dialogs via `webview.windows[0].create_file_dialog`.**
   pywebview exposes native open/save dialogs; `pick_excel_input` /
   `pick_excel_output` wrap them with a `.xlsx` filter. This adds no new
   dependency (already imported `webview`).
6. **Explorer-open via `subprocess`.** `open_in_explorer` uses
   `subprocess.Popen(["explorer", "/select,", path])` on Windows (the
   project targets Windows per `run.bat`); a platform guard falls back to
   `os.startfile` on the parent directory for non-Windows.
7. **Error mapping mirrors the CLI.** The same exception classes map to the
   same user messages as the CLI `excel` command; per-segment failures stay
   in `report.warnings`.
8. **No new model loaded.** The run reuses `adapters.llm` / `embedder` /
   `glossary_index` / `persist_dir` / `tm` already constructed at launch.

## Risks / Trade-offs

- **Polling latency.** 300ms polling means progress updates lag by up to
  300ms. Acceptable for a workbook run; matches the existing single-sentence
  UX.
- **Cross-tab disablement is JS-enforced.** The `Api` rejects concurrent
  starts server-side (the source of truth); the JS disablement is a UX
  nicety. A race where the user clicks both buttons within one poll interval
  is resolved server-side by the single-job guard.
- **Explorer subprocess on non-Windows.** The project targets Windows
  (`run.bat`); the non-Windows fallback is best-effort (`os.startfile` on
  the parent dir).

## Target directory tree

```
src/components/interfaces/
  web_ui.py            # modified — new Api methods, Excel-job state, worker
  web_frontend.py      # modified — new Excel tab (HTML/CSS/JS)
  excel.py             # unchanged
  models.py            # unchanged (ExcelTranslationReport already defined)
  cli.py               # unchanged
tests/
  test_web_ui_excel.py # new
openspec/changes/add-excel-ui/
  proposal.md          # this change
  specs/interfaces/spec.md  # delta
  design.md            # this file
  tasks.md             # task list
pyproject.toml         # one per-file-ignore line added
```

## Component dependency diagram

```
web_ui.py (Api) ──▶ excel.translate_excel ──▶ orchestration.run_translation ──▶ translation_pipeline
                 ──▶ adapters (llm, embedder, glossary_index, persist_dir, tm)  (injected at launch)
                 ──▶ web_frontend._HTML (embedded asset)

No new inter-component edge. interfaces → translation_pipeline (existing).
```

## models.py contents

No new models. `ExcelTranslationReport` already lives in
`src/components/interfaces/models.py`. The `Api`'s Excel-job state is
private (a `_ExcelJob` dataclass local to `web_ui.py`):

```python
@dataclass(slots=True)
class _ExcelJob:
    job_id: str
    state: str            # "running" | "done" | "cancelled" | "error"
    completed: int
    total: int
    current: str
    report: ExcelTranslationReport | None
    error: str
    cancel_event: threading.Event
```

## Inter-component communication protocol

- `web_ui.Api.translate_excel` calls `excel.translate_excel(...)` with the
  injected adapters (keyword-only, DIP).
- Progress is delivered via a closure that mutates the `_ExcelJob` snapshot
  under `_lock`; `get_excel_status` reads it under `_lock`.
- Cancellation: `cancel_excel(job_id)` sets `job.cancel_event` under
  `_lock`; the worker passes it to `translate_excel(cancel_event=...)`.
- No new import edge. `web_ui.py` already imports from
  `src.components.interfaces.cli` and `orchestration`; it gains an import
  of `translate_excel` from `src.components.interfaces.excel`.

## Migration strategy

Additive — no file moves. Order:
1. Add `_ExcelJob` + new `Api` methods to `web_ui.py` (no frontend yet).
2. Add the Excel tab markup/CSS/JS to `web_frontend.py`.
3. Add `tests/test_web_ui_excel.py`.
4. Add the `pyproject.toml` per-file-ignore line.
5. Verify (pytest, ruff, mypy, openspec validate --all).
6. Archive the OpenSpec change.

## app.py / entry point design

Unchanged. `launch_ui(cfg, adapters)` is called by the CLI `ui` command; the
new `Api` methods are transparent to the entry point.

## pyproject.toml changes

- `[tool.ruff.lint.per-file-ignores]` adds:
  `"tests/test_web_ui_excel.py" = ["E501"]`
  (single-line OOXML fixture literals, mirroring `tests/test_excel.py`).

## ruff per-file-ignores path migrations

None. `web_ui.py` and `web_frontend.py` already have `E501` ignores
(long inline SVG/CSS lines); the new Excel tab markup follows the same
convention.
