"""US industry-leader research pool built only from completed daily bars.

Admission is evidence based: during the latest 250 completed US market
sessions, a stock must have printed at least one 9% single-day advance or one
16% compounded two-session advance.  Current trend gates define the smaller
core pool; they never rewrite the historical qualification evidence.
"""
from __future__ import annotations

from datetime import date
import json
from math import sqrt
from pathlib import Path
import re
from statistics import median
import threading
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, text

from db.session import get_db_session
from services.indicators import calc_atr, calc_ema, calc_kdj, calc_ma, calc_macd, calc_rsi, calc_supertrend
from us_quant.repository import (
    USInstrument,
    USRealPosition,
    USSectorRotationSnapshot,
    USStockDaily,
)
from us_quant.sector_rotation import score_sector

router = APIRouter(prefix="/api/us-sector-rotation", tags=["us_sector_rotation"])

LOOKBACK_DAYS = 250
WARMUP_DAYS = 20
MIN_HISTORY_BARS = 60
CORE_MAX_DAYS_SINCE_TRIGGER = 120
CORE_MIN_EVENT_COUNT = 2
SINGLE_DAY_THRESHOLD = 9.0
TWO_DAY_THRESHOLD = 16.0
MAX_ABS_DAILY_PCT = 60.0
MIN_DAILY_COVERAGE = 0.90
MIN_SECTOR_COVERAGE = 0.80
MIN_SECTOR_SAMPLE = 3
SNAPSHOT_VERSION = 5

_CACHE = {"trade_date": None, "snapshot": None}
_CACHE_LOCK = threading.Lock()
_US_NAMES_CACHE = None

POOL_RULE = {
    "lookback_trade_days": LOOKBACK_DAYS,
    "single_day_pct_gte": SINGLE_DAY_THRESHOLD,
    "two_day_compound_pct_gte": TWO_DAY_THRESHOLD,
    "maximum_valid_abs_daily_pct": MAX_ABS_DAILY_PCT,
    "minimum_history_bars": MIN_HISTORY_BARS,
    "ignored_initial_trading_bars": WARMUP_DAYS,
    "requires_latest_completed_bar": True,
    "minimum_daily_universe_coverage_pct": MIN_DAILY_COVERAGE * 100,
    "excludes_etf": True,
    "corporate_action_filter": "疑似拆并股日不计强势事件；技术指标按价格跳变连续修正",
    "core_requires_days_since_trigger_lte": CORE_MAX_DAYS_SINCE_TRIGGER,
    "core_requires_distinct_event_dates_gte": CORE_MIN_EVENT_COUNT,
    "core_requires_above_ma60": True,
    "ranking": "35%触发新近度 + 35%事件强度 + 20%当前20日动量 + 10%行业内20日平均成交额分位",
    "sector_rise_formula": "25%全行业20日上涨广度 + 20%全行业20日中位收益 + 15%站上MA20比例 + 10%站上MA60比例 + 15%ETF评分 + 15%ETF相对SPY强度",
}

SECTOR_ETF_MAP = {
    "半导体": ("SMH", "半导体"), "半导体设备": ("SMH", "半导体"), "存储": ("SMH", "半导体"),
    "软件服务": ("XLK", "科技"), "应用软件": ("XLK", "科技"), "IT服务": ("XLK", "科技"),
    "电脑硬件": ("XLK", "科技"), "消费电子": ("XLK", "科技"), "电子元器件": ("XLK", "科技"),
    "互联网内容": ("XLC", "通信"), "娱乐传媒": ("XLC", "通信"), "广告营销": ("XLC", "通信"),
    "电信服务": ("XLC", "通信"), "通信设备": ("XLC", "通信"), "电子游戏": ("XLC", "通信"),
    "汽车制造": ("XLY", "可选消费"), "汽车零部件": ("XLY", "可选消费"), "电商零售": ("XLY", "可选消费"),
    "旅游服务": ("XLY", "可选消费"), "酒店住宿": ("XLY", "可选消费"), "餐饮": ("XLY", "可选消费"),
    "折扣零售": ("XLY", "可选消费"), "服装零售": ("XLY", "可选消费"), "鞋服配饰": ("XLY", "可选消费"),
    "家居建材零售": ("XLY", "可选消费"), "休闲服务": ("XLY", "可选消费"), "教育培训": ("XLY", "可选消费"),
    "银行": ("XLF", "金融"), "资本市场": ("XLF", "金融"), "资产管理": ("XLF", "金融"),
    "金融数据服务": ("XLF", "金融"), "信贷服务": ("XLF", "金融"), "医疗保险": ("XLF", "金融"),
    "专用机械": ("XLI", "工业"), "工程建筑": ("XLI", "工业"), "工程机械": ("XLI", "工业"),
    "建筑产品": ("XLI", "工业"), "电气设备": ("XLI", "工业"), "物流货运": ("XLI", "工业"),
    "铁路运输": ("XLI", "工业"), "航空": ("XLI", "工业"), "航空航天军工": ("XLI", "工业"),
    "租赁服务": ("XLI", "工业"), "综合集团": ("XLI", "工业"), "科学仪器": ("XLI", "工业"),
    "制药": ("XLV", "医疗"), "生物科技": ("XLV", "医疗"), "医疗器械": ("XLV", "医疗"),
    "医疗耗材": ("XLV", "医疗"), "医疗诊断": ("XLV", "医疗"), "医疗护理设施": ("XLV", "医疗"),
    "综合石油": ("XLE", "能源"), "油气勘探开发": ("XLE", "能源"), "油气中游": ("XLE", "能源"),
    "油服": ("XLE", "能源"), "炼油": ("XLE", "能源"),
    "工业金属": ("XLB", "材料"), "钢铁": ("XLB", "材料"), "铀矿": ("XLB", "材料"),
    "铜业": ("XLB", "材料"), "铝业": ("XLB", "材料"), "黄金矿业": ("XLB", "材料"),
    "包装食品": ("XLP", "必需消费"), "日用消费品": ("XLP", "必需消费"), "烟草": ("XLP", "必需消费"),
    "糖果零食": ("XLP", "必需消费"), "超市零售": ("XLP", "必需消费"), "非酒精饮料": ("XLP", "必需消费"),
    "电力公用事业": ("XLU", "公用事业"), "独立发电": ("XLU", "公用事业"), "综合公用事业": ("XLU", "公用事业"),
    "专项REIT": ("XLRE", "房地产"), "商业REIT": ("XLRE", "房地产"), "工业REIT": ("XLRE", "房地产"),
}


def _last(values):
    return values[-1] if values and values[-1] is not None else None


def _pct(last, old):
    return (last / old - 1) * 100 if last and old else None


def _name_map():
    global _US_NAMES_CACHE
    if _US_NAMES_CACHE is not None:
        return _US_NAMES_CACHE
    source = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "usStockNames.js"
    try:
        content = source.read_text(encoding="utf-8")
    except OSError:
        _US_NAMES_CACHE = {}
        return _US_NAMES_CACHE
    _US_NAMES_CACHE = {
        key: value for key, value in re.findall(r"\b([A-Z][A-Z0-9.]*)\s*:\s*'([^']*)'", content)
    }
    return _US_NAMES_CACHE


def _latest_completed_trade_date(db):
    active_count = db.query(func.count(USInstrument.id)).filter(
        USInstrument.is_active.is_(True),
        USInstrument.is_etf.is_not(True),
        USInstrument.sector.is_not(None),
        USInstrument.sector != "",
    ).scalar() or 0
    if not active_count:
        return None
    rows = db.query(
        USStockDaily.trade_date,
        func.count(func.distinct(USStockDaily.symbol)),
    ).join(USInstrument, USInstrument.symbol == USStockDaily.symbol).filter(
        USInstrument.is_active.is_(True),
        USInstrument.is_etf.is_not(True),
        USInstrument.sector.is_not(None),
        USInstrument.sector != "",
        func.coalesce(USStockDaily.source, "") != "synthetic",
        USStockDaily.close > 0,
        USStockDaily.volume > 0,
    ).group_by(USStockDaily.trade_date).order_by(USStockDaily.trade_date.desc()).limit(30).all()
    required = max(1, int(active_count * MIN_DAILY_COVERAGE))
    return next((trade_day for trade_day, count in rows if count >= required), None)


def _event_rows(db, target):
    sql = text("""
        WITH active AS (
            SELECT symbol
            FROM us_instruments
            WHERE is_active IS TRUE
              AND COALESCE(is_etf, FALSE) IS FALSE
              AND COALESCE(sector, '') <> ''
        ),
        selected_dates AS (
            SELECT trade_date
            FROM us_stock_daily
            WHERE trade_date <= :target
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT :date_limit
        ),
        date_index AS (
            SELECT trade_date, ROW_NUMBER() OVER (ORDER BY trade_date) AS market_seq
            FROM selected_dates
        ),
        bars AS (
            SELECT d.symbol, d.trade_date, x.market_seq, d.open, d.close, d.change_pct,
                   ROW_NUMBER() OVER (PARTITION BY d.symbol ORDER BY d.trade_date) AS stock_seq,
                   LAG(d.close) OVER (PARTITION BY d.symbol ORDER BY d.trade_date) AS prev_close,
                   LAG(d.change_pct) OVER (PARTITION BY d.symbol ORDER BY d.trade_date) AS prev_pct,
                   LAG(x.market_seq) OVER (PARTITION BY d.symbol ORDER BY d.trade_date) AS prev_market_seq
            FROM us_stock_daily d
            JOIN active a ON a.symbol = d.symbol
            JOIN date_index x ON x.trade_date = d.trade_date
            WHERE d.close > 0 AND d.volume > 0
              AND COALESCE(d.source, '') <> 'synthetic'
              AND d.change_pct IS NOT NULL
              AND ABS(d.change_pct) <= :max_abs_daily_pct
        ),
        bounds AS (
            SELECT MAX(market_seq) AS max_seq,
                   GREATEST(MAX(market_seq) - :lookback_days + 1, 1) AS min_seq
            FROM date_index
        ),
        cleaned AS (
            SELECT b.*, bounds.max_seq, bounds.min_seq,
                   CASE
                     WHEN b.prev_close > 0 AND b.open > 0
                       AND (b.open / b.prev_close <= 0.55 OR b.open / b.prev_close >= 1.80)
                       AND ABS(b.close / b.open - 1) <= 0.25
                     THEN TRUE ELSE FALSE
                   END AS corporate_action_jump
            FROM bars b CROSS JOIN bounds
        ),
        adjusted AS (
            SELECT c.*,
                   LAG(c.corporate_action_jump) OVER (PARTITION BY c.symbol ORDER BY c.trade_date) AS prev_corporate_action_jump
            FROM cleaned c
        ),
        measured AS (
            SELECT a.*,
                   ((1 + a.prev_pct / 100.0) * (1 + a.change_pct / 100.0) - 1) * 100.0 AS two_day_pct
            FROM adjusted a
        )
        SELECT symbol, trade_date, market_seq, max_seq, change_pct, two_day_pct,
               (change_pct >= :single_threshold) AS single_hit,
               (market_seq - prev_market_seq = 1 AND two_day_pct >= :two_day_threshold) AS two_day_hit
        FROM measured
        WHERE market_seq >= min_seq
          AND stock_seq > :warmup_days
          AND corporate_action_jump IS FALSE
          AND (change_pct >= :single_threshold OR
               (market_seq - prev_market_seq = 1
                AND COALESCE(prev_corporate_action_jump, FALSE) IS FALSE
                AND two_day_pct >= :two_day_threshold))
        ORDER BY symbol, trade_date
    """)
    return db.execute(sql, {
        "target": target,
        "date_limit": LOOKBACK_DAYS + WARMUP_DAYS,
        "lookback_days": LOOKBACK_DAYS,
        "warmup_days": WARMUP_DAYS,
        "single_threshold": SINGLE_DAY_THRESHOLD,
        "two_day_threshold": TWO_DAY_THRESHOLD,
        "max_abs_daily_pct": MAX_ABS_DAILY_PCT,
    }).mappings().all()


def _summarize_events(rows):
    result = {}
    for row in rows:
        item = result.setdefault(row["symbol"], {
            "single_day_count": 0, "two_day_count": 0,
            "max_single_day_pct": None, "max_two_day_pct": None,
            "latest_trigger_date": None, "latest_trigger_seq": None,
            "target_seq": int(row["max_seq"]), "latest_trigger_types": [],
            "trigger_dates": set(),
        })
        item["trigger_dates"].add(row["trade_date"])
        if row["single_hit"]:
            item["single_day_count"] += 1
            value = float(row["change_pct"])
            item["max_single_day_pct"] = value if item["max_single_day_pct"] is None else max(item["max_single_day_pct"], value)
        if row["two_day_hit"]:
            item["two_day_count"] += 1
            value = float(row["two_day_pct"])
            item["max_two_day_pct"] = value if item["max_two_day_pct"] is None else max(item["max_two_day_pct"], value)
        seq = int(row["market_seq"])
        if item["latest_trigger_seq"] is None or seq >= item["latest_trigger_seq"]:
            item["latest_trigger_seq"] = seq
            item["latest_trigger_date"] = row["trade_date"]
            item["latest_trigger_types"] = (["single_day"] if row["single_hit"] else []) + (["two_day"] if row["two_day_hit"] else [])
    for item in result.values():
        item["days_since_trigger"] = item["target_seq"] - item["latest_trigger_seq"]
        item["trigger_type"] = "both" if item["single_day_count"] and item["two_day_count"] else "single_day" if item["single_day_count"] else "two_day"
        item["strength_ratio"] = max(
            (item["max_single_day_pct"] or 0) / SINGLE_DAY_THRESHOLD,
            (item["max_two_day_pct"] or 0) / TWO_DAY_THRESHOLD,
        )
        item["event_count"] = len(item["trigger_dates"])
        item["recent_trigger_dates"] = sorted(item["trigger_dates"], reverse=True)[:5]
        del item["trigger_dates"], item["latest_trigger_seq"], item["target_seq"]
    return result


def _metrics(rows):
    rows = sorted(rows, key=lambda row: row.trade_date)
    raw_closes = [float(row.close) for row in rows]
    raw_opens = [float(row.open or row.close) for row in rows]
    raw_highs = [float(row.high or row.close) for row in rows]
    raw_lows = [float(row.low or row.close) for row in rows]
    factors = [1.0] * len(rows)
    adjustment_count = 0
    cumulative = 1.0
    for index in range(len(rows) - 1, 0, -1):
        open_ratio = raw_opens[index] / raw_closes[index - 1] if raw_closes[index - 1] > 0 else 1.0
        intraday_move = raw_closes[index] / raw_opens[index] - 1 if raw_opens[index] > 0 else 0.0
        if (open_ratio <= 0.55 or open_ratio >= 1.80) and abs(intraday_move) <= 0.25:
            cumulative *= open_ratio
            adjustment_count += 1
        factors[index - 1] = cumulative
    closes = [value * factors[index] for index, value in enumerate(raw_closes)]
    highs = [value * factors[index] for index, value in enumerate(raw_highs)]
    lows = [value * factors[index] for index, value in enumerate(raw_lows)]
    volumes = [float(row.volume or 0) for row in rows]
    amounts = [float(row.amount) if row.amount is not None else float(row.close or 0) * float(row.volume or 0) for row in rows]
    if len(closes) < MIN_HISTORY_BARS:
        return None
    ema10_values, ema20_values = calc_ema(closes, 10), calc_ema(closes, 20)
    ma5_values, ma20_values, ma50_values, ma60_values = (
        calc_ma(closes, 5), calc_ma(closes, 20), calc_ma(closes, 50), calc_ma(closes, 60)
    )
    ma200_values = calc_ma(closes, 200) if len(closes) >= 200 else []
    rsi_values = calc_rsi(closes, 14)
    dif_values, dea_values, macd_values = calc_macd(closes)
    k_values, d_values, j_values = calc_kdj(highs, lows, closes)
    supports, resistances, _, _ = calc_supertrend(highs, lows, closes, period=10, multiplier=1.0)
    atr_values = calc_atr(highs, lows, closes, period=14)
    last_price = closes[-1]
    ma5, ma20, ma60 = _last(ma5_values), _last(ma20_values), _last(ma60_values)
    returns = [_pct(closes[i], closes[i - 1]) for i in range(1, len(closes))]
    mean_return = sum(returns) / len(returns)
    volatility = sqrt(sum((value - mean_return) ** 2 for value in returns) / len(returns))
    volume_baseline = volumes[-6:-1]
    avg_volume = sum(volume_baseline) / max(1, len(volume_baseline))
    ma20_prior = ma20_values[-6] if len(ma20_values) >= 6 else None
    high_low_window = closes[-252:]
    high_52w, low_52w = max(high_low_window), min(high_low_window)
    recent_highs, recent_lows = highs[-20:], lows[-20:]

    def period_return(days):
        return _pct(last_price, closes[-1 - days]) if len(closes) > days else None

    return {
        "day_change_pct": float(rows[-1].change_pct) if rows[-1].change_pct is not None else period_return(1),
        "ret_5d": period_return(5), "ret_20d": period_return(20), "ret_60d": period_return(60),
        "ema10": _last(ema10_values), "ema20": _last(ema20_values),
        "ma5": ma5, "ma20": ma20, "ma50": _last(ma50_values),
        "ma60": ma60, "ma200": _last(ma200_values),
        "ma20_slope": _pct(ma20, ma20_prior),
        "above_ma20": last_price >= ma20 if ma20 is not None else None,
        "above_ma60": last_price >= ma60 if ma60 is not None else None,
        "volatility": volatility, "drawdown": _pct(last_price, high_52w),
        "high_52w": high_52w, "low_52w": low_52w,
        "pct_from_high": _pct(last_price, high_52w), "pct_from_low": _pct(last_price, low_52w),
        "amount_20d": sum(amounts[-20:]) / min(20, len(amounts)),
        "volume_ratio": volumes[-1] / avg_volume if avg_volume > 0 else None,
        "last_price": last_price, "rsi": _last(rsi_values),
        "dif": _last(dif_values), "dea": _last(dea_values), "macd": _last(macd_values),
        "kdj_k": _last(k_values), "kdj_d": _last(d_values), "kdj_j": _last(j_values),
        "support": min(recent_lows), "resistance": max(recent_highs),
        "supertrend_support": _last(supports), "supertrend_resistance": _last(resistances),
        "atr": _last(atr_values),
        "amplitude": _pct(highs[-1], lows[-1]),
        "turnover": float(rows[-1].turnover) if rows[-1].turnover is not None else None,
        "corporate_action_adjustments": adjustment_count,
    }


def _rank_stocks(stocks):
    ordered = sorted(stocks, key=lambda stock: stock["metrics"].get("amount_20d") or 0)
    denominator = max(1, len(ordered) - 1)
    liquidity = {stock["symbol"]: index / denominator * 100 for index, stock in enumerate(ordered)}
    for stock in stocks:
        evidence, metrics = stock["qualification"], stock["metrics"]
        recency = max(0.0, 100 * (1 - evidence["days_since_trigger"] / max(1, LOOKBACK_DAYS - 1)))
        strength = min(100.0, evidence["strength_ratio"] / 2 * 100)
        momentum = max(0.0, min(100.0, ((metrics.get("ret_20d") or -20) + 20) / 60 * 100))
        components = {
            "trigger_recency": round(recency, 2), "event_strength": round(strength, 2),
            "momentum_20d": round(momentum, 2), "liquidity": round(liquidity[stock["symbol"]], 2),
        }
        stock["score_components"] = components
        stock["score"] = round(recency * .35 + strength * .35 + momentum * .20 + liquidity[stock["symbol"]] * .10, 2)
        if metrics.get("above_ma20") is False:
            stock["action"] = "等待修复"
        elif (metrics.get("rsi") or 0) >= 75:
            stock["action"] = "强势·谨慎追高"
        elif metrics.get("ma5") and metrics.get("ma20") and metrics.get("ma60") and metrics["ma5"] >= metrics["ma20"] >= metrics["ma60"]:
            stock["action"] = "强势跟踪"
        else:
            stock["action"] = "观察"
    stocks.sort(key=lambda stock: (-stock["score"], stock["qualification"]["days_since_trigger"], stock["symbol"]))
    for rank, stock in enumerate(stocks, 1):
        stock["rank"] = rank


def _is_core_stock(stock):
    evidence, metrics = stock["qualification"], stock["metrics"]
    reasons = []
    if evidence["days_since_trigger"] > CORE_MAX_DAYS_SINCE_TRIGGER:
        reasons.append("strong_event_too_old")
    if evidence["event_count"] < CORE_MIN_EVENT_COUNT:
        reasons.append("insufficient_repeat_events")
    if metrics.get("above_ma60") is not True:
        reasons.append("below_ma60")
    stock["core_gate"] = {"valid": not reasons, "reasons": reasons}
    return not reasons


def _average_metrics(stocks):
    result = {}
    for key in ("ret_5d", "ret_20d", "ret_60d", "volatility", "drawdown"):
        values = [stock["metrics"].get(key) for stock in stocks if stock["metrics"].get(key) is not None]
        result[key] = round(sum(values) / len(values), 2) if values else None
    result["breadth"] = round(sum((stock["metrics"].get("ret_20d") or 0) > 0 for stock in stocks) / len(stocks) * 100, 2) if stocks else 0
    result["score"] = round(sum(stock["score"] for stock in stocks) / len(stocks), 2) if stocks else None
    result["is_strong"] = bool(result["ret_20d"] and result["ret_20d"] > 0 and result["breadth"] >= 50)
    return result


def _clamp(value, lower=0.0, upper=100.0):
    return max(lower, min(upper, value))


def _sector_universe_metrics(stocks, universe_count, etf):
    """计算研究宇宙内全部行业成分股的上升度，避免只看少数龙头。"""
    valid_count = len(stocks)
    coverage = valid_count / universe_count * 100 if universe_count else 0.0

    def values(key):
        return [stock["metrics"][key] for stock in stocks if stock["metrics"].get(key) is not None]

    ret_5d_values, ret_20d_values, ret_60d_values = values("ret_5d"), values("ret_20d"), values("ret_60d")
    median_ret_5d = median(ret_5d_values) if ret_5d_values else None
    median_ret_20d = median(ret_20d_values) if ret_20d_values else None
    median_ret_60d = median(ret_60d_values) if ret_60d_values else None
    breadth = sum(value > 0 for value in ret_20d_values) / len(ret_20d_values) * 100 if ret_20d_values else 0.0
    above_ma20 = sum(stock["metrics"].get("above_ma20") is True for stock in stocks) / valid_count * 100 if valid_count else 0.0
    above_ma60 = sum(stock["metrics"].get("above_ma60") is True for stock in stocks) / valid_count * 100 if valid_count else 0.0

    etf_score = etf.get("score") if etf else None
    etf_ret_20d = etf.get("ret_20d") if etf else None
    etf_relative_20d = etf.get("rel_strength_20d") if etf else None
    etf_ma_trend = etf.get("ma_trend") if etf else None
    etf_current = bool(etf and etf.get("is_current"))
    if not etf_current or None in (etf_score, etf_ret_20d, etf_relative_20d, etf_ma_trend):
        etf_status = "MISSING"
    elif etf_score < 40 or etf_ret_20d <= -5 or etf_relative_20d <= -5 or etf_ma_trend <= 2:
        etf_status = "WEAK"
    elif etf_score >= 55 and etf_ret_20d > 0 and etf_relative_20d >= 0 and etf_ma_trend >= 6:
        etf_status = "CONFIRM"
    else:
        etf_status = "NEUTRAL"

    median_component_value = -10 if median_ret_20d is None else median_ret_20d
    relative_component_value = -10 if etf_relative_20d is None else etf_relative_20d
    components = {
        "breadth_20d": round(breadth, 2),
        "median_return_20d": round(_clamp((median_component_value + 10) / 30 * 100), 2),
        "above_ma20": round(above_ma20, 2),
        "above_ma60": round(above_ma60, 2),
        "etf_score": round(_clamp(etf_score or 0), 2),
        "etf_relative_strength_20d": round(_clamp((relative_component_value + 10) / 20 * 100), 2),
    }
    rise_score = round(
        components["breadth_20d"] * .25
        + components["median_return_20d"] * .20
        + components["above_ma20"] * .15
        + components["above_ma60"] * .10
        + components["etf_score"] * .15
        + components["etf_relative_strength_20d"] * .15,
        2,
    )
    gate_reasons = []
    if universe_count < MIN_SECTOR_SAMPLE or valid_count < MIN_SECTOR_SAMPLE:
        gate_reasons.append("sample_too_small")
    if coverage < MIN_SECTOR_COVERAGE * 100:
        gate_reasons.append("data_coverage_low")
    if rise_score < 60:
        gate_reasons.append("rise_score_below_60")
    if median_ret_20d is None or median_ret_20d <= 0:
        gate_reasons.append("median_return_not_positive")
    if breadth < 50:
        gate_reasons.append("breadth_below_50")
    if above_ma20 < 50:
        gate_reasons.append("ma20_breadth_below_50")
    if etf_status == "MISSING":
        gate_reasons.append("etf_data_missing")
    elif etf_status == "WEAK":
        gate_reasons.append("etf_weak_veto")

    if "sample_too_small" in gate_reasons:
        status = "SAMPLE_TOO_SMALL"
    elif "data_coverage_low" in gate_reasons:
        status = "DATA_INSUFFICIENT"
    elif "etf_data_missing" in gate_reasons:
        status = "ETF_MISSING"
    elif gate_reasons:
        status = "CLOSED"
    else:
        status = "OPEN"
    return {
        "rise_score": rise_score,
        "ret_5d": round(median_ret_5d, 2) if median_ret_5d is not None else None,
        "ret_20d": round(median_ret_20d, 2) if median_ret_20d is not None else None,
        "ret_60d": round(median_ret_60d, 2) if median_ret_60d is not None else None,
        "breadth": round(breadth, 2),
        "above_ma20_pct": round(above_ma20, 2),
        "above_ma60_pct": round(above_ma60, 2),
        "coverage_pct": round(coverage, 2),
        "valid_stock_count": valid_count,
        "universe_stock_count": universe_count,
        "score_components": components,
        "etf_status": etf_status,
        "status": status,
        "is_rising": status == "OPEN",
        "gate_reasons": gate_reasons,
    }


def _etf_reference(sector_name, scores):
    symbol, label = SECTOR_ETF_MAP.get(sector_name, (None, None))
    if not symbol:
        return None, "暂无可靠行业ETF映射，当前以强势资格股等权聚合作为参考"
    score = scores.get(symbol)
    if not score:
        return {"symbol": symbol, "name": label}, f"行业映射：{label}；ETF评分暂缺"
    return {"symbol": symbol, "name": label, **score}, f"细分行业映射至 {symbol} {label} ETF"


def _etf_scores_for_date(db, target):
    """从同一决策日的本地日线重算ETF，拒绝只有落库日期、没有行情日期的快照。"""
    symbols = sorted({symbol for symbol, _label in SECTOR_ETF_MAP.values()} | {"SPY"})
    rows = db.query(USStockDaily).filter(
        USStockDaily.symbol.in_(symbols),
        USStockDaily.trade_date <= target,
        USStockDaily.close > 0,
        func.coalesce(USStockDaily.source, "") != "synthetic",
    ).order_by(USStockDaily.symbol, USStockDaily.trade_date.desc()).all()
    histories = {}
    for row in rows:
        history = histories.setdefault(row.symbol, [])
        if len(history) < 90:
            history.append(row)
    for history in histories.values():
        history.sort(key=lambda row: row.trade_date)

    spy_history = histories.get("SPY", [])
    if not spy_history or spy_history[-1].trade_date != target or len(spy_history) < 61:
        return {}
    spy_closes = [float(row.close) for row in spy_history]
    scores = {}
    for symbol, label in sorted(set(SECTOR_ETF_MAP.values())):
        history = histories.get(symbol, [])
        if not history or history[-1].trade_date != target or len(history) < 61:
            continue
        closes = [float(row.close) for row in history]
        volumes = [float(row.volume or 0) for row in history]
        ma20 = sum(closes[-20:]) / 20
        ma50 = sum(closes[-50:]) / 50
        scored = score_sector(
            etf_symbol=symbol,
            etf_name=label,
            industry=label,
            closes_5d=closes[-6:],
            closes_20d=closes[-21:],
            closes_60d=closes[-61:],
            spy_closes_20d=spy_closes[-21:],
            spy_closes_60d=spy_closes[-61:],
            volumes_20d=volumes[-20:],
            avg_volume_20d=sum(volumes[-60:]) / min(60, len(volumes)),
            ma20=ma20,
            ma50=ma50,
            current_price=closes[-1],
        )
        scores[symbol] = {
            "industry": label,
            "score": float(scored.total_score),
            "ret_5d": float(scored.ret_5d),
            "ret_20d": float(scored.ret_20d),
            "ret_60d": float(scored.ret_60d),
            "rel_strength_20d": float(scored.rel_strength_20d),
            "rel_strength_60d": float(scored.rel_strength_60d),
            "ma_trend": float(scored.ma_trend),
            "volume_activity": float(scored.volume_activity),
            "grade": scored.grade,
            "as_of": target,
            "is_current": True,
        }
    ordered = sorted(scores.items(), key=lambda item: (-item[1]["score"], item[0]))
    for rank, (_symbol, score) in enumerate(ordered, 1):
        score["rank"] = rank
    return scores


def _build_snapshot(db, target):
    evidence = _summarize_events(_event_rows(db, target))
    instruments = db.query(USInstrument).filter(
        USInstrument.is_active.is_(True), USInstrument.is_etf.is_not(True),
        USInstrument.sector.is_not(None), USInstrument.sector != "",
    ).all()
    metadata = {item.symbol: item for item in instruments}
    universe_counts = {}
    for item in instruments:
        universe_counts[item.sector] = universe_counts.get(item.sector, 0) + 1

    all_symbols = list(metadata)
    history_rows = db.query(USStockDaily).filter(
        USStockDaily.symbol.in_(all_symbols), USStockDaily.trade_date <= target,
        USStockDaily.close > 0,
        func.coalesce(USStockDaily.source, "") != "synthetic",
    ).order_by(USStockDaily.symbol, USStockDaily.trade_date.desc()).all()
    histories = {}
    for row in history_rows:
        rows = histories.setdefault(row.symbol, [])
        if len(rows) < 260:
            rows.append(row)

    position_rows = db.query(USRealPosition).filter(USRealPosition.status == "ACTIVE").all()
    positions = {row.symbol: {
        "quantity": float(row.quantity) if row.quantity is not None else None,
        "cost_price": float(row.cost_price) if row.cost_price is not None else None,
        "last_price": float(row.last_price) if row.last_price is not None else None,
        "market_value": float(row.market_value) if row.market_value is not None else None,
        "hold_profit": float(row.hold_profit) if row.hold_profit is not None else None,
        "hold_profit_pct": float(row.hold_profit_pct) if row.hold_profit_pct is not None else None,
        "today_profit": float(row.today_profit) if row.today_profit is not None else None,
        "synced_at": row.synced_at,
    } for row in position_rows}

    position_updated_at = None
    for row in position_rows:
        value = getattr(row, "synced_at", None)
        if value is not None and (position_updated_at is None or value > position_updated_at):
            position_updated_at = value

    # ETF 快照必须与行业决策日一致；缺失时明确阻断，而不是偷用旧日或未来日数据。
    etf_scores = _etf_scores_for_date(db, target)
    score_date = target if etf_scores else None
    names = _name_map()
    universe_by_sector = {}
    qualified_by_sector = {}
    for symbol in all_symbols:
        instrument, history = metadata.get(symbol), histories.get(symbol, [])
        if not instrument or not history:
            continue
        history.sort(key=lambda row: row.trade_date)
        if history[-1].trade_date != target or len(history) < MIN_HISTORY_BARS:
            continue
        metrics = _metrics(history)
        if not metrics:
            continue
        stock = {
            "symbol": symbol, "name": names.get(symbol) or instrument.name or symbol,
            "sector": instrument.sector, "industry": instrument.industry,
            "exchange": instrument.exchange, "metrics": metrics,
            "qualification": evidence.get(symbol), "position": positions.get(symbol),
            "sector_context": {},
        }
        universe_by_sector.setdefault(instrument.sector, []).append(stock)
        if symbol in evidence:
            qualified_by_sector.setdefault(instrument.sector, []).append(stock)

    sectors, stocks_by_sector = [], {}
    candidate_stocks_by_sector = {}
    for sector_name in sorted(universe_counts):
        universe_stocks = universe_by_sector.get(sector_name, [])
        qualified = qualified_by_sector.get(sector_name, [])
        _rank_stocks(qualified)
        core = [stock for stock in qualified if _is_core_stock(stock)]
        stocks_by_sector[sector_name] = core
        candidate_stocks_by_sector[sector_name] = sorted(
            qualified,
            key=lambda stock: (-stock["score"], stock["qualification"]["days_since_trigger"], stock["symbol"]),
        )[:10]
        etf, note = _etf_reference(sector_name, etf_scores)
        if etf:
            etf["is_current"] = str(etf.get("as_of")) == str(target)
        universe_metrics = _sector_universe_metrics(
            universe_stocks,
            universe_counts.get(sector_name, len(universe_stocks)),
            etf,
        )
        leader_metrics = _average_metrics(core)
        sectors.append({
            "sector": sector_name, "stock_count": len(core),
            "qualified_stock_count": len(qualified), "universe_stock_count": universe_counts.get(sector_name, len(core)),
            "metrics": universe_metrics,
            "leader_metrics": leader_metrics,
            "leader_strength": leader_metrics.get("score"),
            "etf": etf, "etf_note": note,
        })
    sectors.sort(key=lambda item: (not item["metrics"].get("is_rising"), -(item["metrics"].get("rise_score") or -999), item["sector"]))
    for rank, item in enumerate(sectors, 1):
        item["rank"] = rank
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "trade_date": target, "sectors": sectors, "stocks_by_sector": stocks_by_sector,
        "candidate_stocks_by_sector": candidate_stocks_by_sector,
        "qualification_by_sector": qualified_by_sector, "pool_rule": POOL_RULE,
        "core_stock_count": sum(len(rows) for rows in stocks_by_sector.values()),
        "qualified_stock_count": sum(len(rows) for rows in qualified_by_sector.values()),
        "qualification_library_count": sum(len(rows) for rows in qualified_by_sector.values()),
        "data_mode": "completed_daily_cached",
        "data_as_of": {"daily_kline": target, "sector_etf": score_date, "positions": position_updated_at},
    }


def _serialize_snapshot(snapshot):
    return json.dumps(jsonable_encoder(snapshot), ensure_ascii=False, separators=(",", ":"))


def _persist_snapshot(db, snapshot):
    target = snapshot.get("trade_date")
    if not target:
        return
    payload = _serialize_snapshot(snapshot)
    row = db.query(USSectorRotationSnapshot).filter(USSectorRotationSnapshot.trade_date == target).first()
    if row:
        row.snapshot_json = payload
    else:
        db.add(USSectorRotationSnapshot(trade_date=target, snapshot_json=payload))
    db.commit()


def _load_persisted_snapshot(db, target):
    row = db.query(USSectorRotationSnapshot).filter(USSectorRotationSnapshot.trade_date == target).first()
    if not row:
        return None
    try:
        snapshot = json.loads(row.snapshot_json)
    except (TypeError, json.JSONDecodeError):
        return None
    return snapshot if snapshot.get("trade_date") == target.isoformat() and snapshot.get("snapshot_version") == SNAPSHOT_VERSION else None


def _snapshot_for_date(db, target, build_if_missing=False):
    snapshot = _load_persisted_snapshot(db, target)
    if snapshot is not None:
        return snapshot
    if not build_if_missing:
        return None
    snapshot = _build_snapshot(db, target)
    _persist_snapshot(db, snapshot)
    return snapshot


def _response(snapshot, requested_sector):
    sectors = snapshot.get("sectors", [])
    selected = next((row["sector"] for row in sectors if row["sector"] == requested_sector), sectors[0]["sector"] if sectors else None)
    stocks = snapshot.get("stocks_by_sector", {}).get(selected, []) if selected else []
    qualified = snapshot.get("qualification_by_sector", {}).get(selected, []) if selected else []
    top_candidates = snapshot.get("candidate_stocks_by_sector", {}).get(selected, []) if selected else []
    candidates = [stock for stock in qualified if stock.get("core_gate", {}).get("valid") is not True]
    return jsonable_encoder({
        "source": "database", "status": "READY",
        "trade_date": snapshot.get("trade_date"), "sectors": sectors, "selected": selected,
        "stocks": stocks, "candidate_stocks": candidates, "top_candidates": top_candidates, "stock_count": len(stocks),
        "candidate_count": len(candidates), "qualified_stock_count": snapshot.get("qualified_stock_count", 0),
        "qualification_library_count": snapshot.get("qualification_library_count", 0),
        "pool_rule": snapshot.get("pool_rule", POOL_RULE), "data_mode": snapshot.get("data_mode"),
        "data_as_of": snapshot.get("data_as_of", {}),
    })


def _market_opportunity_response(snapshot):
    """Flatten cached Top10 candidates from sectors whose opportunity gate is open."""
    candidates_by_sector = snapshot.get("candidate_stocks_by_sector", {})
    sectors = []
    candidates = []
    for row in sorted(snapshot.get("sectors", []), key=lambda item: (item.get("rank") or 9999, item.get("sector") or "")):
        metrics = row.get("metrics") or {}
        if metrics.get("status") != "OPEN":
            continue
        context = {
            "sector": row.get("sector"),
            "rank": row.get("rank"),
            "rise_score": metrics.get("rise_score"),
            "ret_5d": metrics.get("ret_5d"),
            "ret_20d": metrics.get("ret_20d"),
            "ret_60d": metrics.get("ret_60d"),
            "breadth": metrics.get("breadth"),
            "status": metrics.get("status"),
            "gate_reasons": metrics.get("gate_reasons", []),
            "etf_status": metrics.get("etf_status"),
            "etf": row.get("etf"),
        }
        sectors.append(context)
        for stock in candidates_by_sector.get(row.get("sector"), [])[:10]:
            candidates.append({**stock, "sector_context": context})
    return jsonable_encoder({
        "source": "database", "status": "READY" if snapshot else "MISSING",
        "trade_date": snapshot.get("trade_date"),
        "sectors": sectors,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "sector_count": len(sectors),
        "pool_rule": snapshot.get("pool_rule", POOL_RULE),
        "data_mode": snapshot.get("data_mode"),
        "data_as_of": snapshot.get("data_as_of", {}),
    })


def get_sector_context_by_name(sector_names=None, include_all=False):
    """Return cached rotation context for watchlist sectors without rescanning bars."""
    requested = {str(name).strip() for name in sector_names or [] if str(name).strip()}
    if not requested and not include_all:
        return {"trade_date": None, "sectors": {}}
    with get_db_session() as db:
        target = _latest_completed_trade_date(db)
        if not target:
            return {"trade_date": None, "sectors": {}}
        with _CACHE_LOCK:
            if _CACHE["trade_date"] == target and _CACHE["snapshot"] is not None:
                snapshot = _CACHE["snapshot"]
            else:
                snapshot = _snapshot_for_date(db, target)
                if snapshot is None:
                    return {
                        "trade_date": target.isoformat(), "sectors": {},
                        "source": "database", "status": "MISSING",
                    }
                _CACHE["trade_date"], _CACHE["snapshot"] = target, snapshot

    result = {}
    for row in snapshot.get("sectors", []):
        name = row.get("sector")
        if not include_all and name not in requested:
            continue
        metrics = row.get("metrics") or {}
        rising = metrics.get("status") == "OPEN"
        result[name] = {
            "sector": name,
            "rank": row.get("rank"),
            "rise_score": metrics.get("rise_score"),
            "leader_strength": row.get("leader_strength"),
            "ret_5d": metrics.get("ret_5d"),
            "ret_20d": metrics.get("ret_20d"),
            "ret_60d": metrics.get("ret_60d"),
            "breadth": metrics.get("breadth"),
            "above_ma20_pct": metrics.get("above_ma20_pct"),
            "above_ma60_pct": metrics.get("above_ma60_pct"),
            "coverage_pct": metrics.get("coverage_pct"),
            "valid_stock_count": metrics.get("valid_stock_count"),
            "score_components": metrics.get("score_components", {}),
            "status": metrics.get("status"),
            "gate_reasons": metrics.get("gate_reasons", []),
            "etf_status": metrics.get("etf_status"),
            "is_rising": rising,
            "opportunity_gate": metrics.get("status", "DATA_INSUFFICIENT"),
            "core_stock_count": row.get("stock_count", 0),
            "qualified_stock_count": row.get("qualified_stock_count", 0),
            "universe_stock_count": row.get("universe_stock_count", 0),
            "etf": row.get("etf"),
        }
    return {"trade_date": snapshot.get("trade_date"), "sectors": result,
            "source": "database", "status": "READY"}


def preheat_cache():
    with get_db_session() as db:
        target = _latest_completed_trade_date(db)
        if not target:
            return {"trade_date": None, "core_stock_count": 0}
        with _CACHE_LOCK:
            if _CACHE["trade_date"] != target or _CACHE["snapshot"] is None:
                _CACHE["snapshot"] = _snapshot_for_date(db, target, build_if_missing=True)
                _CACHE["trade_date"] = target
            snapshot = _CACHE["snapshot"]
        return {"trade_date": target, "core_stock_count": snapshot.get("core_stock_count", 0), "qualification_library_count": snapshot.get("qualification_library_count", 0)}


def invalidate_cache(trade_date=None, persisted=False):
    with _CACHE_LOCK:
        _CACHE["trade_date"], _CACHE["snapshot"] = None, None
    if persisted:
        with get_db_session() as db:
            query = db.query(USSectorRotationSnapshot)
            if trade_date is not None:
                query = query.filter(USSectorRotationSnapshot.trade_date == trade_date)
            query.delete(synchronize_session=False)
            db.commit()


@router.get("")
def get_us_sector_rotation(sector: Optional[str] = Query(None), trade_date: Optional[date] = Query(None)):
    with get_db_session() as db:
        target = trade_date or _latest_completed_trade_date(db)
        if not target:
            return {
                "source": "database", "status": "MISSING",
                "trade_date": None, "sectors": [], "selected": None,
                "stocks": [], "pool_rule": POOL_RULE,
                "message": "数据库暂无已完成交易日的美股行业轮动数据",
            }
        with _CACHE_LOCK:
            if _CACHE["trade_date"] == target and _CACHE["snapshot"] is not None:
                snapshot = _CACHE["snapshot"]
            else:
                snapshot = _snapshot_for_date(db, target)
                if snapshot is None:
                    return {
                        "source": "database", "status": "MISSING",
                        "trade_date": target.isoformat(), "sectors": [],
                        "selected": None, "stocks": [], "pool_rule": POOL_RULE,
                        "message": "数据库暂无美股行业轮动快照，请等待定时任务生成",
                    }
                _CACHE["trade_date"], _CACHE["snapshot"] = target, snapshot
        return _response(snapshot, sector if isinstance(sector, str) else None)


@router.get("/opportunities")
def get_us_market_opportunities():
    """Read the persisted sector snapshot; never rescan the full market on page load."""
    with get_db_session() as db:
        target = _latest_completed_trade_date(db)
        if not target:
            return _market_opportunity_response({})
        with _CACHE_LOCK:
            if _CACHE["trade_date"] == target and _CACHE["snapshot"] is not None:
                snapshot = _CACHE["snapshot"]
            else:
                snapshot = _snapshot_for_date(db, target)
                if snapshot is None:
                    return _market_opportunity_response({})
                _CACHE["trade_date"], _CACHE["snapshot"] = target, snapshot
        return _market_opportunity_response(snapshot)
