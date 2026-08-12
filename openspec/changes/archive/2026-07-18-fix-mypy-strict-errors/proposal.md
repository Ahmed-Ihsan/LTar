## Why

The project's `openspec/config.yaml` declares `mypy strict = true` as a project convention, and the refactor-to-component-architecture change (config/spec.md, "Mypy strict mode passes" requirement) mandates that `mypy src/` passes with zero errors. Currently, `mypy src/` reports **66 errors across 9 files** — all pre-existing baseline issues carried forward from the flat `src/` layout through the component refactor. These errors fall into six root-cause categories:

1. **Missing type parameters on generic types** (24 errors) — bare `dict`, `list`, `Queue` instead of `dict[str, X]`, `list[Y]`, `Queue[Z]`.
2. **Third-party library type mismatches** (14 errors) — ChromaDB's `Collection.add`/`query` signatures don't accept `list[list[float]]`; BeautifulSoup returns `str | AttributeValueList` from attribute access; ChromaDB doesn't explicitly export `SharedSystemClient`.
3. **Stale `# type: ignore` comments** (8 errors) — comments that were needed on Python 3.10/mypy 1.10 but are now unused under mypy 1.20.
4. **ctypes Structure `_fields_` override** (2 errors) — `MEMORYSTATUSEX._fields_` type annotation conflicts with the base `Structure` class.
5. **Missing `__all__` re-exports** (2 errors) — `glossary.py` doesn't declare `__all__`, so mypy's `--no-implicit-reexport` flags `GlossaryConflictError`/`GlossaryValidationError` imports.
6. **Untyped/loosely-typed code paths** (16 errors) — `object` where a concrete type is expected, `str | None` passed where `str` is required, TypedDict construction missing keys, `float(object)` calls, `ttk.Text` not recognized by stubs.

Until these are resolved, mypy strict cannot be used as a CI gate, and the refactor's own spec requirement is unmet.

## What Changes

- **Add type parameters** to all bare `dict`, `list`, and `Queue` annotations across `cli.py`, `web_ui.py`, `hitl.py`, `ingestion.py`, and `tk_ui.py`.
- **Fix ChromaDB type mismatches** in `retrieval.py` by casting embedding lists to the types ChromaDB's stubs expect, or by using `# type: ignore[arg-type]` where the runtime accepts `list[list[float]]` but the stubs don't.
- **Fix BeautifulSoup type mismatches** in `legal_search.py` by wrapping attribute accesses in `str()` (already partially done in the refactor fix session — 5 of 5 errors fixed, but this change formalizes it in the spec).
- **Remove stale `# type: ignore` comments** in `memory.py`, `run_logging.py`, `glossary.py`, `nodes.py`, `cli.py`, `tk_ui.py`, and `web_ui.py`.
- **Fix ctypes `_fields_` annotation** in `memory.py` by using `Sequence` or adding a targeted `# type: ignore[misc,assignment]`.
- **Add `__all__` to `glossary.py`** so `GlossaryConflictError` and `GlossaryValidationError` are explicitly re-exported.
- **Tighten loose type annotations** — replace `object` with concrete types where the runtime type is known (e.g., `ChromaStore` instead of `object` for the embedder in `web_ui.py`, `Text` widget type for Tkinter).
- **Fix `_initial_state` TypedDict construction** in `cli.py` to include all required keys (`tm_hits`, `web_search_results`).
- **Fix `_parse_verdict` return type** in `nodes.py` to return `AuditVerdict` instead of `dict[str, object]`.
- **Add type annotation** to the untyped parameter in `ingestion.py:139`.

**No behavior changes.** Every fix is a type-annotation or type-cast change only — runtime logic is untouched.

## Capabilities

**Modified Capabilities:**
- `infrastructure` — fix ctypes `_fields_` annotation, remove stale type-ignore comments
- `interfaces` — add type parameters, fix object-typed variables, fix TypedDict construction, remove stale type-ignore comments, fix ttk.Text stub issue
- `knowledge_sources` — add `__all__` to glossary.py, fix ChromaDB type mismatches, add type annotation to untyped parameter, add type parameter to list
- `translation_pipeline` — fix `_parse_verdict` return type, fix `scan_glossary_hits` argument type, remove stale type-ignore comments, fix `float(object)` call

**New Capabilities:** None

## Impact

- **Affected code:** 9 source files across 4 components (no config changes, no test changes)
- **Affected APIs:** No public API changes — all fixes are internal type annotations
- **Dependencies:** No dependency version changes; may need `types-PyYAML` already installed (it is)
- **Risk:** Low — type annotations and casts do not change runtime behavior. The main risk is a cast hiding a real type bug, but each cast is documented with a comment explaining why it is safe.

## Scope

**In scope:**
- Fix all 66 mypy strict errors in `src/`
- Remove stale `# type: ignore` comments
- Add missing type parameters to generic types
- Add `__all__` exports where mypy's `--no-implicit-reexport` requires them
- Fix TypedDict construction to include all required keys
- Tighten `object` annotations to concrete types where the runtime type is known

**Out of scope:**
- No runtime behavior changes
- No new features or refactors
- No changes to `tests/` (test imports are already correct)
- No changes to `pyproject.toml` mypy configuration (strict mode stays)
- No changes to `config.yaml` or any non-Python file
- No fixing of third-party library stubs (we work around them, not patch them)

## Migration path

This is a pure type-annotation fix — no file moves, no import path changes. Each fix is applied in-place to the existing component file. The migration is ordered by component (foundation-first) so that fixes to lower-level modules are verified before higher-level modules that depend on them:

1. `infrastructure/` (memory.py, run_logging.py) — 3 errors
2. `knowledge_sources/` (glossary.py, ingestion.py, retrieval.py) — 14 errors
3. `translation_pipeline/` (nodes.py) — 5 errors
4. `interfaces/` (cli.py, web_ui.py, tk_ui.py, hitl.py) — 44 errors

After each component, run `mypy src/` to confirm the error count decreased by the expected amount. After all fixes, run the full verification suite (pytest + ruff + mypy + openspec validate).

## Rollback plan

Since all changes are type annotations and casts (no logic changes), rollback is a simple `git revert` of the commit(s). No data migration, no file moves, no import path changes to undo.

## Affected files

| File | Errors | Primary fix |
|---|---|---|
| `src/components/infrastructure/memory.py` | 3 | Fix `_fields_` annotation, remove stale type-ignore |
| `src/components/infrastructure/run_logging.py` | 1 | Remove stale type-ignore |
| `src/components/knowledge_sources/glossary.py` | 5 | Add `__all__`, remove stale type-ignores, fix `object` → `str` casts |
| `src/components/knowledge_sources/ingestion.py` | 4 | Add `__all__` re-export fix, add type annotation, add type parameter |
| `src/components/knowledge_sources/retrieval.py` | 8 | Cast ChromaDB embedding/query args, fix `SharedSystemClient` import |
| `src/components/translation_pipeline/nodes.py` | 5 | Fix `_parse_verdict` return type, fix `scan_glossary_hits` arg, fix `float(object)` |
| `src/components/interfaces/cli.py` | 14 | Add type parameters, fix `_initial_state` keys, fix `object` → concrete, remove stale type-ignore |
| `src/components/interfaces/web_ui.py` | 8 | Add type parameters, fix `object` → concrete types, remove stale type-ignore |
| `src/components/interfaces/tk_ui.py` | 18 | Fix `ttk.Text` stub issue, add `Queue` type parameters, remove stale type-ignore |
| `src/components/interfaces/hitl.py` | 1 | Add type parameter to `dict` (already fixed in refactor session) |

## Reference

- Error categorization based on `mypy src/` output run with mypy 1.20.2 on Python 3.10 venv
- Baseline: 67 errors at commit `452894b` (pre-refactor); 66 errors after refactor fixes (1 `no-any-return` error naturally resolved)
- Project convention: `openspec/config.yaml` line 41 — `ruff line-length = 100; mypy strict = true`
- Refactor spec requirement: `openspec/changes/refactor-to-component-architecture/specs/config/spec.md` — "Mypy strict mode passes" requirement
