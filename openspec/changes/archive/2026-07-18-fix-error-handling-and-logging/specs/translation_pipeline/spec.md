## MODIFIED Requirements

### Requirement: Node functions mutate state

Each node function MUST receive the current TranslationState and its injected dependencies as keyword-only args, and return an updated TranslationState partial dict. The seven node functions are: `preprocess_node`, `web_search_node`, `tm_lookup_node`, `tm_bypass_node`, `translate_node`, `audit_node`, `finalize_node`. The `web_search_node` SHALL catch only `(httpx.HTTPError, ValueError, LegalSearchError)` from the injected `WebSearcher` — NOT bare `Exception` — and on any caught exception SHALL log a warning via `logging.getLogger(__name__).warning(...)` naming the query and the error, then set `web_search_results = []` so the pipeline continues without web context. `KeyboardInterrupt`, `SystemExit`, and `MemoryError` SHALL propagate.

#### Scenario: preprocess_node scans glossary and retrieves context
- **GIVEN** a TranslationState with input_text and direction, plus glossary_index, embedder, persist_dir, and cfg
- **WHEN** preprocess_node runs
- **THEN** the returned state has `glossary_hits` populated from glossary scan and `context_chunks` populated from retrieval

#### Scenario: translate_node produces a draft
- **GIVEN** a TranslationState with glossary_hits, context_chunks, and web_search_results, plus llm and cfg
- **WHEN** translate_node runs
- **THEN** the returned state has `draft` set to the LLM-generated translation

#### Scenario: audit_node produces a verdict
- **GIVEN** a TranslationState with a draft, plus llm and cfg
- **WHEN** audit_node runs
- **THEN** the returned state has `audit` set to an AuditVerdict with verdict, critique, violations, and confidence

#### Scenario: finalize_node sets final_output
- **GIVEN** a TranslationState with a draft or a TM bypass result, plus cfg
- **WHEN** finalize_node runs
- **THEN** the returned state has `final_output` set to the final translation string

#### Scenario: web_search_node logs and continues on a search failure
- **GIVEN** a `WebSearcher` whose `search(query)` raises `httpx.HTTPError`
- **WHEN** `web_search_node` runs
- **THEN** a warning is logged via `logger.warning(...)` naming the query and the error, the returned state has `web_search_results = []`, and the pipeline continues (no exception propagates)

#### Scenario: web_search_node does not swallow KeyboardInterrupt
- **GIVEN** a `WebSearcher` whose `search(query)` raises `KeyboardInterrupt`
- **WHEN** `web_search_node` runs
- **THEN** `KeyboardInterrupt` propagates out of `web_search_node` (it is NOT caught by the narrowed `except (httpx.HTTPError, ValueError, LegalSearchError)` clause)
