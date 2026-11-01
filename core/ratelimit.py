"""Simple in-memory rate limiter."""
from __future__ import annotations
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_calls=10, window=60):
        self.max_calls = max_calls
        self.window = window
        self._calls = defaultdict(deque)

    def allow(self, key):
        now = time.time()
        q = self._calls[key]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.max_calls:
            return False
        q.append(now)
        return True