## 1. Infrastructure component (3 errors)

- [x] 1.1 Fix `memory.py:59` — add `# type: ignore[misc,assignment]` to `MEMORYSTATUSEX._fields_` line with comment explaining ctypes Structure base-class incompatibility
- [x] 1.2 Fix `memory.py:73` — remove stale `# type: ignore[attr-defined]` comment on `ctypes.windll.kernel32.GlobalMemoryStatusEx` call (mypy 1.20 no longer flags it)
- [x] 1.3 Fix `run_logging.py:90` — remove stale `# type: ignore` comment (mypy 1.20 no longer flags it)
- [x] 1.4 Verify: `mypy src/components/infrastructure/` reports 0 errors (down from 3)

## 2. Knowledge sources component — glossary.py (5 errors)

- [x] 2.1 Add `__all__` declaration to `glossary.py` listing all public symbols including `GlossaryConflictError`, `GlossaryValidationError`, `GlossaryIndex`, `load_glossary_index`, `scan_glossary_hits`, `normalize_arabic`, `normalize_english`, `normalize`, `Term`, `Lang`
- [x] 2.2 Fix `glossary.py:251` — remove stale `# type: ignore` comment and cast `target_lang` from `object` to `Lang` (e.g., `cast(Lang, target_lang)`) before passing to `Term`
- [x] 2.3 Fix `glossary.py:263` — cast the `object`-typed value to `str` before calling `int()` (e.g., `int(str(value))`)
- [x] 2.4 Fix `glossary.py:463` — remove stale `# type: ignore` comment
- [x] 2.5 Fix `glossary.py:465` — remove stale `# type: ignore` comment
- [x] 2.6 Verify: `mypy src/components/knowledge_sources/glossary.py` reports 0 errors (down from 5)

## 3. Knowledge sources component — ingestion.py (4 errors)

- [x] 3.1 Fix `ingestion.py:139` — add type annotation to the untyped parameter (inspect the function signature and add the correct type)
- [x] 3.2 Fix `ingestion.py:537` — verify the `GlossaryConflictError` and `GlossaryValidationError` `attr-defined` errors are resolved by the `__all__` added in task 2.1
- [x] 3.3 Fix `ingestion.py:716` — add type parameter to bare `list` (e.g., `list[Chunk]` or `list[str]` per context)
- [x] 3.4 Verify: `mypy src/components/knowledge_sources/ingestion.py` reports 0 errors (down from 4)

## 4. Knowledge sources component — retrieval.py (8 errors)

- [x] 4.1 Fix `retrieval.py:25` — add `# type: ignore[attr-defined]` to the `SharedSystemClient` import from `chromadb.api.client` with comment explaining the symbol exists at runtime but is not in the stubs' `__all__`
- [x] 4.2 Fix `retrieval.py:172` — add `# type: ignore[arg-type]` to the `Collection.add` call for the `embeddings` argument with comment explaining ChromaDB stubs require ndarray but runtime accepts `list[list[float]]`
- [x] 4.3 Fix `retrieval.py:234` — same `# type: ignore[arg-type]` for the second `Collection.add` call
- [x] 4.4 Fix `retrieval.py:279` — add `# type: ignore[arg-type]` to the `Collection.query` call for `query_embeddings` argument
- [x] 4.5 Fix `retrieval.py:282` — add `# type: ignore[list-item]` to the `include` list argument (stubs require `IncludeEnum`, runtime accepts `str`)
- [x] 4.6 Fix `retrieval.py:286` — add `# type: ignore[arg-type]` to the `_parse_query_result` call (stubs return `QueryResult`, function expects `dict[str, Any]`)
- [x] 4.7 Verify: `mypy src/components/knowledge_sources/retrieval.py` reports 0 errors (down from 8)

## 5. Knowledge sources component — verification

- [x] 5.1 Verify: `mypy src/components/knowledge_sources/` reports 0 errors total (down from 17)
- [x] 5.2 Verify: `ruff check src/components/knowledge_sources/` passes with zero errors
- [x] 5.3 Verify: `pytest tests/ -q -k "glossary or retrieval or ingestion or chunker or corpus or token or rag"` passes with no regressions

## 6. Translation pipeline component — nodes.py (5 errors)

- [x] 6.1 Fix `nodes.py:257` — cast the `lang` variable from `str` to `Lang` before calling `scan_glossary_hits` (e.g., `from typing import cast; cast(Lang, lang)`)
- [x] 6.2 Fix `nodes.py:425` — change `_parse_verdict` return type from `dict[str, object]` to `AuditVerdict` and remove the `# type: ignore[return-value]` comment in `audit_node`
- [x] 6.3 Fix `nodes.py:425` — remove the stale `# type: ignore` comment (resolved by task 6.2)
- [x] 6.4 Fix `nodes.py:471` — cast the `object`-typed confidence value to `str` before calling `float()` (e.g., `float(str(confidence))`)
- [x] 6.5 Verify: `mypy src/components/translation_pipeline/nodes.py` reports 0 errors (down from 5)

## 7. Translation pipeline component — verification

- [x] 7.1 Verify: `mypy src/components/translation_pipeline/` reports 0 errors total (down from 5)
- [x] 7.2 Verify: `ruff check src/components/translation_pipeline/` passes with zero errors
- [x] 7.3 Verify: `pytest tests/ -q -k "nodes or graph or decision or prompts"` passes with no regressions

## 8. Interfaces component — cli.py (14 errors)

- [x] 8.1 Fix `cli.py:192` — guard `_canonical_model_name` against `str | None` input by defaulting to `""` when `None` (e.g., `name or ""`)
- [x] 8.2 Fix `cli.py:280` — guard `int(ByteSize | None)` by checking for `None` before conversion (e.g., `int(value) if value is not None else 0`)
- [x] 8.3 Fix `cli.py:343` — fix the `str`-to-`int` assignment conflict by using the correct type annotation for the variable
- [x] 8.4 Fix `cli.py:406` — add `"tm_hits": []` and `"web_search_results": []` to the `_initial_state` return dict
- [x] 8.5 Fix `cli.py:408` — remove or update the stale `# type: ignore[arg-type]` comment on the `direction` field (may still be needed if `str` is passed where `Direction` is expected — verify after task 8.4)
- [x] 8.6 Fix `cli.py:642` — add type parameter to bare `list` (e.g., `list[str]` per context)
- [x] 8.7 Fix `cli.py:655` — add type parameter to bare `list`
- [x] 8.8 Fix `cli.py:711` — add type parameter to bare `list`
- [x] 8.9 Fix `cli.py:723` — add type parameter to bare `list`
- [x] 8.10 Fix `cli.py:907` — type the `object` variable as `IO[str]` or `TextIO` so `.close()` is recognized
- [x] 8.11 Fix `cli.py:992` — add type parameter to bare `dict` (e.g., `dict[str, object]`)
- [x] 8.12 Fix `cli.py:1063` — type the `object` variable as `IO[str]` or `TextIO` so `.close()` is recognized
- [x] 8.13 Fix `cli.py:1222` — add type parameter to bare `dict`
- [x] 8.14 Fix `cli.py:1300` — add type parameter to bare `dict`
- [x] 8.15 Verify: `mypy src/components/interfaces/cli.py` reports 0 errors (down from 14)

## 9. Interfaces component — web_ui.py (8 errors)

- [x] 9.1 Fix `web_ui.py:128` — add type parameter to bare `dict`
- [x] 9.2 Fix `web_ui.py:145` — add type parameter to bare `dict`
- [x] 9.3 Fix `web_ui.py:149` — add type parameter to bare `dict`
- [x] 9.4 Fix `web_ui.py:157` — add type parameter to bare `dict`
- [x] 9.5 Fix `web_ui.py:172` — type the `embedder` argument as `EmbeddingAdapter | None` instead of `object` (import `EmbeddingAdapter` from infrastructure)
- [x] 9.6 Fix `web_ui.py:180` — type the variable holding the TM/glossary as `TranslationMemory` or `GlossaryIndex` instead of `object` so `.list_all()` is recognized
- [x] 9.7 Fix `web_ui.py:185` — add type parameter to bare `dict`
- [x] 9.8 Fix `web_ui.py:305` — add type parameter to bare `dict`
- [x] 9.9 Verify: `mypy src/components/interfaces/web_ui.py` reports 0 errors (down from 8)

## 10. Interfaces component — tk_ui.py (18 errors)

- [x] 10.1 Fix all `ttk.Text` references (lines 41, 44, 45, 46, 47, 51, 57, 72, 77, 83, 91, 175) — change `ttk.Text` to `tkinter.Text` in type annotations (Text is in tkinter, not ttk; annotations are string-based so no runtime impact)
- [x] 10.2 Fix `tk_ui.py:57, 72, 77, 91` — the `Module has no attribute "Text"` errors (×4) are resolved by task 10.1 (changing `ttk.Text` to `tkinter.Text`)
- [x] 10.3 Fix `tk_ui.py:154` — remove stale `# type: ignore` comment
- [x] 10.4 Fix `tk_ui.py:99` — add type parameter to bare `Queue` (e.g., `Queue[UiTranslationResult | None]`)
- [x] 10.5 Fix `tk_ui.py:136` — add type parameter to bare `Queue`
- [x] 10.6 Fix `tk_ui.py:182` — add type parameter to bare `Queue`
- [x] 10.7 Verify: `mypy src/components/interfaces/tk_ui.py` reports 0 errors (down from 18)

## 11. Interfaces component — hitl.py (1 error, already fixed)

- [x] 11.1 Verify `hitl.py:134` — the `dict` → `dict[str, object]` fix from the refactor session is still in place and mypy reports 0 errors

## 12. Interfaces component — verification

- [x] 12.1 Verify: `mypy src/components/interfaces/` reports 0 errors total (down from 41)
- [x] 12.2 Verify: `ruff check src/components/interfaces/` passes with zero errors
- [x] 12.3 Verify: `pytest tests/ -q -k "cli or web or tk or hitl"` passes with no regressions

## 13. Final full-suite verification

- [x] 13.1 Run `mypy src/` — SHALL report 0 errors (down from 66)
- [x] 13.2 Run `ruff check src/ tests/` — SHALL pass with zero errors
- [x] 13.3 Run `pytest --tb=short -q` — SHALL pass with 390+ tests, 0 failures
- [x] 13.4 Run `openspec validate --all` — SHALL pass with 0 failures
- [x] 13.5 Confirm no runtime behavior changes — compare `pytest` test count and output with pre-fix baseline
