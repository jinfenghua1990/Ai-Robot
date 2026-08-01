from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Iterable

from .contracts import FactorDefinition


class FactorRegistry:
    def __init__(self, definitions: Iterable[FactorDefinition] = ()) -> None:
        self._items: Dict[str, FactorDefinition] = {}
        for item in definitions:
            self.register(item)

    def register(self, definition: FactorDefinition) -> None:
        if definition.name in self._items:
            raise ValueError(f"duplicate factor: {definition.name}")
        if definition.direction not in (-1, 1):
            raise ValueError(f"direction must be -1 or 1: {definition.name}")
        self._items[definition.name] = definition

    def get(self, name: str) -> FactorDefinition:
        return self._items[name]

    def all(self) -> list[FactorDefinition]:
        return list(self._items.values())

    def production(self) -> list[FactorDefinition]:
        return [item for item in self._items.values() if item.production]

    def export(self) -> list[dict]:
        return [asdict(item) for item in self._items.values()]


def default_registry() -> FactorRegistry:
    definitions = [
        # 1. 市场环境：来自 MarketContext / 当前股票横截面，不使用默认 50 分。
        FactorDefinition("market_up_ratio", "market", "market_context", "上涨家数/有效股票数", ("breadth",), 1, 1, production=True),
        FactorDefinition("market_limit_pressure", "market", "market_context", "(涨停数-跌停数)/(涨停数+跌停数+10)", ("limit_up_count", "limit_down_count"), 1, 1, production=True),
        FactorDefinition("market_index_trend", "market", "market_context", "指数20日收益/趋势代理", ("market_return_20d",), 20, 1, production=True),

        # 2. 板块主线：只使用由个股日线聚合得到的真实横截面统计。
        FactorDefinition("sector_rank", "sector", "sector_context", "sector_return_20d 的横截面排名", ("close", "sector"), 20, 1, production=True),
        FactorDefinition("sector_return_5d", "sector", "sector_context", "行业平均5日收益", ("close", "sector"), 5, 1, production=True),
        FactorDefinition("sector_return_20d", "sector", "sector_context", "行业平均20日收益", ("close", "sector"), 20, 1, production=True),
        FactorDefinition("sector_up_ratio", "sector", "sector_context", "行业内上涨家数比例", ("close", "sector"), 1, 1, production=True),
        FactorDefinition("sector_limit_up", "sector", "sector_context", "行业内涨停家数", ("pct_chg", "sector"), 1, 1, production=True),

        # 3. 个股相对强度。
        FactorDefinition("return_20d", "momentum", "daily_bar", "close[t]/close[t-20]-1", ("close",), 20, 1, production=True),
        FactorDefinition("return_60d", "momentum", "daily_bar", "close[t]/close[t-60]-1", ("close",), 60, 1, production=True),
        FactorDefinition("rs_vs_index_20d", "momentum", "market_context", "stock_return_20d-market_return_20d", ("close", "market_return_20d"), 20, 1, production=True),
        FactorDefinition("sector_relative_20d", "momentum", "sector_context", "stock_return_20d-sector_return_20d", ("close", "sector"), 20, 1, production=True),
        FactorDefinition("rank_in_sector", "momentum", "sector_context", "行业内20日收益排名", ("close", "sector"), 20, 1, production=True),
        FactorDefinition("strength_persistence", "momentum", "daily_bar", "过去20日上涨日比例", ("close",), 20, 1, production=True),

        # 4. 趋势结构：MA 只在 alignment 中统一表达，不重复叠加单条均线分数。
        FactorDefinition("ma_alignment", "trend", "daily_bar", "MA5>MA10>MA20", ("close",), 20, 1, production=True),
        FactorDefinition("ma20_slope", "trend", "daily_bar", "slope(MA20, 5)/close", ("close",), 25, 1, production=True),
        FactorDefinition("new_high_20d", "trend", "daily_bar", "high>=过去20日最高价", ("high",), 20, 1, production=True),
        FactorDefinition("trend_consistency", "trend", "daily_bar", "过去20日上涨日比例", ("close",), 20, 1, production=True),
        FactorDefinition("trend_rsq", "trend", "daily_bar", "Rsquare(close,20)", ("close",), 20, 1, production=True),

        # 5. 量价行为：不把主力资金字段伪装成因子。
        FactorDefinition("volume_ratio_20d", "volume_price", "daily_bar", "volume/mean(volume,20)", ("volume",), 20, 1, production=True),
        FactorDefinition("volume_trend", "volume_price", "daily_bar", "mean(volume,5)/mean(volume,20)", ("volume",), 20, 1, production=True),
        FactorDefinition("price_volume_corr", "volume_price", "daily_bar", "Corr(return,volume,20)", ("close", "volume"), 20, 1, production=True),
        FactorDefinition("up_volume_ratio", "volume_price", "daily_bar", "上涨日成交量/总成交量", ("close", "volume"), 20, 1, production=True),
        FactorDefinition("pullback_volume_shrink", "volume_price", "daily_bar", "回调日均量/前20日均量", ("close", "volume"), 20, -1, production=True),

        # 6. 交易位置。
        FactorDefinition("distance_high_20d", "position", "daily_bar", "close/max(high,20)-1", ("high", "close"), 20, 1, production=True),
        FactorDefinition("distance_ma20", "position", "daily_bar", "-abs(close/MA20-1)", ("close",), 20, 1, production=True),
        # 数值越接近 0 代表离阶段高点越近；深度回撤不能被当成更优位置。
        FactorDefinition("pullback_depth_20d", "position", "daily_bar", "close/max(close,20)-1", ("close",), 20, 1, production=True),
        FactorDefinition("breakout_days", "position", "daily_bar", "距20日新高的交易日数", ("high",), 20, -1, production=True),

        # 7. 风险质量：高分表示风险质量好，综合评分会扣除风险惩罚。
        FactorDefinition("volatility_20d", "risk", "daily_bar", "Std(daily_return,20)", ("close",), 20, -1, production=True),
        FactorDefinition("atr_pct_14d", "risk", "daily_bar", "ATR14/close", ("high", "low", "close"), 14, -1, production=True),
        FactorDefinition("drawdown_60d", "risk", "daily_bar", "close/max(close,60)-1", ("close",), 60, 1, production=True),
        FactorDefinition("overextension_5d", "risk", "daily_bar", "return_5d", ("close",), 5, -1, production=True),
        FactorDefinition("liquidity_amount_20d", "risk", "daily_bar", "mean(amount,20)", ("amount",), 20, 1, production=True),
    ]
    return FactorRegistry(definitions)
