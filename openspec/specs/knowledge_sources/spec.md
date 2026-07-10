## Purpose

The knowledge layer: exact-match glossary, ChromaDB retrieval, Translation Memory, Iraqi legal-source web search, and corpus ingestion/chunking. This component provides all external knowledge that feeds the translation pipeline — terminology, legal context, prior translations, and live legal sources.

## Requirements

### Requirement: Glossary exact-match index

The glossary SHALL be a SQLite-backed exact-match index. `GlossaryIndex` is a stateful adapter with `build()`, `scan()`, and a `terms` property. `load_glossary_index(db_path: Path) -> GlossaryIndex` loads the index from SQLite. `scan_glossary_hits(text: str, index: GlossaryIndex, lang: Lang) -> list[GlossaryHit]` scans text for glossary term matches. Arabic normalization (`normalize_arabic`) strips diacritics and folds variant forms; English normalization (`normalize_english`) lowercases and collapses whitespace. `normalize(term, lang)` dispatches to the correct normalizer.

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

### Requirement: ChromaDB vector retrieval

`retrieve_context_chunks(query: str, n: int, *, embedder, persist_dir, cfg) -> list[ContextChunk]` SHALL query the ChromaDB vector store for the top-n most similar corpus chunks. `ChromaStore` is the stateful adapter with `build(chunks)`, `query(query_text, n_results, where)`, `count()`, and `close()`. The default collection is "iraqi_laws"; the default add batch size is 64. Only `PersistentClient` is used — never client/server mode.

#### Scenario: Retrieve top-5 context chunks
- **GIVEN** a populated ChromaDB store and a query string
- **WHEN** retrieve_context_chunks is called with n=5
- **THEN** up to 5 ContextChunk objects are returned, each with text, law, article, and score

#### Scenario: ChromaDB uses PersistentClient only
- **GIVEN** the ChromaStore is initialized
- **WHEN** it connects to ChromaDB
- **THEN** it uses chromadb.PersistentClient with a local directory, never a client/server connection

### Requirement: Translation Memory sentence-level lookup

`TranslationMemory` SHALL be a SQLite-backed TM with `build_from_corpus(corpus_dir)`, `lookup(query: str, source_lang: str) -> TmHit | None`, `add_parallel(pairs: list[tuple])`, and `list_all() -> list[TmEntry]`. Lookup uses SequenceMatcher verification with a max of 50 candidates. A `TmHit` contains source_sentence, target_sentence, similarity, char_start, char_end.

#### Scenario: Lookup finds a high-similarity match
- **GIVEN** a TM populated with the sentence pair ("المادة الأولى", "Article One") and a query "المادة الأولى"
- **WHEN** lookup is called with source_lang="ar"
- **THEN** a TmHit is returned with similarity ≥ 0.9 and target_sentence = "Article One"

#### Scenario: Lookup returns None for no match
- **GIVEN** a TM with no similar sentence to the query
- **WHEN** lookup is called
- **THEN** None is returned

#### Scenario: Build TM from corpus
- **GIVEN** a corpus directory with aligned Arabic and English text files
- **WHEN** build_from_corpus is called
- **THEN** the TM is populated with aligned sentence pairs

### Requirement: Iraqi legal-source web search

`search_all_sources(query: str, max_results_per_source: int = 5) -> list[SearchHit]` SHALL search Dijlex, Ministry of Justice, UR e-government portal, and National Library. Individual functions `search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library` each return `list[SearchHit]`. A `SearchHit` has title, url, snippet, source, and a `to_dict()` method.

#### Scenario: Search all sources aggregates results
- **GIVEN** a query about Iraqi civil code
- **WHEN** search_all_sources is called with max_results_per_source=5
- **THEN** results from all four sources are aggregated into a single list, each with the correct `source` field

#### Scenario: SearchHit serializes to dict
- **GIVEN** a SearchHit with title, url, snippet, source
- **WHEN** to_dict() is called
- **THEN** a dictionary with those four fields is returned

### Requirement: Corpus ingestion and chunking

`ingest_corpus(corpus_dir: Path, *, embedder, cfg) -> tuple[int, int]` SHALL parse corpus files, chunk articles, embed chunks via the embedder, and write to ChromaDB. `iter_articles(path: Path) -> Iterator[Article]` streams articles from a corpus file. `chunk_article(article, chunk_size, chunk_overlap) -> list[Chunk]` splits an article into chunks. `approx_token_count(text: str) -> int` provides a conservative token estimate. `parse_corpus_file(path: Path) -> list[Article]` parses a full file.

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
