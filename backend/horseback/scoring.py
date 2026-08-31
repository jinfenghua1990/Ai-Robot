"""回马枪 v1.1.5 的日线结构评分与实时入选门槛。

日线结构只读取已落库的 ``stock_daily_kline``；实时行情由任务写入本次
结果后再读取，避免读取接口临时外采或把实时数据伪装成历史日线。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
import re
from statistics import fmean
from typing import Iterable


MIN_HISTORY_BARS = 63
LOOKBACK_DAYS = 10
LIMIT_UP_THRESHOLD_PCT = 9.7
LIVE_RISE_PCT_MIN = 3.0
LIVE_VOLUME_RATIO_MIN = 1.2
# v1.1.6：回撤下限按板型区分——20cm 板单日振幅天然更大，允许更深的整理回撤
PULLBACK_FLOOR_MAIN = -22.0
PULLBACK_FLOOR_20CM = -32.0

_MAIN_BOARD_PREFIXES = ("000", "001", "002", "003", "600", "601", "603", "605")
_GEM_PREFIXES = ("300", "301", "302")
_STAR_PREFIXES = ("688", "689")


@dataclass(frozen=True)
class ScoreOptions:
    min_score: int = 75
    min_consolidation_days: int = 3
    max_consolidation_days: int = 12
    allow_gem: bool = False
    allow_star: bool = False

    def __post_init__(self):
        if not 1 <= self.min_consolidation_days <= 15:
            raise ValueError("整理最少天数必须在 1–15 之间")
        if not 2 <= self.max_consolidation_days <= 20:
            raise ValueError("整理最多天数必须在 2–20 之间")
        if self.min_consolidation_days >= self.max_consolidation_days:
            raise ValueError("整理最少天数必须小于整理最多天数")
        if not 50 <= self.min_score <= 100:
            raise ValueError("预选阈值必须在 50–100 之间")


@dataclass(frozen=True)
class GateOptions:
    """v1.1.6：实时入选门槛可按任务配置（默认与 v1.1.5 固定值一致）。"""

    live_rise_pct_min: float = LIVE_RISE_PCT_MIN
    live_volume_ratio_min: float = LIVE_VOLUME_RATIO_MIN

    def __post_init__(self):
        if not 0 <= self.live_rise_pct_min <= 20:
            raise ValueError("实时涨幅阈值必须在 0–20 之间")
        if not 0 <= self.live_volume_ratio_min <= 20:
            raise ValueError("实时量比阈值必须在 0–20 之间")


@dataclass(frozen=True)
class ScoreMetrics:
    ma20: float
    ma60: float
    ma60_prior: float
    close: float
    pre_limit_rise_pct: float
    pullback_pct: float
    volume_ratio_5_5: float
    ma_convergence_pct: float
    support_distance_pct: float
    close_strength: bool
    pullback_floor: float = PULLBACK_FLOOR_MAIN


def normalize_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper().replace(" ", "")
    match = re.search(r"(?<!\d)(\d{6})(?:\.(SH|SZ|BJ))?(?!\d)", symbol)
    if not match:
        return ""
    code, suffix = match.groups()
    if not suffix:
        suffix = "SH" if code.startswith("6") else "BJ" if code.startswith(("4", "8", "9")) else "SZ"
    return f"{code}.{suffix}"


def is_board_candidate(symbol: str, name: str = "", allow_gem: bool = False, allow_star: bool = False) -> bool:
    """默认仅沪深主板；allow_gem/allow_star 分别放开创业板与科创板；统一剔除 ST/退市。"""
    normalized = normalize_symbol(symbol)
    if not normalized:
        return False
    code, suffix = normalized.split(".", 1)
    expected_suffix = "SH" if code.startswith("6") else "SZ"
    if suffix != expected_suffix:
        return False
    board_ok = (
        code.startswith(_MAIN_BOARD_PREFIXES)
        or (allow_gem and code.startswith(_GEM_PREFIXES))
        or (allow_star and code.startswith(_STAR_PREFIXES))
    )
    if not board_ok:
        return False
    upper_name = str(name or "").upper()
    return "ST" not in upper_name and "退" not in upper_name


def is_main_board_candidate(symbol: str, name: str = "") -> bool:
    """兼容 v1.1.5 口径：仅沪深主板。"""
    return is_board_candidate(symbol, name)


def _component(key: str, label: str, points: int, maximum: int, passed: bool, actual) -> dict:
    if isinstance(actual, float) and not math.isfinite(actual):
        actual = None
    return {
        "key": key,
        "label": label,
        "points": points if passed else 0,
        "max_points": maximum,
        "passed": passed,
        "actual": actual,
    }


def score_metrics(metrics: ScoreMetrics) -> tuple[int, list[dict]]:
    """复刻 v1.1.5 的九项日线结构权重，总分 100。"""

    components = [
        _component("ma20_above_ma60", "20日线在长期均线上方", 18, 18, metrics.ma20 > metrics.ma60, round(metrics.ma20 - metrics.ma60, 4)),
        _component("ma60_rising", "长期均线向上", 12, 12, metrics.ma60 > metrics.ma60_prior, round(metrics.ma60 - metrics.ma60_prior, 4)),
        _component("close_holds_ma20", "收盘守住20日支撑", 10, 10, metrics.close >= metrics.ma20 * 0.98, round((metrics.close / metrics.ma20 - 1) * 100, 2)),
        _component("pre_limit_momentum", "涨停前已有趋势动能", 10, 10, metrics.pre_limit_rise_pct >= 15, round(metrics.pre_limit_rise_pct, 2)),
        _component("pullback", "涨停后回撤幅度合适", 15, 15, metrics.pullback_floor <= metrics.pullback_pct <= -4, round(metrics.pullback_pct, 2)),
        _component("volume_contraction", "整理阶段缩量", 15 if metrics.volume_ratio_5_5 <= 0.85 else 8, 15, metrics.volume_ratio_5_5 <= 1, round(metrics.volume_ratio_5_5, 3)),
        _component("ma_convergence", "5/10/20日线粘合", 12 if metrics.ma_convergence_pct <= 6 else 6, 12, metrics.ma_convergence_pct <= 9, round(metrics.ma_convergence_pct, 2)),
        _component("near_ma20", "价格贴近均线平台", 5, 5, -2 <= metrics.support_distance_pct <= 7, round(metrics.support_distance_pct, 2)),
        _component("close_strength", "当日收盘转强", 3, 3, metrics.close_strength, metrics.close_strength),
    ]
    return sum(item["points"] for item in components), components


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return None


def _number(value) -> float | None:
    try:
        number = float(str(value).replace(",", "").replace("%", ""))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _normalize_bars(rows: Iterable[dict], cutoff: date) -> list[dict]:
    normalized = []
    for row in rows:
        bar_date = _as_date(row.get("date") or row.get("trade_date"))
        if not bar_date or bar_date > cutoff:
            continue
        values = {key: _number(row.get(key)) for key in ("open", "high", "low", "close", "volume", "pct_chg")}
        if any(values[key] is None for key in ("open", "high", "low", "close", "volume")):
            continue
        normalized.append({"date": bar_date, **values})
    normalized.sort(key=lambda item: item["date"])
    return normalized[-80:]


def _base_result(symbol: str, name: str, cutoff: date, bars: list[dict], status: str, failure: str) -> dict:
    return {
        "ts_code": normalize_symbol(symbol) or symbol,
        "name": name,
        "status": status,
        "structure_eligible": False,
        "score": None,
        "as_of_date": cutoff.isoformat(),
        "kline_count": len(bars),
        "hard_failures": [failure],
        "components": [],
        "last_four_closes": [],
        "avg_daily_volume5": None,
    }


def _limit_up_threshold_pct(symbol: str) -> float:
    normalized = normalize_symbol(symbol)
    code = normalized.split(".", 1)[0] if normalized else ""
    return 19.5 if code.startswith(("300", "688")) else LIMIT_UP_THRESHOLD_PCT


def evaluate_candidate(
    symbol: str,
    name: str,
    rows: Iterable[dict],
    as_of_date: date,
    options: ScoreOptions | None = None,
) -> dict:
    """计算 v1.1.5 日线结构；实时入选门槛由 ``apply_realtime_entry_gate`` 处理。"""

    options = options or ScoreOptions()
    cutoff = _as_date(as_of_date)
    if cutoff is None:
        raise ValueError("as_of_date 无效")
    bars = _normalize_bars(rows, cutoff)
    if not is_board_candidate(symbol, name, options.allow_gem, options.allow_star):
        return _base_result(symbol, name, cutoff, bars, "INVALID", "非允许板块（主板/未开放的创业板科创板）或名称包含 ST/退市标记")
    if len(bars) < MIN_HISTORY_BARS:
        return _base_result(symbol, name, cutoff, bars, "INVALID", f"历史日线不足：至少 {MIN_HISTORY_BARS} 根，实际 {len(bars)} 根")

    closes = [row["close"] for row in bars]
    volumes = [row["volume"] for row in bars]
    last_index = len(bars) - 1
    last = bars[-1]
    ma = lambda period, offset=0: fmean(closes[last_index - offset - period + 1:last_index - offset + 1])
    ma5 = ma(5)
    ma10 = ma(10)
    ma20 = ma(20)
    ma60 = ma(60)
    ma60_prior = ma(60, 3)

    limit_threshold_pct = _limit_up_threshold_pct(symbol)
    threshold = limit_threshold_pct / 100
    # 20cm 板（创业板/科创板）回撤下限放宽，其余沿用主板区间
    pullback_floor = PULLBACK_FLOOR_20CM if limit_threshold_pct >= 19.5 else PULLBACK_FLOOR_MAIN
    limit_indexes = [
        index for index in range(1, len(bars))
        if bars[index - 1]["close"] > 0 and bars[index]["close"] / bars[index - 1]["close"] - 1 >= threshold
    ]
    recent_limit_indexes = [index for index in limit_indexes if last_index - index < LOOKBACK_DAYS]
    if not recent_limit_indexes:
        return _base_result(symbol, name, cutoff, bars, "NOT_SELECTED", "日线中未识别到近期涨停")
    limit_index = recent_limit_indexes[-1]
    days_since_limit = last_index - limit_index
    if not options.min_consolidation_days <= days_since_limit <= options.max_consolidation_days:
        return _base_result(
            symbol, name, cutoff, bars, "NOT_SELECTED",
            f"最近涨停距今需为 {options.min_consolidation_days}–{options.max_consolidation_days} 个交易日，实际 {days_since_limit}",
        )

    post_limit = bars[limit_index:last_index + 1]
    post_limit_high = max(row["high"] for row in post_limit)
    post_limit_low = min(row["low"] for row in post_limit[1:])
    pullback_pct = (post_limit_low / post_limit_high - 1) * 100 if post_limit_high else float("inf")
    recent_bars = bars[-5:]
    previous_bars = bars[-10:-5]
    avg_daily_volume5 = fmean(row["volume"] for row in recent_bars)
    previous_volume = fmean(row["volume"] for row in previous_bars)
    volume_ratio = avg_daily_volume5 / previous_volume if previous_volume > 0 else float("inf")
    ma_values = (ma5, ma10, ma20)
    ma_convergence = (max(ma_values) / min(ma_values) - 1) * 100 if min(ma_values) > 0 else float("inf")
    support_distance = (last["close"] / ma20 - 1) * 100 if ma20 else float("inf")
    trigger_price = max(row["high"] for row in recent_bars)
    stop_loss = min(ma20 * 0.97, min(row["low"] for row in recent_bars) * 0.99)
    trend_base = min(row["low"] for row in bars[-45:-20])
    pre_limit_rise = (post_limit_high / trend_base - 1) * 100 if trend_base else float("inf")
    metrics = ScoreMetrics(
        ma20=ma20,
        ma60=ma60,
        ma60_prior=ma60_prior,
        close=last["close"],
        pre_limit_rise_pct=pre_limit_rise,
        pullback_pct=pullback_pct,
        pullback_floor=pullback_floor,
        volume_ratio_5_5=volume_ratio,
        ma_convergence_pct=ma_convergence,
        support_distance_pct=support_distance,
        close_strength=last["close"] > last["open"] and last["close"] >= bars[-2]["close"],
    )
    score, components = score_metrics(metrics)
    failures = []
    if not ma20 > ma60:
        failures.append("20日线未站上长期均线")
    if not ma60 > ma60_prior:
        failures.append("长期均线走平或向下")
    if not last["close"] >= ma20 * 0.98:
        failures.append("收盘跌破20日支撑")
    if not pullback_floor <= pullback_pct <= -4:
        failures.append("回撤幅度不合适")
    if not volume_ratio <= 1:
        failures.append("整理阶段未缩量")
    if not ma_convergence <= 9:
        failures.append("短中期均线发散")
    structure_eligible = score >= options.min_score and not failures

    return {
        "ts_code": normalize_symbol(symbol),
        "name": name,
        "status": "SELECTED" if structure_eligible else "NOT_SELECTED",
        "structure_eligible": structure_eligible,
        "score": min(100, score),
        "as_of_date": last["date"].isoformat(),
        "kline_count": len(bars),
        "last_limit_date": bars[limit_index]["date"].isoformat(),
        "days_since_limit": days_since_limit,
        "close": round(last["close"], 4),
        "pct_chg": round(last["pct_chg"], 4) if last["pct_chg"] is not None else None,
        "ma5": round(ma5, 4),
        "ma10": round(ma10, 4),
        "ma20": round(ma20, 4),
        "ma60": round(ma60, 4),
        "pullback_pct": round(pullback_pct, 4) if math.isfinite(pullback_pct) else None,
        "volume_ratio": round(volume_ratio, 4) if math.isfinite(volume_ratio) else None,
        "ma_convergence_pct": round(ma_convergence, 4) if math.isfinite(ma_convergence) else None,
        "suggested_buy": round(trigger_price, 4),
        "stop_loss": round(stop_loss, 4),
        "hard_failures": failures,
        "components": components,
        "last_four_closes": closes[-4:],
        "avg_daily_volume5": avg_daily_volume5,
    }


def _trading_minutes_at(value, fallback: datetime) -> int:
    match = re.search(r"(?:T|\s)(\d{1,2}):(\d{2})", str(value or ""))
    hour, minute = (int(match.group(1)), int(match.group(2))) if match else (fallback.hour, fallback.minute)
    total = hour * 60 + minute
    if total <= 9 * 60 + 30:
        return 0
    if total <= 11 * 60 + 30:
        return total - (9 * 60 + 30)
    if total < 13 * 60:
        return 120
    if total <= 15 * 60:
        return 120 + total - (13 * 60)
    return 240


def _quote_state(result: dict, price: float) -> str:
    stop_loss = _number(result.get("stop_loss"))
    trigger = _number(result.get("suggested_buy"))
    if stop_loss is not None and price <= stop_loss:
        return "低于止损参考"
    if trigger is not None and price >= trigger:
        return "已触及建议买入"
    return "实时观察"


def apply_realtime_entry_gate(
    result: dict,
    quote: dict | None,
    snapshot_at: datetime,
    gate_options: GateOptions | None = None,
) -> dict:
    """将 iFinD 行情快照应用到日线结构结果，返回最终入选/观察池状态。

    v1.1.6 状态分层：SELECTED=形态达标且盘中触发；WATCHING=形态达标、
    等待盘中触发（对标外部选股器的"预选"层）；NOT_SELECTED=形态未达标。
    """

    options = gate_options or GateOptions()
    updated = dict(result)
    if updated.get("status") == "INVALID":
        updated.update({
            "realtime_price": None,
            "realtime_change_pct": None,
            "realtime_volume_ratio": None,
            "today_ma5": None,
            "first_ma5_break": False,
            "realtime_gate": "日线数据无效",
            "realtime_state": "不适用",
            "realtime_at": snapshot_at,
        })
        return updated

    price = _number((quote or {}).get("price"))
    if price is None:
        updated.update({
            "status": "WATCHING" if updated.get("structure_eligible") else "NOT_SELECTED",
            "realtime_price": None,
            "realtime_change_pct": None,
            "realtime_volume_ratio": None,
            "realtime_open": None,
            "realtime_high": None,
            "realtime_low": None,
            "realtime_volume": None,
            "today_ma5": None,
            "first_ma5_break": False,
            "realtime_gate": "实时行情未返回",
            "realtime_state": "实时行情未返回",
            "realtime_at": snapshot_at,
        })
        return updated

    change_pct = _number(quote.get("change_pct"))
    live_volume = _number(quote.get("volume"))
    average_volume = _number(updated.get("avg_daily_volume5"))
    minutes = _trading_minutes_at(quote.get("at"), snapshot_at)
    volume_ratio = None
    if live_volume is not None and average_volume and average_volume > 0 and minutes >= 15:
        # Tushare ``vol`` 与 iFinD 高频 ``成交量`` 均以手为单位，不再做 100 股换算。
        volume_ratio = live_volume * 240 / (minutes * average_volume)

    last_four = [value for value in updated.get("last_four_closes", []) if _number(value) is not None]
    previous_close = _number(updated.get("close"))
    previous_ma5 = _number(updated.get("ma5"))
    today_ma5 = fmean([float(value) for value in last_four] + [price]) if len(last_four) == 4 else None
    first_ma5_break = bool(
        today_ma5 is not None and previous_close is not None and previous_ma5 is not None
        and previous_close <= previous_ma5 and price > today_ma5
    )
    structure_eligible = bool(updated.get("structure_eligible"))
    rise_qualified = change_pct is not None and change_pct > options.live_rise_pct_min
    volume_qualified = volume_ratio is not None and volume_ratio >= options.live_volume_ratio_min
    gate_parts = [
        "形态达标" if structure_eligible else "形态未达标",
        f"涨幅 {change_pct:.2f}%" if rise_qualified else f"涨幅未超 {options.live_rise_pct_min:g}%",
        f"放量 {volume_ratio:.2f} 倍" if volume_qualified else (f"未放量 {volume_ratio:.2f} 倍" if volume_ratio is not None else "实时量比未就绪"),
        f"首次站上 MA5 {today_ma5:.4f}" if first_ma5_break else "未首次站上 MA5",
    ]
    updated.update({
        "status": (
            "SELECTED" if structure_eligible and rise_qualified and volume_qualified and first_ma5_break
            else "WATCHING" if structure_eligible
            else "NOT_SELECTED"
        ),
        "realtime_price": round(price, 4),
        "realtime_change_pct": round(change_pct, 4) if change_pct is not None else None,
        "realtime_volume_ratio": round(volume_ratio, 4) if volume_ratio is not None else None,
        "realtime_open": _number(quote.get("open")),
        "realtime_high": _number(quote.get("high")),
        "realtime_low": _number(quote.get("low")),
        "realtime_volume": live_volume,
        "today_ma5": round(today_ma5, 4) if today_ma5 is not None else None,
        "first_ma5_break": first_ma5_break,
        "realtime_gate": " · ".join(gate_parts),
        "realtime_state": _quote_state(updated, price),
        "realtime_at": snapshot_at,
    })
    return updated
