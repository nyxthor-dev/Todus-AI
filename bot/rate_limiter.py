"""
Rate limiter por usuario.

Reglas:
- Owner: ilimitado (siempre allow)
- Grupos (usuarios normales): LIMIT_GROUP peticiones por minuto
- Privado (usuarios normales, no-owner): LIMIT_PRIVATE peticiones por minuto
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from .config import settings


class RateLimiter:
    """Token-bucket sliding-window por usuario."""

    def __init__(
        self,
        owner_phone: str,
        limit_private: int = None,
        limit_group: int = None,
        window_seconds: int = 60,
    ):
        self.owner = owner_phone
        self.limit_private = limit_private if limit_private is not None else settings.limit_private
        self.limit_group = limit_group if limit_group is not None else settings.limit_group
        self.window = window_seconds
        self._buckets_private: dict[str, deque[float]] = defaultdict(deque)
        self._buckets_group: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    def _allow(self, bucket: dict, key: str, limit: int) -> bool:
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            dq = bucket[key]
            # limpiar viejos
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                return False
            dq.append(now)
            return True

    def _remaining(self, bucket: dict, key: str, limit: int) -> int:
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            dq = bucket[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            return max(0, limit - len(dq))

    def is_owner(self, phone: str) -> bool:
        return phone == self.owner

    def allow_private(self, phone: str) -> bool:
        if self.is_owner(phone):
            return True
        return self._allow(self._buckets_private, phone, self.limit_private)

    def allow_group(self, phone: str) -> bool:
        if self.is_owner(phone):
            return True
        return self._allow(self._buckets_group, phone, self.limit_group)

    def remaining_private(self, phone: str) -> int:
        if self.is_owner(phone):
            return 999
        return self._remaining(self._buckets_private, phone, self.limit_private)

    def remaining_group(self, phone: str) -> int:
        if self.is_owner(phone):
            return 999
        return self._remaining(self._buckets_group, phone, self.limit_group)

    def reset(self, phone: str) -> None:
        with self._lock:
            self._buckets_private.pop(phone, None)
            self._buckets_group.pop(phone, None)
