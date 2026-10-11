"""Tiny in-memory sliding-window rate limiter for POST /auth/login.

Counters live in this process only: with N replicas the effective limit is N x the
configured value. That is fine for brute-force protection; use Redis if you need exact.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.metrics import LOGINS

WINDOW_SECONDS = 60


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> int | None:
        """Record a request. Returns None if allowed, else seconds until retry."""
        now = time.monotonic()
        with self._lock:
            window = self._hits[key]
            while window and now - window[0] >= WINDOW_SECONDS:
                window.popleft()
            if len(window) >= limit:
                return max(1, int(WINDOW_SECONDS - (now - window[0])) + 1)
            window.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    if get_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def login_rate_limit(request: Request) -> None:
    retry_after = login_limiter.hit(client_ip(request), get_settings().login_rate_limit_per_minute)
    if retry_after is not None:
        LOGINS.labels(result="rate_limited").inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
