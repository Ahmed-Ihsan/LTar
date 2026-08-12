"""Configuration loader for the Iraqi Legal Translation Agent.

Loads and validates ``config.yaml`` into a typed ``AppConfig`` model.
Single source of truth for all runtime parameters (chunk size, overlap,
top-k, max revisions, context window, model names, paths).

The CLI (Typer ``app`` and ``load`` command) has been extracted to
``cli.py`` (SRP). Run ``python -m src.config.cli load`` to print the
parsed configuration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config.models import (
    ChromaConfig,
    ExcelConfig,
    PathsConfig,
    PdfConfig,
    UiConfig,
    WordConfig,
)

# Default config location: config.yaml next to the project root.
# This module lives at src/config/config.py, so project root is three
# parents up (src/config/config.py -> src/config -> src -> <root>).
DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parent.parent.parent / "config.yaml"

# Valid LLM backend identifiers (kept here as the single source of truth for
# the `Literal` below and for the ConfigError message listing valid values).
_VALID_BACKENDS: tuple[str, ...] = ("ollama", "llamacpp", "gemini")

# Sentinel masked value used in `AppConfig.__repr__` for `gemini_api_key`.
_KEY_MASK: str = "***"

# Environment variable name from which the Gemini API key is read.
_GEMINI_KEY_ENV: str = "GEMINI_API_KEY"


class AppConfig(BaseModel):
    """Top-level application configuration parsed from ``config.yaml``."""

    # Pydantic v2 model config: extra keys are forbidden (a `gemini_api_key`
    # key placed in config.yaml is rejected by `load_config` before Pydantic
    # sees it, but `extra="forbid"` is the defensive backstop for any other
    # secret-bearing key a user might try to inline).
    model_config = ConfigDict(extra="forbid")

    llm_backend: Literal["ollama", "llamacpp", "gemini"] = "ollama"
    ollama_host: str = "http://localhost:11434"
    llamacpp_url: str = "http://localhost:8080"

    llm_model: str = "gemma3:4b"
    embed_model: str = "nomic-embed-text"

    # Ollama KV-cache context size (num_ctx in the Ollama options dict). Caps
    # the VRAM footprint of the LLM's KV cache so the embed model and gemma3:4b
    # coexist within an 8 GB GPU. Independent of `context_window` (the
    # pipeline-level prompt-truncation budget). Default 2048 is the safe value
    # for the 8 GB target profile; raise it on GPUs with more VRAM.
    ollama_num_ctx: int = 2048

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

    # --- Word (.docx) document translation ---
    word: WordConfig = Field(default_factory=WordConfig)

    # --- PDF (.pdf) document translation (sidecar .docx/.txt output) ---
    pdf: PdfConfig = Field(default_factory=PdfConfig)

    # --- UI backend selection (web vs Tkinter) ---
    ui: UiConfig = Field(default_factory=UiConfig)

    # --- Gemini API (cloud, opt-in) ---
    # `gemini_api_key` is populated from the `GEMINI_API_KEY` environment
    # variable by `load_config` — it MUST NOT appear in `config.yaml`
    # (security: AGENTS.md §12 — never log secrets). Defaults to `None` so
    # the offline-first `ollama` path loads cleanly with no env var set.
    gemini_model: str = "gemini-2.0-flash"
    gemini_embed_model: str = "text-embedding-004"
    gemini_timeout: float = 120.0
    gemini_rpm: int = 15
    gemini_api_key: str | None = None

    @field_validator("chunk_size", "chunk_overlap", "top_k",
                     "embedding_batch_size", "chroma_add_batch",
                     "max_revisions", "context_window",
                     "translator_max_tokens", "auditor_max_tokens",
                     "gemini_rpm", "ollama_num_ctx")
    @classmethod
    def _positive_int(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"expected a positive integer, got {v}")
        return v

    @field_validator("llm_timeout", "translator_temperature", "auditor_temperature",
                     "tm_similarity_threshold", "gemini_timeout")
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

    def __repr__(self) -> str:
        """Mask `gemini_api_key` so the `config load` command never prints it.

        Pydantic v2's generated `__repr__` would include the cleartext key.
        This override substitutes a sentinel mask for the key field only;
        every other field uses Pydantic's default field-by-field rendering.
        """
        key: str | None = self.gemini_api_key
        masked: str = _KEY_MASK if key else "None"
        fields: list[str] = []
        for name, value in self.__dict__.items():
            if name == "gemini_api_key":
                fields.append(f"{name}={masked}")
            else:
                fields.append(f"{name}={value!r}")
        return f"{type(self).__name__}({', '.join(fields)})"

    __str__ = __repr__


class ConfigError(Exception):
    """Raised when ``config.yaml`` is missing, unreadable, or invalid."""


_config_cache: dict[Path, tuple[float, AppConfig]] = {}


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate ``config.yaml`` into an :class:`AppConfig`.

    Raises:
        ConfigError: if the file is missing, not a mapping, fails Pydantic
            validation, contains a `gemini_api_key` key (must come from the
            `GEMINI_API_KEY` env var), or selects `llm_backend: gemini`
            without a `GEMINI_API_KEY` env var set.
    """
    config_path: Path = path if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    mtime: float = config_path.stat().st_mtime
    cached: tuple[float, AppConfig] | None = _config_cache.get(config_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        raw: object = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {config_path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(
            f"config root must be a mapping, got {type(raw).__name__}"
        )
    # Security: the Gemini API key MUST come from the environment, never from
    # config.yaml. Reject a `gemini_api_key` key before Pydantic validation so
    # the error message is actionable and the key never reaches the model.
    if "gemini_api_key" in raw:
        raise ConfigError(
            "gemini_api_key must be set via the GEMINI_API_KEY environment "
            "variable, not config.yaml (security: never commit API keys)."
        )
    try:
        cfg: AppConfig = AppConfig.model_validate(raw)
    except Exception as e:
        # Pydantic's Literal validation rejects an unknown `llm_backend` with
        # a literal_type error; surface a clearer message listing valid values.
        msg: str = str(e)
        if "llm_backend" in msg and "literal" in msg.lower():
            msg = (
                f"invalid llm_backend; valid values are "
                f"{', '.join(_VALID_BACKENDS)}: {msg}"
            )
        raise ConfigError(f"config validation failed: {msg}") from e
    # Populate `gemini_api_key` from the environment (single source of truth).
    api_key: str | None = os.environ.get(_GEMINI_KEY_ENV) or None
    if cfg.llm_backend == "gemini" and not api_key:
        raise ConfigError(
            "llm_backend='gemini' requires the GEMINI_API_KEY environment "
            "variable to be set. Export it (e.g. `$env:GEMINI_API_KEY='...'"
            " on PowerShell or `set GEMINI_API_KEY=...` on cmd) and rerun."
        )
    cfg = cfg.model_copy(update={"gemini_api_key": api_key})
    _config_cache[config_path] = (mtime, cfg)
    return cfg
