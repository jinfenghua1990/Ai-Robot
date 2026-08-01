from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from statistics import mean, pstdev
from typing import Mapping, Sequence

from .contracts import DailyBar, FactorValue, MarketContext
from .registry import FactorRegistry


def _mean(values: Sequence[float]) -> float:
    return mean(values) if values else 0.0


def _return(closes: Sequence[float], period: int) -> float | None:
    if len(closes) < period + 1 or not closes[-period - 1]:
        return None
    return closes[-1] / closes[-period - 1] - 1


def _slope(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    x_bar = (len(values) - 1) / 2
    y_bar = _mean(values)
    den = sum((i - x_bar) ** 2 for i in range(len(values)))
    return sum((i - x_bar) * (v - y_bar) for i, v in enumerate(values)) / den if den else 0.0


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean, right_mean = _mean(left), _mean(right)
    left_dev = sum((value - left_mean) ** 2 for value in left) ** 0.5
    right_dev = sum((value - right_mean) ** 2 for value in right) ** 0.5
    if not left_dev or not right_dev:
        return None
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (left_dev * right_dev)


def _rsquare(values: Sequence[float]) -> float | None:
    correlation = _correlation(list(range(len(values))), values)
    return correlation * correlation if correlation is not None else None


def _atr_pct(bars: Sequence[DailyBar], period: int = 14) -> float | None:
    if len(bars) < period + 1 or not bars[-1].close:
        return None
    true_ranges = []
    for previous, current in zip(bars[-period - 1:-1], bars[-period:]):
        true_ranges.append(max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        ))
    return _mean(true_ranges) / bars[-1].close


def _pct_change(value: float) -> float:
    """Normalize DailyBar.pct_chg, which may be stored as 10 or 0.10."""
    return value * 100 if abs(value) <= 1 else value


def _limit_up(bar: DailyBar) -> bool:
    return _pct_change(float(bar.pct_chg or 0)) >= 9.5


def _limit_down(bar: DailyBar) -> bool:
    return _pct_change(float(bar.pct_chg or 0)) <= -9.5


def _rank_fraction(values: Sequence[float], target: float) -> float:
    if not values:
        return 0.5
    if len(values) == 1:
        return 0.5
    below = sum(value < target for value in values)
    equal = sum(value == target for value in values)
    return (below + equal / 2) / len(values)


class FactorEngine:
    """Calculate the production V1 factor groups from date-bounded daily bars.

    The engine intentionally accepts an optional MarketContext. When it is
    absent (for unit tests or standalone research), market breadth and 20-day
    return are derived from the visible stock universe. No missing value is
    replaced with a neutral score.
    """

    def __init__(self, registry: FactorRegistry) -> None:
        self.registry = registry

    def calculate(
        self,
        history: Mapping[str, Sequence[DailyBar]],
        trade_date: date,
        market: MarketContext | None = None,
    ) -> list[FactorValue]:
        visible_by_code: dict[str, list[DailyBar]] = {}
        for ts_code, source_bars in history.items():
            visible = sorted((bar for bar in source_bars if bar.trade_date <= trade_date), key=lambda bar: bar.trade_date)
            if visible and visible[-1].trade_date == trade_date:
                visible_by_code[ts_code] = visible

        market_values = self._market_values(visible_by_code, market)
        sector_values = self._sector_values(visible_by_code)
        result: list[FactorValue] = []
        for ts_code, bars in visible_by_code.items():
            values = self._stock_values(ts_code, bars, market_values, sector_values)
            for definition in self.registry.production():
                raw_value = values.get(definition.name)
                valid = raw_value is not None and math.isfinite(float(raw_value))
                result.append(FactorValue(
                    ts_code,
                    trade_date,
                    definition.name,
                    definition.category,
                    float(raw_value) if valid else None,
                    None,
                    valid,
                    "" if valid else "insufficient_or_missing_data",
                ))
        return result

    @staticmethod
    def _market_values(visible_by_code: Mapping[str, Sequence[DailyBar]], market: MarketContext | None) -> dict[str, float | None]:
        latest = [bars[-1] for bars in visible_by_code.values() if bars]
        returns = [value for value in (_return([bar.close for bar in bars], 20) for bars in visible_by_code.values()) if value is not None]
        breadth = market.breadth if market is not None else (
            sum(1 for bars in visible_by_code.values() if len(bars) >= 2 and bars[-1].close > bars[-2].close) / len(latest) if latest else None
        )
        limit_up_count = market.limit_up_count if market is not None else sum(_limit_up(bar) for bar in latest)
        limit_down_count = market.limit_down_count if market is not None else sum(_limit_down(bar) for bar in latest)
        if market is not None and not market.market_data_available and limit_up_count == 0 and limit_down_count == 0:
            limit_up_count = sum(_limit_up(bar) for bar in latest)
            limit_down_count = sum(_limit_down(bar) for bar in latest)
        total_limits = limit_up_count + limit_down_count
        limit_pressure = ((limit_up_count - limit_down_count) / (total_limits + 10)) if total_limits else None
        market_return = market.market_return_20d if market is not None and market.market_return_20d is not None else (_mean(returns) if returns else None)
        return {
            "market_up_ratio": breadth,
            "market_limit_pressure": limit_pressure,
            "market_index_trend": market_return,
            "market_return_20d": market_return,
        }

    @staticmethod
    def _sector_values(visible_by_code: Mapping[str, Sequence[DailyBar]]) -> dict[str, dict[str, float | None]]:
        by_sector: dict[str, dict[str, dict[str, float | None]]] = defaultdict(dict)
        for ts_code, bars in visible_by_code.items():
            sector = bars[-1].sector if bars else ""
            if not sector:
                continue
            closes = [bar.close for bar in bars]
            by_sector[sector][ts_code] = {
                "return_5d": _return(closes, 5),
                "return_20d": _return(closes, 20),
                "up": 1.0 if len(closes) >= 2 and closes[-1] > closes[-2] else 0.0,
                "limit_up": 1.0 if _limit_up(bars[-1]) else 0.0,
            }
        result: dict[str, dict[str, float | None]] = {}
        for sector, stocks in by_sector.items():
            return_5 = [item["return_5d"] for item in stocks.values() if item["return_5d"] is not None]
            return_20 = [item["return_20d"] for item in stocks.values() if item["return_20d"] is not None]
            up_ratio = _mean([float(item["up"]) for item in stocks.values()]) if stocks else None
            limit_up_count = sum(float(item["limit_up"]) for item in stocks.values()) if stocks else None
            for ts_code, item in stocks.items():
                result[ts_code] = {
                    "return_5d": _mean(return_5),
                    "return_20d": _mean(return_20),
                    "up_ratio": up_ratio,
                    "limit_up": limit_up_count,
                    "rank": _rank_fraction(return_20, float(item["return_20d"])) if item["return_20d"] is not None else None,
                }
        return result

    @staticmethod
    def _stock_values(
        ts_code: str,
        bars: Sequence[DailyBar],
        market: Mapping[str, float | None],
        sectors: Mapping[str, Mapping[str, float | None]],
    ) -> dict[str, float | None]:
        latest = bars[-1]
        closes = [bar.close for bar in bars]
        highs = [bar.high for bar in bars]
        volumes = [bar.volume for bar in bars]
        amounts = [bar.amount for bar in bars]
        daily_returns = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
        returns_20 = _return(closes, 20)
        returns_5 = _return(closes, 5)
        returns_60 = _return(closes, 60)
        sector = sectors.get(ts_code, {})
        sector_return_20 = sector.get("return_20d")
        ma20 = _mean(closes[-20:]) if len(closes) >= 20 else None
        ma10 = _mean(closes[-10:]) if len(closes) >= 10 else None
        ma5 = _mean(closes[-5:]) if len(closes) >= 5 else None
        ma20_series = [_mean(closes[index - 19:index + 1]) for index in range(max(19, len(closes) - 5), len(closes))] if len(closes) >= 20 else []
        recent_changes = daily_returns[-20:]
        down_volumes = [bar.volume for previous, bar in zip(bars[-5:-1], bars[-4:]) if bar.close < previous.close]
        prior_volume = _mean(volumes[-25:-5]) if len(volumes) >= 25 else None
        recent_volume = _mean(volumes[-5:]) if len(volumes) >= 5 else None
        high20 = max(highs[-20:]) if len(highs) >= 20 else None
        high60 = max(highs[-60:]) if len(highs) >= 60 else None
        close20 = max(closes[-20:]) if len(closes) >= 20 else None
        close60 = max(closes[-60:]) if len(closes) >= 60 else None
        breakout_days = None
        if len(highs) >= 20:
            window = highs[-20:]
            breakout_days = len(window) - 1 - max(index for index, value in enumerate(window) if value == max(window))
        volume_ratio = volumes[-1] / _mean(volumes[-20:]) if len(volumes) >= 20 and _mean(volumes[-20:]) else None
        return {
            # market
            "market_up_ratio": market.get("market_up_ratio"),
            "market_limit_pressure": market.get("market_limit_pressure"),
            "market_index_trend": market.get("market_index_trend"),
            # sector
            "sector_rank": sector.get("rank"),
            "sector_return_5d": sector.get("return_5d"),
            "sector_return_20d": sector_return_20,
            "sector_up_ratio": sector.get("up_ratio"),
            "sector_limit_up": sector.get("limit_up"),
            # relative strength
            "return_20d": returns_20,
            "return_60d": returns_60,
            "rs_vs_index_20d": returns_20 - market["market_return_20d"] if returns_20 is not None and market.get("market_return_20d") is not None else None,
            "sector_relative_20d": returns_20 - sector_return_20 if returns_20 is not None and sector_return_20 is not None else None,
            "rank_in_sector": sector.get("rank"),
            "strength_persistence": _mean([1.0 if change > 0 else 0.0 for change in recent_changes]) if len(recent_changes) == 20 else None,
            # trend
            "ma_alignment": 1.0 if ma5 is not None and ma10 is not None and ma20 is not None and ma5 > ma10 > ma20 else 0.0 if ma5 is not None and ma10 is not None and ma20 is not None else None,
            "ma20_slope": _slope(ma20_series) / latest.close if len(ma20_series) >= 2 and latest.close else None,
            "new_high_20d": 1.0 if len(highs) >= 21 and highs[-1] >= max(highs[-21:-1]) else 0.0 if len(highs) >= 21 else None,
            "trend_consistency": _mean([1.0 if change > 0 else 0.0 for change in recent_changes]) if len(recent_changes) == 20 else None,
            "trend_rsq": _rsquare(closes[-20:]) if len(closes) >= 20 else None,
            # volume and price
            "volume_ratio_20d": volume_ratio,
            "volume_trend": recent_volume / _mean(volumes[-20:]) if recent_volume is not None and len(volumes) >= 20 and _mean(volumes[-20:]) else None,
            "price_volume_corr": _correlation(recent_changes, volumes[-20:]) if len(recent_changes) == 20 else None,
            "up_volume_ratio": _mean([bar.volume for previous, bar in zip(bars[-20:-1], bars[-19:]) if bar.close > previous.close]) / _mean(volumes[-20:]) if len(bars) >= 20 and _mean(volumes[-20:]) else None,
            "pullback_volume_shrink": _mean(down_volumes) / prior_volume if down_volumes and prior_volume else None,
            # position
            "distance_high_20d": latest.close / high20 - 1 if high20 else None,
            "distance_ma20": -(abs(latest.close / ma20 - 1)) if ma20 else None,
            "pullback_depth_20d": latest.close / close20 - 1 if close20 else None,
            "breakout_days": float(breakout_days) if breakout_days is not None else None,
            # risk quality
            "volatility_20d": pstdev(recent_changes) if len(recent_changes) == 20 else None,
            "atr_pct_14d": _atr_pct(bars),
            "drawdown_60d": latest.close / close60 - 1 if close60 else None,
            "overextension_5d": returns_5,
            "liquidity_amount_20d": _mean(amounts[-20:]) if len(amounts) >= 20 else None,
        }
