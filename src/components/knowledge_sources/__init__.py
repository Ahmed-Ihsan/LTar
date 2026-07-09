"""Knowledge sources component — glossary, retrieval, TM, legal search, ingestion.

Re-exports the public API so callers can use the short form::

    from src.components.knowledge_sources import GlossaryIndex, TranslationMemory

or the direct submodule form::

    from src.components.knowledge_sources.glossary import GlossaryIndex
"""
from src.components.knowledge_sources.glossary import (
    GlossaryHit,
    GlossaryIndex,
    build_sqlite_index,
    glossary_scan,
    load_glossary_file,
    load_glossary_files,
    load_glossary_index,
    normalize,
    normalize_arabic,
    normalize_english,
    scan_glossary_hits,
)
from src.components.knowledge_sources.ingestion import (
    CorpusSummary,
    FileHash,
    GlossarySummary,
    IngestionResult,
    approx_token_count,
    chunk_article,
    ingest,
    iter_articles,
    parse_corpus_file,
    run_ingestion,
)
from src.components.knowledge_sources.legal_search import (
    search_all_sources,
    search_dijlex,
    search_moj,
    search_national_library,
    search_ur_portal,
)
from src.components.knowledge_sources.models import (
    Article,
    Chunk,
    ContextChunk,
    Lang,
    SearchHit,
    Term,
    TmEntry,
)
from src.components.knowledge_sources.retrieval import (
    DEFAULT_ADD_BATCH,
    DEFAULT_COLLECTION,
    ChromaStore,
    add_chunks_to_collection,
    build_chroma_collection,
    query_chroma,
    retrieve_context_chunks,
)
from src.components.knowledge_sources.tm import TranslationMemory

__all__ = [
    # models
    "Article",
    "Chunk",
    "ContextChunk",
    "Lang",
    "SearchHit",
    "Term",
    "TmEntry",
    # glossary
    "GlossaryHit",
    "GlossaryIndex",
    "build_sqlite_index",
    "glossary_scan",
    "load_glossary_file",
    "load_glossary_files",
    "load_glossary_index",
    "normalize",
    "normalize_arabic",
    "normalize_english",
    "scan_glossary_hits",
    # retrieval
    "DEFAULT_ADD_BATCH",
    "DEFAULT_COLLECTION",
    "ChromaStore",
    "add_chunks_to_collection",
    "build_chroma_collection",
    "query_chroma",
    "retrieve_context_chunks",
    # tm
    "TranslationMemory",
    # legal_search
    "search_all_sources",
    "search_dijlex",
    "search_moj",
    "search_national_library",
    "search_ur_portal",
    # ingestion
    "CorpusSummary",
    "FileHash",
    "GlossarySummary",
    "IngestionResult",
    "approx_token_count",
    "chunk_article",
    "ingest",
    "iter_articles",
    "parse_corpus_file",
    "run_ingestion",
]
