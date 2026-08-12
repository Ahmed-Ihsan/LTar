## Target directory tree (additions only)

```
src/
  components/
    interfaces/
      excel.py            # NEW — pure XML helpers + translate_excel orchestrator
      models.py           # MODIFIED — + ExcelTranslationReport
      cli.py              # MODIFIED — + excel subcommand
  config/
    models.py             # MODIFIED — + ExcelConfig
    config.py             # MODIFIED — wire excel: ExcelConfig into AppConfig
tests/
  test_excel.py           # NEW
  fixtures/excel/         # NEW — generated at test time (no binary committed)
config.yaml               # MODIFIED — + excel: section
pyproject.toml            # MODIFIED — + per-file-ignore for excel.py
```

## Component dependency diagram (additions)

```
cli.py  ──▶  excel.translate_excel   ──▶  orchestration.run_translation  (existing)
                                       │
                                       └─▶  excel pure XML helpers (stdlib only)

excel.py  ──▶  stdlib (zipfile, xml.etree.ElementTree, re, threading)
excel.py  ──▶  src.config.AppConfig (ExcelConfig)
excel.py  ──▶  src.components.translation_pipeline.exceptions (domain errors)
excel.py  ──▶  src.components.interfaces.orchestration.run_translation
excel.py  ──▶  src.components.interfaces.models.ExcelTranslationReport
```

The pure XML helpers (`extract_translatable_strings`, `patch_strings`, `protect_non_translatable`, `restore_protected`) have **no** dependency on the pipeline or adapters — they are pure functions on `bytes`. This keeps them unit-testable without Ollama and respects the acyclic dependency graph (interfaces → translation_pipeline, never the reverse).

## excel.py module contents

### Data models
- `StringSegment` — frozen dataclass: `part: str` (zip part path), `xpath_id: str` (stable identifier for the `<t>`/`<a:t>` node within the part), `text: str` (the source text). Used as the key for deduplication and translation mapping.

### Pure XML helpers (no pipeline dependency)
- `protect_non_translatable(text, *, cfg) -> tuple[str, dict[str, str]]` — replace URLs, emails, pure numbers, article-ID patterns, and `{...}`/`<...>`/`%...%` placeholders with sentinels `\x00T0\x00`, `\x00T1\x00`, ...; return `(protected_text, token_map)`.
- `restore_protected(text, token_map) -> str` — inverse of `protect_non_translatable`.
- `extract_translatable_strings(xlsx_bytes, *, cfg) -> list[StringSegment]` — open the zip, parse each allowlisted part with `ElementTree`, collect `<t>`/`<a:t>` text nodes, dedupe by text, skip empty and over-`max_segment_chars` texts.
- `patch_strings(xlsx_bytes, segments, translations, *, cfg) -> bytes` — re-open the zip, write a new zip copying every part byte-for-byte except the allowlisted parts, which are re-serialized with translated `<t>`/`<a:t>` text. `translations` maps `StringSegment.text -> translated_text` (deduplication means one translation per unique source).

### Orchestrator (DI, reuses run_translation)
- `translate_excel(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> ExcelTranslationReport`:
  1. Read input bytes.
  2. `segments = extract_translatable_strings(bytes, cfg=cfg)`.
  3. For each unique `segment.text` (in stable order): check `cancel_event`; protect non-translatable tokens; call `run_translation(protected, direction, cfg, llm=..., embedder=..., ...)`; restore tokens; store `translations[text] = result`; report progress; on `LLMRuntimeError`/`EmbeddingError` record warning + keep original; on other exceptions re-raise.
  4. `out_bytes = patch_strings(bytes, segments, translations, cfg=cfg)`.
  5. Write `out_bytes` to `output_path`.
  6. Return `ExcelTranslationReport`.

### Namespace handling
Register the OOXML namespaces with `ElementTree.register_namespace` so round-tripped XML keeps Excel's prefixes:
- `http://schemas.openxmlformats.org/spreadsheetml/2006/main` → `` (default)
- `http://schemas.openxmlformats.org/drawingml/2006/main` → `a`
- `http://schemas.openxmlformats.org/officeDocument/2006/relationships` → `r`
- `http://schemas.openxmlformats.org/chartml/2006/main` → `c`

## AppConfig wiring

`src/config/models.py`:
```python
class ExcelConfig(BaseModel):
    translate_comments: bool = True
    translate_headers_footers: bool = True
    translate_chart_titles: bool = True
    max_segment_chars: int = 4096
```

`src/config/config.py`: add `excel: ExcelConfig = Field(default_factory=ExcelConfig)` to `AppConfig`.

## config.yaml addition

```yaml
# --- Excel workbook translation ---
excel:
  translate_comments: true
  translate_headers_footers: true
  translate_chart_titles: true
  max_segment_chars: 4096
```

## CLI command

```python
@app.command()
def excel(
    input_arg: Annotated[Path, typer.Option("--input", help="Path to input .xlsx file.")],
    out: Annotated[Path, typer.Option("--out", help="Path to output .xlsx file.")],
    direction: Annotated[Direction, typer.Option("--direction", help="Translation direction.")],
    config_path: Annotated[Path, typer.Option("--config", "-c", help="Path to config.yaml.")] = <default>,
) -> None:
    ...
```

Mirrors `batch`: constructs adapters via `_construct_adapters`, calls `translate_excel`, maps domain exceptions to exit codes 2/3/1, prints the `ExcelTranslationReport`.

## pyproject.toml change

Add to `[tool.ruff.lint.per-file-ignores]`:
```toml
# translate_excel takes one arg per injected dependency (DIP, engineering-
# principles §1.5) — mirrors orchestration.py's run_translation seam.
"src/components/interfaces/excel.py" = ["PLR0913"]
```

## Migration strategy

Purely additive. Order:
1. `ExcelConfig` + `AppConfig` wiring + `config.yaml` section.
2. `excel.py` pure helpers.
3. `excel.py` orchestrator.
4. `ExcelTranslationReport` model.
5. `cli.py` `excel` command.
6. `tests/test_excel.py`.
7. `pyproject.toml` per-file-ignore.
8. Verify (pytest + ruff + mypy + openspec validate).

## Rollback

Revert the single commit. No data files touched. The feature is isolated to new files plus small additive edits.
