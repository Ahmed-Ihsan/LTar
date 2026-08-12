"""Integration tests for the ingestion pipeline (tasks 2.3.3, 2.3.4).

Tests the manifest writer (deterministic content hash, idempotency) and the
CLI flag handling using a mock embedder and tmp_path corpus/glossary dirs. No
Ollama daemon is required for the deterministic paths.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.components.knowledge_sources.ingestion import (
    CorpusSummary,
    FileHash,
    GlossarySummary,
    IngestionResult,
    _content_hash,
    _sha256_file,
    _write_manifest,
    chunk_article,
)
from src.components.knowledge_sources.models import Article
from src.components.translation_pipeline.exceptions import (
    CorpusError,
    LegalTranslationError,
)

pytestmark = pytest.mark.integration


class TestManifestContentHash:
    """The content hash is deterministic across runs with identical inputs."""

    def test_identical_inputs_produce_identical_hash(self, tmp_path: Path) -> None:
        from src.config import AppConfig

        cfg = AppConfig()
        f1: Path = tmp_path / "a.txt"
        f2: Path = tmp_path / "b.json"
        f1.write_text("hello", encoding="utf-8")
        f2.write_text('{"x":1}', encoding="utf-8")
        hashes: list[FileHash] = [_sha256_file(f1), _sha256_file(f2)]
        h1: str = _content_hash(hashes, 10, 20, 15, cfg)
        h2: str = _content_hash(hashes, 10, 20, 15, cfg)
        assert h1 == h2

    def test_different_counts_produce_different_hash(self, tmp_path: Path) -> None:
        from src.config import AppConfig

        cfg = AppConfig()
        f1: Path = tmp_path / "a.txt"
        f1.write_text("hello", encoding="utf-8")
        hashes: list[FileHash] = [_sha256_file(f1)]
        h1: str = _content_hash(hashes, 10, 20, 15, cfg)
        h2: str = _content_hash(hashes, 11, 20, 15, cfg)
        assert h1 != h2

    def test_different_file_content_produces_different_hash(
        self, tmp_path: Path
    ) -> None:
        from src.config import AppConfig

        cfg = AppConfig()
        f1: Path = tmp_path / "a.txt"
        f1.write_text("hello", encoding="utf-8")
        h1: str = _content_hash([_sha256_file(f1)], 10, 20, 15, cfg)
        f1.write_text("world", encoding="utf-8")
        h2: str = _content_hash([_sha256_file(f1)], 10, 20, 15, cfg)
        assert h1 != h2


class TestManifestWriter:
    def test_write_manifest_creates_json_with_expected_fields(
        self, tmp_path: Path
    ) -> None:
        from src.config import AppConfig

        cfg = AppConfig()
        f1: Path = tmp_path / "corpus.txt"
        f1.write_text("article text", encoding="utf-8")
        f2: Path = tmp_path / "glossary.json"
        f2.write_text('{"terms":[]}', encoding="utf-8")

        result = IngestionResult(
            glossary=GlossarySummary(1, 5, 0, 0),
            corpus=CorpusSummary(1, 1, 10, 10, 0),
            chroma_embeddings=10,
            duration_seconds=1.5,
            file_hashes=[_sha256_file(f1), _sha256_file(f2)],
        )
        manifest_path: Path = tmp_path / "ingestion_manifest.json"
        content_hash: str = _write_manifest(result, cfg, manifest_path)

        assert manifest_path.is_file()
        data: dict = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["content_hash"] == content_hash
        assert data["glossary"]["term_count"] == 5
        assert data["corpus"]["chunk_count"] == 10
        assert data["corpus"]["article_count"] == 10
        assert data["chroma"]["embeddings_written"] == 10
        assert data["models"]["embed_model"] == cfg.embed_model
        assert "timestamp" in data

    def test_manifest_idempotent_content_hash(self, tmp_path: Path) -> None:
        """Re-writing the manifest with identical inputs yields the same hash."""
        from src.config import AppConfig

        cfg = AppConfig()
        f1: Path = tmp_path / "corpus.txt"
        f1.write_text("article text", encoding="utf-8")
        result = IngestionResult(
            glossary=GlossarySummary(1, 5, 0, 0),
            corpus=CorpusSummary(1, 1, 10, 10, 0),
            chroma_embeddings=10,
            duration_seconds=1.5,
            file_hashes=[_sha256_file(f1)],
        )
        manifest_path: Path = tmp_path / "ingestion_manifest.json"
        h1: str = _write_manifest(result, cfg, manifest_path)
        h2: str = _write_manifest(result, cfg, manifest_path)
        assert h1 == h2


class TestSha256File:
    def test_hash_is_deterministic(self, tmp_path: Path) -> None:
        f: Path = tmp_path / "x.txt"
        f.write_text("test content", encoding="utf-8")
        h1: FileHash = _sha256_file(f)
        h2: FileHash = _sha256_file(f)
        assert h1.sha256 == h2.sha256
        assert h1.size == len("test content")

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f: Path = tmp_path / "x.txt"
        f.write_text("aaa", encoding="utf-8")
        h1: FileHash = _sha256_file(f)
        f.write_text("bbb", encoding="utf-8")
        h2: FileHash = _sha256_file(f)
        assert h1.sha256 != h2.sha256


# ---------------------------------------------------------------------------
# Domain-exception wrapping — raw ValueError must not leak (TDD)
# ---------------------------------------------------------------------------


def _make_test_article() -> Article:
    """Build a minimal :class:`Article` for chunking-parameter tests."""
    return Article(
        number="1",
        text="This is a test article body with some legal text content.",
        law="Test Law",
        source="Test Source",
        lang="en",
        law_slug="test_law",
        char_start=0,
        char_end=50,
        file_path="test.txt",
    )


class TestChunkArticleDomainExceptionWrapping:
    """Raw ``ValueError`` raises in ``chunk_article`` must be wrapped in
    domain exceptions so the CLI boundary never sees a bare built-in.

    Each test triggers a known leak point and asserts the raised exception
    is a :class:`LegalTranslationError` subclass — never a raw ``ValueError``.
    """

    def test_non_positive_target_tokens_raises_domain_error(self) -> None:
        """``chunk_article`` with ``target_tokens <= 0`` must raise
        ``CorpusError``, not a raw ``ValueError``."""
        article = _make_test_article()
        with pytest.raises(CorpusError, match="target_tokens must be positive"):
            chunk_article(article, target_tokens=0, overlap=0)
        with pytest.raises(CorpusError, match="target_tokens must be positive"):
            chunk_article(article, target_tokens=-1, overlap=0)

    def test_non_positive_target_tokens_not_raw_value_error(self) -> None:
        """The raised exception must NOT be a raw ``ValueError``."""
        article = _make_test_article()
        try:
            chunk_article(article, target_tokens=0, overlap=0)
        except ValueError:
            pytest.fail("raw ValueError leaked instead of a domain exception")
        except LegalTranslationError:
            pass  # expected

    def test_negative_overlap_raises_domain_error(self) -> None:
        """``chunk_article`` with ``overlap < 0`` must raise ``CorpusError``,
        not a raw ``ValueError``."""
        article = _make_test_article()
        with pytest.raises(CorpusError, match="overlap must be non-negative"):
            chunk_article(article, target_tokens=100, overlap=-1)

    def test_negative_overlap_not_raw_value_error(self) -> None:
        """The raised exception must NOT be a raw ``ValueError``."""
        article = _make_test_article()
        try:
            chunk_article(article, target_tokens=100, overlap=-1)
        except ValueError:
            pytest.fail("raw ValueError leaked instead of a domain exception")
        except LegalTranslationError:
            pass  # expected
