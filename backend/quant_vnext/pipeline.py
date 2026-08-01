from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

from .contracts import DailyBar, MarketContext, SignalSnapshot
from .engine import FactorEngine
from .market_regime import MarketRegimeEngine
from .registry import default_registry
from .resonance import ResonanceEngine
from .scoring import CrossSectionScorer
from .state import lifecycle_state, trading_state
from .universe import build_universe


class QuantPipeline:
    """独立的全新选股闭环；不依赖旧 strategies/analyzers/services。"""

    def __init__(self) -> None:
        self.registry = default_registry()
        self.factors = FactorEngine(self.registry)
        self.scorer = CrossSectionScorer()
        self.resonance = ResonanceEngine()
        self.market_regime = MarketRegimeEngine()

    def run(self, history: Mapping[str, Sequence[DailyBar]], trade_date: date, market: MarketContext) -> list[SignalSnapshot]:
        if market.trade_date != trade_date:
            raise ValueError("market context date mismatch")
        universe = build_universe(history, trade_date, market)
        values = self.factors.calculate(universe, trade_date, market)
        return self._score_values(values, trade_date, market)

    def run_with_values(self, history: Mapping[str, Sequence[DailyBar]], trade_date: date, market: MarketContext):
        if market.trade_date != trade_date:
            raise ValueError("market context date mismatch")
        universe = build_universe(history, trade_date, market)
        values = self.factors.calculate(universe, trade_date, market)
        return values, self._score_values(values, trade_date, market)

    def _score_values(self, values, trade_date: date, market: MarketContext):
        regime = self.market_regime.assess(market)
        scores = self.scorer.score(values, self.registry)
        snapshots = []
        for ts_code, dimensions in scores.items():
            resonance = self.resonance.evaluate(dimensions)
            factor_score = self.scorer.factor_score(dimensions, regime.weights)
            lifecycle = lifecycle_state(dimensions)
            state = trading_state(dimensions, resonance.eligible, regime.state, regime.allow_new_positions)
            reasons = [f"resonance={resonance.count}", f"lifecycle={lifecycle}", f"state={state}", f"market={regime.state}", regime.reason]
            snapshots.append(SignalSnapshot(
                ts_code, trade_date, factor_score, dimensions, resonance, lifecycle, state, reasons,
                regime.state, regime.weights,
            ))
        return sorted(snapshots, key=lambda x: x.factor_score if x.factor_score is not None else -1, reverse=True)
