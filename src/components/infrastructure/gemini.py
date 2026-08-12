"""Google Gemini API adapter — opt-in cloud LLM + embedding backend.

Single responsibility (per AGENTS.md §5 / engineering-principles §1.1):
call the Google Gemini API through the ``google-genai`` SDK to turn a
(system, user) prompt pair into a text completion, and to turn text into
768-dim embedding vectors. Engine-specific exceptions
(``google.api_core.exceptions.*``, ``TimeoutError``, ``ConnectionError``)
are translated to domain ``LLMRuntimeError`` / ``EmbeddingError``
subclasses inside this adapter (clean-code §3.2) so nodes and the CLI
never see SDK exception types.

This module is the **single source of truth** for Gemini calls. The
``translate`` / ``audit`` nodes and the retrieval layer depend on the
:class:`LLMEngineAdapter` and :class:`EmbeddingAdapter` protocols
(engineering-principles §1.5 / §3.1) and never import the ``google.genai``
SDK directly (DIP, engineering-principles §1.5; adapter boundary,
engineering-principles §3.7 rule 4).

**Lazy SDK import:** ``import google.genai`` lives inside
:meth:`GeminiEngineAdapter.__init__` (and the doctor ping helper), NOT at
module top level. Offline users on the ``ollama`` path never import the
SDK — the package imports cleanly even when ``google-genai`` is not
installed (design D4).

**RAM guard:** :meth:`GeminiEngineAdapter.generate` does NOT call
``check_ram_guard()`` — cloud inference does not consume local RAM for
model weights; the 8 GB ceiling (AGENTS.md §3) is irrelevant to hosted
inference (design D8).

**Rate limiting:** a ``threading.Semaphore``-based, process-local limiter
enforces the configured ``rpm`` (default 15, Gemini free-tier). When the
budget is exhausted, :class:`GeminiQuotaError` is raised *without*
contacting the API (design D5).

Implemented as task 3.x of the ``add-gemini-api-backend`` OpenSpec change.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any

from src.components.infrastructure.embeddings import (
    DEFAULT_BATCH_SIZE,
    EMBED_DIM,
)
from src.components.translation_pipeline.exceptions import (
    AdapterError,
    EmbeddingConnectionError,
    EmbeddingError,
    GeminiAuthError,
    GeminiQuotaError,
    LLMConnectionError,
    LLMRuntimeError,
    LLMTimeoutError,
)
from src.utils.batch_size import validate_batch_size

logger = logging.getLogger(__name__)

# --- Error-classification constants (single source of truth) ---
_KIND_LLM: str = "llm"
_KIND_EMBEDDING: str = "embedding"

# HTTP status codes used by the Gemini / google-api-core error model.
_HTTP_UNAUTHORIZED: int = 401
_HTTP_FORBIDDEN: int = 403
_HTTP_TOO_MANY_REQUESTS: int = 429
_HTTP_SERVICE_UNAVAILABLE: int = 503

# Masked sentinel used in `__repr__` for the API key (security — AGENTS.md §12).
_KEY_MASK: str = "***"


def _translate_gemini_error(
    err: BaseException, *, model: str, kind: str, api_key: str | None = None
) -> Exception:
    """Map a Google GenAI SDK exception to a domain exception.

    Implements the Gemini catch matrix (clean-code §3.2; design D3 + spec
    `Gemini exception mapping`). Classification is **defensive** — it uses
    ``isinstance`` against ``google.api_core.exceptions`` classes when
    available and falls back to HTTP-status / message inspection so SDK
    version drift does not silently leak a raw SDK error.

    The ``kind`` parameter selects the target hierarchy exactly as
    :func:`src.components.infrastructure.ollama_errors.translate_engine_error`
    does:

    - ``"llm"``: 401/403/PermissionDenied → :class:`GeminiAuthError`;
      429/ResourceExhausted → :class:`GeminiQuotaError`; timeout/deadline
      → :class:`LLMTimeoutError`; connection/service-unavailable →
      :class:`LLMConnectionError`; fallback → :class:`LLMRuntimeError`.
    - ``"embedding"``: timeout → :class:`EmbeddingTimeoutError`-style
      mapping is not used here; instead the same classification produces
      :class:`EmbeddingConnectionError` on connection failures and
      :class:`EmbeddingError` on any other failure (matching the Ollama
      ``Embedder`` contract).

    The API key is **never** included in the returned exception message
    (security — AGENTS.md §12; spec scenario "the API key is never leaked
    in an exception message"). If ``api_key`` is provided, any occurrence
    of it in the SDK error message is replaced with the mask sentinel
    before the message is wrapped in a domain exception.

    Args:
        err: The caught SDK exception.
        model: The model name used in the failing call (for diagnostics).
        kind: Either ``"llm"`` or ``"embedding"``.
        api_key: The Gemini API key (optional) — redacted from the message.

    Returns:
        The mapped domain exception (caller should ``raise … from err``).
    """
    status: int | None = _extract_status_code(err)
    name: str = type(err).__name__
    msg: str = str(err)
    # Avoid leaking the API key if the SDK ever echoes it in a message.
    safe_msg: str = _redact_key_with(msg, api_key)

    is_auth: bool = (
        status in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN)
        or "PermissionDenied" in name
        or "Unauthenticated" in name
    )
    is_quota: bool = (
        status == _HTTP_TOO_MANY_REQUESTS
        or "ResourceExhausted" in name
    )
    is_timeout: bool = (
        isinstance(err, TimeoutError)
        or "DeadlineExceeded" in name
        or "timeout" in safe_msg.lower()
        or "timed out" in safe_msg.lower()
    )
    is_connection: bool = (
        isinstance(err, ConnectionError | OSError)
        or status == _HTTP_SERVICE_UNAVAILABLE
        or "ServiceUnavailable" in name
        or "Unavailable" in name
        or "connection" in safe_msg.lower()
    )

    if kind == _KIND_LLM:
        if is_auth:
            return GeminiAuthError(
                f"Gemini API key rejected (model={model}): {safe_msg}"
            )
        if is_quota:
            return GeminiQuotaError(
                f"Gemini RPM/quota exhausted (model={model}): {safe_msg}"
            )
        if is_timeout:
            return LLMTimeoutError(
                f"Gemini request timed out (model={model}): {safe_msg}"
            )
        if is_connection:
            return LLMConnectionError(
                f"cannot reach Gemini API (model={model}): {safe_msg}"
            )
        return LLMRuntimeError(
            f"unexpected Gemini error (model={model}): {safe_msg}"
        )
    if kind == _KIND_EMBEDDING:
        if is_timeout:
            return EmbeddingError(
                f"Gemini embedding request timed out (model={model}): {safe_msg}"
            )
        if is_connection:
            return EmbeddingConnectionError(
                f"cannot reach Gemini embedding API (model={model}): {safe_msg}"
            )
        if is_auth:
            return EmbeddingError(
                f"Gemini embedding API key rejected (model={model}): {safe_msg}"
            )
        if is_quota:
            return EmbeddingError(
                f"Gemini embedding RPM/quota exhausted (model={model}): {safe_msg}"
            )
        return EmbeddingError(
            f"unexpected Gemini embedding error (model={model}): {safe_msg}"
        )
    raise AdapterError(
        f"unknown engine kind {kind!r}; expected 'llm' or 'embedding'"
    )


def _extract_status_code(err: BaseException) -> int | None:
    """Best-effort extraction of an HTTP status code from a SDK exception.

    The ``google-api-core`` ``GoogleAPICallError`` family exposes ``code``
    as the gRPC/HTTP status. We inspect defensively (``getattr`` + integer
    coercion) so SDK version drift does not raise.
    """
    code: object = getattr(err, "code", None)
    if isinstance(code, int):
        return code
    if code is not None:
        try:
            return int(str(code))
        except (TypeError, ValueError):
            return None
    return None


def _redact_key_with(text: str, api_key: str | None) -> str:
    """Replace occurrences of ``api_key`` in ``text`` with the mask sentinel.

    Defensive: the SDK should never echo the key, but if it does we replace
    any occurrence of the key with ``***`` before wrapping the message in a
    domain exception (security — AGENTS.md §12; spec scenario "the API key
    is never leaked in an exception message").
    """
    if not api_key:
        return text
    return text.replace(api_key, _KEY_MASK)


class _RateLimiter:
    """Process-local sliding-window RPM limiter (design D5).

    Tracks call timestamps in a 60-second sliding window. ``acquire()``
    records a timestamp and returns ``True`` when fewer than ``rpm`` calls
    have been made in the last 60 seconds; otherwise it returns ``False``
    (and the caller raises :class:`GeminiQuotaError` without contacting
    the API). ``release(success=...)`` is called in the adapter's
    ``finally`` block: a **successful** call keeps its timestamp (it ages
    out naturally after 60s, correctly counting against the RPM budget);
    a **failed** call removes its timestamp so retries are not penalized
    (spec scenario "a failed call still releases its permit").

    Single-user, single-session (AGENTS.md) means a process-local limiter
    is sufficient — no distributed coordination is required.
    """

    __slots__ = ("_rpm", "_timestamps", "_lock", "_rejected", "_window")

    def __init__(self, rpm: int, *, window: float = 60.0) -> None:
        if rpm <= 0:
            raise GeminiQuotaError(f"rpm must be positive, got {rpm}")
        self._rpm: int = rpm
        self._window: float = window
        self._timestamps: deque[float] = deque()
        self._lock: threading.Lock = threading.Lock()
        self._rejected: int = 0

    @property
    def rpm(self) -> int:
        """The configured per-minute request cap."""
        return self._rpm

    @property
    def rejected(self) -> int:
        """Number of calls rejected so far because the budget was exhausted."""
        return self._rejected

    def acquire(self) -> bool:
        """Record a call attempt; return ``True`` if within budget.

        Purges timestamps older than the 60s window first. If fewer than
        ``rpm`` calls remain in the window, appends ``now`` and returns
        ``True``. Otherwise increments the rejected counter and returns
        ``False`` (the caller should raise :class:`GeminiQuotaError`).
        """
        now: float = time.monotonic()
        cutoff: float = now - self._window
        with self._lock:
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) < self._rpm:
                self._timestamps.append(now)
                return True
            self._rejected += 1
            return False

    def release(self, *, success: bool = True) -> None:
        """Release the permit acquired by the most recent ``acquire()``.

        On success (default), the timestamp is **kept** — it ages out of
        the window naturally after 60s, correctly counting against the RPM
        budget. On failure (``success=False``), the most recent timestamp
        is removed so the failed call does not penalize retries (spec
        scenario "a failed call still releases its permit").
        """
        if success:
            return
        with self._lock:
            if self._timestamps:
                self._timestamps.pop()


class GeminiEngineAdapter:
    """Google Gemini API adapter — implements both ``LLMEngineAdapter`` and
    ``EmbeddingAdapter`` protocols (design D1).

    Wraps a single ``google.genai.Client`` instance (reused across calls —
    clean-code §4.1: never create a new HTTP connection per request) and
    translates SDK exceptions to the domain hierarchy. A process-local
    rate limiter enforces the configured RPM cap (design D5).

    The ``google-genai`` SDK is imported **lazily** inside ``__init__`` so
    that this module imports successfully even when the SDK is not
    installed (offline users on the Ollama path never import it — design
    D4, spec scenario "module imports without the google-genai SDK
    installed").
    """

    __slots__ = (
        "_client",
        "_model",
        "_embed_model",
        "_api_key",
        "_timeout",
        "_limiter",
        "_closed",
        "_types",
    )

    def __init__(
        self,
        *,
        model: str,
        embed_model: str,
        api_key: str,
        timeout: float = 120.0,
        rpm: int = 15,
    ) -> None:
        """Build a Gemini engine + embedding adapter.

        ``model``, ``embed_model``, and ``api_key`` are mandatory (DIP — no
        ``load_config()`` fallback). Callers (``_construct_adapters`` in
        ``cli.py``) resolve config values and pass them explicitly. The
        ``google-genai`` SDK is imported here; an ``ImportError`` is mapped
        to :class:`LLMRuntimeError` so the CLI sees a domain exception.

        Raises:
            GeminiAuthError: if ``api_key`` is empty/None.
            GeminiQuotaError: if ``rpm <= 0``.
            LLMRuntimeError: if the ``google-genai`` SDK is not installed.
        """
        if not api_key:
            raise GeminiAuthError(
                "GeminiEngineAdapter requires a non-empty api_key (read it "
                "from the GEMINI_API_KEY environment variable)."
            )
        if rpm <= 0:
            raise GeminiQuotaError(f"rpm must be positive, got {rpm}")
        self._model: str = model
        self._embed_model: str = embed_model
        self._api_key: str = api_key
        self._timeout: float = timeout
        self._limiter: _RateLimiter = _RateLimiter(rpm)
        self._closed: bool = False
        # Lazy SDK import (design D4). Kept on the instance so methods can
        # build `types.GenerateContentConfig` / `types.EmbedContentConfig`
        # without re-importing.
        try:
            from google import genai
            from google.genai import types as _gtypes
        except ImportError as e:
            raise LLMRuntimeError(
                "the 'google-genai' package is required for the Gemini "
                "backend but is not installed. Run "
                "`pip install -r requirements.txt` to install it."
            ) from e
        self._types: Any = _gtypes
        self._client: Any = genai.Client(api_key=api_key)

    @property
    def model(self) -> str:
        """The configured Gemini chat model name."""
        return self._model

    @property
    def embed_model(self) -> str:
        """The configured Gemini embedding model name."""
        return self._embed_model

    @property
    def rpm(self) -> int:
        """The configured per-minute request cap."""
        return self._limiter.rpm

    @property
    def closed(self) -> bool:
        """``True`` after :meth:`close` has been called."""
        return self._closed

    def __repr__(self) -> str:
        """Mask the API key (security — AGENTS.md §12; spec scenario)."""
        return (
            f"GeminiEngineAdapter(model={self._model!r}, "
            f"embed_model={self._embed_model!r}, "
            f"timeout={self._timeout!r}, rpm={self._limiter.rpm!r}, "
            f"api_key={_KEY_MASK!r}, closed={self._closed!r})"
        )

    def __enter__(self) -> GeminiEngineAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the adapter. Idempotent — safe to call multiple times.

        The ``google-genai`` SDK does not expose a public ``Client.close()``
        in all versions; we defensively call it if present. The
        ``_closed`` flag is the source of truth for idempotency.
        """
        if self._closed:
            return
        self._closed = True
        client_close: Any = getattr(self._client, "close", None)
        if callable(client_close):
            try:
                client_close()
            except Exception as e:  # noqa: BLE001 -- close() must never raise
                logger.warning("Gemini client close() failed: %s", e)

    # --- LLMEngineAdapter protocol -----------------------------------------

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
        """Run a Gemini chat completion and return the assistant text.

        The (system, user) pair is sent as a single-turn ``contents`` with
        a ``system_instruction`` config (the canonical Gemini pattern for a
        system + user prompt pair). The call is wrapped by the rate
        limiter (permit acquired in a ``try`` and released in a
        ``finally``). All SDK exceptions are translated to domain
        ``LLMRuntimeError`` subclasses — no SDK exception type escapes this
        adapter (engineering-principles §3.7 rule 1).

        Per design D8, this method does **NOT** call ``check_ram_guard()``
        — cloud inference does not consume local RAM for model weights.

        Raises:
            GeminiQuotaError: the local RPM budget is exhausted (no API
                call is made).
            GeminiAuthError: the API key is missing/invalid (401/403).
            LLMTimeoutError: the request exceeded the timeout.
            LLMConnectionError: cannot reach the Gemini API.
            LLMRuntimeError: any other Gemini failure.
        """
        if self._closed:
            raise LLMRuntimeError("generate() called on a closed GeminiEngineAdapter")
        if not self._limiter.acquire():
            raise GeminiQuotaError(
                f"Gemini RPM budget ({self._limiter.rpm}/min) exhausted; "
                "no API call was made."
            )
        success: bool = False
        try:
            config: Any = self._types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            try:
                response: Any = self._client.models.generate_content(
                    model=model,
                    contents=user_prompt,
                    config=config,
                )
            except Exception as err:  # noqa: BLE001 -- single boundary; classify below
                raise _translate_gemini_error(
                    err, model=model, kind=_KIND_LLM, api_key=self._api_key
                ) from err
            text: str = self._extract_text(response, model)
            success = True
            return text
        finally:
            self._limiter.release(success=success)

    @staticmethod
    def _extract_text(response: Any, model: str) -> str:
        """Pull the assistant text out of a ``generate_content`` response.

        The ``google-genai`` SDK exposes ``response.text`` which raises
        ``ValueError`` if the response has no text part (e.g. blocked
        content). We fall back to inspecting ``candidates[].content.parts``
        defensively so a blocked-prompt response surfaces a clear domain
        error instead of a SDK ``ValueError``.
        """
        text: str | None = None
        try:
            text = getattr(response, "text", None)
        except Exception as e:  # noqa: BLE001 -- response.text can raise on blocked
            logger.warning("Gemini response.text raised: %s", e)
        if text:
            return text
        # Defensive fallback: walk candidates -> content -> parts.
        candidates: Any = getattr(response, "candidates", None)
        if candidates:
            for cand in candidates:
                content: Any = getattr(cand, "content", None)
                if content is None:
                    continue
                parts: Any = getattr(content, "parts", None)
                if not parts:
                    continue
                for part in parts:
                    part_text: Any = getattr(part, "text", None)
                    if isinstance(part_text, str) and part_text:
                        return part_text
        raise LLMRuntimeError(
            f"Gemini returned no text for model '{model}' "
            "(the prompt may have been blocked or the response was empty)."
        )

    # --- EmbeddingAdapter protocol -----------------------------------------

    def embed(self, text: str) -> list[float]:
        """Embed a single ``text`` into a 768-dim vector.

        Raises:
            GeminiQuotaError: the local RPM budget is exhausted.
            EmbeddingConnectionError: cannot reach the Gemini embedding API.
            EmbeddingError: any other Gemini embedding failure or a
                dimension mismatch.
        """
        return self.embed_batch([text], batch_size=1)[0]

    def embed_batch(
        self,
        texts: list[str],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> list[list[float]]:
        """Embed ``texts`` in bounded batches of ``batch_size``.

        Batching caps peak memory and request size (offline-architecture
        §1.4: 32 texts/batch). Each batch is one
        ``client.models.embed_content`` call; the per-batch vectors are
        concatenated in input order. Empty input returns an empty list
        without contacting the API. Every returned vector MUST be 768-dim
        (``EMBED_DIM``) — a mismatch raises :class:`EmbeddingError` so the
        existing 768-dim cosine ChromaDB collection is never corrupted
        (design D7).

        Raises:
            EmbeddingError: ``batch_size`` is not positive (delegated to
                :func:`src.utils.batch_size.validate_batch_size` which raises
                ``ValueError``; callers should catch ``EmbeddingError`` or
                ``ValueError`` at the boundary).
            GeminiQuotaError: the local RPM budget is exhausted.
            EmbeddingConnectionError: cannot reach the Gemini embedding API.
            EmbeddingError: any other failure or a dimension mismatch.
        """
        if self._closed:
            raise EmbeddingError(
                "embed_batch() called on a closed GeminiEngineAdapter"
            )
        validate_batch_size(batch_size)
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch: list[str] = texts[start:start + batch_size]
            if not self._limiter.acquire():
                raise GeminiQuotaError(
                    f"Gemini RPM budget ({self._limiter.rpm}/min) exhausted; "
                    "no embedding API call was made."
                )
            success: bool = False
            try:
                try:
                    response: Any = self._client.models.embed_content(
                        model=self._embed_model,
                        contents=batch,
                    )
                except Exception as err:  # noqa: BLE001 -- single boundary; classify
                    raise _translate_gemini_error(
                        err, model=self._embed_model, kind=_KIND_EMBEDDING,
                        api_key=self._api_key,
                    ) from err
                batch_vectors: list[list[float]] = self._extract_embeddings(
                    response, expected=len(batch)
                )
                success = True
            finally:
                self._limiter.release(success=success)
            vectors.extend(batch_vectors)
        return vectors

    def _extract_embeddings(
        self, response: Any, *, expected: int
    ) -> list[list[float]]:
        """Pull the embedding vectors out of an ``embed_content`` response.

        The ``google-genai`` SDK exposes ``response.embeddings`` as a list
        of objects with a ``.values`` attribute (a list of floats). We
        enforce the 768-dim contract (design D7) and the count match here.
        """
        embeddings: Any = getattr(response, "embeddings", None)
        if not embeddings:
            raise EmbeddingError(
                f"Gemini embedding response had no embeddings "
                f"(model={self._embed_model})"
            )
        out: list[list[float]] = []
        for emb in embeddings:
            values: Any = getattr(emb, "values", None)
            if not isinstance(values, list):
                raise EmbeddingError(
                    f"Gemini embedding returned non-list values "
                    f"(model={self._embed_model})"
                )
            vec: list[float] = [float(v) for v in values]
            if len(vec) != EMBED_DIM:
                raise EmbeddingError(
                    f"unexpected Gemini embedding dimension: expected "
                    f"{EMBED_DIM}, got {len(vec)} (model={self._embed_model}). "
                    "The existing ChromaDB collection is 768-dim cosine; "
                    "use a 768-dim embed model (e.g. text-embedding-004)."
                )
            out.append(vec)
        if len(out) != expected:
            raise EmbeddingError(
                f"Gemini embedding count mismatch: sent {expected} texts, "
                f"got {len(out)} vectors (model={self._embed_model})"
            )
        return out


__all__ = [
    "GeminiEngineAdapter",
    "_translate_gemini_error",
    "_RateLimiter",
]
