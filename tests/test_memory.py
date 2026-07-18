"""RAM-guard + memory-reading tests for task 4.3.3 (``src/memory.py``).

Covers:
- ``read_memory_info`` returns a real :class:`MemoryInfo` on this host (the
  doctor command depends on it).
- ``check_ram_guard`` raises :class:`RAMGuardError` when available RAM is below
  the 1.5 GB threshold (the 4.3.3 verify step), does not raise when there is
  enough RAM, and does not raise when RAM cannot be measured (cannot guard
  against an unknown value — proceed rather than blocking).
- :class:`OllamaEngineAdapter.generate` invokes the guard *before* the chat
  call, so a low-RAM condition aborts without contacting the daemon.

The adapter test patches ``src.llm.check_ram_guard`` (the seam the adapter
calls) and uses a mock Ollama client so no daemon and no network are required
(testing-verification §3.4).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.components.infrastructure.memory import (
    RAM_GUARD_MIN_GB,
    MemoryInfo,
    check_ram_guard,
    read_memory_info,
)
from src.components.translation_pipeline.exceptions import RAMGuardError

pytestmark = pytest.mark.adapter


class TestReadMemoryInfo:
    def test_returns_memory_info_on_this_host(self) -> None:
        mem: MemoryInfo | None = read_memory_info()
        # On Windows/Linux (the supported targets) this must succeed.
        assert mem is not None
        assert mem.total_bytes > 0
        assert mem.available_bytes >= 0
        assert mem.available_bytes <= mem.total_bytes


class TestRamGuard:
    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        import src.components.infrastructure.memory as mem_mod

        mem_mod._ram_guard_cache_ok.clear()

    def test_raises_when_available_below_threshold(self) -> None:
        low: MemoryInfo = MemoryInfo(
            total_bytes=8 * 1024 ** 3,
            available_bytes=int(0.5 * 1024 ** 3),  # 0.5 GB free
        )
        with patch("src.components.infrastructure.memory.read_memory_info", return_value=low):
            with pytest.raises(RAMGuardError, match="RAM"):
                check_ram_guard()

    def test_does_not_raise_when_available_above_threshold(self) -> None:
        ok: MemoryInfo = MemoryInfo(
            total_bytes=16 * 1024 ** 3,
            available_bytes=int(4.0 * 1024 ** 3),  # 4 GB free
        )
        with patch("src.components.infrastructure.memory.read_memory_info", return_value=ok):
            check_ram_guard()  # must not raise

    def test_does_not_raise_when_memory_unreadable(self) -> None:
        """Cannot measure -> cannot prove low -> proceed (do not block)."""
        with patch("src.components.infrastructure.memory.read_memory_info", return_value=None):
            check_ram_guard()  # must not raise

    def test_threshold_is_1_5_gb(self) -> None:
        assert RAM_GUARD_MIN_GB == 1.5

    def test_boundary_just_below_threshold_raises(self) -> None:
        boundary: MemoryInfo = MemoryInfo(
            total_bytes=8 * 1024 ** 3,
            available_bytes=int(1.49 * 1024 ** 3),
        )
        with patch("src.components.infrastructure.memory.read_memory_info", return_value=boundary):
            with pytest.raises(RAMGuardError):
                check_ram_guard()


class TestAdapterRamGuard:
    def test_generate_aborts_before_chat_when_ram_low(self) -> None:
        """The guard runs before the daemon call — chat is never contacted."""
        from src.components.infrastructure.llm import OllamaEngineAdapter

        fake_client: MagicMock = MagicMock()
        adapter: OllamaEngineAdapter = OllamaEngineAdapter(
            client=fake_client, model="qwen2.5:7b-instruct-q5_K_M",
            host="http://localhost:11434",
        )
        with patch(
            "src.components.infrastructure.llm.check_ram_guard",
            side_effect=RAMGuardError("only 0.4 GB free; aborting to avoid OOM"),
        ):
            with pytest.raises(RAMGuardError):
                adapter.generate(
                    "system", "user",
                    model="qwen2.5:7b-instruct-q5_K_M",
                )
        fake_client.chat.assert_not_called()

    def test_generate_proceeds_when_ram_sufficient(self) -> None:
        """When the guard passes, the chat call proceeds normally."""
        from src.components.infrastructure.llm import OllamaEngineAdapter

        fake_client: MagicMock = MagicMock()
        fake_response: MagicMock = MagicMock()
        fake_response.message.content = "translation output"
        fake_client.chat.return_value = fake_response
        adapter: OllamaEngineAdapter = OllamaEngineAdapter(
            client=fake_client, model="qwen2.5:7b-instruct-q5_K_M",
            host="http://localhost:11434",
        )
        with patch("src.components.infrastructure.llm.check_ram_guard", return_value=None):
            out: str = adapter.generate(
                "system", "user",
                model="qwen2.5:7b-instruct-q5_K_M",
            )
        assert out == "translation output"
        fake_client.chat.assert_called_once()
