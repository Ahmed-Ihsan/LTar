# PDF & Word Document Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `word` and `pdf` CLI subcommands that translate Iraqi legal documents through the existing Translator → Auditor → Revise pipeline, mirroring the proven `excel` adapter.

**Architecture:** Two new document-translation adapters under `src/components/interfaces/` (`word.py`, `pdf.py`), each split into pure helpers (no pipeline dependency, unit-testable) + an orchestrator that reuses `orchestration.run_translation`. Shared protect/restore helpers extracted to `_doc_common.py`. New `WordConfig`/`PdfConfig` Pydantic models + `WordTranslationReport`/`PdfTranslationReport` DTOs. OpenSpec change proposal `add-pdf-word-translation` written and validated before coding.

**Tech Stack:** Python 3.10/3.11 stdlib (`zipfile`, `xml.etree.ElementTree`, `defusedxml`), `pypdf>=4.0,<5` (new, pure-Python, lazy-imported inside `pdf.py` only), Pydantic v2, Typer, pytest with `mock_llm`/`mock_embedder` fixtures (existing pattern from `tests/test_excel.py`).

## Global Constraints

- Python 3.10.x or 3.11.x; mypy strict = true; ruff line-length = 100; target py311.
- 8 GB RAM hard ceiling: concurrency = 1 in-flight translation; embedding batch ≤ 32; never hold full document in memory — stream per-part / per-page.
- No telemetry, no cloud calls (except the existing opt-in Gemini backend). `pypdf` is offline, pure-Python, MIT-licensed.
- Conventional commits: `feat:`, `test:`, `refactor:`, `docs:`, `chore:`.
- TypedDicts for LangGraph state (not Pydantic); Pydantic only for config.
- Adapter dependencies are keyword-only args (DIP).
- All XML parsing via `defusedxml.ElementTree.fromstring`; all zip entries via `src.utils.zip_safe.validate_zip_path`; all translated text via `src.utils.xml_escape.escape_xml_text`.
- `--input` / `--out` validated via `src.utils.paths.validate_path_in_root` (exit code 4 on violation).
- Domain exceptions only surface to the CLI (via `@handle_pipeline_errors`): connection → 2, RAM guard → 3, other domain → 1, path containment → 4.
- New dependency `pypdf` must be published ≥ 7 days ago; pin `pypdf>=4.0,<5`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/components/interfaces/_doc_common.py` | NEW — shared `protect_non_translatable`, `restore_protected`, sentinel constants, `StringSegment` dataclass, `ProgressCallback` protocol. Moved out of `excel.py`. |
| `src/components/interfaces/excel.py` | MODIFIED — re-imports protect/restore from `_doc_common`; behavior unchanged. |
| `src/components/interfaces/word.py` | NEW — pure Word XML helpers (`extract_word_strings`, `patch_word_strings`, `split_translation`) + `translate_word` orchestrator. |
| `src/components/interfaces/pdf.py` | NEW — pure PDF text helpers (`extract_pdf_paragraphs`, `segment_pdf_page`) + `build_docx_from_paragraphs` writer + `translate_pdf` orchestrator. Lazy-imports `pypdf`. |
| `src/components/interfaces/commands/word.py` | NEW — `word` Typer subcommand. |
| `src/components/interfaces/commands/pdf.py` | NEW — `pdf` Typer subcommand. |
| `src/components/interfaces/commands/__init__.py` | MODIFIED — register `word`, `pdf`. |
| `src/components/interfaces/models.py` | MODIFIED — add `WordTranslationReport`, `PdfTranslationReport`. |
| `src/config/models.py` | MODIFIED — add `WordConfig`, `PdfConfig`. |
| `src/config/config.py` | MODIFIED — wire `word: WordConfig`, `pdf: PdfConfig` into `AppConfig`. |
| `config.yaml` | MODIFIED — add `word:` and `pdf:` sections with documented defaults. |
| `requirements.txt` | MODIFIED — add `pypdf>=4.0,<5`. |
| `pyproject.toml` | MODIFIED — add `pypdf` dep + ruff per-file-ignores (`PLR0913`) for `word.py`, `pdf.py`. |
| `tests/test_doc_common.py` | NEW — unit tests for the moved helpers (re-asserts excel behavior). |
| `tests/test_word.py` | NEW — unit + integration + e2e tests for the Word adapter. |
| `tests/test_pdf.py` | NEW — unit + integration + e2e tests for the PDF adapter. |
| `tests/fixtures/word/`, `tests/fixtures/pdf/` | NEW — small fixtures generated programmatically by tests (no binary committed). |
| `openspec/changes/add-pdf-word-translation/` | NEW — proposal.md, design.md, tasks.md, specs/interfaces/spec.md, specs/config/spec.md (delta specs). |
| `README.md` | MODIFIED — document `word` and `pdf` commands in §2.5 and §6.6. |

---

## Task 0: OpenSpec change proposal (spec-first, before any code)

**Files:**
- Create: `openspec/changes/add-pdf-word-translation/proposal.md`
- Create: `openspec/changes/add-pdf-word-translation/design.md`
- Create: `openspec/changes/add-pdf-word-translation/tasks.md`
- Create: `openspec/changes/add-pdf-word-translation/specs/interfaces/spec.md`
- Create: `openspec/changes/add-pdf-word-translation/specs/config/spec.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-07-21-pdf-word-translation-design.md` (this plan's design source).
- Produces: a validated OpenSpec change that delta-specs the new `word`/`pdf` CLI commands, orchestration seams, pure helpers, `WordConfig`/`PdfConfig`, and report DTOs.

- [ ] **Step 1: Create the change with `openspec new change`**

Run:
```bash
openspec new change add-pdf-word-translation --goal "Add word and pdf CLI subcommands that translate Iraqi legal documents through the existing pipeline, mirroring the excel adapter."
```
Expected: `openspec/changes/add-pdf-word-translation/` scaffold created with empty `proposal.md`, `design.md`, `tasks.md`, and `specs/` (consult `openspec/config.yaml` for the per-artifact rules).

- [ ] **Step 2: Write `proposal.md`**

Mirror `openspec/changes/archive/2026-07-18-add-excel-translation/proposal.md` structure: `## Why`, `## What Changes` (ADDED/MODIFIED bullets for each file in the File Structure table above), `## Capabilities` (new: `word_translation`, `pdf_translation`; modified: `interfaces`, `config`), `## Impact` (affected code/APIs/dependencies/systems/migration/rollback/affected-files table), `## Approach (library selection)` (the Word + PDF alternatives from design §4).

- [ ] **Step 3: Write `design.md`**

Adapt `docs/superpowers/specs/2026-07-21-pdf-word-translation-design.md` to OpenSpec's design format (architecture, decisions, alternatives, risks). Reference the excel change's `design.md` for the expected shape.

- [ ] **Step 4: Write delta specs**

`specs/interfaces/spec.md`: ADDED requirements mirroring the excel spec's three requirements ("Word translation command", "Word translation orchestration", "Word XML extraction and patching (pure helpers)", "PDF translation command", "PDF translation orchestration", "PDF text extraction and sidecar writer (pure helpers)"). Each requirement has 3-5 Given/When/Then scenarios covering: happy path, missing input file, RAM guard → exit 3, oversize file rejection, deduplication, paragraph run-splitting, byte-for-byte preservation of non-text parts, path containment → exit 4, scanned-PDF warning.

`specs/config/spec.md`: ADDED requirements for `WordConfig` and `PdfConfig` with scenarios for defaults-when-absent and validation failures.

- [ ] **Step 5: Write `tasks.md`**

Copy the task list from this plan (Tasks 1-9 below) into OpenSpec's checkbox format.

- [ ] **Step 6: Validate the change**

Run:
```bash
openspec validate add-pdf-word-translation
```
Expected: `1 passed, 0 failed`. Fix any validation errors before proceeding.

- [ ] **Step 7: Commit**

```bash
git add openspec/changes/add-pdf-word-translation/
git commit -m "docs: add openspec change proposal for pdf/word translation"
```

---

## Task 1: Extract shared helpers to `_doc_common.py` (safe refactor)

**Files:**
- Create: `src/components/interfaces/_doc_common.py`
- Modify: `src/components/interfaces/excel.py` (re-import from `_doc_common`)
- Test: `tests/test_doc_common.py`

**Interfaces:**
- Consumes: the existing `protect_non_translatable`, `restore_protected`, `_SENTINEL_OPEN`, `_SENTINEL_CLOSE`, `_SENTINEL_RE`, `_PROTECTION_PATTERNS`, `StringSegment`, `ProgressCallback` definitions in `excel.py`.
- Produces: the same symbols at `src.components.interfaces._doc_common`, re-exported from `excel.py` for backward compatibility.

- [ ] **Step 1: Write the failing test**

`tests/test_doc_common.py`:
```python
"""Tests for shared document-translation helpers extracted from excel.py."""
from src.components.interfaces._doc_common import (
    StringSegment,
    protect_non_translatable,
    restore_protected,
)


def test_protect_and_restore_roundtrip():
    text = "See Article 12 and https://example.com/law for {placeholder} details."
    protected, token_map = protect_non_translatable(text)
    assert "\x00T" in protected
    assert "Article" in protected  # 'Article' is not a protected token
    restored = restore_protected(protected, token_map)
    assert restored == text


def test_identical_tokens_reuse_sentinel():
    text = "Call 100 times or 100 times."
    protected, token_map = protect_non_translatable(text)
    # Two occurrences of "100" share one sentinel.
    assert len(token_map) == 1


def test_string_segment_is_frozen():
    seg = StringSegment(part="xl/sharedStrings.xml", text="عقد البيع")
    try:
        seg.text = "other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("StringSegment should be frozen")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_doc_common.py -v`
Expected: FAIL with `ModuleNotFoundError: src.components.interfaces._doc_common`.

- [ ] **Step 3: Create `_doc_common.py`**

Move (cut) the following from `excel.py` into `src/components/interfaces/_doc_common.py`: the module docstring's relevant sentences, `StringSegment`, `_SENTINEL_OPEN`/`_SENTINEL_CLOSE`/`_SENTINEL_RE`, `_PROTECTION_PATTERNS`, `protect_non_translatable`, `restore_protected`, `ProgressCallback`. Add `__all__`. Keep the same code verbatim — this is a mechanical move.

- [ ] **Step 4: Update `excel.py` to re-import**

In `excel.py`, delete the moved definitions and add at the top (after the existing imports):
```python
from src.components.interfaces._doc_common import (
    ProgressCallback,
    StringSegment,
    protect_non_translatable,
    restore_protected,
)
```
Keep them in `excel.py`'s `__all__` for backward compatibility.

- [ ] **Step 5: Run all excel + doc_common tests**

Run: `pytest tests/test_doc_common.py tests/test_excel.py -v`
Expected: PASS (excel behavior unchanged; the move is mechanical).

- [ ] **Step 6: Lint + typecheck**

Run: `ruff check src/components/interfaces/_doc_common.py src/components/interfaces/excel.py` then `mypy src/`
Expected: clean; zero mypy errors.

- [ ] **Step 7: Commit**

```bash
git add src/components/interfaces/_doc_common.py src/components/interfaces/excel.py tests/test_doc_common.py
git commit -m "refactor: extract protect/restore helpers to _doc_common for word/pdf reuse"
```

---

## Task 2: `WordConfig` + `PdfConfig` Pydantic models

**Files:**
- Modify: `src/config/models.py`
- Modify: `src/config/config.py`
- Modify: `config.yaml`
- Test: `tests/test_config.py` (add cases — verify the file's existing style first)

**Interfaces:**
- Consumes: `pydantic.BaseModel`, `field_validator`, the existing `ExcelConfig` pattern.
- Produces: `WordConfig`, `PdfConfig` importable from `src.config.models`; `AppConfig.word` and `AppConfig.pdf` fields with `default_factory`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (match the file's existing test style):
```python
def test_word_config_defaults_applied_when_absent():
    from src.config import AppConfig
    cfg = AppConfig()
    assert cfg.word.translate_comments is True
    assert cfg.word.translate_headers_footers is True
    assert cfg.word.translate_footnotes is True
    assert cfg.word.translate_endnotes is True
    assert cfg.word.translate_glossary_doc is False
    assert cfg.word.max_segment_chars == 8192
    assert cfg.word.max_docx_bytes == 50 * 1024 * 1024
    assert cfg.word.max_segments == 20000


def test_pdf_config_defaults_applied_when_absent():
    from src.config import AppConfig
    cfg = AppConfig()
    assert cfg.pdf.out_format == "docx"
    assert cfg.pdf.max_pdf_bytes == 100 * 1024 * 1024
    assert cfg.pdf.max_pages == 500
    assert cfg.pdf.skip_header_footer is True


def test_word_config_rejects_invalid_max_segment_chars():
    from src.config import AppConfig
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AppConfig(word={"max_segment_chars": 8})


def test_pdf_config_rejects_invalid_out_format():
    from src.config import AppConfig
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AppConfig(pdf={"out_format": "rtf"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -k "word_config or pdf_config" -v`
Expected: FAIL with `AttributeError: AppConfig has no attribute 'word'`.

- [ ] **Step 3: Add the models to `src/config/models.py`**

After `ExcelConfig`, add:
```python
class WordConfig(BaseModel):
    """Word (.docx) translation feature toggles and limits.

    Controls which human-readable text locations the Word adapter translates.
    Non-text artifacts (styles, tables, images, hyperlinks, tracked changes,
    custom XML parts) are always preserved byte-for-byte; these toggles only
    select which text gets routed through the pipeline.
    """
    translate_comments: bool = True
    translate_headers_footers: bool = True
    translate_footnotes: bool = True
    translate_endnotes: bool = True
    translate_glossary_doc: bool = False
    max_segment_chars: int = 8192
    max_docx_bytes: int = 50 * 1024 * 1024
    max_segments: int = 20000

    @field_validator("max_segment_chars")
    @classmethod
    def _max_segment_chars_min(cls, v: int) -> int:
        if v < 16:
            raise ValueError(f"max_segment_chars must be >= 16, got {v}")
        return v

    @field_validator("max_docx_bytes")
    @classmethod
    def _max_docx_bytes_min(cls, v: int) -> int:
        if v < 1_048_576:
            raise ValueError(f"max_docx_bytes must be >= 1 MiB, got {v}")
        return v

    @field_validator("max_segments")
    @classmethod
    def _max_segments_min(cls, v: int) -> int:
        if v < 100:
            raise ValueError(f"max_segments must be >= 100, got {v}")
        return v


class PdfConfig(BaseModel):
    """PDF (.pdf) translation feature toggles and limits.

    PDFs are translated to a sidecar file (``.docx`` by default, or ``.txt``)
    because in-place PDF rewrite is lossy and Arabic-font-dependent. See
    ``docs/superpowers/specs/2026-07-21-pdf-word-translation-design.md`` §5.
    """
    out_format: Literal["docx", "txt"] = "docx"
    max_pdf_bytes: int = 100 * 1024 * 1024
    max_pages: int = 500
    max_segment_chars: int = 8192
    max_segments: int = 20000
    skip_header_footer: bool = True

    @field_validator("max_pdf_bytes")
    @classmethod
    def _max_pdf_bytes_min(cls, v: int) -> int:
        if v < 1_048_576:
            raise ValueError(f"max_pdf_bytes must be >= 1 MiB, got {v}")
        return v

    @field_validator("max_pages", "max_segments", "max_segment_chars")
    @classmethod
    def _positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"expected a positive integer, got {v}")
        return v
```
`Literal` is already imported at the top of `models.py`.

- [ ] **Step 4: Wire into `AppConfig` in `src/config/config.py`**

Update the import line:
```python
from src.config.models import ChromaConfig, ExcelConfig, PathsConfig, PdfConfig, UiConfig, WordConfig
```
Add fields near the existing `excel: ExcelConfig` line:
```python
    # --- Word (.docx) document translation ---
    word: WordConfig = Field(default_factory=WordConfig)

    # --- PDF (.pdf) document translation (sidecar output) ---
    pdf: PdfConfig = Field(default_factory=PdfConfig)
```

- [ ] **Step 5: Add `word:` and `pdf:` sections to `config.yaml`**

After the `excel:` section:
```yaml
# --- Word (.docx) document translation ---
# Controls which human-readable text locations the `word` CLI command
# translates. Non-text artifacts (styles, tables, images, hyperlinks,
# tracked changes, custom XML parts) are always preserved byte-for-byte.
word:
  translate_comments: true
  translate_headers_footers: true
  translate_footnotes: true
  translate_endnotes: true
  translate_glossary_doc: false
  max_segment_chars: 8192     # paragraphs longer than this are skipped (original kept)
  max_docx_bytes: 52428800    # 50 MiB — documents larger than this are rejected
  max_segments: 20000         # documents with more translatable segments are rejected

# --- PDF (.pdf) document translation (sidecar output) ---
# PDFs cannot be cleanly edited in place; the `pdf` command extracts text
# per page, translates it, and writes a sidecar `.docx` (or `.txt`).
# Scanned PDFs (image-only) are not supported — use an OCR tool first.
pdf:
  out_format: docx            # docx | txt — sidecar output format
  max_pdf_bytes: 104857600    # 100 MiB — PDFs larger than this are rejected
  max_pages: 500              # PDFs with more pages are rejected
  max_segment_chars: 8192
  max_segments: 20000
  skip_header_footer: true    # drop short top/bottom lines (page numbers, headers)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_config.py -k "word_config or pdf_config" -v`
Expected: PASS.

- [ ] **Step 7: Lint + typecheck**

Run: `ruff check src/config/` then `mypy src/`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/config/models.py src/config/config.py config.yaml tests/test_config.py
git commit -m "feat: add WordConfig and PdfConfig with defaults"
```

---

## Task 3: Report DTOs (`WordTranslationReport`, `PdfTranslationReport`)

**Files:**
- Modify: `src/components/interfaces/models.py`
- Test: `tests/test_models.py` (add cases — verify the file's existing style first; if it doesn't exist, create it)

**Interfaces:**
- Consumes: `dataclass` (slots, frozen) — same pattern as `ExcelTranslationReport`.
- Produces: `WordTranslationReport`, `PdfTranslationReport` importable from `src.components.interfaces.models`.

- [ ] **Step 1: Write the failing test**

```python
def test_word_translation_report_is_frozen():
    from src.components.interfaces.models import WordTranslationReport
    r = WordTranslationReport(total_segments=10, translated=8, skipped=1,
                              failed=1, cancelled=False, warnings=["w"])
    assert r.translated == 8
    try:
        r.translated = 9  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("WordTranslationReport should be frozen")


def test_pdf_translation_report_carries_page_count():
    from src.components.interfaces.models import PdfTranslationReport
    r = PdfTranslationReport(total_pages=5, total_segments=20, translated=18,
                             skipped=1, failed=1, cancelled=False, warnings=[])
    assert r.total_pages == 5
    assert r.total_segments == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -k "word_translation_report or pdf_translation_report" -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the DTOs to `src/components/interfaces/models.py`**

After `ExcelTranslationReport`:
```python
@dataclass(slots=True, frozen=True)
class WordTranslationReport:
    """Outcome of a ``word`` document translation run.

    Counts are over the deduplicated set of unique source paragraphs
    extracted from the document. ``skipped`` covers paragraphs left
    untranslated due to cancellation or the ``max_segment_chars`` cap;
    ``failed`` covers paragraphs whose translation raised a domain error or
    returned empty output (the original text is preserved in both cases).
    ``cancelled`` is True when the run was interrupted via ``cancel_event``.
    """
    total_segments: int
    translated: int
    skipped: int
    failed: int
    cancelled: bool
    warnings: list[str]


@dataclass(slots=True, frozen=True)
class PdfTranslationReport:
    """Outcome of a ``pdf`` document translation run.

    ``total_pages`` is the page count of the source PDF. Segment counts are
    over the deduplicated set of unique paragraphs extracted across all
    pages. ``warnings`` records per-page extraction issues (e.g. a page that
    yielded no extractable text, suggesting a scanned page).
    """
    total_pages: int
    total_segments: int
    translated: int
    skipped: int
    failed: int
    cancelled: bool
    warnings: list[str]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -k "word_translation_report or pdf_translation_report" -v`
Expected: PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `ruff check src/components/interfaces/models.py` then `mypy src/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/components/interfaces/models.py tests/test_models.py
git commit -m "feat: add WordTranslationReport and PdfTranslationReport DTOs"
```

---

## Task 4: Word adapter — pure XML helpers

**Files:**
- Create: `src/components/interfaces/word.py`
- Test: `tests/test_word.py`

**Interfaces:**
- Consumes: `src.components.interfaces._doc_common` (`StringSegment`, `protect_non_translatable`, `restore_protected`, `ProgressCallback`), `src.utils.zip_safe.validate_zip_path`, `src.utils.xml_escape.escape_xml_text`, `defusedxml.ElementTree.fromstring`, `src.config.AppConfig` (`cfg.word.*`).
- Produces: `extract_word_strings(docx_bytes, *, cfg) -> list[StringSegment]`, `patch_word_strings(docx_bytes, translations, *, cfg) -> bytes`, `split_translation(translation, run_lengths) -> list[str]`.

- [ ] **Step 1: Write the failing test for `extract_word_strings`**

`tests/test_word.py`:
```python
"""Tests for the Word (.docx) translation adapter."""
import zipfile
from io import BytesIO
from xml.etree import ElementTree as ET

from src.components.interfaces.word import (
    extract_word_strings,
    patch_word_strings,
    split_translation,
)
from src.config import AppConfig


def _build_minimal_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal valid .docx with the given body paragraphs."""
    # A minimal .docx needs: [Content_Types].xml, _rels/.rels,
    # word/_rels/document.xml.rels, word/document.xml. We build only what
    # the extractor reads (word/document.xml) plus the bare OOXML scaffolding
    # so zipfile opens cleanly.
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    )
    body = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>'
        for p in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body}</w:body>'
        '</w:document>'
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def test_extract_word_strings_dedupes_paragraphs():
    docx = _build_minimal_docx(["عقد البيع", "عقد البيع", "Article 1"])
    cfg = AppConfig()
    segments = extract_word_strings(docx, cfg=cfg)
    texts = [s.text for s in segments]
    assert texts == ["عقد البيع", "Article 1"]


def test_extract_word_strings_skips_empty_paragraphs():
    docx = _build_minimal_docx(["", "   ", "real text"])
    cfg = AppConfig()
    segments = extract_word_strings(docx, cfg=cfg)
    assert [s.text for s in segments] == ["real text"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_word.py -v`
Expected: FAIL with `ModuleNotFoundError: src.components.interfaces.word`.

- [ ] **Step 3: Implement `extract_word_strings` and `split_translation`**

Create `src/components/interfaces/word.py` with:
- WordprocessingML namespace registration (`w` = `http://schemas.openxmlformats.org/wordprocessingml/2006/main`).
- `_W_T = "{...}t"`, `_W_P = "{...}p"`, `_W_R = "{...}r"`.
- `_is_word_text_part(name, cfg) -> bool`: allowlist `word/document.xml`, `word/headerN.xml`, `word/footerN.xml`, `word/footnotes.xml`, `word/endnotes.xml`, `word/comments.xml` (gated by `cfg.word.translate_*` toggles). Exclude `word/glossary/document.xml` unless `translate_glossary_doc`.
- `_paragraph_text(p_el) -> tuple[str, list[int]]`: walk `w:t` children of `w:r` children in document order, concatenate text, return `(text, run_lengths)` where `run_lengths[i]` is the char length of the i-th run's text. Insert a space between runs when the previous run's text doesn't end in whitespace AND the next doesn't start with whitespace (per OOXML spacing rules) — count that space as belonging to the second run.
- `extract_word_strings(docx_bytes, *, cfg) -> list[StringSegment]`: open the zip, for each allowlisted part, parse with `defusedxml`, for each `w:p` collect `_paragraph_text`; dedupe by text; skip empty/whitespace-only; record `StringSegment(part=name, text=text)`.
- `split_translation(translation, run_lengths) -> list[str]`: proportionally split `translation` into `len(run_lengths)` chunks by character count. If `sum(run_lengths) == 0`, return equal chunks. Never return empty chunks for non-empty input — distribute remainder to the last run.

- [ ] **Step 4: Run extraction tests to verify they pass**

Run: `pytest tests/test_word.py -k "extract_word_strings" -v`
Expected: PASS.

- [ ] **Step 5: Write the failing test for `patch_word_strings`**

```python
def test_patch_word_strings_replaces_text_preserving_other_parts():
    docx = _build_minimal_docx(["عقد البيع", "Article 1"])
    cfg = AppConfig()
    translations = {"عقد البيع": "Contract of Sale", "Article 1": "المادة 1"}
    out = patch_word_strings(docx, translations, cfg=cfg)
    # The translated text must appear in the output document.xml.
    with zipfile.ZipFile(BytesIO(out)) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    assert "Contract of Sale" in doc
    assert "المادة 1" in doc
    # The [Content_Types].xml part must be byte-for-byte unchanged.
    with zipfile.ZipFile(BytesIO(docx)) as zin, zipfile.ZipFile(BytesIO(out)) as zout:
        assert zin.read("[Content_Types].xml") == zout.read("[Content_Types].xml")


def test_patch_word_strings_splits_translation_across_runs():
    # Build a paragraph with two runs: "Very " + "Important Article"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml",
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p>'
            '<w:r><w:t xml:space="preserve">Very </w:t></w:r>'
            '<w:r><w:t xml:space="preserve">Important Article</w:t></w:r>'
            '</w:p></w:body></w:document>')
    cfg = AppConfig()
    segments = extract_word_strings(buf.getvalue(), cfg=cfg)
    assert segments[0].text == "Very Important Article"
    out = patch_word_strings(buf.getvalue(), {"Very Important Article": "مهم جدا"}, cfg=cfg)
    with zipfile.ZipFile(BytesIO(out)) as z:
        doc = z.read("word/document.xml").decode("utf-8")
    assert "مهم جدا" in doc
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_word.py -k "patch_word_strings" -v`
Expected: FAIL (`patch_word_strings` not yet implemented).

- [ ] **Step 7: Implement `patch_word_strings`**

Mirror `excel.py`'s `patch_strings`: open the input zip, copy every part byte-for-byte except allowlisted parts; for allowlisted parts, parse with `defusedxml`, for each `w:p` re-walk the `w:t` runs in order, look up the paragraph's concatenated text in `translations`, and if found, `split_translation` the result across the runs by their original lengths, escaping each chunk with `escape_xml_text` before assigning to `el.text`. Re-serialize with `ET.tostring(root, encoding="UTF-8", xml_declaration=True)`. Validate every zip entry name via `validate_zip_path`.

- [ ] **Step 8: Run patch tests to verify they pass**

Run: `pytest tests/test_word.py -k "patch_word_strings" -v`
Expected: PASS.

- [ ] **Step 9: Write the failing test for `split_translation`**

```python
def test_split_translation_single_run_returns_whole():
    assert split_translation("hello", [5]) == ["hello"]

def test_split_translation_proportional():
    parts = split_translation("abcdef", [2, 4])
    assert parts == ["ab", "cdef"]
    assert sum(len(p) for p in parts) == 6

def test_split_translation_handles_zero_length_runs():
    parts = split_translation("abc", [0, 0])
    # Distribute evenly when original runs were empty.
    assert "".join(parts) == "abc"
    assert len(parts) == 2
```

- [ ] **Step 10: Run split tests to verify they pass**

Run: `pytest tests/test_word.py -k "split_translation" -v`
Expected: PASS (implemented in Step 3).

- [ ] **Step 11: Lint + typecheck**

Run: `ruff check src/components/interfaces/word.py` then `mypy src/`
Expected: clean.

- [ ] **Step 12: Commit**

```bash
git add src/components/interfaces/word.py tests/test_word.py
git commit -m "feat: add Word XML extract/patch pure helpers"
```

---

## Task 5: Word adapter — orchestrator (`translate_word`)

**Files:**
- Modify: `src/components/interfaces/word.py`
- Test: `tests/test_word.py` (add integration tests)

**Interfaces:**
- Consumes: `orchestration.run_translation`, `orchestration.detect_direction`, `_doc_common.protect_non_translatable`/`restore_protected`, `LLMEngineAdapter`, `EmbeddingAdapter`, `GlossaryIndex`, `TranslationMemory`, `RunLogger`, `AppConfig.word.*`.
- Produces: `translate_word(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> WordTranslationReport`.

- [ ] **Step 1: Write the failing integration test**

Use the existing `mock_llm`/`mock_embedder` fixtures from `tests/test_excel.py` (find them with `grep` first; if they live in `tests/conftest.py`, import them; if not, copy the pattern). Add to `tests/test_word.py`:
```python
def test_translate_word_dedupes_and_writes_output(tmp_path, mock_llm, mock_embedder):
    from src.components.interfaces.word import translate_word
    from src.config import AppConfig
    docx = _build_minimal_docx(["عقد البيع", "عقد البيع", "Article 1"])
    in_path = tmp_path / "in.docx"
    out_path = tmp_path / "out.docx"
    in_path.write_bytes(docx)
    cfg = AppConfig()
    report = translate_word(
        str(in_path), str(out_path), "ar-en", cfg,
        llm=mock_llm, embedder=mock_embedder,
    )
    assert report.total_segments == 2  # deduped
    assert report.translated == 2
    assert out_path.exists()
    # Output is a valid zip / .docx.
    with zipfile.ZipFile(out_path) as z:
        assert "word/document.xml" in z.namelist()
```
Also add a test that `max_docx_bytes` oversize raises `InputValidationError`, and a test that `cancel_event` sets `cancelled=True`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_word.py -k "translate_word" -v`
Expected: FAIL (`translate_word` not yet implemented).

- [ ] **Step 3: Implement `translate_word`**

Mirror `excel.py`'s `translate_excel` exactly:
1. `input_p.stat().st_size > cfg.word.max_docx_bytes` → raise `InputValidationError`.
2. Read `docx_bytes` from `input_path`.
3. `segments = extract_word_strings(docx_bytes, cfg=cfg)`.
4. `len(segments) > cfg.word.max_segments` → raise `InputValidationError`.
5. Loop segments with concurrency = 1; per segment: check `cancel_event`, check `len(source) > max_chars` (skip + warn), resolve `auto` via `detect_direction`, call `_translate_segment` (protect → `run_translation` → restore), record `translated`/`failed`/`warnings`.
6. `out_bytes = patch_word_strings(docx_bytes, translations, cfg=cfg)`.
7. Atomic write: `tmp_path = output_p.with_suffix(output_p.suffix + ".tmp")`; write; `os.replace(tmp_path, output_p)`.
8. Return `WordTranslationReport(...)`.

Reuse the `_translate_segment` pattern from `excel.py` — either import it from `excel.py` (it's already generic enough) or copy it into `word.py`. Prefer importing to keep DRY; if it's not generic, generalize it into `_doc_common.py` and have both `excel.py` and `word.py` import it.

- [ ] **Step 4: Run integration tests to verify they pass**

Run: `pytest tests/test_word.py -k "translate_word" -v`
Expected: PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `ruff check src/components/interfaces/word.py` then `mypy src/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/components/interfaces/word.py tests/test_word.py
git commit -m "feat: add translate_word orchestrator reusing run_translation"
```

---

## Task 6: `word` CLI command

**Files:**
- Create: `src/components/interfaces/commands/word.py`
- Modify: `src/components/interfaces/commands/__init__.py`
- Modify: `pyproject.toml` (ruff per-file-ignore `PLR0913` for `word.py`)
- Test: `tests/test_word.py` (add CliRunner test)

**Interfaces:**
- Consumes: `src.components.interfaces.cli` (`app`, `load_or_exit`, `_project_root`, `validate_path_in_root`, `_construct_adapters`, `_new_run_logger`, `_DEFAULT_CONFIG`), `src.components.interfaces.word.translate_word`, `src.components.interfaces.orchestration.Direction`, `src.utils.cli_errors.handle_pipeline_errors`.
- Produces: `iraqi-translate word --input <p> --out <p> --direction <d> [--config <p>]`.

- [ ] **Step 1: Write the failing CliRunner test**

```python
def test_word_command_rejects_missing_input(tmp_path):
    from typer.testing import CliRunner
    from src.components.interfaces.cli import app
    runner = CliRunner()
    result = runner.invoke(app, [
        "word", "--input", str(tmp_path / "missing.docx"),
        "--out", str(tmp_path / "out.docx"), "--direction", "ar-en",
    ])
    assert result.exit_code == 1
    assert "input file not found" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_word.py -k "word_command" -v`
Expected: FAIL (`No such command 'word'`).

- [ ] **Step 3: Create `commands/word.py`**

Mirror `commands/excel.py` exactly, swapping `excel`→`word`, `.xlsx`→`.docx`, `translate_excel`→`translate_word`, `ExcelTranslationReport`→`WordTranslationReport`. Validate suffix is `.docx`. Decorate with `@_cli.app.command()` and `@handle_pipeline_errors`.

- [ ] **Step 4: Register in `commands/__init__.py`**

Add `word` to the import list (alphabetical, between `translate` and `ui`):
```python
from src.components.interfaces.commands import (  # noqa: F401
    batch,
    doctor,
    excel,
    ingest,
    pdf,
    tm_add,
    tm_build,
    translate,
    ui,
    word,
)
```
(`pdf` added too since Task 8 will need it; if you prefer, add only `word` here and `pdf` in Task 8.)

- [ ] **Step 5: Add ruff per-file-ignore to `pyproject.toml`**

Find the existing `[tool.ruff.lint.per-file-ignores]` section (it has an entry for `excel.py` `PLR0913`). Add:
```toml
"src/components/interfaces/word.py" = ["PLR0913"]
"src/components/interfaces/pdf.py" = ["PLR0913"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_word.py -k "word_command" -v` then `python -m src.app word --help`
Expected: test PASS; `--help` exits 0 and shows the `word` command.

- [ ] **Step 7: Lint + typecheck**

Run: `ruff check src/` then `mypy src/`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/components/interfaces/commands/word.py src/components/interfaces/commands/__init__.py pyproject.toml tests/test_word.py
git commit -m "feat: add word CLI subcommand"
```

---

## Task 7: PDF adapter — pure helpers (extraction + sidecar writer)

**Files:**
- Modify: `requirements.txt` (add `pypdf>=4.0,<5`)
- Modify: `pyproject.toml` (add `pyp` dep)
- Create: `src/components/interfaces/pdf.py`
- Test: `tests/test_pdf.py`

**Interfaces:**
- Consumes: `pypdf.PdfReader` (lazy-imported inside `pdf.py`), `src.config.AppConfig.pdf.*`, `src.utils.xml_escape.escape_xml_text`.
- Produces: `extract_pdf_paragraphs(pdf_path, *, cfg) -> tuple[list[list[str]], list[str]]` (per-page paragraph lists + warnings), `build_docx_from_paragraphs(pages, *, rtl) -> bytes`, `build_txt_from_paragraphs(pages) -> str`.

- [ ] **Step 1: Add the `pypdf` dependency**

Edit `requirements.txt`, add after the `defusedxml` line in the "Config & validation" group (or create a new "Document parsing" group):
```
# --- PDF text extraction (offline, pure-Python) ---
# Lazily imported inside pdf.py — only loaded when the `pdf` command runs.
pypdf>=4.0,<5
```
Edit `pyproject.toml` `[project] dependencies = [...]` list to add `"pypdf>=4.0,<5"`. Run `pip install pypdf` (or `pip install -e .`) to install it in the dev env.

- [ ] **Step 2: Write the failing test for `extract_pdf_paragraphs`**

`tests/test_pdf.py`:
```python
"""Tests for the PDF (.pdf) translation adapter."""
import pytest

pypdf = pytest.importorskip("pypdf")  # skip the whole module if pypdf absent

from src.components.interfaces.pdf import (
    extract_pdf_paragraphs,
    build_docx_from_paragraphs,
    build_txt_from_paragraphs,
)
from src.config import AppConfig


def _build_minimal_pdf(text_per_page: list[str], tmp_path) -> str:
    """Build a minimal PDF with the given text using pypdf's writer."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    for text in text_per_page:
        writer.add_blank_page(width=612, height=792)
        # pypdf cannot easily add text without reportlab; for tests we use
        # a fixture file committed under tests/fixtures/pdf/ instead.
    path = tmp_path / "in.pdf"
    # NOTE: see Step 3 — use a committed fixture instead of generating.
    return str(path)
```
**Note:** generating PDFs with embedded text requires `reportlab`. Rather than add a test-only dep, **commit a single small fixture PDF** `tests/fixtures/pdf/sample_ar.pdf` (a 2-page Iraqi legal excerpt, <50 KB) and read it in tests. If you cannot legally commit a fixture, generate one at test time using `pypdf`'s `PageObject` with a content stream built manually — but the simplest path is a tiny fixture. Document the fixture's provenance in `tests/fixtures/pdf/README.md`.

- [ ] **Step 3: Implement `extract_pdf_paragraphs`**

```python
def extract_pdf_paragraphs(
    pdf_path: str, *, cfg: AppConfig
) -> tuple[list[list[str]], list[str]]:
    """Extract per-page paragraphs from a PDF.

    Returns ``(pages, warnings)`` where ``pages[i]`` is the list of
    paragraph strings on page ``i+1``. ``warnings`` records pages that
    yielded no extractable text (likely scanned).
    """
    from pypdf import PdfReader  # lazy import

    reader = PdfReader(pdf_path)
    pages: list[list[str]] = []
    warnings: list[str] = []
    for idx, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        if not raw.strip():
            warnings.append(f"Page {idx}: no extractable text (scanned PDF?).")
            pages.append([])
            continue
        paragraphs = _segment_page(raw, cfg=cfg)
        pages.append(paragraphs)
    return pages, warnings
```
Implement `_segment_page(text, *, cfg) -> list[str]`: split on `\n\s*\n`; for each block, collapse internal newlines to spaces; if `cfg.pdf.skip_header_footer`, drop the first and last block when they are short (<60 chars) and contain only digits / roman numerals / single words. Skip empty blocks and blocks that are pure numbers (page numbers).

- [ ] **Step 4: Implement `build_docx_from_paragraphs` and `build_txt_from_paragraphs`**

`build_docx_from_paragraphs(pages, *, rtl: bool) -> bytes`: build a minimal `.docx` zip with `[Content_Types].xml`, `_rels/.rels`, `word/_rels/document.xml.rels`, `word/document.xml`. For each page, emit each paragraph as `<w:p><w:pPr><w:bidiVisual/>` (only if `rtl`) `</w:pPr><w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>`; between pages emit `<w:p><w:r><w:br w:type="page"/></w:r></w:p>`. Use `escape_xml_text` on every paragraph.

`build_txt_from_paragraphs(pages) -> str`: join paragraphs with `\n\n`, pages with `\n\n--- page break ---\n\n`.

- [ ] **Step 5: Write tests for the writers**

```python
def test_build_docx_from_paragraphs_creates_valid_zip():
    pages = [["Paragraph one", "Paragraph two"], ["Page two text"]]
    out = build_docx_from_paragraphs(pages, rtl=True)
    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(out)) as z:
        assert "word/document.xml" in z.namelist()
        doc = z.read("word/document.xml").decode("utf-8")
    assert "Paragraph one" in doc
    assert "bidiVisual" in doc  # rtl

def test_build_txt_from_paragraphs_includes_page_break_marker():
    pages = [["a"], ["b"]]
    txt = build_txt_from_paragraphs(pages)
    assert "a" in txt and "b" in txt
    assert "page break" in txt
```

- [ ] **Step 6: Run all pdf helper tests**

Run: `pytest tests/test_pdf.py -v`
Expected: PASS (extraction test uses the committed fixture; writer tests are pure).

- [ ] **Step 7: Lint + typecheck**

Run: `ruff check src/components/interfaces/pdf.py` then `mypy src/`
Expected: clean. (`pypdf` types ship with the package; if mypy complains, add `# type: ignore[import-untyped]` on the lazy import line only.)

- [ ] **Step 8: Commit**

```bash
git add requirements.txt pyproject.toml src/components/interfaces/pdf.py tests/test_pdf.py tests/fixtures/pdf/
git commit -m "feat: add PDF text extraction and docx/txt sidecar writers"
```

---

## Task 8: PDF adapter — orchestrator (`translate_pdf`) + CLI command

**Files:**
- Modify: `src/components/interfaces/pdf.py` (add `translate_pdf`)
- Create: `src/components/interfaces/commands/pdf.py`
- Modify: `src/components/interfaces/commands/__init__.py` (register `pdf`)
- Test: `tests/test_pdf.py` (add integration + CliRunner tests)

**Interfaces:**
- Consumes: `extract_pdf_paragraphs`, `build_docx_from_paragraphs`, `build_txt_from_paragraphs`, `orchestration.run_translation`/`detect_direction`, `_doc_common.protect_non_translatable`/`restore_protected`, `AppConfig.pdf.*`.
- Produces: `translate_pdf(input_path, output_path, direction, cfg, *, llm, embedder, ...) -> PdfTranslationReport`; `iraqi-translate pdf --input <p> --out <p> --direction <d> [--config <p>]`.

- [ ] **Step 1: Write the failing integration test**

```python
def test_translate_pdf_writes_docx_sidecar(tmp_path, mock_llm, mock_embedder):
    from src.components.interfaces.pdf import translate_pdf
    from src.config import AppConfig
    cfg = AppConfig()
    in_path = "tests/fixtures/pdf/sample_ar.pdf"  # committed fixture
    out_path = tmp_path / "out.docx"
    report = translate_pdf(
        in_path, str(out_path), "ar-en", cfg,
        llm=mock_llm, embedder=mock_embedder,
    )
    assert report.total_pages >= 1
    assert report.translated >= 1
    assert out_path.exists()
    import zipfile
    with zipfile.ZipFile(out_path) as z:
        assert "word/document.xml" in z.namelist()
```
Also: oversize `max_pdf_bytes` → `InputValidationError`; `cancel_event` → `cancelled=True`; `out_format: txt` writes a `.txt`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf.py -k "translate_pdf" -v`
Expected: FAIL (`translate_pdf` not implemented).

- [ ] **Step 3: Implement `translate_pdf`**

1. `input_p.stat().st_size > cfg.pdf.max_pdf_bytes` → `InputValidationError`.
2. `pages, extract_warnings = extract_pdf_paragraphs(input_path, cfg=cfg)`.
3. `len(pages) > cfg.pdf.max_pages` → `InputValidationError`.
4. Flatten + dedupe paragraphs across all pages into `segments: list[StringSegment]` (dedupe by text).
5. `len(segments) > cfg.pdf.max_segments` → `InputValidationError`.
6. Loop segments (concurrency = 1), same pattern as `translate_word`: cancel check, max_chars skip, `auto` direction, protect → `run_translation` → restore, record counts.
7. Re-assemble `translated_pages` by replacing each page's paragraphs with their translations (lookup by original text; untranslated → original).
8. Branch on `cfg.pdf.out_format`: `"docx"` → `build_docx_from_paragraphs(translated_pages, rtl=(direction=="ar-en"))`; `"txt"` → `build_txt_from_paragraphs(translated_pages)`.
9. Atomic write to `output_path`.
10. Return `PdfTranslationReport(total_pages=len(pages), total_segments=len(segments), translated=..., skipped=..., failed=..., cancelled=..., warnings=extract_warnings + translation_warnings)`.

- [ ] **Step 4: Run integration tests to verify they pass**

Run: `pytest tests/test_pdf.py -k "translate_pdf" -v`
Expected: PASS.

- [ ] **Step 5: Create `commands/pdf.py`**

Mirror `commands/excel.py`/`commands/word.py`. Validate suffix is `.pdf`. Print `PdfTranslationReport` including `total_pages`.

- [ ] **Step 6: Register `pdf` in `commands/__init__.py`** (if not already added in Task 6 Step 4).

- [ ] **Step 7: Write the CliRunner test**

```python
def test_pdf_command_rejects_missing_input(tmp_path):
    from typer.testing import CliRunner
    from src.components.interfaces.cli import app
    runner = CliRunner()
    result = runner.invoke(app, [
        "pdf", "--input", str(tmp_path / "missing.pdf"),
        "--out", str(tmp_path / "out.docx"), "--direction", "ar-en",
    ])
    assert result.exit_code == 1
    assert "input file not found" in result.output
```

- [ ] **Step 8: Run all pdf tests + help**

Run: `pytest tests/test_pdf.py -v` then `python -m src.app pdf --help`
Expected: PASS; `--help` exits 0.

- [ ] **Step 9: Lint + typecheck**

Run: `ruff check src/` then `mypy src/`
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add src/components/interfaces/pdf.py src/components/interfaces/commands/pdf.py src/components/interfaces/commands/__init__.py tests/test_pdf.py
git commit -m "feat: add translate_pdf orchestrator and pdf CLI subcommand"
```

---

## Task 9: Documentation + final verification + OpenSpec archive

**Files:**
- Modify: `README.md` (§2.5 menu table, §6.6 CLI reference)
- Modify: `openspec/changes/add-pdf-word-translation/tasks.md` (check off all tasks)

**Interfaces:**
- Consumes: completed Tasks 1-8.
- Produces: documented, fully-verified feature; archived OpenSpec change.

- [ ] **Step 1: Update `README.md` §2.5 menu table**

Add rows 9 and 10 (Word, PDF) — but note the menu is for `run.bat`; if `run.bat` should also gain entries, update it too (check `run.bat` first). At minimum, document the CLI commands in §6.6:
```
# Translate a Word document (preserves styles, tables, images, tracked changes)
python -m src.app word --input data/source.docx --out data/translated.docx --direction ar-en

# Translate a PDF to a .docx sidecar (or .txt via pdf.out_format: txt)
python -m src.app pdf --input data/source.pdf --out data/translated.docx --direction ar-en
```
Add a note that PDF translation produces a sidecar (does not rewrite the original PDF), and scanned PDFs need OCR first.

- [ ] **Step 2: Run the full test suite**

Run: `pytest --tb=short -q`
Expected: all tests pass (including the existing `tests/test_excel.py` after the `_doc_common.py` move). Record the count.

- [ ] **Step 3: Lint**

Run: `ruff check src/ tests/`
Expected: `All checks passed`.

- [ ] **Step 4: Typecheck**

Run: `mypy src/`
Expected: `Success: no issues found` (record the source file count).

- [ ] **Step 5: Spec validation**

Run: `openspec validate --all`
Expected: all specs + the `add-pdf-word-translation` change pass. Fix any drift between the delta specs and the implemented behavior.

- [ ] **Step 6: Smoke test (manual, requires Ollama running)**

```bash
python -m src.app word --input data/sample.docx --out data/out.docx --direction ar-en
python -m src.app pdf --input data/sample.pdf --out data/out.docx --direction ar-en
```
Confirm output files are produced and open correctly. (Skip if no Ollama available — note it in the run memory.)

- [ ] **Step 7: Archive the OpenSpec change**

Run: `openspec archive add-pdf-word-translation`
Expected: the change moves to `openspec/changes/archive/<date>-add-pdf-word-translation/` and `openspec validate --all` still passes.

- [ ] **Step 8: Final commit**

```bash
git add README.md openspec/changes/add-pdf-word-translation/tasks.md
git commit -m "docs: document word and pdf commands; archive openspec change"
```

---

## Self-Review Notes

**Spec coverage:** Every design section maps to a task — §3.1 Word adapter → Tasks 4-6; §3.2 PDF adapter → Tasks 7-8; §3.3 Config → Task 2; §3.4 DTOs → Task 3; §3.5 CLI → Tasks 6, 8; §3.6 Security → folded into every helper task (defusedxml, validate_zip_path, escape_xml_text used in Tasks 4, 7); §6 OpenSpec → Task 0; §7 Verification → Task 9.

**Type consistency:** `StringSegment`, `protect_non_translatable`, `restore_protected`, `ProgressCallback` all defined once in `_doc_common.py` (Task 1) and imported by `word.py`, `pdf.py`, `excel.py`. `WordTranslationReport`/`PdfTranslationReport` defined once in `models.py` (Task 3). `translate_word`/`translate_pdf` signatures mirror `translate_excel` (keyword-only adapters, `progress`/`cancel_event` optional). `WordConfig`/`PdfConfig` field names match what the orchestrators read (`cfg.word.max_docx_bytes`, `cfg.pdf.max_pdf_bytes`, `cfg.pdf.out_format`, etc.).

**Placeholder scan:** No "TBD"/"TODO" in tasks. The one open item is the PDF fixture provenance (Task 7 Step 2) — the plan explicitly says to commit a small fixture and document its provenance, or generate at test time. This is a concrete decision point, not a placeholder.
