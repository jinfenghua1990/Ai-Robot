"""External collectors for the independent industry-stage module.

All network calls live here.  API handlers never import or call this module.
"""

from datetime import date, datetime, time
import logging

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collectors.tdx_collector import call_tushare_mcp
from db.connection import Base, engine
from db.models import StockDailyKline, StockUniverse
from db.session import get_db_session
from industry_stage.models import (
    INDUSTRY_STAGE_TABLES,
    TAXONOMY_VERSION,
    IndustryStageDailyBasic,
    IndustryStageMembership,
    IndustryStageTaxonomy,
)


logger = logging.getLogger(__name__)


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine, tables=list(INDUSTRY_STAGE_TABLES))


def latest_completed_trade_date(now: datetime | None = None) -> date | None:
    current = now or datetime.now()
    with get_db_session() as db:
        latest = db.query(func.max(StockDailyKline.trade_date)).scalar()
        if latest == current.date() and current.time() < time(15, 5):
            return db.query(func.max(StockDailyKline.trade_date)).filter(
                StockDailyKline.trade_date < latest,
            ).scalar()
        return latest


def _parse_date(value) -> date | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y%m%d").date()


def _chunks(rows, size=500):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def sync_taxonomy_and_membership() -> dict:
    """同步申万 2021 的分类树、当前成分及历史有效期归属。

    ``index_member_all`` 的 ``is_new=Y`` 只覆盖当前成分，``N`` 则包含已经
    调出的历史成分。两者都落库，后续日线/盘中回溯才能按有效日期归类，避免
    用今天的行业标签污染历史数据。
    """
    l1_rows = call_tushare_mcp(
        "index_classify",
        params={"level": "L1", "src": TAXONOMY_VERSION},
        fields=["index_code", "industry_code", "industry_name", "level", "is_pub", "parent_code", "src"],
    ) or []
    l2_rows = call_tushare_mcp(
        "index_classify",
        params={"level": "L2", "src": TAXONOMY_VERSION},
        fields=["index_code", "industry_code", "industry_name", "level", "is_pub", "parent_code", "src"],
    ) or []
    if len(l1_rows) != 31 or len(l2_rows) != 134:
        raise RuntimeError(f"SW2021 taxonomy incomplete: L1={len(l1_rows)}, L2={len(l2_rows)}")

    membership_rows = []
    failed_l1 = []
    for industry in l1_rows:
        l1_code = industry["index_code"]
        fields = [
            "l1_code", "l1_name", "l2_code", "l2_name", "l3_code", "l3_name",
            "ts_code", "name", "in_date", "out_date", "is_new",
        ]
        current_rows = call_tushare_mcp(
            "index_member_all",
            params={"l1_code": l1_code, "is_new": "Y"},
            fields=fields,
        ) or []
        history_rows = call_tushare_mcp(
            "index_member_all",
            params={"l1_code": l1_code, "is_new": "N"},
            fields=fields,
        ) or []
        rows = current_rows + history_rows
        if not current_rows:
            failed_l1.append(l1_code)
        membership_rows.extend(rows)
    if failed_l1:
        raise RuntimeError(f"SW2021 membership missing for: {','.join(failed_l1)}")

    with get_db_session() as db:
        active_codes = {
            row[0] for row in db.query(StockUniverse.ts_code).filter(
                StockUniverse.is_active.is_(True),
            ).all()
        }
    # 当前归属只接受 Tushare 明确标记为新成分且没有 out_date 的记录；
    # 同一股票偶尔会返回多条 L3 记录，按最近 in_date 取一条作为兼容字段。
    current_by_stock = {}
    for row in membership_rows:
        ts_code = str(row.get("ts_code") or "").strip()
        if (
            not ts_code
            or str(row.get("is_new") or "").upper() != "Y"
            or row.get("out_date")
            or ts_code not in active_codes
        ):
            continue
        previous = current_by_stock.get(ts_code)
        if previous is None or str(row.get("in_date") or "") >= str(previous.get("in_date") or ""):
            current_by_stock[ts_code] = row
    if len(current_by_stock) < 5000:
        raise RuntimeError(f"SW2021 membership incomplete: stocks={len(current_by_stock)}")

    fetched_at = datetime.now()
    taxonomy_values = []
    for row in l1_rows + l2_rows:
        taxonomy_values.append({
            "version": TAXONOMY_VERSION,
            "index_code": row["index_code"],
            "industry_code": row["industry_code"],
            "industry_name": row["industry_name"],
            "level": row["level"],
            "parent_code": str(row.get("parent_code") or "0"),
            "source": "tushare_sw2021",
            # is_pub 只表示申万是否发布对应行情指数，不代表该分类失效；
            # SW2021 返回的 31/134 个节点都必须保留在分类树中。
            "is_active": True,
            "fetched_at": fetched_at,
        })
    # 去重后保存全部有效期记录。唯一键包含 in_date，足以区分同一股票的
    # 多次调入/调出周期；当前标志仅用于今天的快速查询。
    deduped = {}
    for row in membership_rows:
        ts_code = str(row.get("ts_code") or "").strip()
        l1_code = str(row.get("l1_code") or "").strip()
        l2_code = str(row.get("l2_code") or "").strip()
        if not ts_code or not l1_code or not l2_code:
            continue
        in_date = _parse_date(row.get("in_date"))
        out_date = _parse_date(row.get("out_date"))
        key = (ts_code, l1_code, l2_code, str(row.get("l3_code") or ""), in_date)
        values = {
            "version": TAXONOMY_VERSION,
            "ts_code": ts_code,
            "stock_name": str(row.get("name") or ""),
            "l1_code": l1_code,
            "l1_name": str(row.get("l1_name") or ""),
            "l2_code": l2_code,
            "l2_name": str(row.get("l2_name") or ""),
            "l3_code": str(row.get("l3_code") or ""),
            "l3_name": str(row.get("l3_name") or ""),
            "in_date": in_date,
            "out_date": out_date,
            "is_current": False,
            "source": "tushare_index_member_all",
            "fetched_at": fetched_at,
        }
        deduped[key] = values

    current_key_by_stock = {}
    for ts_code, row in current_by_stock.items():
        current_key_by_stock[ts_code] = (
            ts_code,
            str(row.get("l1_code") or ""),
            str(row.get("l2_code") or ""),
            str(row.get("l3_code") or ""),
            _parse_date(row.get("in_date")),
        )
    for key, values in deduped.items():
        values["is_current"] = current_key_by_stock.get(values["ts_code"]) == key
    membership_values = list(deduped.values())

    with get_db_session() as db:
        db.query(IndustryStageTaxonomy).filter(
            IndustryStageTaxonomy.version == TAXONOMY_VERSION,
        ).update({"is_active": False}, synchronize_session=False)
        for values in _chunks(taxonomy_values):
            stmt = pg_insert(IndustryStageTaxonomy.__table__).values(values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_industry_stage_taxonomy_version_code",
                set_={
                    "industry_code": stmt.excluded.industry_code,
                    "industry_name": stmt.excluded.industry_name,
                    "level": stmt.excluded.level,
                    "parent_code": stmt.excluded.parent_code,
                    "source": stmt.excluded.source,
                    "is_active": stmt.excluded.is_active,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            db.execute(stmt)

        db.query(IndustryStageMembership).filter(
            IndustryStageMembership.version == TAXONOMY_VERSION,
        ).update({"is_current": False}, synchronize_session=False)
        for values in _chunks(membership_values):
            stmt = pg_insert(IndustryStageMembership.__table__).values(values)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_industry_stage_membership_period",
                set_={
                    "stock_name": stmt.excluded.stock_name,
                    "l1_name": stmt.excluded.l1_name,
                    "l2_name": stmt.excluded.l2_name,
                    "l3_name": stmt.excluded.l3_name,
                    "in_date": stmt.excluded.in_date,
                    "out_date": stmt.excluded.out_date,
                    "is_current": stmt.excluded.is_current,
                    "source": stmt.excluded.source,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            db.execute(stmt)
        db.commit()

    result = {
        "version": TAXONOMY_VERSION,
        "l1_count": len(l1_rows),
        "l2_count": len(l2_rows),
        "membership_count": len(membership_values),
        "current_membership_count": len(current_by_stock),
        "fetched_at": fetched_at.isoformat(),
    }
    logger.info("[industry-stage] taxonomy synced: %s", result)
    return result


def sync_daily_basic(trade_date: date) -> dict:
    """同步指定完成交易日的全市场总市值、流通市值与换手率。"""
    target = trade_date.strftime("%Y%m%d")
    rows = call_tushare_mcp(
        "daily_basic",
        params={"trade_date": target},
        fields=["ts_code", "trade_date", "close", "total_mv", "circ_mv", "turnover_rate", "volume_ratio"],
    ) or []
    with get_db_session() as db:
        expected = db.query(func.count(func.distinct(StockDailyKline.ts_code))).filter(
            StockDailyKline.trade_date == trade_date,
        ).scalar() or 0
    minimum = max(4500, int(expected * 0.95))
    if len(rows) < minimum:
        raise RuntimeError(f"daily_basic incomplete: rows={len(rows)}, expected_at_least={minimum}")

    fetched_at = datetime.now()
    values = [{
        "trade_date": trade_date,
        "ts_code": str(row["ts_code"]),
        "close": row.get("close"),
        "total_mv": row.get("total_mv"),
        "circ_mv": row.get("circ_mv"),
        "turnover_rate": row.get("turnover_rate"),
        "volume_ratio": row.get("volume_ratio"),
        "source": "tushare_daily_basic",
        "fetched_at": fetched_at,
    } for row in rows if row.get("ts_code")]

    with get_db_session() as db:
        for batch in _chunks(values, size=800):
            stmt = pg_insert(IndustryStageDailyBasic.__table__).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_industry_stage_daily_basic_date_code",
                set_={
                    "close": stmt.excluded.close,
                    "total_mv": stmt.excluded.total_mv,
                    "circ_mv": stmt.excluded.circ_mv,
                    "turnover_rate": stmt.excluded.turnover_rate,
                    "volume_ratio": stmt.excluded.volume_ratio,
                    "source": stmt.excluded.source,
                    "fetched_at": stmt.excluded.fetched_at,
                },
            )
            db.execute(stmt)
        db.commit()

    result = {
        "trade_date": trade_date.isoformat(),
        "row_count": len(values),
        "expected_kline_count": expected,
        "coverage": round(len(values) / expected * 100, 2) if expected else 0,
    }
    logger.info("[industry-stage] daily basic synced: %s", result)
    return result
