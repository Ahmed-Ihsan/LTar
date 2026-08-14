"""Unit tests for the corpus parser (DATA_SPEC §1.2, task 2.2.1).

Parsing is deterministic and touches disk only for the small fixture file
(testing-verification skill §1.1 ``unit/`` layer). No LLM, no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.components.knowledge_sources.ingestion import Article, iter_articles, parse_corpus_file
from src.components.translation_pipeline.exceptions import CorpusEncodingError, CorpusParseError

FIXTURES_DIR: Path = Path(__file__).resolve().parent.parent / "fixtures"
CORPUS_SAMPLE: Path = FIXTURES_DIR / "corpus_sample.txt"

pytestmark = pytest.mark.unit


def test_parses_five_articles_with_correct_count() -> None:
    articles: list[Article] = parse_corpus_file(CORPUS_SAMPLE)
    assert len(articles) == 5


def test_header_metadata_propagated_to_every_article() -> None:
    articles: list[Article] = parse_corpus_file(CORPUS_SAMPLE)
    for article in articles:
        assert article.law == "Iraqi Civil Code"
        assert article.source == "Al-Waqa'i al-Iraqiya No. 40, 1951"
        assert article.lang == "en"
        assert article.law_slug == "corpus_sample"


def test_article_numbers_in_order_and_suffix_normalized() -> None:
    articles: list[Article] = parse_corpus_file(CORPUS_SAMPLE)
    numbers: list[str] = [a.number for a in articles]
    assert numbers == ["1", "2", "3", "148", "148 bis"]


def test_article_body_excludes_marker_line() -> None:
    articles: list[Article] = parse_corpus_file(CORPUS_SAMPLE)
    first: Article = articles[0]
    assert first.number == "1"
    assert "ARTICLE" not in first.text
    assert first.text.startswith("This Code shall be cited")


def test_char_offsets_are_non_decreasing_and_within_file() -> None:
    articles: list[Article] = parse_corpus_file(CORPUS_SAMPLE)
    file_size: int = CORPUS_SAMPLE.stat().st_size
    prev_end: int = -1
    for article in articles:
        assert 0 <= article.char_start < article.char_end <= file_size
        assert article.char_start > prev_end  # markers lie between bodies
        prev_end = article.char_end


def test_iter_articles_matches_parse_corpus_file() -> None:
    assert list(iter_articles(CORPUS_SAMPLE)) == parse_corpus_file(CORPUS_SAMPLE)


def test_missing_header_field_raises_corpus_parse_error(tmp_path: Path) -> None:
    bad: Path = tmp_path / "bad_en.txt"
    bad.write_text(
        "LAW: Test Code\n---\n\nARTICLE 1\nBody text.\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusParseError, match="missing required header"):
        parse_corpus_file(bad)


def test_missing_separator_raises_corpus_parse_error(tmp_path: Path) -> None:
    bad: Path = tmp_path / "nosep_en.txt"
    bad.write_text(
        "LAW: Test Code\nSOURCE: gazette\nLANG: en\n\nARTICLE 1\nBody.\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusParseError, match="missing header separator"):
        parse_corpus_file(bad)


def test_invalid_utf8_raises_corpus_encoding_error(tmp_path: Path) -> None:
    bad: Path = tmp_path / "badenc_ar.txt"
    bad.write_bytes(b"LAW: \xff\xfe bad bytes\n---\n\nARTICLE 1\nx\n")
    with pytest.raises(CorpusEncodingError):
        parse_corpus_file(bad)


def test_law_slug_strips_lang_suffix(tmp_path: Path) -> None:
    file_path: Path = tmp_path / "penal_code_ar.txt"
    file_path.write_text(
        "LAW: x\nSOURCE: y\nLANG: ar\n---\n\nARTICLE 1\nbody\n",
        encoding="utf-8",
    )
    articles: list[Article] = parse_corpus_file(file_path)
    assert articles[0].law_slug == "penal_code"
    assert articles[0].lang == "ar"
