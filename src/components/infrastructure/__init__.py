"""Infrastructure component — LLM, embeddings, memory, and run logging adapters.

Re-exports the public adapter API so callers can use the short form::

    from src.components.infrastructure import OllamaEngineAdapter, Embedder

or the direct submodule form::

    from src.components.infrastructure.llm import OllamaEngineAdapter
"""
from src.components.infrastructure.embeddings import (
    DEFAULT_BATCH_SIZE,
    EMBED_DIM,
    Embedder,
    EmbeddingAdapter,
    embed_batch,
    embed_text,
)
from src.components.infrastructure.llm import (
    LLMEngineAdapter,
    OllamaEngineAdapter,
)
from src.components.infrastructure.memory import (
    RAM_GUARD_MIN_GB,
    available_ram_gb,
    check_ram_guard,
    read_memory_info,
)
from src.components.infrastructure.models import MemoryInfo
from src.components.infrastructure.run_logging import RunLogger

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "EMBED_DIM",
    "Embedder",
    "EmbeddingAdapter",
    "LLMEngineAdapter",
    "MemoryInfo",
    "OllamaEngineAdapter",
    "RAM_GUARD_MIN_GB",
    "RunLogger",
    "available_ram_gb",
    "check_ram_guard",
    "embed_batch",
    "embed_text",
    "read_memory_info",
]
