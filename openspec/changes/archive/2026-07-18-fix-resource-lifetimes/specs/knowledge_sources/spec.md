## MODIFIED Requirements

### Requirement: ChromaDB vector retrieval

`retrieve_context_chunks(query: str, n: int, *, embedder, persist_dir, cfg) -> list[ContextChunk]` SHALL query the ChromaDB vector store for the top-n most similar corpus chunks. `ChromaStore` is the stateful adapter with `build(chunks)`, `query(query_text, n_results, where)`, `count()`, and `close()`. The default collection is "iraqi_laws"; the default add batch size is 64. Only `PersistentClient` is used — never client/server mode. `ChromaStore` SHALL implement the context-manager protocol (`__enter__` returning `self`, `__exit__` calling `_close_handles()`). The `_write_collection` and `add_chunks` methods SHALL wrap their bodies in `try/finally` so that `_close_handles()` is called on exception, ensuring a failed embedding run does not leak the ChromaDB client. `_close_handles` SHALL call `gc.collect()` at most once (the second redundant call is removed).

#### Scenario: Retrieve top-5 context chunks
- **GIVEN** a populated ChromaDB store and a query string
- **WHEN** retrieve_context_chunks is called with n=5
- **THEN** up to 5 ContextChunk objects are returned, each with text, law, article, and score

#### Scenario: ChromaDB uses PersistentClient only
- **GIVEN** the ChromaStore is initialized
- **WHEN** it connects to ChromaDB
- **THEN** it uses chromadb.PersistentClient with a local directory, never a client/server connection

#### Scenario: ChromaStore as context manager closes handles
- **GIVEN** a ChromaStore used in a `with` statement
- **WHEN** the context exits
- **THEN** `_close_handles()` is called and the ChromaDB client and collection are released

#### Scenario: ChromaStore closes handles on exception
- **GIVEN** a ChromaStore whose `add_chunks` raises mid-run (e.g., embedding failure)
- **WHEN** the exception propagates
- **THEN** `_close_handles()` was called via `try/finally` before the exception reached the caller, and no ChromaDB client is leaked

### Requirement: Translation Memory sentence-level lookup

`TranslationMemory` SHALL be a SQLite-backed TM with `build_from_corpus(corpus_dir)`, `lookup(query: str, source_lang: str) -> TmHit | None`, `add_parallel(pairs: list[tuple])`, and `list_all() -> list[TmEntry]`. Lookup uses SequenceMatcher verification with a max of 50 candidates. A `TmHit` contains source_sentence, target_sentence, similarity, char_start, char_end. `TranslationMemory` SHALL implement the context-manager protocol (`__enter__` returning `self`, `__exit__` calling `close()`) and an idempotent `close()` method that closes the SQLite connection. Every `self._conn.execute(...)` and `self._conn.commit()` call SHALL be guarded by a `threading.RLock` (`self._lock`) so the TM is safe to call from the LangGraph thread and the UI thread serially. The SQLite connection SHALL be opened with `check_same_thread=True` (the default); the `check_same_thread=False` flag SHALL NOT be used. A `weakref.finalize(self, self._conn.close)` safety net SHALL be registered in `__init__` so a forgotten `close()` still releases the connection on GC.

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

#### Scenario: TranslationMemory as context manager closes the connection
- **GIVEN** a TranslationMemory used in a `with` statement
- **WHEN** the context exits
- **THEN** the SQLite connection is closed via `close()` and `self._conn` is set to `None`

#### Scenario: close is idempotent
- **GIVEN** a TranslationMemory whose `close()` has already been called
- **WHEN** `close()` is called again
- **THEN** no exception is raised and no double-close occurs

#### Scenario: TM is thread-safe under concurrent writes
- **GIVEN** a TranslationMemory and two threads each inserting 50 rows concurrently
- **WHEN** both threads complete
- **THEN** no `sqlite3.ProgrammingError` is raised and all 100 rows are present in the database (the `RLock` serializes access)

#### Scenario: TM does not disable SQLite thread check
- **GIVEN** the `TranslationMemory.__init__` source
- **WHEN** the `sqlite3.connect` call is inspected
- **THEN** `check_same_thread=False` is NOT passed; the default `check_same_thread=True` is used and the `RLock` provides serialization

#### Scenario: TM connection is released on GC if close was forgotten
- **GIVEN** a TranslationMemory whose `close()` was never called and which has gone out of scope
- **WHEN** the garbage collector runs
- **THEN** the `weakref.finalize` callback closes the SQLite connection (no file-descriptor leak)
