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
