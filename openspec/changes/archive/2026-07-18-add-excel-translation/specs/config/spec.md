## ADDED Requirements

### Requirement: ExcelConfig model

`ExcelConfig` SHALL be a Pydantic model in `src/config/models.py` with fields: `translate_comments: bool = True`, `translate_headers_footers: bool = True`, `translate_chart_titles: bool = True`, `max_segment_chars: int = 4096`. `AppConfig` SHALL expose it as `excel: ExcelConfig` with defaults applied when the `excel:` section is absent from `config.yaml` (Pydantic default-factory).

#### Scenario: load_config applies ExcelConfig defaults
- **GIVEN** a `config.yaml` with no `excel:` section
- **WHEN** `load_config` parses it
- **THEN** `cfg.excel` is an `ExcelConfig` with all default values

#### Scenario: load_config honors an explicit excel section
- **GIVEN** a `config.yaml` with `excel: {translate_comments: false, max_segment_chars: 1024}`
- **WHEN** `load_config` parses it
- **THEN** `cfg.excel.translate_comments` is `False` and `cfg.excel.max_segment_chars` is `1024`
