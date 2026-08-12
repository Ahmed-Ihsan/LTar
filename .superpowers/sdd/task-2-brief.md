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
