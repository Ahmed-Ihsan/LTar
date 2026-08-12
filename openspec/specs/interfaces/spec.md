## Purpose

The delivery layer: CLI (Typer), pywebview desktop UI, Tkinter desktop UI, MCP server, and human-in-the-loop review. This component exposes the translation pipeline to users and external tools through multiple interfaces, all sharing the same underlying adapters and graph.
## Requirements
### Requirement: CLI subcommands

The CLI SHALL be a Typer application with nine subcommands: `doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, `ui`, and `excel`. Each command accepts its arguments via Typer options and arguments and lives in its own module under `src/components/interfaces/commands/`. `cli.py` SHALL be a thin Typer app that imports and registers the commands; it SHALL NOT contain command logic directly. Each command SHALL be decorated with `handle_pipeline_errors` from `src/utils/cli_errors.py` so exit codes are consistent (see the `cli-commands` capability for the exit-code table). The `translate`, `batch`, and `excel` commands SHALL validate every user-supplied `--input` and `--out` path via `src.utils.paths.validate_path_in_root` against the project root before any file operation; on `PathContainmentError` they SHALL exit with code 4. Domain exceptions from the Gemini backend (`GeminiAuthError`, `GeminiQuotaError`, `LLMConnectionError`, `LLMTimeoutError`) SHALL map to the same CLI exit codes as the Ollama connection/timeout family (connection → 2, other domain → 1) via the existing `handle_pipeline_errors` decorator — no new exit code is introduced.

#### Scenario: doctor runs environment diagnostics
- **GIVEN** the CLI is invoked with the `doctor` subcommand
- **WHEN** the command executes
- **THEN** it checks the configured backend's reachability, model presence (for local backends) or API-key presence + connectivity (for `gemini`), ChromaDB directory, glossary DB, TM DB, and RAM headroom (for local backends), printing a CheckResult for each

#### Scenario: translate translates a single text
- **GIVEN** the CLI is invoked with `translate --input "المادة ١" --direction ar-en`
- **WHEN** the command executes
- **THEN** the translation pipeline runs and the final translation is printed

#### Scenario: batch translates a JSONL file sequentially
- **GIVEN** the CLI is invoked with `batch --input translations.jsonl`
- **WHEN** the command executes
- **THEN** each line of the JSONL file is translated sequentially (concurrency = 1) and results are written to the output file

#### Scenario: ingest builds the vector store and glossary
- **GIVEN** the CLI is invoked with `ingest --rebuild`
- **WHEN** the command executes
- **THEN** the corpus is parsed, chunked, embedded, and written to ChromaDB, and the glossary is loaded into SQLite

#### Scenario: tm-build builds TM from corpus
- **GIVEN** the CLI is invoked with `tm-build`
- **WHEN** the command executes
- **THEN** the Translation Memory is built from aligned corpus files

#### Scenario: ui launches the configured desktop UI
- **GIVEN** the CLI is invoked with `ui`
- **WHEN** the command executes
- **THEN** the desktop UI backend selected by `cfg.ui.backend` (default `"web"`) is launched

#### Scenario: cli.py is a thin registration file
- **GIVEN** the `cli.py` source
- **WHEN** its line count and imports are inspected
- **THEN** it imports each command from `src.components.interfaces.commands.*` and registers it; it contains no command logic definitions

#### Scenario: a Gemini auth error maps to exit code 2
- **GIVEN** the pipeline raises `GeminiAuthError` during a `translate` run with `llm_backend: gemini`
- **WHEN** `handle_pipeline_errors` catches it
- **THEN** the CLI exits with code 2 (connection/auth family), matching the Ollama connection-error exit code

### Requirement: CLI dependency injection

The CLI SHALL construct concrete adapters via `_construct_adapters(cfg) -> Adapters`, which bundles `llm`, `embedder`, `glossary_index`, `persist_dir`, and `tm`. `_run_translation` and `_run_translation_streamed` accept these as keyword-only args for dependency injection (DIP). Variables holding adapter instances or store handles SHALL be annotated with concrete types (e.g., `ChromaStore`, `TranslationMemory`) not `object`, so that method calls like `.close()` and `.list_all()` pass mypy strict. `_construct_adapters` SHALL branch on `cfg.llm_backend`: when `cfg.llm_backend == "ollama"` (the default) it SHALL construct `OllamaEngineAdapter` and `Embedder` as today; when `cfg.llm_backend == "gemini"` it SHALL construct a single `GeminiEngineAdapter` and use it for **both** the `llm` and `embedder` fields of `Adapters` (the Gemini backend serves LLM and embeddings from the same provider). When `cfg.llm_backend == "gemini"` and `cfg.gemini_api_key` is `None`, `_construct_adapters` SHALL exit with a clear error (this is a defensive check; `load_config` already rejects this case). The `google-genai` SDK SHALL be lazily imported inside `gemini.py` so the Ollama code path never imports it.

#### Scenario: Adapters bundle contains all concrete adapters
- **GIVEN** a valid AppConfig with `llm_backend: ollama`
- **WHEN** _construct_adapters is called
- **THEN** an Adapters object is returned with llm, embedder, glossary_index, persist_dir, and tm fields

#### Scenario: Adapter variables have concrete types
- **GIVEN** the refactored cli.py with concrete type annotations
- **WHEN** mypy checks method calls on adapter variables (e.g., store.close(), tm.list_all())
- **THEN** no attr-defined errors are reported because the variables are typed with their concrete classes

#### Scenario: gemini backend constructs a GeminiEngineAdapter for both llm and embedder
- **GIVEN** a valid AppConfig with `llm_backend: gemini` and a non-None `gemini_api_key`
- **WHEN** `_construct_adapters` is called
- **THEN** the returned `Adapters.llm` and `Adapters.embedder` are the **same** `GeminiEngineAdapter` instance (single backend serving both roles)

#### Scenario: ollama backend path is unchanged
- **GIVEN** a valid AppConfig with `llm_backend: ollama`
- **WHEN** `_construct_adapters` is called
- **THEN** it constructs `OllamaEngineAdapter` and `Embedder` exactly as before this change (no behavioral regression)

#### Scenario: gemini backend without an API key exits with a clear error
- **GIVEN** a valid AppConfig with `llm_backend: gemini` and `gemini_api_key is None`
- **WHEN** `_construct_adapters` is called
- **THEN** it prints an error naming `GEMINI_API_KEY` and raises `typer.Exit(code=1)` without constructing any adapter

#### Scenario: the google-genai SDK is not imported on the ollama path
- **GIVEN** `llm_backend: ollama`
- **WHEN** `_construct_adapters` runs and `sys.modules` is inspected
- **THEN** `google.genai` is NOT present in `sys.modules` (lazy import is confined to `gemini.py`)

### Requirement: CLI helper functions

The CLI SHALL provide helper functions: `_project_root`, `_resolve_path`, `_new_run_logger`, `_new_tm`, `_check_ollama_reachable`, `_canonical_model_name`, `_list_ollama_models`, `_check_models_present`, `_check_chroma_dir`, `_check_glossary_db`, `_check_tm_db`, `_check_ram_headroom`, `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`. The `_canonical_model_name` helper SHALL accept `str | None` and return `str` by handling the `None` case internally. The `int()` conversion of `ByteSize | None` SHALL guard against `None`. The `str`-to-`int` assignment conflict SHALL be resolved by using the correct type for the variable.

#### Scenario: Provenance markdown is generated
- **GIVEN** a TranslationState with glossary_hits, context_chunks, and tm_hits
- **WHEN** _provenance_markdown is called
- **THEN** a markdown string documenting the sources used is returned

#### Scenario: Audit trace markdown is generated
- **GIVEN** a list of revision states from the audit loop
- **WHEN** _audit_trace_markdown is called
- **THEN** a markdown string documenting each revision pass is returned

#### Scenario: _canonical_model_name handles None
- **GIVEN** a model name that is None
- **WHEN** _canonical_model_name is called
- **THEN** it returns a default string (e.g., "") without raising a mypy arg-type error

### Requirement: pywebview desktop UI

`launch_ui(cfg, adapters) -> None` SHALL build and run a pywebview window with an embedded HTML/CSS/JS frontend. The JS-facing `Api` SHALL be a thin facade composing three sub-facades: `TranslationApi` (translate, submit_review, approve_review, get_history), `ExcelApi` (translate_excel, pick_excel_input, pick_excel_output, open_in_explorer), and `SystemApi` (get_models, get_default_model, get_examples, get_store_counts). The facade SHALL expose the same method names to JS as the original monolithic `Api`, so the frontend requires no changes. A `_UiHumanReviewer` implements the HumanReviewer protocol thread-safely.

#### Scenario: Web UI translate returns a result
- **GIVEN** the web UI Api facade is initialized with cfg and adapters
- **WHEN** api.translate("المادة ١", "ar-en", "qwen2.5:7b-instruct-q5_K_M") is called
- **THEN** a result string is returned containing the translation, provenance, and audit trace

#### Scenario: Web UI human review is thread-safe
- **GIVEN** the _UiHumanReviewer is used from the UI thread
- **WHEN** a review is submitted from the JS frontend
- **THEN** the review result is safely communicated back to the translation thread

#### Scenario: Api facade composes three sub-facades
- **GIVEN** the `web_ui.py` source
- **WHEN** the `Api` class is inspected
- **THEN** it constructs `TranslationApi`, `ExcelApi`, and `SystemApi` instances and delegates each method to the appropriate sub-facade; the JS-facing method names are unchanged

### Requirement: Tkinter desktop UI

`launch_ui(cfg, adapters) -> None` SHALL build and run a Tkinter window with a tabbed notebook (Translate tab + Audit Trace tab). Translation runs in a background thread; results are polled via a queue. `UiWidgets` bundles the input_box, direction dropdown, translate button, output box, provenance box, and trace box. `launch_ui` SHALL call `configure_logging(log_dir=cfg.paths.log_dir)` before building the window. The background-thread worker SHALL catch `Exception` (so the UI does not crash) but SHALL log the exception via `logging.getLogger(__name__).exception(...)` before putting the error on the result queue — silent swallowing without a log line is forbidden.

#### Scenario: Tkinter UI launches with tabs
- **GIVEN** a valid cfg and adapters
- **WHEN** launch_ui is called
- **THEN** a Tkinter window opens with a "Translate" tab and an "Audit Trace" tab

#### Scenario: Translation runs in background thread
- **GIVEN** the user clicks the Translate button in the Tkinter UI
- **WHEN** _start_translation is called
- **THEN** the translation runs in a background thread and the UI remains responsive, with results polled via _poll_result

#### Scenario: a worker-thread exception is logged before surfacing
- **GIVEN** a background-thread translation that raises `RuntimeError("boom")`
- **WHEN** the worker's `except Exception as e:` block runs
- **THEN** `logger.exception("Tk translation worker failed")` is called (emitting a full traceback to `app.log`) BEFORE `result_queue.put(("error", str(e)))`, and the UI does not crash

#### Scenario: launch_ui configures logging on startup
- **GIVEN** `launch_ui` is called with a valid `cfg.paths.log_dir`
- **WHEN** the window is being built
- **THEN** `configure_logging(log_dir=cfg.paths.log_dir)` has been called and `app.log` is being written

### Requirement: MCP server

`mcp_server.py` SHALL expose a FastMCP server with five tools: `search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library`, and `search_all`. Each tool takes a query and optional max_results and returns JSON. A `main()` function runs the server on stdio. Each tool SHALL validate `len(query) <= 500` (rejecting empty or oversized queries with `InputValidationError`) and clamp `max_results` to `[1, 100]`. Each tool SHALL be guarded by a `TokenBucket(rate=10/60, capacity=10)` rate limiter that returns a 429-style JSON error when the bucket is empty. A `main()` function runs the server on stdio.

#### Scenario: MCP search_all tool returns JSON
- **GIVEN** the MCP server is running and the rate-limiter bucket is non-empty
- **WHEN** the search_all tool is called with query="القانون المدني"
- **THEN** a JSON string of search results from all sources is returned

#### Scenario: MCP server runs on stdio
- **GIVEN** the mcp_server module is executed
- **WHEN** main() is called
- **THEN** the FastMCP server runs on stdio transport

#### Scenario: an oversized query is rejected
- **GIVEN** the MCP server is running
- **WHEN** a tool is called with a 501-character query
- **THEN** `InputValidationError` is raised and the tool returns an error JSON without contacting any search source

#### Scenario: max_results is clamped to 100
- **GIVEN** the MCP server is running
- **WHEN** a tool is called with `max_results=1000`
- **THEN** the tool proceeds with `max_results=100` (clamped, not rejected)

#### Scenario: rate-limiter returns 429 after a burst
- **GIVEN** the MCP server is running and 10 requests have been made in the last second
- **WHEN** an 11th request is made immediately
- **THEN** the tool returns a 429-style JSON error without contacting any search source

### Requirement: Human-in-the-loop review

`HumanReviewer` SHALL be a PEP 544 Protocol with a `review(state) -> str` method. `human_review(state, cfg, *, llm, reviewer, tm) -> TranslationState` runs the human review step: if the reviewer edits the draft, the correction is saved and re-audited. `_save_correction` writes corrections to a JSONL file. `_save_to_tm` inserts corrected pairs into the Translation Memory. The `record` dict in `_save_correction` SHALL be typed as `dict[str, object]` not bare `dict`.

#### Scenario: Reviewer approves without edits
- **GIVEN** a HumanReviewer that returns the original draft unchanged
- **WHEN** human_review is called
- **THEN** the state is returned with final_output set and no re-audit occurs

#### Scenario: Reviewer edits the draft
- **GIVEN** a HumanReviewer that returns an edited draft different from the original
- **WHEN** human_review is called
- **THEN** the correction is saved via _save_correction, the edited draft is re-audited via audit_node, and the state is updated

#### Scenario: Corrected pair is saved to TM
- **GIVEN** a reviewer edits the draft and a TranslationMemory is provided
- **WHEN** human_review is called
- **THEN** _save_to_tm inserts the corrected source-target pair into the TM

#### Scenario: hitl.py passes mypy strict
- **GIVEN** the refactored hitl.py with dict type parameter
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for hitl.py (no type-arg)

### Requirement: Excel translation command

The CLI SHALL provide an `excel` subcommand that translates a `.xlsx` workbook in place: `iraqi-translate excel --input <path> --out <path> --direction <ar-en|en-ar> [--config <path>]`. It SHALL construct concrete adapters via the existing `_construct_adapters(cfg) -> Adapters` and call `translate_excel(...)`. Domain exceptions from the pipeline SHALL map to the same CLI exit codes as `translate`/`batch` (Ollama/embedding connection → 2, RAM guard → 3, other → 1).

#### Scenario: excel command translates a workbook
- **GIVEN** the CLI is invoked with `excel --input report.xlsx --out report_en.xlsx --direction ar-en`
- **WHEN** the command executes
- **THEN** each human-readable text segment in the workbook is translated through the pipeline and a new workbook is written to `report_en.xlsx` with all non-text artifacts preserved

#### Scenario: excel command rejects a missing input file
- **GIVEN** the CLI is invoked with `excel --input missing.xlsx --out out.xlsx --direction ar-en`
- **WHEN** the command executes
- **THEN** it prints an error and exits with code 1 without constructing adapters

#### Scenario: excel command maps a RAM guard error to exit code 3
- **GIVEN** the pipeline raises `RAMGuardError` during an `excel` run
- **WHEN** the command catches it
- **THEN** it prints a RAM-guard message and exits with code 3

### Requirement: Excel translation orchestration

`translate_excel(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> ExcelTranslationReport` SHALL be the orchestration seam. It SHALL: (1) check `input_path.stat().st_size <= cfg.excel.max_xlsx_bytes`; (2) read the input workbook bytes; (3) extract the deduplicated set of translatable string segments via the pure XML helpers; (4) check `len(segments) <= cfg.excel.max_segments`; (5) translate each unique source string exactly once by calling the existing `run_translation(input_text, direction, cfg, ...)` seam (concurrency = 1 per the RAM rule); (6) patch the translated strings back into a new workbook; (7) write the output workbook atomically. The `extract_translatable_strings` and `patch_strings` helpers SHALL NOT accept unused `segments` or `cfg` parameters (dead parameters are removed). All adapter dependencies are keyword-only (DIP).

#### Scenario: each unique string is translated once
- **GIVEN** a workbook whose `sharedStrings` references the same Arabic string from 50 cells
- **WHEN** `translate_excel` runs
- **THEN** `run_translation` is called exactly once for that string and all 50 cells receive the same translation

#### Scenario: extract_translatable_strings has no dead parameters
- **GIVEN** the `excel.py:extract_translatable_strings` signature
- **WHEN** it is inspected
- **THEN** it accepts only `(xlsx_bytes, *, cfg)` (or fewer); it does NOT accept an unused `segments` parameter

### Requirement: Excel XML extraction and patching (pure helpers)

The pure helpers `extract_translatable_strings(xlsx_bytes, *, cfg) -> list[StringSegment]` and `patch_strings(xlsx_bytes, segments, translations, *, cfg) -> bytes` SHALL operate on workbook bytes with **no dependency on the pipeline or adapters**. Extraction SHALL collect text from this allowlist of OOXML locations only: (a) `xl/sharedStrings.xml` `<si>` plain `<t>` and rich-text `<r><t>` runs; (b) `xl/worksheets/sheetN.xml` inline strings `<is><t>` and `<is><r><t>`; (c) `xl/commentsN.xml` `<text><t>` and `<text><r><t>` (when `cfg.excel.translate_comments`); (d) `xl/worksheets/sheetN.xml` `<header>`/`<footer>` text with `&`-format codes preserved (when `cfg.excel.translate_headers_footers`); (e) `xl/charts/chartN.xml` chart and axis titles `<c:title>` rich-text `<a:t>` (when `cfg.excel.translate_chart_titles`). Extraction SHALL deduplicate by source text and skip empty/whitespace-only texts; it SHALL NOT apply the `max_segment_chars` filter (that is the orchestrator's policy). Patching SHALL write translated text back into the same `<t>`/`<a:t>` nodes and leave every other XML part byte-for-byte unchanged. Every part not in the allowlist (formulas `<f>`, numeric values `<v>`, defined names, table `displayName`, pivot caches, conditional formatting, data validation, hyperlinks, images, page layout, custom XML parts) SHALL be preserved exactly.

**Security:** Both helpers SHALL parse XML with `defusedxml.ElementTree.fromstring` (not `xml.etree.ElementTree.fromstring`) to defend against XXE and entity-expansion attacks. Both helpers SHALL validate every zip entry name via `src.utils.zip_safe.validate_zip_path` before reading or writing, rejecting absolute paths and `..` traversal segments. `patch_strings` SHALL escape every translated string via `src.utils.xml_escape.escape_xml_text` before assigning to `el.text`, so that LLM output containing `</t>`, `<script>`, or `&` cannot corrupt the workbook XML.

#### Scenario: shared strings are extracted and patched
- **GIVEN** a workbook with `sharedStrings.xml` containing `<si><t>عقد البيع</t></si>`
- **WHEN** `extract_translatable_strings` then `patch_strings` run with the translation "contract of sale"
- **THEN** the patched `sharedStrings.xml` contains `<si><t>contract of sale</t></si>` and the cells referencing it render the translated text

#### Scenario: formulas are preserved
- **GIVEN** a cell `<c r="A1"><f>SUM(B1:B3)</f><v>6</v></c>`
- **WHEN** the workbook is translated
- **THEN** the patched sheet XML still contains `<f>SUM(B1:B3)</f><v>6</v>` unchanged

#### Scenario: merged cells, charts, and conditional formatting are preserved byte-for-byte
- **GIVEN** a workbook with merged cells, a chart, and a conditional-formatting rule
- **WHEN** the workbook is translated
- **THEN** the `mergeCells`, `chart`, and `conditionalFormatting` XML parts are identical in the input and output zips

#### Scenario: header/footer formatting codes are preserved
- **GIVEN** a header text `Page &P of &N - تقرير`
- **WHEN** the header is translated
- **THEN** the patched header is `Page &P of &N - report` — the `&P` and `&N` codes are preserved verbatim and only the literal text is translated

#### Scenario: rich-text runs are translated per run
- **GIVEN** a shared string with two rich-text runs `<r><rPr>...</rPr><t>عقد</t></r><r><rPr>...</rPr><t>البيع</t></r>`
- **WHEN** the workbook is translated
- **THEN** each `<t>` is translated independently so per-run formatting is preserved exactly

#### Scenario: XXE entity expansion is refused
- **GIVEN** a workbook whose `sharedStrings.xml` contains `<!DOCTYPE si [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>` and `<t>&xxe;</t>`
- **WHEN** `extract_translatable_strings` parses the part
- **THEN** `defusedxml` refuses to expand the external entity and the part is skipped (or a `defusedxml.EntitiesForbidden` is raised and caught, skipping the part) — the file `/etc/passwd` is never read

#### Scenario: a zip-slip entry is rejected
- **GIVEN** a workbook whose zip contains an entry named `../../evil.txt`
- **WHEN** `extract_translatable_strings` iterates `zin.infolist()`
- **THEN** `validate_zip_path` raises `InputValidationError` for that entry and the run aborts with a clear error (no file is written outside the output path)

#### Scenario: a translation containing XML closing tags is escaped
- **GIVEN** a translation `evil</t><script>alert(1)</script>` produced for a shared string
- **WHEN** `patch_strings` writes it into the `<t>` node
- **THEN** the patched XML contains `&lt;/t&gt;&lt;script&gt;alert(1)&lt;/script&gt;` and the workbook remains well-formed XML

### Requirement: Non-translatable token protection

`protect_non_translatable(text, *, cfg) -> tuple[str, dict[str, str]]` SHALL replace non-translatable tokens (URLs, email addresses, pure numbers, IDs matching `^[A-Z]{1,4}\d+$`-style article references, `{placeholder}` / `<placeholder>` / `%placeholder%` patterns) with stable sentinels before translation. `restore_protected(text, token_map) -> str` SHALL restore them verbatim after translation. This guarantees formulas-as-text, placeholders, IDs, and numbers are not altered by the LLM.

#### Scenario: a placeholder inside a cell is preserved
- **GIVEN** a cell text `Total for {year}: مبلغ`
- **WHEN** protect → translate → restore runs
- **THEN** the `{year}` token appears verbatim in the final output and only `مبلغ` is translated

#### Scenario: a URL is preserved
- **GIVEN** a cell text `See https://example.org for details`
- **WHEN** protect → translate → restore runs
- **THEN** `https://example.org` appears verbatim in the final output

### Requirement: ExcelTranslationReport model

`ExcelTranslationReport` (in `src/components/interfaces/models.py`) SHALL be a frozen dataclass recording: `total_segments`, `translated`, `skipped`, `failed`, `cancelled: bool`, and `warnings: list[str]`. It is returned by `translate_excel` and printed by the CLI.

#### Scenario: report counts are consistent
- **GIVEN** a workbook with 10 unique segments where 9 translated and 1 failed
- **WHEN** `translate_excel` completes
- **THEN** the report has `total_segments=10`, `translated=9`, `failed=1`, `cancelled=False`

### Requirement: ExcelConfig

`ExcelConfig` SHALL be a Pydantic model in `src/config/models.py` with boolean toggles `translate_comments` (default `True`), `translate_headers_footers` (default `True`), `translate_chart_titles` (default `True`), and `max_segment_chars` (default `4096`, segments longer than this are skipped with a warning). `AppConfig` SHALL expose it as `excel: ExcelConfig` with defaults applied when the `excel:` section is absent from `config.yaml`.

#### Scenario: defaults apply when the section is absent
- **GIVEN** a `config.yaml` with no `excel:` section
- **WHEN** `load_config` parses it
- **THEN** `cfg.excel.translate_comments` is `True`, `cfg.excel.translate_headers_footers` is `True`, `cfg.excel.translate_chart_titles` is `True`, and `cfg.excel.max_segment_chars` is `4096`

#### Scenario: an oversized segment is skipped
- **GIVEN** a cell whose text exceeds `max_segment_chars`
- **WHEN** `translate_excel` runs
- **THEN** that segment is skipped (original text preserved) and a warning is recorded in the report

### Requirement: Excel feature respects hard constraints

The Excel feature SHALL respect the project hard constraints: no cloud calls, no telemetry, single in-flight translation (concurrency = 1), 8 GB RAM ceiling (stream per-part XML processing; no whole-workbook in-memory model beyond the `sharedStrings` part), and no new runtime dependencies (stdlib `zipfile` + `xml.etree.ElementTree` only).

#### Scenario: no new runtime dependencies
- **GIVEN** the implemented `excel.py`
- **WHEN** its imports are inspected
- **THEN** it imports only from the Python standard library and from `src.*` project modules — never `openpyxl`, `pandas`, `lxml`, or any third-party package

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

### Requirement: Interfaces component folder

The interface layer SHALL reside in `src/components/interfaces/` as a bounded-context component. The folder SHALL contain: `__init__.py` (re-exports), `models.py`, `cli.py`, `web_ui.py`, `tk_ui.py`, `mcp_server.py`, and `hitl.py`.

#### Scenario: Component folder structure
- **GIVEN** the refactored project structure
- **WHEN** the `src/components/interfaces/` directory is inspected
- **THEN** it contains `__init__.py`, `models.py`, `cli.py`, `web_ui.py`, `tk_ui.py`, `mcp_server.py`, and `hitl.py`

### Requirement: Interfaces models module

Interface-specific data models SHALL reside in `src/components/interfaces/models.py`. This includes `CheckResult` (doctor check outcome), `Adapters` (bundle of concrete adapters), and `UiTranslationResult` (translation result for UI consumption).

#### Scenario: Import interface models from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.models import CheckResult, Adapters, UiTranslationResult` is executed
- **THEN** all data classes are imported successfully

### Requirement: Interfaces CLI module

The Typer `app` and all CLI commands (`doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, `ui`) and helper functions SHALL reside in `src/components/interfaces/cli.py`.

#### Scenario: Import CLI app from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.cli import app` is executed
- **THEN** the Typer app is imported successfully

### Requirement: Interfaces web UI module

`launch_ui`, `Api`, and `_UiHumanReviewer` SHALL reside in `src/components/interfaces/web_ui.py`.

#### Scenario: Import web UI from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.web_ui import launch_ui` is executed
- **THEN** launch_ui is imported successfully

### Requirement: Interfaces Tkinter UI module

`launch_ui`, `UiWidgets`, and the Tkinter UI builder functions SHALL reside in `src/components/interfaces/tk_ui.py`.

#### Scenario: Import Tkinter UI from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.tk_ui import launch_ui` is executed
- **THEN** launch_ui is imported successfully

### Requirement: Interfaces MCP server module

The FastMCP `mcp` instance, all MCP tools (`search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library`, `search_all`), and `main()` SHALL reside in `src/components/interfaces/mcp_server.py`.

#### Scenario: Import MCP server from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.mcp_server import mcp, main` is executed
- **THEN** both the mcp instance and main function are imported successfully

### Requirement: Interfaces HITL module

`HumanReviewer` (Protocol), `human_review`, `_save_correction`, and `_save_to_tm` SHALL reside in `src/components/interfaces/hitl.py`.

#### Scenario: Import HITL API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces.hitl import HumanReviewer, human_review` is executed
- **THEN** both the Protocol and the function are imported successfully

### Requirement: Interfaces public API re-export

`src/components/interfaces/__init__.py` SHALL re-export the component's public API so that `from src.components.interfaces import app, launch_ui, human_review` works without specifying the submodule.

#### Scenario: Re-exported public API
- **GIVEN** the refactored structure
- **WHEN** `from src.components.interfaces import app, human_review` is executed
- **THEN** all symbols are imported successfully via the package __init__

### Requirement: Interfaces inter-component imports

Modules within `interfaces/` SHALL import from other components using component paths (e.g., `from src.components.translation_pipeline.graph import build_graph`), not from the old flat `src.graph` paths.

#### Scenario: cli.py imports from translation pipeline component
- **GIVEN** the refactored cli.py
- **WHEN** its imports are inspected
- **THEN** it imports build_graph from `src.components.translation_pipeline.graph`, not from `src.graph`

#### Scenario: cli.py imports from infrastructure component
- **GIVEN** the refactored cli.py
- **WHEN** its imports are inspected
- **THEN** it imports RunLogger from `src.components.infrastructure.run_logging`, not from `src.run_logging`

#### Scenario: hitl.py imports from translation pipeline component
- **GIVEN** the refactored hitl.py
- **WHEN** its imports are inspected
- **THEN** it imports audit_node from `src.components.translation_pipeline.nodes`, not from `src.nodes`

### Requirement: CLI module single responsibility

The `cli.py` module SHALL contain only Typer app definition and thin command wrappers. Each command function SHALL delegate to dedicated modules: `diagnostics.py` (all `_check_*` doctor functions and `_detect_offload_mode`), `orchestration.py` (`_run_translation`, `_run_translation_streamed`, `_initial_state`, `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`, `_render_provenance`), `tm_commands.py` (`tm_build`, `tm_build_parallel`, `tm_add_parallel` handler logic). Each command function in `cli.py` SHALL be ≤ 20 lines (a thin wrapper that parses args and delegates).

#### Scenario: cli.py contains only command wrappers
- **GIVEN** the `interfaces/cli.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains the Typer `app` and command functions (`doctor`, `translate`, `batch`, `ingest`, `tm_build`, `tm_build_parallel`, `tm_add_parallel`, `ui`); no `_check_*`, `_run_*`, or `_provenance_*` functions

#### Scenario: Diagnostics are in a separate module
- **GIVEN** the `interfaces/diagnostics.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_check_ollama_reachable`, `_check_models_present`, `_check_chroma_dir`, `_check_glossary_db`, `_check_tm_db`, `_check_ram_headroom`, `_detect_offload_mode`

#### Scenario: Orchestration is in a separate module
- **GIVEN** the `interfaces/orchestration.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_run_translation`, `_run_translation_streamed`, `_initial_state`, `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`, `_render_provenance`

#### Scenario: TM commands are in a separate module
- **GIVEN** the `interfaces/tm_commands.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains the TM command handler logic

#### Scenario: Command functions are thin wrappers
- **GIVEN** any command function in `cli.py` (e.g., `translate`)
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 20 lines, delegating to functions in `orchestration.py` or `tm_commands.py`

### Requirement: Web UI frontend separation

The embedded HTML/CSS/JS frontend in `web_frontend.py` SHALL insert all translation, provenance, audit-trace, and history content via `element.textContent` or `element.innerHTML = escapeHtml(value)`. Static markup (hard-coded HTML strings) may continue to use `innerHTML`. An `escapeHtml(s)` JS helper SHALL escape `&`, `<`, `>`, `"`, and `'`.

#### Scenario: a translation containing script tags is rendered as text
- **GIVEN** a translation result `<script>alert(1)</script>` returned from the pipeline
- **WHEN** the frontend renders it into the output panel
- **THEN** the literal text `<script>alert(1)</script>` is displayed to the user and no script executes

#### Scenario: provenance markdown is rendered safely
- **GIVEN** provenance markdown containing a malicious `<img onerror=...>` payload (from a poisoned glossary hit)
- **WHEN** the frontend renders it into the provenance panel
- **THEN** the payload is displayed as text and no `onerror` handler fires

### Requirement: Shared config loader for CLI commands

The `interfaces/config_loader.py` module SHALL provide a `load_or_exit(path: Path | None = None) -> AppConfig` helper that wraps `load_config()`, prints a user-friendly error message on `ConfigError`, and calls `typer.Exit(1)`. All CLI command functions SHALL use this helper instead of duplicating the try/except/load pattern.

#### Scenario: Config loads successfully
- **GIVEN** a valid config.yaml at the default path
- **WHEN** `load_or_exit()` is called
- **THEN** an AppConfig is returned

#### Scenario: Config error exits gracefully
- **GIVEN** no config.yaml at the expected path
- **WHEN** `load_or_exit()` is called
- **THEN** a user-friendly error message is printed and `typer.Exit(1)` is called

#### Scenario: All CLI commands use the shared loader
- **GIVEN** the `cli.py` command functions are inspected
- **WHEN** their config-loading code is read
- **THEN** they all call `load_or_exit()` instead of duplicating try/except/load_config patterns

### Requirement: Adapters interface segregation

The `interfaces/models.py` module SHALL define `LLMAdapters` (containing `llm` and `embedder`) and `KnowledgeAdapters` (containing `glossary_index`, `persist_dir`, and `tm`) as separate dataclasses. The existing `Adapters` dataclass SHALL remain for backward compatibility but SHALL be composed of `LLMAdapters` and `KnowledgeAdapters`. Consumers SHALL depend on the narrowest interface they need.

#### Scenario: LLMAdapters contains only LLM-related adapters
- **GIVEN** the `LLMAdapters` dataclass is inspected
- **WHEN** its fields are listed
- **THEN** it contains `llm` and `embedder` only

#### Scenario: KnowledgeAdapters contains only knowledge-related adapters
- **GIVEN** the `KnowledgeAdapters` dataclass is inspected
- **WHEN** its fields are listed
- **THEN** it contains `glossary_index`, `persist_dir`, and `tm` only

#### Scenario: Adapters composes both
- **GIVEN** the `Adapters` dataclass is inspected
- **WHEN** its fields are listed
- **THEN** it contains all 5 fields (`llm`, `embedder`, `glossary_index`, `persist_dir`, `tm`) for backward compatibility

### Requirement: HITL review decomposition

The `human_review` function SHALL be decomposed into focused helpers: `_handle_review_decision(state, reviewed_text, cfg, *, llm) -> TranslationState` handles the approve/edit decision, `_re_audit_if_edited(state, edited_draft, cfg, *, llm) -> TranslationState` handles re-auditing. The public `human_review` function SHALL orchestrate these helpers and be ≤ 25 lines (excluding docstrings). The `llm` parameter SHALL be typed as `LLMEngineAdapter` and `tm` as `TranslationMemory` — not `object`.

#### Scenario: Reviewer approves without edits
- **GIVEN** a HumanReviewer that returns the original draft unchanged
- **WHEN** human_review is called
- **THEN** the state is returned with final_output set and no re-audit occurs

#### Scenario: Reviewer edits the draft
- **GIVEN** a HumanReviewer that returns an edited draft different from the original
- **WHEN** human_review is called
- **THEN** the correction is saved via _save_correction, the edited draft is re-audited via audit_node, and the state is updated

#### Scenario: Corrected pair is saved to TM
- **GIVEN** a reviewer edits the draft and a TranslationMemory is provided
- **WHEN** human_review is called
- **THEN** _save_to_tm inserts the corrected source-target pair into the TM

#### Scenario: human_review is ≤ 25 lines
- **GIVEN** the `human_review` function
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 25 lines, delegating to `_handle_review_decision` and `_re_audit_if_edited`

#### Scenario: llm parameter is typed as LLMEngineAdapter
- **GIVEN** the `human_review` function signature is inspected
- **WHEN** the type of the `llm` parameter is checked
- **THEN** it is typed as `LLMEngineAdapter`, not `object`

### Requirement: JSONL batch record schema validation

`orchestration.py:_process_batch` SHALL parse each JSONL line via `src.utils.jsonl_schema.BatchRecord.model_validate_json(line)`. On `pydantic.ValidationError`, the orchestrator SHALL log the line number and skip the record (continuing the batch) rather than aborting the run.

#### Scenario: a malformed batch line is skipped with a log
- **GIVEN** a batch JSONL file whose line 7 is `{"input": "x", "direction": "fr-en"}`
- **WHEN** `_process_batch` runs
- **THEN** line 7 is skipped, a warning is logged naming the line number, and the remaining lines are processed

#### Scenario: an oversized batch input is skipped
- **GIVEN** a batch JSONL line whose `input` field is 10 001 characters
- **WHEN** `_process_batch` runs
- **THEN** the line is skipped with a validation-error log and the batch continues

### Requirement: JSONL parallel-pair schema validation

`tm_commands.py:tm_build_parallel` and `tm_add_parallel` SHALL parse each JSONL line via `src.utils.jsonl_schema.ParallelPair.model_validate_json(line)`. On `pydantic.ValidationError`, the command SHALL print the line number and error and exit with code 5.

#### Scenario: a malformed parallel-pair line aborts tm-build-parallel
- **GIVEN** a JSONL file whose line 3 is `{"source_sentence": "a"}` (missing `target_sentence`)
- **WHEN** `tm_build_parallel` runs
- **THEN** the command prints a validation error naming line 3 and exits with code 5 without writing to the TM database

#### Scenario: a valid parallel-pair line is accepted
- **GIVEN** a JSONL line `{"source_sentence": "a", "target_sentence": "b"}`
- **WHEN** `tm_build_parallel` parses it
- **THEN** a `ParallelPair` with `source_lang="ar"` and `target_lang="en"` (defaults) is returned and added to the batch

### Requirement: HITL stream coordinator

`orchestration.py` SHALL expose a `_HITLStreamCoordinator` helper class that encapsulates the HITL stream-loop, history-capture, and reviewer-coordination logic currently inlined in `run_translation_streamed`. `run_translation_streamed` SHALL be a thin wrapper that constructs the coordinator and runs it. The coordinator SHALL be independently testable.

#### Scenario: run_translation_streamed delegates to the coordinator
- **GIVEN** the `orchestration.py:run_translation_streamed` source
- **WHEN** it is inspected
- **THEN** it constructs a `_HITLStreamCoordinator` and calls a `run()` method; the stream-loop and history-capture logic live in the coordinator, not in `run_translation_streamed`

#### Scenario: the coordinator is independently testable
- **GIVEN** a `_HITLStreamCoordinator` constructed with mocked graph, reviewer, and history
- **WHEN** its `run()` method is called
- **THEN** it executes the stream loop and returns the final state and history without requiring the full `run_translation_streamed` wrapper

### Requirement: Doctor command Gemini connectivity check

The `doctor` command SHALL branch on `cfg.llm_backend`. When `cfg.llm_backend == "gemini"`, it SHALL run a `_check_gemini_api_key(cfg) -> CheckResult` check (verifying `cfg.gemini_api_key` is non-None and non-empty) and a `_check_gemini_reachable(cfg) -> CheckResult` check (constructing a `GeminiEngineAdapter` and issuing a minimal API ping — e.g., listing available models — to verify the key is valid and the API is reachable). It SHALL skip the Ollama-reachability, local-model-presence, and LLM-RAM-budget checks (those are local-backend concerns; cloud inference does not consume local RAM for weights). It SHALL still run the ChromaDB-directory, glossary-DB, TM-DB, and (general) RAM-headroom checks — those are backend-independent. The two new check helpers SHALL reside in `src/components/interfaces/diagnostics.py` alongside the existing `_check_*` helpers. A failed API-key or connectivity check SHALL cause the doctor command to exit with code 2 (matching the Ollama-failed exit code).

#### Scenario: doctor checks the API key when gemini is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: gemini` in config.yaml
- **WHEN** the command executes
- **THEN** a CheckResult named "Gemini API key present" is rendered, OK only when `cfg.gemini_api_key` is non-empty

#### Scenario: doctor pings the Gemini API when gemini is selected
- **GIVEN** the CLI is invoked with `doctor`, `llm_backend: gemini`, and a valid `GEMINI_API_KEY`
- **WHEN** the command executes
- **THEN** a CheckResult named "Gemini API reachable" is rendered, OK only when the list-models ping succeeds

#### Scenario: doctor skips Ollama checks when gemini is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: gemini`
- **WHEN** the rendered checks are inspected
- **THEN** no CheckResult named "Ollama daemon reachable" or "Required models present" appears (those checks are skipped on the gemini path)

#### Scenario: doctor still checks ChromaDB, glossary, and TM when gemini is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: gemini`
- **WHEN** the rendered checks are inspected
- **THEN** the "ChromaDB directory exists", "Glossary SQLite populated", and TM checks still appear (they are backend-independent)

#### Scenario: a failed Gemini connectivity check exits with code 2
- **GIVEN** the CLI is invoked with `doctor`, `llm_backend: gemini`, and an invalid `GEMINI_API_KEY`
- **WHEN** the "Gemini API reachable" check fails
- **THEN** the doctor command exits with code 2

#### Scenario: doctor runs Ollama checks when ollama is selected
- **GIVEN** the CLI is invoked with `doctor` and `llm_backend: ollama`
- **WHEN** the command executes
- **THEN** the existing Ollama reachability, model-presence, and RAM-headroom checks run exactly as before this change (no behavioral regression)

