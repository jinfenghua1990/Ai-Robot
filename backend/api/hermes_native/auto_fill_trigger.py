"""
统一的 auto_fill 触发守卫。

背景:
- 原 /api/market-review 在构建数据前会调用 request_auto_fill()，它会检查各核心表
  (index_data / market_sentiment_daily / limit_up_pool_daily / 板块 / 龙头 等) 的最新
  交易日，若滞后则拉起后台采集进程 (robot1_auto_refill.py --watch) 持续灌数。
- 拆分后的独立端点 (themes / market / fundflow / rotation) 取代了 market-review，
  必须保持同样的行为，否则在孤立调用时底层 get_index_data 等会因数据缺失而静默降级为空。

设计:
- 进程内守卫: 同一日期 60 秒内只真正触发一次 request_auto_fill，避免多个端点并发
  请求时重复拉起后台 watcher。
- 任何异常都被吞掉，保证不会因 auto_fill 失败而中断端点响应。
"""

from __future__ import annotations

import time as _time_module
from typing import Any, Optional, Optional

try:
    from api.hermes_native.services.auto_fill_engine import request_auto_fill as _request_auto_fill
except ImportError:  # pragma: no cover - 包模式回退
    try:
        from ..services.auto_fill_engine import request_auto_fill as _request_auto_fill
    except ImportError:
        _request_auto_fill = None

# 同一日期 60 秒冷却，避免重复触发
_COOLDOWN_SECONDS: float = 60.0
_last_trigger: dict[str, float] = {}


def ensure_auto_fill(review_date: str) -> Optional[dict[str, Any]]:
    """
    在构建数据前确保后台自动补数已触发（与原 market-review 行为一致）。

    返回 request_auto_fill 的结果，或在守卫拦截/不可用时返回 None。
    """
    if _request_auto_fill is None:
        return None

    now = _time_module.time()
    last = _last_trigger.get(review_date)
    if last is not None and now - last < _COOLDOWN_SECONDS:
        return None  # 冷却期内，跳过

    _last_trigger[review_date] = now
    try:
        return _request_auto_fill(review_date)
    except Exception:
        # 自动补数失败不应影响端点本身
        return None
