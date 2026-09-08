"""指数每日行情日表（常规维护 + 历史补采）

数据完全来自本地 stock_flow 表按指数成分股聚合（纯 DB，无外部采集），
与「指数资金流向 rank」同口径：
- close      = 成分股均价（代理点位）
- pct_change = 成分股平均涨跌幅（%）

用途：dashboard 强弱对比、指数相关页面做“常规”读取，避免每次现场聚合；
每日收盘后由 scheduler 定时写入，历史缺失通过 backfill 补齐。

范围：仅维护在 MAJOR_INDICES 中定义了成分股列表的宽基指数
（沪深300/上证50/中证500/中证1000/科创50/上证红利/创业板指/中小板指/深证50），
上证指数/深证成指为“全市场前缀”口径、代理点位无意义，不纳入。
"""
import logging
from fastapi import APIRouter, Query
from sqlalchemy import func

from db.session import get_db_session
from db.models import IndexDaily, StockFlow

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_member_indices():
    """返回 MAJOR_INDICES 中有成分股列表的宽基指数定义列表。"""
    from api.index_flow import MAJOR_INDICES
    return [i for i in MAJOR_INDICES if i.get('members')]


def _resolve_members(idx_def, db):
    """解析成分股；仅用静态列表，不强拉远程成分股。"""
    from api.index_flow import _resolve_index_members
    return _resolve_index_members(idx_def, allow_remote_constituents=False)


def _aggregate_days(idx_def, members, db, days: int):
    """对某指数在最近 days 个交易日内按 stock_flow 聚合每日涨跌。

    只保留有真实涨跌幅（|pct|>1e-6）的交易日——盘中/盘中快照全 0 的采集日会被跳过。
    返回 {trade_date(date): {'close','pct_change','member_count'}}
    """
    if not members:
        return {}
    recent = [r[0] for r in db.query(StockFlow.trade_date).distinct().order_by(
        StockFlow.trade_date.desc()).limit(days)]
    if not recent:
        return {}
    rows = db.query(
        StockFlow.trade_date,
        func.avg(StockFlow.price_chg).label('chg'),
        func.avg(StockFlow.price).label('px'),
        func.count('*').label('cnt'),
    ).filter(
        StockFlow.trade_date.in_(recent),
        StockFlow.ts_code.in_(members),
    ).group_by(StockFlow.trade_date).order_by(StockFlow.trade_date.desc()).all()

    out = {}
    for r in rows:
        chg = float(r.chg or 0)
        if abs(chg) > 1e-6:
            px = float(r.px or 0)
            out[r.trade_date] = {
                'close': round(px, 4) if px else None,
                'pct_change': round(chg, 2),
                'member_count': int(r.cnt or 0),
            }
    return out


def _upsert(db, ts_code: str, name: str, day, agg: dict):
    rec = db.query(IndexDaily).filter_by(ts_code=ts_code, trade_date=day).first()
    if rec:
        rec.close = agg['close']
        rec.pct_change = agg['pct_change']
        rec.member_count = agg['member_count']
    else:
        db.add(IndexDaily(
            ts_code=ts_code, name=name, trade_date=day,
            close=agg['close'], pct_change=agg['pct_change'], member_count=agg['member_count'],
        ))


def update_index_daily() -> int:
    """每日维护：对每个宽基指数写入最近一个有效交易日的行情。"""
    written = 0
    try:
        with get_db_session() as db:
            for idx in _resolve_member_indices():
                members = _resolve_members(idx, db)
                agg_by_day = _aggregate_days(idx, members, db, days=1)
                if agg_by_day:
                    day = max(agg_by_day)
                    _upsert(db, idx['ts_code'], idx['name'], day, agg_by_day[day])
                    written += 1
            db.commit()
    except Exception as e:
        logger.error(f'[index_daily] update error: {e}', exc_info=True)
    return written


def backfill_index_daily(days: int) -> int:
    """历史补采：对最近 days 个交易日补写每个宽基指数的行情。"""
    written = 0
    try:
        with get_db_session() as db:
            for idx in _resolve_member_indices():
                members = _resolve_members(idx, db)
                agg_by_day = _aggregate_days(idx, members, db, days=days)
                for day, agg in agg_by_day.items():
                    _upsert(db, idx['ts_code'], idx['name'], day, agg)
                    written += 1
            db.commit()
    except Exception as e:
        logger.error(f'[index_daily] backfill error: {e}', exc_info=True)
    return written


def get_index_daily_pct(ts_code: str):
    """读取某指数最新有效交易日的涨跌幅（%）；无则返回 None。dashboard 读库用。"""
    try:
        with get_db_session() as db:
            row = db.query(IndexDaily).filter(
                IndexDaily.ts_code == ts_code,
                IndexDaily.pct_change.isnot(None),
            ).order_by(IndexDaily.trade_date.desc()).first()
        return float(row.pct_change) if row else None
    except Exception as e:
        logger.debug(f'[index_daily] get {ts_code} error: {e}')
        return None


# ===== 手动触发接口 =====
@router.post("/api/index-daily/refresh")
async def refresh_index_daily():
    """立即执行一次指数日表维护（写最近有效交易日）。"""
    n = await __import__('asyncio').to_thread(update_index_daily)
    return {"success": True, "written": n, "message": f"指数日表维护完成，写入 {n} 条"}


@router.post("/api/index-daily/backfill")
async def backfill_index_daily_api(days: int = Query(90, ge=1, le=365)):
    """历史补采指数日表（最近 N 个交易日）。"""
    n = await __import__('asyncio').to_thread(backfill_index_daily, days)
    return {"success": True, "written": n, "days": days, "message": f"补采完成，写入 {n} 条"}