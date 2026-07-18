"""Glossary loading, normalization, and exact-match scanning.

Single responsibility (per ARCHITECTURE.md / engineering-principles §1.1):
load glossary JSON files, normalize Arabic/English terms, build the SQLite
exact-match index, and scan source text for glossary hits with
longest-match-first and conflict resolution per DATA_SPEC.md §2.4.

This module is the single source of truth for normalization
(``normalize_arabic`` / ``normalize_english``) and glossary scanning
(``scan_glossary_hits``) — no other module may inline these (DRY,
engineering-principles §2.1.2).

Implemented in Phase 2 (tasks 2.1.x).
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from src.components.knowledge_sources.models import Lang, Term
from src.components.translation_pipeline.exceptions import (
    GlossaryConflictError,
    GlossaryError,
    GlossaryValidationError,
)

try:
    import ahocorasick

    _HAS_AHOCORASICK = True
except ImportError:
    _HAS_AHOCORASICK = False

if TYPE_CHECKING:
    from ahocorasick import Automaton

logger = logging.getLogger(__name__)

__all__ = [
    "GlossaryConflictError",
    "GlossaryError",
    "GlossaryHit",
    "GlossaryIndex",
    "GlossaryValidationError",
    "Lang",
    "Term",
    "build_sqlite_index",
    "load_glossary_file",
    "load_glossary_files",
    "load_glossary_index",
    "normalize",
    "normalize_arabic",
    "normalize_english",
    "scan_glossary_hits",
]

# Arabic diacritics (tashkeel) and tatweel, used by normalization and by the
# diacritic-tolerant scan pattern. Kept here as the single source of truth.
_ARABIC_DIACRITICS_RE: re.Pattern[str] = re.compile(r"[\u064B-\u0652]")
_ARABIC_TATWEEL: str = "\u0640"  # ـ
_ARABIC_ALEF_VARIANTS_RE: re.Pattern[str] = re.compile(r"[أإآ]")
_ARABIC_ALIF_MAQSURA: str = "ى"  # ى → ي

# Reverse mapping: normalized character → all original characters that
# normalize to it. Used by ``_diacritic_tolerant_pattern`` so the regex
# (built from the normalized form) matches Alef variants and Alif Maqsura
# in the *original* (un-normalized) text.
_ALEF: str = "\u0627"  # ا
_ALEF_HAMZA_ABOVE: str = "\u0623"  # أ
_ALEF_HAMZA_BELOW: str = "\u0625"  # إ
_ALEF_MADDA: str = "\u0622"  # آ
_YA: str = "\u064A"  # ي
_NORM_VARIANT_MAP: dict[str, str] = {
    _ALEF: f"{_ALEF}{_ALEF_HAMZA_ABOVE}{_ALEF_HAMZA_BELOW}{_ALEF_MADDA}",
    _YA: f"{_YA}{_ARABIC_ALIF_MAQSURA}",
}

# Characters that count as "word" letters for the FOLLOWING boundary check
# during scanning: Arabic block + Arabic Supplement + Latin letters. Diacritics
# and tatweel are intentionally excluded so a term can match across them.
_LETTER_CLASS: str = r"A-Za-z\u0600-\u06FF\u0750-\u077F"
_INTER_LETTER_NOISE: str = r"[\u064B-\u0652\u0640]*"  # diacritics + tatweel
# Set form of the inter-letter noise chars, used by the Aho-Corasick scanner to
# strip diacritics/tatweel from source text (preserving original offsets) and to
# extend a match's end past trailing noise — mirroring the regex's trailing
# ``[\u064B-\u0652\u0640]*`` quantifier.
_NOISE_CHARS: frozenset[str] = frozenset(
    chr(c) for c in range(0x064B, 0x0653)
) | {_ARABIC_TATWEEL}

# Arabic proclitic prefixes (و and, ب in/by, ل for, ف then) that may attach to
# the start of a token without making a glossary term a "substring" of a larger
# word. The PRECEDING boundary blocks any letter EXCEPT these clitics, so
# "الالتزام" still matches inside "والالتزام" while "عقد" does not match inside
# "معقد". The definite-article "ال" is handled by the following-boundary check
# (a suffixed token like "العقدة" is blocked by the trailing ة).
_ARABIC_CLITICS: str = "\u0628\u0641\u0644\u0648"  # ب ف ل و
# Letter class for the preceding lookbehind = all letters MINUS the clitics.
_PRECEDING_BLOCK_CLASS: str = (
    r"A-Za-z"
    r"\u0600-\u0627"   # before ب (U+0628)
    r"\u0629-\u0640"   # after ب, before ف (U+0641)
    r"\u0642-\u0643"   # after ف, before ل (U+0644)
    r"\u0645-\u0647"   # after ل, before و (U+0648)
    r"\u0649-\u06FF"   # after و
    r"\u0750-\u077F"   # Arabic Supplement (no clitics)
)

# Default SQLite column for the normalized lookup key (DATA_SPEC §2.3).
_TERM_TABLE: str = "glossary_terms"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class GlossaryHit:
    """A glossary term occurrence found in source text.

    ``char_start`` / ``char_end`` are offsets into the *original* (un-normalized)
    input text, so ``text[char_start:char_end]`` yields the verbatim matched
    span (including any diacritics present in the source).
    """

    source_term: str
    target_term: str
    source_lang: Lang
    target_lang: Lang
    law_ref: str
    char_start: int
    char_end: int
    article_ref: str | None
    note: str | None
    priority: int


# ---------------------------------------------------------------------------
# Normalization (DATA_SPEC §2.3) — pure functions
# ---------------------------------------------------------------------------


class Normalizer(Protocol):
    """Contract for a language-specific normalizer (OCP).

    Add new languages by registering a new adapter in ``_NORMALIZERS`` —
    no edits to ``normalize()`` required.
    """

    def normalize(self, term: str) -> str: ...


def normalize_arabic(term: str) -> str:
    """Normalize an Arabic term for indexing/lookup.

    Pure and idempotent. Strips tashkeel (diacritics) and tatweel, folds Alef
    variants (أإآ → ا) and Alif Maqsura (ى → ي). Arabic has no case.
    """
    term = _ARABIC_DIACRITICS_RE.sub("", term)
    term = term.replace(_ARABIC_TATWEEL, "")
    term = _ARABIC_ALEF_VARIANTS_RE.sub("ا", term)
    term = term.replace(_ARABIC_ALIF_MAQSURA, "ي")
    return term


def normalize_english(term: str) -> str:
    """Normalize an English term for indexing/lookup.

    Pure and idempotent. Lowercases, collapses internal whitespace runs to a
    single space, and strips trailing punctuation / whitespace.
    """
    term = term.lower()
    term = re.sub(r"\s+", " ", term).strip()
    term = re.sub(r"[.,;:!?\)\]\}\"']+$", "", term).strip()
    return term


class _ArabicNormalizer:
    """Normalizer adapter for Arabic (OCP — wraps ``normalize_arabic``)."""

    def normalize(self, term: str) -> str:
        return normalize_arabic(term)


class _EnglishNormalizer:
    """Normalizer adapter for English (OCP — wraps ``normalize_english``)."""

    def normalize(self, term: str) -> str:
        return normalize_english(term)


_NORMALIZERS: dict[str, Normalizer] = {
    "ar": _ArabicNormalizer(),
    "en": _EnglishNormalizer(),
}


def normalize(term: str, lang: Lang) -> str:
    """Dispatch to the language-appropriate normalizer via the registry."""
    normalizer: Normalizer | None = _NORMALIZERS.get(lang)
    if normalizer is None:
        raise GlossaryValidationError(f"unsupported language: {lang!r}")
    return normalizer.normalize(term)


# ---------------------------------------------------------------------------
# Validation (DATA_SPEC §2.5)
# ---------------------------------------------------------------------------

_REQUIRED_TERM_FIELDS: tuple[str, ...] = (
    "source_term",
    "source_lang",
    "target_term",
    "target_lang",
    "law_ref",
)
_REQUIRED_FILE_FIELDS: tuple[str, ...] = ("domain", "version", "last_updated")
_VALID_LANGS: frozenset[str] = frozenset({"ar", "en"})


def _validate_file_header(raw: object, file_path: Path) -> None:
    """Validate the top-level glossary-file shape (DATA_SPEC §2.5)."""
    if not isinstance(raw, dict):
        raise GlossaryValidationError(
            f"{file_path}: root is not a JSON object (got {type(raw).__name__})"
        )
    for field_name in _REQUIRED_FILE_FIELDS:
        if field_name not in raw:
            raise GlossaryValidationError(
                f"{file_path}: missing required field '{field_name}'"
            )
    terms = raw.get("terms")
    if not isinstance(terms, list) or len(terms) == 0:
        raise GlossaryValidationError(
            f"{file_path}: 'terms' must be a non-empty array"
        )


def _validate_term_entry(term_raw: object, file_path: Path, idx: int) -> dict[str, object]:
    """Validate a single term entry; return the typed dict on success."""
    if not isinstance(term_raw, dict):
        raise GlossaryValidationError(
            f"{file_path}: terms[{idx}] is not a JSON object"
        )
    for field_name in _REQUIRED_TERM_FIELDS:
        if field_name not in term_raw:
            raise GlossaryValidationError(
                f"{file_path}: terms[{idx}] missing required field '{field_name}'"
            )
    term: dict[str, object] = dict(term_raw)
    source_lang = term["source_lang"]
    target_lang = term["target_lang"]
    if source_lang not in _VALID_LANGS or target_lang not in _VALID_LANGS:
        raise GlossaryValidationError(
            f"{file_path}: terms[{idx}] source_lang/target_lang must be 'ar' or 'en'"
        )
    if source_lang == target_lang:
        raise GlossaryValidationError(
            f"{file_path}: terms[{idx}] source_lang == target_lang ('{source_lang}') "
            f"— no-op entry"
        )
    source_term = term["source_term"]
    target_term = term["target_term"]
    if not isinstance(source_term, str) or not source_term.strip():
        raise GlossaryValidationError(
            f"{file_path}: terms[{idx}] 'source_term' is empty or whitespace-only"
        )
    if not isinstance(target_term, str) or not target_term.strip():
        raise GlossaryValidationError(
            f"{file_path}: terms[{idx}] 'target_term' is empty or whitespace-only"
        )
    return term


def _check_intra_file_duplicates(
    terms: list[Term], file_path: Path
) -> None:
    """Reject duplicate (source_term_norm, source_lang, target_lang) in one file."""
    seen: dict[tuple[str, Lang, Lang], str] = {}
    for term in terms:
        if term.file_path != str(file_path):
            continue
        key: tuple[str, Lang, Lang] = (
            term.source_term_norm,
            term.source_lang,
            term.target_lang,
        )
        if key in seen:
            raise GlossaryConflictError(
                f"{file_path}: duplicate term '{term.source_term}' "
                f"(norm='{term.source_term_norm}', {term.source_lang}->"
                f"{term.target_lang}) conflicts with '{seen[key]}'"
            )
        seen[key] = term.source_term


# ---------------------------------------------------------------------------
# Loading (DATA_SPEC §2.1 / §2.5)
# ---------------------------------------------------------------------------


def _build_term(
    term_raw: dict[str, object],
    domain: str,
    file_path: Path,
    file_order: int,
) -> Term:
    """Construct a validated, normalized :class:`Term` from a raw entry."""
    source_lang: Lang = cast(Lang, term_raw["source_lang"])
    source_term: str = str(term_raw["source_term"])
    source_term_norm: str = normalize(source_term, source_lang)
    return Term.from_dict(
        term_raw,
        domain=domain,
        file_path=str(file_path),
        file_order=file_order,
        source_term_norm=source_term_norm,
    )


def load_glossary_file(file_path: Path) -> list[Term]:
    """Load and validate a single glossary JSON file into :class:`Term` objects.

    Raises:
        GlossaryValidationError: on a missing/invalid field or no-op entry.
        GlossaryConflictError: on an intra-file duplicate tuple.
    """
    try:
        raw_text: str = file_path.read_text(encoding="utf-8")
    except OSError as e:
        raise GlossaryError(f"cannot read glossary file {file_path}: {e}") from e
    try:
        raw: object = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise GlossaryValidationError(
            f"{file_path}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}"
        ) from e

    _validate_file_header(raw, file_path)
    raw_dict: dict[str, object] = cast(dict[str, object], raw)
    domain: str = str(raw_dict["domain"])
    terms_raw: list[object] = list(cast(list[object], raw_dict["terms"]))

    terms: list[Term] = []
    for idx, term_raw in enumerate(terms_raw):
        validated: dict[str, object] = _validate_term_entry(term_raw, file_path, idx)
        terms.append(_build_term(validated, domain, file_path, file_order=idx))

    _check_intra_file_duplicates(terms, file_path)
    return terms


def load_glossary_files(glob_pattern: str | Path) -> list[Term]:
    """Load all glossary JSON files matching ``glob_pattern`` (e.g.
    ``data/glossary/*.json``) into a flat, deterministic list of
    :class:`Term` objects.

    Files are processed in sorted path order for deterministic ``file_order``
    provenance. Validation errors abort the whole load (no partial state) per
    DATA_SPEC §4 ("does not write partial state").
    """
    base: Path = Path(glob_pattern)
    parent: Path = base.parent if base.parent != Path("") else Path(".")
    pattern: str = base.name
    file_paths: list[Path] = sorted(parent.glob(pattern))

    all_terms: list[Term] = []
    global_order: int = 0
    for file_path in file_paths:
        file_terms: list[Term] = load_glossary_file(file_path)
        # Re-stamp file_order with a global, cross-file deterministic counter.
        for term in file_terms:
            all_terms.append(replace(term, file_order=global_order))
            global_order += 1
    # Append reverse (bidirectional) entries derived from the explicit terms so
    # the glossary grounds both directions equally. Explicit entries always win
    # (they keep their lower file_order; _resolve_conflict §2.4 tie-breaks on
    # priority → length → law_ref → earliest file_order). A reverse is only
    # derived when no explicit entry already covers that (source, target) pair.
    all_terms.extend(_derive_reverse_terms(all_terms, start_order=global_order))
    return all_terms


def _derive_reverse_terms(terms: list[Term], *, start_order: int = 0) -> list[Term]:
    """Return reverse entries for terms whose reverse is not already present.

    For an explicit term ``(src, sl) -> (tgt, tl)``, the reverse is
    ``(tgt, tl) -> (src, sl)`` reusing the same ``law_ref``, ``domain``,
    ``article_ref``, ``note``, and ``priority``. This is correct by
    construction — it reuses the authored pair rather than inventing a new
    translation. Explicit entries (loaded from JSON) always take precedence:
    if an explicit entry already covers the reverse direction, no derived
    entry is emitted. Derived entries are deduplicated among themselves and
    stamped with ``file_order`` starting at ``start_order`` (so they sort
    after every explicit entry and lose §2.4 tie-breaks against them).
    """
    explicit_keys: set[tuple[str, str, str]] = {
        (t.source_term_norm, t.source_lang, t.target_lang)
        for t in terms
    }
    derived: list[Term] = []
    seen: set[tuple[str, str, str]] = set()
    order: int = start_order
    for t in terms:
        rev_src_term: str = t.target_term
        rev_src_lang: Lang = t.target_lang
        rev_tgt_term: str = t.source_term
        rev_tgt_lang: Lang = t.source_lang
        rev_norm: str = normalize(rev_src_term, rev_src_lang)
        key: tuple[str, str, str] = (rev_norm, rev_src_lang, rev_tgt_lang)
        if key in explicit_keys or key in seen:
            continue
        seen.add(key)
        derived.append(
            Term(
                source_term=rev_src_term,
                source_lang=rev_src_lang,
                target_term=rev_tgt_term,
                target_lang=rev_tgt_lang,
                law_ref=t.law_ref,
                domain=t.domain,
                source_term_norm=rev_norm,
                file_path=t.file_path,
                file_order=order,
                article_ref=t.article_ref,
                note=t.note,
                priority=t.priority,
            )
        )
        order += 1
    return derived


# ---------------------------------------------------------------------------
# SQLite index (DATA_SPEC §2.3)
# ---------------------------------------------------------------------------


def build_sqlite_index(terms: list[Term], db_path: str | Path) -> None:
    """Write ``terms`` into the SQLite exact-match index at ``db_path``.

    The table is recreated (DROP IF EXISTS + CREATE) so re-ingestion is
    idempotent. ``source_term_norm`` is indexed for O(log n) lookup.
    """
    path: Path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()  # idempotent rebuild; never accumulate stale rows
    with sqlite3.connect(str(path)) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.executemany(_INSERT_TERM_SQL, _term_rows(terms))
        conn.execute(_CREATE_NORM_INDEX_SQL)
        conn.commit()


def load_glossary_index(db_path: str | Path | None = None) -> GlossaryIndex:
    """Load a :class:`GlossaryIndex` from the SQLite DB at ``db_path``.

    Raises:
        GlossaryError: if the DB is missing, unreadable, or has no terms.
    """
    path: Path = Path(db_path) if db_path is not None else _DEFAULT_GLOSSARY_DB
    if not path.is_file():
        raise GlossaryError(f"glossary SQLite DB not found: {path}")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows: list[sqlite3.Row] = list(
                conn.execute(f"SELECT * FROM {_TERM_TABLE} ORDER BY file_order")
            )
    except sqlite3.DatabaseError as e:
        raise GlossaryError(f"cannot read glossary DB {path}: {e}") from e
    if not rows:
        raise GlossaryError(f"glossary DB {path} contains no terms")
    return GlossaryIndex([_row_to_term(row) for row in rows])


def _term_rows(terms: list[Term]) -> list[tuple[object, ...]]:
    """Project ``terms`` into the column tuple expected by the insert SQL."""
    return [
        (
            t.domain,
            t.source_term,
            t.source_term_norm,
            t.source_lang,
            t.target_term,
            t.target_lang,
            t.law_ref,
            t.article_ref,
            t.note,
            t.priority,
            t.file_path,
            t.file_order,
        )
        for t in terms
    ]


def _row_to_term(row: sqlite3.Row) -> Term:
    """Reconstruct a :class:`Term` from a SQLite row."""
    return Term(
        source_term=row["source_term"],
        source_lang=row["source_lang"],
        target_term=row["target_term"],
        target_lang=row["target_lang"],
        law_ref=row["law_ref"],
        domain=row["domain"],
        source_term_norm=row["source_term_norm"],
        file_path=row["file_path"],
        file_order=row["file_order"],
        article_ref=row["article_ref"],
        note=row["note"],
        priority=row["priority"],
    )


_CREATE_TABLE_SQL: str = f"""
CREATE TABLE {_TERM_TABLE} (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    domain           TEXT    NOT NULL,
    source_term      TEXT    NOT NULL,
    source_term_norm TEXT    NOT NULL,
    source_lang      TEXT    NOT NULL,
    target_term      TEXT    NOT NULL,
    target_lang      TEXT    NOT NULL,
    law_ref          TEXT    NOT NULL,
    article_ref      TEXT,
    note             TEXT,
    priority         INTEGER NOT NULL DEFAULT 0,
    file_path        TEXT    NOT NULL,
    file_order       INTEGER NOT NULL
)
""".strip()

_INSERT_TERM_SQL: str = (
    f"INSERT INTO {_TERM_TABLE} "
    "(domain, source_term, source_term_norm, source_lang, target_term, "
    "target_lang, law_ref, article_ref, note, priority, file_path, file_order) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_CREATE_NORM_INDEX_SQL: str = (
    f"CREATE INDEX idx_{_TERM_TABLE}_norm "
    f"ON {_TERM_TABLE} (source_term_norm, source_lang)"
)


# ---------------------------------------------------------------------------
# Scanning (DATA_SPEC §2.4) — longest-match-first + conflict resolution
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GlossaryIndex:
    """In-memory exact-match index over a set of :class:`Term` objects.

    Builds one Aho-Corasick automaton per source language (when ``pyahocorasick``
    is installed) for O(text) scanning, falling back to a diacritic-tolerant
    regex alternation otherwise. Both paths share the same longest-match-first
    and conflict-resolution semantics (DATA_SPEC §2.4). Stateful by design
    (clean-code §2.4): the compiled automata/patterns and lookup maps are the
    managed state.
    """

    terms: list[Term]
    _by_lang: dict[Lang, _LangIndex] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        """Compile per-language automata/regexes and normalized-form lookup maps."""
        grouped: dict[Lang, list[Term]] = {"ar": [], "en": []}
        for term in self.terms:
            grouped[term.source_lang].append(term)
        self._by_lang = {
            lang: _LangIndex.build(terms, lang) for lang, terms in grouped.items()
        }

    def scan(self, text: str, lang: Lang) -> list[GlossaryHit]:
        """Return all glossary hits in ``text`` for source language ``lang``.

        Longest-match-first: at each start position the longest viable term
        wins. Same-span conflicts are resolved per DATA_SPEC §2.4 (priority →
        longer verbatim term → more specific law_ref → earliest file order).
        Hits are returned in ascending ``char_start`` order.
        """
        lang_index: _LangIndex | None = self._by_lang.get(lang)
        if lang_index is None or lang_index.pattern is None:
            return []
        if _HAS_AHOCORASICK and lang_index.automaton is not None:
            return _scan_ahocorasick(text, lang, lang_index)
        return _scan_regex(text, lang, lang_index)


@dataclass(slots=True)
class _LangIndex:
    """Per-language compiled scan state."""

    pattern: re.Pattern[str] | None
    terms_by_norm: dict[str, list[Term]]
    automaton: Automaton | None = None

    @classmethod
    def build(cls, terms: list[Term], lang: Lang = "ar") -> _LangIndex:
        """Compile the alternation regex, the norm → terms lookup map, and
        (when available) an Aho-Corasick automaton over the normalized forms.

        English terms are normalized to lowercase, so the regex is compiled
        with :data:`re.IGNORECASE` to match capitalized source text (e.g.
        "Court of First Instance"). Arabic has no case and is unaffected.
        The regex is always compiled so it is available as a fallback when
        ``pyahocorasick`` is not installed.
        """
        if not terms:
            return cls(pattern=None, terms_by_norm={})
        terms_by_norm: dict[str, list[Term]] = {}
        for term in terms:
            terms_by_norm.setdefault(term.source_term_norm, []).append(term)
        # Longest normalized form first so the regex tries the longest term at
        # each position before any shorter substring alternative.
        ordered_norms: list[str] = sorted(
            terms_by_norm.keys(), key=lambda n: len(n), reverse=True
        )
        alternation: str = "|".join(
            _diacritic_tolerant_pattern(n) for n in ordered_norms
        )
        flags: int = re.IGNORECASE if lang == "en" else 0
        pattern: re.Pattern[str] = re.compile(alternation, flags)
        automaton: Automaton | None = None
        if _HAS_AHOCORASICK:
            automaton = ahocorasick.Automaton()
            for norm in terms_by_norm:
                automaton.add_word(norm, norm)
            automaton.make_automaton()
        return cls(pattern=pattern, terms_by_norm=terms_by_norm, automaton=automaton)


def _diacritic_tolerant_pattern(norm: str) -> str:
    """Build a regex fragment matching ``norm`` while tolerating intervening
    Arabic diacritics/tatweel, anchored by word boundaries (letter class).

    Characters that were folded during normalization (Alef variants أإآ→ا,
    Alif Maqsura ى→ي) are emitted as character classes so the regex matches
    the *original* (un-normalized) text, not just the normalized form.
    """
    escaped_chars: list[str] = []
    for ch in norm:
        variants: str | None = _NORM_VARIANT_MAP.get(ch)
        if variants is not None:
            escaped_chars.append(f"[{re.escape(variants)}]")
        else:
            escaped_chars.append(re.escape(ch))
    inner: str = _INTER_LETTER_NOISE.join(escaped_chars)
    # Preceding: block a letter unless it is an Arabic proclitic (و ب ل ف).
    boundary_pre: str = rf"(?<![{_PRECEDING_BLOCK_CLASS}])"
    # Following: block any letter (prevents matching a stem inside a suffixed
    # token, e.g. "عقد" inside "العقدة").
    boundary_post: str = rf"(?![{_LETTER_CLASS}])"
    return rf"{boundary_pre}{inner}{_INTER_LETTER_NOISE}{boundary_post}"


def _scan_regex(text: str, lang: Lang, lang_index: _LangIndex) -> list[GlossaryHit]:
    """Regex-based scan (fallback when ``pyahocorasick`` is unavailable)."""
    assert lang_index.pattern is not None
    hits: list[GlossaryHit] = []
    for match in lang_index.pattern.finditer(text):
        span_text: str = match.group(0)
        norm: str = normalize(span_text, lang)
        candidates: list[Term] = lang_index.terms_by_norm.get(norm, [])
        if not candidates:
            continue
        winner: Term = _resolve_conflict(candidates)
        hits.append(_term_to_hit(winner, match.start(), match.end()))
    return hits


def _scan_ahocorasick(
    text: str, lang: Lang, lang_index: _LangIndex
) -> list[GlossaryHit]:
    """Aho-Corasick scan that reproduces the regex matcher's results.

    The automaton runs over a normalized copy of ``text`` (diacritics/tatweel
    stripped, Alef variants folded, lowercased for English) so its literal
    substring matches line up with the regex's diacritic-tolerant, variant-
    folding patterns. A position map restores original-text offsets, trailing
    inter-letter noise is re-consumed, and the same preceding/following letter
    boundaries + longest-match-first greedy selection as the regex are applied.
    """
    assert lang_index.automaton is not None
    norm_text, pos_map = _normalize_text_for_ac(text, lang)
    raw: list[tuple[int, int, str]] = []
    for end_idx, norm in lang_index.automaton.iter(norm_text):
        start_idx: int = end_idx - len(norm) + 1
        raw.append((start_idx, end_idx + 1, norm))
    # Longest match first at each start position (mirrors the regex's
    # longest-first alternation), then left-to-right non-overlapping selection
    # (mirrors ``re.finditer`` consumption).
    raw.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    hits: list[GlossaryHit] = []
    cur: int = 0
    for start_idx, end_idx, norm in raw:
        if start_idx < cur:
            continue
        orig_start: int = pos_map[start_idx]
        orig_end: int = pos_map[end_idx - 1] + 1
        while orig_end < len(text) and text[orig_end] in _NOISE_CHARS:
            orig_end += 1
        if not _check_boundaries(text, orig_start, orig_end, lang):
            continue
        candidates: list[Term] = lang_index.terms_by_norm.get(norm, [])
        if not candidates:
            continue
        winner: Term = _resolve_conflict(candidates)
        hits.append(_term_to_hit(winner, orig_start, orig_end))
        cur = end_idx
    return hits


def _normalize_text_for_ac(text: str, lang: Lang) -> tuple[str, list[int]]:
    """Return a normalized copy of ``text`` plus a stripped→original index map.

    Arabic: strip diacritics/tatweel (removing chars) and fold Alef variants /
    Alif Maqsura (1:1, position-preserving) — the same folds ``normalize_arabic``
    applies to terms. English: lowercase only (1:1); whitespace/punctuation
    handling lives in the term normalization, and the regex matches the original
    spacing, so the text is not whitespace-collapsed here.
    """
    if lang == "en":
        return text.lower(), list(range(len(text)))
    chars: list[str] = []
    pos_map: list[int] = []
    for i, ch in enumerate(text):
        if ch in _NOISE_CHARS:
            continue
        if ch in (_ALEF_HAMZA_ABOVE, _ALEF_HAMZA_BELOW, _ALEF_MADDA):
            ch = _ALEF
        elif ch == _ARABIC_ALIF_MAQSURA:
            ch = _YA
        chars.append(ch)
        pos_map.append(i)
    return "".join(chars), pos_map


def _is_letter(ch: str) -> bool:
    """True if ``ch`` is in the scan letter class (Arabic block + Latin)."""
    code: int = ord(ch)
    if ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
        return True
    return 0x0600 <= code <= 0x06FF or 0x0750 <= code <= 0x077F


def _check_boundaries(text: str, orig_start: int, orig_end: int, lang: Lang) -> bool:
    """Apply the regex's preceding/following letter-boundary lookarounds.

    Preceding: block any letter except Arabic proclitics (و ب ل ف). Following:
    block any letter (prevents a stem matching inside a suffixed token).
    """
    if orig_start > 0:
        prev: str = text[orig_start - 1]
        if _is_letter(prev) and (lang != "ar" or prev not in _ARABIC_CLITICS):
            return False
    if orig_end < len(text):
        nxt: str = text[orig_end]
        if _is_letter(nxt):
            return False
    return True


def _resolve_conflict(candidates: list[Term]) -> Term:
    """Pick the winning term among same-span matches per DATA_SPEC §2.4."""
    # 1. Higher priority wins.
    max_priority: int = max(t.priority for t in candidates)
    by_priority: list[Term] = [t for t in candidates if t.priority == max_priority]
    if len(by_priority) == 1:
        return by_priority[0]
    # 2. Longer verbatim source_term wins.
    max_len: int = max(len(t.source_term) for t in by_priority)
    by_len: list[Term] = [t for t in by_priority if len(t.source_term) == max_len]
    if len(by_len) == 1:
        return by_len[0]
    # 3. More specific (non-null) law_ref wins.
    with_law_ref: list[Term] = [t for t in by_len if t.law_ref]
    if len(with_law_ref) == 1:
        return with_law_ref[0]
    pool: list[Term] = with_law_ref if with_law_ref else by_len
    # 4. Earliest JSON file order wins (deterministic).
    return min(pool, key=lambda t: t.file_order)


def _term_to_hit(term: Term, char_start: int, char_end: int) -> GlossaryHit:
    """Project a :class:`Term` plus offsets into a :class:`GlossaryHit`."""
    return GlossaryHit(
        source_term=term.source_term,
        target_term=term.target_term,
        source_lang=term.source_lang,
        target_lang=term.target_lang,
        law_ref=term.law_ref,
        char_start=char_start,
        char_end=char_end,
        article_ref=term.article_ref,
        note=term.note,
        priority=term.priority,
    )


def scan_glossary_hits(
    text: str,
    lang: Lang,
    index: GlossaryIndex | None = None,
) -> list[GlossaryHit]:
    """Scan ``text`` for glossary hits in source language ``lang``.

    If ``index`` is omitted, the default SQLite-backed index
    (``db/glossary.sqlite``) is loaded lazily. Pass an explicit ``index`` for
    deterministic unit tests that do not touch disk.
    """
    if index is None:
        index = load_glossary_index()
    return index.scan(text, lang)


# Default DB path: db/glossary.sqlite relative to the project root.
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_GLOSSARY_DB: Path = _PROJECT_ROOT / "db" / "glossary.sqlite"
