# Design — fix-word-pdf-translation-quality

## Context

The `add-pdf-word-translation` change shipped Word and PDF translation adapters.
Three confirmed defects degrade the saved output:

1. `split_translation` distributes a translation across a paragraph's original
   `w:r` runs by character-length ratio, slicing words mid-character so that
   per-run formatting (bold/italic/color) lands on arbitrary fragments.
2. The Word in-place path never sets paragraph direction (`w:bidiVisual`), so
   English→Arabic output stays LTR and may render wrong in Word.
3. The PDF `_PURE_NUMBER_RE` includes the Arabic Unicode block, so short
   Arabic numeric blocks are silently dropped as "page numbers".

## Goals / Non-Goals

**Goals:**
- Stop breaking words across runs in Word output.
- Set RTL paragraph direction for Arabic-dominant Word translations.
- Stop dropping Arabic-Indic digit blocks in PDF extraction.

**Non-Goals:**
- Per-run formatting fidelity for every original run (the translation is a
  different language; source run boundaries do not map to target words).
- In-place PDF rewrite (still out of scope; sidecar approach unchanged).
- OCR for scanned PDFs (out of scope).
- Form-field / annotation extraction (out of scope).

## Decisions

### D1: Whole-translation-in-first-run (not proportional split)

**Decision:** Place the entire translation in the first `w:t` run of the
paragraph; empty all subsequent `w:t` runs.

**Alternatives considered:**
- *Merge all runs into one run before patching:* more invasive — destroys the
  run structure that other parts of the document (e.g. field codes) may
  reference. Emptying subsequent `w:t` text while keeping the `w:r` wrappers
  is safer.
- *Word-boundary-aware split:* would require an LLM call per paragraph to
  align source and target word boundaries — far too expensive and unreliable
  for agentic translation.
- *Keep proportional split but snap to word boundaries:* partial fix only;
  still assigns wrong formatting to wrong words when run lengths don't align
  with word counts.

**Trade-off:** The first run's formatting is applied to the whole translation;
subsequent runs' formatting (e.g. a single italic word mid-paragraph) is not
represented. This is the correct trade-off: the translation is a different
language, so source-language run boundaries do not correspond to
target-language word boundaries. The first run usually carries the
paragraph's dominant formatting.

### D2: split_translation kept as compatibility wrapper

**Decision:** `split_translation(translation, run_lengths)` returns
`[translation] + [""] * (len(run_lengths) - 1)`. The function signature is
unchanged so existing imports and tests that call it directly still compile.

**Rationale:** Avoids a breaking API change for any external caller; the
function is re-exported in `__all__`.

### D3: RTL/bidi via detect_direction on the translation

**Decision:** When `cfg.word.set_bidi_direction` is `True`, for each patched
paragraph, call `orchestration.detect_direction(translation)`:
- `ar-en` (Arabic-dominant) → ensure `<w:bidiVisual/>` in `<w:pPr>`.
- `en-ar` (Latin-dominant) → remove `<w:bidiVisual/>` from `<w:pPr>`.

**Why detect_direction on the translation, not the source:** The paragraph
direction should match the *output* language, not the input. An English
paragraph translated to Arabic needs RTL; an Arabic paragraph translated to
English needs LTR.

**Implementation note:** `detect_direction` is imported lazily inside
`patch_word_strings` (or `_patch_part`) to avoid a circular import with
`orchestration.py` (which imports from `interfaces` for `run_translation`).
The existing `translate_word` already does this lazy import pattern.

**Toggle:** `cfg.word.set_bidi_direction: bool = True` lets users disable the
behavior for documents that already carry correct direction properties.

### D4: pPr handling — create / remove cleanly

**Decision:**
- If `<w:pPr>` does not exist and we need `<w:bidiVisual/>`, insert a new
  `<w:pPr>` as the first child of `<w:p>`, containing `<w:bidiVisual/>`.
- If `<w:pPr>` exists and we need to remove `<w:bidiVisual/>`, remove the
  child. If `<w:pPr>` becomes empty (no children), remove the `<w:pPr>`
  element entirely to avoid leaving an empty paragraph-properties element.

### D5: PDF pure-number regex tightened to ASCII

**Decision:** `_PURE_NUMBER_RE = ^[\d\s,.\-]+$` and the skip condition requires
`any(c.isdigit() and c.isascii() for c in block)` (or equivalently, the regex
already guarantees only ASCII digits since `\d` in the pattern matches ASCII
digits by default in Python's `re` module without `re.UNICODE`... actually
`\d` matches Unicode digits by default in Python 3. To be safe, the regex
uses explicit `[0-9]` instead of `\d`).

**Final regex:** `^[0-9\s,.\-]+$` — matches only ASCII digits, whitespace,
comma, period, hyphen. Arabic-Indic digits and Arabic letters no longer
match.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| First-run-only placement loses mid-paragraph formatting variety | Acceptable: translation is a different language; source run boundaries don't map to target words. `set_bidi_direction` toggle + first-run formatting is the pragmatic choice. |
| `detect_direction` is script-based and may misclassify mixed-script text | Same limitation as the existing `auto` direction feature (AGENTS.md known limitation #3); acceptable for this fix. |
| Removing `<w:bidiVisual/>` from a paragraph that had other pPr children | Only the `<w:bidiVisual/>` child is removed; other pPr children (spacing, indentation) are preserved. |
| Empty `<w:pPr>` left behind | D4: remove `<w:pPr>` if it becomes empty. |
| Existing tests assert proportional split behavior | Tests are updated in the same change to assert the new whole-run behavior. |

## File tree (changes only)

```
src/components/interfaces/word.py          # MODIFIED: split_translation, _patch_part, bidi handling
src/components/interfaces/pdf.py           # MODIFIED: _PURE_NUMBER_RE
src/config/models.py                       # MODIFIED: WordConfig.set_bidi_direction
tests/test_word.py                         # MODIFIED: TestSplitTranslation, test_patch_multi_run; ADDED: bidi tests
tests/test_pdf.py                          # MODIFIED: pure-number tests; ADDED: Arabic-Indic digit test
tests/test_config.py                       # ADDED: set_bidi_direction default + override
openspec/changes/fix-word-pdf-translation-quality/  # this change
```

No new files in `src/`. No new dependencies.
