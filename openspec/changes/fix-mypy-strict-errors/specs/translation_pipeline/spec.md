## MODIFIED Requirements

### Requirement: Node functions mutate state

Each node function MUST receive the current TranslationState and its injected dependencies as keyword-only args, and return an updated TranslationState partial dict. The seven node functions are: `preprocess_node`, `web_search_node`, `tm_lookup_node`, `tm_bypass_node`, `translate_node`, `audit_node`, `finalize_node`. The `scan_glossary_hits` call in `preprocess_node` SHALL pass a `Lang` literal (`"ar"` or `"en"`) not a bare `str`; if the direction-derived lang is typed as `str`, it SHALL be cast to `Lang` before the call. The `_parse_verdict` helper SHALL return `AuditVerdict` (a TypedDict) not `dict[str, object]`, so the `audit_node` return statement does not need a `# type: ignore[return-value]` comment. The `float()` call on audit confidence SHALL cast the `object`-typed value to `str | float` first, or use a targeted type narrowing. Stale `# type: ignore` comments SHALL be removed.

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

#### Scenario: nodes.py passes mypy strict
- **GIVEN** the refactored nodes.py with Lang cast, AuditVerdict return type, and float() narrowing
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for nodes.py (no arg-type, no typeddict-item, no unused-ignore)
