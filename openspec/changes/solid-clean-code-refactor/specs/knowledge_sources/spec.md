## ADDED Requirements

### Requirement: Ingestion module single responsibility

The `ingestion.py` module SHALL contain only parsing and chunking functions: `ingest_corpus`, `iter_articles`, `chunk_article`, `approx_token_count`, `parse_corpus_file`. Manifest writing logic (`_write_manifest`, `_compute_file_hash`, file categorization) SHALL reside in `manifest.py`. Orchestration and progress reporting (`run_ingestion`, `_iter_corpus_chunks`) SHALL reside in `ingestion_runner.py`. Each function SHALL be ≤ 40 lines (excluding docstrings).

#### Scenario: ingestion.py contains only parsing and chunking
- **GIVEN** the `knowledge_sources/ingestion.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `ingest_corpus`, `iter_articles`, `chunk_article`, `approx_token_count`, `parse_corpus_file` only; no manifest or orchestration functions

#### Scenario: Manifest logic is in a separate module
- **GIVEN** the `knowledge_sources/manifest.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `_write_manifest`, `_compute_file_hash`, and file categorization helpers

#### Scenario: Orchestration is in a separate module
- **GIVEN** the `knowledge_sources/ingestion_runner.py` file is inspected
- **WHEN** its top-level definitions are listed
- **THEN** it contains `run_ingestion` and `_iter_corpus_chunks`

#### Scenario: iter_articles is ≤ 40 lines
- **GIVEN** the `iter_articles` function
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 40 lines, achieved by extracting sub-functions for header parsing, body assembly, and metadata extraction

### Requirement: Normalizer registry for open/closed extension

`glossary.py` SHALL define a `Normalizer` protocol (PEP 544) with a `normalize(term: str) -> str` method. `normalize_arabic` and `normalize_english` SHALL be registered in a `_NORMALIZERS: dict[str, Normalizer]` registry. The `normalize(term, lang)` function SHALL dispatch via `_NORMALIZERS[lang]` instead of an if-else chain. Adding a new language normalizer SHALL require only registering a new entry in `_NORMALIZERS`, not modifying `normalize()`.

#### Scenario: Arabic normalization folds variants
- **GIVEN** the Arabic term "القانون" with diacritics or variant forms (e.g., "ٱلقانون")
- **WHEN** normalize_arabic is applied
- **THEN** the result is the canonical normalized form, folding variant alif, ya, and diacritic forms

#### Scenario: English normalization lowercases
- **GIVEN** the English term "Civil Code"
- **WHEN** normalize_english is applied
- **THEN** the result is "civil code" (lowercased, whitespace collapsed)

#### Scenario: New language is added without modifying normalize()
- **GIVEN** a new `normalize_french` function is registered in `_NORMALIZERS`
- **WHEN** `normalize("Code Civil", "fr")` is called
- **THEN** the French normalizer is dispatched without any changes to the `normalize()` function body

### Requirement: Search source registry for open/closed extension

`legal_search.py` SHALL define a `SearchSource` dataclass with `name: str` and `search: Callable[[str, int], list[SearchHit]]` fields. Each search function (`search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library`) SHALL be wrapped in a `SearchSource` instance and registered in a `_SOURCES: list[SearchSource]` list. `search_all_sources` SHALL iterate over `_SOURCES` instead of hardcoding the function list. Adding a new source SHALL require only registering a new `SearchSource`, not modifying `search_all_sources`.

#### Scenario: Search all sources aggregates results
- **GIVEN** a query about Iraqi civil code
- **WHEN** search_all_sources is called with max_results_per_source=5
- **THEN** results from all registered sources are aggregated into a single list, each with the correct `source` field

#### Scenario: New source is added without modifying search_all_sources
- **GIVEN** a new `SearchSource(name="new_source", search=new_search_fn)` is appended to `_SOURCES`
- **WHEN** `search_all_sources` is called
- **THEN** the new source's results are included without any changes to the `search_all_sources` function body

### Requirement: ChromaStore dependency injection

`ChromaStore.__init__` SHALL accept `embedder: EmbeddingAdapter` and `cfg: AppConfig` as keyword-only arguments. It SHALL NOT call `load_config()` or instantiate `Embedder()` internally. Module-level convenience functions (`build_chroma_collection`, `query_chroma`, etc.) SHALL use a shared `_create_store(persist_dir, embedder, cfg)` factory function instead of duplicating `ChromaStore(persist_dir=...)` instantiation.

#### Scenario: ChromaStore receives embedder via injection
- **GIVEN** a ChromaStore is constructed
- **WHEN** its constructor is called
- **THEN** it receives an `EmbeddingAdapter` instance and an `AppConfig` as keyword-only args, and does NOT call `load_config()` or `Embedder()` internally

#### Scenario: Module-level functions use shared factory
- **GIVEN** the `build_chroma_collection` function is inspected
- **WHEN** its body is read
- **THEN** it calls `_create_store()` instead of directly instantiating `ChromaStore`

### Requirement: Term factory methods for DRY

`glossary.py` SHALL provide `Term.from_row(row: sqlite3.Row) -> Term` and `Term.from_dict(data: dict) -> Term` classmethods to eliminate duplicated Term construction logic. All places that construct a `Term` from a database row or dictionary SHALL use these factory methods.

#### Scenario: Term is constructed from a database row
- **GIVEN** a sqlite3.Row with glossary term columns
- **WHEN** `Term.from_row(row)` is called
- **THEN** a Term is returned with all fields populated from the row

#### Scenario: Term is constructed from a dictionary
- **GIVEN** a dictionary with glossary term fields
- **WHEN** `Term.from_dict(data)` is called
- **THEN** a Term is returned with all fields populated from the dict

## MODIFIED Requirements

### Requirement: Translation Memory lookup decomposition

`TranslationMemory.lookup` SHALL be decomposed into focused helper methods, each ≤ 30 lines: `_extract_trigrams(text) -> set[str]`, `_trigram_candidates(trigrams) -> list[str]`, `_full_scan_candidates() -> list[str]`, `_verify_candidates(query, candidates) -> TmHit | None`. The public `lookup` method SHALL orchestrate these helpers. The behavior (SequenceMatcher verification, max 50 candidates, similarity threshold) SHALL remain identical.

#### Scenario: Lookup finds a high-similarity match
- **GIVEN** a TM populated with the sentence pair ("المادة الأولى", "Article One") and a query "المادة الأولى"
- **WHEN** lookup is called with source_lang="ar"
- **THEN** a TmHit is returned with similarity ≥ 0.9 and target_sentence = "Article One"

#### Scenario: Lookup returns None for no match
- **GIVEN** a TM with no similar sentence to the query
- **WHEN** lookup is called
- **THEN** None is returned

#### Scenario: Lookup method is ≤ 30 lines
- **GIVEN** the `lookup` method
- **WHEN** its body length is measured (excluding docstring)
- **THEN** it is ≤ 30 lines, delegating to `_extract_trigrams`, `_trigram_candidates`, `_full_scan_candidates`, and `_verify_candidates`

### Requirement: Corpus ingestion and chunking

`ingest_corpus(corpus_dir: Path, *, embedder, cfg) -> tuple[int, int]` SHALL parse corpus files, chunk articles, embed chunks via the embedder, and write to ChromaDB. `iter_articles(path: Path) -> Iterator[Article]` streams articles from a corpus file. `chunk_article(article, chunk_size, chunk_overlap) -> list[Chunk]` splits an article into chunks. `approx_token_count(text: str) -> int` provides a conservative token estimate. `parse_corpus_file(path: Path) -> list[Article]` parses a full file. Each function SHALL be ≤ 40 lines (excluding docstrings).

#### Scenario: Ingest corpus returns chunk and article counts
- **GIVEN** a corpus directory with valid text files and a configured embedder
- **WHEN** ingest_corpus is called
- **THEN** a tuple (article_count, chunk_count) is returned

#### Scenario: Chunk article respects chunk_size and overlap
- **GIVEN** an Article with 2000 characters of text, chunk_size=500, chunk_overlap=50
- **WHEN** chunk_article is called
- **THEN** the chunks cover the full text with the specified overlap between consecutive chunks

#### Scenario: Token count is conservative
- **GIVEN** a text string
- **WHEN** approx_token_count is called
- **THEN** the returned estimate is conservative (overestimate) suitable for the 8192-token context window cap
