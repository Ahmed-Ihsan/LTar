"""Corpus parsing and chunking.

Single responsibility (per ARCHITECTURE.md / engineering-principles §1.1):
parse corpus files into articles (streaming, per offline-architecture §1.2),
chunk articles (article-as-chunk if <= chunk_size tokens, else overlapping
split at paragraph -> sentence -> hard boundaries per DATA_SPEC §3.2), and
provide the single source of truth for ``approx_token_count`` (DATA_SPEC
§3.4).

This module is the ONLY place chunk size/overlap logic and the token-count
heuristic live (DRY, engineering-principles §2.1.1). ``retrieval.py`` and the
ingestion CLI call into ``chunk_article`` / ``approx_token_count``; they do
not re-implement them.

The ingestion orchestration (run_ingestion, manifest writer, CLI) has been
extracted to ``ingestion_runner.py`` and ``manifest.py`` (SRP). This module
re-exports those names for backward compatibility.
"""
from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any, cast

from src.components.knowledge_sources.manifest import (  # noqa: F401
    _COLLECTION_NAME,
    _MANIFEST_VERSION,
    CorpusSummary,
    FileHash,
    GlossarySummary,
    IngestionResult,
    content_hash as _content_hash,
    hash_files as _hash_files,
    project_root as _project_root,
    sha256_file as _sha256_file,
    write_manifest as _write_manifest,
)
from src.components.knowledge_sources.models import Article, Chunk, Lang
from src.components.translation_pipeline.exceptions import (
    CorpusEncodingError,
    CorpusParseError,
)

# ``ingestion_runner`` imports from this module, so it must be imported lazily
# to avoid a circular import. The re-exports below use PEP 562 ``__getattr__``.
_LAZY_REEXPORTS: dict[str, str] = {
    "ingest_app": "src.components.knowledge_sources.ingestion_runner",
    "run_ingestion": "src.components.knowledge_sources.ingestion_runner",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_REEXPORTS:
        module = importlib.import_module(_LAZY_REEXPORTS[name])
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Header field labels (DATA_SPEC §1.2). Single source of truth for the parser.
_LAW_HEADER: str = "LAW:"
_SOURCE_HEADER: str = "SOURCE:"
_LANG_HEADER: str = "LANG:"
_HEADER_SEPARATOR: str = "---"

# ARTICLE markers are on their own line: ``ARTICLE <number>`` (DATA_SPEC §1.2).
# ``N`` may be numeric or numeric with a suffix (``148 bis``, ``148 ter``).
_ARTICLE_MARKER_RE: re.Pattern[str] = re.compile(r"^ARTICLE\s+(.+?)\s*$")

# Arabic block used by the token-count heuristic (DATA_SPEC §3.4).
_ARABIC_BLOCK_START: str = "\u0600"
_ARABIC_BLOCK_END: str = "\u06FF"

# Paragraph separator: a blank line (two consecutive newlines).
_PARAGRAPH_SEP: str = "\n\n"

# A sentence unit = optional run of non-terminator chars, then one or more
# sentence terminators, then trailing whitespace. The trailing alternative
# catches a final fragment with no terminator. Units are self-delimiting, so
# ``"".join(unit_texts)`` reproduces the source exactly (used for chunk text
# reconstruction via char spans rather than joins, but the property keeps
# offsets honest).
_SENTENCE_UNIT_RE: re.Pattern[str] = re.compile(r"[^.!?]*[.!?]+\s*|[^.!?]+$")


# ---------------------------------------------------------------------------
# Data models (high cardinality during ingestion -> __slots__)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Token-count heuristic (DATA_SPEC §3.4) — single source of truth
# ---------------------------------------------------------------------------


def approx_token_count(text: str) -> int:
    """Conservative token-count estimate for ``nomic-embed-text``.

    Heuristic (DATA_SPEC §3.4): ~1 token per 4 chars for non-Arabic, ~1 token
    per 2 chars for Arabic, blended by script ratio. Intentionally
    overestimates slightly, biasing toward smaller chunks (safe for the RAM
    budget). Pure and deterministic.
    """
    arabic_chars: int = sum(
        1 for c in text if _ARABIC_BLOCK_START <= c <= _ARABIC_BLOCK_END
    )
    other_chars: int = len(text) - arabic_chars
    return max(1, (arabic_chars // 2) + (other_chars // 4))


# ---------------------------------------------------------------------------
# Corpus parsing (DATA_SPEC §1.2 / §1.4)
# ---------------------------------------------------------------------------


def _law_slug_from_path(path: Path) -> str:
    """Derive the law slug from a corpus file name.

    ``civil_code_ar.txt`` -> ``civil_code``. The slug is the file stem with the
    trailing ``_<lang>`` suffix removed.
    """
    stem: str = path.stem
    for sep in ("_", "-"):
        if sep in stem:
            head, _, tail = stem.rpartition(sep)
            if tail in ("ar", "en"):
                return head
    return stem


def _normalize_article_number(raw: str) -> str:
    """Normalize an article number (DATA_SPEC §1.4.4).

    Strips surrounding whitespace and lowercases suffixes (``Bis`` -> ``bis``,
    ``148 Ter`` -> ``148 ter``). The numeric portion is preserved verbatim.
    """
    return re.sub(
        r"\s+",
        " ",
        raw.strip().lower(),
    ).strip()


def _parse_header(
    lines: list[str], file_path: Path
) -> dict[str, str]:
    """Parse the header block (lines before the first ``---``)."""
    header: dict[str, str] = {}
    for line in lines:
        if line.startswith(_LAW_HEADER):
            header["law"] = line[len(_LAW_HEADER):].strip()
        elif line.startswith(_SOURCE_HEADER):
            header["source"] = line[len(_SOURCE_HEADER):].strip()
        elif line.startswith(_LANG_HEADER):
            header["lang"] = line[len(_LANG_HEADER):].strip()
    missing: list[str] = [
        name for name in ("law", "source", "lang") if name not in header
    ]
    if missing:
        raise CorpusParseError(
            f"{file_path}: missing required header field(s): "
            f"{', '.join(missing)}"
        )
    return header


def _strict_utf8_lines(handle: IO[str], path: Path) -> Iterator[str]:
    """Yield lines from ``handle``, translating late UTF-8 decode errors.

    ``open(..., errors="strict")`` defers decode errors until iteration time
    (the bad bytes are encountered), so the ``UnicodeDecodeError`` surfaces
    inside the ``for line in handle`` loop rather than at ``open``. This
    wrapper converts that late error into a :class:`CorpusEncodingError`
    carrying the file path, matching the catch matrix (clean-code §3.2:
    ``ingestion.parse_corpus_file`` / UnicodeDecodeError -> CorpusEncodingError).
    """
    try:
        for line in handle:
            yield line
    except UnicodeDecodeError as e:
        raise CorpusEncodingError(
            f"{path}: not valid UTF-8 (strict decode failed at "
            f"byte {e.start}): {e.reason}"
        ) from e


def _flush_current_article(
    current_number: str | None,
    current_lines: list[str],
    header: dict[str, str],
    law_slug: str,
    body_start: int,
    body_end: int,
    file_path: Path,
) -> Article | None:
    """Build and return the current article if one is being accumulated."""
    if current_number is None:
        return None
    return _build_article(
        number=current_number,
        body_lines=current_lines,
        header=header,
        law_slug=law_slug,
        body_start=body_start,
        body_end=body_end,
        file_path=file_path,
    )


def iter_articles(path: Path) -> Iterator[Article]:
    """Stream articles from a corpus file one at a time.

    Memory-bounded (offline-architecture §1.2): the file is read line-by-line
    and never materialized as a single string. Peak memory is proportional to
    the *largest single article*, not the largest file. Callers that process
    the full corpus (the ingestion CLI) should consume this generator directly
    rather than collecting into a list (offline-architecture §1.3).

    Raises:
        CorpusEncodingError: if the file is not valid UTF-8 (strict).
        CorpusParseError: if a required header field is missing.
    """
    file_path: Path = path
    law_slug: str = _law_slug_from_path(path)
    handle = open(path, encoding="utf-8", errors="strict", newline="")

    header_lines: list[str] = []
    header_parsed: dict[str, str] | None = None
    char_pos: int = 0
    current_number: str | None = None
    current_body_start: int = 0
    current_lines: list[str] = []

    with handle:
        for line in _strict_utf8_lines(handle, path):
            line_len: int = len(line)
            stripped: str = line.rstrip("\r\n")

            if header_parsed is None:
                if stripped == _HEADER_SEPARATOR:
                    header_parsed = _parse_header(header_lines, file_path)
                else:
                    header_lines.append(stripped)
                char_pos += line_len
                continue

            marker_match: re.Match[str] | None = _ARTICLE_MARKER_RE.match(
                stripped
            )
            if marker_match is not None:
                article: Article | None = _flush_current_article(
                    current_number, current_lines, header_parsed,
                    law_slug, current_body_start, char_pos, file_path,
                )
                if article is not None:
                    yield article
                current_number = _normalize_article_number(
                    marker_match.group(1)
                )
                current_lines = []
                current_body_start = char_pos + line_len
            elif current_number is not None:
                current_lines.append(stripped)

            char_pos += line_len

    if header_parsed is None:
        raise CorpusParseError(
            f"{file_path}: missing header separator '{_HEADER_SEPARATOR}'"
        )
    final: Article | None = _flush_current_article(
        current_number, current_lines, header_parsed,
        law_slug, current_body_start, char_pos, file_path,
    )
    if final is not None:
        yield final


def _build_article(
    number: str,
    body_lines: list[str],
    header: dict[str, str],
    law_slug: str,
    body_start: int,
    body_end: int,
    file_path: Path,
) -> Article:
    """Assemble an :class:`Article` from accumulated parse state."""
    body: str = "\n".join(body_lines)
    lang_value: str = header["lang"]
    if lang_value not in ("ar", "en"):
        raise CorpusParseError(
            f"{file_path}: LANG must be 'ar' or 'en', got '{lang_value}'"
        )
    return Article(
        number=number,
        text=body,
        law=sys.intern(header["law"]),
        source=header["source"],
        lang=cast(Lang, lang_value),
        law_slug=sys.intern(law_slug),
        char_start=body_start,
        char_end=body_end,
        file_path=str(file_path),
    )


def parse_corpus_file(path: Path) -> list[Article]:
    """Parse a corpus file into a list of :class:`Article` (DATA_SPEC §1.2).

    This is the list-returning convenience wrapper around the streaming
    :func:`iter_articles` generator, matching the TODO 2.2.1 signature. It is
    appropriate for smoke tests and small files; the full ingestion pipeline
    should consume :func:`iter_articles` directly to stay within the RAM
    budget (offline-architecture §1.2–§1.3).
    """
    return list(iter_articles(path))


# ---------------------------------------------------------------------------
# Chunking (DATA_SPEC §3.2) — single source of truth for split logic
# ---------------------------------------------------------------------------


def chunk_article(
    article: Article,
    target_tokens: int,
    overlap: int,
) -> list[Chunk]:
    """Chunk an article per DATA_SPEC §3.2.

    - If the whole article is <= ``target_tokens``: one chunk (the common case
      for Iraqi statutory articles).
    - Otherwise: split into overlapping chunks of <= ``target_tokens`` with
      ``overlap`` tokens carried between consecutive chunks. Split boundaries
      descend paragraph -> sentence -> hard 512-token boundary, and a sentence
      is never split mid-way unless it alone exceeds the target.

    Each chunk inherits the article's metadata and gets a sequential
    ``chunk_idx`` starting at 0. Char offsets are file-relative
    (``article.char_start`` + in-article offset) so the source span is citable.
    Chunk ids are deterministic (DATA_SPEC §3.5).
    """
    if target_tokens <= 0:
        raise ValueError(f"target_tokens must be positive, got {target_tokens}")
    if overlap < 0:
        raise ValueError(f"overlap must be non-negative, got {overlap}")

    body: str = article.text
    if approx_token_count(body) <= target_tokens:
        return [
            _make_chunk(
                article=article,
                chunk_idx=0,
                rel_start=0,
                rel_end=len(body),
            )
        ]

    unit_spans: list[tuple[int, int]] = _leaf_unit_spans(
        body, target_tokens
    )
    chunk_spans: list[tuple[int, int]] = _pack_units_with_overlap(
        unit_spans, body, target_tokens, overlap
    )
    return [
        _make_chunk(
            article=article,
            chunk_idx=idx,
            rel_start=start,
            rel_end=end,
        )
        for idx, (start, end) in enumerate(chunk_spans)
    ]


def _make_chunk(
    article: Article,
    chunk_idx: int,
    rel_start: int,
    rel_end: int,
) -> Chunk:
    """Build a :class:`Chunk` from in-article char spans -> file-relative.

    The chunk id includes the language (``{law_slug}_{lang}_{article}_{idx}``)
    so bilingual corpus pairs (e.g. ``civil_code_ar`` + ``civil_code_en``)
    produce unique ids. Without the language, the ar and en versions of the
    same article would collide on the same id (DATA_SPEC §3.5 assumes the
    format ``{law_slug}_{article}_{idx}``; the language segment is added here
    to support bilingual pairs per DATA_SPEC §1.1).
    """
    text: str = article.text[rel_start:rel_end]
    return Chunk(
        chunk_id=f"{article.law_slug}_{article.lang}_{article.number}_{chunk_idx}",
        text=text,
        law=article.law,
        article=article.number,
        lang=article.lang,
        law_slug=article.law_slug,
        chunk_idx=chunk_idx,
        char_start=article.char_start + rel_start,
        char_end=article.char_start + rel_end,
    )


def _leaf_unit_spans(
    text: str,
    target: int,
) -> list[tuple[int, int]]:
    """Char spans of leaf units, each <= ``target`` tokens.

    Honors the paragraph -> sentence -> hard boundary hierarchy (DATA_SPEC
    §3.2): a paragraph that fits the budget stays whole; an oversized paragraph
    is split into sentences; an oversized sentence is hard-split at the target
    token boundary.
    """
    units: list[tuple[int, int]] = []
    for p_start, p_end in _paragraph_spans(text):
        p_text: str = text[p_start:p_end]
        if approx_token_count(p_text) <= target:
            units.append((p_start, p_end))
            continue
        for s_start, s_end in _sentence_spans(p_text):
            s_text: str = p_text[s_start:s_end]
            if approx_token_count(s_text) <= target:
                units.append((p_start + s_start, p_start + s_end))
            else:
                units.extend(
                    _hard_split_spans(
                        s_text, target, base=p_start + s_start
                    )
                )
    return units


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Non-empty paragraph char spans, separated by blank lines (``\\n\\n``)."""
    spans: list[tuple[int, int]] = []
    i: int = 0
    n: int = len(text)
    while i < n:
        # Skip blank-line separators and leading newlines.
        while i < n and text[i] == "\n":
            i += 1
        if i >= n:
            break
        start: int = i
        # Advance until a blank line (``\n\n``) or end.
        while i < n:
            if text[i] == "\n" and i + 1 < n and text[i + 1] == "\n":
                break
            i += 1
        spans.append((start, i))
    return spans


def _sentence_spans(paragraph: str) -> list[tuple[int, int]]:
    """Sentence char spans within a paragraph.

    Each unit includes its trailing terminator and whitespace so units are
    self-delimiting (``"".join`` reproduces the paragraph).
    """
    spans: list[tuple[int, int]] = []
    for match in _SENTENCE_UNIT_RE.finditer(paragraph):
        if match.end() > match.start():
            spans.append((match.start(), match.end()))
    return spans


def _hard_split_spans(
    text: str,
    target: int,
    base: int,
) -> list[tuple[int, int]]:
    """Hard-split an oversized unit at the ``target``-token char boundary.

    Uses the token heuristic's char ratio (4 chars/token for non-Arabic, 2 for
    Arabic) to estimate a char step that yields ~``target`` tokens per piece.
    The final piece absorbs the remainder. This path is rare in legal text
    (DATA_SPEC §3.2) and only triggers for a single sentence exceeding the
    chunk budget.
    """
    if not text:
        return []
    arabic_chars: int = sum(
        1 for c in text if _ARABIC_BLOCK_START <= c <= _ARABIC_BLOCK_END
    )
    is_arabic_heavy: bool = arabic_chars > (len(text) - arabic_chars)
    chars_per_token: int = 2 if is_arabic_heavy else 4
    step: int = max(1, target * chars_per_token)
    spans: list[tuple[int, int]] = []
    pos: int = 0
    n: int = len(text)
    while pos < n:
        end: int = min(pos + step, n)
        spans.append((base + pos, base + end))
        pos = end
    return spans


def _pack_units_with_overlap(
    unit_spans: list[tuple[int, int]],
    text: str,
    target: int,
    overlap: int,
) -> list[tuple[int, int]]:
    """Greedily pack leaf units into chunks, carrying ``overlap`` tokens over.

    Each chunk spans ``[first_unit_start, last_unit_end]`` and holds <=
    ``target`` tokens. After flushing a chunk, the trailing units whose token
    sum is <= ``overlap`` are carried into the next chunk as the overlap. If a
    single unit exceeds ``overlap`` (only possible when ``overlap`` is smaller
    than one sentence), the overlap is empty for that boundary — the spec's
    64-token overlap assumes sentence-level units smaller than the overlap.
    """
    chunks: list[tuple[int, int]] = []
    buffer: list[tuple[int, int]] = []
    buffer_tokens: int = 0

    for span in unit_spans:
        unit_tokens: int = approx_token_count(text[span[0]:span[1]])
        if buffer and buffer_tokens + unit_tokens > target:
            chunks.append((buffer[0][0], buffer[-1][1]))
            buffer, buffer_tokens = _trailing_overlap(
                buffer, overlap, text
            )
        buffer.append(span)
        buffer_tokens += unit_tokens

    if buffer:
        chunks.append((buffer[0][0], buffer[-1][1]))
    return chunks


def _trailing_overlap(
    buffer: list[tuple[int, int]],
    overlap: int,
    text: str,
) -> tuple[list[tuple[int, int]], int]:
    """Return the trailing buffer units whose token sum is <= ``overlap``."""
    if overlap <= 0:
        return [], 0
    kept: list[tuple[int, int]] = []
    kept_tokens: int = 0
    for span in reversed(buffer):
        unit_tokens: int = approx_token_count(text[span[0]:span[1]])
        if kept_tokens + unit_tokens > overlap:
            break
        kept.insert(0, span)
        kept_tokens += unit_tokens
    return kept, kept_tokens

