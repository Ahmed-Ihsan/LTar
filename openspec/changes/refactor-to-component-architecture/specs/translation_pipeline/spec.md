## ADDED Requirements

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
