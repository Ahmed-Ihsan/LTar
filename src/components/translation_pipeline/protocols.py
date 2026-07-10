"""PEP 544 protocols for the translation pipeline's external dependencies (DIP).

``nodes.py`` depends on three external capabilities — glossary scanning,
context retrieval, and web search — that are currently imported as concrete
functions from ``knowledge_sources``. These protocols define the abstract
contracts so ``nodes.py`` depends on abstractions, not concretions
(engineering-principles §1.5). The concrete implementations are wired in
``graph.py:build_graph`` via small adapter wrappers (composition root).

The protocols are structural (PEP 544): any class with the right methods
satisfies them automatically — no inheritance required.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.components.knowledge_sources.models import Lang
from src.components.translation_pipeline.models import (
    ContextChunk,
    GlossaryHit,
    WebSearchResult,
)


@runtime_checkable
class GlossaryScanner(Protocol):
    """Scans text for glossary term matches (engineering-principles §2.1.2)."""

    def scan(self, text: str, lang: Lang) -> list[GlossaryHit]:
        """Return glossary hits found in ``text`` for the source ``lang``."""
        ...


@runtime_checkable
class ContextRetriever(Protocol):
    """Retrieves corpus context chunks for a query (engineering-principles §2.1.3)."""

    def retrieve(self, query: str, n: int) -> list[ContextChunk]:
        """Return the top-``n`` context chunks most similar to ``query``."""
        ...


@runtime_checkable
class WebSearcher(Protocol):
    """Searches Iraqi legal sources for additional context."""

    def search(self, query: str) -> list[WebSearchResult]:
        """Return web search hits from Iraqi legal sources for ``query``."""
        ...
