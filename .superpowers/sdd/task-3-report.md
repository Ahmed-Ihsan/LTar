# Task 3 Report: PDF — tighten pure-number filter

## What was implemented

Tightened the `_PURE_NUMBER_RE` regex in `src/components/interfaces/pdf.py` so
that the Arabic Unicode block (`\u0600-\u06FF`) is no longer matched. The regex
now matches only ASCII digits, whitespace, commas, periods, and hyphens. This
prevents short Arabic numeric/letter content (e.g. Arabic-Indic digits
`١٢٣٤`) from being silently dropped as "page numbers".

### Changes

**`src/components/interfaces/pdf.py`**
- Line 65-69: Replaced `_PURE_NUMBER_RE` pattern `^[\d\s,.\u0600-\u06FF]+$`
  with `^[0-9\s,.\-]+$` and added an explanatory comment.
- Lines 76-78: Updated the `_segment_page` docstring to state that ASCII
  pure-number blocks are skipped and Arabic-Indic digits/Arabic letters are
  preserved.

**`tests/test_pdf.py`**
- Added `test_preserves_arabic_indic_digit_blocks` (after
  `test_skips_pure_number_blocks`) asserting `١٢٣٤` is preserved.
- Added `test_preserves_arabic_letter_block_with_period` asserting an
  Arabic-only block `المادة.` is preserved.

## TDD evidence

### RED (Step 2)
```
tests/test_pdf.py::TestSegmentPage::test_preserves_arabic_indic_digit_blocks FAILED
  assert ['المادة الأولى.'] == ['١٢٣٤', 'المادة الأولى.']
  (١٢٣٤ dropped by old regex including \u0600-\u06FF)
1 failed, 1 passed, 32 deselected in 0.22s
```
`test_preserves_arabic_letter_block_with_period` already passed pre-fix because
Arabic letters satisfy the `any(c.isalpha())` guard; it remains a useful
regression guard for the tightened regex.

### GREEN (Step 4)
```
tests/test_pdf.py::TestSegmentPage::test_skips_pure_number_blocks PASSED
tests/test_pdf.py::TestSegmentPage::test_preserves_arabic_indic_digit_blocks PASSED
tests/test_pdf.py::TestSegmentPage::test_preserves_arabic_letter_block_with_period PASSED
tests/test_pdf.py::TestSegmentPage::test_skip_header_footer_drops_short_end_blocks PASSED
4 passed, 30 deselected in 0.06s
```

### Full PDF test file (Step 5)
```
34 passed, 129 warnings in 17.83s
```

### Lint / type-check
- `ruff check src/components/interfaces/pdf.py tests/test_pdf.py` →
  **All checks passed!**
- `mypy src/components/interfaces/pdf.py` → no errors in `pdf.py`. The 19
  reported errors are all pre-existing in `src/components/interfaces/commands/*.py`
  (untyped Typer decorators) and are unrelated to this change.

## Files changed
- `src/components/interfaces/pdf.py`
- `tests/test_pdf.py`

## Commit
- `e12fad7` — `fix: stop dropping Arabic-Indic digit blocks in PDF pure-number filter`

## Self-review findings
- The new regex `^[0-9\s,.\-]+$` correctly excludes Arabic-Indic digits
  (U+0660–U+0669) and all Arabic letters, while still matching ASCII page
  numbers like `"1"`, `"2"`, `"12-13"`, `"1,000.00"`.
- The existing `any(c.isalpha())` guard remains as a second line of defense:
  any block containing a letter is never dropped, regardless of the regex.
- Hyphen `-` was added to the character class (the brief's new pattern includes
  it); it is escaped as `\-` at the end of the class to avoid a range
  interpretation. This is a minor behavior addition (previously `-` was not in
  the class) but is consistent with the brief and only affects ASCII
  numeric ranges like `"12-13"`, which are still page-number noise.
- No regressions: all 34 PDF tests pass.

## Concerns
- None. The mypy errors reported are pre-existing and outside the changed file.
