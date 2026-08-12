## Target directory tree (additions + modifications)

```
src/
  components/
    interfaces/
      _doc_common.py        # NEW — shared protect/restore + StringSegment + ProgressCallback
      excel.py              # MODIFIED — re-imports from _doc_common (behavior unchanged)
      word.py               # NEW — pure Word XML helpers + translate_word orchestrator
      pdf.py                # NEW — pure PDF text helpers + sidecar writers + translate_pdf
      models.py             # MODIFIED — + WordTranslationReport, PdfTranslationReport
      commands/
        __init__.py         # MODIFIED — register word, pdf
        word.py             # NEW — word Typer subcommand
        pdf.py              # NEW — pdf  Typer subcommand
  config/
    models.py               # MODIFIED — + WordConfig, PdfConfig
    config.py               # MODIFIED — wire word: WordConfig, pdf: PdfConfig
tests/
  test_doc_common.py        # NEW — unit tests for the moved helpers
  test_word.py              # NEW — unit + integration + e2e
  test_pdf.py               # NEW — unit + integration + e2e
  fixtures/pdf/             # NEW — one small committed fixture + README
config.yaml                 # MODIFIED — + word:, pdf: sections
requirements.txt            # MODIFIED — + pypdf>=4.0,<5
pyproject.toml              # MODIFIED — + pypdf dep, + per-file-ignores
README.md                   # MODIFIED — document word & pdf commands
```

## Component dependency diagram (additions)

```
commands/word.py  ──▶  interfaces.word.translate_word   ──▶  orchestration.run_translation  (existing)
commands/pdf.py   ──▶  interfaces.pdf.translate_pdf     ──▶  orchestration.run_translation  (existing)

interfaces.word  ──▶  interfaces._doc_common (protect/restore, StringSegment, ProgressCallback)
interfaces.word  ──▶  stdlib (zipfile, xml.etree.ElementTree, defusedxml, re, threading, os)
interfaces.word  ──▶  src.config.AppConfig (WordConfig)
interfaces.word  ──▶  src.components.translation_pipeline.exceptions (domain errors)
interfaces.word  ──▶  src.components.interfaces.orchestration.run_translation
interfaces.word  ──▶  src.components.interfaces.models.WordTranslationReport
interfaces.word  ──▶  src.utils.zip_safe.validate_zip_path
interfaces.word  ──▶  src.utils.xml_escape.escape_xml_text

interfaces.pdf   ──▶  interfaces._doc_common (protect/restore, StringSegment, ProgressCallback)
interfaces.pdf   ──▶  pypdf (LAZY import inside extract_pdf_paragraphs only)
interfaces.pdf   ──▶  stdlib (zipfile, xml.etree.ElementTree, defusedxml, re, os)
interfaces.pdf   ──▶  src.config.AppConfig (PdfConfig)
interfaces.pdf   ──▶  src.components.translation_pipeline.exceptions (domain errors)
interfaces.pdf   ──▶  src.components.interfaces.orchestration.run_translation
interfaces.pdf   ──▶  src.components.interfaces.models.PdfTranslationReport
interfaces.pdf   ──▶  src.utils.xml_escape.escape_xml_text

interfaces.excel ──▶  interfaces._doc_common (re-imports; behavior unchanged)
```

The pure helpers (`extract_word_strings`, `patch_word_strings`,
`split_translation`, `extract_pdf_paragraphs`, `build_docx_from_paragraphs`,
`build_txt_from_paragraphs`, and the moved `protect_non_translatable` /
`restore_protected`) have **no** dependency on the pipeline or adapters —
they are pure functions on `bytes` / `str`. This keeps them unit-testable
without Ollama and respects the acyclic dependency graph (interfaces →
translation_pipeline, never the reverse).

## _doc_common.py module contents

Moved verbatim from `excel.py` (mechanical refactor; excel's existing
tests pin the behavior):

- `StringSegment` — frozen dataclass: `part: str` (zip part path or
  PDF page identifier), `text: str` (the source text). Used as the key
  for deduplication and translation mapping.
- `ProgressCallback` — `Protocol` with `__call__(self, completed: int, total: int, current: str) -> None`.
- `_SENTINEL_OPEN = "\x00T"`, `_SENTINEL_CLOSE = "\x00"`,
  `_SENTINEL_RE = re.compile(r"\x00T(\d+)\x00")` — control-character
  sentinels that never collide with real legal text and pass through
  local LLM tokenizers verbatim.
- `_PROTECTION_PATTERNS` — tuple of compiled regexes for URLs, emails,
  `${...}` / `{...}` / `<...>` / `%...%` placeholders, Excel
  header/footer `&`-codes, and standalone numbers.
- `protect_non_translatable(text) -> tuple[str, dict[str, str]]` —
  replace non-translatable tokens with stable sentinels; identical
  originals reuse the same sentinel.
- `restore_protected(text, token_map) -> str` — inverse; leftover
  sentinels not in `token_map` are removed (defensive against a model
  that drops a sentinel).

`excel.py` re-imports all of the above and keeps them in `__all__` so
existing callers (`from src.components.interfaces.excel import
protect_non_translatable`) keep working.

## word.py module contents

### Namespace handling

Register the WordprocessingML namespace with `ElementTree.register_namespace`:
- `http://schemas.openxmlformats.org/wordprocessingml/2006/main` → `w`

Tag constants:
- `_W_T = "{...}t"`, `_W_P = "{...}p"`, `_W_R = "{...}r"`,
  `_W_BR = "{...}br"`, `_W_BIDI = "{...}bidiVisual"`,
  `_W_PPR = "{...}pPr"`, `_W_RPR = "{...}rPr"`.

### Pure XML helpers (no pipeline dependency)

- `_is_word_text_part(name, cfg) -> bool` — allowlist:
  - `word/document.xml` (always)
  - `word/headerN.xml`, `word/footerN.xml` (when
    `cfg.word.translate_headers_footers`)
  - `word/footnotes.xml` (when `cfg.word.translate_footnotes`)
  - `word/endnotes.xml` (when `cfg.word.translate_endnotes`)
  - `word/comments.xml` (when `cfg.word.translate_comments`)
  - `word/glossary/document.xml` (only when
    `cfg.word.translate_glossary_doc` — default `False`, rare)
- `_paragraph_text(p_el) -> tuple[str, list[int]]` — walk `w:t`
  children of `w:r` children of `w:p` in document order, concatenate
  text, return `(text, run_lengths)` where `run_lengths[i]` is the char
  length of the i-th run's text. Insert a space between runs when the
  previous run's text does not end in whitespace AND the next does not
  start with whitespace (per OOXML spacing rules); count that space as
  belonging to the second run.
- `extract_word_strings(docx_bytes, *, cfg) -> list[StringSegment]` —
  open the zip, validate every entry name via
  `src.utils.zip_safe.validate_zip_path`, parse each allowlisted part
  with `defusedxml.ElementTree.fromstring`, for each `w:p` collect
  `_paragraph_text`; dedupe by concatenated text; skip empty /
  whitespace-only paragraphs; record `StringSegment(part=name,
  text=text)`. Does NOT apply the `max_segment_chars` filter (that is
  the orchestrator's policy, mirroring the excel helper).
- `split_translation(translation, run_lengths) -> list[str]` —
  proportionally split `translation` into `len(run_lengths)` chunks by
  character count. If `sum(run_lengths) == 0`, distribute evenly. Never
  return empty chunks for non-empty input — distribute any remainder to
  the last run.
- `patch_word_strings(docx_bytes, translations, *, cfg) -> bytes` —
  re-open the zip, write a new zip copying every part byte-for-byte
  except the allowlisted parts, which are re-serialized: for each
  `w:p`, re-walk the `w:t` runs in order, look up the paragraph's
  concatenated text in `translations`, and if found, `split_translation`
  the result across the runs by their original lengths, escaping each
  chunk with `src.utils.xml_escape.escape_xml_text` before assigning to
  `el.text`. Re-serialize with `ET.tostring(root, encoding="UTF-8",
  xml_declaration=True)`. Validate every zip entry name via
  `validate_zip_path`.

### Orchestrator (DI, reuses run_translation)

`translate_word(input_path, output_path, direction, cfg, *, llm,
embedder, glossary_index=None, persist_dir=None, run_logger=None,
tm=None, progress=None, cancel_event=None) ->
src.components.interfaces.models.WordTranslationReport`:

1. `input_p.stat().st_size > cfg.word.max_docx_bytes` → raise
   `InputValidationError`.
2. Read `docx_bytes` from `input_path`.
3. `segments = extract_word_strings(docx_bytes, cfg=cfg)`.
4. `len(segments) > cfg.word.max_segments` → raise
   `InputValidationError`.
5. Loop segments with concurrency = 1 (RAM rule); per segment:
   - check `cancel_event` (set `cancelled=True`, record skipped count,
     break);
   - `len(source) > cfg.word.max_segment_chars` → skip + warn + record;
   - resolve `auto` direction via
     `orchestration.detect_direction(source)`;
   - protect non-translatable tokens via
     `_doc_common.protect_non_translatable`;
   - call `orchestration.run_translation(protected, effective_direction,
     cfg, llm=..., embedder=..., glossary_index=..., persist_dir=...,
     run_logger=..., tm=...)`;
   - restore tokens via `_doc_common.restore_protected`;
   - on `LLMRuntimeError` / `EmbeddingError` → record `failed += 1` +
     warning; original text preserved;
   - on success → `translations[source] = restored`, `translated += 1`;
   - report progress.
6. `out_bytes = patch_word_strings(docx_bytes, translations, cfg=cfg)`.
7. Atomic write: `tmp_path = output_p.with_suffix(output_p.suffix +
   ".tmp")`; write; `os.replace(tmp_path, output_p)`.
8. Return `WordTranslationReport(total_segments=len(segments),
   translated=..., skipped=..., failed=..., cancelled=...,
   warnings=...)`.

The `_translate_segment` helper is shared with `excel.py` — it is
generalized into `_doc_common.py` (it already operates on a
`StringSegment` + `run_translation` seam with no excel-specific logic)
so both `excel.py` and `word.py` import it. This is DRY and keeps the
orchestrators thin.

## pdf.py module contents

### Pure PDF text helpers (no pipeline dependency; `pypdf` lazy-imported)

- `extract_pdf_paragraphs(pdf_path, *, cfg) -> tuple[list[list[str]],
  list[str]]` — lazy-import `pypdf.PdfReader` inside the function;
  iterate `reader.pages`; for each page call `page.extract_text()`;
  if empty → record a warning `"Page N: no extractable text (scanned
  PDF?)."` and append an empty list; else `_segment_page(raw, cfg=cfg)`.
  Returns `(pages, warnings)` where `pages[i]` is the list of paragraph
  strings on page `i+1`.
- `_segment_page(text, *, cfg) -> list[str]` — split on `\n\s*\n`;
  for each block, collapse internal newlines to spaces; if
  `cfg.pdf.skip_header_footer`, drop the first and last block when
  they are short (< 60 chars) and contain only digits / roman numerals
  / single words; skip empty blocks and blocks that are pure numbers
  (page numbers).

### Sidecar writers (pure, stdlib only)

- `build_docx_from_paragraphs(pages, *, rtl: bool) -> bytes` — build a
  minimal `.docx` zip with `[Content_Types].xml`, `_rels/.rels`,
  `word/_rels/document.xml.rels`, `word/document.xml`. For each page,
  emit each paragraph as `<w:p><w:pPr><w:bidiVisual/></w:pPr><w:r><w:t
  xml:space="preserve">{escaped}</w:t></w:r></w:p>` (the `w:bidiVisual`
  element only when `rtl=True`, i.e. when `direction == "ar-en"`); between
  pages emit a page break `<w:p><w:r><w:br w:type="page"/></w:r></w:p>`.
  Escape every paragraph via `escape_xml_text`.
- `build_txt_from_paragraphs(pages) -> str` — join paragraphs with
  `\n\n`; join pages with `\n\n--- page break ---\n\n`.

### Orchestrator (DI, reuses run_translation)

`translate_pdf(input_path, output_path, direction, cfg, *, llm,
embedder, glossary_index=None, persist_dir=None, run_logger=None,
tm=None, progress=None, cancel_event=None) ->
src.components.interfaces.models.PdfTranslationReport`:

1. `input_p.stat().st_size > cfg.pdf.max_pdf_bytes` → raise
   `InputValidationError`.
2. `pages, extract_warnings = extract_pdf_paragraphs(input_path,
   cfg=cfg)`.
3. `len(pages) > cfg.pdf.max_pages` → raise `InputValidationError`.
4. Flatten + dedupe paragraphs across all pages into `segments:
   list[StringSegment]` (dedupe by text; first-seen order).
5. `len(segments) > cfg.pdf.max_segments` → raise
   `InputValidationError`.
6. Loop segments (concurrency = 1), same pattern as `translate_word`:
   cancel check, `max_chars` skip, `auto` direction, protect →
   `run_translation` → restore, record counts.
7. Re-assemble `translated_pages` by replacing each page's paragraphs
   with their translations (lookup by original text; untranslated →
   original).
8. Branch on `cfg.pdf.out_format`:
   - `"docx"` → `build_docx_from_paragraphs(translated_pages,
     rtl=(direction == "ar-en"))`;
   - `"txt"` → `build_txt_from_paragraphs(translated_pages)`.
9. Atomic write to `output_path`.
10. Return `PdfTranslationReport(total_pages=len(pages),
    total_segments=len(segments), translated=..., skipped=...,
    failed=..., cancelled=..., warnings=extract_warnings +
    translation_warnings)`.

## AppConfig wiring

`src/config/models.py`:

```python
class WordConfig(BaseModel):
    translate_comments: bool = True
    translate_headers_footers: bool = True
    translate_footnotes: bool = True
    translate_endnotes: bool = True
    translate_glossary_doc: bool = False
    max_segment_chars: int = 8192
    max_docx_bytes: int = 50 * 1024 * 1024   # 50 MiB
    max_segments: int = 20000
    # field validators: max_segment_chars >= 16, max_docx_bytes >= 1 MiB,
    # max_segments >= 100


class PdfConfig(BaseModel):
    out_format: Literal["docx", "txt"] = "docx"
    max_pdf_bytes: int = 100 * 1024 * 1024   # 100 MiB
    max_pages: int = 500
    max_segment_chars: int = 8192
    max_segments: int = 20000
    skip_header_footer: bool = True
    # field validators: max_pdf_bytes >= 1 MiB; positive-int for the rest
```

`src/config/config.py`: add to `AppConfig`:
```python
    word: WordConfig = Field(default_factory=WordConfig)
    pdf:  PdfConfig  = Field(default_factory=PdfConfig)
```

## config.yaml addition

```yaml
# --- Word (.docx) document translation ---
word:
  translate_comments: true
  translate_headers_footers: true
  translate_footnotes: true
  translate_endnotes: true
  translate_glossary_doc: false
  max_segment_chars: 8192
  max_docx_bytes: 52428800    # 50 MiB
  max_segments: 20000

# --- PDF (.pdf) document translation (sidecar output) ---
pdf:
  out_format: docx            # docx | txt
  max_pdf_bytes: 104857600    # 100 MiB
  max_pages: 500
  max_segment_chars: 8192
  max_segments: 20000
  skip_header_footer: true
```

## CLI commands

`commands/word.py` and `commands/pdf.py` mirror `commands/excel.py`
exactly, swapping `excel`→`word`/`pdf`, `.xlsx`→`.docx`/`.pdf`,
`translate_excel`→`translate_word`/`translate_pdf`,
`ExcelTranslationReport`→`WordTranslationReport`/`PdfTranslationReport`.
Both validate the input suffix, construct adapters via the existing
`_construct_adapters(cfg)`, run inside `_new_run_logger(cfg)`, print the
report, and close TM in `finally`. Both are decorated with
`@handle_pipeline_errors` so domain exceptions map to the same exit
codes as `excel` (connection → 2, RAM guard → 3, other → 1, path
containment → 4).

```python
@_cli.app.command()
@handle_pipeline_errors
def word(
    input_arg: Annotated[Path, typer.Option("--input", help="Path to input .docx.")],
    out: Annotated[Path, typer.Option("--out", help="Path to output .docx.")],
    direction: Annotated[Direction, typer.Option("--direction", ...)],
    config_path: Annotated[Path, typer.Option("--config", "-c", ...)] = _cli._DEFAULT_CONFIG,
) -> None: ...

@_cli.app.command()
@handle_pipeline_errors
def pdf(
    input_arg: Annotated[Path, typer.Option("--input", help="Path to input .pdf.")],
    out: Annotated[Path, typer.Option("--out", help="Path to output .docx or .txt.")],
    direction: Annotated[Direction, typer.Option("--direction", ...)],
    config_path: Annotated[Path, typer.Option("--config", "-c", ...)] = _cli._DEFAULT_CONFIG,
) -> None: ...
```

## pyproject.toml change

Add `pypdf>=4.0,<5` to `[project] dependencies`. Add to
`[tool.ruff.lint.per-file-ignores]`:
```toml
# translate_word / translate_pdf take one arg per injected dependency
# (DIP, engineering-principles §1.5) — mirrors excel.py.
"src/components/interfaces/word.py" = ["PLR0913"]
"src/components/interfaces/pdf.py"  = ["PLR0913"]
```

## Migration strategy

Purely additive. Order (one verifiable step per task — see `tasks.md`):

1. **OpenSpec change** (this proposal + design + delta specs + tasks;
   validate before any code).
2. **`_doc_common.py` extraction** — move four symbols out of
   `excel.py`; re-import in `excel.py`; run `tests/test_excel.py` to
   confirm no regression.
3. **`WordConfig` + `PdfConfig`** — add the Pydantic models; wire into
   `AppConfig`; add `config.yaml` sections.
4. **`WordTranslationReport` + `PdfTranslationReport`** — add the DTOs.
5. **Word pure XML helpers** — `extract_word_strings`,
   `patch_word_strings`, `split_translation`; unit tests.
6. **Word orchestrator** — `translate_word`; integration tests with
   mock adapters.
7. **`word` CLI command** — register; CliRunner test; `--help` smoke.
8. **PDF pure helpers + sidecar writers** — add `pypdf` dep;
   `extract_pdf_paragraphs`, `_segment_page`,
   `build_docx_from_paragraphs`, `build_txt_from_paragraphs`; unit
   tests.
9. **PDF orchestrator + `pdf` CLI command** — `translate_pdf`; register;
   integration + CliRunner tests.
10. **Documentation + final verification + OpenSpec archive** — update
    `README.md`; run `pytest`, `ruff`, `mypy`, `openspec validate --all`;
    `openspec archive add-pdf-word-translation`.

Each task ends with an independently verifiable deliverable (test run,
lint, or `--help` smoke). The dependency graph stays satisfiable at
every step: foundation (`_doc_common`, config, DTOs) first, helpers
before orchestrators, orchestrators before CLI commands, documentation
last.

## Rollback

Revert the commits. No data files, `db/`, or `data/` directories are
touched. The feature is isolated to new files plus small additive edits.
The `_doc_common.py` extraction can be reverted independently of the
`word`/`pdf` features — `excel.py` works either way because the
re-export is preserved.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Run-splitting distorts translated text when formatting splits mid-word | Detect mid-word splits (no whitespace boundary) and treat the paragraph as a single run for translation; only proportional-split when runs end at word boundaries. Unit-test the splitter with fixtures. |
| `pypdf` extraction quality on complex PDFs (multi-column, scanned) | Document the limitation in the spec scenario; `PdfTranslationReport.warnings` records pages where extraction yielded < 10 chars; recommend a future OCR change for scanned PDFs. |
| Large PDFs blow the RAM budget | Enforce `max_pdf_bytes` (100 MiB) and `max_pages` (500) up front; stream pages one at a time; `pypdf.PdfReader` lazily reads pages. |
| `protect_non_translatable` refactor breaks excel | Mechanical move to `_doc_common.py`; excel's existing tests pin behavior; run full `tests/test_excel.py` after the move. |
| Arabic RTL paragraph direction in generated `.docx` | Set `w:bidiVisual` on the paragraph properties for `ar-en` output; unit-test the generated XML asserts the attribute. |
| `pypdf` is the first new runtime dep since `google-genai` | Pin `pypdf>=4.0,<5`; verify the published version is ≥ 7 days old at install time (project rule); lazy-import inside `pdf.py` so other code paths never import it. |

## Decisions

- **D1 — Word in-place, PDF sidecar.** Word is OOXML (zip of XML parts)
  and can be patched byte-for-byte like Excel. PDF is positioned glyphs
  and cannot be cleanly rewritten in place without Arabic-font/reshaping
  complexity; a translated `.docx` sidecar is the pragmatic, lossless-
  content output. See §Approach in `proposal.md`.
- **D2 — Separate `word` and `pdf` commands.** Matches the existing
  one-command-per-format `excel` pattern; simpler specs; clearer
  `--help`; one failure mode per command.
- **D3 — Shared `_doc_common.py`.** `protect_non_translatable`,
  `restore_protected`, `StringSegment`, `ProgressCallback`, and the
  `_translate_segment` helper are not Excel-specific. Moving them to a
  shared module is DRY and makes the Word/PDF adapters thin. The move
  is mechanical and pinned by excel's existing tests.
- **D4 — `pypdf` lazy-imported.** The `word`, `excel`, `translate`,
  `batch`, and `ui` code paths never import `pypdf`. This mirrors the
  `google-genai` lazy-import pattern and keeps the offline-first
  guarantee intact for users who only use the Word/Excel commands.
- **D5 — Paragraph-aware Word extraction.** Word runs (`w:t`) split a
  sentence across multiple runs due to formatting. Translating per-run
  would break legal meaning. We concatenate runs per `w:p`, translate
  the whole paragraph, then `split_translation` the result
  proportionally back across the original runs — preserving run-level
  formatting while translating whole semantic units.
- **D6 — `out_format: docx | txt`.** `.docx` is the default (editable,
  preserves page boundaries, reuses the OOXML writer). `.txt` is
  offered for users who want the simplest possible output. No other
  formats (`.rtf`, `.html`) — YAGNI.
