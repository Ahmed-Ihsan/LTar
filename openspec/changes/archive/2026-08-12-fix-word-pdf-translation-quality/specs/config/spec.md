## MODIFIED Requirements

### Requirement: WordConfig model

`WordConfig` SHALL be a Pydantic model in `src/config/models.py` with fields: `translate_comments: bool = True`, `translate_headers_footers: bool = True`, `translate_footnotes: bool = True`, `translate_endnotes: bool = True`, `translate_glossary_doc: bool = False`, `set_bidi_direction: bool = True`, `max_segment_chars: int = 8192`, `max_docx_bytes: int = 52428800` (50 MiB), `max_segments: int = 20000`. Field validators SHALL reject `max_segment_chars < 16`, `max_docx_bytes < 1048576` (1 MiB), and `max_segments < 100`. `AppConfig` SHALL expose it as `word: WordConfig` with defaults applied when the `word:` section is absent from `config.yaml` (Pydantic default-factory).

#### Scenario: load_config applies WordConfig defaults

- **GIVEN** a `config.yaml` with no `word:` section
- **WHEN** `load_config` parses it
- **THEN** `cfg.word` is a `WordConfig` with `translate_comments=True`, `translate_headers_footers=True`, `translate_footnotes=True`, `translate_endnotes=True`, `translate_glossary_doc=False`, `set_bidi_direction=True`, `max_segment_chars=8192`, `max_docx_bytes=52428800`, `max_segments=20000`

#### Scenario: load_config honors an explicit word section

- **GIVEN** a `config.yaml` with `word: {translate_comments: false, max_segment_chars: 1024, set_bidi_direction: false}`
- **WHEN** `load_config` parses it
- **THEN** `cfg.word.translate_comments` is `False`, `cfg.word.max_segment_chars` is `1024`, and `cfg.word.set_bidi_direction` is `False`, while the other fields retain their defaults

#### Scenario: WordConfig rejects max_segment_chars below 16

- **GIVEN** a `config.yaml` with `word: {max_segment_chars: 8}`
- **WHEN** `load_config` parses it
- **THEN** it raises `ConfigError` (Pydantic `ValidationError` wrapped) naming the `max_segment_chars` constraint

#### Scenario: WordConfig rejects max_docx_bytes below 1 MiB

- **GIVEN** a `config.yaml` with `word: {max_docx_bytes: 1024}`
- **WHEN** `load_config` parses it
- **THEN** it raises `ConfigError` naming the `max_docx_bytes` constraint
