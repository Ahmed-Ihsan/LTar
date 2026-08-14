"""Integration tests for the glossary SQLite index (DATA_SPEC §2.3, task 2.1.1).

Uses a real SQLite DB in a temp directory (testing-verification skill §1.1
``integration/`` layer). No LLM, no network.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.components.knowledge_sources.glossary import (
    GlossaryIndex,
    Term,
    build_sqlite_index,
    load_glossary_files,
    load_glossary_index,
    scan_glossary_hits,
)

pytestmark = pytest.mark.integration


def _two_term_file(tmp_path: Path) -> Path:
    """Write a 2-term glossary JSON file and return its path."""
    import json

    glossary_dir: Path = tmp_path / "glossary"
    glossary_dir.mkdir()
    payload: dict[str, object] = {
        "domain": "civil_code",
        "version": "1.0.0",
        "last_updated": "2026-07-01",
        "terms": [
            {
                "source_term": "عقد البيع",
                "source_lang": "ar",
                "target_term": "contract of sale",
                "target_lang": "en",
                "law_ref": "Civil Code",
                "article_ref": "148",
                "priority": 10,
            },
            {
                "source_term": "contract of sale",
                "source_lang": "en",
                "target_term": "عقد البيع",
                "target_lang": "ar",
                "law_ref": "Civil Code",
                "article_ref": "148",
                "priority": 10,
            },
        ],
    }
    path: Path = glossary_dir / "civil_code.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestSqliteRoundTrip:
    def test_load_and_query_both_terms(self, tmp_path: Path) -> None:
        file_path = _two_term_file(tmp_path)
        terms: list[Term] = load_glossary_files(file_path.parent / "*.json")
        assert len(terms) == 2

        db_path: Path = tmp_path / "db" / "glossary.sqlite"
        build_sqlite_index(terms, db_path)
        assert db_path.is_file()

        # Direct SQLite query: both terms retrievable by normalized key.
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = list(
                conn.execute(
                    "SELECT source_term, target_term FROM glossary_terms "
                    "WHERE source_term_norm IN (?, ?) ORDER BY file_order",
                    ("عقد البيع", "contract of sale"),
                )
            )
        assert len(rows) == 2
        assert {r["source_term"] for r in rows} == {"عقد البيع", "contract of sale"}

    def test_load_index_from_db_and_scan(self, tmp_path: Path) -> None:
        file_path = _two_term_file(tmp_path)
        terms = load_glossary_files(file_path.parent / "*.json")
        db_path: Path = tmp_path / "glossary.sqlite"
        build_sqlite_index(terms, db_path)

        index: GlossaryIndex = load_glossary_index(db_path)
        assert len(index.terms) == 2

        hits = scan_glossary_hits("هذا عقد البيع المنصوص", lang="ar", index=index)
        assert len(hits) == 1
        assert hits[0].target_term == "contract of sale"

    def test_rebuild_is_idempotent(self, tmp_path: Path) -> None:
        file_path = _two_term_file(tmp_path)
        terms = load_glossary_files(file_path.parent / "*.json")
        db_path: Path = tmp_path / "glossary.sqlite"
        build_sqlite_index(terms, db_path)
        build_sqlite_index(terms, db_path)  # second build must not duplicate rows
        with sqlite3.connect(str(db_path)) as conn:
            count: int = int(conn.execute("SELECT COUNT(*) FROM glossary_terms").fetchone()[0])
        assert count == 2

    def test_missing_db_raises(self, tmp_path: Path) -> None:
        from src.components.translation_pipeline.exceptions import GlossaryError

        with pytest.raises(GlossaryError, match="not found"):
            load_glossary_index(tmp_path / "does_not_exist.sqlite")
