"""Small in-process sliding-window limiter for public endpoints.
Per-process only: production deployments should also rate-limit at the reverse proxy (see deploy/nginx.conf)."""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests. Try again in a minute.")
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


booking_limiter = RateLimiter(limit=10, window_seconds=600)
public_read_limiter = RateLimiter(limit=240, window_seconds=60)
login_limiter = RateLimiter(limit=20, window_seconds=300)
forgot_limiter = RateLimiter(limit=5, window_seconds=900)
