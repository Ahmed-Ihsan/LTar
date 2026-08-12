# fix-word-pdf-translation-quality

## Why

The Word and PDF translation adapters (shipped in the `add-pdf-word-translation`
change) have three confirmed quality defects that corrupt the saved output or
leave text untranslated:

1. **Word proportional run-split breaks words mid-character.** When a paragraph
   has multiple `w:r` runs with different formatting (bold / italic / color),
   `split_translation` distributes the translated text across the original runs
   by character-length ratio, ignoring word boundaries. Verified example:
   `split_translation("the quick brown fox", [3,5,5,3])` →
   `["the", " quic", "k bro", "wn fox"]` — "quick" and "brown" are sliced
   across two runs, so bold/italic formatting is applied to arbitrary
   character fragments of the translation, not to whole words. This is the
   primary format-corruption mechanism for any mixed-formatting paragraph.
   The current spec *mandates* this proportional split (interfaces spec
   requirement "Word XML extraction and patching", line 85), so fixing it
   requires a **MODIFIED** requirement.

2. **Word has no RTL/bidi direction handling for Arabic output.** When
   translating English → Arabic (`en-ar`), output paragraphs keep the original
   (LTR) paragraph direction. Word may render the Arabic text left-to-right
   instead of right-to-left. The PDF sidecar sets `<w:bidiVisual/>` for `ar-en`
   output, but the Word in-place path does not set paragraph direction at all.
   This is an **ADDED** requirement.

3. **PDF pure-number filter risks dropping Arabic-numeric text.** The regex
   `_PURE_NUMBER_RE = ^[\d\s,.\u0600-\u06FF]+$` includes the Arabic Unicode
   block (`\u0600-\u06FF`), so a block that is only Arabic-Indic digits and
   punctuation (e.g. `١٢٣٤،٥`) matches and is silently dropped as a "page
   number". Legitimate short Arabic numeric content is lost. The fix tightens
   the regex to match only ASCII digits and common separators, and requires at
   least one ASCII digit, so Arabic-letter-only or Arabic-digit-only blocks are
   no longer falsely classified as page numbers. This **MODIFIES** the
   "PDF text extraction and sidecar writers" requirement.

## What Changes

### MODIFIED — interfaces: Word XML extraction and patching

- `split_translation` is replaced by a **whole-translation-in-first-run**
  strategy: the entire translated text is placed in the first `w:t` run; all
  subsequent `w:t` runs in the same paragraph are set to the empty string.
  This preserves the first run's formatting (the paragraph's dominant run) for
  the whole translation and never breaks a word across runs. The
  `split_translation` function is kept as a thin compatibility wrapper that
  returns `[translation, "", "", ...]` so existing callers/tests of the public
  helper still compile; its proportional logic is removed.
- The `_patch_part` function is updated to assign the whole translation to the
  first `w:t` and empty the rest.

### ADDED — interfaces: Word RTL/bidi paragraph direction

- When patching a paragraph whose translated text is Arabic-dominant (resolved
  via `orchestration.detect_direction` on the *translation*),
  `patch_word_strings` SHALL ensure a `<w:bidiVisual/>` element exists in the
  paragraph's `<w:pPr>` (creating `<w:pPr>` if absent). When the translated
  text is Latin-dominant, any existing `<w:bidiVisual/>` SHALL be removed.
  This mirrors the PDF sidecar's RTL behavior and is gated on a new
  `cfg.word.set_bidi_direction: bool = True` toggle (default on; can be
  disabled for documents that already carry correct direction properties).

### MODIFIED — interfaces: PDF text extraction pure-number filter

- `_PURE_NUMBER_RE` is tightened to `^[\d\s,.\-]+$` (ASCII digits only,
  plus whitespace, comma, period, hyphen) and the skip condition requires at
  least one ASCII digit (`\d`). Arabic-Indic digits (`\u0660-\u0669`) and
  Arabic letters (`\u0600-\u06FF`) are no longer treated as "pure number"
  page-number noise, so short Arabic numeric blocks are preserved and
  translated.

### ADDED — config: WordConfig.set_bidi_direction

- New boolean field `set_bidi_direction: bool = True` on `WordConfig`, wired
  into `AppConfig.word`. Default `True` so Arabic output gets RTL paragraphs
  out of the box; users who want the old behavior set it to `False`.

## Capabilities

- **Modified:** `interfaces` (Word patching strategy, PDF pure-number filter)
- **Added:** `interfaces` (Word RTL/bidi paragraph direction)
- **Modified:** `config` (WordConfig.set_bidi_direction field)

## Impact

- **Behavior change (Word):** Multi-run paragraphs now place the whole
  translation in the first run instead of proportionally splitting. This is
  intentional and fixes format corruption. The first run's formatting is
  applied to the whole translation; subsequent runs' formatting is no longer
  represented (their text is emptied). This is the correct trade-off: the
  translation is a different language, so source-language run boundaries do
  not map to target-language word boundaries.
- **Behavior change (Word):** Arabic-dominant translations now get
  `<w:bidiVisual/>` on their paragraph; Latin-dominant translations have it
  removed. Documents that previously relied on the original paragraph
  direction being preserved unchanged will now have direction adjusted to
  match the target language. The `set_bidi_direction` toggle restores the old
  behavior if needed.
- **Behavior change (PDF):** Short Arabic numeric blocks that were silently
  dropped are now preserved and translated. This may slightly increase the
  segment count for Arabic-heavy PDFs, but no longer loses content.
- **No new dependencies.** No new imports. No cloud calls. No RAM impact.
- **Tests:** Existing `test_patch_multi_run_proportional_split` and
  `TestSplitTranslation` tests are updated to assert the new whole-run
  behavior. New tests cover RTL/bidi setting/removal and the tightened
  pure-number filter.
