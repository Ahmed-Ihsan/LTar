"""Domain models for the knowledge_sources component.

Co-locates the internal dataclasses used across the knowledge layer
(glossary, retrieval, translation memory, legal search, ingestion) so the
component is self-describing. These are the *internal* representations; the
state-machine projections (TypedDicts) live in
:mod:`src.components.translation_pipeline.models`.

``Lang`` is the shared language alias for corpus/glossary entries.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Lang = Literal["ar", "en"]
"""Language of a glossary term or corpus article: Arabic or English."""


@dataclass(slots=True, frozen=True)
class Term:
    """A single glossary entry (DATA_SPEC §2.2).

    ``source_term`` is stored verbatim (used for prompt display and offset
    matching); ``source_term_norm`` is the normalized lookup key. ``file_path``
    and ``file_order`` provide deterministic provenance for the §2.4 tie-break.
    """

    source_term: str
    source_lang: Lang
    target_term: str
    target_lang: Lang
    law_ref: str
    domain: str
    source_term_norm: str
    file_path: str
    file_order: int
    article_ref: str | None = None
    note: str | None = None
    priority: int = 0


@dataclass(slots=True, frozen=True)
class SearchHit:
    """One search result from a legal source."""

    title: str
    url: str
    snippet: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


@dataclass(slots=True, frozen=True)
class TmEntry:
    """A stored bilingual sentence pair with provenance."""

    source_sentence: str
    target_sentence: str
    source_lang: str
    target_lang: str
    law_slug: str
    article: str


@dataclass(slots=True, frozen=True)
class ContextChunk:
    """A retrieved chunk with its provenance and similarity distance.

    Mirrors :class:`Chunk` plus the ``distance`` reported by ChromaDB
    (lower = more similar under cosine space). Used by
    ``retrieve_context_chunks`` (engineering-principles §2.1.3) and the
    ingestion verification query.
    """

    chunk_id: str
    text: str
    law: str
    article: str
    lang: str
    law_slug: str
    chunk_idx: int
    char_start: int
    char_end: int
    distance: float


@dataclass(slots=True, frozen=True)
class Article:
    """A parsed corpus article (DATA_SPEC §1.2).

    ``char_start`` / ``char_end`` are offsets into the *original file* pointing
    at the article body (excluding the ``ARTICLE N`` marker line), so the body
    text is recoverable as ``file_text[char_start:char_end]``. ``law_slug`` is
    derived from the file name (e.g. ``civil_code_ar.txt`` -> ``civil_code``)
    and feeds the deterministic chunk-id scheme (DATA_SPEC §3.5).
    """

    number: str
    text: str
    law: str
    source: str
    lang: Lang
    law_slug: str
    char_start: int
    char_end: int
    file_path: str


@dataclass(slots=True, frozen=True)
class Chunk:
    """A chunk produced from an article (DATA_SPEC §3).

    ``char_start`` / ``char_end`` are file-relative offsets so the application
    can cite the exact source span (DATA_SPEC §5). ``chunk_id`` follows
    ``{law_slug}_{article_normalized}_{chunk_idx}`` (DATA_SPEC §3.5) and is
    deterministic across re-ingestion.
    """

    chunk_id: str
    text: str
    law: str
    article: str
    lang: Lang
    law_slug: str
    chunk_idx: int
    char_start: int
    char_end: int
