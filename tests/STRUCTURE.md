# Tests Folder Structure

Reference map of the `tests/` directory for the Iraqi Legal Translation Agent.
Layout is **split by marker/scope** (`unit/`, `adapter/`, `integration/`),
matching the marker taxonomy in `AGENTS.md` > Testing. The `e2e/` and `eval/`
scopes are reserved by the taxonomy but not yet populated.

Reflects the on-disk layout as of 2026-08-13. Hand-maintained — update by
hand when files are added, markers change, or scopes are populated.

---

## Directory Tree

```
tests/
├── STRUCTURE.md                      # this file
├── conftest.py                       # shared fixtures (auto-discovered by all scopes):
│                                     #   MockEmbedder, MockEngineAdapter, mock_llm,
│                                     #   mock_embedder, glossary_terms, glossary_index,
│                                     #   config, sample_state  +  FIXTURES_DIR/GLOSSARY_SAMPLE
├── fixtures/
│   ├── corpus_sample.txt             # sample corpus text (used by unit/test_corpus_parser)
│   └── glossary_sample.json          # sample glossary JSON (used by glossary fixtures)
│
├── unit/                             # pytest.mark.unit  — pure logic, < 100ms each
│   ├── test_auto_direction.py        # detect_direction() script-based classification
│   ├── test_chunker.py               # text chunking logic
│   ├── test_cli_errors.py            # handle_pipeline_errors exit-code mapping
│   ├── test_config.py                # AppConfig / PathsConfig / ChromaConfig loading
│   ├── test_corpus_parser.py         # corpus file parsing (fixture: tests/fixtures/)
│   ├── test_decision.py              # route_after_tm / route_audit pure routing
│   ├── test_doc_common.py            # shared document-translation helpers
│   ├── test_gemini_adapter.py        # GeminiEngineAdapter (lazy import, key redaction)
│   ├── test_glossary.py              # glossary core behavior
│   ├── test_glossary_bidirectional.py# ar<->en bidirectional glossary
│   ├── test_glossary_conflict.py     # glossary conflict detection
│   ├── test_glossary_normalize.py    # glossary term normalization
│   ├── test_glossary_scan.py         # GlossaryScanner protocol conformance
│   ├── test_glossary_un.py           # UN glossary integration
│   ├── test_glossary_validation.py   # glossary JSON input validation
│   ├── test_hitl.py                  # human-in-the-loop review (pywebview)
│   ├── test_mcp_server.py            # MCP server input caps + rate limiting
│   ├── test_models.py                # frozen dataclass / TypedDict state models
│   ├── test_nodes.py                 # translator/auditor/finalize node behavior
│   ├── test_prompts.py               # versioned prompt constants (V1-V4) verbatim
│   ├── test_retrieval_augment.py     # context augmentation logic
│   ├── test_security_hardening.py    # XXE / zip-slip / path containment / API-key masking
│   ├── test_tm.py                    # TranslationMemory similarity + lookup
│   ├── test_tm_node.py               # tm_lookup / tm_bypass node routing
│   ├── test_tm_parallel.py           # TM parallel lookup concurrency guards
│   ├── test_token_count.py           # token counting / context budget
│   └── test_web_search.py            # legal-search URL allowlist + redirect caps
│
├── adapter/                          # pytest.mark.adapter — adapter isolation, < 500ms each
│   ├── test_embeddings.py            # embedding adapter (includes @pytest.mark.slow path)
│   ├── test_memory.py                # TranslationMemory context-manager + persistence
│   └── test_ollama_errors.py         # OllamaEngineAdapter error -> domain exception mapping
│
└── integration/                      # pytest.mark.integration — real SQLite/ChromaDB, < 1s each
    ├── test_cli.py                   # CLI end-to-end (argparse -> pipeline -> exit codes)
    ├── test_excel.py                 # Excel OOXML byte-for-byte preservation
    ├── test_glossary_sqlite.py       # glossary SQLite persistence (temp dir)
    ├── test_graph.py                 # LangGraph build_graph topology + wiring
    ├── test_ingestion_pipeline.py    # corpus ingestion pipeline (temp dir)
    ├── test_pdf.py                   # PDF byte-for-byte preservation
    ├── test_rag_incremental.py       # incremental RAG index updates (temp dir)
    ├── test_retrieval.py             # ChromaStore retrieval (temp dir, @pytest.mark.slow path)
    ├── test_run_logging.py           # RunLogger JSONL schema + redaction
    ├── test_web_ui_docs.py           # pywebview UI Word/PDF translation flow
    ├── test_web_ui_excel.py          # pywebview UI Excel translation flow
    └── test_word.py                  # Word OOXML byte-for-byte preservation
```

`__pycache__/` is intentionally omitted (build artifact, gitignored).

Reserved scopes (taxonomy in `AGENTS.md` > Testing, not yet populated):
- `tests/e2e/`  — full pipeline with mocked LLM, < 5s each
- `tests/eval/` — auditor evaluation matrix, may be slow

---

## Marker Map

Module-level `pytestmark` per file, plus per-test `slow` overrides.
Marker taxonomy and budgets are defined in `AGENTS.md` > Testing.

| Marker | Budget | Count | Folder |
|---|---|---|---|
| `unit` | < 100ms | 27 | `tests/unit/` |
| `adapter` | < 500ms | 3 | `tests/adapter/` |
| `integration` | < 1s | 12 | `tests/integration/` |
| `e2e` | < 5s | 0 | _(reserved)_ |
| `eval` | may be slow | 0 | _(reserved)_ |
| `slow` | > 5s (excluded from default CI) | 2 per-test overrides | `adapter/test_embeddings`, `integration/test_retrieval` |

**Default CI run:** `pytest --tb=short -q` → `addopts = "-ra"`
(`pyproject.toml` `[tool.pytest.ini_options]`; `testpaths = ["tests"]`,
recursive). The `-m "not slow" --strict-markers` filter from `AGENTS.md`
is passed on the command line, not stored in `addopts`.

---

## Conftest & Fixtures

- **Single root `tests/conftest.py`** holds all shared fixtures
  (`MockEmbedder`, `MockEngineAdapter`, `mock_llm`, `mock_embedder`,
  `glossary_terms`, `glossary_index`, `config`, `sample_state`) and the
  `FIXTURES_DIR` / `GLOSSARY_SAMPLE` constants. Pytest auto-discovers the
  root conftest for every subdirectory, so all scopes share these fixtures
  with no duplication. There are no scope-specific fixtures, so per-scope
  `conftest.py` files are intentionally omitted (YAGNI).
- **`tests/fixtures/`** stays at the root; `unit/test_corpus_parser.py`
  resolves it via `Path(__file__).resolve().parent.parent / "fixtures"`.
- **No real Ollama daemon:** tests use the mock adapters from
  `conftest.py`; integration tests use temp directories, never the real
  `db/` artifacts.

---

## Cross-Test Imports

`integration/test_web_ui_docs.py` reuses the raw-OOXML/PDF builders from
sibling integration modules:

```python
from tests.integration.test_pdf import _build_test_pdf
from tests.integration.test_word import _build_docx
```

These resolve via pytest's rootdir sys.path insertion (project root is on
`sys.path` because the rootmost `conftest.py` lives at `tests/`); `tests`
and `tests/integration` are PEP 420 namespace packages (no `__init__.py`
needed). No other test file imports from a sibling test module.

---

## Per-File Ignores

`pyproject.toml` `[tool.ruff.lint.per-file-ignores]` tracks test paths that
need lint exceptions (long OOXML/PDF fixture literals, DI arg counts). After
the split, the tracked test paths are:

| Path | Ignores |
|---|---|
| `tests/conftest.py` | `PLR0913` |
| `tests/unit/test_nodes.py` | `PLR0913` |
| `tests/unit/test_glossary_conflict.py` | `PLR0913` |
| `tests/unit/test_security_hardening.py` | `E501` |
| `tests/integration/test_cli.py` | `PLR0913` |
| `tests/integration/test_excel.py` | `E501` |
| `tests/integration/test_web_ui_excel.py` | `E501`, `PLR0913` |
| `tests/integration/test_word.py` | `E501`, `PLR0913`, `I001` |
| `tests/integration/test_pdf.py` | `E501`, `PLR0913`, `I001` |

Update this table when moving/adding test files with lint exceptions.

---

## Notes

- **Document tests** (`integration/test_excel`, `test_word`, `test_pdf`,
  `test_web_ui_*`) build raw OOXML/PDF in-file — no openpyxl/python-docx/
  pypdf writer dependency in tests.
- **Two formerly-unmarked files** (`test_ollama_errors`, `test_security_hardening`)
  now carry module-level `pytestmark` (`adapter` and `unit` respectively) so
  marker-based selection (`-m adapter`, `-m unit`) matches the folder split.
- **CI** (`.github/workflows/ci.yml`) runs `pytest tests/ -q` — recursive
  discovery picks up the subdirectories with no workflow change needed.
