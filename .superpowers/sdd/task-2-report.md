# Task 2 Report — Word RTL/bidi paragraph direction

## Status: DONE_WITH_CONCERNS

## What I implemented

Added RTL/bidi paragraph direction handling to the Word adapter. When
translating English → Arabic, output paragraphs now get `<w:bidiVisual/>`;
when translating Arabic → English, existing `<w:bidiVisual/>` is removed
(and the `<w:pPr>` is removed if it becomes empty). Gated by a new
`cfg.word.set_bidi_direction: bool = True` toggle.

### Files changed
- `src/config/models.py` — added `set_bidi_direction: bool = True` field to
  `WordConfig` (after `translate_glossary_doc`).
- `src/components/interfaces/word.py` — added `_PPR` / `_BIDI` namespace
  constants near `_RPR`; added `_adjust_bidi_direction` helper above
  `_patch_part`; modified `_patch_part` to call it (gated by `set_bidi`).
- `tests/test_config.py` — added 2 tests for the new field.
- `tests/test_word.py` — added `TestBidiDirection` class with 5 tests.

## TDD evidence

### RED (config tests — written first, passed immediately due to default)
```
$ .\.venv\Scripts\python.exe -m pytest tests/test_config.py -q -k "set_bidi_direction"
..                                                                       [100%]
2 passed, 34 deselected in 0.05s
```

### RED (bidi tests — before implementation, run with system python w/o langgraph)
```
$ pytest tests/test_word.py::TestBidiDirection -v
3 failed, 2 passed in 0.44s
```
Failures: `test_arabic_translation_gets_bidi_visual` (no bidiVisual added),
`test_empty_ppr_removed_when_bidi_was_only_child` (pPr not removed),
`test_other_ppr_children_preserved_when_bidi_removed` (serialization format).

### GREEN (bidi tests — after implementation, venv python with langgraph)
```
$ .\.venv\Scripts\python.exe -m pytest tests/test_word.py::TestBidiDirection -v
5 passed, 1 warning in 0.65s
```

### Full Word + config suite
```
$ .\.venv\Scripts\python.exe -m pytest tests/test_word.py tests/test_config.py -q
75 passed, 147 warnings in 8.51s
```

### Lint / type-check
```
$ .\.venv\Scripts\python.exe -m ruff check src/config/models.py src/components/interfaces/word.py tests/test_config.py tests/test_word.py
All checks passed!

$ .\.venv\Scripts\python.exe -m mypy src/config/models.py src/components/interfaces/word.py
# 0 errors in the two checked files. (Pre-existing errors in
# src/components/interfaces/commands/word.py from typer decorators are
# transitive and unrelated to this task.)
```

## Commit
```
d32c60d feat: set Word paragraph RTL/bidi direction to match translation script
```

## Self-review findings

1. **Test assertion deviation (2 tests).** The brief's test code asserts exact
   self-closing tag strings `<w:bidiVisual/>` and `<w:spacing w:after="120"/>`.
   Python's `xml.etree.ElementTree` serializes empty elements with a space
   before `/>` (e.g. `<w:bidiVisual />`), so those exact-string assertions
   cannot pass. I adjusted two assertions minimally to preserve intent:
   - `test_arabic_translation_gets_bidi_visual`: `"<w:bidiVisual" in body`
     (tag present, regardless of self-close spacing).
   - `test_other_ppr_children_preserved_when_bidi_removed`:
     `'<w:spacing w:after="120"' in body` (spacing element preserved).
   The "not in body" assertions for removed elements were left as-is since a
   removed element produces neither form.

2. **mypy variable-name clash.** The brief's helper reused the name `bidi` in
   both the RTL branch (`ET.Element`) and the LTR branch (`Element | None`).
   Mypy inferred the type from the first assignment and rejected the second.
   Renamed the LTR-branch variable to `bidi_el` with an explicit
   `ET.Element | None` annotation. Behavior unchanged.

3. **Environment note.** The system Python (3.12) does not have `langgraph`
   installed, so the lazy import of `detect_direction` from `orchestration`
   (which transitively imports `build_graph` → `langgraph`) fails there. The
   project `.venv` (Python 3.10.11) has `langgraph` installed and all tests
   pass. This matches the existing `translate_word` lazy-import pattern; the
   pure `patch_word_strings` path now also depends on `langgraph` being
   importable at runtime when `set_bidi_direction=True` (the default). In a
   fully-installed environment (CI / `pip install -r requirements.txt`) this is
   fine.

## Concerns

- The two test-assertion edits deviate from the brief's literal test text
  (unavoidable due to ET serialization format). Intent is fully preserved.
- `patch_word_strings` (previously a pure XML helper with no pipeline
  dependency) now transitively imports `langgraph` via `detect_direction` when
  `set_bidi_direction=True`. If a pure-patch use case without langgraph is
  required, `detect_direction` would need to be moved to a dependency-free
  module. Not blocking for this task since the project venv has langgraph.

---

## Post-amend fix — remove `orchestration` dependency from pure helper

### Problem

`_adjust_bidi_direction` lazily imported `detect_direction` from
`src.components.interfaces.orchestration`, which imports `langgraph` at module
level. This violated the spec constraint that pure helpers
(`extract_word_strings` / `patch_word_strings`) operate on document bytes with
**no dependency on the pipeline or adapters**.

### Fix

Replaced the lazy import with a self-contained `_is_arabic_dominant` helper in
`src/components/interfaces/word.py` that mirrors `detect_direction`'s
character-counting logic (Arabic U+0600–U+06FF vs ASCII alpha; Arabic >= Latin
→ RTL). `_adjust_bidi_direction` now calls `_is_arabic_dominant(translation)`
instead of `detect_direction(translation) == "ar-en"`.

### Verification (commands run + output)

```
$ $env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests/test_word.py::TestBidiDirection -v
5 passed in 0.06s

$ $env:PYTHONIOENCODING='utf-8'; .\.venv\Scripts\python.exe -m pytest tests/test_word.py tests/test_config.py -q
75 passed, 147 warnings in 7.94s

$ .\.venv\Scripts\python.exe -m ruff check src/components/interfaces/word.py
All checks passed!

$ .\.venv\Scripts\python.exe -m mypy src/components/interfaces/word.py
# 0 errors in src/components/interfaces/word.py. (19 pre-existing errors in
# src/components/interfaces/commands/*.py from typer decorators are
# transitive and unrelated to this change.)
```

### Commit (amended)

```
2d07bc5 feat: set Word paragraph RTL/bidi direction to match translation script
```

### Confirmation

`patch_word_strings` no longer imports from `orchestration`. The lazy
`from src.components.interfaces.orchestration import detect_direction` line has
been removed; `word.py` now has zero dependency on the orchestration/pipeline
module.
