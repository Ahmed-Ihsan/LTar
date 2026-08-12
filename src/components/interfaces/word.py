"""Word (.docx) document translation — in-place adapter.

Mirrors :mod:`src.components.interfaces.excel`: pure XML helpers
(:func:`extract_word_strings` / :func:`patch_word_strings` /
:func:`split_translation`) operate on document bytes with **no dependency on
the pipeline or adapters**, and :func:`translate_word` is the orchestration
seam that reuses the existing :func:`run_translation` (Translator → Auditor →
Revise) loop with concurrency = 1 per the RAM rule.

The adapter uses only the Python standard library plus the existing
``defusedxml`` dependency — never ``python-docx``, ``lxml``, ``pypdf``, or any
other third-party package (per the ``add-pdf-word-translation`` spec,
"Word and PDF features respect hard constraints").

Text-bearing OOXML parts (allowlist):

- ``word/document.xml`` — body paragraphs' ``w:t`` runs (body, tables, text
  boxes; everything under ``w:body``).
- ``word/headerN.xml`` / ``word/footerN.xml`` — when
  ``cfg.word.translate_headers_footers``.
- ``word/footnotes.xml`` — when ``cfg.word.translate_footnotes``.
- ``word/endnotes.xml`` — when ``cfg.word.translate_endnotes``.
- ``word/comments.xml`` — when ``cfg.word.translate_comments``.
- ``word/glossary/document.xml`` — only when
  ``cfg.word.translate_glossary_doc`` (default ``False`` — it is a
  term-definition reference, not translatable content).

Every other part (styles, themes, fonts, numbering, settings, embedded images,
drawings, shapes, hyperlink relationships, tracked-change ``w:ins`` /
``w:del`` wrappers, custom XML parts) is preserved byte-for-byte.

Security: XML is parsed with ``defusedxml.ElementTree.fromstring`` (XXE
defense); every zip entry name is validated via
:func:`src.utils.zip_safe.validate_zip_path` (zip-slip defense); every
translated chunk is escaped via :func:`src.utils.xml_escape.escape_xml_text`
before assignment to ``el.text`` (LLM-injection defense).
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
from xml.etree import ElementTree as ET

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring as ET_fromstring

from src.components.infrastructure.embeddings import EmbeddingAdapter
from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.infrastructure.run_logging import RunLogger
from src.components.interfaces._doc_common import (
    ProgressCallback,
    StringSegment,
    translate_segment,
)
from src.components.interfaces.models import WordTranslationReport
from src.components.knowledge_sources.glossary import GlossaryIndex
from src.components.knowledge_sources.tm import TranslationMemory
from src.components.translation_pipeline.exceptions import InputValidationError
from src.config import AppConfig
from src.utils.xml_escape import escape_xml_text
from src.utils.zip_safe import validate_zip_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OOXML namespaces
# ---------------------------------------------------------------------------

NS_W: str = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Register the prefix for faithful serialization (Word uses ``w:``).
ET.register_namespace("w", NS_W)

_W_MAIN: str = NS_W  # re-exported for tests; full-namespace tag helper below.
_T: str = f"{{{NS_W}}}t"
_R: str = f"{{{NS_W}}}r"
_P: str = f"{{{NS_W}}}p"
_RPR: str = f"{{{NS_W}}}rPr"
_PPR: str = f"{{{NS_W}}}pPr"
_BIDI: str = f"{{{NS_W}}}bidiVisual"

# Arabic script Unicode range (U+0600–U+06FF), matching orchestration.detect_direction.
_ARABIC_RANGE_START: int = 0x0600
_ARABIC_RANGE_END: int = 0x06FF


def _is_arabic_dominant(text: str) -> bool:
    """Return True if ``text`` has more Arabic-script chars than Latin chars.

    Mirrors ``orchestration.detect_direction`` but is self-contained so the
    pure helper ``patch_word_strings`` has no dependency on the pipeline or
    orchestration module. Arabic >= Latin → True (matching detect_direction's
    tie-breaks-to-ar-en default).
    """
    arabic_count: int = 0
    latin_count: int = 0
    for ch in text:
        code: int = ord(ch)
        if _ARABIC_RANGE_START <= code <= _ARABIC_RANGE_END:
            arabic_count += 1
        elif ch.isascii() and ch.isalpha():
            latin_count += 1
    return arabic_count >= latin_count


# ---------------------------------------------------------------------------
# Allowlisted text-bearing parts
# ---------------------------------------------------------------------------


def _is_allowlisted_part(name: str, cfg: AppConfig) -> bool:
    """Return True if ``name`` is a Word part we may re-serialize for translation."""
    if name == "word/document.xml":
        return True
    if cfg.word.translate_headers_footers and (
        re.match(r"word/header\d+\.xml$", name)
        or re.match(r"word/footer\d+\.xml$", name)
    ):
        return True
    if cfg.word.translate_footnotes and name == "word/footnotes.xml":
        return True
    if cfg.word.translate_endnotes and name == "word/endnotes.xml":
        return True
    if cfg.word.translate_comments and name == "word/comments.xml":
        return True
    if cfg.word.translate_glossary_doc and name == "word/glossary/document.xml":
        return True
    return False


# ---------------------------------------------------------------------------
# Pure XML helpers — paragraph text + run-length extraction
# ---------------------------------------------------------------------------


def _paragraph_text(p_el: ET.Element) -> tuple[str, list[int]]:
    """Concatenate the ``w:t`` text of all ``w:r`` runs in ``p_el``.

    Returns ``(text, run_lengths)`` where ``run_lengths[i]`` is the character
    length of the i-th run's ``w:t`` text. A space is inserted between runs
    when the previous run's text does not end in whitespace AND the next run's
    text does not start with whitespace (per OOXML spacing rules); that space
    is counted as belonging to the second run.

    Tracked-change wrappers (``w:ins`` / ``w:del``) and any other element that
    contains ``w:r`` runs are walked via ``p_el.iter`` so their runs are
    included in document order — the wrapper elements themselves are preserved
    byte-for-byte by :func:`patch_word_strings` (only the ``w:t`` text nodes
    are re-assigned).
    """
    parts: list[str] = []
    run_lengths: list[int] = []
    prev: str = ""
    for r_el in p_el.iter(_R):
        t_el = r_el.find(_T)
        if t_el is None:
            continue
        text: str = t_el.text or ""
        if not text:
            # An empty w:t still counts as a run with length 0 so the
            # proportional split in patch_word_strings keeps the run.
            run_lengths.append(0)
            prev = ""
            continue
        if prev and not prev[-1].isspace() and not text[0].isspace():
            parts.append(" ")
            # The inserted space belongs to this (second) run.
            run_lengths.append(len(text) + 1)
        else:
            run_lengths.append(len(text))
        parts.append(text)
        prev = text
    return "".join(parts), run_lengths


# ---------------------------------------------------------------------------
# Pure XML helpers — extraction
# ---------------------------------------------------------------------------


def extract_word_strings(
    docx_bytes: bytes, *, cfg: AppConfig
) -> list[StringSegment]:
    """Extract the deduplicated translatable paragraph segments from a .docx.

    Returns one :class:`StringSegment` per unique non-empty paragraph text, in
    first-seen order. Empty / whitespace-only paragraphs are skipped. The
    ``max_segment_chars`` filter is NOT applied here (the orchestrator owns
    that policy so it can record warnings), mirroring the excel helper.

    XML is parsed with :func:`defusedxml.ElementTree.fromstring` (XXE
    defense); unparseable parts are skipped safely. Every zip entry name is
    validated via :func:`validate_zip_path` (zip-slip defense).
    """
    seen: dict[str, StringSegment] = {}
    try:
        zin = zipfile.ZipFile(BytesIO(docx_bytes))
    except zipfile.BadZipFile as e:
        raise InputValidationError(
            f"Input .docx is not a valid zip/OOXML document: {e}"
        ) from e
    with zin:
        for info in zin.infolist():
            name = validate_zip_path(info.filename)
            if not _is_allowlisted_part(name, cfg):
                continue
            data = zin.read(name)
            if not data:
                continue
            try:
                root = ET_fromstring(data)
            except (ET.ParseError, DefusedXmlException):
                # Skip a part we cannot parse (incl. XXE-rejected DOCTYPE)
                # rather than failing the whole document.
                continue
            for p_el in root.iter(_P):
                text, _run_lengths = _paragraph_text(p_el)
                if not text.strip():
                    continue
                if text in seen:
                    continue
                seen[text] = StringSegment(part=name, text=text)
    return list(seen.values())


# ---------------------------------------------------------------------------
# Pure XML helpers — whole-translation-in-first-run split
# ---------------------------------------------------------------------------


def split_translation(translation: str, run_lengths: list[int]) -> list[str]:
    """Place the entire ``translation`` in the first run; empty the rest.

    The whole-translation-in-first-run strategy preserves the first run's
    formatting (the paragraph's dominant run) for the entire translation and
    never breaks a word across runs. Source-language run boundaries do not
    map to target-language word boundaries, so proportional splitting only
    corrupted formatting by slicing words mid-character.

    Returns a list of ``len(run_lengths)`` strings: ``[translation] + [""] * (n - 1)``.
    Kept as a compatibility wrapper so existing callers/tests of the public
    helper still resolve; the proportional-split logic is removed.
    """
    n: int = len(run_lengths)
    if n == 0:
        return []
    if n == 1:
        return [translation]
    return [translation] + [""] * (n - 1)


# ---------------------------------------------------------------------------
# Pure XML helpers — patching
# ---------------------------------------------------------------------------


def _serialize_part(root: ET.Element) -> bytes:
    """Serialize an OOXML part root to bytes with an XML declaration."""
    result: bytes = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    return result


def _adjust_bidi_direction(p_el: ET.Element, translation: str) -> None:
    """Set or remove ``<w:bidiVisual/>`` in the paragraph's ``<w:pPr>`` to
    match the dominant script of ``translation``.

    Arabic-dominant translation -> ensure ``<w:bidiVisual/>`` exists.
    Latin-dominant translation  -> remove ``<w:bidiVisual/>`` (and remove
    ``<w:pPr>`` if it becomes empty).

    Uses the same script heuristic the orchestrator uses for ``auto`` direction
    resolution, applied to the *translation* (the paragraph direction should
    match the output language, not the input).
    """
    is_rtl: bool = _is_arabic_dominant(translation)
    ppr: ET.Element | None = p_el.find(_PPR)
    if is_rtl:
        if ppr is None:
            ppr = ET.Element(_PPR)
            # pPr MUST be the first child of w:p per the OOXML schema.
            p_el.insert(0, ppr)
        if ppr.find(_BIDI) is None:
            bidi = ET.Element(_BIDI)
            ppr.insert(0, bidi)
    else:
        if ppr is not None:
            bidi_el: ET.Element | None = ppr.find(_BIDI)
            if bidi_el is not None:
                ppr.remove(bidi_el)
            # Remove pPr if it became empty to avoid leaving an empty
            # paragraph-properties element.
            if len(list(ppr)) == 0:
                p_el.remove(ppr)


def _patch_part(
    data: bytes,
    name: str,
    translations: dict[str, str],
    cfg: AppConfig,
) -> bytes:
    """Re-serialize one allowlisted Word part with translated paragraph text."""
    try:
        root = ET_fromstring(data)
    except (ET.ParseError, DefusedXmlException):
        # Cannot parse (incl. XXE-rejected DOCTYPE) -> return original bytes
        # unchanged (fail safe).
        return data
    set_bidi: bool = cfg.word.set_bidi_direction
    for p_el in root.iter(_P):
        text, run_lengths = _paragraph_text(p_el)
        if not text.strip():
            continue
        new = translations.get(text)
        if new is None or new == text:
            continue
        # Collect the w:t elements in document order (same walk as
        # _paragraph_text) and place the whole translation in the first run.
        t_els: list[ET.Element] = []
        for r_el in p_el.iter(_R):
            t_el = r_el.find(_T)
            if t_el is not None:
                t_els.append(t_el)
        if not t_els:
            continue
        chunks = split_translation(new, run_lengths)
        for t_el, chunk in zip(t_els, chunks, strict=True):
            t_el.text = escape_xml_text(chunk)
            # Preserve leading/trailing whitespace in the run.
            if chunk and (chunk[0].isspace() or chunk[-1].isspace()):
                t_el.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        # Adjust paragraph RTL/bidi direction to match the translation script.
        if set_bidi:
            _adjust_bidi_direction(p_el, new)
    return _serialize_part(root)


def patch_word_strings(
    docx_bytes: bytes,
    translations: dict[str, str],
    *,
    cfg: AppConfig,
) -> bytes:
    """Write ``translations`` back into the .docx, preserving everything else.

    ``translations`` maps source paragraph text → translated text. For each
    allowlisted part, paragraphs are re-walked; the paragraph whose
    concatenated text matches a key is re-split across its original ``w:t``
    runs via :func:`split_translation` (preserving per-run formatting), and
    each chunk is escaped via :func:`escape_xml_text` before assignment. Every
    other ZIP part is copied byte-for-byte.
    """
    out = BytesIO()
    try:
        zin = zipfile.ZipFile(BytesIO(docx_bytes), mode="r")
    except zipfile.BadZipFile as e:
        raise InputValidationError(
            f"Input .docx is not a valid zip/OOXML document: {e}"
        ) from e
    with zin, zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            name = validate_zip_path(info.filename)
            data = zin.read(name)
            if _is_allowlisted_part(name, cfg) and data:
                data = _patch_part(data, name, translations, cfg)
            zout.writestr(info, data)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Orchestration — reuses run_translation (DI, concurrency = 1)
# ---------------------------------------------------------------------------


def translate_word(
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
) -> WordTranslationReport:
    """Translate a Word document, preserving all non-text artifacts.

    Reads the input document, extracts the deduplicated translatable
    paragraphs, translates each unique source paragraph exactly once through
    the existing :func:`run_translation` seam (concurrency = 1 per the RAM
    rule), patches the translations back, and writes the output document
    atomically.

    Per-segment translation failures (``LLMRuntimeError`` / ``EmbeddingError``)
    are recorded as warnings and the original text is preserved; the remaining
    segments are still processed. Other unexpected exceptions propagate.

    If ``cancel_event`` becomes set, processing stops after the current
    segment; already-translated segments are patched, remaining segments keep
    their original text, and the report records ``cancelled=True``.
    """
    from src.components.interfaces.orchestration import detect_direction, run_translation

    input_p = Path(input_path)
    max_docx_bytes: int = cfg.word.max_docx_bytes
    if input_p.stat().st_size > max_docx_bytes:
        raise InputValidationError(
            f"Input document is {input_p.stat().st_size} bytes, "
            f"exceeds the {max_docx_bytes}-byte limit."
        )

    with open(input_path, "rb") as f:
        docx_bytes: bytes = f.read()

    segments: list[StringSegment] = extract_word_strings(docx_bytes, cfg=cfg)
    max_segments: int = cfg.word.max_segments
    if len(segments) > max_segments:
        raise InputValidationError(
            f"Document has {len(segments)} translatable segments, "
            f"exceeds the {max_segments}-segment limit."
        )
    total: int = len(segments)
    translations: dict[str, str] = {}
    warnings: list[str] = []
    translated: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False
    max_chars: int = cfg.word.max_segment_chars

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

        # Resolve `auto` direction per-segment by script dominance.
        # For explicit directions (`ar-en` / `en-ar`), `detect_direction`
        # is never called — the user's choice is used as-is.
        effective_direction: str = (
            detect_direction(source) if direction == "auto" else direction
        )

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

    out_bytes: bytes = patch_word_strings(docx_bytes, translations, cfg=cfg)
    output_p = Path(output_path)
    tmp_path = output_p.with_suffix(output_p.suffix + ".tmp")
    with open(tmp_path, "wb") as f:
        f.write(out_bytes)
    os.replace(tmp_path, output_p)

    return WordTranslationReport(
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
    "extract_word_strings",
    "patch_word_strings",
    "split_translation",
    "translate_word",
]
