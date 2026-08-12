# fix-word-pdf-translation-quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three confirmed Word/PDF translation quality defects — Word proportional run-split that breaks words mid-character across formatted runs, Word missing RTL/bidi paragraph direction for Arabic output, and the PDF pure-number filter that silently drops Arabic-Indic digit blocks.

**Architecture:** Three independent, test-first fixes in the existing `word.py`, `pdf.py`, and `config/models.py` modules. No new files, no new dependencies. The OpenSpec change proposal `fix-word-pdf-translation-quality` (validated, all 4 artifacts complete) is the contract; this plan implements its `tasks.md`.

**Tech Stack:** Python 3.11, Pydantic 2.6, defusedxml, pypdf, pytest, ruff, mypy (strict), OpenSpec 1.5.

## Global Constraints

- 8 GB RAM ceiling; concurrency = 1; no cloud calls except opt-in Gemini; no telemetry.
- `ruff` line-length = 100; `mypy strict = true`; target `py311`.
- Prompts are versioned code — do not reformat (not touched by this plan).
- Adapters are the trust boundary; depend on protocols, not concretions.
- TDD: write the failing test first, run it red, implement, run it green, commit.
- Conventional commits: `fix:`, `feat:`.
- The OpenSpec change `fix-word-pdf-translation-quality` MUST remain valid after each task; archive it only in the final verification task.

---

## Task 1: Word — whole-translation-in-first-run (split_translation)

**Files:**
- Modify: `src/components/interfaces/word.py:238-279` (`split_translation`)
- Test: `tests/test_word.py:162-208` (`TestSplitTranslation`)

**Interfaces:**
- Consumes: none (pure helper).
- Produces: `split_translation(translation: str, run_lengths: list[int]) -> list[str]` returning `[translation] + [""] * (len(run_lengths) - 1)`.

- [ ] **Step 1: Update `TestSplitTranslation` tests to assert the new whole-run behavior**

In `tests/test_word.py`, replace the body of `class TestSplitTranslation` (lines 162–208) with:

```python
class TestSplitTranslation:
    def test_whole_translation_in_first_run(self) -> None:
        # The entire translation goes in the first run; remaining runs are
        # emptied. No word is ever broken across runs.
        chunks = split_translation("the quick brown fox", [3, 5, 5, 3])
        assert chunks == ["the quick brown fox", "", "", ""]
        assert "".join(chunks) == "the quick brown fox"

    def test_single_run(self) -> None:
        chunks = split_translation("contract of sale", [16])
        assert chunks == ["contract of sale"]

    def test_empty_translation(self) -> None:
        chunks = split_translation("", [3, 5])
        assert chunks == ["", ""]

    def test_zero_run_lengths(self) -> None:
        # Even with zero-length runs, the whole translation still goes in
        # the first slot.
        chunks = split_translation("hello", [0, 0, 0])
        assert chunks == ["hello", "", ""]

    def test_remainder_goes_to_last_run(self) -> None:
        # Compatibility: the last run still receives any "remainder" in the
        # sense that it is the last non-empty slot when there is one run.
        chunks = split_translation("abcdefg", [3, 3])
        assert chunks == ["abcdefg", ""]

    def test_split_does_not_break_protected_sentinel(self) -> None:
        # A protected-token sentinel (`\x00T0\x00`, 4 chars) is never split
        # across two runs because the whole translation lives in the first
        # run. restore_protected applied per-run recovers the original token.
        from src.components.interfaces._doc_common import restore_protected

        sentinel = "\x00T0\x00"
        token_map = {sentinel: "https://example.com"}
        protected = "See " + sentinel + " for details"
        chunks = split_translation(protected, [4, 4, 9])
        # Whole translation in the first run; other runs empty.
        assert chunks[0] == protected
        restored = "".join(restore_protected(c, token_map) for c in chunks)
        assert restored == "See https://example.com for details"
        assert "\x00" not in restored
```

- [ ] **Step 2: Run the updated tests to verify they FAIL**

Run: `pytest tests/test_word.py::TestSplitTranslation -v`
Expected: FAIL — `split_translation("the quick brown fox", [3,5,5,3])` returns `["the", " quic", "k bro", "wn fox"]` (old proportional behavior), not `["the quick brown fox", "", "", ""]`.

- [ ] **Step 3: Rewrite `split_translation` in `src/components/interfaces/word.py`**

Replace the entire `split_translation` function (lines 238–279) and remove the now-unused `_sentinel_spans` / `_snap_out_of_sentinel` helpers (lines 220–235) since the wrapper no longer needs sentinel snapping. The new function:

```python
def split_translation(translation: str, run_lengths: list[int]) -> list[str]:
    """Place the entire ``translation`` in the first run; empty the rest.

    The whole-translation-in-first-run strategy preserves the first run's
    formatting (the paragraph's dominant run) for the entire translation and
    never breaks a word across runs. Source-language run boundaries do not
    map to target-language word boundaries, so proportional splitting only
    corrupted formatting by slicing words mid-character.

    Returns a list of ``len(run_lengths)`` strings: ``[translation] + [""] * (n - 1)``.
    Kept as a compatibility wrapper so existing callers/tests of the public
    helper still resolve; the proportional-split logic is removed.
    """
    n: int = len(run_lengths)
    if n == 0:
        return []
    if n == 1:
        return [translation]
    return [translation] + [""] * (n - 1)
```

Also remove the `_SENTINEL_RE` constant (line 92) and the `_sentinel_spans` / `_snap_out_of_sentinel` functions (lines 220–235) since they are no longer referenced. Keep the module docstring's mention of sentinels accurate by removing the now-stale paragraph at lines 87–92, OR leave a one-line note that `split_translation` no longer needs sentinel snapping. Prefer removing the stale comment block to keep docs truthful.

- [ ] **Step 4: Run the updated tests to verify they PASS**

Run: `pytest tests/test_word.py::TestSplitTranslation -v`
Expected: PASS — all 6 tests green.

- [ ] **Step 5: Update `test_patch_multi_run_proportional_split` to assert whole-run placement**

In `tests/test_word.py`, rename and update the test at lines 302–314:

```python
    def test_patch_multi_run_whole_translation_in_first_run(self, config: AppConfig) -> None:
        docx = _build_docx()
        out = patch_word_strings(
            docx, {"Very Important Article": "مهم جدا"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        # The ENTIRE translation "مهم جدا" is in the first w:t run (which
        # carries the bold w:rPr); the second w:t run is empty.
        assert "مهم جدا" in body
        assert "w:b" in body  # bold formatting preserved on the first run
        # The original English text is gone from the second paragraph.
        assert "Important Article" not in body
        # Verify structurally: the second w:t in the multi-run paragraph is empty.
        from defusedxml.ElementTree import fromstring as ET_fromstring
        from src.components.interfaces.word import _W_MAIN, _P, _R, _T
        doc = ET_fromstring(_read_part(out, "word/document.xml"))
        paras = doc.findall(f".//{{{_W_MAIN}}}p")
        multi_run_p = paras[1]  # "Very Important Article" paragraph
        runs = multi_run_p.findall(f".//{{{_W_MAIN}}}r")
        t_els = [r.find(f"{{{_W_MAIN}}}t") for r in runs if r.find(f"{{{_W_MAIN}}}t") is not None]
        assert t_els[0].text == "مهم جدا"
        assert (t_els[1].text or "") == ""
```

- [ ] **Step 6: Run the patch test to verify it PASSES**

Run: `pytest tests/test_word.py::TestPatchWordStrings::test_patch_multi_run_whole_translation_in_first_run -v`
Expected: PASS (the `_patch_part` change in Step 3 already routes through the new `split_translation`).

- [ ] **Step 7: Run the full Word test file to confirm no regressions**

Run: `pytest tests/test_word.py -q`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/components/interfaces/word.py tests/test_word.py
git commit -m "fix: place whole Word translation in first run instead of proportional split"
```

---

## Task 2: Word — RTL/bidi paragraph direction

**Files:**
- Modify: `src/config/models.py:103-141` (`WordConfig` — add `set_bidi_direction`)
- Modify: `src/components/interfaces/word.py:293-328` (`_patch_part` — bidi handling)
- Test: `tests/test_config.py` (add `set_bidi_direction` tests)
- Test: `tests/test_word.py` (add `TestBidiDirection` class)

**Interfaces:**
- Consumes: `orchestration.detect_direction` (lazy import inside `_patch_part`).
- Produces: `WordConfig.set_bidi_direction: bool = True`; `_patch_part` adjusts `<w:bidiVisual/>` in patched paragraphs' `<w:pPr>`.

- [ ] **Step 1: Add `set_bidi_direction` field to `WordConfig`**

In `src/config/models.py`, inside `class WordConfig` (after line 118 `translate_glossary_doc: bool = False`), add:

```python
    set_bidi_direction: bool = True
```

So the field block becomes:

```python
    translate_comments: bool = True
    translate_headers_footers: bool = True
    translate_footnotes: bool = True
    translate_endnotes: bool = True
    translate_glossary_doc: bool = False
    set_bidi_direction: bool = True
    max_segment_chars: int = 8192
    max_docx_bytes: int = 50 * 1024 * 1024
    max_segments: int = 20000
```

- [ ] **Step 2: Write the config test for `set_bidi_direction`**

In `tests/test_config.py`, add (find the existing WordConfig test class or add a new test function following the file's existing style):

```python
def test_word_config_set_bidi_direction_default_true() -> None:
    from src.config.models import WordConfig
    cfg = WordConfig()
    assert cfg.set_bidi_direction is True


def test_word_config_set_bidi_direction_override_false() -> None:
    from src.config.models import WordConfig
    cfg = WordConfig(set_bidi_direction=False)
    assert cfg.set_bidi_direction is False
```

- [ ] **Step 3: Run the config tests to verify they PASS**

Run: `pytest tests/test_config.py -q -k "set_bidi_direction"`
Expected: PASS (the field has a default, so Pydantic accepts it).

- [ ] **Step 4: Write failing bidi tests in `tests/test_word.py`**

Add a new test class at the end of `tests/test_word.py`:

```python
class TestBidiDirection:
    """Word RTL/bidi paragraph direction is set to match the translation script."""

    def _build_single_para_docx(self, paragraph_xml: str) -> bytes:
        """Build a one-paragraph .docx for bidi tests."""
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{paragraph_xml}</w:body></w:document>'
        )
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CONTENT_TYPES)
            z.writestr("_rels/.rels", _ROOT_RELS)
            z.writestr("word/document.xml", document)
            z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        return buf.getvalue()

    def test_arabic_translation_gets_bidi_visual(self, config: AppConfig) -> None:
        # Source English paragraph with NO w:pPr; translation is Arabic.
        para = '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"Hello": "مرحبا"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" in body
        assert "مرحبا" in body

    def test_latin_translation_removes_bidi_visual(self, config: AppConfig) -> None:
        # Source Arabic paragraph WITH w:bidiVisual; translation is English.
        para = '<w:p><w:pPr><w:bidiVisual/></w:pPr><w:r><w:t>مرحبا</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"مرحبا": "Hello"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body
        assert "Hello" in body

    def test_set_bidi_direction_false_preserves_original(self, config: AppConfig) -> None:
        # With set_bidi_direction=False, the pPr is NOT modified.
        cfg = config.model_copy(update={"word": config.word.model_copy(
            update={"set_bidi_direction": False})})
        para = '<w:p><w:r><w:t>Hello</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"Hello": "مرحبا"}, cfg=cfg)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body  # not added
        assert "مرحبا" in body  # text still replaced

    def test_empty_ppr_removed_when_bidi_was_only_child(self, config: AppConfig) -> None:
        # Source Arabic paragraph where w:bidiVisual is the ONLY pPr child;
        # Latin translation -> remove bidi -> pPr becomes empty -> remove pPr.
        para = '<w:p><w:pPr><w:bidiVisual/></w:pPr><w:r><w:t>مرحبا</w:t></w:r></w:p>'
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"مرحبا": "Hello"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body
        assert "<w:pPr>" not in body  # empty pPr removed
        assert "Hello" in body

    def test_other_ppr_children_preserved_when_bidi_removed(self, config: AppConfig) -> None:
        # pPr has spacing AND bidi; Latin translation -> remove bidi only,
        # spacing stays.
        para = ('<w:p><w:pPr><w:spacing w:after="120"/><w:bidiVisual/></w:pPr>'
                '<w:r><w:t>مرحبا</w:t></w:r></w:p>')
        docx = self._build_single_para_docx(para)
        out = patch_word_strings(docx, {"مرحبا": "Hello"}, cfg=config)
        body = _read_part(out, "word/document.xml").decode("utf-8")
        assert "<w:bidiVisual/>" not in body
        assert '<w:spacing w:after="120"/>' in body  # other pPr child kept
        assert "Hello" in body
```

- [ ] **Step 5: Run the bidi tests to verify they FAIL**

Run: `pytest tests/test_word.py::TestBidiDirection -v`
Expected: FAIL — `test_arabic_translation_gets_bidi_visual` fails because no `<w:bidiVisual/>` is added (current code has no bidi handling); `test_latin_translation_removes_bidi_visual` fails because the existing `<w:bidiVisual/>` is preserved byte-for-byte (not removed).

- [ ] **Step 6: Implement bidi handling in `_patch_part`**

In `src/components/interfaces/word.py`, modify `_patch_part` (lines 293–328). Add the bidi logic after the run-text assignment loop, inside the `if new is None or new == text: continue` block's else path. Add the namespace constants `_PPR` and `_BIDI` near the existing `_RPR` constant (line 85):

```python
_PPR: str = f"{{{NS_W}}}pPr"
_BIDI: str = f"{{{NS_W}}}bidiVisual"
```

Replace `_patch_part` with:

```python
def _patch_part(
    data: bytes,
    name: str,
    translations: dict[str, str],
    cfg: AppConfig,
) -> bytes:
    """Re-serialize one allowlisted Word part with translated paragraph text."""
    try:
        root = ET_fromstring(data)
    except (ET.ParseError, DefusedXmlException):
        # Cannot parse (incl. XXE-rejected DOCTYPE) -> return original bytes
        # unchanged (fail safe).
        return data
    set_bidi: bool = cfg.word.set_bidi_direction
    for p_el in root.iter(_P):
        text, run_lengths = _paragraph_text(p_el)
        if not text.strip():
            continue
        new = translations.get(text)
        if new is None or new == text:
            continue
        # Collect the w:t elements in document order (same walk as
        # _paragraph_text) and place the whole translation in the first run.
        t_els: list[ET.Element] = []
        for r_el in p_el.iter(_R):
            t_el = r_el.find(_T)
            if t_el is not None:
                t_els.append(t_el)
        if not t_els:
            continue
        chunks = split_translation(new, run_lengths)
        for t_el, chunk in zip(t_els, chunks, strict=True):
            t_el.text = escape_xml_text(chunk)
            # Preserve leading/trailing whitespace in the run.
            if chunk and (chunk[0].isspace() or chunk[-1].isspace()):
                t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        # Adjust paragraph RTL/bidi direction to match the translation script.
        if set_bidi:
            _adjust_bidi_direction(p_el, new)
    return _serialize_part(root)
```

Add the `_adjust_bidi_direction` helper just above `_patch_part`:

```python
def _adjust_bidi_direction(p_el: ET.Element, translation: str) -> None:
    """Set or remove ``<w:bidiVisual/>`` in the paragraph's ``<w:pPr>`` to
    match the dominant script of ``translation``.

    Arabic-dominant translation -> ensure ``<w:bidiVisual/>`` exists.
    Latin-dominant translation  -> remove ``<w:bidiVisual/>`` (and remove
    ``<w:pPr>`` if it becomes empty).

    Uses the same ``detect_direction`` script heuristic the orchestrator uses
    for ``auto`` direction resolution, applied to the *translation* (the
    paragraph direction should match the output language, not the input).
    """
    from src.components.interfaces.orchestration import detect_direction

    is_rtl: bool = detect_direction(translation) == "ar-en"
    ppr: ET.Element | None = p_el.find(_PPR)
    if is_rtl:
        if ppr is None:
            ppr = ET.Element(_PPR)
            # pPr MUST be the first child of w:p per the OOXML schema.
            p_el.insert(0, ppr)
        if ppr.find(_BIDI) is None:
            bidi = ET.Element(_BIDI)
            ppr.insert(0, bidi)
    else:
        if ppr is not None:
            bidi = ppr.find(_BIDI)
            if bidi is not None:
                ppr.remove(bidi)
            # Remove pPr if it became empty to avoid leaving an empty
            # paragraph-properties element.
            if len(list(ppr)) == 0:
                p_el.remove(ppr)
```

- [ ] **Step 7: Run the bidi tests to verify they PASS**

Run: `pytest tests/test_word.py::TestBidiDirection -v`
Expected: PASS — all 5 tests green.

- [ ] **Step 8: Run the full Word test file to confirm no regressions**

Run: `pytest tests/test_word.py -q`
Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add src/config/models.py src/components/interfaces/word.py tests/test_config.py tests/test_word.py
git commit -m "feat: set Word paragraph RTL/bidi direction to match translation script"
```

---

## Task 3: PDF — tighten pure-number filter

**Files:**
- Modify: `src/components/interfaces/pdf.py:66` (`_PURE_NUMBER_RE`)
- Test: `tests/test_pdf.py:136-139` (`test_skips_pure_number_blocks` + new test)

**Interfaces:**
- Consumes: none.
- Produces: `_PURE_NUMBER_RE` matching only ASCII digits + whitespace/comma/period/hyphen.

- [ ] **Step 1: Write the failing test for Arabic-Indic digit preservation**

In `tests/test_pdf.py`, inside the `_segment_page` test class (after `test_skips_pure_number_blocks` at line 139), add:

```python
    def test_preserves_arabic_indic_digit_blocks(self, config: AppConfig) -> None:
        # Arabic-Indic digits (U+0660..U+0669) must NOT be classified as
        # pure-number page-number noise — they are legitimate content.
        text = "١٢٣٤\n\nالمادة الأولى."
        paras = _segment_page(text, cfg=config)
        assert paras == ["١٢٣٤", "المادة الأولى."]

    def test_preserves_arabic_letter_block_with_period(self, config: AppConfig) -> None:
        # An Arabic block with no ASCII digits must not be dropped.
        text = "المادة.\n\nArticle 1."
        paras = _segment_page(text, cfg=config)
        assert paras == ["المادة.", "Article 1."]
```

- [ ] **Step 2: Run the new tests to verify they FAIL**

Run: `pytest tests/test_pdf.py -v -k "arabic_indic or arabic_letter"`
Expected: FAIL — `test_preserves_arabic_indic_digit_blocks` fails because `١٢٣٤` matches the current regex `^[\d\s,.\u0600-\u06FF]+$` (Arabic range included) and is dropped.

- [ ] **Step 3: Tighten `_PURE_NUMBER_RE` in `src/components/interfaces/pdf.py`**

Change line 66 from:

```python
_PURE_NUMBER_RE: re.Pattern[str] = re.compile(r"^[\d\s,.\u0600-\u06FF]+$")
```

to:

```python
# A block that is only ASCII digits, commas, periods, hyphens, or whitespace
# (page numbers). Arabic-Indic digits and Arabic letters are intentionally
# excluded so legitimate Arabic numeric/letter content is not dropped.
_PURE_NUMBER_RE: re.Pattern[str] = re.compile(r"^[0-9\s,.\-]+$")
```

Also update the docstring of `_segment_page` (lines 72–79) to reflect the tightened filter — change "pure-number blocks (page numbers)" to "ASCII pure-number blocks (page numbers); Arabic-Indic digits and Arabic letters are preserved".

- [ ] **Step 4: Run the new tests AND the existing pure-number test to verify all PASS**

Run: `pytest tests/test_pdf.py -v -k "pure_number or arabic_indic or arabic_letter or header_footer"`
Expected: PASS — `test_skips_pure_number_blocks` still drops ASCII `"1"` and `"2"`; the two new Arabic tests preserve the Arabic blocks.

- [ ] **Step 5: Run the full PDF test file to confirm no regressions**

Run: `pytest tests/test_pdf.py -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/interfaces/pdf.py tests/test_pdf.py
git commit -m "fix: stop dropping Arabic-Indic digit blocks in PDF pure-number filter"
```

---

## Task 4: Final verification

**Files:** none modified — verification only.

- [ ] **Step 1: Run the full test suite (excludes slow)**

Run: `pytest --tb=short -q`
Expected: all tests PASS, 0 failures.

- [ ] **Step 2: Run ruff lint**

Run: `ruff check src/ tests/`
Expected: clean (0 issues). If `word.py` flags unused imports (e.g. `re` still imported but `_SENTINEL_RE` removed), remove the now-unused import — but verify `re` is still used by `_is_allowlisted_part` (it is, via `re.match`) before deciding.

- [ ] **Step 3: Run mypy strict**

Run: `mypy src/`
Expected: clean (0 errors). Watch for unused-import errors from the removed `_sentinel_spans` / `_snap_out_of_sentinel` helpers.

- [ ] **Step 4: Run radon complexity**

Run: `radon cc src/components/interfaces/word.py src/components/interfaces/pdf.py -a`
Expected: no new complexity hotspots; `_adjust_bidi_direction` should be `A` or `B` grade.

- [ ] **Step 5: Validate OpenSpec**

Run: `openspec validate --all`
Expected: 0 failures. The `fix-word-pdf-translation-quality` change is valid.

- [ ] **Step 6: Archive the completed change**

Run: `openspec archive fix-word-pdf-translation-quality`
Expected: change merged into `openspec/specs/` and moved to `changes/archive/`. `openspec list` shows no active change.

- [ ] **Step 7: Produce a verification summary**

Write the actual command outputs (test counts, lint result, mypy result, openspec validate result) into the final response to the user. **Evidence before assertions.**
