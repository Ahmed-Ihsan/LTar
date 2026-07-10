## Context

The project uses `mypy --strict` as documented in `openspec/config.yaml` (line 41) and `pyproject.toml` (`[tool.mypy] strict = true`). The refactor-to-component-architecture change introduced a spec requirement "Mypy strict mode passes" (config/spec.md). However, `mypy src/` currently reports **66 errors across 9 files** — all pre-existing from the flat `src/` layout, carried forward through the refactor. This change fixes all 66 errors so mypy strict can serve as a CI gate.

### Current error distribution (mypy 1.20.2, Python 3.10 venv)

| File | Errors | Error codes |
|---|---|---|
| `infrastructure/memory.py` | 3 | `misc`, `assignment`, `unused-ignore` |
| `infrastructure/run_logging.py` | 1 | `unused-ignore` |
| `knowledge_sources/glossary.py` | 5 | `arg-type`, `unused-ignore`, `call-overload` |
| `knowledge_sources/ingestion.py` | 4 | `no-untyped-def`, `attr-defined`, `type-arg` |
| `knowledge_sources/retrieval.py` | 8 | `attr-defined`, `arg-type`, `list-item` |
| `translation_pipeline/nodes.py` | 5 | `arg-type`, `typeddict-item`, `unused-ignore` |
| `interfaces/cli.py` | 14 | `type-arg`, `typeddict-item`, `attr-defined`, `arg-type`, `assignment`, `unused-ignore` |
| `interfaces/web_ui.py` | 8 | `type-arg`, `arg-type`, `attr-defined`, `unused-ignore` |
| `interfaces/tk_ui.py` | 18 | `name-defined`, `attr-defined`, `type-arg`, `unused-ignore` |
| `interfaces/hitl.py` | 1 | `type-arg` (already fixed in refactor session) |

## Goals / Non-Goals

**Goals:**
- Achieve `mypy src/` with zero errors in strict mode
- Every fix is a type-annotation, type-cast, or type-ignore change only — no runtime logic changes
- Remove all stale `# type: ignore` comments
- Add missing type parameters to all generic types (`dict`, `list`, `Queue`)
- Add `__all__` declarations where mypy's `--no-implicit-reexport` requires them
- Fix TypedDict construction to include all required keys

**Non-Goals:**
- No runtime behavior changes
- No new features
- No changes to test files
- No changes to mypy configuration (strict stays)
- No patching of third-party library stubs
- No changes to `pyproject.toml` (ruff ignores, packages, etc.)

## Decisions

### D1: Type-cast vs type-ignore for third-party stub mismatches

For ChromaDB (`retrieval.py`) and BeautifulSoup (already fixed in `legal_search.py`), the runtime accepts types that the stubs don't match. Two approaches:

- **`cast()`** — explicit type conversion, mypy-clean, but adds runtime overhead (negligible) and makes the code slightly more verbose.
- **`# type: ignore[code]`** — suppresses the error at the call site, less verbose, but hides the type mismatch.

**Decision:** Use `# type: ignore[code]` with an explanatory comment for ChromaDB stub mismatches (the stubs are known to be incomplete and the runtime is well-tested). Use `cast()` or direct type narrowing for our own code where the type can be improved. This matches the existing pattern in the codebase (e.g., `# type: ignore[attr-defined]` for `ctypes.windll`).

### D2: ttk.Text resolution

`tk_ui.py` references `ttk.Text` which does not exist in `tkinter.ttk` — `Text` is in `tkinter` directly, not `ttk`. This is a pre-existing bug in the type annotations (the code works at runtime because the annotation is string-based via `from __future__ import annotations`).

**Decision:** Change `ttk.Text` to `tkinter.Text` in type annotations. If the code actually uses `ttk.Text` at runtime (which would fail), this is a bug that should be fixed. Investigation shows the annotations are string-based and never evaluated at runtime, so changing them to `tkinter.Text` is safe and correct.

### D3: _parse_verdict return type

`_parse_verdict` currently returns `dict[str, object]` but `audit_node` assigns it to the `audit` field of `TranslationState`, which is typed `AuditVerdict | None`. This causes a `typeddict-item` error.

**Decision:** Change `_parse_verdict` to return `AuditVerdict` (the TypedDict). The function already constructs a dict with the correct keys (`verdict`, `critique`, `violations`, `confidence`); it just needs the return type annotation changed. The `# type: ignore[return-value]` comment in `audit_node` can then be removed.

### D4: _initial_state missing keys

`_initial_state` in `cli.py` constructs a `TranslationState` but omits `tm_hits` and `web_search_results` keys. The TypedDict requires all keys.

**Decision:** Add `"tm_hits": []` and `"web_search_results": []` to the returned dict. This matches the initial state described in the translation_pipeline spec (scenario "Initial state for Arabic-to-English translation" which specifies `tm_hits = []` and `web_search_results = []`).

### D5: object → concrete types in CLI and web_ui

Several variables in `cli.py` and `web_ui.py` are typed as `object` but are known to be concrete types at runtime (e.g., `ChromaStore`, `TranslationMemory`, file handles). This causes `attr-defined` errors when methods are called on them.

**Decision:** Replace `object` with the concrete type. Where the variable is constructed via DI and could be `None`, use `ConcreteType | None`. For file handles opened via `open()`, use `TextIO` or `IO[str]`.

### D6: __all__ for re-exports

`glossary.py` doesn't declare `__all__`, so mypy's `--no-implicit-reexport` (enabled by strict mode) flags imports of `GlossaryConflictError` and `GlossaryValidationError` from it.

**Decision:** Add `__all__` to `glossary.py` listing all public symbols. This is consistent with the pattern already established in `memory.py` (which got `__all__` in the refactor fix session).

### D7: Lang cast in nodes.py

`preprocess_node` derives `lang` from `state["direction"]` as a `str`, but `scan_glossary_hits` expects `Lang` (a `Literal['ar', 'en']`).

**Decision:** Cast the `str` to `Lang` using `cast(Lang, lang)` or by constructing it from the direction with a literal return. Since the direction is already validated as `"ar-en"` or `"en-ar"`, the derived lang is guaranteed to be `"ar"` or `"en"`.

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| `# type: ignore` hides a real type bug | Each type-ignore has a comment explaining why it is safe; the runtime behavior is covered by existing tests |
| Changing `ttk.Text` to `tkinter.Text` might break runtime | Annotations are string-based (`from __future__ import annotations`), so they're never evaluated at runtime; the change is type-checker-only |
| Adding `__all__` might break star imports | No star imports exist in the codebase (verified via grep); `__all__` only affects `from module import *` and mypy's re-export checking |
| Changing `_parse_verdict` return type might break callers | The only caller is `audit_node`, which assigns it to `TranslationState["audit"]` — the `AuditVerdict` type is exactly what the field expects |

## Target Directory Structure

No directory structure changes — all fixes are in-place edits to existing files:

```
src/components/
├── infrastructure/
│   ├── memory.py          # fix _fields_ annotation, remove stale type-ignore, add __all__
│   └── run_logging.py     # remove stale type-ignore
├── knowledge_sources/
│   ├── glossary.py        # add __all__, remove stale type-ignores, fix object→str casts
│   ├── ingestion.py       # add type annotation, add list type parameter, (attr-defined fixed via glossary __all__)
│   └── retrieval.py       # add type-ignore for ChromaDB stub mismatches
├── translation_pipeline/
│   └── nodes.py           # fix _parse_verdict return type, cast Lang, fix float(object), remove stale type-ignores
└── interfaces/
    ├── cli.py             # add type parameters, fix _initial_state keys, fix object→concrete, fix str|None, remove stale type-ignores
    ├── web_ui.py          # add type parameters, fix object→concrete, remove stale type-ignore
    ├── tk_ui.py           # fix ttk.Text→tkinter.Text, add Queue type parameters, remove stale type-ignore
    └── hitl.py            # (already fixed: dict→dict[str,object])
```

## Component dependency diagram (unchanged)

```
                    ┌─────────────┐
                    │   config    │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
  ┌───────────────┐ ┌────────────┐ ┌──────────────┐
  │ translation_  │ │ knowledge_ │ │ infrastructure│
  │   pipeline    │ │  sources   │ │              │
  │ (exceptions,  │◄─┤ (imports  │◄─┤ (imports    │
  │  models)      │ │  exceptions│ │  exceptions) │
  └───────┬───────┘ └─────┬──────┘ └──────┬───────┘
          │                │               │
          └────────────────┼───────────────┘
                           ▼
                   ┌───────────────┐
                   │   interfaces  │
                   │ (cli, ui,     │
                   │  hitl, mcp)   │
                   └───────────────┘
```

No dependency changes — this is a pure type-annotation fix.

## Fix strategy by error category

### Category 1: Missing type parameters (24 errors)

**Fix:** Add type parameters to all bare `dict`, `list`, `Queue` annotations.

| File | Line(s) | Current | Fixed |
|---|---|---|---|
| `cli.py` | 642, 655, 711, 723 | `list` | `list[str]` or `list[dict[str, str]]` (per context) |
| `cli.py` | 992, 1222, 1300 | `dict` | `dict[str, object]` or `dict[str, str]` (per context) |
| `web_ui.py` | 128, 145, 149, 157, 185, 305 | `dict` | `dict[str, object]` or `dict[str, Any]` |
| `tk_ui.py` | 99, 136, 182 | `Queue` | `Queue[UiTranslationResult | None]` |
| `ingestion.py` | 716 | `list` | `list[Chunk]` or `list[str]` (per context) |

### Category 2: Third-party stub mismatches (14 errors)

**Fix:** Add targeted `# type: ignore[code]` comments with explanatory comments.

| File | Line(s) | Error code | Fix |
|---|---|---|---|
| `retrieval.py` | 25 | `attr-defined` | `# type: ignore[attr-defined]` for `SharedSystemClient` import |
| `retrieval.py` | 172, 234, 279 | `arg-type` | `# type: ignore[arg-type]` for embeddings arg (stubs require ndarray, runtime accepts list) |
| `retrieval.py` | 282 (×3) | `list-item` | `# type: ignore[list-item]` for `include` list (stubs require IncludeEnum, runtime accepts str) |
| `retrieval.py` | 286 | `arg-type` | `# type: ignore[arg-type]` for QueryResult → dict[str, Any] |

### Category 3: Stale type-ignore comments (8 errors)

**Fix:** Remove the comment entirely.

| File | Line(s) | Reason stale |
|---|---|---|
| `memory.py` | 73 | mypy 1.20 no longer flags this line |
| `run_logging.py` | 90 | mypy 1.20 no longer flags this line |
| `glossary.py` | 251, 463, 465 | mypy 1.20 no longer flags these lines |
| `nodes.py` | 425 | fixed by changing `_parse_verdict` return type (D3) |
| `cli.py` | 408 | fixed by casting `direction` to `Direction` or keeping only the needed code |
| `tk_ui.py` | 154 | mypy 1.20 no longer flags this line |
| `web_ui.py` | 93 | already removed in refactor fix session |

### Category 4: ctypes _fields_ override (2 errors)

**Fix:** Add `# type: ignore[misc,assignment]` to the `_fields_` line with a comment.

| File | Line | Fix |
|---|---|---|
| `memory.py` | 59 | `# type: ignore[misc,assignment]  # ctypes Structure._fields_ type is incompatible with list[tuple[str, object]]` |

### Category 5: Missing __all__ re-exports (2 errors)

**Fix:** Add `__all__` to `glossary.py`.

| File | Fix |
|---|---|
| `glossary.py` | Add `__all__ = ["GlossaryIndex", "GlossaryConflictError", "GlossaryValidationError", ...]` listing all public symbols |

### Category 6: Untyped/loosely-typed code (16 errors)

**Fix:** Tighten types, add casts, fix TypedDict construction.

| File | Line(s) | Error | Fix |
|---|---|---|---|
| `glossary.py` | 251 | `arg-type`: `object` → `Literal['ar','en']` | Cast `target_lang` to `Lang` |
| `glossary.py` | 263 | `call-overload`: `int(object)` | Cast to `str` before `int()` |
| `ingestion.py` | 139 | `no-untyped-def` | Add type annotation to the parameter |
| `nodes.py` | 257 | `arg-type`: `str` → `Literal['ar','en']` | Cast lang to `Lang` |
| `nodes.py` | 425 | `typeddict-item` | Change `_parse_verdict` return type to `AuditVerdict` |
| `nodes.py` | 471 | `arg-type`: `float(object)` | Cast to `str` or `float` before `float()` |
| `cli.py` | 192 | `arg-type`: `str \| None` → `str` | Guard against `None` in `_canonical_model_name` |
| `cli.py` | 280 | `arg-type`: `ByteSize \| None` → `int` arg | Guard against `None` before `int()` |
| `cli.py` | 343 | `assignment`: `str` → `int` | Fix variable type or cast |
| `cli.py` | 406 | `typeddict-item`: missing keys | Add `tm_hits` and `web_search_results` to `_initial_state` |
| `cli.py` | 907, 1063 | `attr-defined`: `object.close()` | Type variable as `TextIO` or `IO[str]` |
| `web_ui.py` | 172 | `arg-type`: `object` → `EmbeddingAdapter \| None` | Type variable as `EmbeddingAdapter | None` |
| `web_ui.py` | 180 | `attr-defined`: `object.list_all()` | Type variable as `TranslationMemory` or `GlossaryIndex` |
| `tk_ui.py` | 41-91 (×12) | `name-defined`: `ttk.Text` | Change to `tkinter.Text` |
| `tk_ui.py` | 57, 72, 77, 91 (×4) | `attr-defined`: module has no `Text` | Same fix as above |

## Migration strategy

No file moves — all fixes are in-place. Order by component (foundation-first):

1. **infrastructure** (3 errors) — memory.py, run_logging.py
2. **knowledge_sources** (14 errors) — glossary.py, ingestion.py, retrieval.py
3. **translation_pipeline** (5 errors) — nodes.py
4. **interfaces** (44 errors) — cli.py, web_ui.py, tk_ui.py, hitl.py

After each component, run `mypy src/` to confirm the error count decreased. After all fixes, run the full suite: `pytest`, `ruff`, `mypy`, `openspec validate --all`.

## pyproject.toml changes

None. The mypy configuration (`strict = true`) stays unchanged. No new dependencies needed (`types-PyYAML` already installed).

## ruff per-file-ignores changes

None. No new ruff ignores needed — all fixes are mypy-specific.
