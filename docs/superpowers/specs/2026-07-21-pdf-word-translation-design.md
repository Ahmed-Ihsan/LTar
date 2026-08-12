# PDF & Word Document Translation — Design

> Status: **Draft for review** — no code written yet.
> Author: Devin (planning session 20260720-234306)
> Related: `openspec/changes/archive/2026-07-18-add-excel-translation/` (the
> template this design mirrors), `openspec/specs/interfaces/spec.md`
> (Requirement: Excel translation command/orchestration/XML helpers).

## 1. Goal

Add two new CLI subcommands — `word` and `pdf` — that translate Iraqi legal
documents end-to-end through the existing Translator → Auditor → Revise
pipeline, reusing the same adapters, glossary, TM, and HITL seam as the
`excel` command. The feature is **purely additive**: no existing behavior,
spec, or import path changes.

## 2. Scope

**In scope:**
- `word` command: in-place translation of `.docx` (WordprocessingML OOXML)
  preserving styles, tables, images, headers/footers, footnotes, comments,
  hyperlinks, tracked changes, and every non-text artifact byte-for-byte.
- `pdf` command: text extraction from `.pdf` → per-paragraph translation →
  written as a translated `.docx` sidecar (editable, preserves reading order
  and page breaks; does **not** rewrite the original PDF).
- `auto` direction (per-segment script-dominance detection) reused from
  `orchestration.detect_direction`.
- New `WordConfig` and `PdfConfig` Pydantic sub-models wired into `AppConfig`.
- New `WordTranslationReport` and `PdfTranslationReport` DTOs.
- OpenSpec change proposal `add-pdf-word-translation` with delta specs,
  design, and ordered tasks.
- Full test coverage: unit (pure helpers), integration (mock adapters),
  e2e round-trip fixtures.

**Out of scope (YAGNI):**
- In-place PDF rewrite (lossy layout, Arabic font/reshaping complexity —
  explicitly rejected; see §5).
- Legacy `.doc` (binary) and `.pptx` support.
- OCR of scanned PDFs (would require `tesseract` + an Arabic language pack;
  deferred to a future change).
- Translation of embedded objects (OLE, ActiveX) inside `.docx`.
- A unified `document` command (separate commands match the existing
  one-command-per-format `excel` pattern; see §4).

## 3. Architecture

The design mirrors the proven `excel` adapter (verified in
`src/components/interfaces/excel.py`):

```
commands/word.py  ──▶  interfaces/word.py  ──▶  orchestration.run_translation
commands/pdf.py   ──▶  interfaces/pdf.py   ──▶  orchestration.run_translation
                                              (existing seam, unchanged)
```

Each new adapter splits into:
- **Pure helpers** (no pipeline dependency, unit-testable without Ollama):
  extraction + patching/writing operating on file bytes.
- **Orchestrator** (`translate_word` / `translate_pdf`): dedup segments,
  loop with concurrency = 1 (RAM rule), call `run_translation` per unique
  source string, protect/restore non-translatable tokens, write output
  atomically, return a report DTO.

This respects the acyclic component dependency graph
(`interfaces → translation_pipeline`, never the reverse) and the DIP
keyword-only-args convention.

### 3.1 Word adapter (`src/components/interfaces/word.py`)

A `.docx` is a ZIP of OOXML parts. Text-bearing locations (allowlist):

| Part | Element | Toggle |
|---|---|---|
| `word/document.xml` | `w:t` runs in `w:p` paragraphs (body + tables) | always |
| `word/headerN.xml`, `word/footerN.xml` | `w:t` runs | `translate_headers_footers` |
| `word/footnotes.xml`, `word/endnotes.xml` | `w:t` runs | `translate_footnotes` |
| `word/comments.xml` | `w:t` runs | `translate_comments` |
| `word/glossary/document.xml` (glossary doc parts) | `w:t` runs | `translate_glossary_doc` (default false — rare) |

Non-text artifacts preserved byte-for-byte: styles (`word/styles.xml`),
themes, fonts, numbering, settings, embedded images, drawings, shapes,
hyperlink relationships, tracked-change metadata (`w:ins`/`w:del` wrappers
are kept; only their inner `w:t` text is translated), tables, sections,
custom XML parts.

**Paragraph-aware extraction:** unlike Excel cells, Word runs (`w:t`) split
a sentence across multiple runs due to formatting. To translate whole
sentences (required for legal meaning) we extract at the **paragraph**
level: concatenate all `w:t` text within a `w:p` (inserting a space when
the previous run ends without whitespace, per OOXML's `xml:space="preserve"`
rules), translate the concatenated paragraph, then **re-split** the
translation back across the original runs proportionally by character
count. This preserves run-level formatting (bold mid-sentence, etc.) while
translating whole semantic units. A `split_translation` helper handles the
proportional re-split; if a paragraph has a single run, no split is needed.

**Reuse:** `protect_non_translatable` / `restore_protected` from
`excel.py` are generalized — extracted to a new
`src/components/interfaces/_doc_common.py` module shared by `excel.py`,
`word.py`, and `pdf.py`. This is a **safe refactor**: the functions are
pure, the excel tests pin their behavior, and the move is mechanical
(import-path change only). `excel.py` re-imports them from the new module.

### 3.2 PDF adapter (`src/components/interfaces/pdf.py`)

PDFs are positioned-glyph streams, not editable OOXML. In-place rewrite is
rejected (§5). Instead:

1. **Extract** text per page using `pypdf.PdfReader` (new lightweight
   pure-Python dep, ~1 MB, offline, no native deps). `page.extract_text()`
   returns the page's text in reading order for most Iraqi legal PDFs
   (single-column, structured).
2. **Segment** into paragraphs: split on blank-line boundaries (`\n\s*\n`)
   and merge orphaned single lines. Skip pure-numeric lines, page numbers,
   and headers/footers (heuristic: short lines at top/bottom of page with
   only digits / roman numerals).
3. **Dedup + translate** each unique paragraph via `run_translation`
   (concurrency = 1, RAM rule).
4. **Write** a translated `.docx` sidecar using stdlib `zipfile` +
   `xml.etree.ElementTree` (the same OOXML writer approach as the Word
   adapter's patcher, but generating a minimal `word/document.xml` from
   scratch). One `w:p` per translated paragraph, with a page-break
   `w:br w:type="page"` between original pages. No styles complexity —
   plain body text, RTL paragraph direction for `ar-en` output, LTR for
   `en-ar`.

**Why `.docx` sidecar (not `.txt`):** preserves page boundaries, gives the
user an editable artifact they can re-style, and reuses the OOXML writer
we're already building for the Word adapter. A `--pdf-out-format txt|docx`
option lets users pick `.txt` if they want the simplest output.

**New dependency:** `pypdf>=4.0,<5` added to `requirements.txt` and
`pyproject.toml`. It is pure Python, MIT-licensed, offline, and ~1 MB —
fits the 8 GB RAM profile and the no-telemetry/no-cloud constraints. It is
imported lazily inside `pdf.py` so the `word`/`excel` paths never import
it.

### 3.3 Config

New Pydantic sub-models in `src/config/models.py`:

```python
class WordConfig(BaseModel):
    translate_comments: bool = True
    translate_headers_footers: bool = True
    translate_footnotes: bool = True
    translate_endnotes: bool = True
    translate_glossary_doc: bool = False
    max_segment_chars: int = 8192        # paragraphs longer than this are split or skipped
    max_docx_bytes: int = 50 * 1024 * 1024   # 50 MiB
    max_segments: int = 20000

class PdfConfig(BaseModel):
    out_format: Literal["docx", "txt"] = "docx"
    max_pdf_bytes: int = 100 * 1024 * 1024   # 100 MiB
    max_pages: int = 500
    max_segment_chars: int = 8192
    max_segments: int = 20000
    skip_header_footer: bool = True
```

Wired into `AppConfig` as `word: WordConfig` and `pdf: PdfConfig`
(additive — defaults apply when sections absent, so existing `config.yaml`
files keep working).

### 3.4 Report DTOs

In `src/components/interfaces/models.py` (mirroring
`ExcelTranslationReport`):

```python
@dataclass(slots=True, frozen=True)
class WordTranslationReport:
    total_segments: int
    translated: int
    skipped: int
    failed: int
    cancelled: bool
    warnings: list[str]

@dataclass(slots=True, frozen=True)
class PdfTranslationReport:
    total_pages: int
    total_segments: int
    translated: int
    skipped: int
    failed: int
    cancelled: bool
    warnings: list[str]
```

### 3.5 CLI commands

Two new modules under `src/components/interfaces/commands/`, registered in
`commands/__init__.py`:

- `word --input <path> --out <path> --direction <ar-en|en-ar|auto> [--config <path>]`
- `pdf  --input <path> --out <path> --direction <ar-en|en-ar|auto> [--config <path>]`

Both mirror `commands/excel.py` exactly: validate input exists + suffix,
load config, validate path containment, construct adapters via
`_construct_adapters`, run inside `_new_run_logger`, print the report,
close TM in `finally`. Decorated with `@handle_pipeline_errors` for
consistent exit codes (connection → 2, RAM guard → 3, other → 1, path
containment → 4).

### 3.6 Security (carried over from the excel spec)

- All OOXML parsing uses `defusedxml.ElementTree.fromstring` (XXE defense).
- All zip entry names validated via `src.utils.zip_safe.validate_zip_path`
  (zip-slip defense).
- All translated text inserted into XML via
  `src.utils.xml_escape.escape_xml_text` (so LLM output containing `</w:t>`
  or `<script>` cannot corrupt the document).
- `--input` / `--out` validated via `validate_path_in_root` (path
  containment, exit code 4).
- `pypdf` is read-only on the input PDF; no network calls.

## 4. Alternatives Considered

### Word
1. **`python-docx`** — pure-Python lib. New dep; `Document()` loads the
   whole package into memory; known fidelity gaps on tracked changes,
   complex tables, and custom XML parts. Rejected for the same reasons
   openpyxl was rejected for Excel.
2. **Direct XML (stdlib)** — chosen. Max fidelity, no deps, memory-efficient
   per-part processing. Identical to the proven Excel approach.

### PDF
1. **In-place PDF rewrite (`reportlab`/`fpdf2`)** — generates a new PDF
   with translated text. Rejected: re-flowing Arabic text into positioned
   PDF glyphs requires an Arabic reshaper (`arabic-reshaper` + `python-bidi`)
   and per-font metrics; layout (tables, columns, stamps) is lost anyway;
   heavy deps. YAGNI for this change.
2. **`pdfplumber` extraction + `.docx` sidecar** — `pdfplumber` depends on
   `pdfminer.six` (heavier, ~5 MB, slower). `pypdf` is lighter and
   sufficient for single-column legal text. Chosen: `pypdf`.
3. **`pymupdf` (fitz)** — fastest, best extraction quality, but AGPL-licensed
   (incompatible with the project's MIT license) and has a native binary.
   Rejected on licensing grounds.

### Command shape
1. **Separate `word` + `pdf`** — chosen. Matches the `excel` pattern;
   simpler specs; clearer `--help`; one failure mode per command.
2. **Unified `document`** — dispatches on extension. Fewer commands but
   more branching logic, a bigger spec, and mixed error semantics. Rejected.

## 5. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Run-splitting distorts translated text when formatting splits mid-word | Detect mid-word splits (no whitespace boundary) and treat the paragraph as a single run for translation; only proportional-split when runs end at word boundaries. Unit-test the splitter with fixtures. |
| `pypdf` extraction quality on complex PDFs (multi-column, scanned) | Document the limitation in the spec scenario; `PdfTranslationReport.warnings` records pages where extraction yielded <10 chars; recommend OCR change for scanned PDFs. |
| Large PDFs blow the RAM budget | Enforce `max_pdf_bytes` (100 MiB) and `max_pages` (500) up front; stream pages one at a time; `pypdf` `PdfReader` lazily reads pages. |
| `protect_non_translatable` refactor breaks excel | Mechanical move to `_doc_common.py`; excel's existing tests pin behavior; run full `tests/test_excel.py` after the move. |
| Arabic RTL paragraph direction in generated `.docx` | Set `w:bidiVisual` on the paragraph properties for `ar-en` output; unit-test the generated XML asserts the attribute. |

## 6. OpenSpec Change

Per AGENTS.md §6, a change proposal is required. The plan creates:

```
openspec/changes/add-pdf-word-translation/
├── proposal.md          # Why, what changes, capabilities, impact, rollback
├── design.md            # This design doc, adapted to OpenSpec format
├── tasks.md             # Ordered task list (checkboxes)
└── specs/
    ├── interfaces/spec.md   # ADDED: word & pdf command/orchestration/helper requirements
    └── config/spec.md       # ADDED: WordConfig, PdfConfig requirements
```

Validated with `openspec validate add-pdf-word-translation` before any
implementation; archived with `openspec archive add-pdf-word-translation`
after the tasks complete and `openspec validate --all` passes.

## 7. Verification Plan

- `pytest tests/test_word.py tests/test_pdf.py -v` — new tests pass.
- `pytest --tb=short -q` — full suite still green (no regressions,
  especially `tests/test_excel.py` after the `_doc_common.py` move).
- `ruff check src/ tests/` — clean.
- `mypy src/` — strict, zero errors.
- `openspec validate --all` — all specs + the new change pass.
- Manual smoke: `python -m src.app word --input sample.docx --out out.docx --direction ar-en`
  and `python -m src.app pdf --input sample.pdf --out out.docx --direction ar-en`
  on a small Iraqi legal fixture.
