## 1. Foundation — shared helpers + config + DTOs

- [x] 1.1 Create `src/components/interfaces/_doc_common.py`: move `StringSegment`, `ProgressCallback`, `_SENTINEL_OPEN`/`_SENTINEL_CLOSE`/`_SENTINEL_RE`, `_PROTECTION_PATTERNS`, `protect_non_translatable`, `restore_protected` verbatim out of `excel.py`. Add `__all__`. Generalize the `_translate_segment` helper (currently in `excel.py`) into `_doc_common.py` so both `excel.py` and `word.py` can import it.
- [x] 1.2 Modify `src/components/interfaces/excel.py`: delete the moved definitions; add `from src.components.interfaces._doc_common import (ProgressCallback, StringSegment, protect_non_translatable, restore_protected, _translate_segment)`; keep them in `excel.py`'s `__all__` for backward compatibility.
- [x] 1.3 Verify: `pytest tests/test_excel.py -v` passes unchanged (the move is mechanical; excel behavior is pinned by its existing tests).
- [x] 1.4 Add `WordConfig` Pydantic model to `src/config/models.py` (fields + validators per the `config` delta spec).
- [x] 1.5 Add `PdfConfig` Pydantic model to `src/config/models.py` (fields + validators per the `config` delta spec).
- [x] 1.6 Wire `word: WordConfig = Field(default_factory=WordConfig)` and `pdf: PdfConfig = Field(default_factory=PdfConfig)` into `AppConfig` in `src/config/config.py`; update the `from src.config.models import ...` line.
- [x] 1.7 Add `word:` and `pdf:` sections to `config.yaml` with documented defaults (per `design.md` §config.yaml addition).
- [x] 1.8 Verify: `python -c "from src.config import AppConfig; c=AppConfig(); assert c.word.translate_comments and c.pdf.out_format=='docx'"` — defaults apply when sections absent.
- [x] 1.9 Add `WordTranslationReport` and `PdfTranslationReport` frozen dataclasses (slots=True) to `src/components/interfaces/models.py` (fields per the `interfaces` delta spec).
- [x] 1.10 Verify: `pytest tests/test_config.py tests/test_models.py -v` passes (add new test cases for `WordConfig`/`PdfConfig` defaults + validation + the two new DTOs); `ruff check src/config/ src/components/interfaces/_doc_common.py src/components/interfaces/excel.py src/components/interfaces/models.py`; `mypy src/`.
- [x] 1.11 Commit: `refactor: extract protect/restore helpers to _doc_common; add WordConfig/PdfConfig and report DTOs`

## 2. Word adapter — pure XML helpers

- [x] 2.1 Create `src/components/interfaces/word.py`: WordprocessingML namespace registration (`w`), tag constants (`_W_T`, `_W_P`, `_W_R`, `_W_BR`, `_W_BIDI`, `_W_PPR`, `_W_RPR`), module docstring.
- [x] 2.2 Implement `_is_word_text_part(name, cfg) -> bool` — allowlist `word/document.xml` (always); `word/headerN.xml`/`word/footerN.xml` (when `cfg.word.translate_headers_footers`); `word/footnotes.xml` (when `cfg.word.translate_footnotes`); `word/endnotes.xml` (when `cfg.word.translate_endnotes`); `word/comments.xml` (when `cfg.word.translate_comments`); `word/glossary/document.xml` (only when `cfg.word.translate_glossary_doc`).
- [x] 2.3 Implement `_paragraph_text(p_el) -> tuple[str, list[int]]` — walk `w:t` children of `w:r` children of `w:p` in document order; concatenate; insert a space between runs when the previous run's text does not end in whitespace AND the next does not start with whitespace; return `(text, run_lengths)`.
- [x] 2.4 Implement `extract_word_strings(docx_bytes, *, cfg) -> list[StringSegment]` — open the zip; validate every entry name via `src.utils.zip_safe.validate_zip_path`; parse each allowlisted part with `defusedxml.ElementTree.fromstring`; for each `w:p` collect `_paragraph_text`; dedupe by concatenated text; skip empty/whitespace-only; record `StringSegment(part=name, text=text)`. Do NOT apply `max_segment_chars` (orchestrator's policy).
- [x] 2.5 Implement `split_translation(translation, run_lengths) -> list[str]` — proportional split by char count; if `sum(run_lengths) == 0`, distribute evenly; never return empty chunks for non-empty input (remainder to the last run).
- [x] 2.6 Implement `patch_word_strings(docx_bytes, translations, *, cfg) -> bytes` — re-open the zip; copy every part byte-for-byte except allowlisted parts; for allowlisted parts, parse with `defusedxml`, for each `w:p` re-walk the `w:t` runs in order, look up the concatenated paragraph text in `translations`, `split_translation` the result across the runs by their original lengths, escape each chunk via `src.utils.xml_escape.escape_xml_text` before assigning to `el.text`; re-serialize with `ET.tostring(root, encoding="UTF-8", xml_declaration=True)`; validate every zip entry name via `validate_zip_path`.
- [x] 2.7 Verify: `pytest tests/test_word.py -k "extract_word_strings or patch_word_strings or split_translation" -v` passes (unit tests with programmatically-built minimal `.docx` fixtures — no binary committed).
- [x] 2.8 Verify: `ruff check src/components/interfaces/word.py`; `mypy src/`.
- [x] 2.9 Commit: `feat: add Word XML extract/patch/split pure helpers`

## 3. Word adapter — orchestrator

- [x] 3.1 Implement `translate_word(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> WordTranslationReport` in `word.py` per `design.md` §word.py orchestrator (mirror `excel.py`'s `translate_excel`; reuse `_translate_segment` from `_doc_common`).
- [x] 3.2 Verify: `pytest tests/test_word.py -k "translate_word" -v` passes (integration tests with `mock_llm`/`mock_embedder`: dedup, progress, cancel, per-segment failure, oversize `max_docx_bytes`, oversize `max_segments`).
- [x] 3.3 Verify: `ruff check src/components/interfaces/word.py`; `mypy src/`.
- [x] 3.4 Commit: `feat: add translate_word orchestrator reusing run_translation`

## 4. Word CLI command

- [x] 4.1 Create `src/components/interfaces/commands/word.py` mirroring `commands/excel.py` (swap `excel`→`word`, `.xlsx`→`.docx`, `translate_excel`→`translate_word`, `ExcelTranslationReport`→`WordTranslationReport`); validate suffix is `.docx`; decorate with `@_cli.app.command()` and `@handle_pipeline_errors`.
- [x] 4.2 Register `word` in `src/components/interfaces/commands/__init__.py` (alphabetical, between `translate` and `ui`).
- [x] 4.3 Add `"src/components/interfaces/word.py" = ["PLR0913"]` and `"src/components/interfaces/pdf.py" = ["PLR0913"]` to `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`.
- [x] 4.4 Verify: `pytest tests/test_word.py -k "word_command" -v` passes (CliRunner test: missing input → exit 1; wrong suffix → exit 1); `python -m src.app word --help` exits 0.
- [x] 4.5 Verify: `ruff check src/`; `mypy src/`.
- [x] 4.6 Commit: `feat: add word CLI subcommand`

## 5. PDF adapter — dependency + pure helpers + sidecar writers

- [x] 5.1 Add `pypdf>=4.0,<5` to `requirements.txt` (new "PDF text extraction" section, lazy-import note) and to `pyproject.toml` `[project] dependencies`. Run `pip install pypdf` (or `pip install -e .`) in the dev env. Verify the published version is ≥ 7 days old (project rule).
- [x] 5.2 Create `src/components/interfaces/pdf.py`: module docstring, WordprocessingML namespace registration (for the sidecar writer), tag constants.
- [x] 5.3 Implement `extract_pdf_paragraphs(pdf_path, *, cfg) -> tuple[list[list[str]], list[str]]` — lazy-import `pypdf.PdfReader` inside the function; iterate `reader.pages`; `page.extract_text()`; empty → warning + empty list; else `_segment_page`.
- [x] 5.4 Implement `_segment_page(text, *, cfg) -> list[str]` — split on `\n\s*\n`; collapse internal newlines to spaces; if `cfg.pdf.skip_header_footer`, drop short top/bottom blocks containing only digits/roman numerals/single words; skip empty blocks and pure-number blocks.
- [x] 5.5 Implement `build_docx_from_paragraphs(pages, *, rtl: bool) -> bytes` — minimal `.docx` zip with `[Content_Types].xml`, `_rels/.rels`, `word/_rels/document.xml.rels`, `word/document.xml`; one `<w:p>` per paragraph; `<w:br w:type="page"/>` between pages; `<w:bidiVisual/>` in `<w:pPr>` only when `rtl=True`; escape every paragraph via `escape_xml_text`.
- [x] 5.6 Implement `build_txt_from_paragraphs(pages) -> str` — join paragraphs with `\n\n`; join pages with `\n\n--- page break ---\n\n`.
- [x] 5.7 Add a single small (≤ 50 KB) 2-page Arabic legal PDF fixture to `tests/fixtures/pdf/` plus a `README.md` documenting its provenance. (If a fixture cannot be legally committed, generate one at test time using `pypdf`'s `PageObject` with a manually-built content stream — document the chosen approach in the test module docstring.)
- [x] 5.8 Verify: `pytest tests/test_pdf.py -k "extract_pdf_paragraphs or build_docx_from_paragraphs or build_txt_from_paragraphs" -v` passes (extraction test uses the committed fixture; writer tests are pure).
- [x] 5.9 Verify: `ruff check src/components/interfaces/pdf.py`; `mypy src/` (if `pypdf` types are missing, add `# type: ignore[import-untyped]` on the lazy import line only).
- [x] 5.10 Commit: `feat: add PDF text extraction and docx/txt sidecar writers`

## 6. PDF adapter — orchestrator + CLI command

- [x] 6.1 Implement `translate_pdf(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> PdfTranslationReport` in `pdf.py` per `design.md` §pdf.py orchestrator.
- [x] 6.2 Verify: `pytest tests/test_pdf.py -k "translate_pdf" -v` passes (integration tests with mock adapters: dedup, scanned-page warning, cancel, oversize `max_pdf_bytes`, oversize `max_pages`, oversize `max_segments`, `out_format: txt`, RTL for `ar-en`, LTR for `en-ar`).
- [x] 6.3 Create `src/components/interfaces/commands/pdf.py` mirroring `commands/excel.py`/`commands/word.py` (validate suffix is `.pdf`; print `PdfTranslationReport` including `total_pages`).
- [x] 6.4 Register `pdf` in `src/components/interfaces/commands/__init__.py` (alphabetical, between `ingest` and `tm_add`).
- [x] 6.5 Verify: `pytest tests/test_pdf.py -k "pdf_command" -v` passes (CliRunner: missing input → exit 1; wrong suffix → exit 1); `python -m src.app pdf --help` exits 0.
- [x] 6.6 Verify: `ruff check src/`; `mypy src/`.
- [x] 6.7 Commit: `feat: add translate_pdf orchestrator and pdf CLI subcommand`

## 7. Documentation + final verification + OpenSpec archive

- [x] 7.1 Update `README.md` §2.5 (run.bat menu if applicable) and §6.6 (CLI reference): document `word` and `pdf` commands; note that PDF translation produces a sidecar (does not rewrite the original) and scanned PDFs need OCR first.
- [x] 7.2 Verify: `pytest --tb=short -q` — full suite passes (including `tests/test_excel.py` after the `_doc_common.py` move). Record the count.
- [x] 7.3 Verify: `ruff check src/ tests/` — `All checks passed`.
- [x] 7.4 Verify: `mypy src/` — `Success: no issues found` (record the source file count).
- [x] 7.5 Verify: `openspec validate --all` — all specs + the `add-pdf-word-translation` change pass. Fix any drift between the delta specs and the implemented behavior.
- [x] 7.6 Smoke test (manual, requires Ollama running): `python -m src.app word --input data/sample.docx --out data/out.docx --direction ar-en` and `python -m src.app pdf --input data/sample.pdf --out data/out.docx --direction ar-en`. Confirm output files are produced and open correctly. (Skip if no Ollama available — note it in the run memory.)
- [x] 7.7 Archive: `openspec archive add-pdf-word-translation`. Verify `openspec validate --all` still passes after archiving.
- [x] 7.8 Commit: `docs: document word and pdf commands; archive openspec change`
