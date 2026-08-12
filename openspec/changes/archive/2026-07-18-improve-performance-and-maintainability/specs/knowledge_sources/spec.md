## MODIFIED Requirements

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
