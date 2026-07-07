"""GET /api/bs-screener/run  实时扫描"""
import time
from fastapi import APIRouter, Query

from db.connection import get_db
from db.session import get_db_session
from .core import _scan_cache, _execute_bs_scan_core

router = APIRouter()


@router.get("/api/bs-screener/run")
async def run_bs_screener(
    atr_period: int = Query(10, description="ATR周期"),
    atr_multiplier: float = Query(1.0, description="ATR乘数"),
    scan_limit: int = Query(50, description="扫描股票数量"),
    sector: str = Query('', description="板块筛选(逗号分隔)"),
    signal_type: str = Query('B', description="信号类型: B/S/ALL"),
    volume_filter: bool = Query(False),
    ma20_filter: bool = Query(False),
    ma60_trend: bool = Query(False),
    rsi_filter: bool = Query(False),
    strong_volume: bool = Query(False),
    macd_filter: bool = Query(False),
    kdj_filter: bool = Query(False),
    rsi_lower: int = Query(30),
    rsi_upper: int = Query(70),
    dimension: str = Query('', description="维度筛选: star=科创板 chinext=创业板 all=全A股"),
):
    """运行 BS 选股扫描"""
    params_key = f"{atr_period}_{atr_multiplier}_{scan_limit}_{sector}_{signal_type}_{volume_filter}_{ma20_filter}_{ma60_trend}_{rsi_filter}_{strong_volume}_{dimension}"
    if _scan_cache['data'] and time.time() - _scan_cache['ts'] < 30 and _scan_cache['params_key'] == params_key:
        return _scan_cache['data']

    with get_db_session() as db:
        result = await _execute_bs_scan_core(
            db,
            atr_period=atr_period, atr_multiplier=atr_multiplier, scan_limit=scan_limit,
            sector=sector, signal_type=signal_type,
            volume_filter=volume_filter, ma20_filter=ma20_filter, ma60_trend=ma60_trend,
            rsi_filter=rsi_filter, strong_volume=strong_volume,
            macd_filter=macd_filter, kdj_filter=kdj_filter,
            rsi_lower=rsi_lower, rsi_upper=rsi_upper, dimension=dimension,
        )
        _scan_cache['data'] = result
        _scan_cache['ts'] = time.time()
        _scan_cache['params_key'] = params_key
        return result
