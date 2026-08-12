## MODIFIED Requirements

### Requirement: Word XML extraction and patching (pure helpers)

The pure helpers `extract_word_strings(docx_bytes, *, cfg) -> list[StringSegment]` and `patch_word_strings(docx_bytes, translations, *, cfg) -> bytes` SHALL operate on document bytes with **no dependency on the pipeline or adapters**. Extraction SHALL collect text from this allowlist of OOXML locations only: (a) `word/document.xml` `w:p` paragraphs' `w:t` runs (body, tables, text boxes); (b) `word/headerN.xml` and `word/footerN.xml` `w:t` runs (when `cfg.word.translate_headers_footers`); (c) `word/footnotes.xml` `w:t` runs (when `cfg.word.translate_footnotes`); (d) `word/endnotes.xml` `w:t` runs (when `cfg.word.translate_endnotes`); (e) `word/comments.xml` `w:t` runs (when `cfg.word.translate_comments`); (f) `word/glossary/document.xml` `w:t` runs (only when `cfg.word.translate_glossary_doc`, default `False`). Extraction SHALL concatenate all `w:t` text within a `w:p` into a single paragraph string (inserting a space between runs when the previous run's text does not end in whitespace AND the next does not start with whitespace), deduplicate by the concatenated paragraph text, and skip empty / whitespace-only paragraphs; it SHALL NOT apply the `max_segment_chars` filter (that is the orchestrator's policy). Patching SHALL, for each `w:p`, look up the concatenated paragraph text in `translations` and, if found, place the **entire translated text** in the first `w:t` run of the paragraph and set every subsequent `w:t` run's text to the empty string `""`. This whole-translation-in-first-run strategy preserves the first run's formatting (the paragraph's dominant run) for the entire translation and never breaks a word across runs. Each chunk SHALL be escaped via `src.utils.xml_escape.escape_xml_text` before assignment to `el.text`. The `split_translation(translation, run_lengths) -> list[str]` helper SHALL be retained as a compatibility wrapper returning `[translation] + [""] * (len(run_lengths) - 1)` (so existing imports still resolve); its proportional-split logic is removed. Every part not in the allowlist (styles, themes, fonts, numbering, settings, embedded images, drawings, shapes, hyperlink relationships, tracked-change `w:ins`/`w:del` wrappers, custom XML parts) SHALL be preserved byte-for-byte.

**Security:** Both helpers SHALL parse XML with `defusedxml.ElementTree.fromstring` (not `xml.etree.ElementTree.fromstring`) to defend against XXE and entity-expansion attacks. Both helpers SHALL validate every zip entry name via `src.utils.zip_safe.validate_zip_path` before reading or writing, rejecting absolute paths and `..` traversal segments. `patch_word_strings` SHALL escape every translated chunk via `src.utils.xml_escape.escape_xml_text` before assigning to `el.text`, so that LLM output containing `</w:t>`, `<script>`, or `&` cannot corrupt the document XML.

#### Scenario: body paragraphs are extracted and patched

- **GIVEN** a `.docx` with `word/document.xml` containing `<w:p><w:r><w:t>عقد البيع</w:t></w:r></w:p>`
- **WHEN** `extract_word_strings` then `patch_word_strings` run with the translation "contract of sale"
- **THEN** the patched `word/document.xml` contains `<w:t xml:space="preserve">contract of sale</w:t>` and the paragraph renders the translated text

#### Scenario: a paragraph split across runs is translated as one unit and placed in the first run

- **GIVEN** a paragraph `<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Very </w:t></w:r><w:r><w:t>Important Article</w:t></w:r></w:p>`
- **WHEN** `extract_word_strings` runs
- **THEN** it returns one segment with text `"Very Important Article"` (concatenated with a space)
- **WHEN** `patch_word_strings` runs with the translation `"مهم جدا"`
- **THEN** the patched document has the **entire** translation `"مهم جدا"` in the first `w:t` run (which carries the bold `w:rPr`), the second `w:t` run is set to the empty string `""`, and no word is broken across runs

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

#### Scenario: split_translation is a compatibility wrapper placing the whole translation in the first run

- **GIVEN** `split_translation("the quick brown fox", [3, 5, 5, 3])` is called
- **WHEN** it returns
- **THEN** the result is `["the quick brown fox", "", "", ""]` — the entire translation in the first slot, empty strings for the remaining runs, and no word is broken across runs

## ADDED Requirements

### Requirement: Word RTL/bidi paragraph direction on patching

When `cfg.word.set_bidi_direction` is `True` (the default), `patch_word_strings` SHALL adjust each patched paragraph's direction to match the dominant script of its translated text: (a) if the translated text is Arabic-dominant (resolved via `orchestration.detect_direction(translation) == "ar-en"`), the paragraph SHALL contain a `<w:bidiVisual/>` element in its `<w:pPr>` (creating `<w:pPr>` if absent); (b) if the translated text is Latin-dominant (`detect_direction(translation) == "en-ar"`), any existing `<w:bidiVisual/>` element SHALL be removed from the paragraph's `<w:pPr>` (and the `<w:pPr>` is removed if it becomes empty). When `cfg.word.set_bidi_direction` is `False`, paragraph direction SHALL NOT be modified (the original paragraph properties are preserved byte-for-byte, matching the pre-change behavior). The direction check uses the same `detect_direction` helper the orchestrator uses for `auto` direction resolution, applied to the *translation* (not the source).

#### Scenario: an Arabic-dominant translation gets bidiVisual added

- **GIVEN** a paragraph `<w:p><w:r><w:t>Hello</w:t></w:r></w:p>` (no `<w:pPr>`) and the translation `"مرحبا"` (Arabic-dominant)
- **WHEN** `patch_word_strings` runs with `cfg.word.set_bidi_direction=True`
- **THEN** the patched paragraph contains `<w:pPr><w:bidiVisual/></w:pPr>` and the first `w:t` holds `"مرحبا"`

#### Scenario: a Latin-dominant translation has bidiVisual removed

- **GIVEN** a paragraph `<w:p><w:pPr><w:bidiVisual/></w:pPr><w:r><w:t>مرحبا</w:t></w:r></w:p>` and the translation `"Hello"` (Latin-dominant)
- **WHEN** `patch_word_strings` runs with `cfg.word.set_bidi_direction=True`
- **THEN** the patched paragraph's `<w:pPr>` no longer contains `<w:bidiVisual/>`

#### Scenario: set_bidi_direction=False preserves original paragraph direction

- **GIVEN** a paragraph with no `<w:pPr>` and an Arabic-dominant translation, with `cfg.word.set_bidi_direction=False`
- **WHEN** `patch_word_strings` runs
- **THEN** the paragraph's `<w:pPr>` is unchanged (no `<w:bidiVisual/>` is added); only the `w:t` text is replaced

#### Scenario: an empty pPr is removed when bidiVisual was its only child

- **GIVEN** a paragraph `<w:p><w:pPr><w:bidiVisual/></w:pPr><w:r><w:t>مرحبا</w:t></w:r></w:p>` and the Latin-dominant translation `"Hello"`
- **WHEN** `patch_word_strings` runs with `cfg.word.set_bidi_direction=True`
- **THEN** the `<w:pPr>` element is removed (it became empty after `<w:bidiVisual/>` removal); the paragraph is `<w:p><w:r><w:t ...>Hello</w:t></w:r></w:p>`

### Requirement: PDF pure-number filter tightened to ASCII digits only

The `_PURE_NUMBER_RE` regex used by `_segment_page` to skip page-number blocks SHALL match only blocks composed of ASCII digits (`0-9`), whitespace, comma, period, and hyphen, AND the skip condition SHALL require at least one ASCII digit (`\d`) in the block. Arabic-Indic digits (`\u0660-\u0669`) and Arabic letters (`\u0600-\u06FF`) SHALL NOT be classified as "pure number" noise, so short Arabic numeric or letter-only blocks are preserved and translated rather than silently dropped.

#### Scenario: ASCII pure-number blocks are still dropped

- **GIVEN** a `.pdf` page whose extracted text is `"1\n\nArticle 1.\n\n2"` (ASCII page numbers embedded)
- **WHEN** `extract_pdf_paragraphs` runs
- **THEN** the page's paragraph list is `["Article 1."]` (the ASCII pure-number blocks are dropped)

#### Scenario: Arabic-Indic digit blocks are preserved

- **GIVEN** a `.pdf` page whose extracted text is `"١٢٣٤\n\nالمادة الأولى."` where `١٢٣٤` is Arabic-Indic digits
- **WHEN** `extract_pdf_paragraphs` runs
- **THEN** the page's paragraph list is `["١٢٣٤", "المادة الأولى."]` (the Arabic-Indic digit block is NOT dropped)

#### Scenario: a short Arabic block with no ASCII digits is preserved

- **GIVEN** a `.pdf` page whose extracted text is `"المادة.\n\nArticle 1."` where `"المادة."` is Arabic letters + period
- **WHEN** `extract_pdf_paragraphs` runs
- **THEN** the page's paragraph list is `["المادة.", "Article 1."]` (the Arabic block is NOT classified as a pure-number block)
