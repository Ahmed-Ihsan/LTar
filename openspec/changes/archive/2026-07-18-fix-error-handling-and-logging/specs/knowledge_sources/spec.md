## MODIFIED Requirements

### Requirement: Iraqi legal-source web search

`search_all_sources(query: str, max_results_per_source: int = 5) -> list[SearchHit]` SHALL search Dijlex, Ministry of Justice, UR e-government portal, and National Library. Individual functions `search_dijlex`, `search_moj`, `search_ur_portal`, `search_national_library` each return `list[SearchHit]`. A `SearchHit` has title, url, snippet, source, and a `to_dict()` method. The internal `_fetch_html(url)` / `_post_html(url, data)` seams SHALL catch only `(httpx.HTTPError, ValueError)` — NOT bare `Exception` — and on any caught exception SHALL log a warning via `logging.getLogger(__name__).warning(...)` naming the URL and the error, then return `""` so the caller skips that source. `KeyboardInterrupt`, `SystemExit`, and `MemoryError` SHALL propagate.

#### Scenario: Search all sources aggregates results
- **GIVEN** a query about Iraqi civil code
- **WHEN** search_all_sources is called with max_results_per_source=5
- **THEN** results from all four sources are aggregated into a single list, each with the correct `source` field

#### Scenario: SearchHit serializes to dict
- **GIVEN** a SearchHit with title, url, snippet, source
- **WHEN** to_dict() is called
- **THEN** a dictionary with those four fields is returned

#### Scenario: a network failure logs a warning and returns empty
- **GIVEN** `_fetch_html` issues a request that raises `httpx.ConnectError`
- **WHEN** the exception is caught
- **THEN** a warning is logged via `logger.warning(...)` naming the URL and the error, `""` is returned, and the calling search function skips that source (no exception propagates)

#### Scenario: a parse failure logs a warning and returns empty
- **GIVEN** `_fetch_html` receives a response whose body raises `ValueError` during parsing
- **WHEN** the exception is caught
- **THEN** a warning is logged and `""` is returned

### Requirement: Corpus ingestion and chunking

`ingest_corpus(corpus_dir: Path, *, embedder, cfg) -> tuple[int, int]` SHALL parse corpus files, chunk articles, embed chunks via the embedder, and write to ChromaDB. `iter_articles(path: Path) -> Iterator[Article]` streams articles from a corpus file. `chunk_article(article, chunk_size, chunk_overlap) -> list[Chunk]` splits an article into chunks. `approx_token_count(text: str) -> int` provides a conservative token estimate. `parse_corpus_file(path: Path) -> list[Article]` parses a full file. The ingestion runner SHALL catch `GlossaryConflictError`, `CorpusParseError`, and `CorpusEncodingError` per file and continue the run, but SHALL log a warning via `logging.getLogger(__name__).warning(...)` naming the failing file path and the error before continuing — silent swallowing without a log line is forbidden.

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

#### Scenario: a glossary conflict is logged with the file path
- **GIVEN** a glossary file `data/glossary/conflict.json` that raises `GlossaryConflictError` during load
- **WHEN** the ingestion runner processes it
- **THEN** a warning is logged naming `data/glossary/conflict.json` and the conflict detail, the run continues, and the conflict is counted in the returned report

#### Scenario: a corpus parse error is logged with the file path
- **GIVEN** a corpus file `data/corpus/bad.txt` that raises `CorpusParseError` during parsing
- **WHEN** the ingestion runner processes it
- **THEN** a warning is logged naming `data/corpus/bad.txt` and the parse error, the run continues, and the file is counted as skipped
