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
