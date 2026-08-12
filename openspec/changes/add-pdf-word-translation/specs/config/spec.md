## ADDED Requirements

### Requirement: WordConfig model

`WordConfig` SHALL be a Pydantic model in `src/config/models.py` with fields: `translate_comments: bool = True`, `translate_headers_footers: bool = True`, `translate_footnotes: bool = True`, `translate_endnotes: bool = True`, `translate_glossary_doc: bool = False`, `max_segment_chars: int = 8192`, `max_docx_bytes: int = 52428800` (50 MiB), `max_segments: int = 20000`. Field validators SHALL reject `max_segment_chars < 16`, `max_docx_bytes < 1048576` (1 MiB), and `max_segments < 100`. `AppConfig` SHALL expose it as `word: WordConfig` with defaults applied when the `word:` section is absent from `config.yaml` (Pydantic default-factory).

#### Scenario: load_config applies WordConfig defaults

- **GIVEN** a `config.yaml` with no `word:` section
- **WHEN** `load_config` parses it
- **THEN** `cfg.word` is a `WordConfig` with `translate_comments=True`, `translate_headers_footers=True`, `translate_footnotes=True`, `translate_endnotes=True`, `translate_glossary_doc=False`, `max_segment_chars=8192`, `max_docx_bytes=52428800`, `max_segments=20000`

#### Scenario: load_config honors an explicit word section

- **GIVEN** a `config.yaml` with `word: {translate_comments: false, max_segment_chars: 1024}`
- **WHEN** `load_config` parses it
- **THEN** `cfg.word.translate_comments` is `False` and `cfg.word.max_segment_chars` is `1024`, while the other fields retain their defaults

#### Scenario: WordConfig rejects max_segment_chars below 16

- **GIVEN** a `config.yaml` with `word: {max_segment_chars: 8}`
- **WHEN** `load_config` parses it
- **THEN** it raises `ConfigError` (Pydantic `ValidationError` wrapped) naming the `max_segment_chars` constraint

#### Scenario: WordConfig rejects max_docx_bytes below 1 MiB

- **GIVEN** a `config.yaml` with `word: {max_docx_bytes: 1024}`
- **WHEN** `load_config` parses it
- **THEN** it raises `ConfigError` naming the `max_docx_bytes` constraint

### Requirement: PdfConfig model

`PdfConfig` SHALL be a Pydantic model in `src/config/models.py` with fields: `out_format: Literal["docx", "txt"] = "docx"`, `max_pdf_bytes: int = 104857600` (100 MiB), `max_pages: int = 500`, `max_segment_chars: int = 8192`, `max_segments: int = 20000`, `skip_header_footer: bool = True`. Field validators SHALL reject `max_pdf_bytes < 1048576` (1 MiB) and non-positive `max_pages` / `max_segments` / `max_segment_chars`. `AppConfig` SHALL expose it as `pdf: PdfConfig` with defaults applied when the `pdf:` section is absent from `config.yaml` (Pydantic default-factory).

#### Scenario: load_config applies PdfConfig defaults

- **GIVEN** a `config.yaml` with no `pdf:` section
- **WHEN** `load_config` parses it
- **THEN** `cfg.pdf` is a `PdfConfig` with `out_format="docx"`, `max_pdf_bytes=104857600`, `max_pages=500`, `max_segment_chars=8192`, `max_segments=20000`, `skip_header_footer=True`

#### Scenario: load_config honors an explicit pdf section

- **GIVEN** a `config.yaml` with `pdf: {out_format: txt, max_pages: 50}`
- **WHEN** `load_config` parses it
- **THEN** `cfg.pdf.out_format` is `"txt"` and `cfg.pdf.max_pages` is `50`, while the other fields retain their defaults

#### Scenario: PdfConfig rejects an invalid out_format

- **GIVEN** a `config.yaml` with `pdf: {out_format: rtf}`
- **WHEN** `load_config` parses it
- **THEN** it raises `ConfigError` (Pydantic `ValidationError` wrapped) naming the `out_format` literal constraint

#### Scenario: PdfConfig rejects max_pdf_bytes below 1 MiB

- **GIVEN** a `config.yaml` with `pdf: {max_pdf_bytes: 1024}`
- **WHEN** `load_config` parses it
- **THEN** it raises `ConfigError` naming the `max_pdf_bytes` constraint

#### Scenario: PdfConfig rejects non-positive max_pages

- **GIVEN** a `config.yaml` with `pdf: {max_pages: 0}`
- **WHEN** `load_config` parses it
- **THEN** it raises `ConfigError` naming the `max_pages` constraint
