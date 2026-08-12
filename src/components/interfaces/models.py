"""Domain models for the interfaces component.

Co-locates the CLI/UI dataclasses that bundle adapter wiring and command
outcomes. These are the interface-layer DTOs; the orchestration logic that
populates them lives in :mod:`src.components.interfaces.cli`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.knowledge_sources.glossary import GlossaryIndex

if TYPE_CHECKING:
    from src.components.infrastructure.embeddings import EmbeddingAdapter
    from src.components.knowledge_sources.tm import TranslationMemory


@dataclass(slots=True, frozen=True)
class CheckResult:
    """Outcome of a single ``doctor`` check."""

    name: str
    ok: bool
    detail: str


@dataclass(slots=True, frozen=True)
class LLMAdapters:
    """LLM-related adapters (DIP — protocol-typed, injectable)."""

    llm: LLMEngineAdapter
    embedder: EmbeddingAdapter


@dataclass(slots=True, frozen=True)
class KnowledgeAdapters:
    """Knowledge-source adapters (DIP — protocol-typed, injectable)."""

    glossary_index: GlossaryIndex | None
    persist_dir: str
    tm: TranslationMemory | None


@dataclass(slots=True, frozen=True)
class Adapters:
    """Bundle of concrete adapters constructed by the CLI (engineering-principles §3.6).

    Composes :class:`LLMAdapters` and :class:`KnowledgeAdapters` for backward
    compatibility. Built once per command invocation and passed into the
    orchestration seam. ``tm`` is ``None`` when TM is disabled.
    """

    llm: LLMEngineAdapter
    embedder: EmbeddingAdapter
    glossary_index: GlossaryIndex | None
    persist_dir: str
    tm: TranslationMemory | None

    @property
    def llm_adapters(self) -> LLMAdapters:
        """Return the LLM adapter subset."""
        return LLMAdapters(llm=self.llm, embedder=self.embedder)

    @property
    def knowledge_adapters(self) -> KnowledgeAdapters:
        """Return the knowledge-source adapter subset."""
        return KnowledgeAdapters(
            glossary_index=self.glossary_index,
            persist_dir=self.persist_dir,
            tm=self.tm,
        )


@dataclass(slots=True, frozen=True)
class UiTranslationResult:
    """The three outputs a single UI translation produces (one per tab/panel)."""

    translation: str
    provenance_md: str
    audit_trace_md: str


@dataclass(slots=True, frozen=True)
class ExcelTranslationReport:
    """Outcome of an ``excel`` workbook translation run.

    Counts are over the deduplicated set of unique source segments extracted
    from the workbook. ``skipped`` covers segments left untranslated due to
    cancellation or the ``max_segment_chars`` cap; ``failed`` covers segments
    whose translation raised a domain error or returned empty output (the
    original text is preserved in both cases). ``cancelled`` is True when the
    run was interrupted via ``cancel_event``.
    """

    total_segments: int
    translated: int
    skipped: int
    failed: int
    cancelled: bool
    warnings: list[str]


@dataclass(slots=True, frozen=True)
class WordTranslationReport:
    """Outcome of a ``word`` document translation run.

    Counts are over the deduplicated set of unique source segments extracted
    from the .docx (body paragraphs, comments, headers/footers, footnotes,
    endnotes — per :class:`src.config.models.WordConfig`). ``skipped`` covers
    segments left untranslated due to cancellation or the
    ``max_segment_chars`` cap; ``failed`` covers segments whose translation
    raised a domain error or returned empty output (the original text is
    preserved in both cases). ``cancelled`` is True when the run was
    interrupted via ``cancel_event``.
    """

    total_segments: int
    translated: int
    skipped: int
    failed: int
    cancelled: bool
    warnings: list[str]


@dataclass(slots=True, frozen=True)
class PdfTranslationReport:
    """Outcome of a ``pdf`` document translation run.

    The PDF adapter extracts text per page and writes a translated sidecar
    file (``.docx`` or ``.txt``). ``total_pages`` is the number of pages
    processed; ``total_segments`` is the deduplicated segment count. ``skipped``
    covers segments left untranslated due to cancellation or the
    ``max_segment_chars`` cap; ``failed`` covers segments whose translation
    raised a domain error or returned empty output (the original text is
    preserved in both cases). ``cancelled`` is True when the run was
    interrupted via ``cancel_event``.
    """

    total_pages: int
    total_segments: int
    translated: int
    skipped: int
    failed: int
    cancelled: bool
    warnings: list[str]
