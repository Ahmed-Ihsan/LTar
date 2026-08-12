## Purpose

The knowledge layer: exact-match glossary, ChromaDB retrieval, Translation Memory, Iraqi legal-source web search, and corpus ingestion/chunking. This component provides all external knowledge that feeds the translation pipeline — terminology, legal context, prior translations, and live legal sources.
## Requirements
### Requirement: Glossary exact-match index

The glossary SHALL be a SQLite-backed exact-match index. `GlossaryIndex` is a stateful adapter with `build()`, `scan()`, and a `terms` property. `load_glossary_index(db_path: Path) -> GlossaryIndex` loads the index from SQLite. `scan_glossary_hits(text: str, index: GlossaryIndex, lang: Lang) -> list[GlossaryHit]` scans text for glossary term matches. Arabic normalization (`normalize_arabic`) strips diacritics and folds variant forms; English normalization (`normalize_english`) lowercases and collapses whitespace. `normalize(term, lang)` dispatches to the correct normalizer. The matcher SHALL be built via `pyahocorasick.Automaton` (Aho-Corasick) at index load for O(n) scanning regardless of glossary size; if `pyahocorasick` is not installed, the matcher SHALL fall back to the existing regex alternation (graceful degradation). The `glossary_scan` alias SHALL NOT exist (it is removed); callers SHALL use `scan_glossary_hits`. `load_glossary_files` SHALL use `dataclasses.replace(term, file_order=global_order)` instead of reconstructing the full `Term` with 12 fields.

#### Scenario: Load glossary from SQLite
- **GIVEN** a populated SQLite glossary database at db/glossary.sqlite
- **WHEN** load_glossary_index is called with the db path
- **THEN** a GlossaryIndex is returned with terms accessible via the `terms` property

#### Scenario: Scan Arabic text for glossary matches
- **GIVEN** Arabic text "المادة الأولى من القانون المدني" and a glossary index containing "القانون المدني"
- **WHEN** scan_glossary_hits is called with lang="ar"
- **THEN** the returned list includes a GlossaryHit with source_term matching the normalized form of "القانون المدني"

#### Scenario: Arabic normalization folds variants
- **GIVEN** the Arabic term "القانون" with diacritics or variant forms (e.g., "ٱلقانون")
- **WHEN** normalize_arabic is applied
- **THEN** the result is the canonical normalized form, folding variant alif, ya, and diacritic forms

#### Scenario: English normalization lowercases
- **GIVEN** the English term "Civil Code"
- **WHEN** normalize_english is applied
- **THEN** the result is "civil code" (lowercased, whitespace collapsed)

#### Scenario: Aho-Corasick matcher produces the same hits as the regex matcher
- **GIVEN** a glossary index built with `pyahocorasick` available and a text to scan
- **WHEN** `scan_glossary_hits` runs with the Aho-Corasick matcher
- **THEN** the returned hits are identical to those produced by the regex fallback matcher for the same input

#### Scenario: glossary falls back to regex without pyahocorasick
- **GIVEN** a Python environment where `import ahocorasick` raises `ImportError`
- **WHEN** `load_glossary_index` builds the matcher
- **THEN** it falls back to the regex alternation matcher and `scan_glossary_hits` still returns correct hits (graceful degradation)

#### Scenario: glossary_scan alias does not exist
- **GIVEN** the `glossary.py` module
- **WHEN** its attributes are inspected
- **THEN** there is no `glossary_scan` function (the alias is removed; callers use `scan_glossary_hits`)

### Requirement: ChromaDB vector retrieval

`retrieve_context_chunks(query: str, n: int, *, embedder, persist_dir, cfg) -> list[ContextChunk]` SHALL query the ChromaDB vector store for the top-n most similar corpus chunks. `ChromaStore` is the stateful adapter with `build(chunks)`, `query(query_text, n_results, where)`, `count()`, and `close()`. The default collection is "iraqi_laws"; the default add batch size is 64. Only `PersistentClient` is used — never client/server mode. `ChromaStore._write_collection` and `add_chunks` SHALL stream chunks in batches of `embedding_batch_size` (default 32), embedding and inserting each batch before materializing the next, so that a large import does not hold the full chunk-text list in memory (8 GB RAM budget). `_close_handles` SHALL call `gc.collect()` at most once (the second redundant call is removed).

#### Scenario: Retrieve top-5 context chunks
- **GIVEN** a populated ChromaDB store and a query string
- **WHEN** retrieve_context_chunks is called with n=5
- **THEN** up to 5 ContextChunk objects are returned, each with text, law, article, and score

#### Scenario: ChromaDB uses PersistentClient only
- **GIVEN** the ChromaStore is initialized
- **WHEN** it connects to ChromaDB
- **THEN** it uses chromadb.PersistentClient with a local directory, never a client/server connection

#### Scenario: large corpus ingestion streams in batches
- **GIVEN** a corpus with 10 000 chunks and `embedding_batch_size=32`
- **WHEN** `ChromaStore.add_chunks` runs
- **THEN** chunks are embedded and inserted in batches of ≤ 32; the full `list[str]` of 10 000 texts is never materialized in memory at once (peak text-list length ≤ 32)

### Requirement: Translation Memory sentence-level lookup

`TranslationMemory` SHALL be a SQLite-backed TM with `build_from_corpus(corpus_dir)`, `lookup(query: str, source_lang: str) -> TmHit | None`, `add_parallel(pairs: list[tuple])`, and `list_all() -> list[TmEntry]`. Lookup uses SequenceMatcher verification with a max of 50 candidates. A `TmHit` contains source_sentence, target_sentence, similarity, char_start, char_end. `build_from_corpus` and `_build_trigram_index` SHALL stream rows and insert trigrams in batches via `executemany` (batch size 1000), so a large TM does not hold the full row list or `trigram_rows` list in memory. `add_parallel` SHALL use `cursor.lastrowid` to retrieve just-inserted rows instead of `ORDER BY id DESC LIMIT ?`.

#### Scenario: Lookup finds a high-similarity match
- **GIVEN** a TM populated with the sentence pair ("المادة الأولى", "Article One") and a query "المادة الأولى"
- **WHEN** lookup is called with source_lang="ar"
- **THEN** a TmHit is returned with similarity ≥ 0.9 and target_sentence = "Article One"

#### Scenario: Lookup returns None for no match
- **GIVEN** a TM with no similar sentence to the query
- **WHEN** lookup is called
- **THEN** None is returned

#### Scenario: Build TM from corpus streams trigrams
- **GIVEN** a corpus with 100 000 aligned sentence pairs
- **WHEN** `build_from_corpus` runs
- **THEN** trigrams are inserted in batches of 1000 via `executemany`; the full `trigram_rows` list is never materialized (peak list length ≤ 1000)

#### Scenario: add_parallel uses lastrowid
- **GIVEN** the `tm.py:add_parallel` source
- **WHEN** it is inspected
- **THEN** it uses `cursor.lastrowid` to retrieve just-inserted rows, not `ORDER BY id DESC LIMIT ?`

### Requirement: Iraqi legal-source web search

`search_all_sources(query: str, max_results_per_source: int = 5) -> list[SearchHit]` SHALL search Dijlex, Ministry of Justice, UR e-government portal, and National Library. Individual functions `search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library` each return `list[SearchHit]`. A `SearchHit` has title, url, snippet, source, and a `to_dict()` method. URL deduplication SHALL use a `dict[url, SearchHit]` (O(1) lookup) instead of the O(n²) `if url in seen_urls: for h in hits: ...` pattern. Each search function SHALL cache results in an in-memory TTL cache (5-minute `time.monotonic()`-based expiry) so repeated queries within 5 minutes do not re-fetch from the web.

#### Scenario: Search all sources aggregates results
- **GIVEN** a query about Iraqi civil code
- **WHEN** search_all_sources is called with max_results_per_source=5
- **THEN** results from all four sources are aggregated into a single list, each with the correct `source` field

#### Scenario: SearchHit serializes to dict
- **GIVEN** a SearchHit with title, url, snippet, source
- **WHEN** to_dict() is called
- **THEN** a dictionary with those four fields is returned

#### Scenario: repeated queries within 5 minutes use the cache
- **GIVEN** `search_moj("القانون المدني")` has been called once and returned results
- **WHEN** `search_moj("القانون المدني")` is called again 2 minutes later
- **THEN** the cached results are returned without an HTTP request to `moj.gov.iq`

#### Scenario: queries after 5 minutes re-fetch
- **GIVEN** `search_moj("القانون المدني")` has been called once and 6 minutes have elapsed
- **WHEN** `search_moj("القانون المدني")` is called again
- **THEN** a fresh HTTP request is made to `moj.gov.iq` (the cache entry has expired)

#### Scenario: URL dedup is O(1)
- **GIVEN** the `legal_search.py` dedup logic
- **WHEN** it is inspected
- **THEN** it uses a `dict[url, SearchHit]` for dedup, not a nested `for h in hits: if h.url == url:` loop

### Requirement: Corpus ingestion and chunking

`ingest_corpus(corpus_dir: Path, *, embedder, cfg) -> tuple[int, int]` SHALL parse corpus files, chunk articles, embed chunks via the embedder, and write to ChromaDB. `iter_articles(path: Path) -> Iterator[Article]` streams articles from a corpus file. `chunk_article(article, chunk_size, chunk_overlap) -> list[Chunk]` splits an article into chunks. `approx_token_count(text: str) -> int` provides a conservative token estimate. `parse_corpus_file(path: Path) -> list[Article]` parses a full file. `approx_token_count` SHALL be cached per span (keyed by span offsets) so that the paragraph → sentence → packing/overlap phases do not re-tokenize the same span multiple times. The `ingestion_runner` SHALL NOT accept an unused `rebuild` parameter (dead parameter removed; `run_ingestion` always rebuilds atomically).

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

#### Scenario: approx_token_count is cached per span
- **GIVEN** a span at offsets (100, 500) that is tokenized in the paragraph phase
- **WHEN** the same span is tokenized again in the sentence and packing phases
- **THEN** `approx_token_count` is called once for that span (subsequent calls return the cached value)

#### Scenario: ingestion_runner has no dead rebuild parameter
- **GIVEN** the `ingestion_runner.py` source
- **WHEN** its `run_ingestion` signature is inspected
- **THEN** it does NOT accept a `rebuild` parameter (the dead parameter is removed)

### Requirement: Ingestion batch size cap

Ingestion SHALL stream documents in batches of ≤ 64 chunks. Embedding batch size is capped at 32. The full corpus is never held in memory.

#### Scenario: Ingestion respects batch cap
- **GIVEN** a corpus with more than 64 chunks
- **WHEN** ingest_corpus processes chunks
- **THEN** chunks are added to ChromaDB in batches of ≤ 64

#### Scenario: Embedding batch size cap
- **GIVEN** more than 32 texts to embed
- **WHEN** embed_batch is called with DEFAULT_BATCH_SIZE=32
- **THEN** texts are embedded in batches of ≤ 32

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

