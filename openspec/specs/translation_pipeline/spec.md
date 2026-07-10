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

Each node function MUST receive the current TranslationState and its injected dependencies as keyword-only args, and return an updated TranslationState partial dict. The seven node functions are: `preprocess_node`, `web_search_node`, `tm_lookup_node`, `tm_bypass_node`, `translate_node`, `audit_node`, `finalize_node`.

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

Prompts SHALL be versioned constants V1 through V4. Each version provides: `SHARED_SYSTEM_RULES_V{n}`, `TRANSLATOR_SYSTEM_V{n}`, `TRANSLATOR_REVISION_ADDENDUM_V{n}`, `TRANSLATOR_USER_TEMPLATE_V{n}`, `AUDITOR_SYSTEM_V{n}`, `AUDITOR_USER_TEMPLATE_V{n}`. V4 is the current default and adds Arabic script enforcement and romanization detection. An `ALL_PROMPT_CONSTANTS` dictionary maps all constant names to their values for regression tests.

#### Scenario: V4 is the current default
- **GIVEN** the nodes use prompt constants
- **WHEN** translate_node and audit_node build their prompts
- **THEN** they use TRANSLATOR_SYSTEM_V4, TRANSLATOR_USER_TEMPLATE_V4, AUDITOR_SYSTEM_V4, AUDITOR_USER_TEMPLATE_V4, and TRANSLATOR_REVISION_ADDENDUM_V4

#### Scenario: ALL_PROMPT_CONSTANTS contains every version
- **GIVEN** the ALL_PROMPT_CONSTANTS dictionary
- **WHEN** its keys are inspected
- **THEN** it contains all V1, V2, V3, and V4 constant names

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
