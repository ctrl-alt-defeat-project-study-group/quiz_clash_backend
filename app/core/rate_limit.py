"""
Simple in-memory sliding-window rate limiter for auth endpoints.
"""
from collections import defaultdict, deque
import threading
import time
from typing import Deque, Dict, Tuple

from fastapi import Request

from app.core.config import settings
from app.core.security import api_error


class InMemoryRateLimiter:
    """Thread-safe sliding-window rate limiter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def check(self, bucket: str, key: str, max_requests: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            dq = self._hits[(bucket, key)]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= max_requests:
                raise api_error(
                    429,
                    "RATE_LIMITED",
                    "Too many requests. Please try again later.",
                )
            dq.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = InMemoryRateLimiter()


def rate_limit_auth(bucket: str):
    """FastAPI dependency enforcing rate limits on auth endpoints."""

    def _dependency(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        rate_limiter.check(
            bucket=bucket,
            key=client_ip,
            max_requests=settings.RATE_LIMIT_AUTH_MAX_REQUESTS,
            window_seconds=settings.RATE_LIMIT_AUTH_WINDOW_SECONDS,
        )

    return _dependency
