## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Node functions mutate state

Each node function MUST receive the current TranslationState and its injected dependencies as keyword-only args, and return an updated TranslationState partial dict. The seven node functions are: `preprocess_node`, `web_search_node`, `tm_lookup_node`, `tm_bypass_node`, `translate_node`, `audit_node`, `finalize_node`. Node functions SHALL accept protocol-typed dependencies (`GlossaryScanner`, `ContextRetriever`, `WebSearcher`, `LLMEngineAdapter`) instead of concrete types. Each node function SHALL be ≤ 40 lines (excluding docstrings).

#### Scenario: preprocess_node scans glossary and retrieves context
- **GIVEN** a TranslationState with input_text and direction, plus a GlossaryScanner, ContextRetriever, and cfg
- **WHEN** preprocess_node runs
- **THEN** the returned state has `glossary_hits` populated from glossary scan and `context_chunks` populated from retrieval

#### Scenario: translate_node produces a draft
- **GIVEN** a TranslationState with glossary_hits, context_chunks, and web_search_results, plus an LLMEngineAdapter, a PromptVersion, and cfg
- **WHEN** translate_node runs
- **THEN** the returned state has `draft` set to the LLM-generated translation

#### Scenario: audit_node produces a verdict
- **GIVEN** a TranslationState with a draft, plus an LLMEngineAdapter, a PromptVersion, and cfg
- **WHEN** audit_node runs
- **THEN** the returned state has `audit` set to an AuditVerdict with verdict, critique, violations, and confidence

#### Scenario: finalize_node sets final_output
- **GIVEN** a TranslationState with a draft or a TM bypass result, plus cfg
- **WHEN** finalize_node runs
- **THEN** the returned state has `final_output` set to the final translation string
