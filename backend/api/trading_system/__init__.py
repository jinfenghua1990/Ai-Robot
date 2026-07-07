"""游资系统 4.0 API 包"""
from fastapi import APIRouter
from .daily_report import router as daily_report_router
from .risk import router as risk_router
from .backtest import router as backtest_router

router = APIRouter()
router.include_router(daily_report_router)
router.include_router(risk_router)
router.include_router(backtest_router)

__all__ = ["router"]
