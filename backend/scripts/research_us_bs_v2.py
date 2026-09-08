"""Research-only walk-forward comparison for the US-stock B signal.

Signals are calculated after the close and executed at the next session open.
The final 2026-05-01+ period is held out from candidate development.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, "backend")

from api.us_stock_analysis import (  # noqa: E402
    _adx_series,
    _atr_series,
    _kdj_series,
    _macd_series,
    _rsi_series,
    _sma_fill,
)
from db.session import get_db_session  # noqa: E402
from market_quant.universe import get_members  # noqa: E402
from us_quant.repository import USStockDaily  # noqa: E402
from us_quant.universe import get_universe_members  # noqa: E402

START = date(2025, 8, 7)
HOLDOUT = date(2026, 5, 1)
END = date(2026, 8, 7)
COST = 0.003
HORIZONS = (5, 10, 20)


def universe() -> set[str]:
    return (
        set(get_members("US", "CORE"))
        | set(get_members("US", "CORE_B"))
        | set(get_members("US", "RESEARCH"))
        | set(get_universe_members("US_WATCHLIST"))
    )


def load_rows() -> dict[str, list[tuple]]:
    symbols = universe()
    query_symbols = symbols | {"SPY"}
    with get_db_session() as db:
        coverage = (
            db.query(USStockDaily.symbol, USStockDaily.trade_date)
            .filter(USStockDaily.symbol.in_(query_symbols))
            .order_by(USStockDaily.symbol, USStockDaily.trade_date)
            .all()
        )
        grouped_dates: dict[str, list[date]] = defaultdict(list)
        for symbol, trade_date in coverage:
            grouped_dates[symbol].append(trade_date)
        valid = {
            symbol
            for symbol, dates in grouped_dates.items()
            if len(dates) >= 180 and dates[0] <= START and dates[-1] >= END
        }
        rows = (
            db.query(
                USStockDaily.symbol,
                USStockDaily.trade_date,
                USStockDaily.open,
                USStockDaily.high,
                USStockDaily.low,
                USStockDaily.close,
                USStockDaily.volume,
            )
            .filter(USStockDaily.symbol.in_(valid))
            .order_by(USStockDaily.symbol, USStockDaily.trade_date)
            .all()
        )
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        if all(value is not None for value in row[2:]) and all(float(value) > 0 for value in row[2:6]):
            grouped[row[0]].append((row[1], *(float(value) for value in row[2:])))
    return grouped


def feature_rows(grouped: dict[str, list[tuple]]) -> list[dict]:
    result = []
    spy_state = {}
    if "SPY" in grouped:
        spy_data = grouped["SPY"]
        spy_closes = [row[4] for row in spy_data]
        spy_ma20, spy_ma60 = _sma_fill(spy_closes, 20), _sma_fill(spy_closes, 60)
        for i in range(60, len(spy_data)):
            spy_state[spy_data[i][0]] = (
                spy_closes[i] > spy_ma60[i]
                and spy_ma20[i] > spy_ma60[i]
                and spy_ma20[i] > spy_ma20[i - 5]
            )
    for symbol, data in grouped.items():
        dates = [row[0] for row in data]
        opens = [row[1] for row in data]
        highs = [row[2] for row in data]
        lows = [row[3] for row in data]
        closes = [row[4] for row in data]
        volumes = [row[5] for row in data]
        ma5, ma20, ma60 = (_sma_fill(closes, n) for n in (5, 20, 60))
        vol20 = _sma_fill(volumes, 20)
        kdj = _kdj_series(highs, lows, closes)
        macd = _macd_series(closes)
        rsi = _rsi_series(closes)
        adx = _adx_series(highs, lows, closes)
        atr = _atr_series(highs, lows, closes)
        for i in range(60, len(data) - max(HORIZONS) - 1):
            signal_date = dates[i]
            if not START <= signal_date <= END:
                continue
            required = (
                ma5[i - 1], ma20[i - 1], ma5[i], ma20[i], ma60[i],
                kdj["k"][i - 1], kdj["d"][i - 1], kdj["k"][i], kdj["d"][i],
                macd["hist"][i], macd["hist"][i - 1], rsi[i], adx["adx"][i],
                adx["plus_di"][i], adx["minus_di"][i], atr[i], vol20[i],
            )
            if any(value is None for value in required) or opens[i + 1] <= 0:
                continue
            # Corporate actions/raw-price corruption guard. This DB currently has no adj_close.
            if abs(closes[i] / closes[i - 1] - 1) > 0.35 or abs(opens[i + 1] / closes[i] - 1) > 0.35:
                continue
            ma_cross = ma5[i - 1] <= ma20[i - 1] and ma5[i] > ma20[i]
            ma_cross_down = ma5[i - 1] >= ma20[i - 1] and ma5[i] < ma20[i]
            kdj_cross = kdj["k"][i - 1] <= kdj["d"][i - 1] and kdj["k"][i] > kdj["d"][i]
            kdj_cross_down = kdj["k"][i - 1] >= kdj["d"][i - 1] and kdj["k"][i] < kdj["d"][i]
            macd_cross_down = macd["hist"][i - 1] >= 0 and macd["hist"][i] < 0
            row = {
                "symbol": symbol,
                "date": signal_date,
                "ma_cross": ma_cross,
                "ma_cross_down": ma_cross_down,
                "kdj_cross": kdj_cross,
                "kdj_cross_down": kdj_cross_down,
                "macd_cross_down": macd_cross_down,
                "kdj_bull": kdj["k"][i] > kdj["d"][i],
                "trend": closes[i] > ma20[i],
                "trend60": closes[i] > ma60[i],
                "trend_structure": ma20[i] > ma60[i],
                "ma20_up": ma20[i] > ma20[i - 5],
                "macd_pos": macd["hist"][i] > 0,
                "macd_neg": macd["hist"][i] < 0,
                "macd_rising": macd["hist"][i] > macd["hist"][i - 1],
                "macd_above_zero": macd["dif"][i] > 0,
                "rsi_ok": 45 <= rsi[i] <= 70,
                "rsi_entry": 45 <= rsi[i] <= 65,
                "rsi_high": rsi[i] >= 65,
                "kdj_not_hot": kdj["k"][i] <= 75,
                "kdj_was_hot": kdj["k"][i - 1] >= 75,
                "adx_ok": adx["adx"][i] >= 20 and adx["plus_di"][i] > adx["minus_di"][i],
                "volume_ok": volumes[i] >= 0.8 * vol20[i],
                "volume_strong": volumes[i] >= 1.2 * vol20[i],
                "not_extended": closes[i] <= 1.06 * ma20[i],
                "near_ma20": closes[i] <= 1.03 * ma20[i],
                "extended": closes[i] >= 1.04 * ma20[i],
                "atr_ok": atr[i] / closes[i] <= 0.06,
                "mom20_ok": 1.0 <= closes[i] / closes[i - 20] <= 1.25,
                "price_ok": closes[i] >= 5,
                "liquid": closes[i] * vol20[i] >= 20_000_000,
                "breakout20": closes[i] > max(closes[i - 20:i]),
                "breakdown20": closes[i] < min(closes[i - 20:i]),
                "cross_below_ma20": closes[i - 1] >= ma20[i - 1] and closes[i] < ma20[i],
                "below_ma5": closes[i] < ma5[i],
                "retreat5": closes[i] <= 0.95 * max(closes[i - 20:i + 1]),
                "spy_risk_on": spy_state.get(signal_date, False),
                "spy_risk_off": not spy_state.get(signal_date, False),
            }
            entry = opens[i + 1]
            valid_return = True
            for horizon in HORIZONS:
                exit_price = closes[i + horizon]
                raw_return = exit_price / entry - 1
                if abs(raw_return) > 0.8:
                    valid_return = False
                    break
                row[f"r{horizon}"] = raw_return - COST
                row[f"raw{horizon}"] = raw_return
            if valid_return:
                result.append(row)
    return result


CANDIDATES = {
    "v1_current": lambda x: x["ma_cross"] and x["kdj_cross"] and x["trend"],
    "ma_cross_kdj_state": lambda x: x["ma_cross"] and x["kdj_bull"] and x["trend"],
    "kdj_cross_trend": lambda x: x["kdj_cross"] and x["trend"] and x["trend60"] and x["ma20_up"],
    "v1_trend60": lambda x: CANDIDATES["v1_current"](x) and x["trend60"],
    "v1_macd": lambda x: CANDIDATES["v1_current"](x) and x["macd_pos"],
    "v1_macd_rising": lambda x: CANDIDATES["v1_current"](x) and x["macd_rising"],
    "v1_macd_zero": lambda x: CANDIDATES["v1_current"](x) and x["macd_above_zero"],
    "v1_rsi": lambda x: CANDIDATES["v1_current"](x) and x["rsi_ok"],
    "v1_adx": lambda x: CANDIDATES["v1_current"](x) and x["adx_ok"],
    "v1_volume": lambda x: CANDIDATES["v1_current"](x) and x["volume_ok"],
    "v1_not_hot": lambda x: CANDIDATES["v1_current"](x) and x["kdj_not_hot"],
    "v1_not_extended": lambda x: CANDIDATES["v1_current"](x) and x["not_extended"],
    "v1_atr": lambda x: CANDIDATES["v1_current"](x) and x["atr_ok"],
    "v1_momentum": lambda x: CANDIDATES["v1_current"](x) and x["mom20_ok"],
    "v1_liquid": lambda x: CANDIDATES["v1_current"](x) and x["price_ok"] and x["liquid"],
    "v1_quality": lambda x: CANDIDATES["v1_current"](x) and x["trend60"] and x["ma20_up"] and x["rsi_ok"],
    "v1_quality_macd": lambda x: CANDIDATES["v1_quality"](x) and x["macd_pos"],
    "v1_quality_risk": lambda x: CANDIDATES["v1_quality"](x) and x["not_extended"] and x["atr_ok"],
    "kdj_quality": lambda x: CANDIDATES["kdj_cross_trend"](x) and x["macd_pos"] and x["rsi_ok"] and x["not_extended"],
    "ma_quality": lambda x: CANDIDATES["ma_cross_kdj_state"](x) and x["trend60"] and x["ma20_up"] and x["macd_pos"] and x["rsi_ok"],
    "ma_quality_volume": lambda x: CANDIDATES["ma_quality"](x) and x["volume_ok"],
    "ma_quality_risk": lambda x: CANDIDATES["ma_quality"](x) and x["not_extended"] and x["atr_ok"],
    "v1_macd_liquid": lambda x: CANDIDATES["v1_macd"](x) and x["price_ok"] and x["liquid"],
    "v1_macd_market": lambda x: CANDIDATES["v1_macd"](x) and x["spy_risk_on"],
    "v1_macd_liquid_market": lambda x: CANDIDATES["v1_macd_liquid"](x) and x["spy_risk_on"],
    "pullback_quality": lambda x: x["kdj_cross"] and x["trend"] and x["trend_structure"] and x["ma20_up"] and x["macd_pos"] and x["rsi_entry"] and x["near_ma20"] and x["price_ok"] and x["liquid"],
    "pullback_market": lambda x: CANDIDATES["pullback_quality"](x) and x["spy_risk_on"],
    "early_trend": lambda x: x["ma_cross"] and x["kdj_bull"] and x["ma20_up"] and x["macd_rising"] and x["rsi_entry"] and x["price_ok"] and x["liquid"],
    "early_trend_market": lambda x: CANDIDATES["early_trend"](x) and x["spy_risk_on"],
    "breakout_quality": lambda x: x["breakout20"] and x["trend_structure"] and x["ma20_up"] and x["volume_strong"] and x["rsi_ok"] and x["price_ok"] and x["liquid"],
    "breakout_market": lambda x: CANDIDATES["breakout_quality"](x) and x["spy_risk_on"],
}

SELL_CANDIDATES = {
    "s1_current": lambda x: x["ma_cross_down"] and x["kdj_cross_down"],
    "s1_macd": lambda x: SELL_CANDIDATES["s1_current"](x) and x["macd_neg"],
    "s1_below60": lambda x: SELL_CANDIDATES["s1_current"](x) and not x["trend60"],
    "s1_market": lambda x: SELL_CANDIDATES["s1_current"](x) and x["spy_risk_off"],
    "s1_macd_market": lambda x: SELL_CANDIDATES["s1_macd"](x) and x["spy_risk_off"],
    "s_peak_kdj": lambda x: x["kdj_cross_down"] and x["rsi_high"] and x["kdj_was_hot"] and x["below_ma5"],
    "s_peak_extended": lambda x: SELL_CANDIDATES["s_peak_kdj"](x) and x["extended"],
    "s_peak_macd": lambda x: x["macd_cross_down"] and x["rsi_high"] and x["below_ma5"],
    "s_trend_break": lambda x: x["cross_below_ma20"] and x["macd_neg"] and x["below_ma5"],
    "s_trend_break_volume": lambda x: SELL_CANDIDATES["s_trend_break"](x) and x["volume_ok"],
    "s_breakdown": lambda x: x["breakdown20"] and x["macd_neg"] and x["volume_strong"],
    "s_trailing": lambda x: x["retreat5"] and x["cross_below_ma20"] and x["macd_neg"],
}


def metrics(rows: list[dict], predicate, period: str) -> dict:
    selected = [row for row in rows if predicate(row) and (row["date"] < HOLDOUT) == (period == "dev")]
    values = {}
    for horizon in HORIZONS:
        returns = [row[f"r{horizon}"] for row in selected]
        values[horizon] = {
            "n": len(returns),
            "win": sum(value > 0 for value in returns) / len(returns) if returns else 0,
            "avg": sum(returns) / len(returns) if returns else 0,
        }
    return values


if __name__ == "__main__":
    rows = feature_rows(load_rows())
    print(f"feature_rows={len(rows)} cost={COST:.3%} holdout={HOLDOUT}")
    for name, predicate in CANDIDATES.items():
        dev = metrics(rows, predicate, "dev")
        holdout = metrics(rows, predicate, "holdout")
        print(
            name,
            "DEV", " ".join(f"{h}d n={dev[h]['n']} w={dev[h]['win']:.1%} a={dev[h]['avg']:.2%}" for h in HORIZONS),
            "HOLD", " ".join(f"{h}d n={holdout[h]['n']} w={holdout[h]['win']:.1%} a={holdout[h]['avg']:.2%}" for h in HORIZONS),
        )
    for name, predicate in SELL_CANDIDATES.items():
        for period in ("dev", "holdout"):
            selected = [row for row in rows if predicate(row) and (row["date"] < HOLDOUT) == (period == "dev")]
            summary = []
            for horizon in HORIZONS:
                returns = [row[f"raw{horizon}"] for row in selected]
                hit = sum(value < 0 for value in returns) / len(returns) if returns else 0
                average_decline = -sum(returns) / len(returns) if returns else 0
                summary.append(f"{horizon}d n={len(returns)} hit={hit:.1%} decline={average_decline:.2%}")
            print(name, period.upper(), " ".join(summary))
