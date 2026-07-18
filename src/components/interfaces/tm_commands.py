"""Translation Memory build/augment commands (task 8).

Extracted from ``cli.py`` (engineering-principles §1.1 single-responsibility).
These are plain functions with Typer parameter annotations; ``cli.py``
registers them on the Typer ``app`` via ``app.command(...)`` so the CLI
remains the single composition root (engineering-principles §3.6).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from src.components.interfaces.config_loader import load_or_exit
from src.config import AppConfig
from src.utils.jsonl_schema import ParallelPair


def _resolve_path(cfg: AppConfig, rel: str) -> Path:
    """Resolve a config-relative path against the project root.

    Thin delegate to :func:`src.components.interfaces.cli._resolve_path` to
    avoid duplicating the project-root logic (DRY). Imported lazily to break
    the circular dependency between this module and ``cli``.
    """
    from src.components.interfaces.cli import _resolve_path as _cli_resolve_path

    return _cli_resolve_path(cfg, rel)


def tm_build(
    corpus_dir: Annotated[
        Path | None,
        typer.Option("--corpus-dir", help="Path to the corpus directory."),
    ] = None,
    tm_db: Annotated[
        str | None,
        typer.Option("--tm-db", help="Path to the TM SQLite DB to create."),
    ] = None,
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Build the Translation Memory SQLite DB from the bilingual corpus."""
    cfg: AppConfig = load_or_exit(config_path)

    cdir: Path = corpus_dir if corpus_dir is not None else _resolve_path(cfg, cfg.paths.corpus_dir)
    dbpath: str = tm_db if tm_db is not None else str(_resolve_path(cfg, cfg.tm_db))

    from src.components.knowledge_sources.tm import TranslationMemory

    with TranslationMemory(
        db_path=dbpath, similarity_threshold=cfg.tm_similarity_threshold
    ) as tm:
        tm.build_from_corpus(cdir)
        entries = tm.list_all()
    typer.echo(f"TM built: {len(entries)} entries in {dbpath}")


def tm_build_parallel(
    jsonl_path: Annotated[
        Path,
        typer.Argument(help="Path to a JSONL file of parallel sentence pairs "
                            "(fields: source_sentence, target_sentence, "
                            "source_lang, target_lang)."),
    ],
    tm_db: Annotated[
        str | None,
        typer.Option("--tm-db", help="Path to the TM SQLite DB to create."),
    ] = None,
    max_pairs: Annotated[
        int,
        typer.Option("--max-pairs", help="Max sentence pairs to import "
                                          "(default 10000 — keeps RAM bounded)."),
    ] = 10000,
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Build the TM from a JSONL file of pre-aligned parallel sentence pairs.

    Used to import external corpora (e.g. MultiUN filtered sentences) into the
    Translation Memory. Idempotent: clears all existing TM entries first.
    """
    cfg: AppConfig = load_or_exit(config_path)

    dbpath: str = tm_db if tm_db is not None else str(_resolve_path(cfg, cfg.tm_db))

    if not jsonl_path.exists():
        typer.secho(f"error: {jsonl_path} not found", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    pairs: list[tuple[str, str, str, str]] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if len(pairs) >= max_pairs:
                break
            try:
                record = ParallelPair.model_validate_json(line)
                pairs.append((
                    record.source_sentence,
                    record.target_sentence,
                    record.source_lang,
                    record.target_lang,
                ))
            except ValidationError as e:
                typer.secho(
                    f"error: malformed JSONL line in {jsonl_path}: {e}",
                    fg=typer.colors.RED, err=True,
                )
                raise typer.Exit(code=5) from e

    if not pairs:
        typer.secho(f"error: no valid pairs found in {jsonl_path}",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    from src.components.knowledge_sources.tm import TranslationMemory

    with TranslationMemory(
        db_path=dbpath, similarity_threshold=cfg.tm_similarity_threshold
    ) as tm:
        tm.build_from_parallel(pairs)
        entries = tm.list_all()
    typer.echo(f"TM built from parallel: {len(entries)} entries ({len(pairs)} pairs) in {dbpath}")


def tm_add_parallel(
    jsonl_path: Annotated[
        Path,
        typer.Argument(help="Path to a JSONL file of parallel sentence pairs "
                            "(fields: source_sentence, target_sentence, "
                            "source_lang, target_lang)."),
    ],
    tm_db: Annotated[
        str | None,
        typer.Option("--tm-db", help="Path to the TM SQLite DB to augment."),
    ] = None,
    max_pairs: Annotated[
        int,
        typer.Option("--max-pairs", help="Max sentence pairs to add "
                                          "(default 10000 — keeps RAM bounded)."),
    ] = 10000,
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = Path(__file__).resolve().parent.parent.parent.parent / "config.yaml",
) -> None:
    """Add parallel sentence pairs to an existing TM (non-destructive).

    Unlike ``tm-build-parallel``, this does NOT clear existing entries.
    Use it to merge external corpora (e.g. MultiUN) into a TM that already
    has Iraqi-law entries.
    """
    cfg: AppConfig = load_or_exit(config_path)

    dbpath: str = tm_db if tm_db is not None else str(_resolve_path(cfg, cfg.tm_db))

    if not jsonl_path.exists():
        typer.secho(f"error: {jsonl_path} not found", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    pairs: list[tuple[str, str, str, str]] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            if len(pairs) >= max_pairs:
                break
            try:
                record = ParallelPair.model_validate_json(line)
                pairs.append((
                    record.source_sentence,
                    record.target_sentence,
                    record.source_lang,
                    record.target_lang,
                ))
            except ValidationError as e:
                typer.secho(
                    f"error: malformed JSONL line in {jsonl_path}: {e}",
                    fg=typer.colors.RED, err=True,
                )
                raise typer.Exit(code=5) from e

    if not pairs:
        typer.secho(f"error: no valid pairs found in {jsonl_path}",
                    fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    from src.components.knowledge_sources.tm import TranslationMemory

    with TranslationMemory(
        db_path=dbpath, similarity_threshold=cfg.tm_similarity_threshold
    ) as tm:
        before: int = len(tm.list_all())
        added: int = tm.add_parallel(pairs)
        after: int = len(tm.list_all())
    typer.echo(
        f"TM augmented: {added} pairs added ({before} → {after} entries) in {dbpath}"
    )
