# SDD Progress Ledger — fix-word-pdf-translation-quality

Branch: fix-word-pdf-translation-quality
Plan: docs/superpowers/plans/2026-08-12-fix-word-pdf-translation-quality.md
OpenSpec change: fix-word-pdf-translation-quality (validated)

## Tasks
- [x] Task 1: Word — whole-translation-in-first-run (split_translation)
- [x] Task 2: Word — RTL/bidi paragraph direction
- [x] Task 3: PDF — tighten pure-number filter
- [ ] Task 4: Final verification + archive

## Completion Log
Task 1: complete (commits 389c1cf..f044e46, review clean — Approved)
  Minor: stale comments in word.py:143, word.py:266/293, test_word.py:6 referencing "proportional split"
Task 2: complete (commits f044e46..2d07bc5, review clean after fix — Approved)
  Fixed: inlined detect_direction as _is_arabic_dominant to keep patch_word_strings pure
  Minor: test assertions use tag-substring form due to ET serialization spacing
Task 3: complete (commits 2d07bc5..e12fad7, review clean — Approved)
  Minor: inline comment at pdf.py:89 still says "pure-number" not "ASCII pure-number"
