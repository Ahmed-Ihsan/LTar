"""Configuration package for the Iraqi Legal Translation Agent.

Re-exports the public configuration API so callers can use the short form::

    from src.config import AppConfig, load_config, ConfigError, PathsConfig, ChromaConfig

The CLI (Typer ``app`` and ``load`` command) is re-exported from ``cli.py``.
"""
from src.config.cli import app, load
from src.config.config import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    ConfigError,
    load_config,
)
from src.config.models import ChromaConfig, ExcelConfig, PathsConfig

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AppConfig",
    "ChromaConfig",
    "ConfigError",
    "ExcelConfig",
    "PathsConfig",
    "app",
    "load",
    "load_config",
]
