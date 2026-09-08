"""BS 点策略回测 API 包
将原 backend/api/bs_backtest.py（810行）拆为：
- engine.py   核心回测引擎（_backtest_single, _calc_stats, _calc_trade_fee, _calc_hold_days）
- run.py      POST /api/bs-screener/backtest  单股+组合回测
- history.py  POST /api/bs-screener/backtest/save  +  GET /history  +  DELETE
"""
from fastapi import APIRouter
from .run import router as run_router
from .history import router as history_router

router = APIRouter()
router.include_router(run_router)
router.include_router(history_router)


# 公开核心函数供其他模块复用
from .engine import (
    _backtest_single, _calc_stats, _calc_trade_fee, _calc_hold_days,
    COMMISSION_RATE, STAMP_TAX_RATE, MIN_TRADE_FEE,
)

__all__ = [
    "router",
    "_backtest_single", "_calc_stats", "_calc_trade_fee", "_calc_hold_days",
    "COMMISSION_RATE", "STAMP_TAX_RATE", "MIN_TRADE_FEE",
]
