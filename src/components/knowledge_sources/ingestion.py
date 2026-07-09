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

Implemented in Phase 2 (tasks 2.2.x).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Iterator

from src.components.knowledge_sources.models import Article, Chunk, Lang
from src.components.translation_pipeline.exceptions import (
    CorpusEncodingError,
    CorpusParseError,
)

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


def _strict_utf8_lines(handle, path: Path) -> Iterator[str]:
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

    # Two-pass-on-the-fly: collect header lines until the separator, then
    # stream article bodies. Char offsets are tracked relative to the file so
    # provenance is exact without holding the whole file. UTF-8 decode errors
    # surface during iteration (errors="strict" defers them past open), so they
    # are translated by ``_strict_utf8_lines`` below.
    handle = open(path, encoding="utf-8", errors="strict", newline="")

    header_lines: list[str] = []
    header_parsed: dict[str, str] | None = None
    # char position relative to the decoded file content (chars, not bytes).
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
                if current_number is not None:
                    yield _build_article(
                        number=current_number,
                        body_lines=current_lines,
                        header=header_parsed,
                        law_slug=law_slug,
                        body_start=current_body_start,
                        body_end=char_pos,
                        file_path=file_path,
                    )
                current_number = _normalize_article_number(
                    marker_match.group(1)
                )
                current_lines = []
                # The body begins after this marker line.
                current_body_start = char_pos + line_len
            elif current_number is not None:
                current_lines.append(stripped)

            char_pos += line_len

    if header_parsed is None:
        raise CorpusParseError(
            f"{file_path}: missing header separator '{_HEADER_SEPARATOR}'"
        )
    if current_number is not None:
        yield _build_article(
            number=current_number,
            body_lines=current_lines,
            header=header_parsed,
            law_slug=law_slug,
            body_start=current_body_start,
            body_end=char_pos,
            file_path=file_path,
        )


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
        lang=lang_value,  # type: ignore[arg-type]
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


# ---------------------------------------------------------------------------
# Ingestion CLI orchestration (tasks 2.3.3, 2.3.4)
#
# The functions below are coordinators — their single responsibility is
# orchestrating the parse → chunk → embed → store pipeline and writing the
# ingestion manifest (clean-code §2.1: an orchestrator's job is coordination).
# They call into the single-source-of-truth functions defined above and in
# ``embeddings.py`` / ``retrieval.py`` / ``glossary.py`` (DRY).
# ---------------------------------------------------------------------------

import gc
import hashlib
import json
import time
from datetime import datetime, timezone

import typer

from src.config import AppConfig, load_config
from src.components.knowledge_sources.glossary import (
    GlossaryConflictError,
    GlossaryValidationError,
    build_sqlite_index,
    load_glossary_files,
)

# ``retrieval`` and ``embeddings`` are imported lazily inside the CLI functions
# to avoid a circular import: retrieval.py imports ``Chunk`` from this module at
# module level, so this module must not import retrieval at module level.
_MANIFEST_VERSION: str = "1.0.0"
_COLLECTION_NAME: str = "iraqi_laws"  # matches retrieval.DEFAULT_COLLECTION


@dataclass(slots=True)
class FileHash:
    """SHA-256 hash and size of a single input file (manifest entry)."""

    path: str
    sha256: str
    size: int


@dataclass(slots=True)
class GlossarySummary:
    """Summary of glossary ingestion for the CLI output."""

    file_count: int
    term_count: int
    conflict_count: int
    validation_error_count: int


@dataclass(slots=True)
class CorpusSummary:
    """Summary of corpus ingestion for the CLI output."""

    file_count: int
    law_count: int
    article_count: int
    chunk_count: int
    parse_error_count: int


@dataclass(slots=True)
class IngestionResult:
    """Full result of an ingestion run (glossary + corpus + manifest)."""

    glossary: GlossarySummary | None
    corpus: CorpusSummary | None
    chroma_embeddings: int
    duration_seconds: float
    file_hashes: list[FileHash]


def _sha256_file(path: Path) -> FileHash:
    """Compute the SHA-256 hash and byte size of ``path`` (streaming)."""
    h = hashlib.sha256()
    size: int = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
            size += len(block)
    return FileHash(path=str(path), sha256=h.hexdigest(), size=size)


def _hash_files(paths: list[Path]) -> list[FileHash]:
    """Hash a list of files in sorted order (deterministic)."""
    return [_sha256_file(p) for p in sorted(paths)]


def _content_hash(
    file_hashes: list[FileHash],
    term_count: int,
    chunk_count: int,
    article_count: int,
    cfg: AppConfig,
) -> str:
    """Compute a deterministic content hash over all inputs + counts + models.

    Excludes the timestamp so re-ingestion of unchanged inputs yields the same
    hash (idempotency check, TODO 2.3.4). Includes model versions so a model
    swap is detectable.
    """
    h = hashlib.sha256()
    for fh in file_hashes:
        h.update(fh.path.encode("utf-8"))
        h.update(fh.sha256.encode("utf-8"))
        h.update(str(fh.size).encode("utf-8"))
    h.update(str(term_count).encode("utf-8"))
    h.update(str(article_count).encode("utf-8"))
    h.update(str(chunk_count).encode("utf-8"))
    h.update(cfg.llm_model.encode("utf-8"))
    h.update(cfg.embed_model.encode("utf-8"))
    return h.hexdigest()


def _write_manifest(
    result: IngestionResult,
    cfg: AppConfig,
    manifest_path: Path,
) -> str:
    """Write ``data/ingestion_manifest.json`` and return the content hash.

    The manifest records file hashes, counts, model versions, and a timestamp
    (DATA_SPEC §5). The ``content_hash`` field is deterministic (excludes the
    timestamp) so idempotency can be verified by comparing it across runs.
    """
    term_count: int = result.glossary.term_count if result.glossary else 0
    chunk_count: int = result.corpus.chunk_count if result.corpus else 0
    article_count: int = result.corpus.article_count if result.corpus else 0

    content_hash: str = _content_hash(
        result.file_hashes, term_count, chunk_count, article_count, cfg
    )

    glossary_files: list[dict[str, object]] = []
    corpus_files: list[dict[str, object]] = []
    glossary_dir = _project_root() / cfg.paths.glossary_dir
    corpus_dir = _project_root() / cfg.paths.corpus_dir
    for fh in result.file_hashes:
        entry: dict[str, object] = {
            "path": fh.path,
            "sha256": fh.sha256,
            "size": fh.size,
        }
        if glossary_dir in Path(fh.path).parents or fh.path.endswith(".json"):
            glossary_files.append(entry)
        else:
            corpus_files.append(entry)

    manifest: dict[str, object] = {
        "version": _MANIFEST_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "glossary": {
            "file_count": result.glossary.file_count if result.glossary else 0,
            "term_count": term_count,
            "files": glossary_files,
        },
        "corpus": {
            "file_count": result.corpus.file_count if result.corpus else 0,
            "law_count": result.corpus.law_count if result.corpus else 0,
            "article_count": article_count,
            "chunk_count": chunk_count,
            "files": corpus_files,
        },
        "chroma": {
            "collection": _COLLECTION_NAME,
            "embeddings_written": result.chroma_embeddings,
        },
        "models": {
            "llm_model": cfg.llm_model,
            "embed_model": cfg.embed_model,
        },
        "duration_seconds": round(result.duration_seconds, 2),
    }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return content_hash


def _project_root() -> Path:
    """Return the project root (parent of the ``src`` package)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _ingest_glossary(cfg: AppConfig) -> tuple[GlossarySummary, list[FileHash]]:
    """Load glossary files into SQLite; return summary and file hashes."""
    glossary_dir: Path = _project_root() / cfg.paths.glossary_dir
    file_paths: list[Path] = sorted(glossary_dir.glob("*.json"))
    file_hashes: list[FileHash] = _hash_files(file_paths)

    conflicts: int = 0
    validation_errors: int = 0
    all_terms: list = []
    for fp in file_paths:
        try:
            terms = load_glossary_files(fp)
            all_terms.extend(terms)
        except GlossaryConflictError:
            conflicts += 1
        except GlossaryValidationError:
            validation_errors += 1

    if all_terms and conflicts == 0 and validation_errors == 0:
        db_path: Path = _project_root() / cfg.paths.glossary_db
        build_sqlite_index(all_terms, db_path)

    summary = GlossarySummary(
        file_count=len(file_paths),
        term_count=len(all_terms),
        conflict_count=conflicts,
        validation_error_count=validation_errors,
    )
    return summary, file_hashes


def _iter_corpus_chunks(
    cfg: AppConfig, limit: int | None
) -> tuple[list[Chunk], CorpusSummary, list[FileHash]]:
    """Stream-parse corpus files, chunk articles, return chunks + summary.

    Memory-bounded (offline-architecture §1.2–§1.3): articles are streamed via
    :func:`iter_articles` and chunked one at a time. Chunks are collected into a
    list only because :func:`build_chroma_collection` needs the full set for the
    atomic rebuild; for the ~2k-vector corpus this is well within budget.
    """
    corpus_dir: Path = _project_root() / cfg.paths.corpus_dir
    file_paths: list[Path] = sorted(corpus_dir.glob("*.txt"))
    file_hashes: list[FileHash] = _hash_files(file_paths)

    chunks: list[Chunk] = []
    law_slugs: set[str] = set()
    article_count: int = 0
    parse_errors: int = 0

    for fp in file_paths:
        articles_in_file: int = 0
        try:
            for article in iter_articles(fp):
                if limit is not None and articles_in_file >= limit:
                    break
                articles_in_file += 1
                article_count += 1
                law_slugs.add(article.law_slug)
                chunks.extend(
                    chunk_article(article, cfg.chunk_size, cfg.chunk_overlap)
                )
        except (CorpusParseError, CorpusEncodingError):
            parse_errors += 1

    summary = CorpusSummary(
        file_count=len(file_paths),
        law_count=len(law_slugs),
        article_count=article_count,
        chunk_count=len(chunks),
        parse_error_count=parse_errors,
    )
    return chunks, summary, file_hashes


# ---------------------------------------------------------------------------
# Orchestration: run_ingestion (shared by the ingest_app command and the
# src.cli ingest wrapper — DRY, engineering-principles §2.1)
# ---------------------------------------------------------------------------


def run_ingestion(
    cfg: AppConfig,
    *,
    glossary_only: bool = False,
    corpus_only: bool = False,
    limit: int | None = None,
) -> IngestionResult:
    """Run glossary and/or corpus ingestion and return the result.

    This is the orchestration seam between the CLI commands and the ingestion
    pipeline. Both ``src.ingestion.ingest_app`` and ``src.cli.app``'s
    ``ingest`` command call this function (DRY). Renders progress to stdout
    via ``typer.secho`` and writes the manifest. The caller is responsible
    for checking ``error_count`` and setting the exit code.
    """
    # Lazy imports to avoid circular import (retrieval imports Chunk from here).
    from src.embeddings import Embedder
    from src.components.knowledge_sources.retrieval import build_chroma_collection

    start_time: float = time.monotonic()
    all_file_hashes: list[FileHash] = []
    glossary_summary: GlossarySummary | None = None
    corpus_summary: CorpusSummary | None = None
    chroma_embeddings: int = 0

    # --- Glossary ---
    if not corpus_only:
        glossary_summary, g_hashes = _ingest_glossary(cfg)
        all_file_hashes.extend(g_hashes)
        typer.secho(
            f"[ingestion] Glossary: {glossary_summary.file_count} files, "
            f"{glossary_summary.term_count} terms loaded, "
            f"{glossary_summary.conflict_count} conflicts, "
            f"{glossary_summary.validation_error_count} validation errors.",
            fg=typer.colors.CYAN,
        )

    # --- Corpus ---
    if not glossary_only:
        chunks, corpus_summary, c_hashes = _iter_corpus_chunks(cfg, limit)
        all_file_hashes.extend(c_hashes)

        if corpus_summary.parse_error_count == 0 and chunks:
            chroma_dir: Path = _project_root() / cfg.paths.chroma_dir
            embedder = Embedder()
            chroma_embeddings = build_chroma_collection(
                chunks, chroma_dir, embedder=embedder, cfg=cfg
            )
            gc.collect()

        typer.secho(
            f"[ingestion] Corpus: {corpus_summary.law_count} laws, "
            f"{corpus_summary.article_count} articles, "
            f"{corpus_summary.chunk_count} chunks, "
            f"{corpus_summary.parse_error_count} parse errors.",
            fg=typer.colors.CYAN,
        )
        typer.secho(
            f"[ingestion] ChromaDB: collection '{_COLLECTION_NAME}' rebuilt, "
            f"{chroma_embeddings} embeddings written.",
            fg=typer.colors.CYAN,
        )

    duration: float = time.monotonic() - start_time

    # --- Manifest ---
    result = IngestionResult(
        glossary=glossary_summary,
        corpus=corpus_summary,
        chroma_embeddings=chroma_embeddings,
        duration_seconds=duration,
        file_hashes=all_file_hashes,
    )
    manifest_path: Path = _project_root() / "data" / "ingestion_manifest.json"
    content_hash: str = _write_manifest(result, cfg, manifest_path)

    typer.secho(
        f"[ingestion] Duration: {duration:.1f}s. "
        f"Manifest: {manifest_path} (content_hash={content_hash[:12]}...).",
        fg=typer.colors.CYAN,
    )
    return result


# Typer app for ``python -m src.ingestion`` (DATA_SPEC §4).
ingest_app = typer.Typer(
    add_completion=False,
    rich_markup_mode=None,
    help="Ingest glossary and corpus into SQLite + ChromaDB.",
)


@ingest_app.command()
def ingest(
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild", help="Drop existing stores and re-ingest from scratch."),
    ] = False,
    glossary_only: Annotated[
        bool,
        typer.Option("--glossary-only", help="Skip corpus; only load glossary into SQLite."),
    ] = False,
    corpus_only: Annotated[
        bool,
        typer.Option("--corpus-only", help="Skip glossary; only chunk and embed corpus."),
    ] = False,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Process only the first N articles per file (smoke test)."),
    ] = None,
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Ingest glossary and/or corpus into the local stores (DATA_SPEC §4)."""
    _ = rebuild  # run_ingestion always rebuilds atomically
    try:
        cfg: AppConfig = load_config(config_path)
    except Exception as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    result = run_ingestion(
        cfg,
        glossary_only=glossary_only,
        corpus_only=corpus_only,
        limit=limit,
    )

    error_count: int = 0
    if result.glossary:
        error_count += (
            result.glossary.conflict_count
            + result.glossary.validation_error_count
        )
    if result.corpus:
        error_count += result.corpus.parse_error_count

    if error_count > 0:
        typer.secho(
            f"\n{error_count} error(s) during ingestion.", fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)
    typer.secho("\nIngestion complete (0 errors).", fg=typer.colors.GREEN)


if __name__ == "__main__":
    ingest_app()

