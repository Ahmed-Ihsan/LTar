## MODIFIED Requirements

### Requirement: CLI subcommands

The CLI SHALL be a Typer application with nine subcommands: `doctor`, `translate`, `batch`, `ingest`, `tm-build`, `tm-build-parallel`, `tm-add-parallel`, `ui`, and `excel`. Each command accepts its arguments via Typer options and arguments and lives in its own module under `src/components/interfaces/commands/`. `cli.py` SHALL be a thin Typer app that imports and registers the commands; it SHALL NOT contain command logic directly. Each command SHALL be decorated with `handle_pipeline_errors` from `src/utils/cli_errors.py` so exit codes are consistent (see the `cli-commands` capability for the exit-code table). The `translate`, `batch`, and `excel` commands SHALL validate every user-supplied `--input` and `--out` path via `src.utils.paths.validate_path_in_root` against the project root before any file operation; on `PathContainmentError` they SHALL exit with code 4.

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

#### Scenario: ui launches the configured desktop UI
- **GIVEN** the CLI is invoked with `ui`
- **WHEN** the command executes
- **THEN** the desktop UI backend selected by `cfg.ui.backend` (default `"web"`) is launched

#### Scenario: cli.py is a thin registration file
- **GIVEN** the `cli.py` source
- **WHEN** its line count and imports are inspected
- **THEN** it imports each command from `src.components.interfaces.commands.*` and registers it; it contains no command logic definitions

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

## ADDED Requirements

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
