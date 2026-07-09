"""Translation pipeline component — the LangGraph state machine.

Re-exports the public API of the translation pipeline so callers can use the
short form::

    from src.components.translation_pipeline import TranslationState, build_graph

or the direct submodule form::

    from src.components.translation_pipeline.models import TranslationState

Imports are lazy (PEP 562 ``__getattr__``) to avoid circular imports between
component ``__init__`` files.
"""
import importlib
from typing import Any

_LAZY: dict[str, str] = {
    # models
    "AuditVerdict": f"{__name__}.models",
    "ContextChunk": f"{__name__}.models",
    "Direction": f"{__name__}.models",
    "GlossaryHit": f"{__name__}.models",
    "TmHit": f"{__name__}.models",
    "TranslationState": f"{__name__}.models",
    "Verdict": f"{__name__}.models",
    "WebSearchResult": f"{__name__}.models",
    # exceptions
    "AdapterError": f"{__name__}.exceptions",
    "AuditParseError": f"{__name__}.exceptions",
    "ChromaDBCorruptionError": f"{__name__}.exceptions",
    "CorpusEncodingError": f"{__name__}.exceptions",
    "CorpusError": f"{__name__}.exceptions",
    "CorpusParseError": f"{__name__}.exceptions",
    "EmbeddingConnectionError": f"{__name__}.exceptions",
    "EmbeddingError": f"{__name__}.exceptions",
    "EmbeddingTimeoutError": f"{__name__}.exceptions",
    "GlossaryConflictError": f"{__name__}.exceptions",
    "GlossaryError": f"{__name__}.exceptions",
    "GlossaryValidationError": f"{__name__}.exceptions",
    "LegalTranslationError": f"{__name__}.exceptions",
    "LlamaCppConnectionError": f"{__name__}.exceptions",
    "LlamaCppTimeoutError": f"{__name__}.exceptions",
    "LLMRuntimeError": f"{__name__}.exceptions",
    "OllamaConnectionError": f"{__name__}.exceptions",
    "OllamaModelNotLoadedError": f"{__name__}.exceptions",
    "OllamaTimeoutError": f"{__name__}.exceptions",
    "RAMGuardError": f"{__name__}.exceptions",
    "RetrievalError": f"{__name__}.exceptions",
    # prompts
    "ALL_PROMPT_CONSTANTS": f"{__name__}.prompts",
    "AUDITOR_SYSTEM_V1": f"{__name__}.prompts",
    "AUDITOR_SYSTEM_V2": f"{__name__}.prompts",
    "AUDITOR_SYSTEM_V3": f"{__name__}.prompts",
    "AUDITOR_SYSTEM_V4": f"{__name__}.prompts",
    "AUDITOR_USER_TEMPLATE_V1": f"{__name__}.prompts",
    "AUDITOR_USER_TEMPLATE_V2": f"{__name__}.prompts",
    "AUDITOR_USER_TEMPLATE_V3": f"{__name__}.prompts",
    "AUDITOR_USER_TEMPLATE_V4": f"{__name__}.prompts",
    "SHARED_SYSTEM_RULES_V1": f"{__name__}.prompts",
    "SHARED_SYSTEM_RULES_V2": f"{__name__}.prompts",
    "SHARED_SYSTEM_RULES_V3": f"{__name__}.prompts",
    "SHARED_SYSTEM_RULES_V4": f"{__name__}.prompts",
    "TRANSLATOR_REVISION_ADDENDUM_V1": f"{__name__}.prompts",
    "TRANSLATOR_REVISION_ADDENDUM_V2": f"{__name__}.prompts",
    "TRANSLATOR_REVISION_ADDENDUM_V3": f"{__name__}.prompts",
    "TRANSLATOR_REVISION_ADDENDUM_V4": f"{__name__}.prompts",
    "TRANSLATOR_SYSTEM_V1": f"{__name__}.prompts",
    "TRANSLATOR_SYSTEM_V2": f"{__name__}.prompts",
    "TRANSLATOR_SYSTEM_V3": f"{__name__}.prompts",
    "TRANSLATOR_SYSTEM_V4": f"{__name__}.prompts",
    "TRANSLATOR_USER_TEMPLATE_V1": f"{__name__}.prompts",
    "TRANSLATOR_USER_TEMPLATE_V2": f"{__name__}.prompts",
    "TRANSLATOR_USER_TEMPLATE_V3": f"{__name__}.prompts",
    "TRANSLATOR_USER_TEMPLATE_V4": f"{__name__}.prompts",
    # decision
    "route_tm": f"{__name__}.decision",
    # nodes
    "audit_node": f"{__name__}.nodes",
    "finalize_node": f"{__name__}.nodes",
    "preprocess_node": f"{__name__}.nodes",
    "tm_bypass_node": f"{__name__}.nodes",
    "tm_lookup_node": f"{__name__}.nodes",
    "translate_node": f"{__name__}.nodes",
    "web_search_node": f"{__name__}.nodes",
    # graph
    "AUDIT_NODE": f"{__name__}.graph",
    "FINALIZE_NODE": f"{__name__}.graph",
    "PREPROCESS_NODE": f"{__name__}.graph",
    "TM_BYPASS_NODE": f"{__name__}.graph",
    "TM_LOOKUP_NODE": f"{__name__}.graph",
    "TRANSLATE_NODE": f"{__name__}.graph",
    "WEB_SEARCH_NODE": f"{__name__}.graph",
    "build_graph": f"{__name__}.graph",
    "route_after_tm": f"{__name__}.graph",
    "route_audit": f"{__name__}.graph",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name])
        value = getattr(module, name)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY)
