"""统一 TTL 缓存模块

替代各文件自行维护的 _cache = {} 字典。
支持：TTL 过期 + 最大条目数（防止内存泄漏）

用法:
    quote_cache = TTLCache(maxsize=500, ttl=30)
    quote_cache.set('600519', {...})
    result = quote_cache.get('600519')  # 过期返回 None
    quote_cache.clear()
"""
import time
from typing import Any, Optional


class TTLCache:
    def __init__(self, maxsize: int = 200, ttl: int = 300, name: str = ""):
        self._data: dict = {}
        self.maxsize = maxsize
        self.ttl = ttl
        self.name = name or f"cache_{id(self)}"

    def get(self, key: str) -> Optional[Any]:
        entry = self._data.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self.ttl:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._data) >= self.maxsize:
            self._evict_half()
        self._data[key] = (time.time(), value)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def _evict_half(self) -> None:
        sorted_items = sorted(self._data.items(), key=lambda x: x[1][0])
        for k, _ in sorted_items[:len(sorted_items) // 2]:
            del self._data[k]
