"""LLM engine adapter for the Ollama chat completion runtime.

Single responsibility (per ARCHITECTURE.md / engineering-principles §1.1):
call the Ollama chat model through the ``ollama`` client to turn a
(system, user) prompt pair into a text completion. Engine-specific
exceptions (``ollama.ResponseError``, ``httpx.ConnectError``,
``httpx.ReadTimeout``) are translated to domain ``LLMRuntimeError``
subclasses inside this adapter (clean-code §3.2) so nodes and the CLI
never see ``ollama.ResponseError`` / ``httpx`` types.

This module is the single source of truth for LLM calls. The
``translate`` and ``audit`` nodes depend on the
:class:`LLMEngineAdapter` protocol (engineering-principles §1.5 / §3.1)
and never import the ``ollama`` client directly (DIP, engineering-
principles §1.5; adapter boundary, engineering-principles §3.7 rule 4).

Implemented in Phase 3 (task 3.2.x — dependency of the translate/audit
nodes).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import ollama

from src.config import AppConfig, load_config
from src.components.translation_pipeline.exceptions import (
    LLMRuntimeError,
    OllamaConnectionError,
    OllamaModelNotLoadedError,
    OllamaTimeoutError,
)
from src.components.infrastructure.memory import check_ram_guard

# HTTP 404 from Ollama indicates the requested model is not pulled locally.
_MODEL_NOT_FOUND_STATUS: int = 404


@runtime_checkable
class LLMEngineAdapter(Protocol):
    """Adapter contract for LLM completion engines (engineering-principles §3.1).

    Any class implementing this protocol (the real :class:`OllamaEngineAdapter`,
    the deterministic mock used in CI) is substitutable everywhere an LLM engine
    is accepted (LSP, engineering-principles §1.3). Nodes depend on this
    abstraction, never on a concrete engine class (DIP, engineering-principles
    §1.5).
    """

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
        """Run inference and return the text output.

        Raises:
            OllamaConnectionError: cannot reach the LLM daemon.
            OllamaTimeoutError: the request exceeded the timeout.
            OllamaModelNotLoadedError: the requested model is not present.
            LLMRuntimeError: any other engine failure.
        """
        ...


def _translate_engine_error(
    err: BaseException, model: str, host: str
) -> LLMRuntimeError:
    """Map an Ollama/httpx engine exception to a domain ``LLMRuntimeError``.

    Implements the catch matrix (clean-code §3.2): 404 response errors become
    :class:`OllamaModelNotLoadedError`, connection failures become
    :class:`OllamaConnectionError`, timeouts become
    :class:`OllamaTimeoutError`, anything else becomes a generic
    :class:`LLMRuntimeError` carrying the model name and host for diagnosis.
    """
    if isinstance(err, ollama.ResponseError):
        if err.status_code == _MODEL_NOT_FOUND_STATUS:
            return OllamaModelNotLoadedError(
                f"model '{model}' not loaded on Ollama at {host}: {err}"
            )
        return OllamaConnectionError(
            f"Ollama response error (status={err.status_code}) at {host}: {err}"
        )
    if isinstance(err, TimeoutError) or "timeout" in str(err).lower():
        return OllamaTimeoutError(
            f"Ollama request to {host} timed out (model={model}): {err}"
        )
    if isinstance(err, (ConnectionError, OSError)):
        return OllamaConnectionError(
            f"cannot reach Ollama daemon at {host} (model={model}): {err}"
        )
    return LLMRuntimeError(
        f"unexpected Ollama error (model={model}, host={host}): {err}"
    )


class OllamaEngineAdapter:
    """Real Ollama LLM adapter (clean-code §2.4: manages client state).

    Wraps a single :class:`ollama.Client` instance (reused across calls —
    clean-code §4.1: never create a new httpx connection per request) and
    translates engine exceptions to the domain hierarchy. A timed-out request
    is retried once with a doubled timeout (clean-code §3.2 catch matrix);
    a second timeout becomes :class:`OllamaTimeoutError`.
    """

    __slots__ = ("_client", "_model", "_host")

    def __init__(
        self,
        client: ollama.Client | None = None,
        *,
        model: str | None = None,
        host: str | None = None,
    ) -> None:
        """Build an LLM engine adapter.

        If ``client`` is omitted, a new :class:`ollama.Client` is created from
        the resolved ``host`` (defaults to the config ``ollama_host``). If
        ``model`` is omitted, the config ``llm_model`` is used. Resolving
        defaults from config keeps model names out of node/caller code (DRY,
        engineering-principles §2.2.4).
        """
        cfg: AppConfig = load_config()
        self._model: str = model if model is not None else cfg.llm_model
        self._host: str = host if host is not None else cfg.ollama_host
        self._client: ollama.Client = (
            client if client is not None else ollama.Client(host=self._host)
        )

    @property
    def model(self) -> str:
        """The default chat model name used when none is passed to ``generate``."""
        return self._model

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
        """Run a chat completion and return the assistant message text.

        The (system, user) pair is sent as a two-turn chat. A timed-out request
        is retried once with ``timeout * 2`` (clean-code §3.2). All engine
        exceptions are translated to domain ``LLMRuntimeError`` subclasses — no
        engine exception type escapes this adapter (engineering-principles
        §3.7 rule 1).

        Raises:
            RAMGuardError: available RAM is below the safe threshold
                (task 4.3.3); raised *before* the daemon is contacted.
            OllamaConnectionError: cannot reach the Ollama daemon.
            OllamaTimeoutError: the request exceeded the (doubled) timeout.
            OllamaModelNotLoadedError: the requested model is not present.
            LLMRuntimeError: any other engine failure.
        """
        # RAM guard (task 4.3.3): abort before the call if free RAM is too low
        # to risk an OOM kill mid-inference. No daemon contact on this path.
        check_ram_guard()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        options: dict[str, object] = {
            "temperature": temperature,
            "num_predict": max_tokens,
        }
        return self._chat_with_retry(
            messages=messages, model=model, options=options, timeout=timeout
        )

    def _chat_with_retry(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, object],
        timeout: float,
    ) -> str:
        """Call ``client.chat`` once, retrying once on timeout with 2x timeout."""
        try:
            response = self._client.chat(
                model=model,
                messages=messages,
                options=options,
                keep_alive=timeout,
            )
        except TimeoutError as err:
            return self._retry_on_timeout(
                messages=messages, model=model, options=options, timeout=timeout,
                first_err=err,
            )
        except Exception as err:  # ollama.ResponseError / httpx.* / others
            if "timeout" in str(err).lower() or "timed out" in str(err).lower():
                return self._retry_on_timeout(
                    messages=messages, model=model, options=options,
                    timeout=timeout, first_err=err,
                )
            raise _translate_engine_error(err, model, self._host) from err
        return self._extract_content(response, model)

    def _retry_on_timeout(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, object],
        timeout: float,
        first_err: BaseException,
    ) -> str:
        """Retry once with a doubled timeout; raise on a second failure."""
        try:
            response = self._client.chat(
                model=model,
                messages=messages,
                options=options,
                keep_alive=timeout * 2,
            )
        except Exception as err:
            translated: LLMRuntimeError = _translate_engine_error(
                err, model, self._host
            )
            raise translated from first_err
        return self._extract_content(response, model)

    @staticmethod
    def _extract_content(response: object, model: str) -> str:
        """Pull the assistant message text out of the chat response."""
        message: object = getattr(response, "message", None)
        if message is None:
            raise LLMRuntimeError(
                f"Ollama returned no message for model '{model}'"
            )
        content: object = getattr(message, "content", None)
        if not isinstance(content, str):
            raise LLMRuntimeError(
                f"Ollama returned non-string content for model '{model}'"
            )
        return content
