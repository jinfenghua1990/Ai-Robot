"""
调度器状态 API（只读，便于确认"每日网上数据入库"定时器是否在工作）
- GET /api/scheduler/jobs           列出所有定时任务 + 下次运行时间 + 进程存活
- GET /api/scheduler/research-status  今日研究采集落库条数（证明 19:30 定时器已执行）
"""
import time
import logging
from datetime import datetime, date

from fastapi import APIRouter
from sqlalchemy import text
from collectors.scheduler import scheduler
from db.session import get_db_session
from db.models import StockNewsSearch, StockDataQuery, AIAnalysisCache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

# 进程启动时刻（用于 uptime 展示）
START_TIME = time.time()

# 与"每日网上数据 → 本地库"最相关的定时任务（其余是实时/盘中任务，列表里折叠展示）
_DAILY_ETL_FOCUS = {
    "research_collection",   # 19:30 妙想资讯+数据+AI基线 → stock_news_search/stock_data_query/ai_analysis_cache
    "daily_report",          # 20:00 综合日报 HTML 生成
    "archive",               # 15:05 收盘归档 → sector_flow/stock_flow
    "analyze",               # 15:30 盘后分析
    "dragon_tiger_evening",  # 18:30 龙虎榜
    "moneyflow_detail",      # 17:30 四档资金流
}


@router.get("/jobs")
def list_jobs():
    """列出所有已注册的定时任务及下次触发时间"""
    jobs = []
    for j in scheduler.get_jobs():
        jobs.append({
            "id": j.id,
            "trigger": str(j.trigger),
            "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
        })
    daily = [j for j in jobs if j["id"] in _DAILY_ETL_FOCUS]
    return {
        "scheduler_running": scheduler.running,
        "uptime_seconds": int(time.time() - START_TIME),
        "job_count": len(jobs),
        "daily_etl_jobs": daily,
        "all_jobs": jobs,
    }


@router.get("/research-status")
def research_status():
    """今日研究采集落库情况——三项均 >0 即表示当日 19:30 定时器已成功执行"""
    today = date.today()
    today_start = datetime(today.year, today.month, today.day)
    with get_db_session() as db:
        news = db.query(StockNewsSearch).filter(
            StockNewsSearch.created_at >= today_start).count()
        data = db.query(StockDataQuery).filter(
            StockDataQuery.query_time >= today_start).count()
        ai = db.query(AIAnalysisCache).filter(
            AIAnalysisCache.created_at >= today_start).count()
    return {
        "date": today.isoformat(),
        "stock_news_search_today": news,
        "stock_data_query_today": data,
        "ai_analysis_cache_today": ai,
        "note": "三项均 >0 表示当日 19:30 研究采集定时器已成功执行并落库",
    }


@router.get("/freshness")
def data_freshness():
    """全表数据新鲜度看板：每张关键表的最新数据日期 + 是否落后于最新交易日。

    返回 reference_market_day（以 stock_flow 最大交易日为基准）与每个表的
    latest / gap_days / fresh。gap_days>0 即表示数据滞后，可一眼看出哪里卡住
    （例如此前 concept_sector_flow 卡在 07-06 即会被暴露）。
    """
    # (表名, 日期列) —— 均为硬编码常量，非用户输入，可安全拼接到 SQL
    targets = [
        ("sector_flow", "trade_date"),
        ("stock_flow", "trade_date"),
        ("concept_sector_flow", "trade_date"),
        ("leader_lifecycle", "trade_date"),
        ("watchlist_signal_daily", "trade_date"),
        ("trading_signal_daily", "trade_date"),
        ("stock_daily_kline", "trade_date"),
        ("stock_news_search", "created_at"),
        ("stock_data_query", "query_time"),
        ("ai_analysis_cache", "created_at"),
        ("realtime_concept_sector_flow", "snapshot_time"),
    ]
    # 白名单校验，防止未来配置被篡改时 SQL 注入
    _ALLOWED_TABLES = {t for t, _ in targets}
    _ALLOWED_COLS = {c for _, c in targets}
    with get_db_session() as db:
        ref = db.execute(text("SELECT max(trade_date) FROM stock_flow")).scalar()
        rows = []
        for tbl, col in targets:
            try:
                if tbl not in _ALLOWED_TABLES or col not in _ALLOWED_COLS:
                    raise ValueError(f"table/column not in whitelist: {tbl}.{col}")
                d = db.execute(text(f"SELECT max({col})::date FROM {tbl}")).scalar()
            except Exception as e:
                rows.append({"table": tbl, "latest": None, "gap_days": None,
                             "fresh": False, "error": str(e)[:120]})
                continue
            gap = (ref - d).days if (ref and d) else None
            rows.append({
                "table": tbl,
                "latest": d.isoformat() if d else None,
                "gap_days": gap,
                "fresh": bool(gap is not None and gap <= 0),
            })
    return {
        "reference_market_day": ref.isoformat() if ref else None,
        "tables": rows,
        "stale_count": sum(1 for r in rows if r.get("gap_days") and r["gap_days"] > 0),
    }
