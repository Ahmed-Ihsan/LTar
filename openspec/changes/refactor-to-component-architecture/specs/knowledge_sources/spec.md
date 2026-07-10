## ADDED Requirements

### Requirement: Knowledge sources component folder

The knowledge sources SHALL reside in `src/components/knowledge_sources/` as a bounded-context component. The folder SHALL contain: `__init__.py` (re-exports), `models.py`, `glossary.py`, `retrieval.py`, `tm.py`, `legal_search.py`, and `ingestion.py`.

#### Scenario: Component folder structure
- **GIVEN** the refactored project structure
- **WHEN** the `src/components/knowledge_sources/` directory is inspected
- **THEN** it contains `__init__.py`, `models.py`, `glossary.py`, `retrieval.py`, `tm.py`, `legal_search.py`, and `ingestion.py`

### Requirement: Knowledge sources domain models module

Domain models specific to the knowledge layer SHALL reside in `src/components/knowledge_sources/models.py`. This includes data classes for glossary entries, corpus chunks, and TM pairs that are internal to this component (e.g., `Term`, `GlossaryHit`, `Article`, `Chunk`, `TmEntry`, `SearchHit`, `ContextChunk`).

#### Scenario: Import domain models from component models
- **GIVEN** the refactored structure
- **WHEN** `from src.components.knowledge_sources.models import Term, Article, Chunk, TmEntry, SearchHit` is executed
- **THEN** all domain model classes are imported successfully

### Requirement: Knowledge sources glossary module

`GlossaryIndex`, `load_glossary_index`, `scan_glossary_hits`, `normalize_arabic`, `normalize_english`, and `normalize` SHALL reside in `src/components/knowledge_sources/glossary.py`.

#### Scenario: Import glossary API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.knowledge_sources.glossary import GlossaryIndex, load_glossary_index, scan_glossary_hits` is executed
- **THEN** all symbols are imported successfully

### Requirement: Knowledge sources retrieval module

`retrieve_context_chunks`, `ChromaStore`, `DEFAULT_COLLECTION`, and `DEFAULT_ADD_BATCH` SHALL reside in `src/components/knowledge_sources/retrieval.py`.

#### Scenario: Import retrieval API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.knowledge_sources.retrieval import retrieve_context_chunks, ChromaStore` is executed
- **THEN** all symbols are imported successfully

### Requirement: Knowledge sources TM module

`TranslationMemory` and `TmEntry` SHALL reside in `src/components/knowledge_sources/tm.py`.

#### Scenario: Import TM API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.knowledge_sources.tm import TranslationMemory` is executed
- **THEN** TranslationMemory is imported successfully

### Requirement: Knowledge sources legal search module

`search_all_sources`, `search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library`, and `SearchHit` SHALL reside in `src/components/knowledge_sources/legal_search.py`.

#### Scenario: Import legal search API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.knowledge_sources.legal_search import search_all_sources, SearchHit` is executed
- **THEN** all symbols are imported successfully

### Requirement: Knowledge sources ingestion module

`ingest_corpus`, `iter_articles`, `chunk_article`, `parse_corpus_file`, `approx_token_count`, `Article`, and `Chunk` SHALL reside in `src/components/knowledge_sources/ingestion.py`.

#### Scenario: Import ingestion API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.knowledge_sources.ingestion import ingest_corpus, iter_articles, chunk_article` is executed
- **THEN** all symbols are imported successfully

### Requirement: Knowledge sources public API re-export

`src/components/knowledge_sources/__init__.py` SHALL re-export the component's public API so that `from src.components.knowledge_sources import GlossaryIndex, TranslationMemory, retrieve_context_chunks` works without specifying the submodule.

#### Scenario: Re-exported public API
- **GIVEN** the refactored structure
- **WHEN** `from src.components.knowledge_sources import GlossaryIndex, TranslationMemory, retrieve_context_chunks` is executed
- **THEN** all symbols are imported successfully via the package __init__

### Requirement: Knowledge sources intra-component imports

Modules within `knowledge_sources/` SHALL import from sibling modules within the same component using component paths (e.g., `from src.components.knowledge_sources.models import Chunk`), not from the old flat `src.ingestion` paths.

#### Scenario: retrieval.py imports from component models
- **GIVEN** the refactored retrieval.py
- **WHEN** its imports are inspected
- **THEN** it imports Chunk from `src.components.knowledge_sources.models` or `src.components.knowledge_sources.ingestion`, not from `src.ingestion`

#### Scenario: ingestion.py imports from component glossary
- **GIVEN** the refactored ingestion.py
- **WHEN** its imports are inspected
- **THEN** it imports normalize_arabic from `src.components.knowledge_sources.glossary`, not from `src.glossary`
