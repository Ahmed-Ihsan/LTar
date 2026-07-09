"""Domain models for the interfaces component.

Co-locates the CLI/UI dataclasses that bundle adapter wiring and command
outcomes. These are the interface-layer DTOs; the orchestration logic that
populates them lives in :mod:`src.components.interfaces.cli`.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.knowledge_sources.glossary import GlossaryIndex


@dataclass(slots=True, frozen=True)
class CheckResult:
    """Outcome of a single ``doctor`` check."""

    name: str
    ok: bool
    detail: str


@dataclass(slots=True, frozen=True)
class Adapters:
    """Bundle of concrete adapters constructed by the CLI (engineering-principles §3.6).

    Built once per command invocation and passed into the orchestration seam.
    ``tm`` is ``None`` when TM is disabled.
    """

    llm: LLMEngineAdapter
    embedder: object
    glossary_index: GlossaryIndex | None
    persist_dir: str
    tm: object | None


@dataclass(slots=True, frozen=True)
class UiTranslationResult:
    """The three outputs a single UI translation produces (one per tab/panel)."""

    translation: str
    provenance_md: str
    audit_trace_md: str
