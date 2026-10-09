"""In-memory sliding-window rate limiter."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float = 3600.0) -> bool:
        """Record a hit; returns False if the key is over its limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            if len(self._hits) > 50_000:
                self._prune(now, window)
            return True

    def _prune(self, now: float, window: float) -> None:
        for k in [k for k, v in self._hits.items() if not v or now - v[-1] > window]:
            del self._hits[k]


limiter = RateLimiter()
