## Why

The agent currently translates single sentences and JSONL batches of plain text. Iraqi legal work is frequently delivered as **Excel workbooks** — statute tables, article indexes, bilingual glossaries maintained in spreadsheets, and ministry templates with heavy formatting (merged cells, formulas, charts, comments, data validation, page layout). Translating these today means manually copying cells out and back, losing all formatting and breaking formulas. A first-class `excel` command that translates the workbook in place — preserving every non-text artifact exactly — closes that gap and reuses the existing Translator → Auditor → Revise pipeline for the actual translation work.

## What Changes

- **ADDED:** `src/components/interfaces/excel.py` — a document-translation adapter for `.xlsx`. Pure XML helpers (`extract_translatable_strings`, `patch_strings`, `protect_non_translatable`, `restore_protected`) operate on workbook bytes with **no dependency on the pipeline**; the orchestrator `translate_excel(...)` runs each unique string through the existing `run_translation` seam.
- **ADDED:** `src/components/interfaces/models.py` — `ExcelTranslationReport` DTO (counts + per-segment warnings).
- **ADDED:** `src/config/models.py` — `ExcelConfig` Pydantic model (toggles for comments, headers/footers, chart titles; max segment chars; protect-token patterns). Wired into `AppConfig` as `excel: ExcelConfig`.
- **MODIFIED:** `config.yaml` — new `excel:` section with documented defaults.
- **MODIFIED:** `src/components/interfaces/cli.py` — new `excel` subcommand (`--input`, `--out`, `--direction`, `--config`). Constructs adapters via the existing `_construct_adapters` and calls `translate_excel`.
- **ADDED:** `tests/test_excel.py` — unit tests for the pure XML helpers + protect/restore, integration tests for `translate_excel` with the deterministic `mock_llm`/`mock_embedder`, and an e2e round-trip fixture that asserts formatting/formulas/merged cells are preserved byte-for-byte except translated text.
- **ADDED:** `tests/fixtures/excel/` — small `.xlsx` fixtures generated programmatically by the tests (no binary committed), covering: plain cells, shared strings, inline strings, merged cells, formulas, comments, headers/footers, chart titles, hidden sheets, conditional formatting, data validation, hyperlinks, numbers/IDs/placeholders.
- No changes to the LangGraph state machine, nodes, prompts, glossary, TM, or any existing behavior. The Excel feature is purely additive and reuses `run_translation` unchanged.

## Capabilities

### New Capabilities

- `excel_translation` (documented under `interfaces`): Excel workbook translation that preserves workbook structure and routes human-readable text through the translation pipeline.

### Modified Capabilities

- `interfaces`: ADDED `excel` CLI subcommand and the `translate_excel` orchestration seam + `ExcelTranslationReport` model.
- `config`: ADDED `ExcelConfig` Pydantic model and `excel` section in `config.yaml`.

## Impact

**Affected code:**
- New: `src/components/interfaces/excel.py`, `tests/test_excel.py`, `tests/fixtures/excel/` (generated).
- Modified: `src/components/interfaces/cli.py` (new command), `src/components/interfaces/models.py` (new DTO), `src/config/config.py` (wire `ExcelConfig`), `src/config/models.py` (new model), `config.yaml` (new section), `pyproject.toml` (ruff per-file-ignores for the new orchestration seam), `requirements.txt` (no new runtime deps — stdlib only), `pytest.ini` (no change needed; markers already cover unit/integration/e2e).

**Affected APIs:**
- New public function `translate_excel(...)` and pure helpers in `excel.py`.
- New CLI subcommand `iraqi-translate excel ...`.
- `AppConfig` gains an `excel: ExcelConfig` field (additive, backward compatible — defaults applied when the section is absent).

**Dependencies:** No new runtime dependencies. Uses stdlib `zipfile`, `xml.etree.ElementTree`, `re`, `threading`. No cloud calls, no telemetry. Fits the 8 GB RAM profile (streams per-part; only `sharedStrings.xml` is held for patching, with `iterparse` clearing elements after processing).

**Systems affected:**
- CLI (`iraqi-translate excel`).
- Test suite (new test module).
- Lint/type-check (new file).

**Migration path:** Purely additive. No existing import paths change. `config.yaml` gains an optional `excel:` section; `AppConfig` applies defaults when absent (so existing configs keep working).

**Rollback plan:** Revert the commit. No data files, `db/`, or `data/` directories are touched. The feature is isolated to new files plus small additive edits to `cli.py`, `models.py`, `config.py`, `config.yaml`, `pyproject.toml`.

**Affected files (old → new):**

| Old path | New path |
|---|---|
| (none) | `src/components/interfaces/excel.py` |
| (none) | `tests/test_excel.py` |
| `src/components/interfaces/models.py` | `src/components/interfaces/models.py` (+ `ExcelTranslationReport`) |
| `src/components/interfaces/cli.py` | `src/components/interfaces/cli.py` (+ `excel` command) |
| `src/config/models.py` | `src/config/models.py` (+ `ExcelConfig`) |
| `src/config/config.py` | `src/config/config.py` (wire `excel`) |
| `config.yaml` | `config.yaml` (+ `excel:` section) |
| `pyproject.toml` | `pyproject.toml` (+ per-file-ignore for `excel.py`) |

## Approach (library selection)

Three approaches were compared:

1. **openpyxl** — pure-Python `.xlsx` library. New dependency; `load_workbook` (the modify path) loads the whole file into memory (poor for large files); known fidelity gaps on sparklines, pivot tables, some chart subtypes, and custom XML parts.
2. **Direct XML (stdlib `zipfile` + `xml.etree.ElementTree`)** — `.xlsx` is a zip of OOXML parts. No new dependencies; maximum fidelity (only text-bearing XML nodes are patched, every other part is preserved byte-for-byte); memory-efficient (process per-part, `iterparse` for `sharedStrings`).
3. **pandas `read_excel`/`to_excel`** — destroys all formatting, formulas, merged cells, and charts. Fails the "preserve exactly" requirement. Rejected.

**Chosen: Direct XML (stdlib only).** It is the only approach that satisfies all requirements simultaneously — exact preservation of charts/images/conditional-formatting/data-validation/page-layout/structure, large-file memory efficiency, no new dependencies, and offline operation within the 8 GB RAM ceiling.
