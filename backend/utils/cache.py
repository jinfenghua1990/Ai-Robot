"""统一缓存装饰器
- 单 worker 内存缓存（多 worker 部署需迁 Redis）
- 支持 TTL + 手动失效
- 线程安全（threading.Lock）
- 支持参数化 key（key_fn 从 args/kwargs 生成缓存键）
- 同一装饰器自动适配 sync / async 函数（消除重复实现）

【命名规范】（P1-#15 统一）
- 所有模块级缓存对象必须以 `_cache` 后缀命名，禁止使用 `_memo` / `_store` / `_buffer` / `_map` 等
- 单值带 TTL 的缓存：使用 TTLCache（多 key）或 dict-of-dict 模式 `{'data': ..., 'ts': ...}`（单 key）
- 多 key 缓存：使用 BoundedDict(maxsize=N) 防止内存无限增长
"""
import time
import threading
import functools
import inspect
from typing import Any, Callable, Optional
import logging

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_registry: dict = {}  # full_cache_name -> {'data':..., 'ts':..., 'ttl':...}
_MAX_ENTRIES = 1000


def _evict_expired():
    """惰性清理：移除所有过期条目；若仍超限则淘汰最旧的 20%"""
    now = time.time()
    expired = [k for k, v in _registry.items() if now - v['ts'] >= v['ttl']]
    for k in expired:
        del _registry[k]
    if len(_registry) > _MAX_ENTRIES:
        # 仍超限：按写入时间排序，淘汰最旧的 20%
        sorted_keys = sorted(_registry.keys(), key=lambda k: _registry[k]['ts'])
        for k in sorted_keys[:max(len(sorted_keys) // 5, 1)]:
            del _registry[k]


def _make_key(name: str, args: tuple, kwargs: dict, key_fn: Optional[Callable]) -> str:
    """生成缓存键；key_fn 优先，否则回退到 args+kwargs repr。"""
    if key_fn:
        return f"{name}:{key_fn(*args, **kwargs)}"
    return name


def _read_cache(cache_key: str):
    """线程安全读取；命中且未过期返回 data，否则返回 None。"""
    with _lock:
        entry = _registry.get(cache_key)
        if entry and time.time() - entry['ts'] < entry['ttl']:
            return entry['data']
        return None


def _write_cache(cache_key: str, data: Any, ttl: int) -> None:
    """线程安全写入并触发惰性清理。"""
    with _lock:
        _registry[cache_key] = {'data': data, 'ts': time.time(), 'ttl': ttl}
        _evict_expired()


def cached(name: str, ttl: int = 60, key_fn: Optional[Callable] = None):
    """统一缓存装饰器（自动适配 sync / async 函数）

    Args:
        name: 缓存命名空间（全局唯一前缀）
        ttl: 缓存有效期（秒）
        key_fn: 可选，从 (*args, **kwargs) 返回缓存键后缀。
                若为 None 则用全部 args+kwargs 的 repr。
                对于无参函数可省略。

    行为：
        - sync 函数：直接调用并缓存结果
        - async 函数：await 调用并缓存结果
        - 调用时可传 _force_refresh=True 跳过缓存
    """
    def decorator(fn):
        is_coro = inspect.iscoroutinefunction(fn)

        if is_coro:
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                force = kwargs.pop('_force_refresh', False)
                cache_key = _make_key(name, args, kwargs, key_fn)
                if not force:
                    hit = _read_cache(cache_key)
                    if hit is not None:
                        return hit
                data = await fn(*args, **kwargs)
                _write_cache(cache_key, data, ttl)
                return data
            wrapper = async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args, **kwargs):
                force = kwargs.pop('_force_refresh', False)
                cache_key = _make_key(name, args, kwargs, key_fn)
                if not force:
                    hit = _read_cache(cache_key)
                    if hit is not None:
                        return hit
                data = fn(*args, **kwargs)
                _write_cache(cache_key, data, ttl)
                return data
            wrapper = sync_wrapper

        wrapper.invalidate = lambda: invalidate_prefix(name)  # type: ignore[attr-defined]
        wrapper._cache_name = name
        return wrapper
    return decorator


# 向后兼容别名：保留旧名以避免外部调用中断
async_cached = cached


def invalidate(name: str) -> bool:
    """手动失效某个缓存（精确匹配）"""
    with _lock:
        return _registry.pop(name, None) is not None


def invalidate_prefix(prefix: str) -> int:
    """批量失效（按前缀，含 namespace:key 形式）"""
    with _lock:
        keys = [k for k in _registry if k == prefix or k.startswith(prefix + ':')]
        for k in keys:
            _registry.pop(k, None)
        return len(keys)


def cache_status() -> dict:
    """获取所有缓存状态（用于 /api/health/cache）"""
    with _lock:
        now = time.time()
        return {
            name: {
                'age_seconds': round(now - e['ts'], 1),
                'ttl_seconds': e['ttl'],
                'expired': now - e['ts'] > e['ttl'],
            }
            for name, e in _registry.items()
        }


class BoundedDict(dict):
    """有上限的字典缓存，超出 maxsize 时淘汰最旧条目（FIFO）。

    用于替代模块级裸字典缓存，防止内存无限增长。

    用法:
        _cache = BoundedDict(maxsize=200)  # 最多 200 个 key
        _cache[key] = value                 # 超限时自动淘汰最早写入的 key
    """

    def __init__(self, maxsize: int = 200, *args, **kwargs):
        self._maxsize = maxsize
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        if len(self) >= self._maxsize and key not in self:
            # 淘汰最早写入的 key（FIFO）
            oldest = next(iter(self))
            del self[oldest]
        super().__setitem__(key, value)


class TTLCache:
    """带 TTL 的缓存，替代手动 {'data':.., 'ts':..} 模式。

    用法:
        cache = TTLCache(ttl=300)
        cache.set(key, data)
        data = cache.get(key)  # 过期返回 None
    """

    def __init__(self, ttl: int = 300, maxsize: int = 200):
        self._ttl = ttl
        self._maxsize = maxsize
        self._store: dict = {}
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            if time.time() - entry['ts'] >= self._ttl:
                del self._store[key]
                return default
            return entry['data']

    def set(self, key, data):
        with self._lock:
            if len(self._store) >= self._maxsize and key not in self._store:
                oldest = min(self._store, key=lambda k: self._store[k]['ts'])
                del self._store[oldest]
            self._store[key] = {'data': data, 'ts': time.time()}

    def invalidate(self, key=None):
        """失效单个 key 或全部"""
        with self._lock:
            if key:
                self._store.pop(key, None)
            else:
                self._store.clear()

    def __len__(self):
        return len(self._store)

    def __contains__(self, key):
        return self.get(key) is not None
