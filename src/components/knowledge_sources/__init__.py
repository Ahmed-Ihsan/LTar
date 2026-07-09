"""Knowledge sources component — glossary, retrieval, TM, legal search, ingestion.

Re-exports the public API so callers can use the short form::

    from src.components.knowledge_sources import GlossaryIndex, TranslationMemory

or the direct submodule form::

    from src.components.knowledge_sources.glossary import GlossaryIndex

Imports are lazy (PEP 562 ``__getattr__``) to avoid circular imports between
component ``__init__`` files.
"""
import importlib
from typing import Any

_LAZY: dict[str, str] = {
    # models
    "Article": f"{__name__}.models",
    "Chunk": f"{__name__}.models",
    "ContextChunk": f"{__name__}.models",
    "Lang": f"{__name__}.models",
    "SearchHit": f"{__name__}.models",
    "Term": f"{__name__}.models",
    "TmEntry": f"{__name__}.models",
    # glossary
    "GlossaryHit": f"{__name__}.glossary",
    "GlossaryIndex": f"{__name__}.glossary",
    "build_sqlite_index": f"{__name__}.glossary",
    "glossary_scan": f"{__name__}.glossary",
    "load_glossary_file": f"{__name__}.glossary",
    "load_glossary_files": f"{__name__}.glossary",
    "load_glossary_index": f"{__name__}.glossary",
    "normalize": f"{__name__}.glossary",
    "normalize_arabic": f"{__name__}.glossary",
    "normalize_english": f"{__name__}.glossary",
    "scan_glossary_hits": f"{__name__}.glossary",
    # retrieval
    "DEFAULT_ADD_BATCH": f"{__name__}.retrieval",
    "DEFAULT_COLLECTION": f"{__name__}.retrieval",
    "ChromaStore": f"{__name__}.retrieval",
    "add_chunks_to_collection": f"{__name__}.retrieval",
    "build_chroma_collection": f"{__name__}.retrieval",
    "query_chroma": f"{__name__}.retrieval",
    "retrieve_context_chunks": f"{__name__}.retrieval",
    # tm
    "TranslationMemory": f"{__name__}.tm",
    # legal_search
    "search_all_sources": f"{__name__}.legal_search",
    "search_dijlex": f"{__name__}.legal_search",
    "search_moj": f"{__name__}.legal_search",
    "search_national_library": f"{__name__}.legal_search",
    "search_ur_portal": f"{__name__}.legal_search",
    # ingestion
    "CorpusSummary": f"{__name__}.ingestion",
    "FileHash": f"{__name__}.ingestion",
    "GlossarySummary": f"{__name__}.ingestion",
    "IngestionResult": f"{__name__}.ingestion",
    "approx_token_count": f"{__name__}.ingestion",
    "chunk_article": f"{__name__}.ingestion",
    "ingest": f"{__name__}.ingestion",
    "iter_articles": f"{__name__}.ingestion",
    "parse_corpus_file": f"{__name__}.ingestion",
    "run_ingestion": f"{__name__}.ingestion",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name])
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY)
