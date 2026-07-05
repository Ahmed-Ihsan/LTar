"""Configuration loader for the Iraqi Legal Translation Agent.

Loads and validates ``config.yaml`` into a typed ``AppConfig`` model.
Single source of truth for all runtime parameters (chunk size, overlap,
top-k, max revisions, context window, model names, paths).

Run ``python -m src.config load`` to print the parsed configuration.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
import yaml
from pydantic import BaseModel, Field, field_validator

# Default config location: config.yaml next to the project root.
DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parent.parent / "config.yaml"


class PathsConfig(BaseModel):
    """Filesystem paths, all relative to the project root."""

    data_dir: str = "data"
    corpus_dir: str = "data/corpus"
    glossary_dir: str = "data/glossary"
    raw_dir: str = "data/raw"
    db_dir: str = "db"
    glossary_db: str = "db/glossary.sqlite"
    chroma_dir: str = "db/chroma"


class ChromaConfig(BaseModel):
    """ChromaDB HNSW index tuning for a small corpus on low-RAM hardware."""

    space: str = "cosine"
    hnsw_M: int = 8
    construction_ef: int = 64
    search_ef: int = 32


class AppConfig(BaseModel):
    """Top-level application configuration parsed from ``config.yaml``."""

    llm_backend: str = "ollama"
    ollama_host: str = "http://localhost:11434"
    llamacpp_url: str = "http://localhost:8080"

    llm_model: str = "gemma3:4b"
    embed_model: str = "nomic-embed-text"

    paths: PathsConfig = Field(default_factory=PathsConfig)

    chunk_size: int = 512
    chunk_overlap: int = 64
    top_k: int = 8
    embedding_batch_size: int = 32
    chroma_add_batch: int = 64

    max_revisions: int = 3
    context_window: int = 8192
    translator_temperature: float = 0.0
    auditor_temperature: float = 0.0
    translator_max_tokens: int = 2048
    auditor_max_tokens: int = 2048
    llm_timeout: float = 120.0

    chroma: ChromaConfig = Field(default_factory=ChromaConfig)

    # --- Translation Memory (TM) ---
    tm_enabled: bool = True
    tm_similarity_threshold: float = 0.98
    tm_db: str = "db/tm.sqlite"

    @field_validator("chunk_size", "chunk_overlap", "top_k",
                     "embedding_batch_size", "chroma_add_batch",
                     "max_revisions", "context_window",
                     "translator_max_tokens", "auditor_max_tokens")
    @classmethod
    def _positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"expected a positive integer, got {v}")
        return v

    @field_validator("llm_timeout", "translator_temperature", "auditor_temperature",
                     "tm_similarity_threshold")
    @classmethod
    def _non_negative_float(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"expected a non-negative float, got {v}")
        return v

    @field_validator("tm_similarity_threshold")
    @classmethod
    def _threshold_upper_bound(cls, v: float) -> float:
        if v > 1.0:
            raise ValueError(f"tm_similarity_threshold must be <= 1.0, got {v}")
        return v


class ConfigError(Exception):
    """Raised when ``config.yaml`` is missing, unreadable, or invalid."""


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate ``config.yaml`` into an :class:`AppConfig`.

    Raises:
        ConfigError: if the file is missing, not a mapping, or fails
            Pydantic validation.
    """
    config_path: Path = path if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    try:
        raw: object = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {config_path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(
            f"config root must be a mapping, got {type(raw).__name__}"
        )
    try:
        return AppConfig.model_validate(raw)
    except Exception as e:
        raise ConfigError(f"config validation failed: {e}") from e


app = typer.Typer(
    add_completion=False,
    rich_markup_mode=None,  # plain Click help; rich panels break on piped Windows stdout
    help="Configuration utilities.",
)


@app.callback()
def _config_main(ctx: typer.Context) -> None:
    """Configuration utilities for loading and validating config.yaml."""
    _ = ctx


@app.command()
def load(
    config_path: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to config.yaml."),
    ] = DEFAULT_CONFIG_PATH,
) -> None:
    """Load and print the parsed configuration as JSON."""
    try:
        cfg: AppConfig = load_config(config_path)
    except ConfigError as e:
        typer.secho(f"config error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(cfg.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
