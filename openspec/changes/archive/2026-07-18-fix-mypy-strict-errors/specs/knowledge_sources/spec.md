## MODIFIED Requirements

### Requirement: Glossary exact-match index

The glossary SHALL be a SQLite-backed exact-match index. `GlossaryIndex` is a stateful adapter with `build()`, `scan()`, and a `terms` property. `load_glossary_index(db_path: Path) -> GlossaryIndex` loads the index from SQLite. `scan_glossary_hits(text: str, index: GlossaryIndex, lang: Lang) -> list[GlossaryHit]` scans text for glossary term matches. Arabic normalization (`normalize_arabic`) strips diacritics and folds variant forms; English normalization (`normalize_english`) lowercases and collapses whitespace. `normalize(term, lang)` dispatches to the correct normalizer. The module SHALL declare `__all__` listing all public symbols including `GlossaryConflictError` and `GlossaryValidationError` so that mypy's `--no-implicit-reexport` does not flag imports of these exception classes from other modules. Stale `# type: ignore` comments SHALL be removed. Where `object`-typed values from JSON parsing are passed to `Term` or `int()`, the code SHALL cast or narrow to the correct type (`str`, `Literal['ar', 'en']`) before the call, or use a targeted `# type: ignore[arg-type]` with a comment explaining the runtime guarantee.

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

#### Scenario: GlossaryConflictError is explicitly re-exported
- **GIVEN** the refactored glossary.py with __all__ declared
- **WHEN** ingestion.py imports GlossaryConflictError from src.components.knowledge_sources.glossary
- **THEN** mypy does not report an attr-defined error because GlossaryConflictError is in __all__

#### Scenario: glossary.py passes mypy strict
- **GIVEN** the refactored glossary.py with type casts and __all__
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for glossary.py (no unused-ignore, no arg-type, no call-overload)

### Requirement: ChromaDB vector retrieval

`retrieve_context_chunks(query: str, n: int, *, embedder, persist_dir, cfg) -> list[ContextChunk]` SHALL query the ChromaDB vector store for the top-n most similar corpus chunks. `ChromaStore` is the stateful adapter with `build(chunks)`, `query(query_text, n_results, where)`, `count()`, and `close()`. The default collection is "iraqi_laws"; the default add batch size is 64. Only `PersistentClient` is used — never client/server mode. The `SharedSystemClient` import from `chromadb.api.client` SHALL use a `# type: ignore[attr-defined]` comment because the symbol is not in the library's `__all__` but exists at runtime. Embedding lists passed to `Collection.add` and `Collection.query` SHALL be cast to the type expected by ChromaDB's type stubs, or use targeted `# type: ignore[arg-type]` comments, because the runtime accepts `list[list[float]]` but the stubs require `ndarray | Sequence` types. The `include` list passed to `Collection.query` SHALL be cast to `list[IncludeEnum]` or use a `# type: ignore[list-item]` comment. The `_parse_query_result` helper SHALL accept the ChromaDB `QueryResult` type or use a `# type: ignore[arg-type]` comment where the stubs return `QueryResult` but the function expects `dict[str, Any]`.

#### Scenario: Retrieve top-5 context chunks
- **GIVEN** a populated ChromaDB store and a query string
- **WHEN** retrieve_context_chunks is called with n=5
- **THEN** up to 5 ContextChunk objects are returned, each with text, law, article, and score

#### Scenario: ChromaDB uses PersistentClient only
- **GIVEN** the ChromaStore is initialized
- **WHEN** it connects to ChromaDB
- **THEN** it uses chromadb.PersistentClient with a local directory, never a client/server connection

#### Scenario: retrieval.py passes mypy strict
- **GIVEN** the refactored retrieval.py with type casts and type-ignore comments
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for retrieval.py (all ChromaDB stub mismatches are handled)

### Requirement: Corpus ingestion and chunking

`ingest_corpus(corpus_dir: Path, *, embedder, cfg) -> tuple[int, int]` SHALL parse corpus files, chunk articles, embed chunks via the embedder, and write to ChromaDB. `iter_articles(path: Path) -> Iterator[Article]` streams articles from a corpus file. `chunk_article(article, chunk_size, chunk_overlap) -> list[Chunk]` splits an article into chunks. `approx_token_count(text: str) -> int` provides a conservative token estimate. `parse_corpus_file(path: Path) -> list[Article]` parses a full file. All function parameters SHALL have complete type annotations (no untyped parameters). All `list` return types and local variables SHALL have type parameters (e.g., `list[Chunk]` not bare `list`). The module SHALL import `GlossaryConflictError` and `GlossaryValidationError` without mypy `attr-defined` errors (these are re-exported via `__all__` in glossary.py).

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

#### Scenario: ingestion.py passes mypy strict
- **GIVEN** the refactored ingestion.py with all parameters annotated and list type parameters added
- **WHEN** `mypy src/` is run in strict mode
- **THEN** zero errors are reported for ingestion.py (no no-untyped-def, no type-arg, no attr-defined)
