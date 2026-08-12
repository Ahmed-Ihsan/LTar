## MODIFIED Requirements

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

### Requirement: Excel translation orchestration

`translate_excel(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> ExcelTranslationReport` SHALL be the orchestration seam. It SHALL: (1) check `input_path.stat().st_size <= cfg.excel.max_xlsx_bytes` and abort with `InputValidationError` if exceeded; (2) read the input workbook bytes; (3) extract the deduplicated set of translatable string segments via the pure XML helpers; (4) check `len(segments) <= cfg.excel.max_segments` and abort with `InputValidationError` if exceeded; (5) translate each unique source string exactly once by calling the existing `run_translation(input_text, direction, cfg, ...)` seam (concurrency = 1 per the RAM rule); (6) patch the translated strings back into a new workbook; (7) write the output workbook atomically to `<output>.tmp` then `os.replace(tmp, output)` so a crash never leaves a partial workbook. All adapter dependencies are keyword-only (DIP).

#### Scenario: each unique string is translated once
- **GIVEN** a workbook whose `sharedStrings` references the same Arabic string from 50 cells
- **WHEN** `translate_excel` runs
- **THEN** `run_translation` is called exactly once for that string and all 50 cells receive the same translation

#### Scenario: progress is reported per segment
- **GIVEN** a `progress` callback accepting `(completed, total, current_source)`
- **WHEN** `translate_excel` runs over a workbook with N unique segments
- **THEN** the callback is invoked after each segment with monotonically increasing `completed`

#### Scenario: cancellation stops the run early
- **GIVEN** a `cancel_event` that becomes set after the third segment
- **WHEN** `translate_excel` runs
- **THEN** it stops processing further segments, writes the partial workbook (segments already translated are patched; remaining segments keep their original text), and the report records `cancelled=True`

#### Scenario: a per-segment translation failure keeps the original text
- **GIVEN** `run_translation` raises `LLMRuntimeError` for one segment
- **WHEN** `translate_excel` runs
- **THEN** that segment is left untranslated (original text preserved), a warning is recorded in the report, and the remaining segments are still processed

#### Scenario: an oversized workbook is rejected before processing
- **GIVEN** an input workbook whose file size exceeds `cfg.excel.max_xlsx_bytes`
- **WHEN** `translate_excel` is called
- **THEN** `InputValidationError` is raised before any adapter is constructed and no output file is created

#### Scenario: a workbook with too many segments is rejected
- **GIVEN** a workbook whose extracted segment count exceeds `cfg.excel.max_segments`
- **WHEN** `translate_excel` runs
- **THEN** `InputValidationError` is raised after extraction but before any translation, and no output file is created

#### Scenario: output is written atomically
- **GIVEN** a successful `translate_excel` run
- **WHEN** the run completes
- **THEN** the output file exists at `output_path` and no `.tmp` file remains; if the process crashes mid-write, no partial file exists at `output_path`

### Requirement: CLI subcommands

The CLI SHALL be a Typer application with eight subcommands: `doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, and `ui`. Each command accepts its arguments via Typer options and arguments. The `translate`, `batch`, and `excel` commands SHALL validate every user-supplied `--input` and `--out` path via `src.utils.paths.validate_path_in_root` against the project root before any file operation; on `PathContainmentError` they SHALL print a clear error and exit with code 4.

#### Scenario: doctor runs environment diagnostics
- **GIVEN** the CLI is invoked with the `doctor` subcommand
- **WHEN** the command executes
- **THEN** it checks Ollama reachability, model presence, ChromaDB directory, glossary DB, TM DB, and RAM headroom, printing a CheckResult for each

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

#### Scenario: ui launches the web-based desktop UI
- **GIVEN** the CLI is invoked with `ui`
- **WHEN** the command executes
- **THEN** the pywebview desktop UI is launched

#### Scenario: translate rejects a path-traversal input
- **GIVEN** the CLI is invoked with `translate --input "../../etc/passwd" --direction ar-en`
- **WHEN** the command executes
- **THEN** it prints a path-containment error and exits with code 4 without constructing adapters

#### Scenario: batch rejects a path-traversal output
- **GIVEN** the CLI is invoked with `batch --input data/batch.jsonl --out "../../etc/evil.jsonl"`
- **WHEN** the command executes
- **THEN** it prints a path-containment error and exits with code 4 without opening the input file

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

### Requirement: pywebview desktop UI

`launch_ui(cfg, adapters) -> None` SHALL build and run a pywebview window with an embedded HTML/CSS/JS frontend. An `Api` class is exposed to JS with methods: `get_models`, `get_default_model`, `get_examples`, `get_store_counts`, `get_history`, `translate`, `submit_review`, `approve_review`. A `_UiHumanReviewer` implements the HumanReviewer protocol thread-safely. `Api.__init__` SHALL generate a cryptographically random session token (`secrets.token_urlsafe(32)`) and inject it into the page at load time via `evaluate_js`. Every state-mutating `Api` method (`translate`, `translate_excel`, `submit_review`, `approve_review`, `open_in_explorer`, `pick_excel_input`, `pick_excel_output`) SHALL require the token via a `_require_token` decorator and raise `PermissionError` on mismatch. The frontend SHALL send `window.__SESSION_TOKEN` as the first argument to every `pywebview.api.*` call.

#### Scenario: Web UI translate returns a result
- **GIVEN** the web UI Api is initialized with cfg and adapters and a valid session token
- **WHEN** api.translate("المادة ١", "ar-en", "qwen2.5:7b-instruct-q5_K_M", token=<valid>) is called
- **THEN** a result string is returned containing the translation, provenance, and audit trace

#### Scenario: Web UI human review is thread-safe
- **GIVEN** the _UiHumanReviewer is used from the UI thread
- **WHEN** a review is submitted from the JS frontend with a valid token
- **THEN** the review result is safely communicated back to the translation thread

#### Scenario: an API call without a token is rejected
- **GIVEN** the web UI Api is initialized
- **WHEN** a state-mutating method is called without a `token` argument
- **THEN** `PermissionError` is raised and no translation job is started

#### Scenario: an API call with the wrong token is rejected
- **GIVEN** the web UI Api is initialized with token T
- **WHEN** a state-mutating method is called with `token="wrong"`
- **THEN** `PermissionError` is raised and no translation job is started

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

## ADDED Requirements

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
