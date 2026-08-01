"""Market regime assessment and dynamic factor-weight scheduling."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import MarketContext


@dataclass(frozen=True)
class MarketRegime:
    state: str
    score: float
    weights: dict[str, float]
    allow_new_positions: bool
    reason: str


class MarketRegimeEngine:
    """Turn market breadth into a regime, not a binary strategy switch."""

    BASE_WEIGHTS = {
        "market": 0.10,
        "sector": 0.20,
        "strength": 0.20,
        "trend": 0.15,
        "volume_price": 0.15,
        "position": 0.15,
        "risk_penalty": 0.05,
    }

    def assess(self, market: MarketContext) -> MarketRegime:
        breadth = max(0.0, min(1.0, float(market.breadth)))
        limit_balance = self._limit_balance(market)
        trend = market.market_return_20d
        trend_component = 0.5 if trend is None else max(0.0, min(1.0, 0.5 + float(trend) * 5.0))
        score = round((breadth * 0.60 + (limit_balance * 0.5 + 0.5) * 0.20 + trend_component * 0.20) * 100, 2)

        if breadth >= 0.70 and limit_balance >= 0 and trend_component >= 0.50:
            return MarketRegime("STRONG", score, {
                "market": 0.10, "sector": 0.20, "strength": 0.25,
                "trend": 0.20, "volume_price": 0.10, "position": 0.10,
                "risk_penalty": 0.05,
            }, True, "上涨家数占优，趋势与强度优先；降低追高位置权重")
        if breadth < 0.30 or limit_balance <= -0.35 or trend_component <= 0.30:
            return MarketRegime("WEAK", score, {
                "market": 0.10, "sector": 0.15, "strength": 0.10,
                "trend": 0.10, "volume_price": 0.10, "position": 0.15,
                "risk_penalty": 0.30,
            }, False, "市场宽度或涨跌停结构恶化；禁止新开仓并提高风险惩罚")
        return MarketRegime("RANGE", score, {
            "market": 0.10, "sector": 0.20, "strength": 0.15,
            "trend": 0.10, "volume_price": 0.20, "position": 0.20,
            "risk_penalty": 0.05,
        }, True, "市场处于震荡区间；回踩位置和量价确认优先")

    @staticmethod
    def _limit_balance(market: MarketContext) -> float:
        total = market.limit_up_count + market.limit_down_count
        if total <= 0:
            return 0.0
        return (market.limit_up_count - market.limit_down_count) / total
