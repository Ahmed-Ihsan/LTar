"""Configuration loader for the Iraqi Legal Translation Agent.

Loads and validates ``config.yaml`` into a typed ``AppConfig`` model.
Single source of truth for all runtime parameters (chunk size, overlap,
top-k, max revisions, context window, model names, paths).

The CLI (Typer ``app`` and ``load`` command) has been extracted to
``cli.py`` (SRP). Run ``python -m src.config.cli load`` to print the
parsed configuration.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from src.config.models import ChromaConfig, ExcelConfig, PathsConfig

# Default config location: config.yaml next to the project root.
# This module lives at src/config/config.py, so project root is three
# parents up (src/config/config.py -> src/config -> src -> <root>).
DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parent.parent.parent / "config.yaml"


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

    # --- Human-in-the-loop (HITL) ---
    hitl_enabled: bool = False
    hitl_feedback_dir: str = "data/feedback"

    # --- Web search (Iraqi legal sources) ---
    web_search_enabled: bool = False
    web_search_max_results: int = 5

    # --- Excel (.xlsx) workbook translation ---
    excel: ExcelConfig = Field(default_factory=ExcelConfig)

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
