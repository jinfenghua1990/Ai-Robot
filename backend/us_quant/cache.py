"""
US Quant System — 简单缓存层

V2.2: 减少 API 重复计算，缓存扫描结果。
"""

from __future__ import annotations

import time
import logging
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TTLCache:
    """时间感知缓存，支持 TTL 过期"""

    def __init__(self, default_ttl: int = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if now > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        ttl = ttl if ttl is not None else self.default_ttl
        self._store[key] = (time.time() + ttl, value)

    def delete(self, key: str):
        self._store.pop(key, None)

    def clear(self):
        self._store.clear()

    def keys(self) -> list[str]:
        return list(self._store.keys())


# 全局缓存实例
scanner_cache = TTLCache(default_ttl=120)  # 扫描结果缓存 2 分钟
kline_cache = TTLCache(default_ttl=60)     # K 线数据缓存 1 分钟


def make_cache_key(scanner: bool = False, **kwargs) -> str:
    """生成缓存 key"""
    parts = sorted(f"{k}={v}" for k, v in kwargs.items() if v)
    prefix = "scanner" if scanner else "kline"
    return f"{prefix}:{'|'.join(parts)}"


def cached_scanner(ttl: int = 120):
    """装饰器：缓存扫描结果"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            key = make_cache_key(scanner=True, **kwargs)
            cached = scanner_cache.get(key)
            if cached is not None:
                logger.debug(f"[cache] 命中 scanner: {key}")
                return cached
            result = func(*args, **kwargs)
            scanner_cache.set(key, result, ttl=ttl)
            return result
        return wrapper
    return decorator