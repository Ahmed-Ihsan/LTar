"""Adapter wrappers bridging knowledge_sources concretions to pipeline protocols.

These adapters are the composition-root glue (DIP, engineering-principles §1.5):
they encapsulate the concrete dependencies (glossary index, embedder, persist
dir, config, max results) and expose the protocol interfaces
(:class:`GlossaryScanner`, :class:`ContextRetriever`, :class:`WebSearcher`)
that ``nodes.py`` depends on. ``graph.py:build_graph`` creates the adapter
instances and injects them into the nodes.

Created during the SOLID/clean-code refactor (Section 9).
"""
from __future__ import annotations

from src.components.infrastructure.embeddings import EmbeddingAdapter
from src.components.knowledge_sources.glossary import (
    GlossaryIndex,
    scan_glossary_hits,
)
from src.components.knowledge_sources.legal_search import search_all_sources
from src.components.knowledge_sources.models import Lang
from src.components.knowledge_sources.retrieval import retrieve_context_chunks
from src.components.translation_pipeline.mappers import chunk_to_state, hit_to_state
from src.components.translation_pipeline.models import (
    ContextChunk,
    GlossaryHit,
    WebSearchResult,
)
from src.config import AppConfig


class GlossaryScannerAdapter:
    """Adapt :func:`scan_glossary_hits` to the :class:`GlossaryScanner` protocol.

    Encapsulates the optional :class:`GlossaryIndex` so the node sees a uniform
    ``scan(text, lang)`` interface regardless of whether a custom index is used.
    Maps dataclass hits to state TypedDicts.
    """

    __slots__ = ("_index",)

    def __init__(self, index: GlossaryIndex | None = None) -> None:
        self._index: GlossaryIndex | None = index

    def scan(self, text: str, lang: Lang) -> list[GlossaryHit]:
        return [
            hit_to_state(h)
            for h in scan_glossary_hits(text, lang, index=self._index)
        ]


class ContextRetrieverAdapter:
    """Adapt :func:`retrieve_context_chunks` to the :class:`ContextRetriever` protocol.

    Encapsulates the embedder, persist directory, and config so the node sees a
    uniform ``retrieve(query, n)`` interface. Maps dataclass chunks to state
    TypedDicts with the ``score = 1.0 - distance`` conversion.
    """

    __slots__ = ("_embedder", "_persist_dir", "_cfg")

    def __init__(
        self,
        *,
        embedder: EmbeddingAdapter | None = None,
        persist_dir: str | None = None,
        cfg: AppConfig | None = None,
    ) -> None:
        self._embedder: EmbeddingAdapter | None = embedder
        self._persist_dir: str | None = persist_dir
        self._cfg: AppConfig | None = cfg

    def retrieve(self, query: str, n: int) -> list[ContextChunk]:
        return [
            chunk_to_state(c)
            for c in retrieve_context_chunks(
                query,
                persist_dir=self._persist_dir,
                embedder=self._embedder,
                cfg=self._cfg,
            )
        ]


class WebSearcherAdapter:
    """Adapt :func:`search_all_sources` to the :class:`WebSearcher` protocol.

    Encapsulates ``max_results_per_source`` so the node sees a uniform
    ``search(query)`` interface. Maps :class:`SearchHit` dataclasses to state
    TypedDicts. Network errors are allowed to propagate — the node handles
    them (the pipeline must not crash on a web search failure).
    """

    __slots__ = ("_max_results_per_source",)

    def __init__(self, max_results_per_source: int = 5) -> None:
        self._max_results_per_source: int = max_results_per_source

    def search(self, query: str) -> list[WebSearchResult]:
        hits = search_all_sources(
            query, max_results_per_source=self._max_results_per_source
        )
        return [
            WebSearchResult(
                title=h.title, url=h.url, snippet=h.snippet, source=h.source
            )
            for h in hits
        ]
