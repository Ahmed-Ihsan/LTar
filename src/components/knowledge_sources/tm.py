"""Legal Translation Memory (TM) — sentence-level bilingual lookup.

Single responsibility: build a SQLite TM from aligned ar/en corpus article
pairs, and look up source sentences with a similarity threshold. Sentences
at or above the threshold return a stored target translation directly,
bypassing the LLM (spec §5). Below the threshold, lookup returns None and
the sentence goes to the LLM.

The TM is built once from ``data/corpus`` by aligning articles by their
``ARTICLE N`` marker across ar/en file pairs with the same law slug. The
similarity metric is ``difflib.SequenceMatcher.ratio`` (stdlib, no
dependencies). The threshold (default 0.98) is non-negotiable per the spec
safety rules: a near-match with a critical legal difference is worse than
a slow LLM call.

Lookup uses a **two-stage algorithm** (trigram index → SequenceMatcher):
1. Extract character trigrams from the query and find the top-K entries
   that share the most trigrams (fast SQL query with an index).
2. Run ``SequenceMatcher.ratio`` only on those K candidates.

This scales to millions of entries (e.g. MultiUN's 9.7M pairs) without the
O(n) cost of comparing against every row.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import weakref
from difflib import SequenceMatcher
from pathlib import Path

from src.components.knowledge_sources.models import TmEntry
from src.components.translation_pipeline.models import TmHit

_ARTICLE_MARKER_RE: re.Pattern[str] = re.compile(r"^ARTICLE\s+(.+?)\s*$")
_HEADER_SEPARATOR: str = "---"

# Two-stage lookup: after the trigram filter, verify at most this many
# candidates with SequenceMatcher. 50 is enough to catch near-matches while
# keeping the verification stage fast (50 × SequenceMatcher ≈ <5ms).
_MAX_CANDIDATES: int = 50


def _parse_articles(file_path: Path) -> dict[str, str]:
    """Parse a corpus file into {article_number: article_body} pairs."""
    text: str = file_path.read_text(encoding="utf-8")
    lines: list[str] = text.splitlines()
    articles: dict[str, str] = {}
    current_article: str | None = None
    body_lines: list[str] = []
    past_header: bool = False

    for line in lines:
        if not past_header:
            if line.strip() == _HEADER_SEPARATOR:
                past_header = True
            continue
        marker_match: re.Match[str] | None = _ARTICLE_MARKER_RE.match(line.strip())
        if marker_match is not None:
            if current_article is not None:
                articles[current_article] = "\n".join(body_lines).strip()
            current_article = marker_match.group(1).strip()
            body_lines = []
        elif current_article is not None:
            body_lines.append(line)

    if current_article is not None:
        articles[current_article] = "\n".join(body_lines).strip()
    return articles


def _law_slug_from_filename(filename: str) -> str:
    """civil_code_ar.txt -> civil_code"""
    stem: str = Path(filename).stem
    for suffix in ("_ar", "_en"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


def _lang_from_filename(filename: str) -> str:
    stem: str = Path(filename).stem
    if stem.endswith("_ar"):
        return "ar"
    if stem.endswith("_en"):
        return "en"
    return ""


def _align_corpus(corpus_dir: Path) -> list[TmEntry]:
    """Align ar/en article pairs from the corpus directory."""
    files: list[Path] = sorted(corpus_dir.glob("*.txt"))
    by_slug: dict[str, dict[str, dict[str, str]]] = {}

    for f in files:
        lang: str = _lang_from_filename(f.name)
        if lang not in ("ar", "en"):
            continue
        slug: str = _law_slug_from_filename(f.name)
        if slug not in by_slug:
            by_slug[slug] = {}
        by_slug[slug][lang] = _parse_articles(f)

    entries: list[TmEntry] = []
    for slug, langs in by_slug.items():
        ar_articles: dict[str, str] = langs.get("ar", {})
        en_articles: dict[str, str] = langs.get("en", {})
        for article_num, ar_body in ar_articles.items():
            en_body: str | None = en_articles.get(article_num)
            if en_body is None or not ar_body or not en_body:
                continue
            entries.append(TmEntry(
                source_sentence=ar_body, target_sentence=en_body,
                source_lang="ar", target_lang="en",
                law_slug=slug, article=article_num,
            ))
            entries.append(TmEntry(
                source_sentence=en_body, target_sentence=ar_body,
                source_lang="en", target_lang="ar",
                law_slug=slug, article=article_num,
            ))
    return entries


def _extract_trigrams(text: str) -> set[str]:
    """Extract the set of character trigrams from ``text``.

    Padded with leading/trailing spaces so short words still produce
    meaningful trigrams. Whitespace is collapsed to single spaces.
    """
    normalized: str = re.sub(r"\s+", " ", text.strip().lower())
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    padded: str = f" {normalized} "
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


class TranslationMemory:
    """SQLite-backed legal Translation Memory with threshold-gated lookup.

    Uses a two-stage lookup: a character-trigram index filters candidates
    fast, then ``SequenceMatcher`` verifies only the top-K. This scales to
    millions of entries without O(n) comparisons.
    """

    __slots__ = ("_db_path", "_threshold", "_conn", "_lock", "__weakref__")

    def __init__(self, *, db_path: str, similarity_threshold: float = 0.98) -> None:
        self._db_path: str = db_path
        self._threshold: float = similarity_threshold
        self._lock = threading.RLock()
        # check_same_thread=False is required because the TM is shared across
        # threads (e.g. CLI batch + UI). The RLock above serializes all access
        # so the connection is never used concurrently.
        self._conn: sqlite3.Connection = sqlite3.connect(
            db_path, check_same_thread=False
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tm_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_sentence TEXT NOT NULL,
                target_sentence TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                law_slug TEXT NOT NULL,
                article TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tm_trigrams (
                trigram TEXT NOT NULL,
                entry_id INTEGER NOT NULL,
                source_lang TEXT NOT NULL,
                FOREIGN KEY (entry_id) REFERENCES tm_entries(id)
            )
            """
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_trigram_lang "
            "ON tm_trigrams(trigram, source_lang)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entry_id "
            "ON tm_trigrams(entry_id)"
        )
        self._conn.commit()
        weakref.finalize(self, self._close_impl)

    def build_from_corpus(self, corpus_dir: Path) -> None:
        """Build the TM by aligning ar/en article pairs. Idempotent rebuild."""
        with self._lock:
            self._conn.execute("DELETE FROM tm_entries")
            self._conn.execute("DELETE FROM tm_trigrams")
            entries: list[TmEntry] = _align_corpus(corpus_dir)
            self._conn.executemany(
                """
                INSERT INTO tm_entries
                    (source_sentence, target_sentence, source_lang,
                     target_lang, law_slug, article)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(e.source_sentence, e.target_sentence, e.source_lang,
                  e.target_lang, e.law_slug, e.article) for e in entries],
            )
            self._build_trigram_index()
            self._conn.commit()

    def _build_trigram_index(self) -> None:
        """Build the trigram index from all entries in ``tm_entries``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, source_sentence, source_lang FROM tm_entries"
            ).fetchall()
            trigram_rows: list[tuple[str, int, str]] = []
            for entry_id, sentence, lang in rows:
                for trigram in _extract_trigrams(sentence):
                    trigram_rows.append((trigram, entry_id, lang))
            self._conn.executemany(
                "INSERT INTO tm_trigrams (trigram, entry_id, source_lang) VALUES (?, ?, ?)",
                trigram_rows,
            )

    def build_from_parallel(
        self, pairs: list[tuple[str, str, str, str]],
    ) -> None:
        """Build the TM from pre-aligned parallel sentence pairs.

        Each pair is ``(source_sentence, target_sentence, source_lang,
        target_lang)``. Used by external corpus importers (e.g. MultiUN).
        Idempotent: clears all existing entries first.
        """
        with self._lock:
            self._conn.execute("DELETE FROM tm_entries")
            self._conn.execute("DELETE FROM tm_trigrams")
            self._conn.executemany(
                """
                INSERT INTO tm_entries
                    (source_sentence, target_sentence, source_lang,
                     target_lang, law_slug, article)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(s, t, sl, tl, "external", "") for s, t, sl, tl in pairs],
            )
            self._build_trigram_index()
            self._conn.commit()

    def add_parallel(
        self, pairs: list[tuple[str, str, str, str]],
    ) -> int:
        """Add parallel sentence pairs to the TM without clearing existing entries.

        Non-destructive counterpart to :meth:`build_from_parallel`. Inserts
        new entries and augments the trigram index. Used to merge multiple
        corpora (e.g. add MultiUN entries to an existing Iraqi-law TM).
        Returns the number of pairs added.
        """
        if not pairs:
            return 0
        with self._lock:
            self._conn.executemany(
                """
                INSERT INTO tm_entries
                    (source_sentence, target_sentence, source_lang,
                     target_lang, law_slug, article)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [(s, t, sl, tl, "external", "") for s, t, sl, tl in pairs],
            )
            # Build trigram index only for the newly inserted rows.
            rows = self._conn.execute(
                "SELECT id, source_sentence, source_lang FROM tm_entries "
                "ORDER BY id DESC LIMIT ?", (len(pairs),),
            ).fetchall()
            trigram_rows: list[tuple[str, int, str]] = []
            for entry_id, sentence, lang in rows:
                for trigram in _extract_trigrams(sentence):
                    trigram_rows.append((trigram, entry_id, lang))
            self._conn.executemany(
                "INSERT INTO tm_trigrams (trigram, entry_id, source_lang) VALUES (?, ?, ?)",
                trigram_rows,
            )
            self._conn.commit()
            return len(pairs)

    def _trigram_candidates(
        self, query_trigrams: set[str], source_lang: str
    ) -> list[int]:
        """Stage 1: fast trigram-based candidate filtering."""
        with self._lock:
            placeholders: str = ",".join("?" * len(query_trigrams))
            candidates = self._conn.execute(
                f"""
                SELECT entry_id, COUNT(*) AS shared
                FROM tm_trigrams
                WHERE source_lang = ? AND trigram IN ({placeholders})
                GROUP BY entry_id
                ORDER BY shared DESC
                LIMIT ?
                """,
                (source_lang, *query_trigrams, _MAX_CANDIDATES),
            ).fetchall()
            return [c[0] for c in candidates]

    def _full_scan_candidates(
        self, source_lang: str
    ) -> tuple[list[int], dict[int, tuple[str, str]]]:
        """Fallback: full scan when the trigram index is empty (old DB)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, source_sentence, target_sentence FROM tm_entries "
                "WHERE source_lang = ?",
                (source_lang,),
            ).fetchall()
            candidate_ids: list[int] = [r[0] for r in rows]
            candidate_map: dict[int, tuple[str, str]] = {
                r[0]: (r[1], r[2]) for r in rows
            }
            return candidate_ids, candidate_map

    def _load_candidate_map(
        self, candidate_ids: list[int]
    ) -> dict[int, tuple[str, str]]:
        """Load source/target sentences for the given candidate IDs."""
        with self._lock:
            placeholders_ids: str = ",".join("?" * len(candidate_ids))
            rows = self._conn.execute(
                f"SELECT id, source_sentence, target_sentence FROM tm_entries "
                f"WHERE id IN ({placeholders_ids})",
                candidate_ids,
            ).fetchall()
            return {r[0]: (r[1], r[2]) for r in rows}

    def _verify_candidates(
        self,
        sentence: str,
        candidate_ids: list[int],
        candidate_map: dict[int, tuple[str, str]],
    ) -> TmHit | None:
        """Stage 2: precise SequenceMatcher verification on candidates only."""
        best_ratio: float = 0.0
        best_source: str = ""
        best_target: str = ""
        for cid in candidate_ids:
            pair = candidate_map.get(cid)
            if pair is None:
                continue
            source_sentence, target_sentence = pair
            ratio: float = SequenceMatcher(None, sentence, source_sentence).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_source = source_sentence
                best_target = target_sentence

        if best_ratio < self._threshold:
            return None

        return TmHit(
            source_sentence=best_source,
            target_sentence=best_target,
            similarity=best_ratio,
            char_start=0,
            char_end=len(sentence),
        )

    def lookup(self, sentence: str, direction: str) -> TmHit | None:
        """Look up a source sentence; return a TmHit if above threshold.

        Two-stage: trigram index filters to top-K candidates, then
        ``SequenceMatcher`` verifies only those. Falls back to full scan
        if the trigram index is empty (backward compat with old DBs).
        """
        source_lang: str = direction.split("-")[0]
        query_trigrams: set[str] = _extract_trigrams(sentence)
        if not query_trigrams:
            return None

        candidate_ids: list[int] = self._trigram_candidates(
            query_trigrams, source_lang
        )

        if not candidate_ids:
            # Fallback: no trigram index (old DB) → full scan.
            candidate_ids, candidate_map = self._full_scan_candidates(source_lang)
        else:
            candidate_map = self._load_candidate_map(candidate_ids)

        return self._verify_candidates(sentence, candidate_ids, candidate_map)

    def list_all(self) -> list[dict[str, str]]:
        """Return all entries as dicts (for testing / inspection)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT source_sentence, target_sentence, source_lang, "
                "target_lang, law_slug, article FROM tm_entries"
            ).fetchall()
            return [
                {"source_sentence": r[0], "target_sentence": r[1],
                 "source_lang": r[2], "target_lang": r[3],
                 "law_slug": r[4], "article": r[5]}
                for r in rows
            ]

    def _close_impl(self) -> None:
        """Idempotent close — safe to call from both ``close()`` and the
        ``weakref`` finalizer."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None  # type: ignore[assignment]

    def close(self) -> None:
        """Close the SQLite connection (idempotent)."""
        self._close_impl()

    def __enter__(self) -> TranslationMemory:
        return self

    def __exit__(self, *exc: object) -> None:
        self._close_impl()
