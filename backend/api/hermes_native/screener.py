"""
Stock Screener API - Real-time strategy screening with market context.

Endpoints:
  GET  /api/ops/screener/market-environment  - Latest market sentiment
  GET  /api/ops/screener/concept-boards      - Concept boards for latest trading day
  POST /api/ops/screener/scan                - Run strategy screening
  GET  /api/ops/screener/strategies          - List available screening strategies
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional, Optional

import numpy as np
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

# ── Path setup ────────────────────────────────────────────────────────────────
_DB_ROOT = "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database"
_DATA_ROOT = "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data"
_STRATEGIES_ROOT = "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data/strategies"
_COCKPIT_BACKEND = "/Users/gino/Projects/AIROBOT/backend"

for p in (_DB_ROOT, _DATA_ROOT, _STRATEGIES_ROOT, _COCKPIT_BACKEND):
    if p not in sys.path:
        sys.path.insert(0, p)

from api.hermes_native.db_connector import execute_query, execute_one  # noqa: E402
from strategy_base import calc_rsi, calc_ma, calc_atr, calc_donchian  # noqa: E402

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MAX_SCAN_STOCKS = 5500
KLINE_LOOKBACK_DAYS = 60
KLINE_CALENDAR_BUFFER = 120  # Calendar days to cover lookback with holidays/weekends

# Market type -> stock code prefix rules
MARKET_CODE_RULES: dict[str, list[str]] = {
    "主板": ["600", "601", "603", "605", "000", "001", "002", "003"],
    "创业板": ["300", "301"],
    "科创板": ["688", "689"],
    "北交所": ["920"],
}

# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/ops/screener", tags=["screener"])


# ── Request / Response models ─────────────────────────────────────────────────

class ScanRequest(BaseModel):
    strategy: str = Field(..., description="Strategy key to use")
    markets: list[str] = Field(
        default_factory=lambda: ["主板", "创业板", "科创板", "北交所"],
        description="Market types to scan",
    )
    concepts: list[str] = Field(
        default_factory=list,
        description="Optional concept board filters",
    )
    mode: str = Field(default="standard", description="Scanning mode")


# ── Utility helpers ───────────────────────────────────────────────────────────

def _safe_float(value: Any) -> Optional[float]:
    """Safely convert a value to float, returning None on failure."""
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    """Safely convert a value to int, returning None on failure."""
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def _get_latest_trade_date() -> str:
    """Get the most recent trade_date from kline_daily."""
    result = execute_one(
        "SELECT MAX(trade_date) AS latest_date FROM kline_daily WHERE market IN ('SH','SZ','BJ')"
    )
    if result and result.get("latest_date"):
        return str(result["latest_date"])
    # Fallback: try CN_A market
    result2 = execute_one(
        "SELECT MAX(trade_date) AS latest_date FROM kline_daily"
    )
    if result2 and result2.get("latest_date"):
        return str(result2["latest_date"])
    return date.today().strftime("%Y-%m-%d")


def _normalize_symbol(raw_symbol: str) -> str:
    """Normalize a stock symbol by stripping exchange suffixes.
    E.g. '920964.BJ' -> '920964', '000001' -> '000001'
    """
    s = str(raw_symbol).strip()
    if "." in s:
        s = s.split(".")[0]
    return s


def _match_market_type(symbol: str, market_types: list[str]) -> bool:
    """Check if a stock symbol matches any of the requested market types."""
    code = _normalize_symbol(symbol)
    # Also match by exchange suffix
    raw = str(symbol).strip()
    suffix_map = {".BJ": "北交所", ".SH": "主板", ".SZ": "创业板"}
    for mt in market_types:
        # Check suffix first
        for suffix, mapped_mt in suffix_map.items():
            if raw.endswith(suffix) and mapped_mt == mt:
                return True
        # Check code prefix
        prefixes = MARKET_CODE_RULES.get(mt, [])
        for prefix in prefixes:
            if code.startswith(prefix):
                return True
    return False


def _classify(score: float, tradeable_threshold: float = 4, observe_threshold: float = 3) -> str:
    """Classify a stock based on its score."""
    if score >= tradeable_threshold:
        return "tradeable"
    if score >= observe_threshold:
        return "observe"
    return "exclude"


# ── Data fetching helpers ─────────────────────────────────────────────────────

def _fetch_active_stocks_filtered(
    market_types: list[str],
    concept_names: Optional[list[str]] = None,
    limit: int = MAX_SCAN_STOCKS,
) -> list[dict[str, Any]]:
    """
    Fetch active stocks from stock_list, filtered by market type and optional concepts.
    Returns list of dicts with keys: symbol, name, market, industry.
    """
    # Step 1: Get all active A-share stocks
    # stock_list uses market='CN_A' for all A-share stocks; differentiation
    # by exchange is done via code prefix in _match_market_type().
    rows = execute_query(
        """
        SELECT symbol, name, market, industry
        FROM stock_list
        WHERE is_active = TRUE
          AND list_status = 'L'
        ORDER BY symbol
        """
    ) or []

    # Step 2: Filter by market type prefixes
    candidates = [r for r in rows if _match_market_type(r.get("symbol", ""), market_types)]

    # Step 3: If concepts are specified, intersect with concept member stocks
    if concept_names:
        concept_stock_codes = _get_concept_stock_codes(concept_names)
        if concept_stock_codes is not None:
            candidates = [c for c in candidates if c.get("symbol") in concept_stock_codes]

    # Step 4: Limit for performance
    return candidates[:limit]


def _get_concept_stock_codes(concept_names: list[str]) -> Optional[set[str]]:
    """
    Get the union of stock codes belonging to the specified concept boards.
    Uses concept_components table. Returns None if no data found (meaning: do not filter).
    """
    if not concept_names:
        return None

    placeholders = ",".join(["%s"] * len(concept_names))
    rows = execute_query(
        f"""
        SELECT stock_code
        FROM concept_components
        WHERE board_name IN ({placeholders})
          AND is_active = TRUE
        """,
        tuple(concept_names),
    ) or []

    all_codes: set[str] = set()
    for row in rows:
        raw_code = str(row.get("stock_code", "")).strip()
        # Normalize: "300222.SZ" -> "300222"
        code = raw_code.split(".")[0] if "." in raw_code else raw_code
        code = code.zfill(6) if code.isdigit() else code
        if code:
            all_codes.add(code)

    return all_codes if all_codes else None


def _batch_fetch_kline(
    codes: list[str],
    days: int = KLINE_LOOKBACK_DAYS,
) -> dict[str, list[dict[str, Any]]]:
    """
    Batch-fetch kline data for a list of stock codes.
    Returns a dict mapping code -> list of kline rows sorted by trade_date ASC.
    Uses both CN_A (historical) and SH/SZ/BJ (recent) markets, deduplicating
    by (code, trade_date) and preferring the SH/SZ/BJ version when both exist.
    """
    if not codes:
        return {}

    normalized = sorted({_normalize_symbol(c) for c in codes if str(c).strip()})
    if not normalized:
        return {}

    placeholders = ",".join(["%s"] * len(normalized))
    date_bound = (datetime.now() - timedelta(days=KLINE_CALENDAR_BUFFER)).strftime("%Y-%m-%d")

    # Fetch from all markets; CN_A has deep history, SH/SZ/BJ have latest data
    rows = execute_query(
        f"""
        WITH all_rows AS (
            SELECT
                code, trade_date, open, high, low, close, volume, amount,
                change_pct, turnover_rate, market,
                CASE WHEN market IN ('SH','SZ','BJ') THEN 1 ELSE 2 END AS market_priority
            FROM kline_daily
            WHERE code IN ({placeholders})
              AND trade_date >= %s
        ),
        deduped AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY code, trade_date
                    ORDER BY market_priority
                ) AS dup_rn
            FROM all_rows
        ),
        ranked AS (
            SELECT
                code, trade_date, open, high, low, close, volume, amount,
                change_pct, turnover_rate,
                ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) AS rn
            FROM deduped
            WHERE dup_rn = 1
        )
        SELECT code, trade_date, open, high, low, close, volume, amount,
               change_pct, turnover_rate, rn
        FROM ranked
        WHERE rn <= %s
        ORDER BY code, rn
        """,
        tuple(normalized) + (date_bound, days),
    ) or []

    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        code = str(row.get("code", "")).strip()
        if not code:
            continue
        result.setdefault(code, []).append(row)

    # Reverse each list so it is sorted by trade_date ASC (oldest first)
    for code in result:
        result[code].reverse()

    return result


def _build_concept_map(codes: list[str]) -> dict[str, list[str]]:
    """
    Build a mapping from stock code to list of concept board names it belongs to.
    Uses the concept_components table which maps stocks to boards.
    """
    if not codes:
        return {}

    # Normalize codes and build lookup set
    normalized_codes = sorted({_normalize_symbol(c) for c in codes if str(c).strip()})
    if not normalized_codes:
        return {}

    placeholders = ",".join(["%s"] * len(normalized_codes))

    # concept_components uses stock_code with possible exchange suffix (e.g. "300222.SZ")
    # We need to match both plain codes and suffixed codes
    rows = execute_query(
        f"""
        SELECT stock_code, board_name
        FROM concept_components
        WHERE stock_code IN ({placeholders})
           OR SPLIT_PART(stock_code, '.', 1) IN ({placeholders})
        """,
        tuple(normalized_codes) + tuple(normalized_codes),
    ) or []

    code_set = set(normalized_codes)
    mapping: dict[str, list[str]] = {c: [] for c in code_set}

    for row in rows:
        raw_code = str(row.get("stock_code", "")).strip()
        board_name = row.get("board_name", "")
        if not raw_code or not board_name:
            continue
        code = _normalize_symbol(raw_code)
        if code in code_set:
            mapping.setdefault(code, []).append(board_name)

    # Limit to top 5 concepts per stock for readability
    for code in mapping:
        mapping[code] = mapping[code][:5]

    return mapping


# ── Strategy evaluation functions ─────────────────────────────────────────────

def _evaluate_qinglong(kline: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Qinglong (MA10 main uptrend):
    - MA10 strictly rising for last 5 bars
    - Close >= MA10 * 0.97
    - 5% <= 10-day gain <= 40%
    - 40 <= RSI(14) <= 85
    - Score >= 4 -> tradeable, >= 3 -> observe, else -> exclude
    """
    if len(kline) < 15:
        return None

    closes = [_safe_float(k.get("close")) for k in kline]
    closes = [c for c in closes if c is not None]
    if len(closes) < 15:
        return None

    current_close = closes[-1]

    # Compute MA10 values for the last 10 bars
    ma10_values: list[float] = []
    for i in range(max(0, len(closes) - 10), len(closes)):
        ma = calc_ma(closes[: i + 1], 10)
        if ma is not None:
            ma10_values.append(ma)

    if len(ma10_values) < 5:
        return None

    # MA10 strictly rising for last 5 bars
    start_idx = len(ma10_values) - 5
    ma10_rising = all(
        ma10_values[j] < ma10_values[j + 1]
        for j in range(start_idx, len(ma10_values) - 1)
    )
    if not ma10_rising:
        return None

    # Close >= MA10 * 0.97
    latest_ma10 = ma10_values[-1]
    if current_close < latest_ma10 * 0.97:
        return None

    # 10-day gain
    if len(closes) <= 11:
        return None
    gain_10d = (current_close - closes[-11]) / closes[-11] * 100
    if gain_10d < 5 or gain_10d > 40:
        return None

    # RSI(14)
    rsi = calc_rsi(closes, 14)
    if rsi < 40 or rsi > 85:
        return None

    # Scoring
    score = 0.0
    # MA10 rising strongly
    if len(ma10_values) >= 5:
        ma10_slope = (ma10_values[-1] - ma10_values[-5]) / ma10_values[-5] * 100
        if ma10_slope > 3:
            score += 2.0
        elif ma10_slope > 1:
            score += 1.5
        else:
            score += 1.0

    # Close relative to MA10
    deviation = (current_close - latest_ma10) / latest_ma10 * 100
    if 0 <= deviation <= 5:
        score += 1.5
    elif deviation > 5:
        score += 0.5
    else:
        score += 1.0

    # Gain health
    if 8 <= gain_10d <= 25:
        score += 1.5
    elif 5 <= gain_10d <= 40:
        score += 1.0

    # RSI health
    if 50 <= rsi <= 70:
        score += 1.0
    elif 40 <= rsi <= 85:
        score += 0.5

    # Volume confirmation
    volumes = [_safe_float(k.get("volume")) for k in kline]
    volumes = [v for v in volumes if v is not None]
    if len(volumes) >= 10:
        vol_ma5 = float(np.mean(volumes[-5:]))
        vol_prev5 = float(np.mean(volumes[-10:-5]))
        if vol_prev5 > 0 and vol_ma5 > vol_prev5:
            score += 1.0

    reason_parts = ["MA10连涨5日"]
    if 50 <= rsi <= 70:
        reason_parts.append("RSI健康")
    if len(volumes) >= 10:
        vol_ma5_val = float(np.mean(volumes[-5:]))
        vol_prev5_val = float(np.mean(volumes[-10:-5]))
        if vol_prev5_val > 0 and vol_ma5_val > vol_prev5_val * 1.2:
            reason_parts.append("量价齐升")

    return {
        "score": round(score, 1),
        "rsi": rsi,
        "ma10": round(latest_ma10, 2),
        "gain_10d": round(gain_10d, 2),
        "deviation": round(deviation, 2),
        "reason": "+".join(reason_parts),
    }


def _evaluate_baihu(kline: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Baihu V2.6 (MA20 strong pullback) — exact mirror of baihu_strategy.py:
    - MA20 rising for last 3 consecutive bars (needs ≥4 MA20 values)
    - abs((close - MA20) / MA20) <= 3%
    - 10% <= 20-day gain <= 60%
    - 30 <= RSI(14) <= 75
    - Score: max ~9 pts (MA20 proximity 0-4, shadow 1-3, RSI 0-1, gain 0-1)
    - Score >= 3 -> tradeable (same as original strategy)
    """
    if len(kline) < 25:
        return None

    closes = [_safe_float(k.get("close")) for k in kline]
    highs = [_safe_float(k.get("high")) for k in kline]
    lows = [_safe_float(k.get("low")) for k in kline]
    opens = [_safe_float(k.get("open")) for k in kline]
    closes = [c for c in closes if c is not None]
    highs = [h for h in highs if h is not None]
    lows = [lo for lo in lows if lo is not None]
    opens = [o for o in opens if o is not None]
    if len(closes) < 25 or len(highs) < 25 or len(lows) < 25 or len(opens) < 25:
        return None

    current_close = closes[-1]

    # Compute MA20 values for last 8 bars
    ma20_values: list[float] = []
    for i in range(max(0, len(closes) - 8), len(closes)):
        ma = calc_ma(closes[: i + 1], 20)
        if ma is not None:
            ma20_values.append(ma)

    # Original requires ≥4 MA20 values
    if len(ma20_values) < 4:
        return None

    current_ma20 = ma20_values[-1]

    # Hard filter: MA20 rising for last 3 consecutive bars (checked via 4 values)
    ma20_rising = all(
        ma20_values[j] < ma20_values[j + 1]
        for j in range(len(ma20_values) - 4, len(ma20_values) - 1)
    )
    if not ma20_rising:
        return None

    # Hard filter: deviation from MA20 within ±3%
    deviation = (current_close - current_ma20) / current_ma20 * 100
    if abs(deviation) > 3.0:
        return None

    # Hard filter: 20-day gain between 10% and 60%
    if len(closes) > 25:
        gain_20d = (current_close - closes[-21]) / closes[-21] * 100
    else:
        gain_20d = (current_close - closes[0]) / closes[0] * 100
    if gain_20d < 10 or gain_20d > 60:
        return None

    # Hard filter: RSI(14) between 30 and 75
    rsi = calc_rsi(closes, 14)
    if rsi < 30 or rsi > 75:
        return None

    # ── Scoring — exact match with baihu_strategy.py ──
    today_open = opens[-1]
    today_low = lows[-1]
    lower_shadow = (min(current_close, today_open) - today_low) / current_close * 100

    score = 0
    score += min(4, int(abs(deviation) < 1.0) + 2)    # MA20 proximity (2-4)
    score += min(3, int(lower_shadow > 1.0) + 1)       # lower shadow (1-3)
    score += min(3, int(60 > rsi > 40))                 # RSI health (0-1)
    score += min(3, int(40 > gain_20d > 15))            # gain health (0-1)

    # Reason
    reason_parts = ["MA20强势回调"]
    if abs(deviation) < 1:
        reason_parts.append("贴近均线")
    if 40 < rsi < 60:
        reason_parts.append("RSI适中")
    if lower_shadow > 1.0:
        reason_parts.append("下影线支撑")
    if 15 < gain_20d < 40:
        reason_parts.append("涨幅健康")

    return {
        "score": score,
        "rsi": round(rsi, 1),
        "ma20": round(current_ma20, 2),
        "gain_20d": round(gain_20d, 2),
        "deviation": round(deviation, 2),
        "reason": "+".join(reason_parts),
    }


def _evaluate_turtle(kline: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Turtle trend (Donchian channel breakout + ATR stop-loss):
    - Close > 20-day high (Donchian upper)
    - ATR(14) > 0 and ATR/close * 100 < 5%
    - Classification based on ATR and trend strength
    """
    if len(kline) < 25:
        return None

    closes = [_safe_float(k.get("close")) for k in kline]
    highs = [_safe_float(k.get("high")) for k in kline]
    lows = [_safe_float(k.get("low")) for k in kline]
    volumes = [_safe_float(k.get("volume")) for k in kline]

    closes = [c for c in closes if c is not None]
    highs = [h for h in highs if h is not None]
    lows = [lo for lo in lows if lo is not None]
    volumes = [v for v in volumes if v is not None]

    if len(closes) < 25 or len(highs) < 25 or len(lows) < 25:
        return None

    current_close = closes[-1]

    # Donchian channel
    donchian_high, donchian_low = calc_donchian(highs, lows, 20, 10)
    if donchian_high == 0 or donchian_low == 0:
        return None

    # ATR(14)
    atr = calc_atr(highs, lows, closes, 14)
    if atr <= 0:
        return None

    atr_pct = atr / current_close * 100 if current_close > 0 else 0
    if atr_pct >= 5:
        return None

    # Must be near or above Donchian upper
    if current_close < donchian_high * 0.98:
        return None

    # MA trend filter
    ma20 = calc_ma(closes, 20)
    if ma20 is None:
        return None

    # Scoring
    score = 0.0

    # Breakout strength
    if current_close >= donchian_high:
        score += 3.0
        signal_type = "breakout"
    elif current_close >= donchian_high * 0.99:
        score += 2.0
        signal_type = "near_breakout"
    else:
        score += 1.0
        signal_type = "near"

    # Trend alignment
    if current_close > ma20:
        score += 1.0
    if ma20 is not None:
        ma20_prev = calc_ma(closes[:-5], 20)
        if ma20_prev is not None and ma20 > ma20_prev:
            score += 0.5

    # ATR health (moderate volatility preferred)
    if 2 <= atr_pct <= 4:
        score += 1.5
    elif 1 <= atr_pct < 2:
        score += 1.0
    else:
        score += 0.5

    # RSI confirmation
    rsi = calc_rsi(closes, 14)
    if 45 <= rsi <= 80:
        score += 1.0

    # Volume confirmation
    if len(volumes) >= 10:
        vol_recent = float(np.mean(volumes[-3:]))
        vol_prev = float(np.mean(volumes[-10:-3]))
        if vol_prev > 0 and vol_recent > vol_prev * 1.3:
            score += 1.0

    stop_loss = round(current_close - 2 * atr, 2)
    take_profit = round(current_close + 3 * atr, 2)

    reason_parts = ["Donchian突破" if signal_type == "breakout" else "接近突破"]
    if 2 <= atr_pct <= 4:
        reason_parts.append("波动适中")
    if current_close > ma20:
        reason_parts.append("均线多头")

    return {
        "score": round(score, 1),
        "rsi": rsi,
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 1),
        "donchian_high": round(donchian_high, 2),
        "donchian_low": round(donchian_low, 2),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "signal_type": signal_type,
        "reason": "+".join(reason_parts),
    }


def _evaluate_alpha(kline: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Alpha multi-factor:
    - Composite score from RSI, volume ratio, MA alignment, momentum, volatility
    - Classification based on composite score
    """
    if len(kline) < 40:
        return None

    closes = [_safe_float(k.get("close")) for k in kline]
    highs = [_safe_float(k.get("high")) for k in kline]
    lows = [_safe_float(k.get("low")) for k in kline]
    volumes = [_safe_float(k.get("volume")) for k in kline]

    closes = [c for c in closes if c is not None]
    highs = [h for h in highs if h is not None]
    lows = [lo for lo in lows if lo is not None]
    volumes = [v for v in volumes if v is not None]

    if len(closes) < 40 or len(volumes) < 20:
        return None

    current_close = closes[-1]

    # Factor 1: Momentum (20-day gain)
    if len(closes) <= 21:
        return None
    mom_20 = (current_close - closes[-21]) / closes[-21] * 100
    mom_score = min(10, max(0, (mom_20 + 10) / 4))  # -10%~30% -> 0~10

    # Factor 2: MA alignment (bull arrangement)
    ma5 = calc_ma(closes, 5) or current_close
    ma10 = calc_ma(closes, 10) or current_close
    ma20 = calc_ma(closes, 20) or current_close
    ma_score = 0.0
    if ma5 > ma10 > ma20:
        ma_score += 5.0
    if current_close > ma5 > ma10 > ma20:
        ma_score += 5.0

    # Factor 3: Volatility (lower is preferred)
    returns = np.diff(closes[-30:]) / np.array(closes[-30:-1])
    volatility = float(np.std(returns)) * 100
    vol_score = max(0, 10 - volatility * 50)

    # Factor 4: RSI health
    rsi = calc_rsi(closes, 14)
    if 45 <= rsi <= 70:
        rsi_score = 10.0
    elif 40 <= rsi <= 75:
        rsi_score = 7.0
    elif 30 <= rsi <= 80:
        rsi_score = 4.0
    else:
        rsi_score = 0.0

    # Factor 5: Volume health
    vol_ma20 = float(np.mean(volumes[-20:]))
    vol_ratio = float(volumes[-1] / vol_ma20) if vol_ma20 > 0 else 1.0
    vol_health_score = 10.0 if 0.8 <= vol_ratio <= 2.0 else (7.0 if 0.5 <= vol_ratio <= 3.0 else 3.0)

    # Composite score (weighted)
    total_score = (
        mom_score * 0.25
        + ma_score * 0.25
        + vol_score * 0.15
        + rsi_score * 0.20
        + vol_health_score * 0.15
    )

    # Scale to 0-10 range for classification consistency
    scaled_score = total_score  # Already in 0-10 range

    reason_parts = []
    if mom_score >= 6:
        reason_parts.append("动量强")
    if ma_score >= 8:
        reason_parts.append("多头排列")
    if rsi_score >= 8:
        reason_parts.append("RSI健康")
    if vol_health_score >= 8:
        reason_parts.append("量能配合")
    if not reason_parts:
        reason_parts.append("综合因子")

    return {
        "score": round(scaled_score, 1),
        "rsi": rsi,
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "gain_20d": round(mom_20, 2),
        "volatility": round(volatility * 100, 2),
        "vol_ratio": round(vol_ratio * 100, 1),
        "reason": "+".join(reason_parts),
    }


# ── Strategy registry ─────────────────────────────────────────────────────────

STRATEGY_EVALUATORS: dict[str, dict[str, Any]] = {
    "qinglong": {
        "name": "青龙白虎",
        "desc": "MA10主升浪 + MA20第二波",
        "evaluate": _evaluate_qinglong,
        "tradeable_threshold": 4,
        "observe_threshold": 3,
        "min_kline": 15,
    },
    "baihu": {
        "name": "白虎-科创创业V26",
        "desc": "MA20强势回调选股",
        "evaluate": _evaluate_baihu,
        "tradeable_threshold": 3,
        "observe_threshold": 2,
        "min_kline": 25,
    },
    "turtle": {
        "name": "海龟趋势",
        "desc": "Donchian通道突破 + ATR止损",
        "evaluate": _evaluate_turtle,
        "tradeable_threshold": 5,
        "observe_threshold": 3.5,
        "min_kline": 25,
    },
    "alpha": {
        "name": "Alpha多因子",
        "desc": "多因子综合打分选股",
        "evaluate": _evaluate_alpha,
        "tradeable_threshold": 6,
        "observe_threshold": 4,
        "min_kline": 40,
    },
}


# ── Execution plan builder ────────────────────────────────────────────────────

def _build_execution_plan(
    tradeable_stocks: list[dict[str, Any]],
    strategy_key: str,
    strategy_name: str,
) -> list[dict[str, Any]]:
    """
    Build an execution plan for tradeable stocks with buy/sell points,
    stop-loss, take-profit, and position sizing guidance.
    """
    plans: list[dict[str, Any]] = []

    for stock in tradeable_stocks:
        code = stock.get("code", "")
        name = stock.get("name", "")
        close = _safe_float(stock.get("close"))
        if close is None or close <= 0:
            continue

        concepts = stock.get("concepts", [])
        concept_str = concepts[0] if concepts else ""

        # Compute buy/stop/profit levels based on strategy
        if strategy_key == "qinglong":
            ma10 = _safe_float(stock.get("ma10")) or close
            buy_point = round(ma10, 2)
            buy_range = f"{round(ma10 * 0.98, 2)}-{round(ma10 * 1.02, 2)}"
            stop_loss = round(ma10 * 0.95, 2)
            take_profit = round(close * 1.15, 2)
            trigger = "回踩MA10"
            expiry = "跌破MA20"
        elif strategy_key == "baihu":
            ma20 = _safe_float(stock.get("ma20")) or close
            buy_point = round(ma20, 2)
            buy_range = f"{round(ma20 * 0.98, 2)}-{round(ma20 * 1.02, 2)}"
            stop_loss = round(ma20 * 0.93, 2)
            take_profit = round(close * 1.12, 2)
            trigger = "回踩MA20企稳"
            expiry = "跌破MA20超过3%"
        elif strategy_key == "turtle":
            atr = _safe_float(stock.get("atr")) or close * 0.03
            buy_point = close
            buy_range = f"{round(close * 0.98, 2)}-{round(close * 1.02, 2)}"
            stop_loss = round(close - 2 * atr, 2)
            take_profit = round(close + 3 * atr, 2)
            trigger = "突破Donchian上轨"
            expiry = "跌破2ATR止损"
        elif strategy_key == "alpha":
            ma20 = _safe_float(stock.get("ma20")) or close
            buy_point = round(close, 2)
            buy_range = f"{round(close * 0.97, 2)}-{round(close * 1.03, 2)}"
            stop_loss = round(close * 0.92, 2)
            take_profit = round(close * 1.15, 2)
            trigger = "多因子共振"
            expiry = "因子评分下降"
        else:
            buy_point = close
            buy_range = f"{round(close * 0.98, 2)}-{round(close * 1.02, 2)}"
            stop_loss = round(close * 0.93, 2)
            take_profit = round(close * 1.15, 2)
            trigger = "信号确认"
            expiry = "止损/止盈"

        plans.append({
            "type": "买入",
            "strategy": strategy_name,
            "code": code,
            "name": name,
            "concept": concept_str,
            "buy_point": buy_point,
            "buy_range": buy_range,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "position": "10%",
            "trigger": trigger,
            "expiry": expiry,
            "time": "次日开盘",
            "reason": stock.get("reason", ""),
        })

    return plans


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/market-environment")
def get_market_environment():
    """
    Return market sentiment for the latest trading day.
    Queries market_sentiment_daily and returns sentiment metrics.
    """
    try:
        row = execute_one(
            """
            SELECT
                trade_date, market,
                sentiment_score, sentiment_label,
                advance_count, decline_count,
                up_limit_count, down_limit_count,
                total_volume, total_amount,
                new_high_count, new_low_count,
                amplitude, advance_decline_ratio
            FROM market_sentiment_daily
            ORDER BY trade_date DESC
            LIMIT 1
            """
        )

        if not row:
            return {
                "trade_date": date.today().strftime("%Y-%m-%d"),
                "sentiment_score": None,
                "sentiment_label": "无数据",
                "advance_count": None,
                "decline_count": None,
                "up_limit_count": None,
                "down_limit_count": None,
                "total_volume": None,
                "status": "undetected",
            }

        trade_date_val = row.get("trade_date")
        trade_date_str = str(trade_date_val) if trade_date_val else date.today().strftime("%Y-%m-%d")

        return {
            "trade_date": trade_date_str,
            "sentiment_score": _safe_int(row.get("sentiment_score")),
            "sentiment_label": row.get("sentiment_label") or "中性",
            "advance_count": _safe_int(row.get("advance_count")),
            "decline_count": _safe_int(row.get("decline_count")),
            "up_limit_count": _safe_int(row.get("up_limit_count")),
            "down_limit_count": _safe_int(row.get("down_limit_count")),
            "total_volume": _safe_int(row.get("total_volume")),
            "total_amount": _safe_int(row.get("total_amount")),
            "new_high_count": _safe_int(row.get("new_high_count")),
            "new_low_count": _safe_int(row.get("new_low_count")),
            "amplitude": _safe_float(row.get("amplitude")),
            "advance_decline_ratio": _safe_float(row.get("advance_decline_ratio")),
            "status": "detected",
        }

    except Exception as exc:
        logger.exception("Failed to fetch market environment")
        return {
            "trade_date": date.today().strftime("%Y-%m-%d"),
            "sentiment_score": None,
            "sentiment_label": "查询异常",
            "advance_count": None,
            "decline_count": None,
            "up_limit_count": None,
            "down_limit_count": None,
            "total_volume": None,
            "status": "undetected",
            "error": str(exc),
        }


@router.get("/concept-boards")
def get_concept_boards():
    """
    Return concept boards with stock counts for the latest trading day.
    Sorted by change_pct descending.
    """
    try:
        # Get latest trade_date from concept_board_daily
        date_row = execute_one(
            "SELECT MAX(trade_date) AS latest_date FROM concept_board_daily"
        )
        if not date_row or not date_row.get("latest_date"):
            return []

        trade_date_str = str(date_row["latest_date"])

        board_rows = execute_query(
            """
            SELECT board_code AS code, board_name AS name,
                   change_pct, stock_count
            FROM concept_board_daily
            WHERE trade_date = %s
            ORDER BY change_pct DESC NULLS LAST
            LIMIT 100
            """,
            (trade_date_str,),
        ) or []

        result: list[dict[str, Any]] = []
        for row in board_rows:
            result.append({
                "code": row.get("code", ""),
                "name": row.get("name", ""),
                "stock_count": _safe_int(row.get("stock_count")) or 0,
                "change_pct": _safe_float(row.get("change_pct")),
            })

        return result

    except Exception as exc:
        logger.exception("Failed to fetch concept boards")
        return {"ok": False, "error": str(exc), "items": []}


@router.post("/scan")
def run_scan(request: ScanRequest):
    """
    Main screening endpoint.
    Accepts a strategy key, market filters, optional concept filters, and scanning mode.
    Returns classified results (tradeable / observe / exclude) with execution plan.
    """
    start_time = time.monotonic()

    strategy_key = request.strategy
    markets = request.markets or ["主板", "创业板", "科创板", "北交所"]
    concepts = request.concepts or []
    mode = request.mode or "standard"

    # Validate strategy
    strategy_info = STRATEGY_EVALUATORS.get(strategy_key)
    if not strategy_info:
        available = ", ".join(STRATEGY_EVALUATORS.keys())
        return {
            "ok": False,
            "error": f"Unknown strategy: '{strategy_key}'. Available: {available}",
        }

    evaluate_fn = strategy_info["evaluate"]
    strategy_name = strategy_info["name"]
    tradeable_threshold = strategy_info["tradeable_threshold"]
    observe_threshold = strategy_info["observe_threshold"]

    trade_date = _get_latest_trade_date()

    # Step 1: Get candidate stocks
    try:
        candidates = _fetch_active_stocks_filtered(
            market_types=markets,
            concept_names=concepts if concepts else None,
            limit=MAX_SCAN_STOCKS,
        )
    except Exception as exc:
        logger.exception("Failed to fetch candidate stocks")
        return {"ok": False, "error": f"Failed to fetch candidates: {exc}"}

    if not candidates:
        return {
            "ok": True,
            "strategy": strategy_key,
            "mode": mode,
            "scanned": 0,
            "tradeable": [],
            "observe": [],
            "exclude": [],
            "execution_plan": [],
            "trade_date": trade_date,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": "No candidate stocks found for the specified filters",
        }

    # Step 2: Batch fetch kline data (symbols are normalized inside _batch_fetch_kline)
    codes = [_normalize_symbol(c["symbol"]) for c in candidates]
    try:
        kline_map = _batch_fetch_kline(codes)
    except Exception as exc:
        logger.exception("Failed to fetch kline data")
        return {"ok": False, "error": f"Failed to fetch kline data: {exc}"}

    # Step 3: Build concept mapping for result enrichment
    concept_map: dict[str, list[str]] = {}
    try:
        concept_map = _build_concept_map(codes)
    except Exception:
        pass  # Non-critical: concept labels are enrichment

    # Step 4: Build stock meta lookup (keyed by normalized symbol)
    stock_meta: dict[str, dict[str, Any]] = {}
    for c in candidates:
        sym = _normalize_symbol(c.get("symbol", ""))
        stock_meta[sym] = {
            "name": c.get("name", ""),
            "industry": c.get("industry", ""),
        }

    # Step 5: Evaluate each stock
    tradeable: list[dict[str, Any]] = []
    observe: list[dict[str, Any]] = []
    exclude: list[dict[str, Any]] = []
    scanned_count = 0

    for code, kline_rows in kline_map.items():
        scanned_count += 1

        if len(kline_rows) < strategy_info.get("min_kline", 15):
            continue

        try:
            result = evaluate_fn(kline_rows)
        except Exception:
            continue

        if result is None:
            continue

        score = result.get("score", 0)
        classification = _classify(score, tradeable_threshold, observe_threshold)

        latest_row = kline_rows[-1]
        meta = stock_meta.get(code, {})
        stock_concepts = concept_map.get(code, [])

        entry = {
            "code": code,
            "name": meta.get("name", ""),
            "close": _safe_float(latest_row.get("close")),
            "change_pct": _safe_float(latest_row.get("change_pct")),
            "score": score,
            "concepts": stock_concepts[:3],  # Limit to top 3 concepts
            "reason": result.get("reason", ""),
            "industry": meta.get("industry", ""),
        }

        # Attach strategy-specific fields
        for key in ("rsi", "ma10", "ma20", "ma5", "gain_10d", "gain_20d",
                     "deviation", "atr", "atr_pct", "stop_loss", "take_profit",
                     "donchian_high", "donchian_low", "signal_type",
                     "volatility", "vol_ratio"):
            if key in result:
                entry[key] = result[key]

        if classification == "tradeable":
            tradeable.append(entry)
        elif classification == "observe":
            observe.append(entry)
        else:
            exclude.append(entry)

    # Sort by score descending within each category
    tradeable.sort(key=lambda x: x.get("score", 0), reverse=True)
    observe.sort(key=lambda x: x.get("score", 0), reverse=True)
    exclude.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Cap results for reasonable payload size
    tradeable = tradeable[:50]
    observe = observe[:50]
    exclude = exclude[:50]

    # Step 6: Build execution plan for tradeable stocks
    execution_plan = _build_execution_plan(tradeable, strategy_key, strategy_name)

    elapsed_ms = round((time.monotonic() - start_time) * 1000)

    return {
        "ok": True,
        "strategy": strategy_key,
        "strategy_name": strategy_name,
        "mode": mode,
        "scanned": scanned_count,
        "tradeable": tradeable,
        "observe": observe,
        "exclude": exclude,
        "execution_plan": execution_plan,
        "trade_date": trade_date,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_ms": elapsed_ms,
    }


@router.get("/strategies")
def get_strategies():
    """
    Return the list of strategies available for screening.
    These are strategies that have a script_name in the catalog (i.e., runnable).
    """
    try:
        # Load from the STRATEGY_CATALOG in the backend config
        from api.hermes_native.strategies.catalog import STRATEGY_DEFINITIONS

        result: list[dict[str, Any]] = []

        # First, add strategies that have evaluators in this screener
        evaluator_keys = set(STRATEGY_EVALUATORS.keys())

        for definition in STRATEGY_DEFINITIONS:
            key = definition.get("key", "")
            has_evaluator = key in evaluator_keys
            has_script = bool(definition.get("script_name"))
            is_hidden = bool(definition.get("hidden"))

            # Include if: has an evaluator OR has a script, and not hidden
            if is_hidden:
                continue
            if not has_evaluator and not has_script:
                continue

            result.append({
                "key": key,
                "name": definition.get("name", key),
                "desc": definition.get("desc", ""),
                "market": definition.get("market", ""),
                "runnable": has_script,
                "screenable": has_evaluator,
            })

        return result

    except Exception as exc:
        logger.exception("Failed to load strategy catalog")
        # Fallback: return strategies from local evaluators
        result = []
        for key, info in STRATEGY_EVALUATORS.items():
            result.append({
                "key": key,
                "name": info["name"],
                "desc": info["desc"],
                "market": "A股",
                "runnable": False,
                "screenable": True,
            })
        return result
