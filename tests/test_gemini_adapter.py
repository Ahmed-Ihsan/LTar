"""Tests for the Gemini API backend adapter (add-gemini-api-backend).

All tests **mock the Gemini SDK** — no real cloud calls are made. The
``google.genai`` client is replaced with an in-process fake that returns
canned responses or raises SDK-shaped exceptions, so the adapter's error
mapping, rate limiter, context-manager, and idempotent-close behavior are
exercised deterministically in CI.

Covers the `infrastructure` spec delta scenarios:
- `GeminiEngineAdapter` satisfies both protocols (LLM + embedding).
- `generate` returns the mocked completion string.
- `embed`/`embed_batch` return 768-dim vectors; dimension mismatch raises
  `EmbeddingError`; non-positive `batch_size` raises `ValueError`.
- Exception mapping: 401/403 → `GeminiAuthError`; 429 → `GeminiQuotaError`;
  timeout → `LLMTimeoutError`; connection → `LLMConnectionError`;
  unknown → `LLMRuntimeError`; embedding connection →
  `EmbeddingConnectionError`.
- Rate limiter: within-budget succeeds; over-budget raises
  `GeminiQuotaError` without an API call; a failed call still releases its
  permit.
- Context manager closes exactly once; `close()` is idempotent.
- Security: `repr(adapter)` and mapped exception messages never contain the
  API key.
- `generate` does NOT call `check_ram_guard` (cloud inference).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.components.infrastructure.embeddings import EMBED_DIM, EmbeddingAdapter
from src.components.infrastructure.gemini import (
    GeminiEngineAdapter,
    _RateLimiter,
    _translate_gemini_error,
)
from src.components.infrastructure.llm import LLMEngineAdapter
from src.components.translation_pipeline.exceptions import (
    AdapterError,
    EmbeddingConnectionError,
    EmbeddingError,
    GeminiAuthError,
    GeminiQuotaError,
    LegalTranslationError,
    LLMConnectionError,
    LLMRuntimeError,
    LLMTimeoutError,
)

pytestmark = pytest.mark.unit

_FAKE_KEY: str = "AIzaTestKeyDoNotUse123"


# ---------------------------------------------------------------------------
# Fakes — replace `google.genai.Client` with an in-process object.
# ---------------------------------------------------------------------------


class _FakePart:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeContent:
    def __init__(self, parts: list[_FakePart]) -> None:
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts: list[_FakePart]) -> None:
        self.content = _FakeContent(parts)


class _FakeGenerateResponse:
    """Fake `client.models.generate_content` response.

    Set `.text` to the canned output, or set `.candidates` for the
    fallback path. Setting `.text` to `None` and leaving `.candidates`
    empty simulates a blocked/empty response.
    """

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.candidates: list[_FakeCandidate] = []

    @classmethod
    def from_text(cls, text: str) -> _FakeGenerateResponse:
        return cls(text=text)

    @classmethod
    def blocked(cls) -> _FakeGenerateResponse:
        # `response.text` raises on a blocked response in the real SDK.
        # Simulate the SDK behavior where `.text` raises ValueError when
        # there are no text parts. We do this by overriding the attribute
        # with a property that raises.

        class _Blocked(_FakeGenerateResponse):
            @property
            def text(self) -> str:  # type: ignore[override]
                raise ValueError("blocked by safety settings")

            @text.setter
            def text(self, _v: object) -> None:
                pass

        return _Blocked()


class _FakeEmbedding:
    def __init__(self, values: list[float]) -> None:
        self.values = values


class _FakeEmbedResponse:
    def __init__(self, embeddings: list[_FakeEmbedding]) -> None:
        self.embeddings = embeddings


class _FakeModels:
    """Fake `client.models` namespace."""

    def __init__(
        self,
        gen_response: _FakeGenerateResponse | None = None,
        gen_exc: BaseException | None = None,
        embed_response: _FakeEmbedResponse | None = None,
        embed_exc: BaseException | None = None,
        list_exc: BaseException | None = None,
    ) -> None:
        self._gen_response = gen_response
        self._gen_exc = gen_exc
        self._embed_response = embed_response
        self._embed_exc = embed_exc
        self._list_exc = list_exc
        self.generate_calls: list[dict[str, Any]] = []
        self.embed_calls: list[dict[str, Any]] = []
        self.list_calls: int = 0

    def generate_content(
        self, *, model: str, contents: Any, config: Any = None
    ) -> _FakeGenerateResponse:
        self.generate_calls.append(
            {"model": model, "contents": contents, "config": config}
        )
        if self._gen_exc is not None:
            raise self._gen_exc
        assert self._gen_response is not None
        return self._gen_response

    def embed_content(
        self, *, model: str, contents: Any, config: Any = None
    ) -> _FakeEmbedResponse:
        self.embed_calls.append(
            {"model": model, "contents": contents, "config": config}
        )
        if self._embed_exc is not None:
            raise self._embed_exc
        assert self._embed_response is not None
        return self._embed_response

    def list(self) -> list[object]:
        self.list_calls += 1
        if self._list_exc is not None:
            raise self._list_exc
        return [object(), object(), object()]


class _FakeClient:
    """Fake `google.genai.Client`."""

    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def _build_adapter(
    models: _FakeModels,
    *,
    api_key: str = _FAKE_KEY,
    rpm: int = 15,
) -> GeminiEngineAdapter:
    """Construct a `GeminiEngineAdapter` with a fake SDK client.

    Patches `google.genai.Client` (the real SDK is installed in the test
    venv) so the adapter builds against an in-process fake client that
    records calls and returns canned responses. The real
    `google.genai.types.GenerateContentConfig` is used (it is a Pydantic
    model that accepts `system_instruction`, `temperature`,
    `max_output_tokens` as kwargs). No real network call is ever made.
    """
    import google.genai  # type: ignore[import-not-found]

    with patch.object(google.genai, "Client", lambda **kw: _FakeClient(models)):
        return GeminiEngineAdapter(
            model="gemini-2.0-flash",
            embed_model="text-embedding-004",
            api_key=api_key,
            rpm=rpm,
        )


def _fake_vector(dim: int = EMBED_DIM) -> list[float]:
    return [0.01 * (i % 7) for i in range(dim)]


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_llm_engine_adapter_protocol(self) -> None:
        a = _build_adapter(_FakeModels())
        assert isinstance(a, LLMEngineAdapter)

    def test_satisfies_embedding_adapter_protocol(self) -> None:
        a = _build_adapter(_FakeModels())
        assert isinstance(a, EmbeddingAdapter)


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


class TestGenerate:
    def test_generate_returns_text(self) -> None:
        models = _FakeModels(gen_response=_FakeGenerateResponse.from_text("Contract of Sale"))
        a = _build_adapter(models)
        out = a.generate("system", "user", model="gemini-2.0-flash")
        assert out == "Contract of Sale"
        assert len(models.generate_calls) == 1
        a.close()

    def test_generate_uses_system_instruction_config(self) -> None:
        models = _FakeModels(gen_response=_FakeGenerateResponse.from_text("ok"))
        a = _build_adapter(models)
        a.generate("SYS", "USR", model="gemini-2.0-flash", temperature=0.3, max_tokens=512)
        call = models.generate_calls[0]
        assert call["contents"] == "USR"
        cfg = call["config"]
        # The config is a real `google.genai.types.GenerateContentConfig`
        # (Pydantic model) — inspect its attributes.
        assert cfg.system_instruction == "SYS"
        assert cfg.temperature == 0.3
        assert cfg.max_output_tokens == 512
        a.close()

    def test_generate_does_not_call_ram_guard(self) -> None:
        # The Gemini adapter must NOT call the RAM guard (cloud inference
        # does not consume local RAM for weights — design D8). The adapter
        # module does not even import `check_ram_guard`; we verify that
        # symbol is absent and that `generate` succeeds without any
        # ram-guard interaction.
        import src.components.infrastructure.gemini as gmod
        assert not hasattr(gmod, "check_ram_guard")
        models = _FakeModels(gen_response=_FakeGenerateResponse.from_text("ok"))
        a = _build_adapter(models)
        out = a.generate("s", "u", model="gemini-2.0-flash")
        assert out == "ok"
        a.close()

    def test_generate_on_closed_adapter_raises(self) -> None:
        a = _build_adapter(_FakeModels())
        a.close()
        with pytest.raises(LLMRuntimeError):
            a.generate("s", "u", model="gemini-2.0-flash")


# ---------------------------------------------------------------------------
# embed / embed_batch
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_embed_returns_768_dim_vector(self) -> None:
        models = _FakeModels(
            embed_response=_FakeEmbedResponse([_FakeEmbedding(_fake_vector())])
        )
        a = _build_adapter(models)
        vec = a.embed("hello")
        assert len(vec) == EMBED_DIM
        a.close()

    def test_embed_batch_returns_vectors_in_order(self) -> None:
        models = _FakeModels(
            embed_response=_FakeEmbedResponse(
                [_FakeEmbedding(_fake_vector()), _FakeEmbedding(_fake_vector())]
            )
        )
        a = _build_adapter(models)
        out = a.embed_batch(["a", "b"], batch_size=2)
        assert len(out) == 2
        assert all(len(v) == EMBED_DIM for v in out)
        a.close()

    def test_embed_batch_empty_input_no_api_call(self) -> None:
        models = _FakeModels()
        a = _build_adapter(models)
        assert a.embed_batch([]) == []
        assert models.embed_calls == []
        a.close()

    def test_embed_batch_rejects_non_positive_batch_size(self) -> None:
        a = _build_adapter(_FakeModels())
        with pytest.raises(ValueError):
            a.embed_batch(["a"], batch_size=0)
        with pytest.raises(ValueError):
            a.embed_batch(["a"], batch_size=-1)
        a.close()

    def test_embed_batch_dimension_mismatch_raises_embedding_error(self) -> None:
        models = _FakeModels(
            embed_response=_FakeEmbedResponse([_FakeEmbedding(_fake_vector(dim=512))])
        )
        a = _build_adapter(models)
        with pytest.raises(EmbeddingError) as ei:
            a.embed_batch(["a"], batch_size=1)
        assert "768" in str(ei.value)
        a.close()

    def test_embed_batch_count_mismatch_raises_embedding_error(self) -> None:
        models = _FakeModels(
            embed_response=_FakeEmbedResponse([_FakeEmbedding(_fake_vector())])
        )
        a = _build_adapter(models)
        with pytest.raises(EmbeddingError):
            a.embed_batch(["a", "b"], batch_size=2)
        a.close()

    def test_embed_on_closed_adapter_raises(self) -> None:
        a = _build_adapter(_FakeModels())
        a.close()
        with pytest.raises(EmbeddingError):
            a.embed("x")


# ---------------------------------------------------------------------------
# Exception mapping
# ---------------------------------------------------------------------------


class _FakeApiError(Exception):
    """Fake `google.api_core.exceptions.GoogleAPICallError`-shaped error."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


class TestExceptionMapping:
    def test_401_maps_to_gemini_auth_error(self) -> None:
        models = _FakeModels(gen_exc=_FakeApiError("unauthorized", 401))
        a = _build_adapter(models)
        with pytest.raises(GeminiAuthError):
            a.generate("s", "u", model="gemini-2.0-flash")
        a.close()

    def test_403_maps_to_gemini_auth_error(self) -> None:
        models = _FakeModels(gen_exc=_FakeApiError("forbidden", 403))
        a = _build_adapter(models)
        with pytest.raises(GeminiAuthError):
            a.generate("s", "u", model="gemini-2.0-flash")
        a.close()

    def test_429_maps_to_gemini_quota_error(self) -> None:
        models = _FakeModels(gen_exc=_FakeApiError("rate limited", 429))
        a = _build_adapter(models)
        with pytest.raises(GeminiQuotaError):
            a.generate("s", "u", model="gemini-2.0-flash")
        a.close()

    def test_timeout_maps_to_llm_timeout_error(self) -> None:
        models = _FakeModels(gen_exc=TimeoutError("read timed out"))
        a = _build_adapter(models)
        with pytest.raises(LLMTimeoutError):
            a.generate("s", "u", model="gemini-2.0-flash")
        a.close()

    def test_connection_error_maps_to_llm_connection_error(self) -> None:
        models = _FakeModels(gen_exc=ConnectionError("refused"))
        a = _build_adapter(models)
        with pytest.raises(LLMConnectionError):
            a.generate("s", "u", model="gemini-2.0-flash")
        a.close()

    def test_unknown_error_maps_to_llm_runtime_error(self) -> None:
        models = _FakeModels(gen_exc=RuntimeError("boom"))
        a = _build_adapter(models)
        with pytest.raises(LLMRuntimeError):
            a.generate("s", "u", model="gemini-2.0-flash")
        a.close()

    def test_embedding_connection_error_maps_to_embedding_connection_error(self) -> None:
        models = _FakeModels(embed_exc=ConnectionError("refused"))
        a = _build_adapter(models)
        with pytest.raises(EmbeddingConnectionError):
            a.embed_batch(["a"], batch_size=1)
        a.close()

    def test_embedding_unknown_error_maps_to_embedding_error(self) -> None:
        models = _FakeModels(embed_exc=RuntimeError("boom"))
        a = _build_adapter(models)
        with pytest.raises(EmbeddingError):
            a.embed_batch(["a"], batch_size=1)
        a.close()

    def test_translate_gemini_error_unknown_kind_raises_domain_error(self) -> None:
        with pytest.raises(AdapterError):
            _translate_gemini_error(RuntimeError("x"), model="m", kind="bogus")

    def test_api_key_not_leaked_in_exception_message(self) -> None:
        # Build an error whose message contains the key, then verify the
        # mapped domain exception does NOT contain it (the mapper redacts
        # the key when `api_key` is passed).
        err = _FakeApiError(f"key={_FAKE_KEY} rejected", 401)
        mapped = _translate_gemini_error(err, model="m", kind="llm", api_key=_FAKE_KEY)
        assert _FAKE_KEY not in str(mapped)
        assert "***" in str(mapped)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_within_budget_succeeds(self) -> None:
        models = _FakeModels(gen_response=_FakeGenerateResponse.from_text("ok"))
        a = _build_adapter(models, rpm=2)
        a.generate("s", "u", model="gemini-2.0-flash")
        a.generate("s", "u", model="gemini-2.0-flash")
        assert len(models.generate_calls) == 2
        a.close()

    def test_exceeding_budget_raises_quota_error_without_api_call(self) -> None:
        models = _FakeModels(gen_response=_FakeGenerateResponse.from_text("ok"))
        a = _build_adapter(models, rpm=1)
        a.generate("s", "u", model="gemini-2.0-flash")
        with pytest.raises(GeminiQuotaError):
            a.generate("s", "u", model="gemini-2.0-flash")
        # Only the first (within-budget) call reached the API.
        assert len(models.generate_calls) == 1
        a.close()

    def test_failed_call_releases_permit(self) -> None:
        # First call fails (raises), but the permit must be released so the
        # next call within the same budget window can proceed.
        models_ok = _FakeModels(gen_response=_FakeGenerateResponse.from_text("ok"))
        models_fail = _FakeModels(gen_exc=RuntimeError("transient"))
        a = _build_adapter(models_fail, rpm=1)
        with pytest.raises(LLMRuntimeError):
            a.generate("s", "u", model="gemini-2.0-flash")
        # Swap the models namespace so the next call succeeds (same adapter,
        # same client — we just swap the fake models object the client
        # references).
        a._client.models = models_ok  # noqa: SLF001
        a.generate("s", "u", model="gemini-2.0-flash")
        assert len(models_ok.generate_calls) == 1
        a.close()

    def test_rate_limiter_rejects_non_positive_rpm(self) -> None:
        with pytest.raises(GeminiQuotaError):
            _RateLimiter(0)
        with pytest.raises(GeminiQuotaError):
            _RateLimiter(-1)


# ---------------------------------------------------------------------------
# Context manager + idempotent close
# ---------------------------------------------------------------------------


class TestCloseAndContextManager:
    def test_close_is_idempotent(self) -> None:
        a = _build_adapter(_FakeModels())
        a.close()
        a.close()  # no error
        assert a.closed is True

    def test_context_manager_closes_on_exit(self) -> None:
        with _build_adapter(_FakeModels()) as a:
            assert a.closed is False
        assert a.closed is True

    def test_repr_does_not_leak_api_key(self) -> None:
        a = _build_adapter(_FakeModels(), api_key=_FAKE_KEY)
        r = repr(a)
        assert _FAKE_KEY not in r
        assert "***" in r
        a.close()


# ---------------------------------------------------------------------------
# Construction validation
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_missing_api_key_raises_on_construct(self) -> None:
        with pytest.raises(GeminiAuthError):
            _build_adapter(_FakeModels(), api_key="")
        with pytest.raises(GeminiAuthError):
            GeminiEngineAdapter(
                model="m", embed_model="e", api_key=None,  # type: ignore[arg-type]
            )

    def test_module_imports_without_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The `gemini` module loads even when the SDK is not importable.

        The `google-genai` SDK is lazily imported inside
        `GeminiEngineAdapter.__init__`, NOT at module top level. We simulate
        the SDK being absent by making `google.genai` unimportable, then
        re-import the `gemini` module fresh and confirm it loads. Only
        constructing an adapter triggers the (mapped) failure.
        """
        import builtins
        import importlib
        import sys

        real_import = builtins.__import__

        def _blocking_import(name: str, *args: object, **kwargs: object):
            if name == "google" or name.startswith("google."):
                raise ImportError(f"simulated absence of {name}")
            return real_import(name, *args, **kwargs)

        # Drop cached google.* + the gemini module so the re-import is clean.
        for mod in list(sys.modules):
            if mod.startswith("google") or mod == "src.components.infrastructure.gemini":
                monkeypatch.delitem(sys.modules, mod, raising=False)
        monkeypatch.setattr(builtins, "__import__", _blocking_import)

        # Re-import the gemini module — must NOT raise (lazy import).
        gemini_mod = importlib.import_module("src.components.infrastructure.gemini")
        assert gemini_mod is not None
        # Constructing an adapter with the SDK absent raises a clean
        # LLMRuntimeError (mapped ImportError), not a raw ImportError.
        with pytest.raises(LLMRuntimeError):
            gemini_mod.GeminiEngineAdapter(
                model="m", embed_model="e", api_key="k"
            )


# ---------------------------------------------------------------------------
# Domain-exception wrapping — raw ValueError must not leak (TDD)
# ---------------------------------------------------------------------------


class TestDomainExceptionWrapping:
    """Raw ``ValueError`` raises in the Gemini adapter must be wrapped in
    domain exceptions so the CLI boundary never sees a bare built-in.

    Each test triggers a known leak point and asserts the raised exception
    is a :class:`LegalTranslationError` subclass — never a raw ``ValueError``.
    """

    def test_unknown_engine_kind_raises_domain_error(self) -> None:
        """``_translate_gemini_error`` with an invalid ``kind`` must raise a
        domain exception (``AdapterError``), not a raw ``ValueError``."""
        with pytest.raises(AdapterError, match="unknown engine kind"):
            _translate_gemini_error(RuntimeError("x"), model="m", kind="bogus")

    def test_unknown_engine_kind_not_raw_value_error(self) -> None:
        """The raised exception must NOT be a raw ``ValueError``."""
        with pytest.raises(LegalTranslationError):
            _translate_gemini_error(RuntimeError("x"), model="m", kind="bogus")
        # Explicitly ensure it is not a bare ValueError.
        try:
            _translate_gemini_error(RuntimeError("x"), model="m", kind="bogus")
        except ValueError:
            pytest.fail("raw ValueError leaked instead of a domain exception")
        except LegalTranslationError:
            pass  # expected

    def test_rate_limiter_non_positive_rpm_raises_domain_error(self) -> None:
        """``_RateLimiter`` with ``rpm <= 0`` must raise ``GeminiQuotaError``."""
        with pytest.raises(GeminiQuotaError, match="rpm must be positive"):
            _RateLimiter(0)
        with pytest.raises(GeminiQuotaError, match="rpm must be positive"):
            _RateLimiter(-1)

    def test_rate_limiter_non_positive_rpm_not_raw_value_error(self) -> None:
        """The raised exception must NOT be a raw ``ValueError``."""
        try:
            _RateLimiter(0)
        except ValueError:
            pytest.fail("raw ValueError leaked instead of a domain exception")
        except LegalTranslationError:
            pass  # expected

    def test_empty_api_key_raises_domain_error(self) -> None:
        """An empty ``api_key`` must raise ``GeminiAuthError``."""
        with pytest.raises(GeminiAuthError, match="api_key"):
            _build_adapter(_FakeModels(), api_key="")

    def test_empty_api_key_not_raw_value_error(self) -> None:
        """The raised exception must NOT be a raw ``ValueError``."""
        try:
            _build_adapter(_FakeModels(), api_key="")
        except ValueError:
            pytest.fail("raw ValueError leaked instead of a domain exception")
        except LegalTranslationError:
            pass  # expected

    def test_adapter_non_positive_rpm_raises_domain_error(self) -> None:
        """``GeminiEngineAdapter`` with ``rpm <= 0`` must raise
        ``GeminiQuotaError``."""
        with pytest.raises(GeminiQuotaError, match="rpm must be positive"):
            _build_adapter(_FakeModels(), rpm=0)

    def test_adapter_non_positive_rpm_not_raw_value_error(self) -> None:
        """The raised exception must NOT be a raw ``ValueError``."""
        try:
            _build_adapter(_FakeModels(), rpm=-1)
        except ValueError:
            pytest.fail("raw ValueError leaked instead of a domain exception")
        except LegalTranslationError:
            pass  # expected
