"""Ingestion runner: orchestrates parse → chunk → embed → store → manifest.

Extracted from ``ingestion.py`` (SRP) so the parsing/chunking module stays
focused on corpus transformation. This module coordinates the full ingestion
pipeline, renders progress to stdout via ``typer.secho``, and writes the
manifest. It calls into the single-source-of-truth functions in
``ingestion.py`` (parsing/chunking), ``manifest.py`` (hashing/manifest), and
``embeddings.py`` / ``retrieval.py`` (storage) — DRY.
"""
from __future__ import annotations

import gc
import logging
import time
from pathlib import Path
from typing import Annotated

import typer

from src.components.knowledge_sources.glossary import (
    GlossaryConflictError,
    GlossaryValidationError,
    build_sqlite_index,
    load_glossary_files,
)
from src.components.knowledge_sources.ingestion import chunk_article, iter_articles
from src.components.knowledge_sources.manifest import (
    _COLLECTION_NAME,
    CorpusSummary,
    FileHash,
    GlossarySummary,
    IngestionResult,
    hash_files,
    project_root,
    write_manifest,
)
from src.components.knowledge_sources.models import Chunk, Term
from src.components.translation_pipeline.exceptions import (
    CorpusEncodingError,
    CorpusParseError,
)
from src.config import AppConfig, load_config

logger = logging.getLogger(__name__)


def _ingest_glossary(cfg: AppConfig) -> tuple[GlossarySummary, list[FileHash]]:
    """Load glossary files into SQLite; return summary and file hashes."""
    glossary_dir: Path = project_root() / cfg.paths.glossary_dir
    file_paths: list[Path] = sorted(glossary_dir.glob("*.json"))
    file_hashes: list[FileHash] = hash_files(file_paths)

    conflicts: int = 0
    validation_errors: int = 0
    all_terms: list[Term] = []
    for fp in file_paths:
        try:
            terms = load_glossary_files(fp)
            all_terms.extend(terms)
        except GlossaryConflictError as e:
            logger.warning("Glossary conflict in %s: %s", fp, e)
            conflicts += 1
        except GlossaryValidationError as e:
            logger.warning("Glossary validation error in %s: %s", fp, e)
            validation_errors += 1

    if all_terms and conflicts == 0 and validation_errors == 0:
        db_path: Path = project_root() / cfg.paths.glossary_db
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
    corpus_dir: Path = project_root() / cfg.paths.corpus_dir
    file_paths: list[Path] = sorted(corpus_dir.glob("*.txt"))
    file_hashes: list[FileHash] = hash_files(file_paths)

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
        except (CorpusParseError, CorpusEncodingError) as e:
            logger.warning("Corpus parse/encoding error in %s: %s", fp, e)
            parse_errors += 1

    summary = CorpusSummary(
        file_count=len(file_paths),
        law_count=len(law_slugs),
        article_count=article_count,
        chunk_count=len(chunks),
        parse_error_count=parse_errors,
    )
    return chunks, summary, file_hashes


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
    # Lazy imports to avoid circular import (retrieval imports Chunk from ingestion).
    from src.components.infrastructure.embeddings import Embedder
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
            chroma_dir: Path = project_root() / cfg.paths.chroma_dir
            embedder = Embedder(model=cfg.embed_model, host=cfg.ollama_host)
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
    manifest_path: Path = project_root() / "data" / "ingestion_manifest.json"
    ch: str = write_manifest(result, cfg, manifest_path)

    typer.secho(
        f"[ingestion] Duration: {duration:.1f}s. "
        f"Manifest: {manifest_path} (content_hash={ch[:12]}...).",
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
