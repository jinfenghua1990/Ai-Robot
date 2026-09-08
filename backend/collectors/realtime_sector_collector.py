"""实时 SW2021 行业资金流聚合。

盘中行业数据不再读取新浪/东方财富的旧行业标签；先落个股快照，再按
SW2021 L2 ``sector`` 聚合，保证板块与个股使用同一套归属。
"""

import logging
from datetime import date, datetime

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert

from db.models import RealtimeSectorFlow, RealtimeStockFlow
from db.session import get_db_session

logger = logging.getLogger(__name__)


def _now_truncated():
    """当前时间截断到分钟（秒数归零）。"""
    return datetime.now().replace(second=0, microsecond=0)


def _as_trade_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).replace("-", ""), "%Y%m%d").date()


def collect_realtime_sector_flow(trade_date, snapshot_time=None):
    """按指定快照的 SW2021 L2 个股数据生成实时行业快照。"""
    target_date = _as_trade_date(trade_date)
    snapshot_time = snapshot_time or _now_truncated()
    print(f"[realtime] Aggregating SW2021 sector flow at {snapshot_time}")

    with get_db_session() as db:
        # 正常编排会传入刚写入的个股快照时间；手动调用时回退到当日最新点。
        has_rows = db.query(RealtimeStockFlow.ts_code).filter(
            RealtimeStockFlow.trade_date == target_date,
            RealtimeStockFlow.snapshot_time == snapshot_time,
            RealtimeStockFlow.sector.isnot(None),
            RealtimeStockFlow.sector != "",
        ).first()
        if has_rows is None:
            snapshot_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter(
                RealtimeStockFlow.trade_date == target_date,
            ).scalar()
        if snapshot_time is None:
            logger.info("[realtime] no SW2021 stock snapshot for %s", target_date)
            return 0

        positive_flow = case(
            (RealtimeStockFlow.main_force_inflow > 0, RealtimeStockFlow.main_force_inflow),
            else_=0,
        )
        negative_flow = case(
            (RealtimeStockFlow.main_force_inflow < 0, -RealtimeStockFlow.main_force_inflow),
            else_=0,
        )
        rising = case((RealtimeStockFlow.price_chg > 0, 1), else_=0)
        rows = db.query(
            RealtimeStockFlow.sector.label("sector"),
            func.sum(positive_flow).label("money_inflow"),
            func.sum(negative_flow).label("money_outflow"),
            func.sum(RealtimeStockFlow.main_force_inflow).label("net_flow"),
            (func.sum(rising) * 100.0 / func.count(RealtimeStockFlow.ts_code)).label("rise_ratio"),
        ).filter(
            RealtimeStockFlow.trade_date == target_date,
            RealtimeStockFlow.snapshot_time == snapshot_time,
            RealtimeStockFlow.sector.isnot(None),
            RealtimeStockFlow.sector != "",
        ).group_by(RealtimeStockFlow.sector).all()
        if not rows:
            return 0

        values = [{
            "snapshot_time": snapshot_time,
            "trade_date": target_date,
            "sector": str(row.sector),
            "money_inflow": row.money_inflow,
            "money_outflow": row.money_outflow,
            "net_flow": row.net_flow,
            "rise_ratio": row.rise_ratio,
            "source": "computed_sw2021",
        } for row in rows]
        stmt = insert(RealtimeSectorFlow).values(values)
        db.execute(stmt.on_conflict_do_update(
            constraint="uq_realtime_sector_time",
            set_={
                "trade_date": stmt.excluded.trade_date,
                "money_inflow": stmt.excluded.money_inflow,
                "money_outflow": stmt.excluded.money_outflow,
                "net_flow": stmt.excluded.net_flow,
                "rise_ratio": stmt.excluded.rise_ratio,
                "source": stmt.excluded.source,
            },
        ))
        db.commit()
        logger.info(
            "[realtime] saved %s SW2021 sector snapshots for %s",
            len(values), snapshot_time,
        )
        return len(values)
