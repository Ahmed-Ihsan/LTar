## ADDED Requirements

### Requirement: Word translation command

The CLI SHALL provide a `word` subcommand that translates a `.docx` document in place: `iraqi-translate word --input <path> --out <path> --direction <ar-en|en-ar|auto> [--config <path>]`. It SHALL construct concrete adapters via the existing `_construct_adapters(cfg) -> Adapters` and call `translate_word(...)`. It SHALL validate the input suffix is `.docx` and exit with code 1 on a missing input file or wrong suffix, without constructing adapters. Domain exceptions from the pipeline SHALL map to the same CLI exit codes as `translate`/`batch`/`excel` (Ollama/embedding/Gemini connection → 2, RAM guard → 3, other domain → 1) via the existing `handle_pipeline_errors` decorator — no new exit code is introduced. The `--input` and `--out` paths SHALL be validated via `src.utils.paths.validate_path_in_root` against the project root; on `PathContainmentError` the command SHALL exit with code 4.

#### Scenario: word command translates a document

- **GIVEN** the CLI is invoked with `word --input contract.docx --out contract_en.docx --direction ar-en`
- **WHEN** the command executes
- **THEN** each human-readable paragraph in the document is translated through the pipeline and a new `.docx` is written to `contract_en.docx` with all non-text artifacts (styles, tables, images, headers, footers, footnotes, comments, hyperlinks, tracked changes, custom XML parts) preserved byte-for-byte

#### Scenario: word command rejects a missing input file

- **GIVEN** the CLI is invoked with `word --input missing.docx --out out.docx --direction ar-en`
- **WHEN** the command executes
- **THEN** it prints an error and exits with code 1 without constructing adapters

#### Scenario: word command rejects a non-docx input

- **GIVEN** the CLI is invoked with `word --input report.pdf --out out.docx --direction ar-en`
- **WHEN** the command executes
- **THEN** it prints an error naming the expected `.docx` suffix and exits with code 1 without constructing adapters

#### Scenario: word command maps a RAM guard error to exit code 3

- **GIVEN** the pipeline raises `RAMGuardError` during a `word` run
- **WHEN** the command catches it
- **THEN** it prints a RAM-guard message and exits with code 3

#### Scenario: word command maps a path-containment error to exit code 4

- **GIVEN** the CLI is invoked with `word --input /etc/passwd --out out.docx --direction ar-en`
- **WHEN** `validate_path_in_root` raises `PathContainmentError`
- **THEN** the command exits with code 4

#### Scenario: word command auto-detects direction per paragraph

- **GIVEN** a `.docx` with mixed Arabic and English paragraphs and `--direction auto`
- **WHEN** the command executes
- **THEN** each paragraph's direction is resolved by `orchestration.detect_direction` (Arabic-dominant → `ar-en`, Latin-dominant → `en-ar`) and translated accordingly

### Requirement: Word translation orchestration

`translate_word(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> WordTranslationReport` SHALL be the orchestration seam. It SHALL: (1) check `input_path.stat().st_size <= cfg.word.max_docx_bytes` and raise `InputValidationError` otherwise; (2) read the input document bytes; (3) extract the deduplicated set of translatable paragraph segments via the pure Word XML helpers; (4) check `len(segments) <= cfg.word.max_segments` and raise `InputValidationError` otherwise; (5) translate each unique source paragraph exactly once by calling the existing `run_translation(input_text, direction, cfg, ...)` seam (concurrency = 1 per the RAM rule); (6) patch the translated paragraphs back into a new `.docx`; (7) write the output document atomically (`tmp_path = output_p.with_suffix(output_p.suffix + ".tmp")`; write; `os.replace(tmp_path, output_p)`). All adapter dependencies are keyword-only (DIP). Per-segment translation failures (`LLMRuntimeError` / `EmbeddingError`) SHALL be recorded as warnings with the original text preserved; the remaining segments SHALL still be processed. If `cancel_event` becomes set, processing SHALL stop after the current segment; already-translated segments are patched; remaining segments keep their original text; and the report records `cancelled=True`.

#### Scenario: each unique paragraph is translated once

- **GIVEN** a `.docx` whose body references the same Arabic paragraph from 10 cells/tables
- **WHEN** `translate_word` runs
- **THEN** `run_translation` is called exactly once for that paragraph and all 10 occurrences receive the same translation

#### Scenario: progress is reported per segment

- **GIVEN** a `progress` callback accepting `(completed, total, current_source)`
- **WHEN** `translate_word` runs over a document with N unique segments
- **THEN** the callback is invoked after each segment with monotonically increasing `completed`

#### Scenario: cancellation stops the run early

- **GIVEN** a `cancel_event` that becomes set after the third segment
- **WHEN** `translate_word` runs
- **THEN** it stops processing further segments, writes the partial document (segments already translated are patched; remaining segments keep their original text), and the report records `cancelled=True`

#### Scenario: a per-segment translation failure keeps the original text

- **GIVEN** `run_translation` raises `LLMRuntimeError` for one paragraph
- **WHEN** `translate_word` runs
- **THEN** that paragraph is left untranslated (original text preserved), a warning is recorded in the report, and the remaining paragraphs are still processed

#### Scenario: an oversized document is rejected

- **GIVEN** a `.docx` whose file size exceeds `cfg.word.max_docx_bytes`
- **WHEN** `translate_word` runs
- **THEN** it raises `InputValidationError` before reading the file body

#### Scenario: a document with too many segments is rejected

- **GIVEN** a `.docx` with more than `cfg.word.max_segments` unique translatable paragraphs
- **WHEN** `translate_word` runs
- **THEN** it raises `InputValidationError` after extraction and before any LLM call

### Requirement: Word XML extraction and patching (pure helpers)

The pure helpers `extract_word_strings(docx_bytes, *, cfg) -> list[StringSegment]` and `patch_word_strings(docx_bytes, translations, *, cfg) -> bytes` SHALL operate on document bytes with **no dependency on the pipeline or adapters**. Extraction SHALL collect text from this allowlist of OOXML locations only: (a) `word/document.xml` `w:p` paragraphs' `w:t` runs (body, tables, text boxes); (b) `word/headerN.xml` and `word/footerN.xml` `w:t` runs (when `cfg.word.translate_headers_footers`); (c) `word/footnotes.xml` `w:t` runs (when `cfg.word.translate_footnotes`); (d) `word/endnotes.xml` `w:t` runs (when `cfg.word.translate_endnotes`); (e) `word/comments.xml` `w:t` runs (when `cfg.word.translate_comments`); (f) `word/glossary/document.xml` `w:t` runs (only when `cfg.word.translate_glossary_doc`, default `False`). Extraction SHALL concatenate all `w:t` text within a `w:p` into a single paragraph string (inserting a space between runs when the previous run's text does not end in whitespace AND the next does not start with whitespace), deduplicate by the concatenated paragraph text, and skip empty / whitespace-only paragraphs; it SHALL NOT apply the `max_segment_chars` filter (that is the orchestrator's policy). Patching SHALL, for each `w:p`, look up the concatenated paragraph text in `translations` and, if found, split the translated text across the original `w:t` runs proportionally by their original character lengths via `split_translation(translation, run_lengths) -> list[str]`, escaping each chunk via `src.utils.xml_escape.escape_xml_text` before assigning to `el.text`. Every part not in the allowlist (styles, themes, fonts, numbering, settings, embedded images, drawings, shapes, hyperlink relationships, tracked-change `w:ins`/`w:del` wrappers, custom XML parts) SHALL be preserved byte-for-byte.

**Security:** Both helpers SHALL parse XML with `defusedxml.ElementTree.fromstring` (not `xml.etree.ElementTree.fromstring`) to defend against XXE and entity-expansion attacks. Both helpers SHALL validate every zip entry name via `src.utils.zip_safe.validate_zip_path` before reading or writing, rejecting absolute paths and `..` traversal segments. `patch_word_strings` SHALL escape every translated chunk via `src.utils.xml_escape.escape_xml_text` before assigning to `el.text`, so that LLM output containing `</w:t>`, `<script>`, or `&` cannot corrupt the document XML.

#### Scenario: body paragraphs are extracted and patched

- **GIVEN** a `.docx` with `word/document.xml` containing `<w:p><w:r><w:t>عقد البيع</w:t></w:r></w:p>`
- **WHEN** `extract_word_strings` then `patch_word_strings` run with the translation "contract of sale"
- **THEN** the patched `word/document.xml` contains `<w:t xml:space="preserve">contract of sale</w:t>` and the paragraph renders the translated text

#### Scenario: a paragraph split across runs is translated as one unit and re-split

- **GIVEN** a paragraph `<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Very </w:t></w:r><w:r><w:t>Important Article</w:t></w:r></w:p>`
- **WHEN** `extract_word_strings` runs
- **THEN** it returns one segment with text `"Very Important Article"` (concatenated with a space)
- **WHEN** `patch_word_strings` runs with the translation `"مهم جدا"`
- **THEN** the patched document has the translation split across the two original `w:t` runs, preserving the bold formatting on the first run

#### Scenario: styles, images, and tracked changes are preserved byte-for-byte

- **GIVEN** a `.docx` with a custom style, an embedded image, and a tracked-change `w:ins` wrapper
- **WHEN** the document is translated
- **THEN** the `word/styles.xml`, `word/media/image1.png`, and `w:ins` XML parts are identical in the input and output zips

#### Scenario: headers, footers, and footnotes are translated when enabled

- **GIVEN** a `.docx` with `word/header1.xml`, `word/footer1.xml`, and `word/footnotes.xml` containing Arabic text and `cfg.word.translate_headers_footers=True` and `cfg.word.translate_footnotes=True`
- **WHEN** the document is translated
- **THEN** the header, footer, and footnote `w:t` runs are translated; the rest of those parts is preserved

#### Scenario: comments are skipped when the toggle is false

- **GIVEN** a `.docx` with `word/comments.xml` containing Arabic text and `cfg.word.translate_comments=False`
- **WHEN** the document is translated
- **THEN** `word/comments.xml` is copied byte-for-byte unchanged

#### Scenario: a glossary document part is skipped by default

- **GIVEN** a `.docx` with `word/glossary/document.xml` containing Arabic text and `cfg.word.translate_glossary_doc=False` (the default)
- **WHEN** the document is translated
- **THEN** `word/glossary/document.xml` is copied byte-for-byte unchanged

#### Scenario: defusedxml defends against XXE

- **GIVEN** a `.docx` whose `word/document.xml` contains an XXE entity reference
- **WHEN** `extract_word_strings` parses it
- **THEN** `defusedxml.ElementTree.fromstring` refuses to resolve the entity (no file read, no expansion) and the part is skipped safely

### Requirement: PDF translation command

The CLI SHALL provide a `pdf` subcommand that translates a `.pdf` document to a sidecar file: `iraqi-translate pdf --input <path> --out <path> --direction <ar-en|en-ar|auto> [--config <path>]`. The output format is selected by `cfg.pdf.out_format` (`docx` default, or `txt`). It SHALL construct concrete adapters via the existing `_construct_adapters(cfg) -> Adapters` and call `translate_pdf(...)`. It SHALL validate the input suffix is `.pdf` and exit with code 1 on a missing input file or wrong suffix, without constructing adapters. Domain exceptions from the pipeline SHALL map to the same CLI exit codes as `translate`/`batch`/`excel`/`word` (connection → 2, RAM guard → 3, other → 1) via `handle_pipeline_errors`. The `--input` and `--out` paths SHALL be validated via `src.utils.paths.validate_path_in_root`; on `PathContainmentError` the command SHALL exit with code 4. The command SHALL NOT rewrite the original PDF; it SHALL write the sidecar to `--out`.

#### Scenario: pdf command translates to a docx sidecar

- **GIVEN** the CLI is invoked with `pdf --input statute.pdf --out statute_en.docx --direction ar-en` and `cfg.pdf.out_format: docx`
- **WHEN** the command executes
- **THEN** text is extracted per page, each paragraph is translated through the pipeline, and a new `.docx` is written to `statute_en.docx` with one paragraph per source paragraph and a page break between original pages; the original `statute.pdf` is unchanged

#### Scenario: pdf command translates to a txt sidecar

- **GIVEN** the CLI is invoked with `pdf --input statute.pdf --out statute_en.txt --direction ar-en` and `cfg.pdf.out_format: txt`
- **WHEN** the command executes
- **THEN** a new `.txt` is written to `statute_en.txt` with paragraphs joined by blank lines and a `--- page break ---` marker between original pages

#### Scenario: pdf command rejects a missing input file

- **GIVEN** the CLI is invoked with `pdf --input missing.pdf --out out.docx --direction ar-en`
- **WHEN** the command executes
- **THEN** it prints an error and exits with code 1 without constructing adapters

#### Scenario: pdf command rejects a non-pdf input

- **GIVEN** the CLI is invoked with `pdf --input report.docx --out out.docx --direction ar-en`
- **WHEN** the command executes
- **THEN** it prints an error naming the expected `.pdf` suffix and exits with code 1 without constructing adapters

#### Scenario: pdf command maps a RAM guard error to exit code 3

- **GIVEN** the pipeline raises `RAMGuardError` during a `pdf` run
- **WHEN** the command catches it
- **THEN** it prints a RAM-guard message and exits with code 3

#### Scenario: pdf command maps a path-containment error to exit code 4

- **GIVEN** the CLI is invoked with `pdf --input /etc/passwd --out out.docx --direction ar-en`
- **WHEN** `validate_path_in_root` raises `PathContainmentError`
- **THEN** the command exits with code 4

#### Scenario: pdf command auto-detects direction per paragraph

- **GIVEN** a `.pdf` with mixed Arabic and English paragraphs and `--direction auto`
- **WHEN** the command executes
- **THEN** each paragraph's direction is resolved by `orchestration.detect_direction` and translated accordingly

### Requirement: PDF translation orchestration

`translate_pdf(input_path, output_path, direction, cfg, *, llm, embedder, glossary_index=None, persist_dir=None, run_logger=None, tm=None, progress=None, cancel_event=None) -> PdfTranslationReport` SHALL be the orchestration seam. It SHALL: (1) check `input_path.stat().st_size <= cfg.pdf.max_pdf_bytes` and raise `InputValidationError` otherwise; (2) extract per-page paragraphs via `extract_pdf_paragraphs(input_path, cfg=cfg)`; (3) check `len(pages) <= cfg.pdf.max_pages` and raise `InputValidationError` otherwise; (4) flatten and deduplicate paragraphs across all pages into a segment list; (5) check `len(segments) <= cfg.pdf.max_segments` and raise `InputValidationError` otherwise; (6) translate each unique source paragraph exactly once via `run_translation` (concurrency = 1); (7) re-assemble the translated pages by replacing each paragraph with its translation (untranslated → original); (8) branch on `cfg.pdf.out_format`: `"docx"` → `build_docx_from_paragraphs(translated_pages, rtl=(direction=="ar-en"))`, `"txt"` → `build_txt_from_paragraphs(translated_pages)`; (9) write the sidecar atomically. All adapter dependencies are keyword-only (DIP). Per-segment translation failures SHALL be recorded as warnings with the original text preserved. If `cancel_event` becomes set, processing SHALL stop after the current segment and the report records `cancelled=True`. Pages that yielded no extractable text SHALL be recorded in `warnings` as `"Page N: no extractable text (scanned PDF?)."` and skipped.

#### Scenario: each unique paragraph is translated once

- **GIVEN** a `.pdf` where the same Arabic paragraph appears on pages 1 and 3
- **WHEN** `translate_pdf` runs
- **THEN** `run_translation` is called exactly once for that paragraph and both pages receive the same translation

#### Scenario: a scanned page is recorded as a warning

- **GIVEN** a `.pdf` whose page 2 is a scanned image (no extractable text)
- **WHEN** `translate_pdf` runs
- **THEN** the report's `warnings` contains `"Page 2: no extractable text (scanned PDF?)."` and page 2 contributes no segments

#### Scenario: cancellation stops the run early

- **GIVEN** a `cancel_event` that becomes set after the third segment
- **WHEN** `translate_pdf` runs
- **THEN** it stops processing further segments, writes the partial sidecar (translated paragraphs replaced; remaining paragraphs keep their original text), and the report records `cancelled=True`

#### Scenario: an oversized PDF is rejected

- **GIVEN** a `.pdf` whose file size exceeds `cfg.pdf.max_pdf_bytes`
- **WHEN** `translate_pdf` runs
- **THEN** it raises `InputValidationError` before extracting any text

#### Scenario: a PDF with too many pages is rejected

- **GIVEN** a `.pdf` with more than `cfg.pdf.max_pages` pages
- **WHEN** `translate_pdf` runs
- **THEN** it raises `InputValidationError` after the page count check and before any LLM call

#### Scenario: the docx sidecar sets RTL for ar-en output

- **GIVEN** `translate_pdf` runs with `direction="ar-en"` and `cfg.pdf.out_format="docx"`
- **WHEN** the sidecar is written
- **THEN** every paragraph in the generated `word/document.xml` has `<w:bidiVisual/>` in its `<w:pPr>`

#### Scenario: the docx sidecar sets LTR for en-ar output

- **GIVEN** `translate_pdf` runs with `direction="en-ar"` and `cfg.pdf.out_format="docx"`
- **WHEN** the sidecar is written
- **THEN** no `<w:bidiVisual/>` element appears in the generated `word/document.xml`

### Requirement: PDF text extraction and sidecar writers (pure helpers)

The pure helpers `extract_pdf_paragraphs(pdf_path, *, cfg) -> tuple[list[list[str]], list[str]]`, `build_docx_from_paragraphs(pages, *, rtl) -> bytes`, and `build_txt_from_paragraphs(pages) -> str` SHALL have **no dependency on the pipeline or adapters**. `extract_pdf_paragraphs` SHALL lazy-import `pypdf.PdfReader` inside the function body (so the `word`/`excel`/`translate`/`batch`/`ui` code paths never import `pypdf`); iterate `reader.pages`; call `page.extract_text()`; for each page with no extractable text, append an empty list and record a warning; for each non-empty page, segment into paragraphs via `_segment_page` (split on `\n\s*\n`, collapse internal newlines to spaces, optionally drop short top/bottom header/footer blocks when `cfg.pdf.skip_header_footer`, skip empty blocks and pure-number blocks). `build_docx_from_paragraphs` SHALL produce a valid minimal `.docx` zip (`[Content_Types].xml`, `_rels/.rels`, `word/_rels/document.xml.rels`, `word/document.xml`) with one `<w:p>` per paragraph, a `<w:br w:type="page"/>` between pages, and `<w:bidiVisual/>` in `<w:pPr>` only when `rtl=True`. Every paragraph SHALL be escaped via `src.utils.xml_escape.escape_xml_text` before insertion. `build_txt_from_paragraphs` SHALL join paragraphs with `\n\n` and pages with `\n\n--- page break ---\n\n`.

#### Scenario: extract_pdf_paragraphs segments a page into paragraphs

- **GIVEN** a `.pdf` page whose extracted text is `"Article 1.\n\nالمادة الأولى.\n\nArticle 2."`
- **WHEN** `extract_pdf_paragraphs` runs
- **THEN** the page's paragraph list is `["Article 1.", "المادة الأولى.", "Article 2."]`

#### Scenario: extract_pdf_paragraphs skips pure-number blocks

- **GIVEN** a `.pdf` page whose extracted text is `"1\n\nArticle 1.\n\n2"` (page numbers embedded)
- **WHEN** `extract_pdf_paragraphs` runs
- **THEN** the page's paragraph list is `["Article 1."]` (the pure-number blocks are dropped)

#### Scenario: extract_pdf_paragraphs records a warning for a scanned page

- **GIVEN** a `.pdf` whose page 2 yields no extractable text
- **WHEN** `extract_pdf_paragraphs` runs
- **THEN** `pages[1]` is `[]` and `warnings` contains `"Page 2: no extractable text (scanned PDF?)."`

#### Scenario: build_docx_from_paragraphs produces a valid zip

- **GIVEN** `pages = [["Paragraph one", "Paragraph two"], ["Page two"]]` and `rtl=True`
- **WHEN** `build_docx_from_paragraphs` runs
- **THEN** the returned bytes are a valid zip containing `word/document.xml`, the document XML contains `<w:bidiVisual/>` and `Paragraph one`, and a `<w:br w:type="page"/>` appears between the two pages

#### Scenario: build_txt_from_paragraphs includes a page-break marker

- **GIVEN** `pages = [["a"], ["b"]]`
- **WHEN** `build_txt_from_paragraphs` runs
- **THEN** the returned string contains `"a"`, `"b"`, and `"--- page break ---"`

#### Scenario: pypdf is not imported on the word/excel paths

- **GIVEN** `extract_pdf_paragraphs` has not been called
- **WHEN** `import src.components.interfaces.word` and `import src.components.interfaces.excel` run
- **THEN** `pypdf` is NOT present in `sys.modules` (lazy import is confined to `extract_pdf_paragraphs`)

### Requirement: Non-translatable token protection (shared with excel)

The existing `protect_non_translatable(text) -> tuple[str, dict[str, str]]` and `restore_protected(text, token_map) -> str` helpers SHALL be moved from `src/components/interfaces/excel.py` to a new shared module `src/components/interfaces/_doc_common.py` so that `excel.py`, `word.py`, and `pdf.py` all reuse them. `excel.py` SHALL re-export them from `_doc_common` so existing callers (`from src.components.interfaces.excel import protect_non_translatable`) keep working without changes. The helpers' behavior SHALL be unchanged: `protect_non_translatable` replaces URLs, email addresses, pure numbers, `${...}` / `{...}` / `<...>` / `%...%` placeholders, and Excel header/footer `&`-codes with stable `\x00TN\x00` sentinels; `restore_protected` restores them verbatim after translation. The `StringSegment` frozen dataclass and the `ProgressCallback` protocol SHALL also move to `_doc_common.py` and be re-exported from `excel.py`.

#### Scenario: excel still imports protect_non_translatable after the move

- **GIVEN** the `_doc_common.py` extraction is complete
- **WHEN** `from src.components.interfaces.excel import protect_non_translatable, restore_protected, StringSegment, ProgressCallback` runs
- **THEN** all four symbols are importable (re-exported from `_doc_common`)

#### Scenario: word and pdf import the shared helpers

- **GIVEN** the `_doc_common.py` extraction is complete
- **WHEN** `from src.components.interfaces._doc_common import protect_non_translatable, restore_protected, StringSegment, ProgressCallback` runs
- **THEN** all four symbols are importable directly from `_doc_common`

#### Scenario: protect/restore behavior is unchanged

- **GIVEN** the existing `tests/test_excel.py` protect/restore tests
- **WHEN** they run against the moved helpers
- **THEN** they pass unchanged (the move is mechanical; behavior is identical)

### Requirement: WordTranslationReport model

`WordTranslationReport` (in `src/components/interfaces/models.py`) SHALL be a frozen dataclass (slots=True) recording: `total_segments: int`, `translated: int`, `skipped: int`, `failed: int`, `cancelled: bool`, and `warnings: list[str]`. It is returned by `translate_word` and printed by the CLI. `skipped` covers paragraphs left untranslated due to cancellation or the `max_segment_chars` cap; `failed` covers paragraphs whose translation raised a domain error or returned empty output (the original text is preserved in both cases).

#### Scenario: report counts are consistent

- **GIVEN** a `.docx` with 10 unique paragraphs where 9 translated and 1 failed
- **WHEN** `translate_word` completes
- **THEN** the report has `total_segments=10`, `translated=9`, `failed=1`, `cancelled=False`

### Requirement: PdfTranslationReport model

`PdfTranslationReport` (in `src/components/interfaces/models.py`) SHALL be a frozen dataclass (slots=True) recording: `total_pages: int`, `total_segments: int`, `translated: int`, `skipped: int`, `failed: int`, `cancelled: bool`, and `warnings: list[str]`. It is returned by `translate_pdf` and printed by the CLI. `total_pages` is the page count of the source PDF. `warnings` records per-page extraction issues (e.g. a page that yielded no extractable text) plus per-segment translation warnings.

#### Scenario: report carries page count

- **GIVEN** a 5-page `.pdf` with 20 unique paragraphs where 18 translated, 1 skipped, 1 failed
- **WHEN** `translate_pdf` completes
- **THEN** the report has `total_pages=5`, `total_segments=20`, `translated=18`, `skipped=1`, `failed=1`, `cancelled=False`

### Requirement: Word and PDF features respect hard constraints

The Word and PDF features SHALL respect the project hard constraints: no cloud calls (except the existing opt-in Gemini backend), no telemetry, single in-flight translation (concurrency = 1), 8 GB RAM ceiling (Word: stream per-part XML processing, only allowlisted text-bearing parts held in memory; PDF: stream pages one at a time via `pypdf`'s lazy page reader, no whole-PDF in-memory model). The only new runtime dependency SHALL be `pypdf>=4.0,<5` (pure Python, MIT-licensed, offline, lazy-imported inside `pdf.py`); the Word adapter SHALL use only the Python standard library plus the existing `defusedxml` dependency. No new telemetry, no new network calls, no new native binaries.

#### Scenario: the word adapter imports no third-party packages

- **GIVEN** the implemented `word.py`
- **WHEN** its imports are inspected
- **THEN** it imports only from the Python standard library, `defusedxml`, and `src.*` project modules — never `python-docx`, `lxml`, `pypdf`, or any other third-party package

#### Scenario: the pdf adapter imports pypdf lazily

- **GIVEN** the implemented `pdf.py`
- **WHEN** its top-level imports are inspected
- **THEN** `pypdf` is NOT imported at module top level; the `import pypdf` statement appears only inside `extract_pdf_paragraphs`

#### Scenario: pypdf is not imported when only word is used

- **GIVEN** a user runs `iraqi-translate word --input in.docx --out out.docx --direction ar-en`
- **WHEN** the command completes
- **THEN** `pypdf` is NOT present in `sys.modules` at any point during the run

#### Scenario: concurrency is 1

- **GIVEN** a `translate_word` or `translate_pdf` run over N segments
- **WHEN** the run executes
- **THEN** `run_translation` is never called concurrently with itself (no parallel translation jobs), per the RAM rule
