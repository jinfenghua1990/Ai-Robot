"""
板块全景个股增强 API
- /api/panorama/stocks  批量将个股代码列表增强为完整 18 字段 signal 数据
"""
import logging
from fastapi import APIRouter, Body
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import func
from db.connection import get_db
from db.session import get_db_session
from db.models import WatchlistSignalDaily
from services.signal_builder import build_signal_for_stock, build_signal_from_precomputed
import asyncio

router = APIRouter()
logger = logging.getLogger(__name__)


class StockItem(BaseModel):
    ts_code: str
    name: str = ''
    sector: str = ''
    main_force_inflow: Optional[float] = None
    price_chg: Optional[float] = None


class EnrichRequest(BaseModel):
    stocks: List[StockItem]


def _normalize_ts_code(code: str) -> str:
    """统一转成 600000.SH / 000001.SZ 格式"""
    if '.' in code:
        return code
    return f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"


def _load_precomputed_map(db, stocks: list) -> dict:
    """同步查预计算表（最近交易日），返回 {normalized_ts_code: row}"""
    precomputed_map = {}
    ts_codes = []
    for item in stocks:
        code = item.ts_code.split('.')[0] if '.' in item.ts_code else item.ts_code
        if code and len(code) == 6:
            ts_codes.append(_normalize_ts_code(code))
    if not ts_codes:
        return precomputed_map
    latest_date = db.query(func.max(WatchlistSignalDaily.trade_date)).scalar()
    if latest_date:
        rows = db.query(WatchlistSignalDaily).filter(
            WatchlistSignalDaily.trade_date == latest_date,
            WatchlistSignalDaily.ts_code.in_(ts_codes),
        ).all()
        for row in rows:
            precomputed_map[row.ts_code] = row
    return precomputed_map


@router.post("/api/panorama/stocks")
async def enrich_panorama_stocks(req: EnrichRequest = Body(...)):
    """批量增强个股列表为完整 signal 数据（用于板块全景个股列表展示）

    优先读预计算表（WatchlistSignalDaily），命中则跳过 K线/BS/板块现场计算；
    未命中才 fallback 到 build_signal_for_stock。
    """
    if not req.stocks:
        return {'stocks': []}

    with get_db_session() as db:
        # 批量查预计算表（丢线程池避免阻塞事件循环）
        precomputed_map = await run_in_threadpool(_load_precomputed_map, db, req.stocks)

        async def _enrich(item: StockItem):
            ts_code = item.ts_code
            code = ts_code.split('.')[0] if '.' in ts_code else ts_code
            if not code or len(code) != 6:
                return None
            try:
                normalized = _normalize_ts_code(code)
                precomputed = precomputed_map.get(normalized)
                if precomputed:
                    signal = await build_signal_from_precomputed(
                        code, item.name, precomputed, db=db,
                    )
                else:
                    signal = await build_signal_for_stock(
                        code, item.name, item.sector, db,
                        change_rate=item.price_chg,
                    )
                signal['mainForceInflow'] = item.main_force_inflow or 0
                signal['priceChg'] = item.price_chg or 0
                return signal
            except Exception as e:
                logger.warning(f'enrich {ts_code} failed: {e}')
                return None

        tasks = [_enrich(item) for item in req.stocks]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        enriched = [r for r in results if r is not None and not isinstance(r, Exception)]

        return {'stocks': enriched}
