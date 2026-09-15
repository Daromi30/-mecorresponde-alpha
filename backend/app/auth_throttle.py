from __future__ import annotations

import hashlib
import threading
import time
from collections import deque

from fastapi import HTTPException


class LoginThrottle:
    """Small single-instance alpha throttle keyed by a one-way email digest.

    This deliberately does not retain raw email addresses or IP addresses. It is
    a first layer for the current one-instance alpha, not a replacement for an
    edge/distributed rate limiter before a scaled public launch.
    """

    def __init__(self, limit: int = 8, window_seconds: int = 15 * 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(email: str) -> str:
        return hashlib.sha256(email.encode("utf-8")).hexdigest()

    def _prune(self, key: str, current: float) -> deque[float]:
        bucket = self._failures.setdefault(key, deque())
        cutoff = current - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if not bucket:
            self._failures.pop(key, None)
            return deque()
        return bucket

    def check(self, email: str) -> None:
        key = self._key(email)
        current = time.monotonic()
        with self._lock:
            bucket = self._prune(key, current)
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (current - bucket[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Too many login attempts. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )

    def fail(self, email: str) -> None:
        key = self._key(email)
        current = time.monotonic()
        with self._lock:
            bucket = self._prune(key, current)
            if key not in self._failures:
                bucket = deque()
                self._failures[key] = bucket
            bucket.append(current)

    def success(self, email: str) -> None:
        with self._lock:
            self._failures.pop(self._key(email), None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()
