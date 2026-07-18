"""Excel (.xlsx) workbook translation adapter.

A document-translation adapter that translates the human-readable text of an
Excel workbook in place while preserving every non-text artifact (formulas,
merged cells, charts, images, comments structure, conditional formatting, data
validation, hyperlinks, page layout, custom XML parts) byte-for-byte.

Design (see ``openspec/changes/add-excel-translation/design.md``):

- The **pure XML helpers** (``protect_non_translatable`` / ``restore_protected``
  / ``extract_translatable_strings`` / ``patch_strings``) operate on workbook
  bytes with NO dependency on the pipeline or adapters. They use only the
  Python standard library (``zipfile``, ``xml.etree.ElementTree``, ``re``).
  This keeps them unit-testable without Ollama and respects the acyclic
  component dependency graph (interfaces → translation_pipeline, never the
  reverse).
- The **orchestrator** ``translate_excel`` reuses the existing
  :func:`src.components.interfaces.orchestration.run_translation` seam: each
  unique source string is translated exactly once through the full
  Translator → Auditor → Revise pipeline, then patched back.

An ``.xlsx`` file is a ZIP archive of OOXML parts. We only ever modify the
text-bearing nodes of a small allowlist of parts (``sharedStrings.xml``,
``xl/worksheets/sheetN.xml`` inline strings + headers/footers,
``xl/commentsN.xml``, ``xl/charts/chartN.xml`` titles). Every other part is
copied byte-for-byte into the output zip, so charts, images, conditional
formatting, data validation, page layout, and the workbook structure are
preserved exactly.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, cast
from xml.etree import ElementTree as ET

from defusedxml.ElementTree import fromstring as ET_fromstring

from src.components.infrastructure.embeddings import EmbeddingAdapter
from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.infrastructure.run_logging import RunLogger
from src.components.interfaces.models import ExcelTranslationReport
from src.components.knowledge_sources.glossary import GlossaryIndex
from src.components.knowledge_sources.tm import TranslationMemory
from src.components.translation_pipeline.exceptions import (
    EmbeddingError,
    InputValidationError,
    LLMRuntimeError,
)
from src.config import AppConfig
from src.utils.xml_escape import escape_xml_text
from src.utils.zip_safe import validate_zip_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OOXML namespaces (registered so round-tripped XML keeps Excel's prefixes).
# ---------------------------------------------------------------------------

NS_MAIN: str = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_DRAWING: str = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_CHART: str = "http://schemas.openxmlformats.org/chartml/2006/main"
NS_REL: str = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Register prefixes for faithful serialization. The main spreadsheet namespace
# is the default (empty prefix) in Excel's part documents.
ET.register_namespace("", NS_MAIN)
ET.register_namespace("a", NS_DRAWING)
ET.register_namespace("c", NS_CHART)
ET.register_namespace("r", NS_REL)

_T_MAIN: str = f"{{{NS_MAIN}}}t"
_T_DRAWING: str = f"{{{NS_DRAWING}}}t"
_SI_MAIN: str = f"{{{NS_MAIN}}}si"
_IS_MAIN: str = f"{{{NS_MAIN}}}is"
_TEXT_MAIN: str = f"{{{NS_MAIN}}}text"
_HEADERFOOTER_MAIN: str = f"{{{NS_MAIN}}}headerFooter"
_TITLE_CHART: str = f"{{{NS_CHART}}}title"

# Header/footer child element local names that carry literal text.
_HEADERFOOTER_CHILDREN: tuple[str, ...] = (
    "oddHeader", "evenHeader", "oddFooter", "evenFooter",
    "firstHeader", "firstFooter",
)

# ZIP parts we may re-serialize. Anything else is copied byte-for-byte.
_SHARED_STRINGS_PART: str = "xl/sharedStrings.xml"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class StringSegment:
    """One translatable text occurrence in a workbook part.

    ``part`` is the ZIP entry path (e.g. ``xl/sharedStrings.xml``). ``text`` is
    the source text. Segments are deduplicated by ``text`` so each unique
    source string is translated exactly once; ``part`` is retained for
    reporting and debugging.
    """

    part: str
    text: str


# ---------------------------------------------------------------------------
# Non-translatable token protection
# ---------------------------------------------------------------------------

# Sentinel format: control-character-delimited so it never collides with real
# legal text and is passed through verbatim by local LLM tokenizers.
_SENTINEL_OPEN: str = "\x00T"
_SENTINEL_CLOSE: str = "\x00"
_SENTINEL_RE: re.Pattern[str] = re.compile(r"\x00T(\d+)\x00")

# Protection patterns, applied in order. URLs first (so embedded numbers/emails
# are not separately protected), then emails, template placeholders, Excel
# header/footer ``&``-codes, and finally standalone numbers.
_PROTECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://[^\s<>\"']+"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\$\{[^}]+\}"),
    re.compile(r"\{[^}]+\}"),
    re.compile(r"<[A-Za-z_][\w.-]*>"),
    re.compile(r"%[A-Za-z_][\w]*%"),
    re.compile(r"&[A-Za-z0-9\"&]"),
    re.compile(r"(?<![\w/])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w/])"),
)


def protect_non_translatable(
    text: str, *, cfg: AppConfig
) -> tuple[str, dict[str, str]]:
    """Replace non-translatable tokens with stable sentinels.

    Returns ``(protected_text, token_map)`` where ``token_map`` maps each
    sentinel to its original token. Identical originals reuse the same sentinel
    so the protected text stays short. ``cfg`` is accepted for future
    tunability (e.g. custom patterns); the current pattern set is fixed.
    """
    _ = cfg  # reserved for future pattern configuration
    token_map: dict[str, str] = {}
    original_to_sentinel: dict[str, str] = {}

    def _replace(match: re.Match[str]) -> str:
        original: str = match.group(0)
        sentinel = original_to_sentinel.get(original)
        if sentinel is None:
            sentinel = f"{_SENTINEL_OPEN}{len(token_map)}{_SENTINEL_CLOSE}"
            original_to_sentinel[original] = sentinel
            token_map[sentinel] = original
        return sentinel

    protected: str = text
    for pattern in _PROTECTION_PATTERNS:
        protected = pattern.sub(_replace, protected)
    return protected, token_map


def restore_protected(text: str, token_map: dict[str, str]) -> str:
    """Restore sentinels to their original tokens.

    Any leftover sentinel not in ``token_map`` is removed (defensive: a model
    that drops a sentinel should not corrupt the output).
    """
    def _restore(match: re.Match[str]) -> str:
        return token_map.get(match.group(0), "")

    return _SENTINEL_RE.sub(_restore, text)


# ---------------------------------------------------------------------------
# Pure XML helpers — extraction
# ---------------------------------------------------------------------------


def _is_allowlisted_part(name: str, cfg: AppConfig) -> bool:
    """Return True if ``name`` is a part we may re-serialize for translation."""
    if name == _SHARED_STRINGS_PART:
        return True
    if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
        return True
    if cfg.excel.translate_comments and name.startswith("xl/comments") \
            and name.endswith(".xml"):
        return True
    if cfg.excel.translate_chart_titles and name.startswith("xl/charts/chart") \
            and name.endswith(".xml"):
        return True
    return False


def _iter_translatable_elements(
    root: ET.Element, part: str, cfg: AppConfig
) -> list[ET.Element]:
    """Return the text-bearing elements in ``root`` per the allowlist.

    For string/comment/chart parts these are ``<t>`` / ``<a:t>`` elements. For
    worksheet parts they are inline-string ``<t>`` elements plus the
    header/footer child elements (when enabled). The returned list is in
    document order so :func:`patch_strings` can re-walk the same order.
    """
    elements: list[ET.Element] = []
    if part == _SHARED_STRINGS_PART:
        for si in root.findall(f".//{_SI_MAIN}"):
            elements.extend(si.iter(_T_MAIN))
        return elements

    if part.startswith("xl/comments"):
        for text_el in root.findall(f".//{_TEXT_MAIN}"):
            elements.extend(text_el.iter(_T_MAIN))
        return elements

    if part.startswith("xl/charts/chart"):
        for title in root.findall(f".//{_TITLE_CHART}"):
            elements.extend(title.iter(_T_DRAWING))
        return elements

    if part.startswith("xl/worksheets/sheet"):
        # Inline strings: <c t="inlineStr"><is>...<t>...</t></is></c>
        for is_el in root.findall(f".//{_IS_MAIN}"):
            elements.extend(is_el.iter(_T_MAIN))
        # Headers / footers (literal text with &-codes; protect handles codes).
        if cfg.excel.translate_headers_footers:
            hf = root.find(f".//{_HEADERFOOTER_MAIN}")
            if hf is not None:
                for child in hf:
                    if _local(child.tag) in _HEADERFOOTER_CHILDREN:
                        elements.append(child)
        return elements

    return elements


def _local(tag: str) -> str:
    """Strip the XML namespace from an ElementTree tag."""
    return tag.split("}", 1)[-1]


def extract_translatable_strings(
    xlsx_bytes: bytes, *, cfg: AppConfig
) -> list[StringSegment]:
    """Extract the deduplicated translatable text segments from a workbook.

    Returns one :class:`StringSegment` per unique non-empty source text, in
    first-seen order. Empty / whitespace-only texts are skipped. The
    ``max_segment_chars`` filter is NOT applied here (the orchestrator owns
    that policy so it can record warnings).
    """
    seen: dict[str, StringSegment] = {}
    with zipfile.ZipFile(BytesIO(xlsx_bytes)) as zin:
        for info in zin.infolist():
            name = validate_zip_path(info.filename)
            if not _is_allowlisted_part(name, cfg):
                continue
            data = zin.read(name)
            if not data:
                continue
            try:
                root = ET_fromstring(data)
            except ET.ParseError:
                # Skip a part we cannot parse rather than failing the workbook.
                continue
            for el in _iter_translatable_elements(root, name, cfg):
                text = el.text
                if text is None or not text.strip():
                    continue
                if text in seen:
                    continue
                seen[text] = StringSegment(part=name, text=text)
    return list(seen.values())


# ---------------------------------------------------------------------------
# Pure XML helpers — patching
# ---------------------------------------------------------------------------


def _serialize_part(root: ET.Element) -> bytes:
    """Serialize an OOXML part root to bytes with an XML declaration."""
    result: bytes = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    return result


def patch_strings(
    xlsx_bytes: bytes,
    segments: list[StringSegment],
    translations: dict[str, str],
    *,
    cfg: AppConfig,
) -> bytes:
    """Write ``translations`` back into the workbook, preserving everything else.

    ``translations`` maps source text → translated text. For each allowlisted
    part, the text-bearing elements are re-walked in the same order as
    :func:`extract_translatable_strings` and each element's text is replaced
    with ``translations.get(current_text, current_text)``. Every other ZIP part
    is copied byte-for-byte. ``segments`` is accepted for API symmetry; the
    lookup is keyed on each element's current text.
    """
    _ = segments  # lookup is by current text; segments retained for API symmetry
    out = BytesIO()
    with zipfile.ZipFile(BytesIO(xlsx_bytes), mode="r") as zin, \
            zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            name = validate_zip_path(info.filename)
            data = zin.read(name)
            if _is_allowlisted_part(name, cfg) and data:
                data = _patch_part(data, name, translations, cfg)
            zout.writestr(info, data)
    return out.getvalue()


def _patch_part(
    data: bytes,
    name: str,
    translations: dict[str, str],
    cfg: AppConfig,
) -> bytes:
    """Re-serialize one allowlisted part with translated text nodes."""
    try:
        root = ET_fromstring(data)
    except ET.ParseError:
        # Cannot parse -> return original bytes unchanged (fail safe).
        return data
    for el in _iter_translatable_elements(root, name, cfg):
        text = el.text
        if text is None or not text.strip():
            continue
        new = translations.get(text)
        if new is not None and new != text:
            el.text = escape_xml_text(new)
    return _serialize_part(root)


# ---------------------------------------------------------------------------
# Orchestration — reuses run_translation
# ---------------------------------------------------------------------------


class ProgressCallback(Protocol):
    """Progress callback signature: ``(completed, total, current_source)``."""

    def __call__(self, completed: int, total: int, current: str) -> None: ...


def _translate_segment(
    source: str,
    seg: StringSegment,
    direction: str,
    cfg: AppConfig,
    *,
    run_translation_fn: Callable[..., Any],
    llm: LLMEngineAdapter,
    embedder: EmbeddingAdapter,
    glossary_index: GlossaryIndex | None,
    persist_dir: str | None,
    run_logger: RunLogger | None,
    tm: TranslationMemory | None,
) -> str | None:
    """Translate one segment; return the translated text or ``None`` on failure.

    Protects non-translatable tokens, calls ``run_translation_fn``, restores
    the tokens, and returns the result. Returns ``None`` if the translation
    failed (``LLMRuntimeError`` / ``EmbeddingError``) or produced empty output;
    the caller records the warning and preserves the original text.
    """
    protected, token_map = protect_non_translatable(source, cfg=cfg)
    try:
        state = run_translation_fn(
            protected, direction, cfg,
            llm=llm, embedder=embedder,
            glossary_index=glossary_index, persist_dir=persist_dir,
            run_logger=run_logger, tm=tm,
        )
    except (LLMRuntimeError, EmbeddingError):
        return None
    raw: str = state.get("final_output") or ""
    restored: str = restore_protected(raw, token_map) if raw else source
    if not restored.strip():
        return None
    return restored


def translate_excel(
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
) -> ExcelTranslationReport:
    """Translate an Excel workbook, preserving all non-text artifacts.

    Reads the input workbook, extracts the deduplicated translatable strings,
    translates each unique source string exactly once through the existing
    :func:`run_translation` seam (concurrency = 1 per the RAM rule), patches
    the translations back, and writes the output workbook.

    Per-segment translation failures (``LLMRuntimeError`` / ``EmbeddingError``)
    are recorded as warnings and the original text is preserved; the remaining
    segments are still processed. Other unexpected exceptions propagate.

    If ``cancel_event`` becomes set, processing stops after the current
    segment; already-translated segments are patched, remaining segments keep
    their original text, and the report records ``cancelled=True``.
    """
    from src.components.interfaces.orchestration import run_translation

    input_p = Path(input_path)
    max_xlsx_bytes: int = cfg.excel.max_xlsx_bytes
    if input_p.stat().st_size > max_xlsx_bytes:
        raise InputValidationError(
            f"Input workbook is {input_p.stat().st_size} bytes, "
            f"exceeds the {max_xlsx_bytes}-byte limit."
        )

    with open(input_path, "rb") as f:
        xlsx_bytes: bytes = f.read()

    segments: list[StringSegment] = extract_translatable_strings(
        xlsx_bytes, cfg=cfg
    )
    max_segments: int = cfg.excel.max_segments
    if len(segments) > max_segments:
        raise InputValidationError(
            f"Workbook has {len(segments)} translatable segments, "
            f"exceeds the {max_segments}-segment limit."
        )
    total: int = len(segments)
    translations: dict[str, str] = {}
    warnings: list[str] = []
    translated: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False
    max_chars: int = cfg.excel.max_segment_chars

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

        result: str | None = _translate_segment(
            source, seg, direction, cfg,
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

    out_bytes: bytes = patch_strings(
        xlsx_bytes, segments, translations, cfg=cfg
    )
    output_p = Path(output_path)
    tmp_path = output_p.with_suffix(output_p.suffix + ".tmp")
    with open(tmp_path, "wb") as f:
        f.write(out_bytes)
    os.replace(tmp_path, output_p)

    return ExcelTranslationReport(
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
    "extract_translatable_strings",
    "patch_strings",
    "protect_non_translatable",
    "restore_protected",
    "translate_excel",
]
