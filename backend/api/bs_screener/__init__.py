"""BS 点选股 API 包
将原 backend/api/bs_screener.py（600行）拆为：
- core.py       扫描核心（_execute_bs_scan_core, _scan_single_stock, _get_quote, _fetch_kline_cached, _kline_cache）
- run.py        GET /api/bs-screener/run
- today.py      GET /api/bs-screener/today  +  GET /api/bs-screener/strategy-picks
- strategies.py 策略 CRUD（list/save/delete）
"""
from fastapi import APIRouter
import api.bs_screener.run
import api.bs_screener.today
import api.bs_screener.strategies
from .run import router as run_router
from .today import router as today_router
from .strategies import router as strategies_router

router = APIRouter()
router.include_router(run_router)
router.include_router(today_router)
router.include_router(strategies_router)


# 公开核心函数供其他模块复用
from .core import (
    _kline_cache, _KLINE_CACHE_TTL, _fetch_kline_cached, _get_quote,
    _scan_single_stock, _execute_bs_scan_core,
)

__all__ = [
    "router",
    "_kline_cache", "_KLINE_CACHE_TTL", "_fetch_kline_cached", "_get_quote",
    "_scan_single_stock", "_execute_bs_scan_core",
]
