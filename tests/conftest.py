"""Shared pytest fixtures for the Iraqi Legal Translation Agent test suite.

Fixture layout follows the ``testing-verification`` skill §1.1. Glossary
fixtures build an in-memory :class:`GlossaryIndex` from the sample JSON so
scan/normalize tests are deterministic and never touch the real SQLite DB.

The ``mock_embedder`` fixture (testing-verification §3.2) provides a
deterministic hash-based 768-dim embedder so retrieval/ingestion tests run in
CI with no Ollama daemon and no network calls.

The ``mock_llm`` fixture (testing-verification §3.1) provides a deterministic
:class:`MockEngineAdapter` implementing the ``LLMEngineAdapter`` protocol so
the translate/audit nodes run in CI with no Ollama daemon.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.config import AppConfig, load_config
from src.embeddings import EMBED_DIM
from src.exceptions import (
    OllamaConnectionError,
    OllamaModelNotLoadedError,
    OllamaTimeoutError,
)
from src.glossary import GlossaryIndex, Term, load_glossary_file
from src.state import TranslationState

FIXTURES_DIR: Path = Path(__file__).parent / "fixtures"
GLOSSARY_SAMPLE: Path = FIXTURES_DIR / "glossary_sample.json"


@pytest.fixture
def glossary_terms() -> list[Term]:
    """The validated terms loaded from the sample glossary fixture."""
    return load_glossary_file(GLOSSARY_SAMPLE)


@pytest.fixture
def glossary_index(glossary_terms: list[Term]) -> GlossaryIndex:
    """An in-memory glossary index built from the sample fixture."""
    return GlossaryIndex(glossary_terms)


class MockEmbedder:
    """Deterministic mock embedding adapter for CI (testing-verification §3.2).

    Hash-based, 768-dim, no Ollama call. Implements :class:`EmbeddingAdapter`.
    Identical input always yields identical output (deterministic). Texts that
    share a long common prefix produce similar vectors (overlapping hash bytes),
    which gives the retrieval tests a realistic top-1-self signal without a
    real model.
    """

    def embed(self, text: str) -> list[float]:
        h: bytes = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand 32 bytes to 768 floats deterministically in [-1, 1].
        return [(h[i % 32] / 255.0) * 2 - 1 for i in range(EMBED_DIM)]

    def embed_batch(
        self, texts: list[str], batch_size: int = 32
    ) -> list[list[float]]:
        return [self.embed(t) for t in texts]


@pytest.fixture
def mock_embedder() -> MockEmbedder:
    """A deterministic mock embedder (no Ollama daemon required)."""
    return MockEmbedder()


class MockEngineAdapter:
    """Deterministic mock LLM adapter for CI (testing-verification §3.1).

    Implements the ``LLMEngineAdapter`` protocol. Returns canned responses
    keyed by a prompt signature (translator vs. auditor), or an explicit
    override registered via :meth:`set_response`. Identical input always yields
    identical output (deterministic). Fail modes simulate the domain exceptions
    the real :class:`OllamaEngineAdapter` raises after translating engine
    errors, so node error-propagation tests are realistic.
    """

    def __init__(self) -> None:
        self._overrides: dict[str, str] = {}
        self._call_log: list[tuple[str, str]] = []
        self._fail_mode: str | None = None

    def set_response(self, signature: str, response: str) -> None:
        """Override the response returned for a given prompt signature."""
        self._overrides[signature] = response

    def set_fail_mode(self, mode: str) -> None:
        """Simulate a failure: 'timeout', 'connection', or 'model_not_found'."""
        self._fail_mode = mode

    @property
    def call_log(self) -> list[tuple[str, str]]:
        """Recorded (system_prompt, user_prompt) per generate call (full text)."""
        return list(self._call_log)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 120.0,
    ) -> str:
        if self._fail_mode == "timeout":
            raise OllamaTimeoutError("Simulated timeout")
        if self._fail_mode == "connection":
            raise OllamaConnectionError("Simulated connection refused")
        if self._fail_mode == "model_not_found":
            raise OllamaModelNotLoadedError(model)
        self._call_log.append((system_prompt, user_prompt))
        signature: str = self._signature(user_prompt)
        if signature in self._overrides:
            return self._overrides[signature]
        return self._default_response(signature)

    @staticmethod
    def _signature(prompt: str) -> str:
        if "JSON" in prompt and "verdict" in prompt:
            return "auditor"
        if "Produce the translation" in prompt:
            return "translator"
        return "default"

    @staticmethod
    def _default_response(signature: str) -> str:
        if signature == "auditor":
            return (
                '{"verdict": "APPROVE", "critique": "", '
                '"violations": [], "confidence": 0.95}'
            )
        return "[Mock translation output]"


@pytest.fixture
def mock_llm() -> MockEngineAdapter:
    """A deterministic mock LLM engine adapter (no Ollama daemon required)."""
    return MockEngineAdapter()


@pytest.fixture
def config() -> AppConfig:
    """The parsed ``config.yaml`` as an :class:`AppConfig`."""
    return load_config()


def _empty_state(
    input_text: str = "", direction: str = "ar-en"
) -> TranslationState:
    """Build a minimal ``TranslationState`` with all fields initialized."""
    return {
        "input_text": input_text,
        "direction": direction,  # type: ignore[arg-type]
        "glossary_hits": [],
        "context_chunks": [],
        "tm_hits": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
    }


@pytest.fixture
def sample_state() -> TranslationState:
    """A minimal ``TranslationState`` for node tests (ar->en, empty fields)."""
    return _empty_state("المادة 148: عقد البيع", "ar-en")

