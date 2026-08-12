## MODIFIED Requirements

### Requirement: ExcelConfig model

`ExcelConfig` SHALL be a Pydantic model in `src/config/models.py` with boolean toggles `translate_comments` (default `True`), `translate_headers_footers` (default `True`), `translate_chart_titles` (default `True`), `max_segment_chars` (default `4096`, segments longer than this are skipped with a warning), `max_xlsx_bytes` (default `104857600` = 100 MB, files larger than this are rejected before processing), and `max_segments` (default `10000`, workbooks whose extracted segment count exceeds this are rejected before translation). `AppConfig` SHALL expose it as `excel: ExcelConfig` with defaults applied when the `excel:` section is absent from `config.yaml`.

#### Scenario: defaults apply when the section is absent
- **GIVEN** a `config.yaml` with no `excel:` section
- **WHEN** `load_config` parses it
- **THEN** `cfg.excel.translate_comments` is `True`, `cfg.excel.translate_headers_footers` is `True`, `cfg.excel.translate_chart_titles` is `True`, `cfg.excel.max_segment_chars` is `4096`, `cfg.excel.max_xlsx_bytes` is `104857600`, and `cfg.excel.max_segments` is `10000`

#### Scenario: an oversized segment is skipped
- **GIVEN** a cell whose text exceeds `max_segment_chars`
- **WHEN** `translate_excel` runs
- **THEN** that segment is skipped (original text preserved) and a warning is recorded in the report

#### Scenario: an oversized workbook is rejected
- **GIVEN** a `config.yaml` with `excel.max_xlsx_bytes: 10485760` (10 MB) and an input workbook of 50 MB
- **WHEN** `translate_excel` runs
- **THEN** `InputValidationError` is raised before any adapter is constructed

#### Scenario: a workbook with too many segments is rejected
- **GIVEN** a `config.yaml` with `excel.max_segments: 1000` and a workbook whose extracted segment count is 1500
- **WHEN** `translate_excel` runs
- **THEN** `InputValidationError` is raised after extraction but before any translation

#### Scenario: invalid max_xlsx_bytes is rejected at config load
- **GIVEN** a `config.yaml` with `excel.max_xlsx_bytes: 0`
- **WHEN** `load_config` parses it
- **THEN** `ConfigError` is raised (the validator requires `max_xlsx_bytes >= 1_048_576`)

#### Scenario: invalid max_segments is rejected at config load
- **GIVEN** a `config.yaml` with `excel.max_segments: 50`
- **WHEN** `load_config` parses it
- **THEN** `ConfigError` is raised (the validator requires `max_segments >= 100`)
