"""PDF (.pdf) document translation — sidecar .docx/.txt adapter.

The PDF adapter extracts text per page via ``pypdf`` (lazy-imported inside
:func:`extract_pdf_paragraphs` so the ``word`` / ``excel`` / ``translate`` /
``batch`` / ``ui`` code paths never import ``pypdf``), translates each unique
paragraph through the existing :func:`run_translation` seam (concurrency = 1
per the RAM rule), and writes a translated sidecar file — a minimal ``.docx``
(by default) or ``.txt`` — to ``--out``. The original PDF is never rewritten
(in-place PDF rewrite is lossy and complex with Arabic fonts/reshaping; the
``add-pdf-word-translation`` proposal §Approach rejected it).

The pure helpers (:func:`extract_pdf_paragraphs`, :func:`_segment_page`,
:func:`build_docx_from_paragraphs`, :func:`build_txt_from_paragraphs`) have
**no dependency on the pipeline or adapters**. :func:`translate_pdf` is the
orchestration seam that reuses :func:`run_translation`.

Security: every paragraph is escaped via :func:`src.utils.xml_escape.escape_xml_text`
before insertion into the sidecar ``.docx`` (LLM-injection defense). The only
new runtime dependency is ``pypdf>=4.0,<5`` (pure Python, MIT-licensed,
offline, lazy-imported); the sidecar writers use only the Python standard
library.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from src.components.infrastructure.embeddings import EmbeddingAdapter
from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.infrastructure.run_logging import RunLogger
from src.components.interfaces._doc_common import (
    ProgressCallback,
    StringSegment,
    translate_segment,
)
from src.components.interfaces.models import PdfTranslationReport
from src.components.knowledge_sources.glossary import GlossaryIndex
from src.components.knowledge_sources.tm import TranslationMemory
from src.components.translation_pipeline.exceptions import InputValidationError
from src.config import AppConfig
from src.utils.xml_escape import escape_xml_text
from src.utils.zip_safe import validate_zip_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OOXML namespace for the sidecar .docx
# ---------------------------------------------------------------------------

_NS_W: str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# ---------------------------------------------------------------------------
# Pure PDF text helpers (no pipeline dependency; pypdf lazy-imported)
# ---------------------------------------------------------------------------

# Split on blank lines (one or more newlines surrounded by whitespace).
_PARAGRAPH_SPLIT_RE: re.Pattern[str] = re.compile(r"\n\s*\n")
# A block that is only digits, commas, periods, or whitespace (page numbers).
_PURE_NUMBER_RE: re.Pattern[str] = re.compile(r"^[\d\s,.\u0600-\u06FF]+$")
# A short header/footer block: < 60 chars and only "word-like" tokens.
_SHORT_BLOCK_MAX: int = 60


def _segment_page(text: str, *, cfg: AppConfig) -> list[str]:
    """Segment a page's extracted text into paragraphs.

    Splits on ``\\n\\s*\\n`` (blank lines); collapses internal newlines to
    spaces; skips empty blocks and pure-number blocks (page numbers). When
    ``cfg.pdf.skip_header_footer`` is True, drops the first and last block
    when they are short (``< 60`` chars) and look like headers/footers
    (digits, roman numerals, or single words).
    """
    raw_blocks = _PARAGRAPH_SPLIT_RE.split(text)
    blocks: list[str] = []
    for block in raw_blocks:
        collapsed = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if not collapsed.strip():
            continue
        # Skip pure-number blocks (page numbers embedded in the text flow).
        if _PURE_NUMBER_RE.match(collapsed.strip()) and not any(
            c.isalpha() for c in collapsed
        ):
            continue
        blocks.append(collapsed)

    if not blocks:
        return []

    if cfg.pdf.skip_header_footer and len(blocks) > 2:
        # Drop the first and last block when they are short header/footer-like.
        if len(blocks[0]) < _SHORT_BLOCK_MAX and not _has_sentence_text(blocks[0]):
            blocks.pop(0)
        if (
            len(blocks) > 1
            and len(blocks[-1]) < _SHORT_BLOCK_MAX
            and not _has_sentence_text(blocks[-1])
        ):
            blocks.pop(-1)

    return blocks


def _has_sentence_text(block: str) -> bool:
    """Return True if ``block`` looks like real sentence text (not a header/footer)."""
    # A header/footer is typically a single short word or a page number.
    # Real sentence text has multiple words and at least one letter-heavy word.
    words = block.split()
    if len(words) <= 1:
        return False
    # At least one word with >= 4 alpha chars suggests sentence text.
    return any(len(w) >= 4 and w.isalpha() for w in words)


def extract_pdf_paragraphs(
    pdf_path: str, *, cfg: AppConfig
) -> tuple[list[list[str]], list[str]]:
    """Extract per-page paragraphs from a PDF.

    Lazy-imports ``pypdf.PdfReader`` inside this function so the
    ``word`` / ``excel`` / ``translate`` / ``batch`` / ``ui`` code paths
    never import ``pypdf``.

    Returns ``(pages, warnings)`` where ``pages[i]`` is the list of paragraph
    strings on page ``i+1``. Pages that yield no extractable text (scanned
    PDFs) get an empty list and a warning
    ``"Page N: no extractable text (scanned PDF?)."``
    """
    from pypdf import PdfReader  # lazy import — confined to this function
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(pdf_path)
    except PyPdfError as e:
        raise InputValidationError(
            f"Input is not a valid PDF or is corrupted: {e}"
        ) from e
    max_pages: int = cfg.pdf.max_pages
    if len(reader.pages) > max_pages:
        raise InputValidationError(
            f"PDF has {len(reader.pages)} pages, exceeds the {max_pages}-page limit."
        )
    pages: list[list[str]] = []
    warnings: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        raw: str = page.extract_text() or ""
        if not raw.strip():
            warnings.append(f"Page {i}: no extractable text (scanned PDF?).")
            pages.append([])
            continue
        pages.append(_segment_page(raw, cfg=cfg))
    return pages, warnings


# ---------------------------------------------------------------------------
# Sidecar writers (pure, stdlib only)
# ---------------------------------------------------------------------------


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)

_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '</Relationships>'
)

_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
)


def _docx_paragraph_xml(text: str, *, rtl: bool) -> str:
    """Build the XML for one ``<w:p>`` paragraph with the given text."""
    escaped = escape_xml_text(text)
    ppr = "<w:pPr><w:bidiVisual/></w:pPr>" if rtl else ""
    return (
        f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{escaped}</w:t></w:r></w:p>"
    )


def _docx_page_break_xml() -> str:
    """Build the XML for a page-break paragraph."""
    return "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"


def build_docx_from_paragraphs(
    pages: list[list[str]], *, rtl: bool
) -> bytes:
    """Build a minimal ``.docx`` zip from per-page paragraph lists.

    Produces ``[Content_Types].xml``, ``_rels/.rels``,
    ``word/_rels/document.xml.rels``, and ``word/document.xml``. Each
    paragraph is one ``<w:p>``; between pages a page-break paragraph is
    emitted. ``<w:bidiVisual/>`` is added to each paragraph's ``<w:pPr>``
    only when ``rtl=True``. Every paragraph is escaped via
    :func:`escape_xml_text`. Every zip entry name is validated via
    :func:`validate_zip_path` (zip-slip defense-in-depth, matching the Word
    adapter).
    """
    body_parts: list[str] = []
    for pi, page in enumerate(pages):
        if pi > 0:
            body_parts.append(_docx_page_break_xml())
        for para in page:
            body_parts.append(_docx_paragraph_xml(para, rtl=rtl))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_NS_W}"><w:body>'
        + "".join(body_parts)
        + "</w:body></w:document>"
    )

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # Defense-in-depth: validate each entry name against zip-slip, matching
        # the Word adapter's pattern. The entries are generated internally
        # (not from user input), but validation guards against future regressions.
        z.writestr(validate_zip_path("[Content_Types].xml"), _CONTENT_TYPES)
        z.writestr(validate_zip_path("_rels/.rels"), _ROOT_RELS)
        z.writestr(validate_zip_path("word/_rels/document.xml.rels"), _DOC_RELS)
        z.writestr(validate_zip_path("word/document.xml"), document_xml)
    return out.getvalue()


def build_txt_from_paragraphs(pages: list[list[str]]) -> str:
    """Join paragraphs into a plain-text string with page-break markers.

    Paragraphs within a page are joined by ``\\n\\n``; pages are joined by
    ``\\n\\n--- page break ---\\n\\n``.
    """
    page_texts: list[str] = []
    for page in pages:
        page_texts.append("\n\n".join(page))
    return "\n\n--- page break ---\n\n".join(page_texts)


# ---------------------------------------------------------------------------
# Orchestration — reuses run_translation (DI, concurrency = 1)
# ---------------------------------------------------------------------------


def translate_pdf(
    input_path: str,
    output_path: str,
    direction: str,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: EmbeddingAdapter,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: TranslationMemory | None = None,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> PdfTranslationReport:
    """Translate a PDF to a sidecar .docx or .txt file.

    Extracts per-page paragraphs, deduplicates across all pages, translates
    each unique paragraph exactly once through :func:`run_translation`
    (concurrency = 1), re-assembles the translated pages, and writes the
    sidecar atomically. The original PDF is never rewritten.

    Per-segment translation failures are recorded as warnings with the
    original text preserved. Pages that yielded no extractable text are
    recorded in ``warnings``. If ``cancel_event`` becomes set, processing
    stops after the current segment and the report records ``cancelled=True``.
    """
    from src.components.interfaces.orchestration import detect_direction, run_translation

    input_p = Path(input_path)
    max_pdf_bytes: int = cfg.pdf.max_pdf_bytes
    if input_p.stat().st_size > max_pdf_bytes:
        raise InputValidationError(
            f"Input PDF is {input_p.stat().st_size} bytes, "
            f"exceeds the {max_pdf_bytes}-byte limit."
        )

    pages, extract_warnings = extract_pdf_paragraphs(input_path, cfg=cfg)

    # Flatten + deduplicate paragraphs across all pages.
    seen: dict[str, StringSegment] = {}
    for pi, page in enumerate(pages):
        for para in page:
            if para and para not in seen:
                seen[para] = StringSegment(part=f"page:{pi + 1}", text=para)
    segments: list[StringSegment] = list(seen.values())

    max_segments: int = cfg.pdf.max_segments
    if len(segments) > max_segments:
        raise InputValidationError(
            f"PDF has {len(segments)} translatable segments, "
            f"exceeds the {max_segments}-segment limit."
        )

    total: int = len(segments)
    translations: dict[str, str] = {}
    warnings: list[str] = list(extract_warnings)
    translated: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False
    max_chars: int = cfg.pdf.max_segment_chars
    # Track the dominant resolved direction for the sidecar RTL flag.
    # For explicit directions, this is the user's choice. For `auto`,
    # each segment's direction is resolved by detect_direction; the
    # majority wins (tie -> ar-en, matching detect_direction's default).
    ar_en_count: int = 0
    en_ar_count: int = 0

    for i, seg in enumerate(segments):
        if cancel_event is not None and cancel_event.is_set():
            skipped = total - i
            cancelled = True
            warnings.append(f"Cancelled: {skipped} segment(s) left untranslated.")
            break

        source: str = seg.text
        if len(source) > max_chars:
            warnings.append(
                f"Skipped oversized segment ({len(source)} > "
                f"{max_chars} chars) in {seg.part}: {source[:40]!r}..."
            )
            skipped += 1
            if progress is not None:
                progress(i + 1, total, source)
            continue

        if progress is not None:
            progress(i, total, source)

        effective_direction: str = (
            detect_direction(source) if direction == "auto" else direction
        )
        if effective_direction == "ar-en":
            ar_en_count += 1
        else:
            en_ar_count += 1

        result: str | None = translate_segment(
            source, seg, effective_direction, cfg,
            run_translation_fn=cast(Callable[..., Any], run_translation),
            llm=llm, embedder=embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
            run_logger=run_logger, tm=tm,
        )
        if result is None:
            failed += 1
            warnings.append(
                f"Translation failed for segment in {seg.part}; "
                f"original text preserved."
            )
        else:
            translations[source] = result
            translated += 1
        if progress is not None:
            progress(i + 1, total, source)

    # Re-assemble translated pages (untranslated -> original).
    translated_pages: list[list[str]] = []
    for page in pages:
        translated_page: list[str] = []
        for para in page:
            translated_page.append(translations.get(para, para))
        translated_pages.append(translated_page)

    # Branch on output format.
    # Derive the sidecar RTL flag from the dominant resolved direction.
    # For explicit directions, ar_en_count/en_ar_count reflect the user's
    # choice (all segments use it). For `auto`, the majority of per-segment
    # detect_direction resolutions wins (tie -> ar-en -> RTL).
    rtl: bool = ar_en_count >= en_ar_count
    if cfg.pdf.out_format == "txt":
        out_content: bytes = build_txt_from_paragraphs(translated_pages).encode("utf-8")
    else:
        out_content = build_docx_from_paragraphs(
            translated_pages, rtl=rtl
        )

    output_p = Path(output_path)
    tmp_path = output_p.with_suffix(output_p.suffix + ".tmp")
    with open(tmp_path, "wb") as f:
        f.write(out_content)
    os.replace(tmp_path, output_p)

    return PdfTranslationReport(
        total_pages=len(pages),
        total_segments=total,
        translated=translated,
        skipped=skipped,
        failed=failed,
        cancelled=cancelled,
        warnings=warnings,
    )


__all__ = [
    "ProgressCallback",
    "StringSegment",
    "build_docx_from_paragraphs",
    "build_txt_from_paragraphs",
    "extract_pdf_paragraphs",
    "translate_pdf",
]
