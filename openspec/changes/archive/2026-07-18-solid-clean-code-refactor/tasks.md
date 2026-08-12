## 1. Infrastructure — Shared Error Translation (DRY)

- [x] 1.1 Create `src/components/infrastructure/ollama_errors.py` with shared `translate_engine_error(err, *, model, kind) -> Exception` function that maps Ollama exceptions to domain hierarchy
- [x] 1.2 Update `llm.py` to import `translate_engine_error` from `ollama_errors.py` and remove its local `_translate_engine_error` copy
- [x] 1.3 Update `embeddings.py` to import `translate_engine_error` from `ollama_errors.py` and remove its local `_translate_engine_error` copy
- [x] 1.4 Verify: `python -c "import src.components.infrastructure.llm; import src.components.infrastructure.embeddings; import src.components.infrastructure.ollama_errors"` and `pytest --tb=short -q`

## 2. Infrastructure — Remove load_config() from Adapter Constructors (DIP)

- [x] 2.1 Update `OllamaEngineAdapter.__init__` in `llm.py` to remove the `load_config()` fallback; require `model` and `host` as mandatory keyword-only args
- [x] 2.2 Update `Embedder.__init__` in `embeddings.py` to remove the `load_config()` fallback; require `model` and `host` as mandatory keyword-only args
- [x] 2.3 Update `ChromaStore.__init__` in `retrieval.py` to accept `embedder: EmbeddingAdapter` and `cfg: AppConfig` as keyword-only args; remove internal `load_config()` and `Embedder()` calls
- [x] 2.4 Update all callers of `OllamaEngineAdapter`, `Embedder`, and `ChromaStore` to pass config explicitly (check `cli.py:_construct_adapters` and test fixtures)
- [x] 2.5 Verify: `pytest --tb=short -q` and `mypy src/components/infrastructure/`

## 3. Infrastructure — Platform Registry and Run Logging Decomposition (OCP, SRP)

- [x] 3.1 Update `memory.py` to use `_PLATFORM_READERS: dict[str, Callable[[], MemoryInfo | None]]` registry instead of if-else chains; extract `_read_memory_info_windows` to module level
- [x] 3.2 Update `run_logging.py` to decompose `log_node` into `_extract_state_snapshot(state) -> dict` and `_serialize_record(node_name, latency_ms, snapshot) -> str`; `log_node` must be ≤ 20 lines
- [x] 3.3 Verify: `pytest --tb=short -q` and `mypy src/components/infrastructure/`

## 4. Infrastructure — Update __init__.py Re-exports

- [x] 4.1 Update `src/components/infrastructure/__init__.py` to re-export `translate_engine_error` from `ollama_errors.py`
- [x] 4.2 Verify: `python -c "from src.components.infrastructure import translate_engine_error"` and `pytest --tb=short -q`

## 5. Infrastructure — Full Verification

- [x] 5.1 Run `pytest --tb=short -q`, `ruff check src/components/infrastructure/`, `mypy src/components/infrastructure/` — all must pass

## 6. Translation Pipeline — Constants and Protocols (Clean Code, DIP)

- [x] 6.1 Create `src/components/translation_pipeline/constants.py` with `DIRECTION_AR_EN`, `DIRECTION_EN_AR`, `LANG_AR`, `LANG_EN`, `VERDICT_APPROVE`, `VERDICT_REVISE`, `NA_PLACEHOLDER`
- [x] 6.2 Create `src/components/translation_pipeline/protocols.py` with `GlossaryScanner`, `ContextRetriever`, `WebSearcher` PEP 544 protocols
- [x] 6.3 Verify: `python -c "import src.components.translation_pipeline.constants; import src.components.translation_pipeline.protocols"`

## 7. Translation Pipeline — PromptVersion Protocol (OCP)

- [x] 7.1 Update `prompts.py` to add `PromptVersion` protocol with fields: `shared_system_rules`, `translator_system`, `translator_revision_addendum`, `translator_user_template`, `auditor_system`, `auditor_user_template`
- [x] 7.2 Add `PromptV1`, `PromptV2`, `PromptV3`, `PromptV4` NamedTuple/dataclass implementations of `PromptVersion`
- [x] 7.3 Add `DEFAULT_PROMPT_VERSION: PromptVersion = PromptV4()` constant
- [x] 7.4 Verify: `python -c "from src.components.translation_pipeline.prompts import DEFAULT_PROMPT_VERSION, PromptVersion"` and `pytest --tb=short -q`

## 8. Translation Pipeline — Extract formatters.py, parsers.py, mappers.py (SRP)

- [x] 8.1 Create `formatters.py` — extract `_format_glossary_bindings`, `_format_context_chunks`, `_format_web_search_results`, `_augment_query_for_retrieval`, `_langs` from `nodes.py`
- [x] 8.2 Create `parsers.py` — extract `_parse_verdict` and JSON validation helpers from `nodes.py`
- [x] 8.3 Create `mappers.py` — extract `_hit_to_state`, `_chunk_to_state` from `nodes.py`
- [x] 8.4 Update `nodes.py` to import from `formatters.py`, `parsers.py`, `mappers.py` instead of defining them inline
- [x] 8.5 Verify: `python -c "import src.components.translation_pipeline.nodes"` and `pytest --tb=short -q`

## 9. Translation Pipeline — Update nodes.py for DIP, OCP, Constants

- [x] 9.1 Update `nodes.py` to use protocol types (`GlossaryScanner`, `ContextRetriever`, `WebSearcher`) instead of concrete imports (`GlossaryIndex`, `scan_glossary_hits`, `retrieve_context_chunks`, `search_all_sources`)
- [x] 9.2 Update `nodes.py` to accept `prompts: PromptVersion = DEFAULT_PROMPT_VERSION` as keyword-only arg instead of importing V4 constants directly
- [x] 9.3 Update `nodes.py` to import and use constants from `constants.py` instead of magic strings
- [x] 9.4 Decompose any node function > 40 lines into helpers (extract sub-functions, use early returns)
- [x] 9.5 Resolve all `# type: ignore` comments in `nodes.py` by fixing underlying type issues
- [x] 9.6 Verify: `pytest --tb=short -q` and `mypy src/components/translation_pipeline/nodes.py`

## 10. Translation Pipeline — Update graph.py (DIP, Composition Root)

- [x] 10.1 Add adapter wrapper classes (`_GlossaryScannerAdapter`, `_ContextRetrieverAdapter`, `_WebSearcherAdapter`) to `graph.py` that wrap concrete implementations into protocol-satisfying objects
- [x] 10.2 Update `build_graph` to type `embedder` as `EmbeddingAdapter`, `tm` as `TranslationMemory`, `persist_dir` as `Path` — not `object | None`
- [x] 10.3 Update `build_graph` to construct adapter wrappers and pass protocol-typed deps to node functions
- [x] 10.4 Update `build_graph` to accept and pass `PromptVersion` to nodes that need it
- [x] 10.5 Decompose `build_graph` if > 40 lines: extract `_bind_nodes`, `_add_edges` helpers
- [x] 10.6 Verify: `pytest --tb=short -q` and `mypy src/components/translation_pipeline/graph.py`

## 11. Translation Pipeline — Update __init__.py Re-exports

- [x] 11.1 Update `src/components/translation_pipeline/__init__.py` to re-export new modules: `constants`, `protocols`, `formatters`, `parsers`, `mappers`, `PromptVersion`, `DEFAULT_PROMPT_VERSION`
- [x] 11.2 Verify: `python -c "from src.components.translation_pipeline import constants, protocols, formatters, parsers, mappers"` and `pytest --tb=short -q`

## 12. Translation Pipeline — Full Verification

- [x] 12.1 Run `pytest --tb=short -q`, `ruff check src/components/translation_pipeline/`, `mypy src/components/translation_pipeline/` — all must pass

## 13. Knowledge Sources — Split ingestion.py (SRP)

- [x] 13.1 Create `manifest.py` — extract `_write_manifest`, `_compute_file_hash`, file categorization logic from `ingestion.py`
- [x] 13.2 Create `ingestion_runner.py` — extract `run_ingestion`, `_iter_corpus_chunks`, progress reporting from `ingestion.py`
- [x] 13.3 Update `ingestion.py` to import from `manifest.py` and `ingestion_runner.py`; keep only parsing/chunking functions
- [x] 13.4 Decompose `iter_articles` (> 40 lines) into sub-functions for header parsing, body assembly, metadata extraction
- [x] 13.5 Verify: `python -c "import src.components.knowledge_sources.ingest_corpus"` and `pytest --tb=short -q`

## 14. Knowledge Sources — Decompose tm.py lookup (SRP)

- [x] 14.1 Add `_extract_trigrams(text) -> set[str]` method to `TranslationMemory`
- [x] 14.2 Add `_trigram_candidates(trigrams) -> list[str]` method to `TranslationMemory`
- [x] 14.3 Add `_full_scan_candidates() -> list[str]` method to `TranslationMemory`
- [x] 14.4 Add `_verify_candidates(query, candidates) -> TmHit | None` method to `TranslationMemory`
- [x] 14.5 Update `lookup` to orchestrate these helpers; ensure `lookup` is ≤ 30 lines
- [x] 14.6 Verify: `pytest --tb=short -q` (TM lookup tests must pass unchanged)

## 15. Knowledge Sources — Normalizer Registry and Term Factory (OCP, DRY)

- [x] 15.1 Add `Normalizer` protocol to `glossary.py` with `normalize(term: str) -> str` method
- [x] 15.2 Create `_NORMALIZERS: dict[str, Normalizer]` registry in `glossary.py`; update `normalize()` to dispatch via registry
- [x] 15.3 Add `Term.from_row(row: sqlite3.Row) -> Term` and `Term.from_dict(data: dict) -> Term` classmethods to eliminate duplicated construction
- [x] 15.4 Update all Term construction sites to use the factory methods
- [x] 15.5 Verify: `pytest --tb=short -q` (glossary tests must pass unchanged)

## 16. Knowledge Sources — ChromaStore DI and Shared Factory (DIP, DRY)

- [x] 16.1 Update `ChromaStore.__init__` to accept `embedder: EmbeddingAdapter` and `cfg: AppConfig` as keyword-only args (if not already done in task 2.3)
- [x] 16.2 Create `_create_store(persist_dir, embedder, cfg) -> ChromaStore` shared factory function in `retrieval.py`
- [x] 16.3 Update all module-level functions (`build_chroma_collection`, `query_chroma`, etc.) to use `_create_store()` instead of duplicating `ChromaStore(persist_dir=...)`
- [x] 16.4 Verify: `pytest --tb=short -q` (retrieval tests must pass unchanged)

## 17. Knowledge Sources — Search Source Registry (OCP)

- [x] 17.1 Add `SearchSource` dataclass to `legal_search.py` with `name: str` and `search: Callable` fields
- [x] 17.2 Create `_SOURCES: list[SearchSource]` registry; wrap each search function in a `SearchSource` instance
- [x] 17.3 Update `search_all_sources` to iterate over `_SOURCES` instead of hardcoding the function list
- [x] 17.4 Verify: `pytest --tb=short -q` (legal search tests must pass unchanged)

## 18. Knowledge Sources — Update __init__.py Re-exports

- [x] 18.1 Update `src/components/knowledge_sources/__init__.py` to re-export new modules: `manifest`, `ingestion_runner`
- [x] 18.2 Verify: `python -c "from src.components.knowledge_sources import manifest, ingestion_runner"` and `pytest --tb=short -q`

## 19. Knowledge Sources — Full Verification

- [x] 19.1 Run `pytest --tb=short -q`, `ruff check src/components/knowledge_sources/`, `mypy src/components/knowledge_sources/` — all must pass

## 20. Interfaces — Shared Config Loader (DRY)

- [x] 20.1 Create `src/components/interfaces/config_loader.py` with `load_or_exit(path: Path | None = None) -> AppConfig` helper
- [x] 20.2 Verify: `python -c "from src.components.interfaces.config_loader import load_or_exit"`

## 21. Interfaces — Split cli.py (SRP)

- [x] 21.1 Create `diagnostics.py` — extract all `_check_*` functions and `_detect_offload_mode` from `cli.py`
- [x] 21.2 Create `orchestration.py` — extract `_run_translation`, `_run_translation_streamed`, `_initial_state`, `_translate_for_ui`, `_provenance_markdown`, `_audit_trace_markdown`, `_render_provenance` from `cli.py`
- [x] 21.3 Create `tm_commands.py` — extract TM command handler logic (`tm_build`, `tm_build_parallel`, `tm_add_parallel`) from `cli.py`
- [x] 21.4 Update `cli.py` to import from `diagnostics.py`, `orchestration.py`, `tm_commands.py`, `config_loader.py`; slim to thin command wrappers (≤ 20 lines each)
- [x] 21.5 Update all CLI commands to use `load_or_exit()` instead of duplicating try/except/load_config
- [x] 21.6 Verify: `pytest --tb=short -q` (CLI tests must pass unchanged)

## 22. Interfaces — Split web_ui.py (SRP)

- [x] 22.1 Create `web_frontend.py` — extract the `_HTML` constant from `web_ui.py`
- [x] 22.2 Update `web_ui.py` to import `HTML` from `web_frontend.py`
- [x] 22.3 Verify: `python -c "import src.components.interfaces.web_ui"` and `pytest --tb=short -q`

## 23. Interfaces — Decompose hitl.py (SRP, DIP)

- [x] 23.1 Add `_handle_review_decision` helper to `hitl.py`
- [x] 23.2 Add `_re_audit_if_edited` helper to `hitl.py`
- [x] 23.3 Update `human_review` to orchestrate helpers; ensure ≤ 25 lines
- [x] 23.4 Update `human_review` to type `llm` as `LLMEngineAdapter` and `tm` as `TranslationMemory` — not `object`
- [x] 23.5 Verify: `pytest --tb=short -q` (HITL tests must pass unchanged)

## 24. Interfaces — Adapters Segregation (ISP)

- [x] 24.1 Add `LLMAdapters` dataclass (fields: `llm`, `embedder`) to `interfaces/models.py`
- [x] 24.2 Add `KnowledgeAdapters` dataclass (fields: `glossary_index`, `persist_dir`, `tm`) to `interfaces/models.py`
- [x] 24.3 Update `Adapters` to compose `LLMAdapters` and `KnowledgeAdapters` for backward compatibility
- [x] 24.4 Verify: `pytest --tb=short -q` (all tests using `Adapters` must pass unchanged)

## 25. Interfaces — Fix Protocol Types in cli.py and tk_ui.py (DIP)

- [x] 25.1 Update `_run_translation` and `_run_translation_streamed` in `orchestration.py` to type `embedder` as `EmbeddingAdapter` and `tm` as `TranslationMemory` — not `object`
- [x] 25.2 Update `tk_ui.py` to use proper protocol types instead of `object` for adapters
- [x] 25.3 Verify: `mypy src/components/interfaces/` — no `object` types for adapter parameters

## 26. Interfaces — Update __init__.py Re-exports

- [x] 26.1 Update `src/components/interfaces/__init__.py` to re-export new modules: `diagnostics`, `orchestration`, `tm_commands`, `config_loader`, `web_frontend`, `LLMAdapters`, `KnowledgeAdapters`
- [x] 26.2 Verify: `python -c "from src.components.interfaces import diagnostics, orchestration, tm_commands, config_loader"` and `pytest --tb=short -q`

## 27. Interfaces — Full Verification

- [x] 27.1 Run `pytest --tb=short -q`, `ruff check src/components/interfaces/`, `mypy src/components/interfaces/` — all must pass

## 28. Config — Separate CLI from Loading (SRP)

- [x] 28.1 Create `src/config/cli.py` — extract Typer `app` and `load` command from `config.py`
- [x] 28.2 Update `config.py` to remove CLI definitions; keep only `load_config`, `AppConfig`, `ConfigError`, `DEFAULT_CONFIG_PATH`
- [x] 28.3 Update `src/config/__init__.py` to re-export from both `config.py` and `cli.py`
- [x] 28.4 Verify: `python -c "from src.config import AppConfig, load_config, app"` and `pytest --tb=short -q`

## 29. Config — Add Validators (Clean Code)

- [x] 29.1 Add Pydantic validators to `PathsConfig` fields ensuring non-empty paths
- [x] 29.2 Add Pydantic validators to `ChromaConfig` fields ensuring valid ranges (hnsw_M ≥ 2, construction_ef ≥ 1, search_ef ≥ 1)
- [x] 29.3 Verify: `pytest --tb=short -q` (config tests must pass, including invalid-config tests)

## 30. Config — Update app.py (Clean Code)

- [x] 30.1 Remove unused `load_config` import from `app.py`
- [x] 30.2 Add `-> None` return type annotation to `main()`
- [x] 30.3 Verify: `mypy src/app.py` and `python -c "from src.app import main"`

## 31. Config — Full Verification

- [x] 31.1 Run `pytest --tb=short -q`, `ruff check src/config/ src/app.py`, `mypy src/config/ src/app.py` — all must pass

## 32. Cleanup — Resolve type: ignore Comments

- [x] 32.1 Search for all remaining `# type: ignore` comments in `src/` and resolve each by fixing the underlying type issue
- [x] 32.2 Verify: `grep -r "type: ignore" src/` returns zero results and `mypy src/` passes

## 33. Cleanup — Update pyproject.toml

- [x] 33.1 Update `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml` to add entries for all new files
- [x] 33.2 Remove any per-file-ignores for `cli.py` that are no longer needed after the split
- [x] 33.3 Verify: `ruff check src/ tests/` passes

## 34. Final Full-Suite Verification

- [x] 34.1 Run `pytest --tb=short -q` — all tests pass
- [x] 34.2 Run `ruff check src/ tests/` — no lint errors
- [x] 34.3 Run `mypy src/` — no type errors
- [x] 34.4 Run `openspec validate --all` — all specs and changes validate
- [x] 34.5 Run `python -m src.cli doctor` — smoke test passes
- [x] 34.6 Run `python -m src.cli translate --input "المادة ١" --direction ar-en` — smoke test passes
