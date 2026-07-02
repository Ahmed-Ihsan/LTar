"""Unit tests for the chunker (DATA_SPEC §3.2, task 2.2.2).

The chunker is the single source of truth for split logic
(engineering-principles §2.1.1). Tests are pure and deterministic — no I/O, no
LLM, no network (testing-verification skill §1.1 ``unit/`` layer).
"""
from __future__ import annotations

import pytest

from src.ingestion import Article, Chunk, approx_token_count, chunk_article

pytestmark = pytest.mark.unit

_TARGET: int = 512
_OVERLAP: int = 64


def _synthetic_article_1200_tokens() -> Article:
    """Build an article whose body is exactly 1200 approx-tokens.

    75 sentences, each 64 chars (62-char base + ``". "``) = 16 tokens, joined
    with no extra delimiter (the trailing ``". "`` is part of each unit). Total
    = 75 * 64 = 4800 chars = 1200 tokens. Sentences contain no internal
    sentence terminators so the sentence splitter yields 75 uniform 16-token
    units, giving deterministic packing and an exact 64-token (4-sentence)
    overlap.
    """
    sentences: list[str] = []
    for i in range(75):
        base: str = f"legal sentence number {i:03d}".ljust(62, "x")
        sentences.append(base + ". ")
    body: str = "".join(sentences)
    assert approx_token_count(body) == 1200
    return Article(
        number="148",
        text=body,
        law="Iraqi Civil Code",
        source="gazette",
        lang="en",
        law_slug="civil_code",
        char_start=0,
        char_end=len(body),
        file_path="synthetic",
    )


class TestChunkerOverlap:
    def test_1200_token_article_produces_three_chunks(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        assert len(chunks) == 3

    def test_chunks_have_sequential_indices(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        assert [c.chunk_idx for c in chunks] == [0, 1, 2]

    def test_consecutive_chunks_have_64_token_overlap(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        # char_start is file-relative; article.char_start == 0 here, so the
        # overlap span is directly indexable into the article body.
        for i in range(len(chunks) - 1):
            overlap_span: str = article.text[
                chunks[i + 1].char_start : chunks[i].char_end
            ]
            assert approx_token_count(overlap_span) == _OVERLAP

    def test_each_chunk_within_target_token_budget(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        for chunk in chunks:
            assert approx_token_count(chunk.text) <= _TARGET

    def test_chunk_text_matches_article_slice(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        for chunk in chunks:
            assert chunk.text == article.text[
                chunk.char_start : chunk.char_end
            ]

    def test_chunk_ids_are_deterministic(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        assert [c.chunk_id for c in chunks] == [
            "civil_code_en_148_0",
            "civil_code_en_148_1",
            "civil_code_en_148_2",
        ]

    def test_chunks_inherit_article_metadata(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        for chunk in chunks:
            assert chunk.law == article.law
            assert chunk.article == article.number
            assert chunk.lang == article.lang
            assert chunk.law_slug == article.law_slug


class TestArticleAsChunk:
    def test_short_article_is_single_chunk(self) -> None:
        article: Article = Article(
            number="1",
            text="This is a short article well under the budget.",
            law="Iraqi Civil Code",
            source="gazette",
            lang="en",
            law_slug="civil_code",
            char_start=100,
            char_end=100 + len("This is a short article well under the budget."),
            file_path="synthetic",
        )
        chunks: list[Chunk] = chunk_article(article, _TARGET, _OVERLAP)
        assert len(chunks) == 1
        assert chunks[0].chunk_idx == 0
        assert chunks[0].text == article.text
        assert chunks[0].chunk_id == "civil_code_en_1_0"
        # File-relative offsets add the article's file offset.
        assert chunks[0].char_start == article.char_start
        assert chunks[0].char_end == article.char_end


class TestChunkerValidation:
    def test_zero_target_raises(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        with pytest.raises(ValueError, match="target_tokens"):
            chunk_article(article, 0, _OVERLAP)

    def test_negative_overlap_raises(self) -> None:
        article: Article = _synthetic_article_1200_tokens()
        with pytest.raises(ValueError, match="overlap"):
            chunk_article(article, _TARGET, -1)
