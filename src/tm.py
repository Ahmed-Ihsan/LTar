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
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from src.state import TmHit

_ARTICLE_MARKER_RE: re.Pattern[str] = re.compile(r"^ARTICLE\s+(.+?)\s*$")
_HEADER_SEPARATOR: str = "---"


@dataclass(slots=True, frozen=True)
class TmEntry:
    """A stored bilingual sentence pair with provenance."""

    source_sentence: str
    target_sentence: str
    source_lang: str
    target_lang: str
    law_slug: str
    article: str


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


class TranslationMemory:
    """SQLite-backed legal Translation Memory with threshold-gated lookup."""

    __slots__ = ("_db_path", "_threshold", "_conn")

    def __init__(self, *, db_path: str, similarity_threshold: float = 0.98) -> None:
        self._db_path: str = db_path
        self._threshold: float = similarity_threshold
        self._conn: sqlite3.Connection = sqlite3.connect(db_path)
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
        self._conn.commit()

    def build_from_corpus(self, corpus_dir: Path) -> None:
        """Build the TM by aligning ar/en article pairs. Idempotent rebuild."""
        self._conn.execute("DELETE FROM tm_entries")
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
        self._conn.commit()

    def lookup(self, sentence: str, direction: str) -> TmHit | None:
        """Look up a source sentence; return a TmHit if above threshold."""
        source_lang: str = direction.split("-")[0]
        rows = self._conn.execute(
            "SELECT source_sentence, target_sentence FROM tm_entries "
            "WHERE source_lang = ?",
            (source_lang,),
        ).fetchall()

        best_ratio: float = 0.0
        best_source: str = ""
        best_target: str = ""
        for source_sentence, target_sentence in rows:
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

    def list_all(self) -> list[dict[str, str]]:
        """Return all entries as dicts (for testing / inspection)."""
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

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()
