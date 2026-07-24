from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Optional, Union

# 让 ops.py 能直接 import 上级目录的 config/adapters
_TRACKING_DIR = Path(__file__).resolve().parent.parent
if str(_TRACKING_DIR) not in sys.path:
    sys.path.insert(0, str(_TRACKING_DIR))

_DATA_HOME = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data")
_DB_ROOT = _DATA_HOME / "db"
for p in (_DB_ROOT,):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from fastapi import APIRouter, Body, Query

from api.hermes_native.services.ai_advice import (
    get_provider,
    get_default_provider,
    list_providers,
)
from api.hermes_native.services.ai_advice.base import StockInfo
from api.hermes_native.services.market_trends import get_market_trends
from api.hermes_native.services.miaoxiang_service import (
    query as mx_query,
    realtime_quote as mx_quote,
    index_quote as mx_index,
    smart_select as mx_select,
    search_news as mx_news,
)


from api.hermes_native.services.cron_scheduler import HermesCronScheduler
from api.hermes_native.services.main_central_hub import MainCentralHub
from api.hermes_native.services.monitor_pool import (
    add_monitor_stock,
    bootstrap_from_legacy_wave_watchlist,
    ensure_monitor_schema,
    get_pool_row,
    get_pool_rows_for_stock_monitor,
    get_realtime_quote_map,
    get_realtime_quote_rows,
    get_watchlist_items,
    load_or_sync_realtime_quotes,
    remove_monitor_stock,
    set_wave_pool_membership,
    sync_broker_positions,
)
from api.hermes_native.services.robot1_provider import build_robot1_scheduler_payload
from api.hermes_native.services.robot3_strategy import Robot3SniperStrategy
from api.hermes_native.config import (
    ALL_ROBOT_IDS,
    DEFAULT_CUSTOM_STRATEGY_KEYS,
    ROBOT_ID_TO_KEY,
    ROBOT_STRATEGY_MAP,
    STRATEGY_CATALOG,
)
from api.hermes_native.adapters import load_robot_result
from api.hermes_native.db_connector import execute_query, execute_one, execute_write


def _row_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        return row
    return dict(row) if row else {}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _format_datetime(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("T", " ").replace("Z", "")
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def _round_or_none(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(value, digits)


def _calc_pct(current: Optional[float], base: Optional[float]) -> Optional[float]:
    if current is None or base is None or base == 0:
        return None
    return ((current - base) / base) * 100.0


def _mean(values: list[Optional[float]]) -> Optional[float]:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _calc_rsi(closes_desc: list[Optional[float]], period: int = 6) -> Optional[float]:
    closes = [v for v in closes_desc if v is not None]
    if len(closes) < 2:
        return None
    closes_asc = list(reversed(closes))
    diffs = [cur - prev for prev, cur in zip(closes_asc, closes_asc[1:])]
    if not diffs:
        return None
    diffs = diffs[-period:]
    avg_gain = sum(max(delta, 0.0) for delta in diffs) / len(diffs)
    avg_loss = sum(max(-delta, 0.0) for delta in diffs) / len(diffs)
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ── 评分/等级/推荐/MACD 函数（对应前端相同逻辑，移至后端统一计算） ──

def _calc_macd_label(ma5: Optional[float], ma10: Optional[float]) -> Optional[str]:
    if ma5 is None or ma10 is None or ma5 <= 0 or ma10 <= 0:
        return None
    if ma5 >= ma10 * 1.01:
        return "golden_cross"
    if ma5 <= ma10 * 0.99:
        return "death_cross"
    return None


def _calc_trend_score(change_pct: Optional[float]) -> int:
    v = change_pct
    if v is None:
        return 0
    if v >= 10:
        return 20
    if v >= 6:
        return 18
    if v >= 3:
        return 15
    if v >= 1:
        return 12
    if v >= 0:
        return 10
    if v >= -2:
        return 8
    if v >= -5:
        return 4
    return 0


def _calc_deviation_score(deviation: Optional[float]) -> int:
    v = abs(deviation) if deviation is not None else None
    if v is None:
        return 0
    if v <= 2:
        return 20
    if v <= 5:
        return 18
    if v <= 8:
        return 14
    if v <= 12:
        return 10
    if v <= 18:
        return 6
    return 2


def _calc_rsi_score(rsi: Optional[float]) -> int:
    v = rsi
    if v is None:
        return 0
    if 45 <= v <= 65:
        return 20
    if 35 <= v <= 70:
        return 15
    if 30 <= v < 35:
        return 10
    if 70 < v <= 80:
        return 8
    if v < 30 or v > 80:
        return 4
    return 12


def _calc_macd_score(macd_label: Optional[str]) -> int:
    if macd_label == "golden_cross":
        return 25
    if macd_label == "death_cross":
        return 0
    return 12


def _calc_vol_score(volume_ratio: Optional[float]) -> int:
    v = volume_ratio
    if v is None or v <= 0:
        return 0
    if 1 <= v <= 2.5:
        return 15
    if 2.5 < v <= 4:
        return 10
    if 4 < v <= 6:
        return 6
    if v > 6:
        return 2
    return 8


def _derive_total_score(
    change_pct: Optional[float],
    deviation: Optional[float],
    rsi: Optional[float],
    macd_label: Optional[str],
    vol_ratio: Optional[float],
) -> int:
    return (
        _calc_trend_score(change_pct)
        + _calc_deviation_score(deviation)
        + _calc_rsi_score(rsi)
        + _calc_macd_score(macd_label)
        + _calc_vol_score(vol_ratio)
    )


def _derive_leader_level(score: Optional[float]) -> str:
    v = score
    if v is None:
        return ""
    if v >= 85:
        return "龙头"
    if v >= 75:
        return "次龙头"
    if v >= 60:
        return "潜力"
    if v >= 45:
        return "趋势"
    return "待评估"


def _derive_recommendation(score: Optional[float], wave_signal: Optional[str] = None) -> str:
    if wave_signal == "buy":
        return "买入"
    if wave_signal == "sell":
        return "剔除"
    v = score
    if v is None:
        return "-"
    if v >= 75:
        return "买入"
    if v >= 50:
        return "观察"
    return "剔除"


def _build_risk_signals(
    deviation: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    rsi: Optional[float] = None,
    macd_label: Optional[str] = None,
    profit_pct: Optional[float] = None,
    source: Optional[str] = None,
) -> list[str]:
    signals: list[str] = []
    if deviation is not None:
        if deviation > 15:
            signals.append("超涨回调")
        if deviation < -10:
            signals.append("超跌反弹")
        if deviation > 25:
            signals.append("偏离过大")
    if volume_ratio is not None:
        if volume_ratio > 10:
            signals.append("冷静期")
        elif volume_ratio > 5:
            signals.append("高风险放量")
        elif volume_ratio < 0.3:
            signals.append("缩量低迷")
    if rsi is not None:
        if rsi > 80:
            signals.append("RSI超买")
        if rsi < 30:
            signals.append("RSI超卖")
    if macd_label == "golden_cross":
        signals.append("MACD金叉")
    if macd_label == "death_cross":
        signals.append("MACD死叉")
    if source == "holding" and profit_pct is not None:
        if profit_pct < -10:
            signals.append("浮亏超10%")
        if profit_pct > 15:
            signals.append("浮盈超15%")
    return signals


def _load_stock_meta_map(codes: list[str]) -> dict[str, dict[str, Any]]:
    normalized = sorted({
        _normalize_stock_code(code)
        for code in codes
        if _normalize_stock_code(code).isdigit()
    })
    if not normalized:
        return {}
    placeholders = ",".join(["%s"] * len(normalized))
    rows = execute_query(
        f"""
        SELECT symbol, name, market, industry
        FROM stock_list
        WHERE symbol IN ({placeholders})
        """,
        tuple(normalized),
    ) or []
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        data = _row_to_dict(row)
        code = _normalize_stock_code(data.get("symbol"))
        if code:
            mapping[code] = data
    return mapping


def _fetch_recent_kline_rows(
    table_name: str,
    codes: list[str],
    lookback: int = 25,
) -> list[dict[str, Any]]:
    normalized = sorted({
        _normalize_stock_code(code)
        for code in codes
        if _normalize_stock_code(code).isdigit()
    })
    if not normalized:
        return []
    placeholders = ",".join(["%s"] * len(normalized))
    # 给 TimescaleDB 一个日期下界，让 chunk exclusion 在规划阶段就排除大部分 chunk
    # 交易日 ~25 天 ≈ 日历 40 天，用 90 天留足余量（节假日、停牌等）
    date_bound = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    rows = execute_query(
        f"""
        WITH ranked AS (
            SELECT
                code,
                trade_date,
                close,
                volume,
                change_pct,
                ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) AS rn
            FROM {table_name}
            WHERE code IN ({placeholders})
              AND trade_date >= %s
        )
        SELECT code, trade_date, close, volume, change_pct, rn
        FROM ranked
        WHERE rn <= %s
        ORDER BY code, rn
        """,
        tuple(normalized) + (date_bound, lookback,),
    ) or []
    return [_row_to_dict(row) for row in rows]


def _load_recent_kline_metrics(codes: list[str], lookback: int = 25) -> dict[str, dict[str, Any]]:
    histories: dict[str, list[dict[str, Any]]] = {}
    missing_codes = sorted({
        _normalize_stock_code(code)
        for code in codes
        if _normalize_stock_code(code).isdigit()
    })

    for table_name in ("kline_daily", "kline_daily_cn_a"):
        if not missing_codes:
            break
        rows = _fetch_recent_kline_rows(table_name, missing_codes, lookback=lookback)
        for row in rows:
            code = _normalize_stock_code(row.get("code"))
            if not code:
                continue
            histories.setdefault(code, []).append(row)
        missing_codes = [code for code in missing_codes if code not in histories]

    metrics_map: dict[str, dict[str, Any]] = {}
    for code, rows in histories.items():
        if not rows:
            continue
        rows = sorted(rows, key=lambda item: int(item.get("rn") or 0))
        closes = [_safe_float(item.get("close")) for item in rows]
        volumes = [_safe_float(item.get("volume")) for item in rows]
        latest_close = closes[0] if closes else None
        latest_volume = volumes[0] if volumes else None
        ma5 = _mean(closes[:5])
        ma10 = _mean(closes[:10])
        ma20 = _mean(closes[:20])
        avg_prev5_volume = _mean(volumes[1:6])
        volume_ratio = (
            (latest_volume / avg_prev5_volume)
            if latest_volume is not None and avg_prev5_volume not in (None, 0)
            else None
        )
        change5d = _calc_pct(latest_close, closes[5] if len(closes) > 5 else None)
        change10d = _calc_pct(latest_close, closes[10] if len(closes) > 10 else None)
        change20d = _calc_pct(latest_close, closes[20] if len(closes) > 20 else None)
        rsi = _calc_rsi(closes, period=6)
        change_pct = _safe_float(rows[0].get("change_pct")) if rows else None
        metrics_map[code] = {
            "trade_date": str(rows[0].get("trade_date")) if rows and rows[0].get("trade_date") else None,
            "close": _round_or_none(latest_close),
            "change_pct": _round_or_none(change_pct),
            "ma5": _round_or_none(ma5),
            "ma10": _round_or_none(ma10),
            "ma20": _round_or_none(ma20),
            "volume_ratio": _round_or_none(volume_ratio),
            "rsi": _round_or_none(rsi, 1),
            "change5d": _round_or_none(change5d),
            "change10d": _round_or_none(change10d),
            "change20d": _round_or_none(change20d),
        }
    return metrics_map

router = APIRouter(prefix="/api/ops", tags=["ops"])

MAIN_HUB = MainCentralHub()
CRON_SCHEDULER = HermesCronScheduler(
    MAIN_HUB,
    payload_provider=lambda: build_robot1_scheduler_payload(),
)
ROBOT3_STRATEGY = Robot3SniperStrategy()

# 旧的 HERMES_BASE 和 ROBOT_STRATEGY_MAP 已移到 config.py
# 旧的 _load_robot_result 已移到 adapters.py




def _normalize_review_date(value: Any) -> str:
    if value in (None, "", []):
        return date.today().isoformat()
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return date.today().isoformat()


def _extract_strategy_stocks(strategy_key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    data_block = payload.get("data") if isinstance(payload, dict) else {}
    stocks: list[dict[str, Any]] = []

    if isinstance(data_block, dict):
        stocks = data_block.get("stocks") or []
    if not stocks and isinstance(payload, dict):
        stocks = payload.get("stocks") or []

    # robot-7: data.qinglong + data.baihu
    if not stocks and strategy_key == "qinglong" and isinstance(data_block, dict):
        stocks = (data_block.get("qinglong") or []) + (data_block.get("baihu") or [])

    # robot-11: score_strategy.json 使用 results 字段
    if not stocks and strategy_key == "score":
        if isinstance(data_block, dict):
            stocks = data_block.get("results") or []
        if not stocks and isinstance(payload, dict):
            stocks = payload.get("results") or []

    return stocks if isinstance(stocks, list) else []


@router.get("/scheduler/status")
def get_scheduler_status():
    return CRON_SCHEDULER.status()


@router.post("/scheduler/start")
def start_scheduler():
    CRON_SCHEDULER.start()
    return {
        "status": "ok",
        "scheduler": CRON_SCHEDULER.status(),
    }


@router.post("/scheduler/stop")
def stop_scheduler():
    CRON_SCHEDULER.stop()
    return {
        "status": "ok",
        "scheduler": CRON_SCHEDULER.status(),
    }


@router.post("/scheduler/run-once")
def run_scheduler_once(payload: dict[str, Any] = Body(default_factory=dict)):
    payload = payload or {}
    review_date = _normalize_review_date(payload.get("review_date"))

    # ── 0. 撞车检查:防止跟 launchd 后台采集 / 上一次按钮触发打架 ─────────
    collect_script = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data/scripts/run_collect_once.sh")
    collect_triggered = False
    collect_pid: Optional[int] = None
    collect_error: Optional[str] = None
    already_running = False
    try:
        pgrep_out = subprocess.run(
            ["pgrep", "-f", "tushare_collector.py"],
            capture_output=True, text=True, timeout=2,
        )
        running_pids = [int(x) for x in pgrep_out.stdout.split() if x.strip().isdigit()]
        if running_pids:
            already_running = True
    except Exception:
        pass  # pgrep 失败不阻塞前端

    if not already_running and collect_script.exists() and os.access(collect_script, os.X_OK):
        # ── 1. 异步触发一次性采集(不阻塞 HTTP 响应) ──────────────────────
        try:
            log_dir = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data/logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"collect_button_{date.today().strftime('%Y%m%d_%H%M%S')}.log"
            log_fh = open(log_path, "ab", buffering=0)
            cmd_str = f"unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; {shlex.quote(str(collect_script))} {shlex.quote(review_date.replace('-', ''))}"
            proc = subprocess.Popen(
                ["/bin/bash", "-lc", cmd_str],
                stdout=log_fh, stderr=subprocess.STDOUT,
                start_new_session=True,  # 脱离 cockpit 进程组
            )
            collect_pid = proc.pid
            collect_triggered = True
        except Exception as exc:
            collect_error = str(exc)

    # ── 2. 跑 scheduler 拿前端要的数据(payload 透传) ────────────────────
    scheduler_payload = payload.get("payload")
    if isinstance(scheduler_payload, dict) and scheduler_payload:
        scheduler_result = CRON_SCHEDULER.run_once(payload=scheduler_payload, enforce_time_window=False)
    elif payload.get("use_robot1_review", True):
        scheduler_result = CRON_SCHEDULER.run_once(payload=build_robot1_scheduler_payload(review_date), enforce_time_window=False)
    else:
        scheduler_result = CRON_SCHEDULER.run_once(enforce_time_window=False)

    return {
        "scheduler_result": scheduler_result,
        "collect_triggered": collect_triggered,
        "collect_pid": collect_pid,
        "collect_already_running": already_running,
        "collect_error": collect_error,
    }


@router.get("/robot3/status")
def get_robot3_status():
    report = ROBOT3_STRATEGY.load_latest_report()
    return {
        "status": report.get("status", "EMPTY"),
        "generated_at": report.get("generated_at"),
        "execution_date": report.get("execution_date"),
        "strategy_name": report.get("strategy_name"),
        "radar_count": len(report.get("radar_results", []) or []),
        "report": report,
    }


@router.post("/robot3/run")
def run_robot3_strategy():
    return ROBOT3_STRATEGY.generate_sniper_signals()


@router.post("/custom-analysis")
def run_custom_analysis(payload: dict[str, Any] = Body(...)):
    """
    对自选股票运行指定策略分析
    payload: {
        "stocks": ["000001.SZ", "600519.SH"],
        "strategy": "Union[baihu, qinglong, qlib_factor, theme_momentum, all]"
    }
    """
    stocks = payload.get("stocks", [])
    strategy_raw = payload.get("strategy", "all")

    if not stocks:
        return {"ok": False, "error": "股票列表为空"}

    # 解析策略列表（支持逗号分隔或单个值）
    if isinstance(strategy_raw, list):
        selected_items = [str(s).strip() for s in strategy_raw if str(s).strip()]
    else:
        selected_items = [s.strip() for s in str(strategy_raw).split(",") if s.strip()]

    run_all = "all" in selected_items
    selected_strategy_keys: set[str] = set()
    selected_robot_ids: set[str] = set()
    for item in selected_items:
        if item == "all":
            continue
        if item in ROBOT_STRATEGY_MAP:
            selected_strategy_keys.add(item)
            selected_robot_ids.add(ROBOT_STRATEGY_MAP[item]["id"])
            continue
        mapped_key = ROBOT_ID_TO_KEY.get(item)
        if mapped_key:
            selected_strategy_keys.add(mapped_key)
            selected_robot_ids.add(item)
            continue
        selected_strategy_keys.add(item)

    # 调用 Robot-1 获取股票数据
    try:
        from api.hermes_native.services.robot1_provider import build_robot1_review
        review = build_robot1_review()
    except Exception:
        review = {}

    results = []
    for stock_code in stocks:
        stock_code = stock_code.strip()
        if not stock_code:
            continue

        # 标准化: "000791.SZ" → "000791"
        norm_code = _normalize_stock_code(stock_code)

        # 获取股票基础信息
        stock_info = {
            "code": norm_code,
            "input": stock_code,
            "name": _get_stock_name(stock_code, review),
            "strategies": []
        }

        # 加载各策略结果
        for strategy_key, info in ROBOT_STRATEGY_MAP.items():
            robot_id = info["id"]
            if not run_all and strategy_key not in selected_strategy_keys and robot_id not in selected_robot_ids:
                continue

            result = load_robot_result(strategy_key)
            # 在 stocks 列表中找这只股票（统一走策略抽取器）
            stocks_data = _extract_strategy_stocks(strategy_key, result)
            matched = [
                s for s in stocks_data
                if _normalize_stock_code(s.get("symbol", "")) == norm_code
                or _normalize_stock_code(s.get("code", "")) == norm_code
                or str(s.get("symbol", "")) == stock_code
                or str(s.get("code", "")) == stock_code
            ]
            if matched:
                stock = matched[0]
                # 获取评分 - 不同策略用不同字段
                score = stock.get("score") or stock.get("vol_ratio") or stock.get("net_buy") or 0
                # 获取理由 - 优先用题材/行业/概念
                reason = stock.get("theme") or stock.get("industry") or stock.get("concept") or ""
                if not reason:
                    # 用其他可用字段
                    if stock.get('net_buy'):
                        reason = f"净买入{int(stock.get('net_buy'))}万"
                    elif stock.get('vol_ratio'):
                        reason = f"量比{stock.get('vol_ratio')}x"
                    elif stock.get('change_pct'):
                        reason = f"涨幅{stock.get('change_pct')}%"
                    else:
                        reason = stock.get('reason') or "入选"
                # 过滤ST股票
                name_for_check = stock.get("name", "")
                if name_for_check.startswith("*ST") or name_for_check.startswith("ST"):
                    stock_info["strategies"].append({
                        "name": result.get("name", info["name"]),
                        "signal": "analyze",
                        "score": 0,
                        "reason": "ST股票已过滤"
                    })
                    continue
                stock_info["strategies"].append({
                    "name": result.get("name", info["name"]),
                    "signal": "analyze",
                    "score": score,
                    "reason": reason
                })
                # 附加价格信息（从matched stock中获取）
                if stock.get("close"):
                    stock_info["close"] = stock.get("close")
                    stock_info["change_pct"] = stock.get("change_pct") or stock.get("pct_chg") or 0
            else:
                stock_info["strategies"].append({
                    "name": result.get("name", info["name"]),
                    "signal": "analyze",
                    "score": 0,
                    "reason": "未入选"
                })

        results.append(stock_info)

    return {"ok": True, "results": results, "count": len(results)}


def _normalize_stock_code(code: str) -> str:
    """
    把 "000791.SZ" / "600519.SH" / "000791" 都规范成 6 位纯数字。
    前端 placeholder 提示用户带后缀,但 result.json 里 symbol 字段是 6 位纯数字。
    此外带后缀还能辅助 _get_stock_name 查表。
    """
    if not code:
        return ""
    code = str(code).strip().upper()
    # 剥后缀: .SZ / .SH / .BJ / .HK / .US
    for suf in (".SZ", ".SH", ".BJ", ".HK", ".US"):
        if code.endswith(suf):
            code = code[: -len(suf)]
            break
    return code.zfill(6) if code.isdigit() else code


def _get_stock_name(code: str, review: dict) -> str:
    """从数据库查找股票名称(支持带后缀输入)"""
    if not code:
        return code
    norm = _normalize_stock_code(code)
    try:
        from api.hermes_native.db_connector import execute_query
        rows = execute_query(
            "SELECT name FROM stock_list WHERE symbol = %s OR ts_code = %s LIMIT 1",
            (norm, code.strip().upper()),
        )
        if rows:
            return rows[0].get("name", code)
    except Exception:
        pass
    return code


@router.get("/robot3/latest")
def get_robot3_latest():
    return ROBOT3_STRATEGY.load_latest_report()


def _calculate_backtest_metrics(stocks):
    """计算回测指标（基于当前信号）"""
    if not stocks or len(stocks) == 0:
        return {
            "total_signals": 0,
            "win_rate": 0,
            "avg_return": 0,
            "max_drawdown": 0,
            "sharpe": 0
        }
    
    total_signals = len(stocks)
    positive_returns = 0
    total_return = 0
    max_drawdown = 0
    returns = []
    
    for stock in stocks:
        change_pct = stock.get("change_pct") or stock.get("pct") or 0
        returns.append(change_pct)
        if change_pct > 0:
            positive_returns += 1
        total_return += change_pct
        if change_pct < max_drawdown:
            max_drawdown = change_pct
    
    win_rate = (positive_returns / total_signals) * 100 if total_signals > 0 else 0
    avg_return = total_return / total_signals if total_signals > 0 else 0
    
    returns_mean = avg_return / 100
    returns_std = 0
    if len(returns) > 1:
        variance = sum((r/100 - returns_mean)**2 for r in returns) / (len(returns) - 1)
        returns_std = variance ** 0.5
    
    sharpe = returns_mean / returns_std * (252 ** 0.5) if returns_std > 0 else 0
    
    return {
        "total_signals": total_signals,
        "win_rate": round(win_rate, 1),
        "avg_return": round(avg_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": round(sharpe, 2) if sharpe < 10 else round(sharpe, 1)
    }


import threading

from api.hermes_native.runners.backtest_runner import execute_backtest, save_result, DEFAULT_PARAMS

# robot_id → backtest_runner strategy_name
_ROBOT_BT_STRATEGY = {
    "robot-6": "baihu",
    "robot-100": "baihu-gem",
    "robot-101": "baihu-star",
    "robot-wave": "wave",
}

_backtest_tasks: dict[str, dict] = {}


@router.post("/backtest/run/{robot_id}")
def run_backtest(robot_id: str, body: dict = {}):
    """在后台线程执行回测，立即返回"""
    strategy_name = _ROBOT_BT_STRATEGY.get(robot_id)
    if not strategy_name:
        return {"ok": False, "error": f"不支持的机器人: {robot_id}"}

    task = _backtest_tasks.get(robot_id, {})
    if task.get("running"):
        return {"ok": False, "error": "回测已在运行中，请等待完成"}

    params = {**DEFAULT_PARAMS, **body.get("params", {})}
    days = max(60, min(int(body.get("days", 180)), 365))
    stock_filter = body.get("stock_filter")  # 扫描范围 key: 'gem_star' | 'gem' | 'star' | 'all'
    max_samples = max(10, min(int(body.get("max_samples", 50)), 500))  # 样本数量限制
    use_pytdx = bool(body.get("use_pytdx", False))  # 是否使用 pytdx 实时数据源

    _backtest_tasks[robot_id] = {"running": True, "error": None}

    def _run():
        try:
            print('[bt] thread started', flush=True)
            result = execute_backtest(strategy_name, params, days, stock_filters=stock_filter, max_samples=max_samples, use_pytdx=use_pytdx)
            print(f'[bt] result: signal_cnt={result.get("signal_cnt")}, win_rate={result.get("win_rate")}', flush=True)
            save_result(strategy_name, result)
            print('[bt] saved', flush=True)
            _backtest_tasks[robot_id] = {"running": False, "error": None, "done": True}
        except Exception as e:
            import traceback
            traceback.print_exc()
            _backtest_tasks[robot_id] = {"running": False, "error": str(e), "done": True}

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return {"ok": True, "message": "回测任务已启动"}


@router.get("/backtest/status/{robot_id}")
def get_backtest_status(robot_id: str):
    """查询回测任务状态"""
    task = _backtest_tasks.get(robot_id, {})
    return {
        "running": task.get("running", False),
        "done": task.get("done", False),
        "error": task.get("error"),
    }


# strategy_key → 独立回测结果文件路径（不影响信号页的 load_robot_result）
_BACKTEST_RESULT_PATHS: dict[str, str] = {
    "baihu": "/Users/gino/backtest_results/baihu/result.json",
    "baihu_gem": "/Users/gino/backtest_results/baihu-gem/result.json",
    "baihu_star": "/Users/gino/backtest_results/baihu-star/result.json",
}


@router.get("/backtest/{robot_id}")
def get_backtest(robot_id: str):
    """获取指定机器人的回测/策略结果"""
    # 使用 config.py 的反向映射（robot 编号 -> 策略 key）
    strategy_key = ROBOT_ID_TO_KEY.get(robot_id, robot_id.replace("robot-", ""))
    info = ROBOT_STRATEGY_MAP.get(strategy_key, {"id": robot_id, "name": robot_id})

    normalized = {}
    is_real_backtest = False

    # 优先读取独立回测结果文件（由"运行回测"生成）
    backtest_path_str = _BACKTEST_RESULT_PATHS.get(strategy_key)
    if backtest_path_str:
        bp = Path(backtest_path_str)
        if bp.exists():
            try:
                with open(bp, "r", encoding="utf-8") as f:
                    raw_bt = json.load(f)
                if isinstance(raw_bt, dict) and isinstance(raw_bt.get("data"), dict) and raw_bt["data"].get("win_rate") is not None:
                    is_real_backtest = True
                    normalized = raw_bt
                    normalized["robot"] = robot_id
                    normalized["name"] = normalized.get("name") or info["name"]
            except Exception:
                pass

    # 没有真实回测，回退到日常信号数据
    if not is_real_backtest:
        result = load_robot_result(strategy_key)
        if "error" in result and result.get("error") == "no data":
            return {"robot": robot_id, "name": info["name"], "data": {"stocks": [], **_calculate_backtest_metrics([])}, "count": 0, "metrics_source": "signal"}
        normalized = dict(result) if isinstance(result, dict) else {"data": result}
        normalized["robot"] = robot_id
        normalized["name"] = normalized.get("name") or info["name"]

    stocks_data = normalized.get("data", {}).get("stocks", normalized.get("stocks", []))

    if "data" not in normalized:
        normalized["data"] = {}

    if is_real_backtest:
        normalized["metrics_source"] = "backtest"
    else:
        # 从当日信号计算指标（仅供参考，不是真正的历史回测）
        metrics = _calculate_backtest_metrics(stocks_data)
        normalized["data"].update(metrics)
        normalized["metrics_source"] = "signal"
    normalized["data"]["stocks"] = stocks_data

    return normalized


@router.get("/backtest/{robot_id}/full")
def get_full_backtest(robot_id: str):
    """获取指定机器人的全量历史回测结果"""
    strategy_key = ROBOT_ID_TO_KEY.get(robot_id, robot_id.replace("robot-", ""))
    info = ROBOT_STRATEGY_MAP.get(strategy_key, {"id": robot_id, "name": robot_id})
    
    try:
        query = """
            SELECT s.code, s.signal_time, s.signal_type, 
                   k.close AS signal_close, k_next.close AS next_close
            FROM signals s
            LEFT JOIN kline_daily k ON s.code = k.code AND s.signal_time::DATE = k.trade_date
            LEFT JOIN kline_daily k_next ON s.code = k_next.code AND s.signal_time::DATE + INTERVAL '1 day' = k_next.trade_date
            WHERE s.signal_type = %s
            ORDER BY s.signal_time DESC
            LIMIT 500
        """
        
        results = execute_query(query, (strategy_key,))
        
        returns = []
        for row in results:
            signal_close = row.get('signal_close')
            next_close = row.get('next_close')
            if signal_close and next_close and signal_close > 0:
                ret = (next_close - signal_close) / signal_close * 100
                returns.append(ret)
        
        if not returns:
            return {
                "robot": robot_id,
                "name": info["name"],
                "data": {
                    "total_signals": 0,
                    "win_rate": 0,
                    "avg_return": 0,
                    "max_drawdown": 0,
                    "sharpe": 0,
                    "type": "full_backtest",
                    "period": "历史全量"
                },
                "count": 0
            }
        
        import numpy as np
        returns_np = np.array(returns)
        wins = len(returns_np[returns_np > 0])
        win_rate = wins / len(returns_np) * 100
        avg_return = np.mean(returns_np)
        
        cum_returns = np.cumsum(returns_np)
        running_max = np.maximum.accumulate(cum_returns)
        drawdown = cum_returns - running_max
        max_drawdown = np.min(drawdown)
        
        sharpe = avg_return / np.std(returns_np) * np.sqrt(252) if np.std(returns_np) > 0 else 0
        
        return {
            "robot": robot_id,
            "name": info["name"],
            "data": {
                "total_signals": len(returns),
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_return, 2),
                "max_drawdown": round(max_drawdown, 2),
                "sharpe": round(sharpe, 2) if sharpe < 10 else round(sharpe, 1),
                "type": "full_backtest",
                "period": "历史全量"
            },
            "count": len(returns)
        }
        
    except Exception as e:
        return {
            "robot": robot_id,
            "name": info["name"],
            "data": {
                "total_signals": 0,
                "win_rate": 0,
                "avg_return": 0,
                "max_drawdown": 0,
                "sharpe": 0,
                "type": "full_backtest",
                "period": "历史全量",
                "error": str(e)
            },
            "count": 0
        }


# ── 策略信号内存缓存（文件 mtime 变更时自动失效）──────────────────
import time as _time

_strategy_cache: dict[str, Any] = {}
_strategy_cache_mtimes: dict[str, float] = {}
_strategy_cache_ts: float = 0.0
_STRATEGY_CACHE_TTL = 15  # 秒：即使文件无变化，15 秒后也刷新

def _get_strategy_file_mtimes() -> dict[str, float]:
    """收集所有策略结果文件的 mtime"""
    mtimes: dict[str, float] = {}
    for key, info in ROBOT_STRATEGY_MAP.items():
        if not info.get("script_name"):
            continue
        fp = Path(info["path"])
        try:
            mtimes[key] = fp.stat().st_mtime
        except OSError:
            mtimes[key] = 0.0
    return mtimes


@router.get("/robot-strategies")
def get_robot_strategies():
    """获取可运行策略机器人的实时信号（过滤掉无脚本的纯回测策略）"""
    global _strategy_cache, _strategy_cache_mtimes, _strategy_cache_ts

    now = _time.monotonic()
    # 检查缓存是否可用：TTL 内 + 文件 mtime 未变
    if _strategy_cache and (now - _strategy_cache_ts) < _STRATEGY_CACHE_TTL:
        current_mtimes = _get_strategy_file_mtimes()
        if current_mtimes == _strategy_cache_mtimes:
            return _strategy_cache

    # 重新计算
    result = {}
    for key, info in ROBOT_STRATEGY_MAP.items():
        # 跳过纯回测策略（没有 script_name 的，如 robot-100/101）
        if not info.get("script_name"):
            continue
        data = load_robot_result(key)
        stocks = _extract_strategy_stocks(key, data)
        has_stocks = bool(stocks)
        count = len(stocks)
        # 确保 data 字段始终是标准数据结构，不是包装对象
        inner_data = data.get("data")
        if isinstance(inner_data, dict):
            result_data = inner_data
        else:
            result_data = {"stocks": stocks}
        result[info["id"]] = {
            "id": info["id"],
            "name": info["name"],
            "display_name": info.get("display_name", info["name"]),
            "key": key,
            "has_data": has_stocks,
            "count": count,
            "trade_date": data.get("trade_date", data.get("timestamp", "")[:10]),
            "data": result_data,
        }

    _strategy_cache = result
    _strategy_cache_mtimes = _get_strategy_file_mtimes()
    _strategy_cache_ts = now
    return result


@router.get("/robot-strategies-history")
def get_robot_strategies_history():
    """获取策略历史按日期，按robotId索引"""
    # 返回格式: { "robot-6": [{date: "2026-05-29", stocks: [...], name: "白虎-科创创业V26"}, ...], "robot-7": [...] }
    result = {}
    for robot_id in ALL_ROBOT_IDS:
        result[robot_id] = []

    def add_history_item(robot_id, name, date_str, stocks):
        if not date_str or not stocks:
            return
        existing = next((item for item in result[robot_id] if item.get("date") == date_str), None)
        if existing is None:
            result[robot_id].append({
                "date": date_str,
                "name": name,
                "stocks": list(stocks),
                "count": len(stocks),
            })
            return
        seen = {
            str(stock.get("symbol") or stock.get("code") or stock.get("name") or "")
            for stock in existing.get("stocks", [])
            if isinstance(stock, dict)
        }
        for stock in stocks:
            if not isinstance(stock, dict):
                continue
            code = str(stock.get("symbol") or stock.get("code") or stock.get("name") or "")
            if code and code in seen:
                continue
            seen.add(code)
            existing["stocks"].append(stock)
        existing["count"] = len(existing["stocks"])

    # 遍历所有策略路径
    for key, info in ROBOT_STRATEGY_MAP.items():
        robot_id = info["id"]
        strategy_path = Path(info["path"])
        # config.py 中 path 是 Path 对象，历史目录统一取其父目录
        history_dir = str(strategy_path.parent)
        if not os.path.exists(history_dir):
            continue
        # 查找所有result*.json备份
        for fname in os.listdir(history_dir):
            if not fname.startswith("result"):
                continue
            if not fname.endswith(".json"):
                continue
            # result_2026-05-29.json -> 2026-05-29
            # result.json 没有日期后缀，后续从数据本身提取选股日期
            if fname == "result.json":
                date_str = None
            else:
                import re
                m = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
                date_str = m.group(1) if m else None
            try:
                with open(f"{history_dir}/{fname}", "r", encoding="utf-8") as f:
                    data = json.load(f)
                stocks = _extract_strategy_stocks(key, data)

                resolved_date = date_str
                if not resolved_date:
                    resolved_date = (
                        data.get("trade_date")
                        or data.get("selected_date")
                        or data.get("date")
                        or (str(data.get("timestamp", ""))[:10] if data.get("timestamp") else "")
                    )
                if (not resolved_date or resolved_date == "today") and stocks:
                    first_stock = stocks[0] if isinstance(stocks[0], dict) else {}
                    if isinstance(first_stock, dict):
                        resolved_date = (
                            first_stock.get("trade_date")
                            or first_stock.get("selected_date")
                            or first_stock.get("signal_date")
                            or first_stock.get("date")
                            or resolved_date
                        )
                if not resolved_date or resolved_date == "today":
                    resolved_date = date.today().isoformat()
                resolved_date = str(resolved_date)[:10]

                add_history_item(robot_id, info["name"], resolved_date, stocks)
            except Exception:
                pass

        archive_dir = f"/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/robot-history/{robot_id}"
        if os.path.exists(archive_dir):
            for fname in os.listdir(archive_dir):
                if not fname.endswith(".json"):
                    continue
                import re
                m = re.search(r'(\d{4}-\d{2}-\d{2})', fname)
                date_str = m.group(1) if m else None
                if not date_str:
                    continue
                try:
                    with open(f"{archive_dir}/{fname}", "r", encoding="utf-8") as f:
                        data = json.load(f)
                    stocks = _extract_strategy_stocks(key, data)
                    add_history_item(robot_id, info["name"], date_str, stocks)
                except Exception:
                    pass

    # 每robot按日期排序（最新在前）
    for robot_id in result:
        result[robot_id] = sorted(result[robot_id], key=lambda x: x.get("date", ""), reverse=True)[:30]
    return result


@router.get("/backtest-summary")
def get_backtest_summary():
    """获取回测汇总"""
    summary = []
    for key, info in ROBOT_STRATEGY_MAP.items():
        result = load_robot_result(key)
        count = len(_extract_strategy_stocks(key, result))
        summary.append({
            "robot": info["id"],
            "name": info["name"],
            "count": count,
            "trade_date": result.get("trade_date", ""),
        })
    return {"summary": summary}


@router.get("/strategy-catalog")
def get_strategy_catalog():
    """返回前端可用的策略目录"""
    # 过滤掉 hidden 策略（如波浪分析）
    visible_catalog = [item for item in STRATEGY_CATALOG if not item.get("hidden")]
    return {
        "items": visible_catalog,
        "default_custom_strategy_keys": list(DEFAULT_CUSTOM_STRATEGY_KEYS),
        "robot_ids": list(ALL_ROBOT_IDS),
    }


# ── 策略执行触发 ─────────────────────────────────────────────────────
import subprocess
from pathlib import Path

# 各策略的脚本路径映射（统一为 .sh 启动脚本）
_STRATEGY_SCRIPTS: dict[str, str] = {
    "baihu":         "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot6.sh",
    "qinglong":      "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot7.sh",
    "robot8":        "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot8.sh",
    "qlib_factor":   "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot9.sh",
    "theme_momentum":"/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot10.sh",
    "score":         "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot11.sh",
    "mode2":         "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot12.sh",
    "alpha":         "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot13.sh",
    "sector_rotate": "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot14.sh",
    "turtle":        "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot15.sh",
    "volume_surge":  "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot16.sh",
    "ma250_backtrace": "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot17.sh",
    "breakthrough_platform": "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/scripts/run_robot18.sh",
}


@router.post("/run-strategy/{strategy_key}")
def run_strategy(strategy_key: str, background: bool = True):
    """
    触发执行指定策略脚本。
    background=True 异步执行（推荐），立即返回 task_id
    background=False 同步执行（等结果），用于调试
    """
    resolved_key = strategy_key if strategy_key in _STRATEGY_SCRIPTS else ROBOT_ID_TO_KEY.get(strategy_key, strategy_key)
    script = _STRATEGY_SCRIPTS.get(resolved_key)
    if not script:
        return {"ok": False, "error": f"unknown strategy: {strategy_key}"}

    script_path = Path(script)
    if not script_path.exists():
        return {"ok": False, "error": f"script not found: {script}"}

    # Python 脚本用 sys.executable 运行
    is_python = script_path.suffix == ".py"
    cmd = [sys.executable, str(script_path)] if is_python else [str(script_path)]

    if background:
        # 异步执行，结果写入文件，stdout/stderr 重定向到日志
        log_path = Path("/Users/gino/Projects/AIROBOT/backend/strategy_runs") / f"{strategy_key}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            cmd,
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return {
            "ok": True,
            "strategy": resolved_key,
            "status": "started",
            "log": str(log_path),
        }
    else:
        # 同步执行
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "ok": r.returncode == 0,
                "strategy": resolved_key,
                "returncode": r.returncode,
                "stdout": r.stdout[-2000:] if r.stdout else "",
                "stderr": r.stderr[-1000:] if r.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout (300s)"}


@router.post("/run-all-strategies")
def run_all_strategies():
    """触发所有策略脚本（异步）"""
    results = []
    for key, script in _STRATEGY_SCRIPTS.items():
        script_path = Path(script)
        if not script_path.exists():
            results.append({"strategy": key, "status": "skipped", "reason": "no script"})
            continue
        log_path = Path("/Users/gino/Projects/AIROBOT/backend/strategy_runs") / f"{key}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        is_python = script_path.suffix == ".py"
        cmd = [sys.executable, str(script_path)] if is_python else [str(script_path)]
        subprocess.Popen(
            cmd,
            stdout=open(log_path, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        results.append({"strategy": key, "status": "started", "log": str(log_path)})
    return {"ok": True, "results": results}


@router.get("/strategy-run-log/{strategy_key}")
def get_strategy_run_log(strategy_key: str, lines: int = 100):
    """查看策略最近执行日志"""
    log_path = Path("/Users/gino/Projects/AIROBOT/backend/strategy_runs") / f"{strategy_key}.log"
    if not log_path.exists():
        return {"ok": False, "error": "no log", "strategy": strategy_key}
    try:
        content = log_path.read_text(encoding="utf-8", errors="ignore")
        tail = "\n".join(content.splitlines()[-lines:])
        return {"ok": True, "strategy": strategy_key, "log": tail, "path": str(log_path)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/watchlist-with-leaders")
def get_watchlist_with_leaders(force_refresh: bool = False):
    """
    选股监控聚合页面。
    当前以 monitor.stock_pool 为主池，再叠加东方财富模拟盘持仓和技术指标。
    force_refresh=true 时绕过缓存，强制从东方财富拉取最新行情。
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        ensure_monitor_schema()
        bootstrap_from_legacy_wave_watchlist()
        merged: dict[str, dict[str, Any]] = {}  # code -> stock info

        # 1. 从东方财富模拟盘拉持仓
        try:
            from api.hermes_native.services.miaoxiang_service import mock_positions
            pos_raw = mock_positions() or {}
            if not isinstance(pos_raw, dict):
                pos_raw = {}
            try:
                sync_broker_positions(pos_raw)
            except Exception as sync_err:
                logger.warning("broker sync err: %s", sync_err)
            pos_data = pos_raw.get("data", pos_raw)
            for p in pos_data.get("posList", []):
                code = str(p.get("secCode", "")).strip()
                if not code or not code.isdigit():
                    continue
                merged[code] = {
                    "code": code,
                    "name": p.get("secName", code),
                    "price": p.get("price", 0) / (10 ** p.get("priceDec", 2)),
                    "cost": p.get("costPrice", p.get("price", 0)) / (10 ** p.get("costPriceDec", 2)),
                    "count": p.get("count", 0),
                    "profitPct": round(p.get("profitPct", 0), 2),
                    "source": "holding",
                    "priceUpdatedAt": None,
                }
        except Exception as e:
            logger.warning("mock_positions err: %s", e)

        # 2. 从监控主池补充观察/波段股票
        try:
            for item in get_pool_rows_for_stock_monitor():
                code = str(item.get("code", "")).strip().zfill(6)
                if not code:
                    continue
                existing = merged.get(code)
                source = "holding" if (str(item.get("execution_status") or "") == "holding" or int(item.get("position_qty") or 0) > 0) else ("wave" if item.get("in_wave_pool") else "monitor")
                payload = {
                    "code": code,
                    "name": item.get("name", code),
                    "market": item.get("market", ""),
                    "industry": item.get("industry") or "",
                    "price": float(item.get("last_price") or 0) if item.get("last_price") is not None else 0,
                    "cost": float(item.get("cost_price") or 0) if item.get("cost_price") is not None else 0,
                    "count": int(item.get("position_qty") or 0),
                    "profitPct": 0,
                    "source": source if not existing else existing.get("source", source),
                    "priceUpdatedAt": item.get("last_trade_date"),
                    "tracking_status": item.get("tracking_status"),
                    "execution_status": item.get("execution_status"),
                    "in_wave_pool": bool(item.get("in_wave_pool")),
                    "in_monitor_pool": bool(item.get("in_monitor_pool")),
                    "latest_source_type": item.get("latest_source_type"),
                    "latest_source_key": item.get("latest_source_key"),
                }
                if existing:
                    existing.update({k: v for k, v in payload.items() if v not in (None, "", 0) or k in {"tracking_status", "execution_status", "in_wave_pool", "in_monitor_pool", "latest_source_type", "latest_source_key"}})
                else:
                    merged[code] = payload
        except Exception as e:
            logger.warning("monitor pool err: %s", e)

        realtime_map: dict[str, dict[str, Any]] = {}
        realtime_updated_at = None
        realtime_source = None
        try:
            realtime_result = load_or_sync_realtime_quotes(
                list(merged.keys()),
                ttl_seconds=300,
                force_refresh=force_refresh,
                source_key="api/ops/watchlist-with-leaders",
            )
            realtime_map = realtime_result.get("items_map") or {}
            realtime_source = realtime_result.get("source")
            realtime_items = realtime_result.get("items") or []
            realtime_times = [
                _format_datetime(item.get("updated_at"))
                for item in realtime_items
                if isinstance(item, dict) and item.get("updated_at")
            ]
            realtime_times = [item for item in realtime_times if item]
            if realtime_times:
                realtime_updated_at = max(realtime_times)
        except Exception as e:
            logger.warning("realtime quotes err: %s", e)

        stock_meta_map = _load_stock_meta_map(list(merged.keys()))
        kline_metrics_map = _load_recent_kline_metrics(list(merged.keys()))

        for code, entry in merged.items():
            meta = stock_meta_map.get(code) or {}
            metrics = kline_metrics_map.get(code) or {}
            realtime = realtime_map.get(code) or {}
            realtime_price = _safe_float(realtime.get("price"))
            realtime_change_pct = _safe_float(realtime.get("change_pct"))
            realtime_open = _safe_float(realtime.get("open_price") or realtime.get("open"))
            realtime_high = _safe_float(realtime.get("high_price") or realtime.get("high"))
            realtime_low = _safe_float(realtime.get("low_price") or realtime.get("low"))
            realtime_close = _safe_float(realtime.get("close"))
            realtime_volume = _safe_float(realtime.get("volume"))
            realtime_amount = _safe_float(realtime.get("amount"))
            realtime_turnover = _safe_float(realtime.get("turnover_rate"))
            latest_close = _safe_float(metrics.get("close"))
            current_price = _safe_float(entry.get("price"))
            if realtime_price is not None:
                entry["price"] = realtime_price
                current_price = realtime_price
            elif current_price in (None, 0.0) and latest_close is not None:
                entry["price"] = latest_close
                current_price = latest_close
            if current_price in (None, 0.0) and latest_close is not None:
                entry["price"] = latest_close
                current_price = latest_close
            if realtime.get("updated_at"):
                entry["priceUpdatedAt"] = realtime.get("updated_at")
            elif not entry.get("priceUpdatedAt") and metrics.get("trade_date"):
                entry["priceUpdatedAt"] = metrics["trade_date"]
            if latest_close is not None:
                entry["close"] = latest_close
            if realtime_change_pct is not None:
                entry["change_pct"] = realtime_change_pct
            if realtime_open is not None:
                entry["open"] = realtime_open
            if realtime_high is not None:
                entry["high"] = realtime_high
            if realtime_low is not None:
                entry["low"] = realtime_low
            if realtime_close is not None:
                entry["realtime_close"] = realtime_close
            if realtime_volume is not None:
                entry["volume"] = realtime_volume
            if realtime_amount is not None:
                entry["amount"] = realtime_amount
            if realtime_turnover is not None:
                entry["turnover_rate"] = realtime_turnover
            if meta.get("name") and not entry.get("name"):
                entry["name"] = meta["name"]
            if meta.get("market"):
                entry["market"] = meta["market"]
            entry["industry"] = meta.get("industry") or entry.get("industry") or "未分类"
            for field in ("change_pct", "ma5", "ma10", "ma20", "volume_ratio", "rsi", "change5d", "change10d", "change20d"):
                if metrics.get(field) is not None:
                    entry[field] = metrics[field]
            entry["pattern"] = entry.get("pattern") or ("持有" if entry.get("source") == "holding" else "观察池")
            if current_price is not None and _safe_float(entry.get("ma20")) not in (None, 0.0):
                deviation = _calc_pct(current_price, _safe_float(entry.get("ma20")))
                entry["deviation"] = _round_or_none(deviation)

        # 3. 从机器人策略(白虎)补充技术指标
        try:
            baihu = load_robot_result("baihu")
            strategy = baihu.get("data", baihu)
            for item in (strategy.get("stocks") or []):
                code = str(item.get("symbol") or item.get("code") or "").strip()
                if not code:
                    continue
                entry = merged.get(code)
                if entry is None:
                    continue
                entry["close"] = item.get("close") or entry.get("close", 0)
                entry["score"] = item.get("score")
                entry["change_pct"] = item.get("change_pct")
                entry["rsi"] = item.get("rsi")
                entry["vol_ratio"] = item.get("vol_ratio")
                entry["deviation"] = item.get("deviation")
                entry["industry"] = item.get("industry") or entry.get("industry", "")
                entry["pattern"] = "强势回调"
                entry["day20Gain"] = item.get("20day_gain")
                entry["ma20"] = item.get("ma20")
        except Exception as e:
            logger.warning("baihu enrich err: %s", e)

        # 4. 统一计算 leader_level、recommendation、risk_signals
        for code, entry in merged.items():
            score_val = _safe_float(entry.get("score"))
            change_pct = _safe_float(entry.get("change_pct"))
            deviation = _safe_float(entry.get("deviation"))
            rsi = _safe_float(entry.get("rsi"))
            vol_ratio = _safe_float(entry.get("vol_ratio"))
            ma5 = _safe_float(entry.get("ma5"))
            ma10 = _safe_float(entry.get("ma10"))
            profit_pct = _safe_float(entry.get("profitPct"))
            source = entry.get("source", "")

            macd_label = _calc_macd_label(ma5, ma10)
            if score_val is None:
                score_val = _derive_total_score(change_pct, deviation, rsi, macd_label, vol_ratio)

            entry["leader_level"] = _derive_leader_level(score_val)
            entry["recommendation"] = _derive_recommendation(score_val)
            entry["risk_signals"] = _build_risk_signals(
                deviation=deviation,
                volume_ratio=vol_ratio,
                rsi=rsi,
                macd_label=macd_label,
                profit_pct=profit_pct,
                source=source,
            )

        # 排序: 持仓在前,观察在后,同组按code排序
        result = sorted(merged.values(), key=lambda x: (0 if x.get("source") == "holding" else 1, x.get("code", "")))
        return {
            "items": result,
            "realtime_updated_at": realtime_updated_at,
            "realtime_source": realtime_source,
            "realtime_count": len(realtime_map),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "items": []}


@router.get("/stock-analysis-latest")
def get_stock_analysis_latest():
    """返回机器人策略技术分析数据"""
    try:
        s = load_robot_result("baihu")
        strategy = s.get("data") or s if s else None

        results = []
        if strategy and isinstance(strategy, dict):
            for item in (strategy.get("stocks") or []):
                code = str(item.get("symbol") or item.get("code") or "").strip()
                if not code:
                    continue
                change_pct = item.get("change_pct")
                deviation = item.get("deviation")
                rsi = item.get("rsi")
                vol_ratio = item.get("vol_ratio")
                ma5 = item.get("ma5")
                ma10 = item.get("ma10")
                macd_label = _calc_macd_label(ma5, ma10)
                total_score = _derive_total_score(change_pct, deviation, rsi, macd_label, vol_ratio)
                results.append({
                    "code": code,
                    "name": item.get("name") or item.get("theme") or code,
                    "indicators": {
                        "ma5": ma5,
                        "ma10": ma10,
                        "ma20": item.get("ma20"),
                        "change_pct": change_pct,
                        "volume_ratio": vol_ratio,
                        "rsi": rsi,
                    },
                    "leader_level": _derive_leader_level(total_score),
                    "scoring": {
                        "total_score": total_score,
                        "recommendation": _derive_recommendation(total_score),
                        "risk_signals": _build_risk_signals(
                            deviation=deviation,
                            volume_ratio=vol_ratio,
                            rsi=rsi,
                            macd_label=macd_label,
                        ),
                        "scores": {
                            "trend": _calc_trend_score(change_pct),
                            "deviation_score": _calc_deviation_score(deviation),
                            "rsi_score": _calc_rsi_score(rsi),
                            "macd_score": _calc_macd_score(macd_label),
                            "vol_score": _calc_vol_score(vol_ratio),
                        },
                    },
                })
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e), "results": []}


@router.get("/miaoxiang/quote")
def miaoxiang_quote(codes: str = ""):
    """实时行情查询。codes: 逗号分隔，如 300502.SZ,300308.SZ"""
    try:
        if not codes:
            return {"ok": False, "error": "codes 必填"}
        items = mx_quote([c.strip() for c in codes.split(",") if c.strip()])
        return {"ok": True, "count": len(items), "items": items}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/miaoxiang/index")
def miaoxiang_index():
    """查询主要指数行情"""
    try:
        idx = mx_quote(["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"])
        return {"ok": True, "count": len(idx), "items": idx}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/miaoxiang/select")
def miaoxiang_select(condition: str = ""):
    """智能选股。condition: 选股条件"""
    try:
        if not condition:
            return {"ok": False, "error": "condition 必填"}
        stocks = mx_select(condition)
        return {"ok": True, "count": len(stocks), "stocks": stocks}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/miaoxiang/news")
def miaoxiang_news(keyword: str = ""):
    """搜索财经资讯"""
    try:
        if not keyword:
            return {"ok": False, "error": "keyword 必填"}
        news = mx_news(keyword)
        return {"ok": True, "count": len(news), "news": news}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/stock-advice/providers")
def get_stock_advice_providers():
    """列出所有可用的 AI 分析提供商"""
    return {"ok": True, "providers": list_providers()}


@router.get("/stock-advice")
def get_stock_advice(
    code: str = "",
    name: str = "",
    price: float = 0,
    cost: float = 0,
    profit: float = 0,
    score: float = 0,
    provider: str = "",
):
    """个股 AI 分析建议 — 多提供商支持

    参数:
    - provider: 提供商 key，为空则返回所有提供商的分析结果
    - 可选值: eastmoney(东方财富), guoxin(国信证券)
    """
    if not code:
        return {"ok": False, "error": "code 必填"}

    code_clean = str(code).strip().zfill(6)
    stock = StockInfo(
        code=code_clean,
        name=name,
        price=price,
        cost=cost,
        profit_pct=profit,
        score=score,
    )

    # 指定单个提供商
    if provider:
        p = get_provider(provider)
        if not p:
            available = [info["key"] for info in list_providers()]
            return {
                "ok": False,
                "error": f"未知提供商: {provider}，可用: {', '.join(available)}",
            }
        try:
            report = p.analyze(stock)
            return {
                "ok": True,
                "provider": report.provider_key,
                "provider_name": report.provider_name,
                "summary": report.summary,
                "sections": [
                    {"title": s.title, "content": s.content, "style": s.style}
                    for s in report.sections
                ],
                "advice": report.raw_text,
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "advice": f"分析失败: {e}"}

    # 返回所有提供商的分析结果
    providers = list_providers()
    if not providers:
        return {"ok": False, "error": "无可用分析提供商"}

    results = []
    fallback_advice = ""
    for p_info in providers:
        p = get_provider(p_info["key"])
        if not p:
            continue
        try:
            report = p.analyze(stock)
            result = {
                "provider": report.provider_key,
                "provider_name": report.provider_name,
                "summary": report.summary,
                "sections": [
                    {"title": s.title, "content": s.content, "style": s.style}
                    for s in report.sections
                ],
                "advice": report.raw_text,
            }
            results.append(result)
            if not fallback_advice:
                fallback_advice = report.raw_text
        except Exception as e:
            results.append({
                "provider": p_info["key"],
                "provider_name": p_info["name"],
                "summary": f"分析失败: {e}",
                "sections": [],
                "advice": f"分析失败: {e}",
            })

    return {
        "ok": True,
        "providers": results,
        "advice": fallback_advice,
    }


@router.get("/market-trends")
def get_market_trends_endpoint(
    date: str = "",
    days: int = 30,
):
    """获取近N日市场趋势数据（指数走势、情绪变化、涨停趋势）

    参数:
    - date: 基准日期 YYYY-MM-DD，默认最新
    - days: 回溯天数，默认30
    """
    return get_market_trends(date, days)


@router.get("/realtime/quotes")
def get_realtime_quotes(codes: str = "", refresh: bool = False, ttl_seconds: int = 25):
    """读取或刷新共享实时行情快照，供页面和机器人复用。"""
    try:
        ensure_monitor_schema()
        code_list = [c.strip() for c in codes.split(",") if c.strip()]
        if code_list:
            result = load_or_sync_realtime_quotes(
                code_list,
                ttl_seconds=max(1, int(ttl_seconds or 25)),
                force_refresh=bool(refresh),
                source_key="api/ops/realtime/quotes",
            )
            return {
                "ok": True,
                "count": result.get("count", 0),
                "requested": result.get("requested", len(code_list)),
                "source": result.get("source", "cache"),
                "items": result.get("items", []),
            }
        rows = get_realtime_quote_rows()
        return {
            "ok": True,
            "count": len(rows),
            "requested": 0,
            "source": "cache",
            "items": rows,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "items": []}


@router.get("/watchlist")
def get_watchlist():
    """返回监控池中的自选/波段股票列表"""
    try:
        ensure_monitor_schema()
        bootstrap_from_legacy_wave_watchlist()
        rows = get_watchlist_items()
        return [
            {
                "code": row.get("code", ""),
                "name": row.get("name", ""),
                "market": row.get("market", ""),
                "industry": row.get("industry", ""),
                "tracking_status": row.get("tracking_status", ""),
                "execution_status": row.get("execution_status", ""),
                "in_wave_pool": bool(row.get("in_wave_pool")),
            }
            for row in rows
        ]
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/watchlist/add")
def add_to_watchlist(payload: dict[str, Any] = Body(...)):
    """添加股票到监控池(不直接进入波段池)"""
    try:
        code = str(payload.get("code") or "").strip().zfill(6)
        if not code.isdigit() or len(code) != 6:
            return {"ok": False, "error": "invalid code"}
        name = payload.get("name", code)
        market = "SZ" if code[0] in ("0", "3") else "SH"
        row = add_monitor_stock(
            code=code,
            name=name,
            market=market,
            source_type=str(payload.get("source_type") or "manual"),
            source_key=str(payload.get("source_key") or payload.get("source_ref") or "watchlist.add"),
            source_ref=str(payload.get("source_ref") or code),
            signal_date=payload.get("signal_date"),
            signal=payload.get("signal"),
            score=payload.get("score"),
            reason=payload.get("reason"),
            source_page=str(payload.get("source_page") or "stock_monitor"),
            metadata={"price": payload.get("price"), "count": payload.get("count")},
        )
        # 同步到 AIROBOT 共享自选股（失败不影响主流程）
        _sync_add_to_shared_watchlist(code, name=str(row.get("name") or name or code))
        return {
            "success": True,
            "code": code,
            "name": row.get("name"),
            "market": row.get("market"),
            "tracking_status": row.get("tracking_status"),
            "in_wave_pool": bool(row.get("in_wave_pool")),
            "message": "已加入选股监控",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/watchlist/remove")
def remove_from_watchlist(payload: dict[str, Any] = Body(...)):
    """从监控池剔除；若已持仓则保留持仓记录但退出观察/波段池。"""
    try:
        code = str(payload.get("code") or "").strip().zfill(6)
        if not code.isdigit() or len(code) != 6:
            return {"ok": False, "error": "invalid code"}
        row = remove_monitor_stock(code, source_page=str(payload.get("source_page") or "stock_monitor"))
        # 同步从 AIROBOT 共享自选股移除（失败不影响主流程）
        _sync_remove_from_shared_watchlist(code)
        if not row:
            return {"success": True, "code": code, "message": "股票不在监控池中"}
        return {
            "success": True,
            "code": code,
            "tracking_status": row.get("tracking_status"),
            "execution_status": row.get("execution_status"),
            "message": "已从选股监控剔除",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/watchlist/set-wave")
def set_watchlist_wave_state(payload: dict[str, Any] = Body(...)):
    """设置股票是否进入波段池，供后续页面动作直接调用。"""
    try:
        code = str(payload.get("code") or "").strip().zfill(6)
        if not code.isdigit() or len(code) != 6:
            return {"ok": False, "error": "invalid code"}
        enabled = bool(payload.get("enabled", True))
        row = set_wave_pool_membership(
            code=code,
            enabled=enabled,
            name=payload.get("name"),
            market=payload.get("market"),
            note=payload.get("note"),
            source_type=str(payload.get("source_type") or "manual"),
            source_key=str(payload.get("source_key") or "watchlist.set-wave"),
            source_page=str(payload.get("source_page") or "stock_monitor"),
        )
        return {
            "success": True,
            "code": row.get("code"),
            "enabled": bool(row.get("in_wave_pool")),
            "message": "已加入波段池" if enabled else "已移出波段池",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/monitor/pool")
def get_monitor_pool():
    """调试入口：返回监控池当前状态。"""
    try:
        ensure_monitor_schema()
        rows = execute_query(
            """
            SELECT *
            FROM monitor.stock_pool
            ORDER BY
              CASE WHEN execution_status = 'holding' THEN 0 ELSE 1 END,
              code
            """
        ) or []
        return {"ok": True, "count": len(rows), "items": [_row_to_dict(r) for r in rows]}
    except Exception as e:
        return {"ok": False, "error": str(e), "items": []}


@router.get("/monitor/events")
def get_monitor_events(code: Optional[str] = None, limit: int = 100):
    """调试入口：查看监控池动作日志。"""
    try:
        ensure_monitor_schema()
        params: list[Any] = []
        sql = """
            SELECT e.*, p.code, p.name
            FROM monitor.stock_pool_events e
            JOIN monitor.stock_pool p ON p.id = e.pool_id
        """
        if code:
            sql += " WHERE p.code = %s "
            params.append(str(code).strip().zfill(6))
        sql += " ORDER BY e.created_at DESC LIMIT %s "
        params.append(max(1, min(int(limit or 100), 500)))
        rows = execute_query(sql, tuple(params)) or []
        return {"ok": True, "count": len(rows), "items": [_row_to_dict(r) for r in rows]}
    except Exception as e:
        return {"ok": False, "error": str(e), "items": []}


@router.get("/stock-detail/{code}")
def get_stock_detail(code: str):
    """个股全景分析 — 聚合技术指标、策略信号、AI建议"""
    try:
        ensure_monitor_schema()
        code = str(code).strip().zfill(6)
        if not code.isdigit():
            return {"ok": False, "error": "invalid code"}

        # --- 1. 基础信息 ---
        meta_map = _load_stock_meta_map([code])
        meta = meta_map.get(code) or {}
        name = meta.get("name", code)
        industry = meta.get("industry", "")
        market = meta.get("market", "")

        # --- 2. 实时行情 ---
        rt_map = get_realtime_quote_map([code])
        rt = rt_map.get(code) or {}
        price = _safe_float(rt.get("price"))
        open_p = _safe_float(rt.get("open_price") or rt.get("open"))
        high_p = _safe_float(rt.get("high_price") or rt.get("high"))
        low_p = _safe_float(rt.get("low_price") or rt.get("low"))
        prev_close = _safe_float(rt.get("prev_close") or rt.get("close_price"))
        volume = _safe_float(rt.get("volume"))
        amount = _safe_float(rt.get("amount"))
        turnover = _safe_float(rt.get("turnover_rate"))
        change_pct = _safe_float(rt.get("change_pct"))
        updated_at = rt.get("updated_at")

        # --- 3. K线技术指标 ---
        kline_map = _load_recent_kline_metrics([code])
        km = kline_map.get(code) or {}
        ma5 = _safe_float(km.get("ma5"))
        ma10 = _safe_float(km.get("ma10"))
        ma20 = _safe_float(km.get("ma20"))
        rsi = _safe_float(km.get("rsi"))
        vol_ratio = _safe_float(km.get("volume_ratio"))
        change5d = _safe_float(km.get("change5d"))
        change10d = _safe_float(km.get("change10d"))
        change20d = _safe_float(km.get("change20d"))
        if price is None:
            price = _safe_float(km.get("close"))
        if change_pct is None:
            change_pct = _safe_float(km.get("change_pct"))

        # --- 4. 评分 ---
        macd_label = _calc_macd_label(ma5, ma10)
        total_score = _derive_total_score(change_pct, _safe_float(None), rsi, macd_label, vol_ratio)
        # 尝试从 stock_pool 取偏离度
        deviation = None
        try:
            sp_row = execute_one(
                "SELECT last_price, cost_price, position_qty FROM monitor.stock_pool WHERE code = %s",
                (code,),
            )
            if sp_row:
                sp = _row_to_dict(sp_row)
                if price and _safe_float(km.get("ma20")):
                    deviation = round((price - float(km["ma20"])) / float(km["ma20"]) * 100, 2)
        except Exception:
            pass
        if deviation is not None:
            total_score = _derive_total_score(change_pct, deviation, rsi, macd_label, vol_ratio)

        leader_level = _derive_leader_level(total_score)
        recommendation = _derive_recommendation(total_score)
        risk_signals = _build_risk_signals(
            deviation=deviation, volume_ratio=vol_ratio, rsi=rsi,
            macd_label=macd_label, profit_pct=None, source="",
        )
        sub_scores = {
            "trend": _calc_trend_score(change_pct),
            "deviation": _calc_deviation_score(deviation),
            "rsi": _calc_rsi_score(rsi),
            "macd": _calc_macd_score(macd_label),
            "vol": _calc_vol_score(vol_ratio),
        }

        # --- 5. 策略信号聚合 ---
        strategies_found = []
        try:
            from api.hermes_native.adapters import load_robot_result
            from api.hermes_native.strategies.catalog import ROBOT_STRATEGY_MAP
            for key, info in ROBOT_STRATEGY_MAP.items():
                if not info.get("script_name"):
                    continue  # 跳过纯回测策略
                try:
                    result = load_robot_result(key)
                    stocks = (result.get("data") or {}).get("stocks") or []
                    for s in stocks:
                        sc = str(s.get("code") or s.get("symbol") or "").strip().zfill(6)
                        if sc == code:
                            strategies_found.append({
                                "key": key,
                                "name": result.get("name") or info.get("display_name") or key,
                                "score": _safe_float(s.get("score")),
                                "trade_date": result.get("trade_date") or "",
                                "reason": s.get("industry") or s.get("_raw", {}).get("reason") or "",
                            })
                            break
                except Exception:
                    continue
        except Exception:
            pass

        # --- 6. AI 提供商列表（实际分析由前端懒加载 /api/ops/stock-advice）---
        ai_provider_list = []
        try:
            from api.hermes_native.services.ai_advice import list_providers as _list_ai_providers
            ai_provider_list = [
                {"key": p["key"], "name": p["name"]}
                for p in _list_ai_providers()
            ]
        except Exception:
            pass

        return {
            "ok": True,
            "code": code,
            "name": name,
            "industry": industry,
            "market": market,
            "quote": {
                "price": price, "open": open_p, "high": high_p, "low": low_p,
                "prev_close": prev_close, "change_pct": change_pct,
                "volume": volume, "amount": amount, "turnover": turnover,
                "updated_at": _format_datetime(updated_at) if updated_at else None,
            },
            "technicals": {
                "ma5": ma5, "ma10": ma10, "ma20": ma20,
                "macd": macd_label, "rsi": rsi, "volume_ratio": vol_ratio,
                "deviation": deviation,
                "change5d": change5d, "change10d": change10d, "change20d": change20d,
            },
            "scoring": {
                "total": total_score,
                "recommendation": recommendation,
                "leader_level": leader_level,
                "risk_signals": risk_signals,
                "sub_scores": sub_scores,
            },
            "strategies": strategies_found,
            "ai_providers": ai_provider_list,
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("stock-detail error: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


# ── 共享自选股同步（从 AIROBOT 共享数据层同步到 Hermes 监控池） ──
import urllib.request as _urllib_request


def _airobot_post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    """向 AIROBOT 后端发送 JSON POST 请求，失败时返回空 dict"""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = _urllib_request.Request(
            f"http://127.0.0.1:9000{path}",
            data=data,
            headers={
                "User-Agent": "Hermes/1.0",
                "Content-Type": "application/json",
            },
        )
        with _urllib_request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning("AIROBOT shared API call failed: %s %s", path, e)
        return {}


def _sync_add_to_shared_watchlist(code: str, name: str = ""):
    """将股票同步添加到 AIROBOT 共享自选股（失败不影响主流程）"""
    _airobot_post_json(
        "/api/shared/watchlist/add",
        {
            "codes": [code],
            "note": "Hermes监控池同步",
            "group": "Hermes监控",
        },
    )


def _sync_remove_from_shared_watchlist(code: str):
    """将股票从 AIROBOT 共享自选股中移除（仅移除由 Hermes 监控池同步的分组）"""
    logger = logging.getLogger(__name__)
    try:
        req = _urllib_request.Request(
            "http://127.0.0.1:9000/api/shared/watchlist",
            headers={"User-Agent": "Hermes/1.0"},
        )
        with _urllib_request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logger.warning("读取共享自选股失败: %s", e)
        return

    stocks = data.get("stocks") or []
    target = next((s for s in stocks if s.get("code") == code), None)
    if not target:
        return

    group = target.get("group", "")
    if group not in ("Hermes监控", "Vibe同步"):
        logger.info(
            "共享自选股 code=%s group=%s 不是子系统同步分组，跳过移除", code, group
        )
        return

    _airobot_post_json("/api/shared/watchlist/remove", {"code": code})


def sync_shared_watchlist():
    """从 AIROBOT 共享数据层同步自选股到 Hermes 监控池"""
    logger = logging.getLogger(__name__)
    try:
        req = _urllib_request.Request(
            "http://127.0.0.1:9000/api/shared/watchlist/codes",
            headers={"User-Agent": "Hermes/1.0"},
        )
        with _urllib_request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        codes = data.get("codes", [])
        if not codes:
            return {"ok": True, "synced": 0, "total": 0, "message": "共享自选股为空"}
        synced = 0
        for code in codes:
            code = str(code).strip().zfill(6)
            if not code.isdigit():
                continue
            existing = get_pool_row(code)
            if existing:
                # 确保已在监控池中
                if not existing.get("in_monitor_pool"):
                    upsert_pool_stock(
                        code=code,
                        name=existing.get("name", code),
                        market=existing.get("market", ""),
                        in_monitor_pool=True,
                        tracking_status="watching",
                        latest_source_type="shared_watchlist",
                        latest_source_key="shared_watchlist.sync",
                        is_active=True,
                    )
                    synced += 1
                continue
            name = _get_stock_name(code, {})
            market = "SZ" if code[0] in ("0", "3") else "SH"
            add_monitor_stock(
                code=code,
                name=name or code,
                market=market,
                source_type="shared_watchlist",
                source_key="shared_watchlist.sync",
                source_page="shared_sync",
            )
            synced += 1
        logger.info("sync_shared_watchlist: synced=%d total=%d", synced, len(codes))
        return {"ok": True, "synced": synced, "total": len(codes)}
    except Exception as e:
        logger.warning("sync_shared_watchlist error: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/watchlist/shared-sync")
def trigger_shared_watchlist_sync():
    """手动触发从 AIROBOT 共享数据层同步自选股"""
    return sync_shared_watchlist()


__all__ = ["router"]
