"""Infrastructure component — LLM, embeddings, memory, and run logging adapters.

Re-exports the public adapter API so callers can use the short form::

    from src.components.infrastructure import OllamaEngineAdapter, Embedder

or the direct submodule form::

    from src.components.infrastructure.llm import OllamaEngineAdapter

Imports are lazy (PEP 562 ``__getattr__``) to avoid circular imports between
component ``__init__`` files.
"""
import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "DEFAULT_BATCH_SIZE": f"{__name__}.embeddings",
    "EMBED_DIM": f"{__name__}.embeddings",
    "Embedder": f"{__name__}.embeddings",
    "EmbeddingAdapter": f"{__name__}.embeddings",
    "embed_batch": f"{__name__}.embeddings",
    "embed_text": f"{__name__}.embeddings",
    "LLMEngineAdapter": f"{__name__}.llm",
    "OllamaEngineAdapter": f"{__name__}.llm",
    "RAM_GUARD_MIN_GB": f"{__name__}.memory",
    "available_ram_gb": f"{__name__}.memory",
    "check_ram_guard": f"{__name__}.memory",
    "read_memory_info": f"{__name__}.memory",
    "MemoryInfo": f"{__name__}.models",
    "RunLogger": f"{__name__}.run_logging",
    "translate_engine_error": f"{__name__}.ollama_errors",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name])
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY)
