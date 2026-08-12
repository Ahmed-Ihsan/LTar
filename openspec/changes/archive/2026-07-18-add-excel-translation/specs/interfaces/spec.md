## ADDED Requirements

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

`translate_excel(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> ExcelTranslationReport` SHALL be the orchestration seam. It SHALL: (1) read the input workbook bytes; (2) extract the deduplicated set of translatable string segments via the pure XML helpers; (3) translate each unique source string exactly once by calling the existing `run_translation(input_text, direction, cfg, ...)` seam (concurrency = 1 per the RAM rule); (4) patch the translated strings back into a new workbook; (5) write the output workbook. All adapter dependencies are keyword-only (DIP).

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

### Requirement: Excel XML extraction and patching (pure helpers)

The pure helpers `extract_translatable_strings(xlsx_bytes, *, cfg) -> list[StringSegment]` and `patch_strings(xlsx_bytes, segments, translations, *, cfg) -> bytes` SHALL operate on workbook bytes with **no dependency on the pipeline or adapters**. Extraction SHALL collect text from this allowlist of OOXML locations only: (a) `xl/sharedStrings.xml` `<si>` plain `<t>` and rich-text `<r><t>` runs; (b) `xl/worksheets/sheetN.xml` inline strings `<is><t>` and `<is><r><t>`; (c) `xl/commentsN.xml` `<text><t>` and `<text><r><t>` (when `cfg.excel.translate_comments`); (d) `xl/worksheets/sheetN.xml` `<header>`/`<footer>` text with `&`-format codes preserved (when `cfg.excel.translate_headers_footers`); (e) `xl/charts/chartN.xml` chart and axis titles `<c:title>` rich-text `<a:t>` (when `cfg.excel.translate_chart_titles`). Extraction SHALL deduplicate by source text and skip empty/whitespace-only texts; it SHALL NOT apply the `max_segment_chars` filter (that is the orchestrator's policy). Patching SHALL write translated text back into the same `<t>`/`<a:t>` nodes and leave every other XML part byte-for-byte unchanged. Every part not in the allowlist (formulas `<f>`, numeric values `<v>`, defined names, table `displayName`, pivot caches, conditional formatting, data validation, hyperlinks, images, page layout, custom XML parts) SHALL be preserved exactly.

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
