## Why

The agent translates single sentences, JSONL batches, and — since the
`add-excel-translation` change — `.xlsx` workbooks in place. Iraqi legal
work, however, is delivered most often as **Word documents** (statutes,
contracts, ministerial decrees, court judgments) and increasingly as
**PDFs** (official-gazette scans, exported court PDFs, ministry portals).
Translating these today means manually copying paragraphs out and back,
losing all formatting, breaking footnote/comment structure, and — for PDFs
— fighting positioned-glyph layout that no stdlib tool can rewrite cleanly.

A first-class `word` command that translates `.docx` **in place**
(preserving styles, tables, images, headers/footers, footnotes, comments,
hyperlinks, tracked changes byte-for-byte) and a `pdf` command that
extracts text per page and writes a translated **sidecar** `.docx` (or
`.txt`) close that gap. Both reuse the existing Translator → Auditor →
Revise pipeline via the proven `run_translation` seam — no pipeline,
prompt, glossary, TM, or node changes.

This change is **purely additive**: no existing behavior, spec
requirement, or import path changes. It mirrors the archived
`add-excel-translation` change (the template for document-translation
adapters in this codebase).

## Scope

### In scope

- `word` CLI subcommand: in-place `.docx` translation via a new
  `src/components/interfaces/word.py` adapter (pure OOXML XML helpers +
  `translate_word` orchestrator). Preserves every non-text artifact
  byte-for-byte; translates `w:t` runs in `word/document.xml`, headers,
  footers, footnotes, endnotes, comments (gated by `cfg.word.translate_*`
  toggles).
- `pdf` CLI subcommand: `.pdf` text extraction (via a new lightweight
  pure-Python `pypdf>=4.0,<5` dependency, lazy-imported) → per-paragraph
  translation → sidecar `.docx` (default) or `.txt` writer. Does **not**
  rewrite the original PDF.
- New `WordConfig` and `PdfConfig` Pydantic sub-models wired into
  `AppConfig` as `word: WordConfig` and `pdf: PdfConfig` (additive —
  defaults apply when sections absent).
- New `WordTranslationReport` and `PdfTranslationReport` frozen dataclass
  DTOs in `src/components/interfaces/models.py`.
- Safe refactor: extract the existing `protect_non_translatable` /
  `restore_protected` / `StringSegment` / `ProgressCallback` helpers from
  `excel.py` into a new shared `src/components/interfaces/_doc_common.py`
  module so `excel.py`, `word.py`, and `pdf.py` all reuse them. The
  excel behavior and public re-exports are unchanged.
- `auto` direction (per-segment script-dominance detection) reused from
  `orchestration.detect_direction`.
- OpenSpec delta specs for the `interfaces` and `config` capabilities.
- Full test coverage: unit (pure helpers), integration (mock adapters),
  e2e round-trip fixtures (programmatically-built `.docx`; a single small
  committed `.pdf` fixture with documented provenance).

### Out of scope

- In-place PDF rewrite (lossy layout, Arabic font/reshaping complexity —
  explicitly rejected; see `design.md` §Alternatives).
- Legacy `.doc` (binary OLE) and `.pptx` support.
- OCR of scanned PDFs (would require `tesseract` + an Arabic language
  pack; deferred to a future change).
- Translation of embedded OLE/ActiveX objects inside `.docx`.
- A unified `document` command (separate `word`/`pdf` commands match the
  existing one-command-per-format `excel` pattern; see `design.md`
  §Alternatives).
- Any change to the LangGraph state machine, nodes, prompts, glossary,
  TM, retrieval, or existing CLI commands.

## What Changes

- **ADDED:** `src/components/interfaces/_doc_common.py` — shared
  `protect_non_translatable`, `restore_protected`, sentinel constants
  (`_SENTINEL_OPEN`/`_SENTINEL_CLOSE`/`_SENTINEL_RE`),
  `_PROTECTION_PATTERNS`, `StringSegment` dataclass, `ProgressCallback`
  protocol. Moved verbatim out of `excel.py`.
- **MODIFIED:** `src/components/interfaces/excel.py` — re-imports the
  moved symbols from `_doc_common`; keeps them in `__all__` for backward
  compatibility. Behavior unchanged.
- **ADDED:** `src/components/interfaces/word.py` — pure Word XML helpers
  (`extract_word_strings`, `patch_word_strings`, `split_translation`) +
  `translate_word` orchestrator. Stdlib only (`zipfile`,
  `xml.etree.ElementTree`, `defusedxml`, `re`).
- **ADDED:** `src/components/interfaces/pdf.py` — pure PDF text helpers
  (`extract_pdf_paragraphs`, `_segment_page`) + sidecar writers
  (`build_docx_from_paragraphs`, `build_txt_from_paragraphs`) +
  `translate_pdf` orchestrator. Lazy-imports `pypdf` inside the
  extractor so the `word`/`excel` paths never import it.
- **ADDED:** `src/components/interfaces/commands/word.py` — `word` Typer
  subcommand mirroring `commands/excel.py`.
- **ADDED:** `src/components/interfaces/commands/pdf.py` — `pdf` Typer
  subcommand mirroring `commands/excel.py`.
- **MODIFIED:** `src/components/interfaces/commands/__init__.py` —
  register `word` and `pdf` in the import list.
- **MODIFIED:** `src/components/interfaces/models.py` — add
  `WordTranslationReport` and `PdfTranslationReport` frozen dataclasses.
- **ADDED:** `src/config/models.py` — `WordConfig` and `PdfConfig`
  Pydantic sub-models.
- **MODIFIED:** `src/config/config.py` — wire `word: WordConfig` and
  `pdf: PdfConfig` into `AppConfig` with `default_factory`.
- **MODIFIED:** `config.yaml` — new `word:` and `pdf:` sections with
  documented defaults.
- **MODIFIED:** `requirements.txt` — add `pypdf>=4.0,<5` (pure-Python,
  MIT-licensed, offline, ~1 MB; lazy-imported inside `pdf.py`).
- **MODIFIED:** `pyproject.toml` — add `pypdf>=4.0,<5` to
  `[project] dependencies` and add ruff per-file-ignores (`PLR0913`) for
  `src/components/interfaces/word.py` and `src/components/interfaces/pdf.py`
  (mirrors the existing `excel.py` ignore — the orchestrators take one
  arg per injected dependency per DIP).
- **ADDED:** `tests/test_doc_common.py` — unit tests for the moved
  helpers (re-asserts the excel behavior pins).
- **ADDED:** `tests/test_word.py` — unit tests for the pure XML helpers,
  integration tests for `translate_word` with `mock_llm`/`mock_embedder`,
  and an e2e round-trip fixture asserting non-text artifacts are
  preserved byte-for-byte.
- **ADDED:** `tests/test_pdf.py` — unit tests for the sidecar writers,
  integration tests for `translate_pdf` with mock adapters, and an e2e
  test over a small committed fixture.
- **ADDED:** `tests/fixtures/pdf/` — a single small (≤ 50 KB) 2-page
  Arabic legal PDF fixture plus a `README.md` documenting its
  provenance. (Word fixtures are generated programmatically by the
  tests — no binary committed.)
- **MODIFIED:** `README.md` — document `word` and `pdf` in §2.5 (run.bat
  menu if applicable) and §6.6 (CLI reference); note that PDF
  translation produces a sidecar (does not rewrite the original) and
  scanned PDFs need OCR first.
- No changes to the LangGraph state machine, nodes, prompts, glossary,
  TM, retrieval, or any existing command. The feature is purely
  additive and reuses `run_translation` unchanged.

## Capabilities

### New Capabilities

- `word_translation` (documented under `interfaces`): Word document
  translation that preserves document structure and routes
  human-readable text through the translation pipeline.
- `pdf_translation` (documented under `interfaces`): PDF document
  translation that extracts text per page, translates it, and writes a
  sidecar `.docx` or `.txt`.

### Modified Capabilities

- `interfaces`: ADDED `word` and `pdf` CLI subcommands; ADDED the
  `translate_word` and `translate_pdf` orchestration seams; ADDED the
  pure Word XML helpers and pure PDF text helpers + sidecar writers;
  ADDED `WordTranslationReport` and `PdfTranslationReport` models;
  MODIFIED `excel.py` to re-import shared helpers from `_doc_common`
  (behavior unchanged).
- `config`: ADDED `WordConfig` and `PdfConfig` Pydantic models and
  `word:` / `pdf:` sections in `config.yaml`.

## Impact

**Affected code:**

| Path | Status |
|---|---|
| `src/components/interfaces/_doc_common.py` | NEW |
| `src/components/interfaces/excel.py` | MODIFIED (re-imports from `_doc_common`) |
| `src/components/interfaces/word.py` | NEW |
| `src/components/interfaces/pdf.py` | NEW |
| `src/components/interfaces/commands/word.py` | NEW |
| `src/components/interfaces/commands/pdf.py` | NEW |
| `src/components/interfaces/commands/__init__.py` | MODIFIED (register `word`, `pdf`) |
| `src/components/interfaces/models.py` | MODIFIED (+ `WordTranslationReport`, `PdfTranslationReport`) |
| `src/config/models.py` | MODIFIED (+ `WordConfig`, `PdfConfig`) |
| `src/config/config.py` | MODIFIED (wire `word`, `pdf`) |
| `config.yaml` | MODIFIED (+ `word:`, `pdf:` sections) |
| `requirements.txt` | MODIFIED (+ `pypdf>=4.0,<5`) |
| `pyproject.toml` | MODIFIED (+ `pypdf` dep, + per-file-ignores) |
| `tests/test_doc_common.py` | NEW |
| `tests/test_word.py` | NEW |
| `tests/test_pdf.py` | NEW |
| `tests/fixtures/pdf/` | NEW (one small fixture + README) |
| `README.md` | MODIFIED (document the two new commands) |

**Affected APIs:**

- New public functions `translate_word(...)` and `translate_pdf(...)` and
  their pure helpers in `word.py` / `pdf.py`.
- New CLI subcommands `iraqi-translate word ...` and
  `iraqi-translate pdf ...`.
- `AppConfig` gains `word: WordConfig` and `pdf: PdfConfig` fields
  (additive, backward compatible — defaults applied when the sections
  are absent).
- `excel.py`'s public re-exports (`protect_non_translatable`,
  `restore_protected`, `StringSegment`, `ProgressCallback`) are
  preserved; only their definition site moves to `_doc_common.py`.

**Dependencies:**

- One new runtime dependency: `pypdf>=4.0,<5` (pure Python, MIT-licensed,
  ~1 MB, offline, no native binaries, no telemetry). It is
  lazy-imported inside `pdf.py` so the `word`, `excel`, `translate`,
  `batch`, and `ui` code paths never import it. It is the first new
  runtime dep since the opt-in `google-genai` cloud backend; per the
  project rule, the published version pinned must be ≥ 7 days old at
  install time.
- No new cloud calls. No new telemetry. Fits the 8 GB RAM profile
  (PDF pages are streamed one at a time via `pypdf`'s lazy page reader;
  Word parts are processed per-part; only the allowlisted text-bearing
  OOXML parts are held in memory, identical to the excel adapter's
  memory profile).

**Systems affected:**

- CLI (`iraqi-translate word`, `iraqi-translate pdf`).
- Test suite (three new test modules + one fixture directory).
- Lint / type-check (three new source files; `pypdf` ships type stubs).
- Packaging (`requirements.txt`, `pyproject.toml`).

**Migration path:** Purely additive. No existing import paths change.
`config.yaml` gains two optional sections; `AppConfig` applies defaults
when they are absent, so existing configs keep working unchanged. Users
who want the `pdf` command must re-run `pip install -r requirements.txt`
to pick up `pypdf`; the `word` command works with the existing
environment. The `excel.py` refactor is a mechanical move of four
symbols to `_doc_common.py` with re-exports preserved — no caller of
`excel.py`'s public API needs to change.

**Rollback plan:** Revert the commits. No data files, `db/`, or `data/`
directories are touched. The feature is isolated to new files plus small
additive edits to `cli.py`'s command registry, `models.py`, `config.py`,
`config.yaml`, `pyproject.toml`, `requirements.txt`, and `README.md`.
The `_doc_common.py` extraction can be reverted independently of the
`word`/`pdf` features (excel will work either way because the re-export
is preserved).

**Affected files (old → new):**

| Old path | New path |
|---|---|
| (none) | `src/components/interfaces/_doc_common.py` |
| (none) | `src/components/interfaces/word.py` |
| (none) | `src/components/interfaces/pdf.py` |
| (none) | `src/components/interfaces/commands/word.py` |
| (none) | `src/components/interfaces/commands/pdf.py` |
| (none) | `tests/test_doc_common.py` |
| (none) | `tests/test_word.py` |
| (none) | `tests/test_pdf.py` |
| (none) | `tests/fixtures/pdf/` |
| `src/components/interfaces/excel.py` | `src/components/interfaces/excel.py` (re-imports from `_doc_common`) |
| `src/components/interfaces/commands/__init__.py` | `src/components/interfaces/commands/__init__.py` (+ `word`, `pdf`) |
| `src/components/interfaces/models.py` | `src/components/interfaces/models.py` (+ 2 DTOs) |
| `src/config/models.py` | `src/config/models.py` (+ `WordConfig`, `PdfConfig`) |
| `src/config/config.py` | `src/config/config.py` (wire `word`, `pdf`) |
| `config.yaml` | `config.yaml` (+ `word:`, `pdf:` sections) |
| `requirements.txt` | `requirements.txt` (+ `pypdf`) |
| `pyproject.toml` | `pyproject.toml` (+ `pypdf`, + per-file-ignores) |
| `README.md` | `README.md` (document the two new commands) |

## Approach (library selection)

### Word (`.docx`)

Three approaches were compared:

1. **`python-docx`** — pure-Python `.docx` library. New dependency;
   `Document()` loads the whole package into memory (poor for large
   files); known fidelity gaps on tracked changes, complex tables, and
   custom XML parts. Rejected for the same reasons `openpyxl` was
   rejected for Excel.
2. **Direct XML (stdlib `zipfile` + `xml.etree.ElementTree` +
   `defusedxml`)** — `.docx` is a zip of OOXML parts. No new
   dependencies; maximum fidelity (only text-bearing `w:t` nodes are
   patched, every other part is preserved byte-for-byte);
   memory-efficient per-part processing. Identical to the proven Excel
   approach.
3. **`pandas`** — not applicable to `.docx`; rejected.

**Chosen: Direct XML (stdlib only).** It is the only approach that
satisfies all requirements simultaneously — exact preservation of
styles/tables/images/hyperlinks/tracked-changes, large-file memory
efficiency, no new dependencies, and offline operation within the 8 GB
RAM ceiling.

### PDF (`.pdf`)

Four approaches were compared:

1. **In-place PDF rewrite (`reportlab` / `fpdf2`)** — generates a new
   PDF with translated text. Rejected: re-flowing Arabic text into
   positioned PDF glyphs requires an Arabic reshaper
   (`arabic-reshaper` + `python-bidi`) and per-font metrics; layout
   (tables, columns, stamps) is lost anyway; heavy native deps. YAGNI
   for this change.
2. **`pypdf` extraction + `.docx` sidecar** — `pypdf` is pure Python,
   ~1 MB, MIT-licensed, offline, lazily importable. Sufficient for
   single-column legal text. The sidecar `.docx` is editable and
   reuses the OOXML writer we are already building for the Word
   adapter. Chosen.
3. **`pdfplumber` extraction + `.docx` sidecar** — `pdfplumber` depends
   on `pdfminer.six` (heavier, ~5 MB, slower). `pypdf` is lighter and
   sufficient for single-column legal text. Rejected on weight.
4. **`pymupdf` (fitz)** — fastest, best extraction quality, but
   **AGPL-licensed** (incompatible with the project's MIT license) and
   ships a native binary. Rejected on licensing grounds.

**Chosen: `pypdf` extraction → translated `.docx` (or `.txt`) sidecar.**
It is the only approach that is MIT-compatible, offline, lightweight,
lazy-importable, and reuses the OOXML writer infrastructure from the
Word adapter.

### Command shape

Two approaches were compared:

1. **Separate `word` + `pdf` subcommands** — matches the existing
   one-command-per-format `excel` pattern; simpler specs; clearer
   `--help`; one failure mode per command. Chosen.
2. **Unified `document` command dispatching on extension** — fewer
   commands but more branching logic, a bigger spec, and mixed error
   semantics. Rejected.

**Chosen: separate `word` and `pdf` subcommands.**
