"""Ingestion manifest: file hashing, content hash, and manifest writer.

Extracted from ``ingestion.py`` (SRP) so the parsing/chunking module stays
focused on corpus transformation. This module is the single source of truth
for the manifest dataclasses, file hashing, and the deterministic content
hash that enables idempotency checks (DATA_SPEC §5).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.config import AppConfig

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


def project_root() -> Path:
    """Return the project root (parent of the ``src`` package)."""
    return Path(__file__).resolve().parent.parent.parent.parent


def sha256_file(path: Path) -> FileHash:
    """Compute the SHA-256 hash and byte size of ``path`` (streaming)."""
    h = hashlib.sha256()
    size: int = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
            size += len(block)
    return FileHash(path=str(path), sha256=h.hexdigest(), size=size)


def hash_files(paths: list[Path]) -> list[FileHash]:
    """Hash a list of files in sorted order (deterministic)."""
    return [sha256_file(p) for p in sorted(paths)]


def content_hash(
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


def _categorize_file_hashes(
    file_hashes: list[FileHash],
    glossary_dir: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Split file hashes into glossary and corpus entries for the manifest."""
    glossary_files: list[dict[str, object]] = []
    corpus_files: list[dict[str, object]] = []
    for fh in file_hashes:
        entry: dict[str, object] = {
            "path": fh.path,
            "sha256": fh.sha256,
            "size": fh.size,
        }
        if glossary_dir in Path(fh.path).parents or fh.path.endswith(".json"):
            glossary_files.append(entry)
        else:
            corpus_files.append(entry)
    return glossary_files, corpus_files


def write_manifest(
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

    ch: str = content_hash(
        result.file_hashes, term_count, chunk_count, article_count, cfg
    )

    glossary_dir = project_root() / cfg.paths.glossary_dir
    glossary_files, corpus_files = _categorize_file_hashes(
        result.file_hashes, glossary_dir
    )

    manifest: dict[str, object] = {
        "version": _MANIFEST_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        "content_hash": ch,
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
    return ch
