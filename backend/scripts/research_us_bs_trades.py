"""Paired B-to-S trade research using next-session open fills."""
from __future__ import annotations

import sys

sys.path.insert(0, "backend")

from api.us_stock_analysis import _atr_series, _kdj_series, _macd_series, _sma_fill  # noqa: E402
from scripts.research_us_bs_v2 import COST, END, HOLDOUT, START, load_rows  # noqa: E402

EXITS = (
    "fixed15", "fixed20", "fixed25", "fixed30", "bracket_8_6", "bracket_10_8",
    "take8_20", "take8_30", "take10_30", "take12_30", "stop8_20", "stop10_30",
    "bracket_8_12_30", "bracket_8_15_30", "bracket_10_10_30",
    "kdj20", "kdj30", "macd30", "ma20_30",
    "hybrid20", "risk20", "trail30",
)


def exit_index(kind, entry_i, opens, closes, ma20, kdj, macd):
    maximum = {"fixed15": 15, "fixed25": 25}.get(
        kind, 20 if kind.endswith("20") or kind in {"bracket_8_6", "bracket_10_8"} else 30
    )
    peak = closes[entry_i]
    for held in range(1, maximum + 1):
        i = entry_i + held
        if i + 1 >= len(closes):
            return None
        peak = max(peak, closes[i])
        kdj_down = kdj["k"][i - 1] >= kdj["d"][i - 1] and kdj["k"][i] < kdj["d"][i]
        macd_down = macd["hist"][i - 1] >= 0 and macd["hist"][i] < 0
        below20 = closes[i - 1] >= ma20[i - 1] and closes[i] < ma20[i]
        close_return = closes[i] / opens[entry_i] - 1
        trailing = closes[i] / peak - 1
        should_exit = held >= maximum
        if kind == "bracket_8_6":
            should_exit |= close_return >= 0.08 or close_return <= -0.06
        elif kind == "bracket_10_8":
            should_exit |= close_return >= 0.10 or close_return <= -0.08
        elif kind == "take8_20":
            should_exit |= close_return >= 0.08
        elif kind == "take8_30":
            should_exit |= close_return >= 0.08
        elif kind == "take10_30":
            should_exit |= close_return >= 0.10
        elif kind == "take12_30":
            should_exit |= close_return >= 0.12
        elif kind == "stop8_20":
            should_exit |= close_return <= -0.08
        elif kind == "stop10_30":
            should_exit |= close_return <= -0.10
        elif kind == "bracket_8_12_30":
            should_exit |= close_return >= 0.08 or close_return <= -0.12
        elif kind == "bracket_8_15_30":
            should_exit |= close_return >= 0.08 or close_return <= -0.15
        elif kind == "bracket_10_10_30":
            should_exit |= close_return >= 0.10 or close_return <= -0.10
        elif kind == "kdj20":
            should_exit |= held >= 3 and kdj_down
        elif kind == "kdj30":
            should_exit |= held >= 5 and kdj_down
        elif kind == "macd30":
            should_exit |= held >= 3 and macd_down
        elif kind == "ma20_30":
            should_exit |= held >= 3 and below20
        elif kind == "hybrid20":
            should_exit |= held >= 5 and (kdj_down or below20)
        elif kind == "risk20":
            should_exit |= (held >= 3 and below20) or close_return <= -0.08
        elif kind == "trail30":
            should_exit |= held >= 5 and (below20 or trailing <= -0.07)
        if should_exit:
            return i + 1, held
    return None


def calculate():
    entry_names = ("base", "macd", "macd_liquid", "macd_atr", "macd_liquid_atr", "macd_market")
    trades = {(entry, exit_name): [] for entry in entry_names for exit_name in EXITS}
    grouped = load_rows()
    spy_state = {}
    if "SPY" in grouped:
        spy = grouped["SPY"]
        spy_closes = [row[4] for row in spy]
        spy_ma20, spy_ma60 = _sma_fill(spy_closes, 20), _sma_fill(spy_closes, 60)
        for i in range(60, len(spy)):
            spy_state[spy[i][0]] = spy_closes[i] > spy_ma60[i] and spy_ma20[i] > spy_ma60[i] and spy_ma20[i] > spy_ma20[i - 5]
    for symbol, data in grouped.items():
        if symbol == "SPY":
            continue
        dates = [row[0] for row in data]
        opens = [row[1] for row in data]
        highs = [row[2] for row in data]
        lows = [row[3] for row in data]
        closes = [row[4] for row in data]
        volumes = [row[5] for row in data]
        ma5, ma20 = _sma_fill(closes, 5), _sma_fill(closes, 20)
        vol20 = _sma_fill(volumes, 20)
        atr = _atr_series(highs, lows, closes)
        kdj = _kdj_series(highs, lows, closes)
        macd = _macd_series(closes)
        for i in range(34, len(data) - 32):
            if not START <= dates[i] <= END:
                continue
            needed = (ma5[i - 1], ma20[i - 1], ma5[i], ma20[i], kdj["k"][i - 1],
                      kdj["d"][i - 1], kdj["k"][i], kdj["d"][i], macd["hist"][i])
            if any(value is None for value in needed):
                continue
            if abs(closes[i] / closes[i - 1] - 1) > 0.35 or abs(opens[i + 1] / closes[i] - 1) > 0.35:
                continue
            base = (
                closes[i] > ma20[i]
                and ma5[i - 1] <= ma20[i - 1]
                and ma5[i] > ma20[i]
                and kdj["k"][i - 1] <= kdj["d"][i - 1]
                and kdj["k"][i] > kdj["d"][i]
            )
            if not base:
                continue
            for entry in entry_names:
                if entry != "base" and macd["hist"][i] <= 0:
                    continue
                if "liquid" in entry and (closes[i] < 5 or closes[i] * vol20[i] < 20_000_000):
                    continue
                if "atr" in entry and atr[i] / closes[i] > 0.06:
                    continue
                if entry == "macd_market" and not spy_state.get(dates[i], False):
                    continue
                for exit_name in EXITS:
                    found = exit_index(exit_name, i + 1, opens, closes, ma20, kdj, macd)
                    if found is None:
                        continue
                    exit_i, held = found
                    trade_return = opens[exit_i] / opens[i + 1] - 1 - COST
                    if abs(trade_return) <= 0.8:
                        trades[(entry, exit_name)].append((dates[i], trade_return, held))
    return trades


def describe(rows):
    if not rows:
        return "n=0"
    returns = [row[1] for row in rows]
    profit_factor = sum(value for value in returns if value > 0) / abs(sum(value for value in returns if value < 0))
    return (
        f"n={len(rows)} win={sum(value > 0 for value in returns) / len(rows):.1%} "
        f"avg={sum(returns) / len(rows):.2%} median={sorted(returns)[len(returns) // 2]:.2%} "
        f"pf={profit_factor:.2f} hold={sum(row[2] for row in rows) / len(rows):.1f}"
    )


if __name__ == "__main__":
    for (entry, exit_name), rows in calculate().items():
        development = [row for row in rows if row[0] < HOLDOUT]
        holdout = [row for row in rows if row[0] >= HOLDOUT]
        print(entry, exit_name, "DEV", describe(development), "HOLD", describe(holdout))
