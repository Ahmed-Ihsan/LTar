"""Prompt formatting helpers for the translation pipeline (SRP).

Extracted from ``nodes.py`` so the node functions focus on orchestration.
These helpers format glossary hits, context chunks, and web search results
into the prompt template sections (PROMPTS.md §2.2), resolve language pairs
from a direction, and augment the retrieval query for EN→AR.
"""
from __future__ import annotations

from src.components.knowledge_sources.models import Lang
from src.components.translation_pipeline.constants import NA_PLACEHOLDER
from src.components.translation_pipeline.models import (
    ContextChunk as StateContextChunk,
)
from src.components.translation_pipeline.models import (
    GlossaryHit as StateGlossaryHit,
)
from src.components.translation_pipeline.models import WebSearchResult

# Source/target language labels per direction (closed set, clean-code §1.1).
_DIR_LANGS: dict[str, tuple[Lang, Lang]] = {
    "ar-en": ("ar", "en"),
    "en-ar": ("en", "ar"),
}


def langs(direction: str) -> tuple[Lang, Lang]:
    """Resolve ``(source_lang, target_lang)`` from a translation direction."""
    return _DIR_LANGS[direction]


def augment_query_for_retrieval(
    input_text: str,
    source_lang: str,
    target_lang: str,
    hits: list[StateGlossaryHit],
) -> str:
    """Augment the retrieval query with target-language glossary anchors.

    The RAG corpus is predominantly Arabic (see the corpus build in
    ``src.ingestion.py``), so an English query embeds poorly against it and
    EN→AR retrieval returns weakly-relevant chunks. For EN→AR, the
    glossary-bound Arabic target terms are appended to the query as anchors so
    the Arabic corpus returns chunks the translator can mimic for register and
    phrasing. AR→EN retrieval is already monolingual (Arabic query → Arabic
    corpus) and is left unchanged to avoid regressing the strong direction.
    """
    if source_lang != "en" or target_lang != "ar" or not hits:
        return input_text
    anchors: list[str] = [
        h["target_term"] for h in hits if h.get("target_term")
    ]
    if not anchors:
        return input_text
    return input_text + "\n" + " ".join(anchors)


def format_glossary_bindings(hits: list[StateGlossaryHit]) -> str:
    """Format glossary hits as the prompt bindings list (PROMPTS.md §2.2).

    One line per hit:
    ``"{source_term}"  ->  "{target_term}"   [Law: {law_ref}, Art: {article_ref}]``
    """
    if not hits:
        return NA_PLACEHOLDER
    lines: list[str] = []
    for hit in hits:
        article: str = hit.get("article_ref", "") or ""
        lines.append(
            f'"{hit["source_term"]}"  ->  "{hit["target_term"]}"'
            f'   [Law: {hit["law_ref"]}, Art: {article}]'
        )
    return "\n".join(lines)


def format_context_chunks(chunks: list[StateContextChunk]) -> str:
    """Format context chunks with provenance headers (PROMPTS.md §2.2)."""
    if not chunks:
        return NA_PLACEHOLDER
    lines: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(
            f"[Chunk {i} | Law: {chunk['law']} | Article: {chunk['article']}]\n"
            f"{chunk['text']}"
        )
    return "\n\n".join(lines)


def format_web_search_results(results: list[WebSearchResult]) -> str:
    """Format web search hits for the translator/auditor prompt.

    Each hit is rendered as:
    ``[Source: {source}] {title} — {snippet} ({url})``
    """
    if not results:
        return NA_PLACEHOLDER
    lines: list[str] = []
    for i, r in enumerate(results, start=1):
        title: str = r.get("title", "")
        url: str = r.get("url", "")
        snippet: str = r.get("snippet", "")
        source: str = r.get("source", "")
        header: str = f"[{i} | Source: {source}] {title}\n  URL: {url}"
        if snippet:
            header += f"\n  Snippet: {snippet}"
        lines.append(header)
    return "\n\n".join(lines)
