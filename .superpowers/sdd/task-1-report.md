# Task 1 Report — Word: whole-translation-in-first-run (split_translation)

## Status: DONE

## What I Implemented

Replaced the proportional character-length split in `split_translation`
(`src/components/interfaces/word.py`) with a whole-translation-in-first-run
strategy: the entire translation goes in the first `w:t` run, all subsequent
runs are emptied. This preserves the first run's formatting (the paragraph's
dominant run) for the whole translation and never slices a word across runs.

Removed the now-unused helpers that only the old proportional split needed:
- `_SENTINEL_RE` constant (was line 92)
- `_sentinel_spans` function
- `_snap_out_of_sentinel` function

Verified `import re` is still required and used by `_is_allowlisted_part`
(via `re.match` for header/footer part names) — kept the import.
`_doc_common.py`'s own `_SENTINEL_RE` was NOT touched.

## TDD Evidence

### RED (Step 2) — updated tests fail against old proportional behavior

Command:
```
$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests/test_word.py::TestSplitTranslation -v
```
Result: **4 failed, 2 passed** — failures show old proportional output:
- `test_whole_translation_in_first_run`: `['the', ' qui...ro', 'wn fox']` != `['the quick brown fox', '', '', '']`
- `test_zero_run_lengths`: `['h', 'e', 'llo']` != `['hello', '', '']`
- `test_remainder_goes_to_last_run`: `['abc', 'defg']` != `['abcdefg', '']`
- `test_split_does_not_break_protected_sentinel`: `'See '` != full protected string

### GREEN (Step 4) — after rewriting split_translation

Command:
```
$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests/test_word.py::TestSplitTranslation -v
```
Result: **6 passed in 0.06s**

### Patch test (Step 6)

Command:
```
$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest "tests/test_word.py::TestExtractPatch::test_patch_multi_run_whole_translation_in_first_run" -v
```
Result: **1 passed in 0.09s** — structurally verified first `w:t` == "مهم جدا", second `w:t` empty.

### Full Word test file (Step 7)

Command:
```
$env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests/test_word.py -q
```
Result: **34 passed, 147 warnings in 11.42s** — no regressions.

## Lint / Type-check

- `ruff check src/components/interfaces/word.py tests/test_word.py` → **All checks passed!**
  (Note: the brief's test imported `_P, _R, _T` but used `_W_MAIN` directly in
  f-strings, so ruff flagged them as unused [F401]. Trimmed the import to
  `_W_MAIN` only — functionally identical, just satisfies the linter.)
- `mypy src/components/interfaces/word.py` → 19 errors, ALL pre-existing in
  `commands/*.py` (typer decorator `has-type`/`untyped-decorator`), NONE in
  `word.py`. Verified identical 19 errors exist on baseline commit `389c1cf`
  via `git stash` comparison. Zero new type errors introduced.

## Files Changed

- `src/components/interfaces/word.py` — rewrote `split_translation`; removed
  `_SENTINEL_RE`, `_sentinel_spans`, `_snap_out_of_sentinel`; updated section
  header comment from "proportional split" to "whole-translation-in-first-run
  split".
- `tests/test_word.py` — replaced `TestSplitTranslation` class body (6 new
  tests asserting whole-run behavior); renamed
  `test_patch_multi_run_proportional_split` →
  `test_patch_multi_run_whole_translation_in_first_run` with structural
  assertions (first `w:t` holds full translation, second `w:t` empty).

## Commit

```
f044e46 fix: place whole Word translation in first run instead of proportional split
2 files changed, 54 insertions(+), 114 deletions(-)
```

## Self-Review Findings

- The new `split_translation` is a pure, deterministic helper — no sentinel
  snapping needed because the whole translation lives in one run, so a
  protected-token sentinel can never straddle a run boundary. The
  `test_split_does_not_break_protected_sentinel` test confirms
  `restore_protected` recovers the original token cleanly.
- `_paragraph_text` still computes `run_lengths` and `_patch_part` still
  passes them to `split_translation`; the lengths are now only used to size
  the output list (`len(run_lengths)`), not to proportionally slice. This
  keeps the public signature stable for existing callers/tests.
- Empty-translation and zero-run-length edge cases handled: `n==0` → `[]`,
  `n==1` → `[translation]`, else `[translation] + [""]*(n-1)`.
- No references to the removed helpers remain in any source/test file (only
  in docs/brief markdown, which is expected).
- `_doc_common.py`'s own `_SENTINEL_RE` confirmed untouched.

## Concerns

None. The change is minimal, behavior-preserving for single-run paragraphs
(the common case), and fixes the multi-run formatting-corruption bug as
specified.
