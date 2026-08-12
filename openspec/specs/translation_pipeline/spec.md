## Purpose

The LangGraph translation state machine: state schema, graph wiring, node functions, TM routing decision, versioned prompts, and the domain exception hierarchy. This component orchestrates the Translate → Audit → Revise loop with conditional edges, TM-based bypass, and bounded retry.
## Requirements
### Requirement: TranslationState schema

The translation pipeline SHALL operate on a `TranslationState` TypedDict (PEP 692) with 11 fields: `input_text` (str), `direction` (Literal "ar-en" | "en-ar"), `glossary_hits` (list[GlossaryHit]), `context_chunks` (list[ContextChunk]), `tm_hits` (list[TmHit]), `web_search_results` (list[WebSearchResult]), `draft` (str), `audit` (AuditVerdict | None), `revision_count` (int), `final_output` (str | None), and `warnings` (list[str]).

#### Scenario: Initial state for Arabic-to-English translation
- **GIVEN** a source text "المادة ١ من القانون المدني" and direction "ar-en"
- **WHEN** the pipeline initializes TranslationState
- **THEN** `input_text` = "المادة ١ من القانون المدني", `direction` = "ar-en", `glossary_hits` = [], `context_chunks` = [], `tm_hits` = [], `web_search_results` = [], `draft` = "", `audit` = None, `revision_count` = 0, `final_output` = None, `warnings` = []

#### Scenario: Direction type is constrained
- **GIVEN** the `Direction` type alias
- **WHEN** a value is assigned to the `direction` field
- **THEN** only "ar-en" or "en-ar" are accepted; any other value is a type error

### Requirement: Sub-TypedDicts for state payload

The state SHALL carry five sub-TypedDicts: `GlossaryHit` (source_term, target_term, law_ref, article_ref, note, char_start, char_end), `ContextChunk` (text, law, article, score), `AuditVerdict` (verdict, critique, violations, confidence), `TmHit` (source_sentence, target_sentence, similarity, char_start, char_end), and `WebSearchResult` (title, url, snippet, source).

#### Scenario: GlossaryHit fields
- **GIVEN** a glossary term match found in source text
- **WHEN** the match is projected into a GlossaryHit
- **THEN** the TypedDict contains source_term, target_term, law_ref, article_ref, note, char_start, char_end

#### Scenario: AuditVerdict verdict values
- **GIVEN** the `Verdict` type alias
- **WHEN** the Auditor returns a verdict
- **THEN** the value is either "APPROVE" or "REVISE"

### Requirement: LangGraph node identifiers

The graph SHALL define seven node identifier constants: `PREPROCESS_NODE` = "preprocess", `WEB_SEARCH_NODE` = "web_search", `TM_LOOKUP_NODE` = "tm_lookup", `TM_BYPASS_NODE` = "tm_bypass", `TRANSLATE_NODE` = "translate", `AUDIT_NODE` = "auditor" (named "auditor" to avoid collision with the state field "audit"), and `FINALIZE_NODE` = "finalize".

#### Scenario: Auditor node name avoids state field collision
- **GIVEN** the graph is built with an audit node
- **WHEN** the node identifier is registered
- **THEN** it is "auditor", not "audit", to avoid collision with the TranslationState field `audit`

### Requirement: Graph flow order

The compiled LangGraph SHALL execute nodes in this order: preprocess → web_search → tm_lookup → route_after_tm (conditional). If TM similarity is high (≥ threshold), the flow goes tm_bypass → finalize → END. If TM similarity is low, the flow goes translate → audit → route_audit (conditional). If the Auditor approves or max revisions is reached, the flow goes finalize → END. If the Auditor requests revision and the limit is not reached, the flow loops back to translate.

#### Scenario: High-similarity TM hit bypasses translation
- **GIVEN** a TM lookup returns a hit with similarity ≥ the configured threshold
- **WHEN** route_after_tm evaluates the state
- **THEN** the flow routes to tm_bypass → finalize → END, skipping the translate and audit nodes

#### Scenario: Low-similarity TM hit proceeds to translation
- **GIVEN** a TM lookup returns a hit with similarity < the configured threshold (or no hit)
- **WHEN** route_after_tm evaluates the state
- **THEN** the flow routes to translate → audit

#### Scenario: Auditor approves on first pass
- **GIVEN** the Auditor returns verdict "APPROVE"
- **WHEN** route_audit evaluates the state
- **THEN** the flow routes to finalize → END

#### Scenario: Auditor requests revision under the limit
- **GIVEN** the Auditor returns verdict "REVISE" and revision_count < max_revisions
- **WHEN** route_audit evaluates the state
- **THEN** the flow loops back to translate

#### Scenario: Max revisions reached forces finalization
- **GIVEN** revision_count ≥ max_revisions regardless of Auditor verdict
- **WHEN** route_audit evaluates the state
- **THEN** the flow routes to finalize → END

### Requirement: build_graph dependency injection

`build_graph` SHALL accept all dependencies as keyword-only arguments: `llm` (LLMEngineAdapter), `cfg` (AppConfig), `glossary_index` (GlossaryIndex), `embedder` (EmbeddingAdapter), `persist_dir` (Path), `run_logger` (RunLogger), and `tm` (TranslationMemory). It returns a compiled LangGraph.

#### Scenario: build_graph with all injected dependencies
- **GIVEN** concrete adapters for llm, embedder, glossary_index, run_logger, tm, a config, and a persist_dir
- **WHEN** build_graph is called with all keyword-only arguments
- **THEN** a compiled LangGraph is returned with all nodes and conditional edges wired

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

### Requirement: TM routing decision function

`route_tm(hit: TmHit | None, *, threshold: float) -> bool` SHALL return True if the TM hit's similarity is ≥ the threshold, meaning the TM translation should be used directly (bypassing the LLM). Returns False if the hit is None or similarity is below threshold.

#### Scenario: Hit above threshold
- **GIVEN** a TmHit with similarity 0.95 and threshold 0.90
- **WHEN** route_tm is called
- **THEN** it returns True

#### Scenario: Hit below threshold
- **GIVEN** a TmHit with similarity 0.80 and threshold 0.90
- **WHEN** route_tm is called
- **THEN** it returns False

#### Scenario: No hit
- **GIVEN** hit is None and threshold 0.90
- **WHEN** route_tm is called
- **THEN** it returns False

### Requirement: Versioned prompt constants

Prompts SHALL be versioned constants V1 through V4. Each version provides: `SHARED_SYSTEM_RULES_V{n}`, `TRANSLATOR_SYSTEM_V{n}`, `TRANSLATOR_REVISION_ADDENDUM_V{n}`, `TRANSLATOR_USER_TEMPLATE_V{n}`, `AUDITOR_SYSTEM_V{n}`, `AUDITOR_USER_TEMPLATE_V{n}`. V4 is the current default and adds Arabic script enforcement and romanization detection. An `ALL_PROMPT_CONSTANTS` dictionary maps all constant names to their values for regression tests. `ALL_PROMPT_CONSTANTS` SHALL be auto-generated at module load via introspection of module-level prompt constants (e.g., a comprehension over `globals()` filtered by a naming convention), NOT hand-maintained as a dict literal. Adding a new prompt constant SHALL NOT require editing `ALL_PROMPT_CONSTANTS` (it is picked up automatically).

#### Scenario: V4 is the current default
- **GIVEN** the nodes use prompt constants
- **WHEN** translate_node and audit_node build their prompts
- **THEN** they use TRANSLATOR_SYSTEM_V4, TRANSLATOR_USER_TEMPLATE_V4, AUDITOR_SYSTEM_V4, AUDITOR_USER_TEMPLATE_V4, and TRANSLATOR_REVISION_ADDENDUM_V4

#### Scenario: ALL_PROMPT_CONSTANTS contains every version
- **GIVEN** the ALL_PROMPT_CONSTANTS dictionary
- **WHEN** its keys are inspected
- **THEN** it contains all V1, V2, V3, and V4 constant names

#### Scenario: ALL_PROMPT_CONSTANTS is auto-generated
- **GIVEN** the `prompts.py` source
- **WHEN** `ALL_PROMPT_CONSTANTS` is inspected
- **THEN** it is built by introspection (e.g., a comprehension over `globals()` filtered by a naming convention or a decorator), not a hand-written dict literal

#### Scenario: a new prompt constant appears in the registry automatically
- **GIVEN** a new module-level prompt constant `TRANSLATOR_SYSTEM_V5` is added to `prompts.py`
- **WHEN** the module is re-imported
- **THEN** `ALL_PROMPT_CONSTANTS["TRANSLATOR_SYSTEM_V5"]` exists without any edit to the registry definition

### Requirement: Domain exception hierarchy

All domain exceptions MUST derive from `LegalTranslationError`. The hierarchy includes: `AdapterError`, `GlossaryError` (with `GlossaryConflictError`, `GlossaryValidationError`), `CorpusError` (with `CorpusParseError`, `CorpusEncodingError`), `RetrievalError` (with `ChromaDBCorruptionError`), `LLMRuntimeError` (with `OllamaConnectionError`, `OllamaTimeoutError`, `OllamaModelNotLoadedError`, `LlamaCppConnectionError`, `LlamaCppTimeoutError`), `EmbeddingError` (with `EmbeddingConnectionError`, `EmbeddingTimeoutError`), `AuditParseError`, and `RAMGuardError`.

#### Scenario: All exceptions inherit from LegalTranslationError
- **GIVEN** any exception class in the hierarchy
- **WHEN** it is raised and caught
- **THEN** it is an instance of LegalTranslationError

#### Scenario: OllamaTimeoutError inherits from OllamaConnectionError
- **GIVEN** an OllamaTimeoutError is raised
- **WHEN** it is caught as OllamaConnectionError
- **THEN** the catch succeeds because OllamaTimeoutError inherits from OllamaConnectionError

### Requirement: Translation pipeline component folder

The translation pipeline SHALL reside in `src/components/translation_pipeline/` as a bounded-context component. The folder SHALL contain: `__init__.py` (re-exports), `models.py`, `graph.py`, `nodes.py`, `decision.py`, `prompts.py`, and `exceptions.py`.

#### Scenario: Component folder structure
- **GIVEN** the refactored project structure
- **WHEN** the `src/components/translation_pipeline/` directory is inspected
- **THEN** it contains `__init__.py`, `models.py`, `graph.py`, `nodes.py`, `decision.py`, `prompts.py`, and `exceptions.py`

### Requirement: Translation pipeline models module

All TypedDicts, type aliases, and the state schema SHALL reside in `src/components/translation_pipeline/models.py`. This includes: `TranslationState`, `GlossaryHit`, `ContextChunk`, `AuditVerdict`, `TmHit`, `WebSearchResult`, `Direction`, and `Verdict`.

#### Scenario: Import TranslationState from component models
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline.models import TranslationState` is executed
- **THEN** TranslationState is imported successfully with all 11 fields

#### Scenario: Import Direction and Verdict from component models
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline.models import Direction, Verdict` is executed
- **THEN** both type aliases are imported successfully

### Requirement: Translation pipeline graph module

`build_graph`, `route_audit`, `route_after_tm`, and all node identifier constants (`PREPROCESS_NODE`, `WEB_SEARCH_NODE`, `TM_LOOKUP_NODE`, `TM_BYPASS_NODE`, `TRANSLATE_NODE`, `AUDIT_NODE`, `FINALIZE_NODE`) SHALL reside in `src/components/translation_pipeline/graph.py`.

#### Scenario: Import build_graph from component graph
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline.graph import build_graph` is executed
- **THEN** build_graph is imported successfully

### Requirement: Translation pipeline nodes module

All node functions (`preprocess_node`, `web_search_node`, `tm_lookup_node`, `tm_bypass_node`, `translate_node`, `audit_node`, `finalize_node`) and their helper functions SHALL reside in `src/components/translation_pipeline/nodes.py`.

#### Scenario: Import node functions from component nodes
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline.nodes import preprocess_node, translate_node, audit_node, finalize_node` is executed
- **THEN** all node functions are imported successfully

### Requirement: Translation pipeline decision module

`route_tm` SHALL reside in `src/components/translation_pipeline/decision.py`.

#### Scenario: Import route_tm from component decision
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline.decision import route_tm` is executed
- **THEN** route_tm is imported successfully

### Requirement: Translation pipeline prompts module

All versioned prompt constants (V1–V4) and `ALL_PROMPT_CONSTANTS` SHALL reside in `src/components/translation_pipeline/prompts.py`.

#### Scenario: Import V4 prompts from component prompts
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline.prompts import TRANSLATOR_SYSTEM_V4, AUDITOR_SYSTEM_V4, ALL_PROMPT_CONSTANTS` is executed
- **THEN** all symbols are imported successfully

### Requirement: Translation pipeline exceptions module

The complete domain exception hierarchy rooted at `LegalTranslationError` SHALL reside in `src/components/translation_pipeline/exceptions.py`.

#### Scenario: Import exceptions from component exceptions
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline.exceptions import LegalTranslationError, OllamaConnectionError, RAMGuardError` is executed
- **THEN** all exception classes are imported successfully

### Requirement: Translation pipeline public API re-export

`src/components/translation_pipeline/__init__.py` SHALL re-export the component's public API so that `from src.components.translation_pipeline import TranslationState, build_graph, route_tm` works without specifying the submodule.

#### Scenario: Re-exported public API
- **GIVEN** the refactored structure
- **WHEN** `from src.components.translation_pipeline import TranslationState, build_graph, route_tm, LegalTranslationError` is executed
- **THEN** all symbols are imported successfully via the package __init__

### Requirement: Translation pipeline intra-component imports

Modules within `translation_pipeline/` SHALL import from sibling modules within the same component using relative or absolute component paths (e.g., `from src.components.translation_pipeline.models import TranslationState`), not from the old flat `src.state` paths.

#### Scenario: nodes.py imports from component models
- **GIVEN** the refactored nodes.py
- **WHEN** its imports are inspected
- **THEN** it imports TranslationState from `src.components.translation_pipeline.models`, not from `src.state`

#### Scenario: graph.py imports from component nodes
- **GIVEN** the refactored graph.py
- **WHEN** its imports are inspected
- **THEN** it imports node functions from `src.components.translation_pipeline.nodes`, not from `src.nodes`

### Requirement: Node module single responsibility

The `nodes.py` module SHALL contain only pure node functions (`preprocess_node`, `web_search_node`, `tm_lookup_node`, `tm_bypass_node`, `translate_node`, `audit_node`, `finalize_node`). Prompt formatting helpers (`_format_glossary_bindings`, `_format_context_chunks`, `_format_web_search_results`, `_augment_query_for_retrieval`, `_langs`) SHALL reside in `formatters.py`. JSON parsing and validation logic (`_parse_verdict`) SHALL reside in `parsers.py`. Type-conversion helpers (`_hit_to_state`, `_chunk_to_state`) SHALL reside in `mappers.py`. Each node function SHALL be ≤ 40 lines (excluding docstrings).

#### Scenario: nodes.py contains only node functions
- **GIVEN** the `translation_pipeline/nodes.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains only the seven node functions and the `_logged` decorator; no formatting, parsing, or mapping helpers

#### Scenario: Formatters are in a separate module
- **GIVEN** the `translation_pipeline/formatters.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_format_glossary_bindings`, `_format_context_chunks`, `_format_web_search_results`, `_augment_query_for_retrieval`, and `_langs`

#### Scenario: Parsers are in a separate module
- **GIVEN** the `translation_pipeline/parsers.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_parse_verdict` and any JSON validation helpers

#### Scenario: Mappers are in a separate module
- **GIVEN** the `translation_pipeline/mappers.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_hit_to_state` and `_chunk_to_state`

#### Scenario: Node functions are ≤ 40 lines
- **GIVEN** any node function in `nodes.py`
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 40 lines

### Requirement: Prompt version protocol for open/closed extension

`prompts.py` SHALL define a `PromptVersion` protocol (PEP 544) with fields: `shared_system_rules`, `translator_system`, `translator_revision_addendum`, `translator_user_template`, `auditor_system`, `auditor_user_template`. Each version (V1–V4) SHALL be a `NamedTuple` or dataclass implementing this protocol. `nodes.py` SHALL receive the active prompt version as a keyword-only argument (default: V4) instead of importing V4 constants directly. Adding a new prompt version (V5) SHALL require only adding a new `PromptVersion` implementation and registering it, not modifying `nodes.py`.

#### Scenario: V4 is the current default
- **GIVEN** the nodes use prompt constants
- **WHEN** translate_node and audit_node build their prompts without an explicit version argument
- **THEN** they use the V4 PromptVersion implementation

#### Scenario: V5 is added without modifying nodes.py
- **GIVEN** a new V5 PromptVersion implementation is added to `prompts.py`
- **WHEN** translate_node is called with `prompts=V5`
- **THEN** it uses the V5 translator system and user template without any changes to `nodes.py`

#### Scenario: ALL_PROMPT_CONSTANTS contains every version
- **GIVEN** the ALL_PROMPT_CONSTANTS dictionary
- **WHEN** its keys are inspected
- **THEN** it contains all V1, V2, V3, and V4 constant names

### Requirement: Pipeline adapter protocols for dependency inversion

The translation pipeline SHALL define three PEP 544 protocols for external dependencies: `GlossaryScanner` with `scan(text: str, lang: Lang) -> list[GlossaryHit]`, `ContextRetriever` with `retrieve(query: str, n: int) -> list[ContextChunk]`, and `WebSearcher` with `search(query: str) -> list[WebSearchResult]`. Node functions SHALL depend on these protocols (typed as the protocol) instead of importing concrete classes (`GlossaryIndex`, `scan_glossary_hits`, `retrieve_context_chunks`, `search_all_sources`).

#### Scenario: preprocess_node depends on GlossaryScanner protocol
- **GIVEN** the `preprocess_node` function signature is inspected
- **WHEN** the type of the glossary parameter is checked
- **THEN** it is typed as `GlossaryScanner` (protocol), not `GlossaryIndex` (concrete class)

#### Scenario: preprocess_node depends on ContextRetriever protocol
- **GIVEN** the `preprocess_node` function signature is inspected
- **WHEN** the type of the retriever parameter is checked
- **THEN** it is typed as `ContextRetriever` (protocol), not a concrete function reference

#### Scenario: web_search_node depends on WebSearcher protocol
- **GIVEN** the `web_search_node` function signature is inspected
- **WHEN** the type of the searcher parameter is checked
- **THEN** it is typed as `WebSearcher` (protocol), not a concrete function reference

#### Scenario: Concrete implementations satisfy the protocols
- **GIVEN** a `GlossaryIndex` instance with a `scan` method
- **WHEN** it is checked against the `GlossaryScanner` protocol
- **THEN** it satisfies the protocol (structural subtyping)

### Requirement: Pipeline constants module

The `translation_pipeline/constants.py` module SHALL define named constants for all magic strings used across the pipeline: `DIRECTION_AR_EN = "ar-en"`, `DIRECTION_EN_AR = "en-ar"`, `LANG_AR = "ar"`, `LANG_EN = "en"`, `VERDICT_APPROVE = "APPROVE"`, `VERDICT_REVISE = "REVISE"`, `NA_PLACEHOLDER = "N/A"`. All modules within the translation_pipeline component SHALL import these constants instead of using string literals.

#### Scenario: Direction constants are used
- **GIVEN** any module in the translation_pipeline component
- **WHEN** it references a direction string
- **THEN** it imports and uses `DIRECTION_AR_EN` or `DIRECTION_EN_AR` from `constants.py`, not a bare string literal

#### Scenario: Verdict constants are used
- **GIVEN** any module in the translation_pipeline component
- **WHEN** it references a verdict value
- **THEN** it imports and uses `VERDICT_APPROVE` or `VERDICT_REVISE` from `constants.py`, not a bare string literal

### Requirement: Graph type annotations use protocols

`build_graph` SHALL type all dependency parameters with proper protocol types: `llm` as `LLMEngineAdapter`, `embedder` as `EmbeddingAdapter`, `tm` as `TranslationMemory` (or a `TranslationMemoryAdapter` protocol), and `persist_dir` as `Path`. No parameter SHALL be typed as `object` or `object | None`.

#### Scenario: build_graph types embedder as EmbeddingAdapter
- **GIVEN** the `build_graph` function signature is inspected
- **WHEN** the type of the `embedder` parameter is checked
- **THEN** it is typed as `EmbeddingAdapter`, not `object | None`

#### Scenario: build_graph types tm as TranslationMemory
- **GIVEN** the `build_graph` function signature is inspected
- **WHEN** the type of the `tm` parameter is checked
- **THEN** it is typed as `TranslationMemory` or a protocol, not `object | None`

### Requirement: Auditor verdict confidence validation

`parse_audit_verdict` (and any other parser that reads an auditor-produced `confidence` field) SHALL validate that the parsed `confidence` is a finite float in the `[0.0, 1.0]` range. An out-of-range value (including `nan` and `inf`) SHALL raise `AuditParseError` (a `LegalTranslationError` subclass) with a message naming the offending value.

#### Scenario: an out-of-range confidence is rejected
- **GIVEN** a raw auditor output with `confidence: 1.5`
- **WHEN** parse_audit_verdict is called
- **THEN** `AuditParseError` is raised with a message naming the value 1.5

#### Scenario: a NaN confidence is rejected
- **GIVEN** a raw auditor output with `confidence` parsed as `NaN`
- **WHEN** parse_audit_verdict is called
- **THEN** `AuditParseError` is raised (NaN is not in `[0.0, 1.0]`)

#### Scenario: an infinite confidence is rejected
- **GIVEN** a raw auditor output with `confidence` parsed as `inf`
- **WHEN** parse_audit_verdict is called
- **THEN** `AuditParseError` is raised (inf is not in `[0.0, 1.0]`)

#### Scenario: a valid confidence is accepted
- **GIVEN** a raw auditor output with `confidence: 0.95`
- **WHEN** parse_audit_verdict is called
- **THEN** an AuditVerdict with confidence=0.95 is returned (no exception)

