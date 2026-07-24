"""
Data Center API — 三市场数据中心：数据新鲜度、一键采集、调度管理
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from .cache import cache, cached

# 数据中心原属 Hermes 子系统，连接独立的 hermes PostgreSQL 数据库
os.environ.setdefault("DB_NAME", "hermes")

_TRACKING_DIR = Path(__file__).resolve().parent.parent
if str(_TRACKING_DIR) not in sys.path:
    sys.path.insert(0, str(_TRACKING_DIR))

_DATA_HOME = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data")

from api.hermes_native.db_connector import execute_query, execute_one

logger = logging.getLogger("data_center")

router = APIRouter(prefix="/api/data-center", tags=["data-center"])

_PYTHON = "/Library/Developer/CommandLineTools/usr/bin/python3"
_INGESTION_DIR = _DATA_HOME / "ingestion"
_PIPELINES_DIR = _DATA_HOME / "pipelines"
_SCRIPTS_DIR = _DATA_HOME.parent / "scripts"

# ─── 数据表配置 ────────────────────────────────────────────────────────────────

MARKET_TABLES = {
    "CN_A": {
        "label": "A股",
        "tables": [
            {"key": "kline_daily", "label": "日K行情", "market_filter": "CN_A"},
            {"key": "index_data", "label": "指数数据", "market_filter": None},
            {"key": "market_sentiment_daily", "label": "市场情绪", "market_filter": None},
            {"key": "limit_up_pool_daily", "label": "涨停池", "market_filter": None},
            {"key": "industry_board_daily", "label": "行业板块", "market_filter": None},
            {"key": "concept_board_daily", "label": "概念板块", "market_filter": None},
            {"key": "north_money_flow", "label": "北向资金", "market_filter": None},
            {"key": "margin_data", "label": "融资融券", "market_filter": None},
        ],
    },
    "HK": {
        "label": "港股",
        "tables": [
            {"key": "kline_daily", "label": "日K行情", "market_filter": "HK"},
        ],
    },
    "US": {
        "label": "美股",
        "tables": [
            {"key": "kline_daily", "label": "日K行情", "market_filter": "US"},
        ],
    },
}

MARKET_INDICES_MAP = {
    "CN_A": [
        {"table": "index_data", "code": "000001.SH", "label": "上证综指"},
        {"table": "index_data", "code": "399001.SZ", "label": "深证成指"},
        {"table": "index_data", "code": "399006.SZ", "label": "创业板指"},
    ],
    "HK": [
        {"yahoo": "^HSI", "label": "恒生指数"},
        {"yahoo": "^HSCE", "label": "国企指数"},
    ],
    "US": [
        {"yahoo": "^DJI", "label": "道琼斯"},
        {"yahoo": "^GSPC", "label": "标普500"},
        {"yahoo": "^IXIC", "label": "纳斯达克"},
    ],
}

# 采集任务配置
COLLECTION_TASKS = {
    "CN_A": {
        "label": "A股全量采集",
        "script": str(_SCRIPTS_DIR / "daily_after_close.sh"),
        "workdir": str(_SCRIPTS_DIR),
        "pgrep_pattern": "daily_after_close",
    },
    "HK": {
        "label": "港股K线采集",
        "script": str(_INGESTION_DIR / "ingest_hk_kline.py"),
        "workdir": str(_INGESTION_DIR),
        "pgrep_pattern": "ingest_hk_kline",
        "is_python": True,
    },
    "US": {
        "label": "美股K线采集",
        "script": str(_DATA_HOME / "after_close_us_collector.py"),
        "workdir": str(_DATA_HOME),
        "pgrep_pattern": "after_close_us",
        "is_python": True,
    },
}

# ─── 调度配置 ──────────────────────────────────────────────────────────────────

SCHEDULE_INFO = {
    "CN_A": {
        "label": "A股盘后采集",
        "plist": "com.gino.hermes.daily-after-close",
        "default_hour": 16,
        "default_minute": 20,
        "description": "每个交易日 16:20 自动执行全量采集流水线",
        "weekdays": "Mon-Fri",
    },
    "HK": {
        "label": "港股盘后采集",
        "plist": "com.gino.hermes.daily-after-close",
        "default_hour": 16,
        "default_minute": 30,
        "description": "跟随 A 股盘后流水线一起执行",
        "weekdays": "Mon-Fri",
    },
    "US": {
        "label": "美股盘后采集",
        "plist": "com.gino.hermes.us-after-close",
        "default_hour": 6,
        "default_minute": 0,
        "description": "周二至周六 06:00 CST（覆盖周一至周五美股收盘）",
        "weekdays": "Tue-Sat",
    },
}


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


# ─── 数据状态查询 ──────────────────────────────────────────────────────────────

def _get_table_stats(table: str, market_filter: str | None = None) -> dict:
    """查询单张表的数据状态（带 5 分钟缓存）"""
    cache_key = f"table_stats:{table}:{market_filter or 'all'}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    try:
        if market_filter:
            if market_filter == "CN_A":
                market_clause = "WHERE market IN ('SH','SZ','BJ')"
            else:
                market_clause = f"WHERE market = '{market_filter}'"
        else:
            market_clause = ""

        # 确定日期列名
        date_col = "trade_date"
        if table == "market_sentiment_daily":
            date_col = "trade_date"

        # 总行数
        count_sql = f"SELECT COUNT(*) as cnt FROM {table} {market_clause}"
        count_row = execute_one(count_sql)
        total = count_row["cnt"] if count_row else 0

        # 最新日期和行数
        stats_sql = (
            f"SELECT MAX({date_col}) as max_d, MIN({date_col}) as min_d, "
            f"COUNT(*) as cnt FROM {table} {market_clause}"
        )
        stats_row = execute_one(stats_sql)

        if stats_row and stats_row.get("max_d"):
            max_d = stats_row["max_d"]
            min_d = stats_row.get("min_d")

            # 计算数据天数（从今天到最新日期的差距）
            if isinstance(max_d, date):
                max_d_str = max_d.isoformat()
                days_behind = (date.today() - max_d).days
            else:
                max_d_str = str(max_d)
                days_behind = -1

            if isinstance(min_d, date):
                min_d_str = min_d.isoformat()
            else:
                min_d_str = str(min_d) if min_d else None

            result = {
                "total": total,
                "count": stats_row["cnt"],
                "latest_date": max_d_str,
                "earliest_date": min_d_str,
                "days_behind": max(0, days_behind),
                "is_fresh": days_behind <= 3,  # 3 天内算新鲜
            }
            cache.set(cache_key, result, 300)
            return result
        result = {"total": total, "count": 0, "latest_date": None, "earliest_date": None, "days_behind": -1, "is_fresh": False}
        cache.set(cache_key, result, 300)
        return result
    except Exception as e:
        return {"total": 0, "count": 0, "latest_date": None, "earliest_date": None, "days_behind": -1, "is_fresh": False, "error": str(e)}


def _fetch_single_index(cfg: dict) -> dict:
    """获取单个指数数据（带 10 分钟缓存）"""
    if "table" in cfg:
        cache_key = f"index_db:{cfg['code']}"
        hit = cache.get(cache_key)
        if hit is not None:
            return hit
        try:
            row = execute_one(
                f"SELECT close, change_pct, trade_date FROM {cfg['table']} "
                f"WHERE index_code = %s ORDER BY trade_date DESC LIMIT 1",
                (cfg["code"],),
            )
            result = {
                "code": cfg["code"],
                "label": cfg["label"],
                "value": _safe_float(row.get("close")) if row else None,
                "change_pct": _safe_float(row.get("change_pct")) if row else None,
                "date": str(row["trade_date"]) if row and row.get("trade_date") else None,
            }
            cache.set(cache_key, result, 600)
            return result
        except Exception:
            return {"code": cfg["code"], "label": cfg["label"], "value": None, "change_pct": None}

    elif "yahoo" in cfg:
        cache_key = f"index_yahoo:{cfg['yahoo']}"
        hit = cache.get(cache_key)
        if hit is not None:
            return hit
        try:
            from api.global_market import _yahoo_fetch
            items = _yahoo_fetch(cfg["yahoo"], range_str="5d")
            if items:
                latest = items[-1]
                result = {
                    "code": cfg["yahoo"],
                    "label": cfg["label"],
                    "value": _safe_float(latest.get("close")),
                    "change_pct": _safe_float(latest.get("change_pct")),
                    "date": latest.get("date"),
                }
                cache.set(cache_key, result, 600)
                return result
            else:
                result = {"code": cfg["yahoo"], "label": cfg["label"], "value": None, "change_pct": None}
                cache.set(cache_key, result, 60)  # 空结果短缓存
                return result
        except Exception:
            return {"code": cfg["yahoo"], "label": cfg["label"], "value": None, "change_pct": None}

    return {"code": "?", "label": cfg.get("label", "?"), "value": None, "change_pct": None}


def _get_index_values(market: str) -> list[dict]:
    """获取市场主要指数最新值 — 并行请求"""
    configs = MARKET_INDICES_MAP.get(market, [])
    if not configs:
        return []

    results = [None] * len(configs)
    with ThreadPoolExecutor(max_workers=min(len(configs), 5)) as pool:
        futures = {pool.submit(_fetch_single_index, cfg): i for i, cfg in enumerate(configs)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception:
                cfg = configs[idx]
                results[idx] = {"code": cfg.get("yahoo", cfg.get("code", "?")), "label": cfg.get("label", "?"), "value": None, "change_pct": None}

    return [r for r in results if r is not None]


def _get_market_summary(market: str) -> dict:
    """获取市场涨跌统计（带 5 分钟缓存）"""
    cache_key = f"market_summary:{market}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    if market == "CN_A":
        market_clause = "market IN ('SH','SZ','BJ')"
    else:
        market_clause = f"market = '{market}'"

    try:
        # 获取最新交易日的涨跌统计
        row = execute_one(f"""
            SELECT trade_date, 
                   COUNT(*) as total,
                   SUM(CASE WHEN change_pct > 0 THEN 1 ELSE 0 END) as up_count,
                   SUM(CASE WHEN change_pct < 0 THEN 1 ELSE 0 END) as down_count,
                   SUM(CASE WHEN change_pct = 0 THEN 1 ELSE 0 END) as flat_count
            FROM kline_daily
            WHERE {market_clause}
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT 1
        """)
        if row:
            result = {
                "date": str(row["trade_date"]),
                "total": row["total"],
                "up": row["up_count"] or 0,
                "down": row["down_count"] or 0,
                "flat": row["flat_count"] or 0,
            }
            cache.set(cache_key, result, 300)
            return result
    except Exception:
        pass
    return {}


def _get_top_movers(market: str, limit: int = 5) -> dict:
    """获取最新交易日涨跌幅前5（带 5 分钟缓存）"""
    cache_key = f"top_movers:{market}:{limit}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    if market == "CN_A":
        market_clause = "market IN ('SH','SZ','BJ')"
    else:
        market_clause = f"market = '{market}'"

    try:
        # 获取最新日期
        latest_row = execute_one(
            f"SELECT MAX(trade_date) as max_d FROM kline_daily WHERE {market_clause}"
        )
        if not latest_row or not latest_row.get("max_d"):
            return {"gainers": [], "losers": []}

        latest_date = latest_row["max_d"]

        gainers = execute_query(
            f"SELECT code, close, change_pct FROM kline_daily "
            f"WHERE {market_clause} AND trade_date = %s AND change_pct IS NOT NULL "
            f"ORDER BY change_pct DESC LIMIT %s",
            (latest_date, limit),
        )
        losers = execute_query(
            f"SELECT code, close, change_pct FROM kline_daily "
            f"WHERE {market_clause} AND trade_date = %s AND change_pct IS NOT NULL "
            f"ORDER BY change_pct ASC LIMIT %s",
            (latest_date, limit),
        )

        result = {
            "gainers": [
                {"code": r["code"], "close": _safe_float(r.get("close")), "change_pct": _safe_float(r.get("change_pct"))}
                for r in (gainers or [])
            ],
            "losers": [
                {"code": r["code"], "close": _safe_float(r.get("close")), "change_pct": _safe_float(r.get("change_pct"))}
                for r in (losers or [])
            ],
        }
        cache.set(cache_key, result, 300)
        return result
    except Exception:
        return {"gainers": [], "losers": []}


def _check_task_running(task_config: dict) -> bool:
    """检查采集任务是否正在运行"""
    pgrep_pattern = task_config.get("pgrep_pattern", "")
    if not pgrep_pattern:
        return False
    try:
        result = subprocess.run(
            ["pgrep", "-f", pgrep_pattern],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _build_market_status(market: str, config: dict) -> tuple[str, dict]:
    """构建单个市场的状态数据"""
    table_stats = []
    for t in config["tables"]:
        stats = _get_table_stats(t["key"], t.get("market_filter"))
        stats["key"] = t["key"]
        stats["label"] = t["label"]
        table_stats.append(stats)

    indices = _get_index_values(market)
    summary = _get_market_summary(market)

    # 整体数据新鲜度
    latest_dates = [s["latest_date"] for s in table_stats if s.get("latest_date")]
    if latest_dates:
        overall_latest = max(latest_dates)
        days_behind = min(s.get("days_behind", 999) for s in table_stats if s.get("days_behind", -1) >= 0)
    else:
        overall_latest = None
        days_behind = -1

    # 采集任务状态
    task_config = COLLECTION_TASKS.get(market, {})
    is_collecting = _check_task_running(task_config)

    # 调度信息
    schedule = SCHEDULE_INFO.get(market, {})

    return market, {
        "label": config["label"],
        "tables": table_stats,
        "indices": indices,
        "summary": summary,
        "latest_date": overall_latest,
        "days_behind": days_behind,
        "is_collecting": is_collecting,
        "schedule": schedule,
    }


# ─── API 端点 ──────────────────────────────────────────────────────────────────

@router.get("/status")
def get_data_center_status(nocache: bool = Query(default=False)):
    """数据中心状态总览 — 三市场数据新鲜度（带 3 分钟端点缓存）"""
    if nocache:
        cache.invalidate("ep:data_center_status")
        cache.invalidate("table_stats:")
        cache.invalidate("index_")
        cache.invalidate("market_summary:")
        cache.invalidate("top_movers:")

    ep_key = "ep:data_center_status"
    hit = cache.get(ep_key)
    if hit is not None:
        return hit

    # 三市场并行构建
    markets = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_build_market_status, mkt, cfg): mkt
            for mkt, cfg in MARKET_TABLES.items()
        }
        for fut in as_completed(futures):
            try:
                mkt, data = fut.result()
                markets[mkt] = data
            except Exception as e:
                mkt = futures[fut]
                logger.error(f"Failed to build status for {mkt}: {e}")
                markets[mkt] = {"label": MARKET_TABLES[mkt]["label"], "tables": [], "indices": [], "summary": {}, "error": str(e)}

    result = {
        "markets": markets,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    cache.set(ep_key, result, 180)
    return result


@router.get("/market/{market}/detail")
def get_market_detail(market: str, limit: int = Query(default=12, le=30), nocache: bool = Query(default=False)):
    """获取市场详细数据 — 关注股票最新行情（带 5 分钟缓存）"""
    market = market.upper()
    ep_key = f"ep:market_detail:{market}:{limit}"
    if nocache:
        cache.invalidate(f"ep:market_detail:{market}")
        cache.invalidate(f"top_movers:{market}")
        cache.invalidate(f"table_stats:")

    hit = cache.get(ep_key)
    if hit is not None:
        return hit

    # 获取关注列表行情（复用 global_market 逻辑）
    from api.global_market import DEFAULT_WATCHLIST, _safe_float as gf

    watchlist = DEFAULT_WATCHLIST.get(market, [])
    if not watchlist:
        return {"market": market, "items": [], "error": "未知市场"}

    codes = [s["code"] for s in watchlist]
    placeholders = ",".join(["%s"] * len(codes))

    if market == "CN_A":
        market_clause = "market IN ('SH','SZ','BJ')"
    else:
        market_clause = f"market = '{market}'"

    try:
        rows = execute_query(
            f"""
            SELECT code, trade_date, open, high, low, close, volume, amount,
                   change_pct, turnover_rate, amplitude
            FROM kline_daily
            WHERE {market_clause} AND code IN ({placeholders})
            ORDER BY code, trade_date DESC
            """,
            (*codes,),
        )

        # 每只股票取最近 2 条
        kline_map = {}
        for r in rows:
            code = r["code"]
            if code not in kline_map:
                kline_map[code] = []
            if len(kline_map[code]) < 2:
                kline_map[code].append(r)

        items = []
        for stock in watchlist:
            code = stock["code"]
            klines = kline_map.get(code, [])
            if klines:
                latest = klines[0]
                prev = klines[1] if len(klines) > 1 else None
                price = gf(latest.get("close"))
                change_pct = gf(latest.get("change_pct"))
                if change_pct is None and prev and price:
                    prev_close = gf(prev.get("close"))
                    if prev_close and prev_close > 0:
                        change_pct = round((price - prev_close) / prev_close * 100, 2)

                items.append({
                    "code": code,
                    "name": stock["name"],
                    "price": price,
                    "change_pct": change_pct,
                    "open": gf(latest.get("open")),
                    "high": gf(latest.get("high")),
                    "low": gf(latest.get("low")),
                    "volume": latest.get("volume"),
                    "amount": latest.get("amount"),
                    "amplitude": gf(latest.get("amplitude")),
                    "turnover_rate": gf(latest.get("turnover_rate")),
                    "trade_date": str(latest.get("trade_date", "")),
                })
            else:
                items.append({"code": code, "name": stock["name"], "price": None, "change_pct": None})

        # 涨跌排序
        top_movers = _get_top_movers(market, limit=5)

        result = {
            "market": market,
            "items": items,
            "top_movers": top_movers,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        cache.set(ep_key, result, 300)
        return result
    except Exception as e:
        return {"market": market, "items": [], "error": str(e)}


@router.post("/collect/{market}")
def trigger_collection(market: str):
    """触发一键采集"""
    market = market.upper()
    task_config = COLLECTION_TASKS.get(market)

    if not task_config:
        return {"ok": False, "error": f"未知市场: {market}"}

    # 检查是否已经在运行
    if _check_task_running(task_config):
        return {"ok": False, "error": f"{task_config['label']}正在运行中", "already_running": True}

    try:
        # 清除相关缓存
        cache.invalidate("ep:data_center_status")
        cache.invalidate(f"ep:market_detail:{market}")
        cache.invalidate(f"table_stats:")
        cache.invalidate(f"market_summary:{market}")
        cache.invalidate(f"top_movers:{market}")

        script = task_config["script"]
        workdir = task_config.get("workdir", str(_DATA_HOME))

        log_dir = _DATA_HOME / "logs"
        log_dir.mkdir(exist_ok=True)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"collect_{market}_{now_str}.log"

        if task_config.get("is_python"):
            cmd = [_PYTHON, script]
        else:
            cmd = ["/bin/bash", script]

        env = os.environ.copy()
        env["PYTHONPATH"] = f"{_DB_ROOT}:{_DATA_HOME}:{workdir}"
        env["NO_PROXY"] = "*"

        process = subprocess.Popen(
            cmd,
            stdout=open(log_file, "w"),
            stderr=subprocess.STDOUT,
            cwd=workdir,
            env=env,
            start_new_session=True,
        )

        return {
            "ok": True,
            "market": market,
            "label": task_config["label"],
            "pid": process.pid,
            "log_file": str(log_file),
            "message": f"{task_config['label']}已启动（PID: {process.pid}）",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/collect/status")
def get_collection_status():
    """获取所有采集任务的运行状态"""
    statuses = {}
    for market, task_config in COLLECTION_TASKS.items():
        is_running = _check_task_running(task_config)

        # 查找最新日志
        log_dir = _DATA_HOME / "logs"
        latest_log = None
        latest_log_time = None
        if log_dir.exists():
            for f in sorted(log_dir.glob(f"collect_{market}_*.log"), reverse=True):
                latest_log = str(f)
                latest_log_time = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                break

        statuses[market] = {
            "label": task_config["label"],
            "is_running": is_running,
            "latest_log": latest_log,
            "latest_log_time": latest_log_time,
        }

    return {"statuses": statuses}


@router.get("/collect/log/{market}")
def get_collection_log(market: str, lines: int = Query(default=50, le=200)):
    """获取采集日志"""
    market = market.upper()
    log_dir = _DATA_HOME / "logs"

    # 也检查 daily_after_close 的日志
    patterns = [f"collect_{market}_*.log"]
    if market == "CN_A":
        patterns.append("daily_after_close_*.log")
        patterns.append("collect_20*.log")  # daily_after_close 的日志格式
    if market == "US":
        patterns.append("us_kline_*.log")

    latest_log = None
    for pattern in patterns:
        logs = sorted(log_dir.glob(pattern), reverse=True)
        if logs:
            if latest_log is None or logs[0].stat().st_mtime > latest_log.stat().st_mtime:
                latest_log = logs[0]

    if latest_log and latest_log.exists():
        content = latest_log.read_text(errors="replace")
        log_lines = content.strip().split("\n")
        return {
            "market": market,
            "log_file": str(latest_log),
            "total_lines": len(log_lines),
            "lines": log_lines[-lines:],
        }

    return {"market": market, "log_file": None, "lines": [], "total_lines": 0}


@router.get("/schedules")
def get_schedules():
    """获取采集调度配置"""
    schedules = {}
    for market, info in SCHEDULE_INFO.items():
        # 读取 launchd plist 获取实际配置
        plist_path = Path(f"/Users/gino/Library/LaunchAgents/{info['plist']}.plist")
        is_loaded = False
        try:
            result = subprocess.run(
                ["launchctl", "list", info["plist"]],
                capture_output=True, timeout=5, text=True,
            )
            is_loaded = result.returncode == 0
        except Exception:
            pass

        schedules[market] = {
            **info,
            "market": market,
            "is_loaded": is_loaded,
        }

    return {"schedules": schedules}
