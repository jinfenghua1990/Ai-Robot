"""统一缓存装饰器
- 单 worker 内存缓存（多 worker 部署需迁 Redis）
- 支持 TTL + 手动失效
- 线程安全（threading.Lock）
- 支持参数化 key（key_fn 从 args/kwargs 生成缓存键）
"""
import time
import threading
import functools
from typing import Any, Callable, Optional
import logging

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_registry: dict = {}  # full_cache_name -> {'data':..., 'ts':..., 'ttl':...}


def cached(name: str, ttl: int = 60, key_fn: Optional[Callable] = None):
    """同步函数缓存装饰器

    Args:
        name: 缓存命名空间（全局唯一前缀）
        ttl: 缓存有效期（秒）
        key_fn: 可选，从 (*args, **kwargs) 返回缓存键后缀。
                若为 None 则用全部 args+kwargs 的 repr。
                对于无参函数可省略。
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            force = kwargs.pop('_force_refresh', False)
            cache_key = f"{name}:{key_fn(*args, **kwargs)}" if key_fn else name
            if not force:
                with _lock:
                    entry = _registry.get(cache_key)
                    if entry and time.time() - entry['ts'] < entry['ttl']:
                        return entry['data']
            data = fn(*args, **kwargs)
            with _lock:
                _registry[cache_key] = {'data': data, 'ts': time.time(), 'ttl': ttl}
            return data
        wrapper.invalidate = lambda: invalidate_prefix(name)
        wrapper._cache_name = name
        return wrapper
    return decorator


def async_cached(name: str, ttl: int = 60, key_fn: Optional[Callable] = None):
    """异步函数缓存装饰器"""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            force = kwargs.pop('_force_refresh', False)
            cache_key = f"{name}:{key_fn(*args, **kwargs)}" if key_fn else name
            if not force:
                with _lock:
                    entry = _registry.get(cache_key)
                    if entry and time.time() - entry['ts'] < entry['ttl']:
                        return entry['data']
            data = await fn(*args, **kwargs)
            with _lock:
                _registry[cache_key] = {'data': data, 'ts': time.time(), 'ttl': ttl}
            return data
        wrapper.invalidate = lambda: invalidate_prefix(name)
        wrapper._cache_name = name
        return wrapper
    return decorator


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
