"""
Lightweight in-memory TTL cache for API responses.
"""
from __future__ import annotations

import time
import threading
import hashlib
import json
from functools import wraps
from typing import Any, Callable


class TTLCache:
    """Thread-safe TTL cache with key-based expiry."""

    def __init__(self):
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: float):
        with self._lock:
            self._store[key] = (time.time() + ttl, value)

    def invalidate(self, prefix: str = ""):
        """Remove all keys matching prefix (empty = flush all)."""
        with self._lock:
            if not prefix:
                self._store.clear()
            else:
                keys_to_del = [k for k in self._store if k.startswith(prefix)]
                for k in keys_to_del:
                    del self._store[k]

    def cleanup_expired(self):
        """Remove all expired entries."""
        now = time.time()
        with self._lock:
            expired = [k for k, (exp, _) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]


# Global cache instance
cache = TTLCache()


def cached(ttl: float = 300, prefix: str = "", key_func: Callable | None = None):
    """Decorator to cache function results with TTL.

    Args:
        ttl: Cache lifetime in seconds (default 5 min)
        prefix: Cache key prefix for group invalidation
        key_func: Custom function to generate cache key from args.
                  Defaults to using all positional args + sorted kwargs.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if key_func:
                cache_key = f"{prefix}:{key_func(*args, **kwargs)}"
            else:
                # Build key from function name + args
                parts = [fn.__module__, fn.__qualname__]
                if args:
                    parts.append(json.dumps(args, default=str, ensure_ascii=False))
                if kwargs:
                    parts.append(json.dumps(kwargs, sort_keys=True, default=str, ensure_ascii=False))
                raw = "|".join(parts)
                cache_key = f"{prefix}:{hashlib.md5(raw.encode()).hexdigest()}"

            result = cache.get(cache_key)
            if result is not None:
                return result

            result = fn(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator
