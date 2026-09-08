"""Auditable high-confidence filters for the US B/S V2 entry."""
from __future__ import annotations

import hashlib
import itertools
import sys
from collections import defaultdict

sys.path.insert(0, "backend")

from api.us_stock_analysis import (  # noqa: E402
    _adx_series,
    _atr_series,
    _kdj_series,
    _macd_series,
    _rsi_series,
    _sma_fill,
)
from scripts.research_us_bs_trades import exit_index  # noqa: E402
from scripts.research_us_bs_v2 import COST, END, START, load_rows  # noqa: E402


def held_out(symbol: str) -> bool:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16) % 5 == 0


def events():
    grouped = load_rows()
    spy = grouped["SPY"]
    spy_dates = [row[0] for row in spy]
    spy_closes = [row[4] for row in spy]
    spy_ma20, spy_ma60 = _sma_fill(spy_closes, 20), _sma_fill(spy_closes, 60)
    spy_by_date = {}
    for i in range(60, len(spy)):
        spy_by_date[spy_dates[i]] = {
            "market": spy_closes[i] > spy_ma60[i] and spy_ma20[i] > spy_ma60[i] and spy_ma20[i] > spy_ma20[i - 5],
            "mom": spy_closes[i] / spy_closes[i - 20] - 1,
        }

    output = []
    for symbol, data in grouped.items():
        if symbol == "SPY":
            continue
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
        atr = _atr_series(highs, lows, closes)
        adx = _adx_series(highs, lows, closes)
        for i in range(60, len(data) - 32):
            if not START <= dates[i] <= END or dates[i] not in spy_by_date:
                continue
            needed = (
                ma5[i - 1], ma20[i - 1], ma5[i], ma20[i], ma60[i], vol20[i],
                kdj["k"][i - 1], kdj["d"][i - 1], kdj["k"][i], kdj["d"][i],
                macd["hist"][i], macd["dif"][i], rsi[i], atr[i], adx["adx"][i],
                adx["plus_di"][i], adx["minus_di"][i],
            )
            if any(value is None for value in needed):
                continue
            base = (
                closes[i] > ma20[i]
                and ma5[i - 1] <= ma20[i - 1]
                and ma5[i] > ma20[i]
                and kdj["k"][i - 1] <= kdj["d"][i - 1]
                and kdj["k"][i] > kdj["d"][i]
                and macd["hist"][i] > 0
            )
            if not base:
                continue
            found = exit_index("take8_30", i + 1, opens, closes, ma20, kdj, macd)
            if found is None:
                continue
            exit_i, _ = found
            trade_return = opens[exit_i] / opens[i + 1] - 1 - COST
            if abs(trade_return) > 0.8:
                continue
            mom20 = closes[i] / closes[i - 20] - 1
            spy_state = spy_by_date[dates[i]]
            output.append({
                "symbol": symbol,
                "date": dates[i],
                "return": trade_return,
                "market": spy_state["market"],
                "liquid": closes[i] >= 5 and closes[i] * vol20[i] >= 20_000_000,
                "atr5": atr[i] / closes[i] <= 0.05,
                "rsi": 45 <= rsi[i] <= 70,
                "not_extended": closes[i] <= 1.06 * ma20[i],
                "momentum": 0 <= mom20 <= 0.25,
                "adx": adx["adx"][i] >= 20 and adx["plus_di"][i] > adx["minus_di"][i],
                "volume": volumes[i] >= 0.8 * vol20[i],
                "ma20_up": ma20[i] > ma20[i - 5],
                "trend60": closes[i] > ma60[i],
                "dif_positive": macd["dif"][i] > 0,
                "relative_strength": mom20 >= spy_state["mom"],
            })
    return output


def stats(rows):
    if not rows:
        return (0, 0.0, 0.0)
    returns = [row["return"] for row in rows]
    return len(rows), sum(value > 0 for value in returns) / len(rows), sum(returns) / len(rows)


if __name__ == "__main__":
    records = events()
    atoms = ["market", "liquid", "atr5", "rsi", "not_extended", "momentum", "adx", "volume", "ma20_up", "trend60", "dif_positive", "relative_strength"]
    candidates = []
    for size in range(0, 4):
        for combo in itertools.combinations(atoms, size):
            development = [row for row in records if not held_out(row["symbol"]) and all(row[key] for key in combo)]
            if len(development) < 100:
                continue
            by_quarter = defaultdict(list)
            for row in development:
                by_quarter[(row["date"].year, (row["date"].month - 1) // 3)].append(row)
            if min((len(rows) for rows in by_quarter.values()), default=0) < 12:
                continue
            minimum_quarter_win = min(stats(rows)[1] for rows in by_quarter.values())
            dev = stats(development)
            candidates.append((minimum_quarter_win, dev[1], dev[2], combo, dev))
    for _, _, _, combo, dev in sorted(candidates, reverse=True)[:20]:
        validation = [row for row in records if held_out(row["symbol"]) and all(row[key] for key in combo)]
        print(combo or ("base",), "DEV", dev, "SYMBOL_HOLDOUT", stats(validation))
