"""A small, dependency-free implementation of Qlib Alpha158 features.

The V2 app does not import Qlib at runtime.  The formulas below are mapped
from the local Qlib Alpha158 loader and are calculated only from bars visible
on the signal date.  They are deliberately registered as candidate factors;
the lifecycle engine decides whether any can enter the scoring set.
"""

from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Sequence

from .domain import Bar, FactorDefinition


WINDOWS = (5, 10, 20, 30, 60)


def _safe(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1e-12:
        return None
    return _safe(numerator / denominator)


def _slope(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    xbar = (len(values) - 1) / 2
    ybar = mean(values)
    den = sum((index - xbar) ** 2 for index in range(len(values)))
    return _safe(sum((index - xbar) * (value - ybar) for index, value in enumerate(values)) / den) if den else None


def _corr(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean, right_mean = mean(left), mean(right)
    left_sd = sum((value - left_mean) ** 2 for value in left) ** 0.5
    right_sd = sum((value - right_mean) ** 2 for value in right) ** 0.5
    if not left_sd or not right_sd:
        return None
    return _safe(sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (left_sd * right_sd))


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return _safe(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _definition(
    name: str,
    label: str,
    category: str,
    formula: str,
    inputs: tuple[str, ...],
    period: int,
    direction: int,
) -> FactorDefinition:
    return FactorDefinition(
        name=name,
        label=label,
        category=category,
        source="Qlib Alpha158（本地公式映射）",
        formula=formula,
        inputs=inputs,
        period=period,
        direction=direction,
        status="candidate",
    )


def alpha158_definitions() -> list[FactorDefinition]:
    definitions = [
        ("kmid", "K线实体幅度", "volume_price", "($close-$open)/$open", ("open", "close"), 1, 1),
        ("klen", "K线振幅", "volume_price", "($high-$low)/$open", ("open", "high", "low"), 1, -1),
        ("kmid2", "实体占振幅", "volume_price", "($close-$open)/($high-$low+1e-12)", ("open", "high", "low", "close"), 1, 1),
        ("kup", "上影线幅度", "volume_price", "($high-Greater($open,$close))/$open", ("open", "high", "close"), 1, -1),
        ("kup2", "上影线占比", "volume_price", "($high-Greater($open,$close))/($high-$low+1e-12)", ("open", "high", "low", "close"), 1, -1),
        ("klow", "下影线幅度", "volume_price", "(Less($open,$close)-$low)/$open", ("open", "low", "close"), 1, 1),
        ("klow2", "下影线占比", "volume_price", "(Less($open,$close)-$low)/($high-$low+1e-12)", ("high", "open", "low", "close"), 1, 1),
        ("ksft", "K线收盘偏移", "volume_price", "(2*$close-$high-$low)/$open", ("open", "high", "low", "close"), 1, 1),
        ("ksft2", "K线收盘位置", "volume_price", "(2*$close-$high-$low)/($high-$low+1e-12)", ("high", "low", "close"), 1, 1),
        ("open0", "当日开盘相对价", "position", "$open/$close", ("open", "close"), 1, -1),
        ("high0", "当日最高相对价", "position", "$high/$close", ("high", "close"), 1, -1),
        ("low0", "当日最低相对价", "position", "$low/$close", ("low", "close"), 1, 1),
        ("vwap0", "当日均价相对价", "position", "$vwap/$close", ("amount", "volume", "close"), 1, -1),
    ]
    result = [_definition("qlib_alpha158_" + name, label, category, formula, inputs, period, direction) for name, label, category, formula, inputs, period, direction in definitions]

    operators = [
        ("roc", "过去收益反向比", "trend", "Ref($close,{w})/$close", ("close",), -1),
        ("ma", "均线相对价", "trend", "Mean($close,{w})/$close", ("close",), 1),
        ("std", "价格波动率", "risk", "Std($close,{w})/$close", ("close",), -1),
        ("beta", "价格趋势斜率", "trend", "Slope($close,{w})/$close", ("close",), 1),
        ("rsqr", "趋势线性度", "trend", "Rsquare($close,{w})", ("close",), 1),
        ("resi", "趋势回归残差", "risk", "Resi($close,{w})/$close", ("close",), -1),
        ("max", "阶段最高价相对值", "position", "Max($high,{w})/$close", ("high", "close"), -1),
        ("min", "阶段最低价相对值", "position", "Min($low,{w})/$close", ("low", "close"), 1),
        ("qtlu", "价格上分位", "position", "Quantile($close,{w},0.8)/$close", ("close",), -1),
        ("qtld", "价格下分位", "position", "Quantile($close,{w},0.2)/$close", ("close",), 1),
        ("rank", "历史价格分位", "position", "Rank($close,{w})", ("close",), -1),
        ("rsv", "区间位置RSV", "position", "($close-Min($low,{w}))/(Max($high,{w})-Min($low,{w})+1e-12)", ("high", "low", "close"), -1),
        ("imax", "距阶段高点时间", "position", "IdxMax($high,{w})/{w}", ("high",), -1),
        ("imin", "距阶段低点时间", "position", "IdxMin($low,{w})/{w}", ("low",), 1),
        ("imxd", "高低点时间差", "position", "(IdxMax($high,{w})-IdxMin($low,{w}))/{w}", ("high", "low"), -1),
        ("corr", "价格成交量相关", "volume_price", "Corr($close,Log($volume+1),{w})", ("close", "volume"), 1),
        ("cord", "涨跌量变相关", "volume_price", "Corr($close/Ref($close,1),Log($volume/Ref($volume,1)+1),{w})", ("close", "volume"), 1),
        ("cntp", "上涨天数比例", "trend", "Mean($close>Ref($close,1),{w})", ("close",), 1),
        ("cntn", "下跌天数比例", "trend", "Mean($close<Ref($close,1),{w})", ("close",), -1),
        ("cntd", "涨跌天数差", "trend", "CNTP{w}-CNTN{w}", ("close",), 1),
        ("sump", "上涨收益占比", "trend", "上涨收益绝对值占比({w})", ("close",), 1),
        ("sumn", "下跌收益占比", "trend", "下跌收益绝对值占比({w})", ("close",), -1),
        ("sumd", "涨跌收益差", "trend", "上涨与下跌收益差({w})", ("close",), 1),
        ("vma", "成交量均线相对值", "volume_price", "Mean($volume,{w})/($volume+1e-12)", ("volume",), -1),
        ("vstd", "成交量波动率", "risk", "Std($volume,{w})/($volume+1e-12)", ("volume",), -1),
        ("wvma", "成交量加权波动", "risk", "Std(Abs(收益)*$volume,{w})/(Mean(Abs(收益)*$volume,{w})+1e-12)", ("close", "volume"), -1),
        ("vsump", "成交量上涨占比", "volume_price", "成交量上涨绝对值占比({w})", ("volume",), 1),
        ("vsumn", "成交量下跌占比", "volume_price", "成交量下跌绝对值占比({w})", ("volume",), -1),
        ("vsumd", "成交量涨跌差", "volume_price", "成交量上涨与下跌差({w})", ("volume",), 1),
    ]
    for operator, label, category, formula, inputs, direction in operators:
        for window in WINDOWS:
            result.append(_definition(
                f"qlib_alpha158_{operator}{window}",
                f"{label}{window}日",
                category,
                formula.format(w=window),
                inputs,
                window,
                direction,
            ))
    return result


def _price_field(bars: Sequence[Bar], name: str) -> float:
    bar = bars[-1]
    if name == "open":
        return bar.open
    if name == "high":
        return bar.high
    if name == "low":
        return bar.low
    return bar.amount / bar.volume if bar.volume else bar.close


def _window(values: Sequence[float], period: int) -> list[float] | None:
    return list(values[-period:]) if len(values) >= period else None


def _change_window(values: Sequence[float], period: int) -> list[float] | None:
    if len(values) < period + 1:
        return None
    return [values[index] - values[index - 1] for index in range(len(values) - period, len(values))]


def _alpha158_values(bars: Sequence[Bar]) -> dict[str, float | None]:
    if not bars:
        return {}
    latest = bars[-1]
    close = [bar.close for bar in bars]
    high = [bar.high for bar in bars]
    low = [bar.low for bar in bars]
    volume = [bar.volume for bar in bars]
    current_close = latest.close
    result: dict[str, float | None] = {}

    candle_range = latest.high - latest.low
    open_price = latest.open
    upper = latest.high - max(latest.open, latest.close)
    lower = min(latest.open, latest.close) - latest.low
    result.update({
        "qlib_alpha158_kmid": _div(latest.close - latest.open, open_price),
        "qlib_alpha158_klen": _div(latest.high - latest.low, open_price),
        "qlib_alpha158_kmid2": _div(latest.close - latest.open, candle_range),
        "qlib_alpha158_kup": _div(upper, open_price),
        "qlib_alpha158_kup2": _div(upper, candle_range),
        "qlib_alpha158_klow": _div(lower, open_price),
        "qlib_alpha158_klow2": _div(lower, candle_range),
        "qlib_alpha158_ksft": _div(2 * latest.close - latest.high - latest.low, open_price),
        "qlib_alpha158_ksft2": _div(2 * latest.close - latest.high - latest.low, candle_range),
    })
    for field in ("open", "high", "low", "vwap"):
        result[f"qlib_alpha158_{field}0"] = _div(_price_field(bars, field), current_close)

    for period in WINDOWS:
        closes = _window(close, period)
        highs = _window(high, period)
        lows = _window(low, period)
        volumes = _window(volume, period)
        changes = _change_window(close, period)
        volume_changes = _change_window(volume, period)
        if not closes or not highs or not lows or not volumes:
            for operator in ("roc", "ma", "std", "beta", "rsqr", "resi", "max", "min", "qtlu", "qtld", "rank", "rsv", "imax", "imin", "imxd", "corr", "cord", "cntp", "cntn", "cntd", "sump", "sumn", "sumd", "vma", "vstd", "wvma", "vsump", "vsumn", "vsumd"):
                result[f"qlib_alpha158_{operator}{period}"] = None
            continue
        lagged_close = close[-period - 1] if len(close) >= period + 1 else None
        result[f"qlib_alpha158_roc{period}"] = _div(lagged_close, current_close)
        result[f"qlib_alpha158_ma{period}"] = _div(mean(closes), current_close)
        result[f"qlib_alpha158_std{period}"] = _div(pstdev(closes), current_close)
        slope = _slope(closes)
        result[f"qlib_alpha158_beta{period}"] = _div(slope, current_close)
        if slope is None:
            result[f"qlib_alpha158_rsqr{period}"] = None
            result[f"qlib_alpha158_resi{period}"] = None
        else:
            xbar = (period - 1) / 2
            ybar = mean(closes)
            intercept = ybar - slope * xbar
            fitted = [intercept + slope * index for index in range(period)]
            total = sum((value - ybar) ** 2 for value in closes)
            residual = closes[-1] - fitted[-1]
            result[f"qlib_alpha158_rsqr{period}"] = _safe(1 - sum((actual - predicted) ** 2 for actual, predicted in zip(closes, fitted)) / total) if total else 0.0
            result[f"qlib_alpha158_resi{period}"] = _div(residual, current_close)
        result[f"qlib_alpha158_max{period}"] = _div(max(highs), current_close)
        result[f"qlib_alpha158_min{period}"] = _div(min(lows), current_close)
        result[f"qlib_alpha158_qtlu{period}"] = _div(_quantile(closes, 0.8), current_close)
        result[f"qlib_alpha158_qtld{period}"] = _div(_quantile(closes, 0.2), current_close)
        result[f"qlib_alpha158_rank{period}"] = _safe((sum(value < current_close for value in closes) + 0.5 * sum(value == current_close for value in closes)) / period)
        range_value = max(highs) - min(lows)
        result[f"qlib_alpha158_rsv{period}"] = _div(current_close - min(lows), range_value)
        max_index = max(index for index, value in enumerate(highs) if value == max(highs))
        min_index = max(index for index, value in enumerate(lows) if value == min(lows))
        idx_max = (period - 1 - max_index) / period
        idx_min = (period - 1 - min_index) / period
        result[f"qlib_alpha158_imax{period}"] = _safe(idx_max)
        result[f"qlib_alpha158_imin{period}"] = _safe(idx_min)
        result[f"qlib_alpha158_imxd{period}"] = _safe(idx_max - idx_min)
        log_volume = [math.log(max(value, 0.0) + 1.0) for value in volumes]
        result[f"qlib_alpha158_corr{period}"] = _corr(closes, log_volume)
        if changes and volume_changes:
            close_ratios = [close[index] / close[index - 1] for index in range(len(close) - period, len(close)) if close[index - 1]]
            volume_ratios = [math.log(max(volume[index] / volume[index - 1], 0.0) + 1.0) for index in range(len(volume) - period, len(volume)) if volume[index - 1]]
            result[f"qlib_alpha158_cord{period}"] = _corr(close_ratios, volume_ratios) if len(close_ratios) == len(volume_ratios) else None
            positive_changes = [value for value in changes if value > 0]
            negative_changes = [-value for value in changes if value < 0]
            absolute_changes = sum(abs(value) for value in changes)
            result[f"qlib_alpha158_cntp{period}"] = sum(value > 0 for value in changes) / period
            result[f"qlib_alpha158_cntn{period}"] = sum(value < 0 for value in changes) / period
            result[f"qlib_alpha158_cntd{period}"] = result[f"qlib_alpha158_cntp{period}"] - result[f"qlib_alpha158_cntn{period}"]
            result[f"qlib_alpha158_sump{period}"] = _div(sum(positive_changes), absolute_changes)
            result[f"qlib_alpha158_sumn{period}"] = _div(sum(negative_changes), absolute_changes)
            result[f"qlib_alpha158_sumd{period}"] = _div(sum(positive_changes) - sum(negative_changes), absolute_changes)
        else:
            for operator in ("cord", "cntp", "cntn", "cntd", "sump", "sumn", "sumd"):
                result[f"qlib_alpha158_{operator}{period}"] = None
        result[f"qlib_alpha158_vma{period}"] = _div(mean(volumes), latest.volume)
        result[f"qlib_alpha158_vstd{period}"] = _div(pstdev(volumes), latest.volume)
        if changes:
            weighted = [abs(changes[index]) * volume[len(volume) - period + index] for index in range(period)]
            result[f"qlib_alpha158_wvma{period}"] = _div(pstdev(weighted), mean(weighted)) if weighted else None
        else:
            result[f"qlib_alpha158_wvma{period}"] = None
        if volume_changes:
            positive_volume = [value for value in volume_changes if value > 0]
            negative_volume = [-value for value in volume_changes if value < 0]
            absolute_volume = sum(abs(value) for value in volume_changes)
            result[f"qlib_alpha158_vsump{period}"] = _div(sum(positive_volume), absolute_volume)
            result[f"qlib_alpha158_vsumn{period}"] = _div(sum(negative_volume), absolute_volume)
            result[f"qlib_alpha158_vsumd{period}"] = _div(sum(positive_volume) - sum(negative_volume), absolute_volume)
        else:
            result[f"qlib_alpha158_vsump{period}"] = None
            result[f"qlib_alpha158_vsumn{period}"] = None
            result[f"qlib_alpha158_vsumd{period}"] = None
    return result


calculate_alpha158 = _alpha158_values
ALPHA158_FACTOR_NAMES = frozenset(item.name for item in alpha158_definitions())
