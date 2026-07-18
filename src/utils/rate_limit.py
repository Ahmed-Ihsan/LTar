"""Thread-safe token bucket rate limiter."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """A simple thread-safe token bucket for rate limiting.

    Args:
        rate: Tokens added per second.
        capacity: Maximum tokens the bucket can hold.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, cost: float = 1.0) -> bool:
        """Try to acquire *cost* tokens.

        Returns:
            ``True`` if tokens were available (and consumed), ``False``
            otherwise. This method does not block.
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False
