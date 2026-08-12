# Tasks — fix-word-pdf-translation-quality

## 1. Word: whole-translation-in-first-run (split_translation + _patch_part)

- [ ] 1.1 Update `TestSplitTranslation` in `tests/test_word.py` to assert the new whole-run behavior: `split_translation("the quick brown fox", [3,5,5,3])` returns `["the quick brown fox", "", "", ""]`. Run the test to confirm it FAILS (red).
- [ ] 1.2 Rewrite `split_translation` in `src/components/interfaces/word.py` to return `[translation] + [""] * (len(run_lengths) - 1)` (keep sentinel-snapping import removed; the wrapper no longer needs it). Run the updated test to confirm it PASSES (green).
- [ ] 1.3 Update `test_patch_multi_run_proportional_split` in `tests/test_word.py` to assert the entire translation `"مهم جدا"` is in the first `w:t` run and the second `w:t` is empty. Run to confirm it PASSES (the `_patch_part` change in 1.2 already routes through `split_translation`).
- [ ] 1.4 Run `pytest tests/test_word.py -q` to confirm no regressions in the rest of the Word tests.
- [ ] 1.5 Commit: `fix: place whole Word translation in first run instead of proportional split`

## 2. Word: RTL/bidi paragraph direction

- [ ] 2.1 Add `set_bidi_direction: bool = True` field to `WordConfig` in `src/config/models.py`. Add a config test in `tests/test_config.py` asserting the default is `True` and an explicit `set_bidi_direction: false` override works. Run to confirm the new test PASSES.
- [ ] 2.2 Write failing tests in `tests/test_word.py` (new `TestBidiDirection` class): (a) Arabic-dominant translation gets `<w:bidiVisual/>` added to `<w:pPr>`; (b) Latin-dominant translation has `<w:bidiVisual/>` removed; (c) `set_bidi_direction=False` leaves `<w:pPr>` unchanged; (d) empty `<w:pPr>` is removed when `<w:bidiVisual/>` was its only child. Run to confirm they FAIL (red).
- [ ] 2.3 Implement bidi handling in `_patch_part` in `src/components/interfaces/word.py`: lazily import `detect_direction` from `orchestration`; when `cfg.word.set_bidi_direction` is `True` and the paragraph was patched, adjust `<w:bidiVisual/>` in the paragraph's `<w:pPr>` per design D3/D4. Run the bidi tests to confirm they PASS (green).
- [ ] 2.4 Run `pytest tests/test_word.py -q` to confirm no regressions.
- [ ] 2.5 Commit: `feat: set Word paragraph RTL/bidi direction to match translation script`

## 3. PDF: tighten pure-number filter

- [ ] 3.1 Add a failing test in `tests/test_pdf.py`: `_segment_page("١٢٣٤\n\nالمادة الأولى.", cfg=config)` returns `["١٢٣٤", "المادة الأولى."]` (Arabic-Indic digits preserved). Run to confirm it FAILS (red).
- [ ] 3.2 Change `_PURE_NUMBER_RE` in `src/components/interfaces/pdf.py` from `^[\d\s,.\u0600-\u06FF]+$` to `^[0-9\s,.\-]+$`. Run the new test and the existing `test_skips_pure_number_blocks` to confirm both PASS (green).
- [ ] 3.3 Run `pytest tests/test_pdf.py -q` to confirm no regressions.
- [ ] 3.4 Commit: `fix: stop dropping Arabic-Indic digit blocks in PDF pure-number filter`

## 4. Verification

- [ ] 4.1 Run `pytest --tb=short -q` (full suite, excludes slow). Confirm all pass.
- [ ] 4.2 Run `ruff check src/ tests/`. Confirm clean.
- [ ] 4.3 Run `mypy src/`. Confirm clean (strict).
- [ ] 4.4 Run `openspec validate --all`. Confirm 0 failures.
- [ ] 4.5 Run `radon cc src/ -a` and confirm no new complexity hotspots in `word.py` / `pdf.py`.
- [ ] 4.6 Archive the change: `openspec archive fix-word-pdf-translation-quality`.
