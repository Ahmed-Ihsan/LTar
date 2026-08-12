## ADDED Requirements

### Requirement: pywebview Excel tab

The pywebview desktop UI SHALL add an "Excel" tab alongside the existing
Translate, Audit Trace, and History tabs. The Excel tab SHALL contain: an
input-file picker button that opens a native open-file dialog filtered to
`.xlsx`; an output-file picker button that opens a native save-file dialog
filtered to `.xlsx` with a default name of `<input-stem>_translated.xlsx`;
a direction dropdown (`ar-en` / `en-ar`) reusing the existing direction
selector styling; Excel-option controls bound to `cfg.excel`
(`translate_comments`, `translate_headers_footers`,
`translate_chart_titles` checkboxes and a `max_segment_chars` number field
with min 16); a Translate Excel button (disabled until both paths are set
and a direction is chosen, and disabled while a run is in progress); a
Cancel button visible only while a run is in progress; a progress bar
(0–100%) plus a live `translated / total` counter and the current segment's
source text truncated to 80 chars; a report panel rendering
`ExcelTranslationReport` (`total_segments`, `translated`, `skipped`,
`failed`, `cancelled`, and a scrollable warnings list) after the run; and an
"Open output" button that opens the OS file explorer at the output file,
shown only after a successful run. The Translate Excel button SHALL prompt a
confirmation dialog before overwriting an existing output file. All labels
SHALL be in English. The tab SHALL match the existing UI's visual style (no
new CSS framework).

#### Scenario: Excel tab is present alongside existing tabs
- **GIVEN** the pywebview desktop UI is launched
- **WHEN** the window renders
- **THEN** four tabs are visible: Translate, Audit Trace, History, and Excel

#### Scenario: Translate Excel button is disabled until inputs are valid
- **GIVEN** the Excel tab is open and no input or output path is set
- **WHEN** the user inspects the Translate Excel button
- **THEN** the button is disabled
- **WHEN** the user sets an input path, an output path, and a direction
- **THEN** the button becomes enabled

#### Scenario: overwriting an existing output file requires confirmation
- **GIVEN** the user has set an output path that already exists on disk
- **WHEN** the user clicks Translate Excel
- **THEN** a confirmation dialog is shown before the run starts
- **WHEN** the user declines the confirmation
- **THEN** no run is started

#### Scenario: open-output button opens the OS file explorer
- **GIVEN** a successful Excel run has completed and the output file exists
- **WHEN** the user clicks the Open output button
- **THEN** the OS file explorer opens with the output file selected

### Requirement: pywebview Excel Api methods

The `Api` class exposed to JS SHALL add these methods, keeping all existing
methods intact: `pick_excel_input() -> str | None` (native open-file dialog,
`.xlsx` filter, returns the path or `None`); `pick_excel_output(default_name:
str) -> str | None` (native save-file dialog, `.xlsx` filter); 
`translate_excel(input_path: str, output_path: str, direction: str, options:
dict) -> dict` (starts the run in a background thread and returns
immediately with a job descriptor, never blocking the UI thread);
`get_excel_status(job_id: str) -> dict` returning
`{state: "running"|"done"|"cancelled"|"error", completed, total, current,
report}` where `report` is the `ExcelTranslationReport` as a dict (or `None`
while running); `cancel_excel(job_id: str) -> None` (sets the cancel event
for that job); `open_in_explorer(path: str) -> None` (opens the OS file
explorer at the file); and `get_excel_options() -> dict` (returns the current
`cfg.excel` values). The `options` dict passed to `translate_excel` SHALL be
applied to a deep copy of `cfg` (via `cfg.model_copy(deep=True)` then
`cfg.excel = cfg.excel.model_copy(update=...)`) so the run uses the
UI-selected values without mutating the global config or writing
`config.yaml`.

#### Scenario: translate_excel starts a job and returns immediately
- **GIVEN** the `Api` is initialized with cfg and adapters and no Excel job is running
- **WHEN** `api.translate_excel(input, output, "ar-en", options)` is called
- **THEN** a background thread is started, a job descriptor is returned, and the calling (UI) thread is not blocked

#### Scenario: get_excel_status reports progress then a final report
- **GIVEN** an Excel job is running
- **WHEN** `api.get_excel_status(job_id)` is polled
- **THEN** it returns `state="running"` with increasing `completed` values until the run finishes, then `state="done"` with the final `report` dict

#### Scenario: get_excel_options returns the current cfg.excel values
- **GIVEN** the `Api` is initialized with a cfg whose `excel` section has defaults
- **WHEN** `api.get_excel_options()` is called
- **THEN** a dict with `translate_comments`, `translate_headers_footers`, `translate_chart_titles`, and `max_segment_chars` is returned

#### Scenario: options override does not mutate the global config
- **GIVEN** the user sets `translate_comments=False` in the UI and starts a run
- **WHEN** `translate_excel` is called with `options={"translate_comments": False, ...}`
- **THEN** the run uses `translate_comments=False` and the global `cfg.excel.translate_comments` is unchanged after the run

### Requirement: pywebview Excel background-thread execution and cancellation

The Excel run SHALL execute in a background thread (it is long-running and
calls the local LLM). The `Api` methods exposed to JS SHALL be thread-safe,
reusing the same locking pattern as the existing translate flow; the
pywebview JS bridge calls SHALL never block the UI thread. Progress updates
SHALL be pushed to the JS frontend via the `get_excel_status` polling
endpoint (matching the existing `get_result` polling pattern). A
`threading.Event` SHALL be wired to the `cancel_event` parameter of
`translate_excel`; the Cancel button sets it. After cancellation, the UI
SHALL show the partial `ExcelTranslationReport` with `cancelled=True` and
SHALL communicate to the user that the output file was still written with
already-translated segments patched and remaining segments keeping their
original text.

#### Scenario: the UI thread is not blocked during an Excel run
- **GIVEN** an Excel run is in progress
- **WHEN** the JS frontend polls `get_excel_status`
- **THEN** the call returns promptly without waiting for the run to finish

#### Scenario: cancellation stops the run and shows the partial report
- **GIVEN** an Excel run is in progress
- **WHEN** the user clicks Cancel and `cancel_excel(job_id)` is called
- **THEN** the run stops processing further segments, the output file is written with already-translated segments patched, and `get_excel_status` returns `state="cancelled"` with a report whose `cancelled` is `True`

### Requirement: pywebview Excel error mapping

The Excel run SHALL map domain exceptions to user-friendly messages mirroring
the CLI `excel` command: `OllamaConnectionError` / `EmbeddingConnectionError`
→ "Cannot reach the Ollama daemon. Is `ollama serve` running?";
`RAMGuardError` → "RAM guard aborted the run. Free up memory and retry.";
other `LegalTranslationError` → the exception message. Per-segment
translation failures are already captured in
`ExcelTranslationReport.warnings` and SHALL be rendered in the warnings list,
not as modal errors. Invalid input (missing file or wrong extension) SHALL
produce an inline error message and SHALL NOT start a run.

#### Scenario: Ollama connection error maps to a daemon-reachability message
- **GIVEN** the LLM adapter raises `OllamaConnectionError` during an Excel run
- **WHEN** the run fails
- **THEN** `get_excel_status` returns `state="error"` with a message telling the user to check that `ollama serve` is running

#### Scenario: missing input file produces an inline error and no run
- **GIVEN** the user sets an input path that does not exist
- **WHEN** `translate_excel` is called
- **THEN** it returns an error state without starting a background thread

#### Scenario: per-segment failures appear in the warnings list
- **GIVEN** one segment's translation fails during an otherwise successful run
- **WHEN** the run completes
- **THEN** the report panel shows `failed=1` and the warnings list contains the per-segment failure entry, and no modal error is shown

### Requirement: pywebview Excel single-job concurrency guard

Only one Excel job SHALL run at a time (the project enforces concurrency = 1).
If a job is already running, `translate_excel` SHALL return an error state
immediately with the message "An Excel run is already in progress" without
starting a new thread. The single-sentence Translate button SHALL be disabled
while an Excel run is in progress, and the Translate Excel button SHALL be
disabled while a single-sentence translation is in progress, because they
share the same local LLM daemon.

#### Scenario: a second Excel job is rejected while one is running
- **GIVEN** an Excel job is running
- **WHEN** `translate_excel` is called again
- **THEN** it returns an error state with "An Excel run is already in progress" and no second background thread is started

#### Scenario: the Translate button is disabled during an Excel run
- **GIVEN** an Excel run is in progress
- **WHEN** the user switches to the Translate tab
- **THEN** the single-sentence Translate button is disabled until the Excel run finishes
