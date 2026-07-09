"""Configuration package for the Iraqi Legal Translation Agent.

Re-exports the public configuration API so callers can use the short form::

    from src.config import AppConfig, load_config, ConfigError, PathsConfig, ChromaConfig
"""
from src.config.config import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    ConfigError,
    app,
    load,
    load_config,
)
from src.config.models import ChromaConfig, PathsConfig

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "AppConfig",
    "ChromaConfig",
    "ConfigError",
    "PathsConfig",
    "app",
    "load",
    "load_config",
]
