from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Mapping, Sequence

from .domain import Bar, DimensionScore, MarketContext, Signal
from .factors import DIMENSION_LABELS, FACTOR_BY_NAME, PRODUCTION_FACTORS, calculate_raw


WEIGHTS = {
    "market": 0.10,
    "sector": 0.20,
    "strength": 0.20,
    "trend": 0.15,
    "volume_price": 0.15,
    "position": 0.15,
    "risk_penalty": 0.05,
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 2)


def _percentile(values: Sequence[float], target: float) -> float:
    if len(values) < 2:
        return 50.0
    # ``values`` is sorted once by the caller; avoid an O(N^2) scan when
    # standardising 31 factors across the full market.
    below = bisect_left(values, target)
    equal = bisect_right(values, target) - below
    return 100.0 * (below + equal / 2) / len(values)


def _market_score(name: str, value: float) -> float:
    if name == "market_breadth":
        return _clamp(value * 100)
    if name == "market_limit_balance":
        return _clamp((value + 1) * 50)
    if name == "market_trend_20d":
        return _clamp(50 + value * 500)
    if name == "market_sentiment":
        return _clamp(value * 100)
    return _clamp(value)


def _normalize(raw_values: Mapping[str, Mapping[str, float | None]]) -> dict[str, dict[str, float | None]]:
    pools: dict[str, list[float]] = defaultdict(list)
    for row in raw_values.values():
        for name, value in row.items():
            if value is not None:
                pools[name].append(float(value))
    sorted_pools = {name: sorted(values) for name, values in pools.items()}
    normalized: dict[str, dict[str, float | None]] = {}
    for code, row in raw_values.items():
        normalized[code] = {}
        for name, value in row.items():
            definition = FACTOR_BY_NAME[name]
            if value is None:
                normalized[code][name] = None
                continue
            raw = float(value)
            if definition.category == "market":
                score = _market_score(name, raw)
            elif name in {"sector_rank", "sector_inner_rank"}:
                score = _clamp(raw)
            else:
                score = _percentile(sorted_pools[name], raw)
                if definition.direction < 0:
                    score = 100 - score
            normalized[code][name] = round(score, 4)
    return normalized


class V2Engine:
    """Quant-team style cross-sectional factor decision engine."""

    opportunity_dimensions = ("market", "sector", "strength", "trend", "volume_price", "position")
    all_dimensions = opportunity_dimensions + ("risk",)

    def run(
        self,
        history: Mapping[str, Sequence[Bar]],
        market: MarketContext,
        sector_flow: Mapping[str, Mapping[str, float | None]],
        display_limit: int | None = 50,
        active_factor_names: set[str] | None = None,
        score_mode: str = "RESEARCH",
        include_candidate_factors: bool = False,
    ) -> dict:
        raw = calculate_raw(history, market, sector_flow, include_candidate=include_candidate_factors)
        normalized = _normalize(raw)
        active = set(active_factor_names or FACTOR_BY_NAME)
        dimensions_by_code = {
            code: self._dimensions(code, raw[code], normalized[code], active)
            for code in raw
        }
        signals = []
        for code, dimensions in dimensions_by_code.items():
            bars = history[code]
            resonance = self._resonance(dimensions)
            score = self._factor_score(dimensions)
            patterns = self._patterns(raw[code], bars, active)
            lifecycle = self._lifecycle(dimensions, raw[code])
            state = self._trading_state(dimensions, resonance, patterns, raw[code], market, score_mode)
            reasons = self._reasons(dimensions, resonance, patterns, lifecycle, state, market, score_mode)
            item = Signal(
                code=code,
                name=bars[-1].name or code,
                sector=bars[-1].sector or "未分类",
                trade_date=market.trade_date,
                rank=0,
                factor_score=score,
                dimensions=dimensions,
                resonance_count=resonance["count"],
                resonance_dimensions=resonance["dimensions"],
                failed_dimensions=resonance["failed"],
                resonance_eligible=resonance["eligible"],
                resonance_reason=resonance["reason"],
                patterns=patterns,
                lifecycle=lifecycle,
                trading_state=state,
                signal_valid_until=market.trade_date + timedelta(days=5),
                market_state=market.state,
                reasons=reasons,
                score_mode=score_mode,
            )
            signals.append(item)
        signals.sort(key=lambda item: item.factor_score if item.factor_score is not None else -1, reverse=True)
        for rank, item in enumerate(signals, 1):
            item.rank = rank
        shown = signals[:display_limit] if display_limit is not None else signals
        return {
            "trade_date": market.trade_date,
            "universe_count": len(signals),
            "market": market,
            "raw": raw,
            "normalized": normalized,
            "signals": shown,
            "all_signals": signals,
            "active_factor_names": sorted(active),
            "score_mode": score_mode,
            "production_ready": score_mode == "PRODUCTION",
        }

    def _dimensions(self, code: str, raw: Mapping[str, float | None], normalized: Mapping[str, float | None], active_factor_names: set[str]) -> dict[str, DimensionScore]:
        grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for name, value in normalized.items():
            if value is not None and name in active_factor_names and name in FACTOR_BY_NAME:
                grouped[FACTOR_BY_NAME[name].category].append((name, value))
        result = {}
        for key in self.all_dimensions:
            rows = grouped.get(key, [])
            result[key] = DimensionScore(
                key=key,
                label=DIMENSION_LABELS[key],
                score=round(mean(value for _, value in rows), 2) if rows else None,
                valid=bool(rows),
                factors=[name for name, _ in rows],
                reason="" if rows else "有效因子不足",
            )
        return result

    def _factor_score(self, dimensions: Mapping[str, DimensionScore]) -> float | None:
        positive = []
        for key in self.opportunity_dimensions:
            item = dimensions[key]
            if item.valid and item.score is not None:
                positive.append((item.score, WEIGHTS[key]))
        risk = dimensions["risk"]
        if not positive:
            return None
        # 缺失维度不补 50 分；只对有效维度重标化，透明地保留“有效维度数”。
        usable_weight = sum(weight for _, weight in positive)
        score = sum(value * weight for value, weight in positive) / usable_weight
        if risk.valid and risk.score is not None:
            score -= (100 - risk.score) * WEIGHTS["risk_penalty"]
        return _clamp(score)

    def _resonance(self, dimensions: Mapping[str, DimensionScore]) -> dict:
        confirmed = [
            key for key in self.opportunity_dimensions
            if dimensions[key].valid and dimensions[key].score is not None and dimensions[key].score >= 60
        ]
        failed = [key for key in self.opportunity_dimensions if key not in confirmed]
        trend_ok = "trend" in confirmed
        strength_ok = "strength" in confirmed or "sector" in confirmed
        risk = dimensions["risk"]
        risk_ok = risk.valid and risk.score is not None and risk.score >= 40
        if not risk_ok:
            failed.append("risk")
        reasons = []
        if len(confirmed) < 4:
            reasons.append("有效机会维度不足4个")
        if not trend_ok:
            reasons.append("趋势结构未确认")
        if not strength_ok:
            reasons.append("板块或个股强度未确认")
        if not risk_ok:
            reasons.append("风险闸门未通过")
        return {
            "count": len(confirmed),
            "dimensions": confirmed,
            "failed": failed,
            "eligible": len(confirmed) >= 4 and trend_ok and strength_ok and risk_ok,
            "reason": "通过" if not reasons else "；".join(reasons),
        }

    def _patterns(self, raw: Mapping[str, float | None], bars: Sequence[Bar], active_factor_names: set[str]) -> list[dict]:
        patterns = []
        if {"new_high_20d", "volume_change"}.issubset(active_factor_names) and raw.get("new_high_20d") == 1 and (raw.get("volume_change") or 0) >= 1.15:
            patterns.append({"key": "baihu", "label": "白虎", "text": "趋势突破且成交量确认"})
        elif {"breakout_days", "pullback_depth", "pullback_volume_shrink"}.issubset(active_factor_names) and raw.get("breakout_days") is not None and raw.get("breakout_days") <= 5 and (raw.get("pullback_depth") or -1) >= -0.08 and (raw.get("pullback_volume_shrink") or 2) <= 1:
            patterns.append({"key": "baihu", "label": "白虎", "text": "突破后首次浅回踩、回调缩量"})
        if {"ma_alignment", "trend_continuity", "return_20d"}.issubset(active_factor_names) and (raw.get("ma_alignment") or 0) == 1 and (raw.get("trend_continuity") or 0) >= 0.60 and (raw.get("return_20d") or -1) > 0:
            patterns.append({"key": "qinglong", "label": "青龙", "text": "多头排列、趋势延续"})
        if {"up_volume_ratio", "pullback_volume_shrink", "price_volume_corr"}.issubset(active_factor_names) and (raw.get("up_volume_ratio") or 0) >= 1.0 and (raw.get("pullback_volume_shrink") or 2) <= 1.0 and (raw.get("price_volume_corr") or -1) > 0:
            patterns.append({"key": "zhuque", "label": "朱雀", "text": "上涨放量、回调缩量、量价配合"})
        return patterns

    def _lifecycle(self, dimensions: Mapping[str, DimensionScore], raw: Mapping[str, float | None]) -> str:
        trend = dimensions["trend"].score or 0
        strength = dimensions["strength"].score or 0
        position = dimensions["position"].score or 0
        drawdown = raw.get("drawdown_60d")
        if (drawdown is not None and drawdown <= -0.20) or strength < 25:
            return "退潮"
        if trend >= 78 and strength >= 75:
            return "主升"
        if trend >= 65 and position >= 55:
            return "启动"
        if trend >= 60:
            return "发酵"
        if strength >= 55 and position >= 55:
            return "吸筹"
        return "关注"

    def _trading_state(self, dimensions, resonance, patterns, raw, market: MarketContext, score_mode: str = "PRODUCTION") -> str:
        risk = dimensions["risk"].score
        if not dimensions["risk"].valid or risk is None or risk < 40:
            return "INVALID"
        # Observation scores are useful for research and ranking, but cannot
        # create a formal right-side trigger before production admission.
        if score_mode != "PRODUCTION":
            return "NO_CHASE" if market.state == "WEAK" else "WATCH"
        if market.state == "WEAK":
            return "NO_CHASE"
        overextended = (raw.get("high_position_risk") or 0) >= 1 or ((raw.get("distance_high_20d") or -1) >= -0.015 and (raw.get("return_20d") or 0) > 0.25)
        if overextended:
            return "NO_CHASE"
        if resonance["eligible"] and dimensions["trend"].score is not None and dimensions["trend"].score >= 70 and patterns:
            return "TRIGGERED"
        if resonance["eligible"] or (dimensions["trend"].score or 0) >= 60:
            return "READY"
        return "WATCH"

    def _reasons(self, dimensions, resonance, patterns, lifecycle, state, market, score_mode: str) -> list[str]:
        reasons = [f"市场{market.state}·{market.sentiment}", f"共振{resonance['count']}个机会维度", f"生命周期：{lifecycle}", f"交易状态：{state}"]
        if score_mode != "PRODUCTION":
            reasons.append("评分口径：观察因子研究评分，尚未进入正式生产")
        if patterns:
            reasons.append("形态解释：" + "、".join(item["label"] for item in patterns))
        if resonance["failed"]:
            reasons.append("未通过：" + "、".join(DIMENSION_LABELS.get(key, key) for key in resonance["failed"]))
        return reasons


def serialize_dimension(item: DimensionScore) -> dict:
    return {
        "key": item.key, "label": item.label, "score": item.score,
        "valid": item.valid, "factors": item.factors, "reason": item.reason,
    }


def serialize_signal(item: Signal) -> dict:
    return {
        "code": item.code,
        "name": item.name or item.code,
        "sector": item.sector or "未分类",
        "trade_date": item.trade_date.isoformat(),
        "rank": item.rank,
        "factor_score": item.factor_score,
        "dimensions": {key: serialize_dimension(value) for key, value in item.dimensions.items()},
        "resonance_count": item.resonance_count,
        "resonance_dimensions": item.resonance_dimensions,
        "failed_dimensions": item.failed_dimensions,
        "resonance_eligible": item.resonance_eligible,
        "resonance_reason": item.resonance_reason,
        "patterns": item.patterns,
        "lifecycle": item.lifecycle,
        "trading_state": item.trading_state,
        "signal_valid_until": item.signal_valid_until.isoformat() if item.signal_valid_until else None,
        "market_state": item.market_state,
        "reasons": item.reasons,
        "score_mode": item.score_mode,
        "production_ready": item.score_mode == "PRODUCTION",
    }


def serialize_market(item: MarketContext | None) -> dict | None:
    if item is None:
        return None
    return {
        "trade_date": item.trade_date.isoformat(), "breadth": round(item.breadth, 4),
        "limit_up": item.limit_up, "limit_down": item.limit_down,
        "market_return_20d": item.market_return_20d,
        "sentiment": item.sentiment, "state": item.state, "source": item.source,
    }
