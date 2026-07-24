from __future__ import annotations

import json
import uuid
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Optional

from ._utils import as_text, clamp, mean, safe_dict, safe_list, to_float, to_int, unique_by_name
from .rotation_engine import build_rotation_context

try:
    from api.hermes_native.db_connector import execute_query
except Exception:
    execute_query = None

SECRET_KEYS = {
    "api_key",
    "api_secret",
    "access_token",
    "password",
    "secret",
    "token",
    "app_secret",
}

POSITION_GUIDANCE = {
    "冰点": "2~3成",
    "修复": "4成",
    "发酵": "6成",
    "高潮": "7成",
    "分歧": "4~5成",
    "退潮": "3成",
}

STAGE_DESCRIPTIONS = {
    "冰点": "短线情绪偏弱，资金仍在等待方向。",
    "修复": "市场进入试探性修复，承接开始出现。",
    "发酵": "主线扩散中，资金开始向核心方向集中。",
    "高潮": "强势主线集中爆发，赚钱效应升温。",
    "分歧": "高位分歧加剧，强弱切换明显。",
    "退潮": "短线情绪回落，风险释放阶段。",
}


def _now_str() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def _normalize_date(value: Any) -> str:
    if value in (None, "", []):
        return datetime.now().strftime("%Y-%m-%d")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _normalize_key(text: Any) -> str:
    return "".join(ch for ch in str(text or "").strip().lower() if ch.isalnum() or ch in {"_", "-", " "}).replace(" ", "")


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _redact_mapping(item)
        return redacted
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    return value


def _coerce_float_list(values: Any) -> list[float]:
    result: list[float] = []
    for item in safe_list(values):
        parsed = to_float(item, None)
        if parsed is not None:
            result.append(parsed)
    return result


def _money_to_yi(value: Any) -> Optional[float]:
    parsed = to_float(value, None)
    if parsed is None:
        return None
    return round(parsed / 100000000.0, 2)


def _normalize_capital_flow_timeline(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        timeline: dict[str, float] = {}
        for key, item in value.items():
            parsed = to_float(item, None)
            if parsed is None:
                continue
            timeline[str(key)] = round(parsed, 2)
        return timeline

    if isinstance(value, list):
        timeline: dict[str, float] = {}
        for index, item in enumerate(value):
            if isinstance(item, dict):
                label = str(item.get("t") or item.get("time") or item.get("label") or item.get("x") or index)
                parsed = to_float(item.get("v") or item.get("value") or item.get("amount") or item.get("flow"), None)
            else:
                label = str(index)
                parsed = to_float(item, None)
            if parsed is None:
                continue
            timeline[label] = round(parsed, 2)
        return timeline

    return {}


def _query_rows(sql: str, params: Optional[tuple[Any, ...]] = None) -> list[dict[str, Any]]:
    if execute_query is None:
        return []
    try:
        rows = execute_query(sql, params or ())
    except Exception:
        return []
    return [dict(row) for row in rows]


def _join_names(items: list[dict[str, Any]], limit: int = 3) -> str:
    names = [as_text(item.get("name"), default="") for item in items[:limit]]
    names = [name for name in names if name]
    return "、".join(names) if names else "暂无明显主线"


def _build_history_snapshot(history_map: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    history_map = safe_dict(history_map)
    snapshot: dict[str, Any] = {}
    for key, values in history_map.items():
        series = _coerce_float_list(values)
        if not series:
            continue
        delta = series[-1] - series[0] if len(series) > 1 else 0.0
        recent_delta = series[-1] - series[-2] if len(series) > 1 else 0.0
        snapshot[str(key)] = {
            "points": len(series),
            "first": round(series[0], 2),
            "last": round(series[-1], 2),
            "delta": round(delta, 2),
            "recent_delta": round(recent_delta, 2),
            "trend": "up" if delta > 0 else "down" if delta < 0 else "flat",
            "avg": round(mean(series, 0.0), 2),
        }
    return snapshot


def _derive_capital_migration(sector_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows = [dict(row) for row in safe_list(sector_rows) if isinstance(row, dict)]
    if not rows:
        return {"outflow_from": [], "inflow_to": []}

    def flow_score(item: Mapping[str, Any]) -> float:
        capital = to_float(item.get("capital_flow_yi"), None)
        if capital is not None:
            return float(capital)
        return to_float(item.get("score") or item.get("strength") or item.get("heat_score"), 0.0) or 0.0

    ordered = sorted(rows, key=flow_score)

    def pack(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "sector_name": as_text(item.get("name"), default="数据暂缺"),
            "heat_score": item.get("score") or item.get("strength") or item.get("heat_score"),
            "capital_flow_yi": item.get("capital_flow_yi"),
            "capital_flow_timeline": deepcopy(safe_dict(item.get("capital_flow_timeline"))),
        }

    return {
        "outflow_from": [pack(item) for item in ordered[:2]],
        "inflow_to": [pack(item) for item in ordered[-2:][::-1]],
    }


def _lookup_history_series(history_map: Optional[Mapping[str, Any]], sector_name: str) -> list[float]:
    history_map = safe_dict(history_map)
    if not history_map or not sector_name:
        return []
    normalized_target = _normalize_key(sector_name)
    for key, values in history_map.items():
        if _normalize_key(key) == normalized_target:
            return _coerce_float_list(values)
    return []


def _extract_market_metrics_from_upstream(upstream_context: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    upstream_context = safe_dict(upstream_context)
    market = safe_dict(upstream_context.get("market"))
    indices = safe_list(market.get("indices"))
    index_map: dict[str, Optional[float]] = {}
    for item in indices:
        if not isinstance(item, dict):
            continue
        name = as_text(item.get("name"), default="")
        change = to_float(item.get("change"), None)
        if name:
            index_map[name] = change

    limit = safe_dict(market.get("limit_up"))
    breadth = safe_dict(market.get("breadth"))
    limit_up = max(to_int(limit.get("limit_up"), 0) or 0, 0)
    broken = max(to_int(limit.get("broken"), 0) or 0, 0)
    limit_down = max(to_int(limit.get("limit_down"), 0) or 0, 0)
    up = max(to_int(breadth.get("up"), 0) or 0, 0)
    down = max(to_int(breadth.get("down"), 0) or 0, 0)

    advance_rate = None
    total_breadth = up + down
    if total_breadth > 0:
        advance_rate = round(up / total_breadth * 100.0, 2)

    return {
        "trade_date": upstream_context.get("resolved_date") or upstream_context.get("date"),
        "sh_index_change": index_map.get("上证指数"),
        "sz_index_change": index_map.get("深证成指"),
        "cyb_index_change": index_map.get("创业板指"),
        "limit_up_total": limit_up,
        "failed_bar_rate": round(broken / limit_up, 4) if limit_up else 0.0,
        "max_series_boards": max(
            to_int(item.get("consecutive_days") or item.get("series") or item.get("board_count"), 0) or 0
            for item in safe_list(upstream_context.get("themes", {}).get("mainline")) + safe_list(upstream_context.get("themes", {}).get("watch")) + safe_list(upstream_context.get("themes", {}).get("alive"))
        ) if safe_list(upstream_context.get("themes", {}).get("mainline")) or safe_list(upstream_context.get("themes", {}).get("watch")) or safe_list(upstream_context.get("themes", {}).get("alive")) else 0,
        "limit_down_total": limit_down,
        "advance_rate": advance_rate,
        "market_heat": to_float(safe_dict(market.get("heat")).get("value"), None),
    }


def _extract_sector_rows_from_upstream(upstream_context: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    upstream_context = safe_dict(upstream_context)
    themes = safe_dict(upstream_context.get("themes"))
    rows: list[dict[str, Any]] = []
    for group_name in ("mainline", "watch", "alive"):
        for item in safe_list(themes.get(group_name)):
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "sector_name": item.get("name") or item.get("leader") or "数据暂缺",
                    "avg_change": item.get("change"),
                    "up_count": None,
                    "down_count": None,
                    "limit_up_count": None,
                    "limit_down_count": None,
                    "volume_ratio": item.get("strength"),
                    "leading_stock": item.get("leader"),
                    "leading_change": None,
                    "capital_flow": None,
                    "capital_flow_timeline": _normalize_capital_flow_timeline(
                        item.get("capital_flow_timeline") or item.get("capital_flow_series") or item.get("capital_timeline")
                    ),
                    "state": group_name,
                    "source_state": group_name,
                    "source_from": "upstream",
                }
            )
    return rows


def _sector_signal_text(row: Mapping[str, Any], history_series: list[float]) -> list[str]:
    reasons: list[str] = []
    change = to_float(row.get("avg_change") or row.get("change_pct") or row.get("pct_chg"), None)
    up_count = max(to_int(row.get("up_count"), 0) or 0, 0)
    down_count = max(to_int(row.get("down_count"), 0) or 0, 0)
    limit_up = max(to_int(row.get("limit_up_count"), 0) or 0, 0)
    limit_down = max(to_int(row.get("limit_down_count"), 0) or 0, 0)
    volume_ratio = to_float(row.get("volume_ratio"), None)
    capital_flow = _money_to_yi(row.get("capital_flow"))
    leading_change = to_float(row.get("leading_change"), None)

    if change is not None:
        reasons.append(f"板块涨幅 {change:+.2f}%")
    if up_count or down_count:
        reasons.append(f"涨跌结构 {up_count}/{down_count}")
    if limit_up or limit_down:
        reasons.append(f"涨停/跌停 {limit_up}/{limit_down}")
    if volume_ratio is not None:
        reasons.append(f"量比 {volume_ratio:.2f}")
    if capital_flow is not None:
        reasons.append(f"资金净流 {capital_flow:+.2f} 亿")
    if leading_change is not None:
        reasons.append(f"龙头涨幅 {leading_change:+.2f}%")
    if history_series:
        delta = history_series[-1] - history_series[0] if len(history_series) > 1 else 0.0
        reasons.append(f"历史动量 {delta:+.2f}")
    return reasons


def _score_sector(row: Mapping[str, Any], history_series: list[float]) -> tuple[float, dict[str, Any]]:
    name = as_text(row.get("sector_name") or row.get("name") or row.get("board_name") or row.get("theme_name"))
    change = to_float(row.get("avg_change") or row.get("change_pct") or row.get("pct_chg"), 0.0) or 0.0
    up_count = max(to_int(row.get("up_count"), 0) or 0, 0)
    down_count = max(to_int(row.get("down_count"), 0) or 0, 0)
    limit_up = max(to_int(row.get("limit_up_count"), 0) or 0, 0)
    limit_down = max(to_int(row.get("limit_down_count"), 0) or 0, 0)
    volume_ratio = to_float(row.get("volume_ratio"), 1.0) or 1.0
    capital_flow = _money_to_yi(row.get("capital_flow")) or 0.0
    leading_change = to_float(row.get("leading_change"), 0.0) or 0.0
    leading_stock = as_text(row.get("leading_stock"), default="数据暂缺")

    history_delta = 0.0
    history_recent = 0.0
    history_avg = None
    if history_series:
        history_delta = history_series[-1] - history_series[0] if len(history_series) > 1 else 0.0
        history_recent = history_series[-1] - history_series[-2] if len(history_series) > 1 else 0.0
        history_avg = mean(history_series, 0.0)

    score = 50.0
    score += clamp(change * 7.5, -28.0, 28.0)
    score += clamp((volume_ratio - 1.0) * 12.0, -12.0, 18.0)
    score += clamp((up_count - down_count) * 0.55, -15.0, 15.0)
    score += clamp(limit_up * 2.2 - limit_down * 2.0, -10.0, 14.0)
    score += clamp(capital_flow * 0.8, -12.0, 12.0)
    score += clamp(history_delta * 0.6, -8.0, 8.0)
    score += clamp(history_recent * 0.9, -5.0, 5.0)
    score += clamp(leading_change * 1.2, -8.0, 8.0)
    if history_avg is not None:
        score += clamp((history_series[-1] - history_avg) * 0.3, -4.0, 4.0)
    if leading_change >= 5:
        score += 4.0
    elif leading_change <= -5:
        score -= 4.0

    score = clamp(score, 0.0, 100.0)

    if score >= 70 and change >= 0:
        state = "mainline"
        judgment = "主升延续，资金仍在核心板块。"
    elif score >= 50:
        state = "watch"
        judgment = "热度足够，仍在主线确认区。"
    elif score >= 30:
        state = "alive"
        judgment = "有轮动热度，适合盯补涨。"
    else:
        state = "alive"
        judgment = "偏防守观察位，等进一步确认。"

    item = {
        "name": name,
        "change": round(change, 2) if row.get("avg_change") is not None or row.get("change_pct") is not None or row.get("pct_chg") is not None else None,
        "strength": int(round(score)),
        "leader": leading_stock,
        "hot": int(round(score)),
        "state": state,
        "judgment": judgment,
        "score": round(score, 2),
        "reasons": _sector_signal_text(row, history_series),
        "history_series": [round(value, 2) for value in history_series[-20:]] if history_series else [],
        "history": {
            "points": len(history_series),
            "delta": round(history_delta, 2),
            "recent_delta": round(history_recent, 2),
            "avg": round(history_avg, 2) if history_avg is not None else None,
        } if history_series else {},
        "volume_ratio": round(volume_ratio, 2) if row.get("volume_ratio") is not None else None,
        "capital_flow_yi": round(capital_flow, 2) if row.get("capital_flow") is not None else None,
        "capital_flow_timeline": _normalize_capital_flow_timeline(
            row.get("capital_flow_timeline") or row.get("capital_flow_series") or row.get("capital_timeline")
        ),
        "leading_change": round(leading_change, 2) if row.get("leading_change") is not None else None,
        "up_count": up_count,
        "down_count": down_count,
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "source_type": "sector",
    }
    return score, item


def _build_sector_matrix(
    today_sectors: list[dict[str, Any]] | None,
    history_map: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in safe_list(today_sectors)]
    candidates: list[dict[str, Any]] = []
    for row in rows:
        sector_name = as_text(row.get("sector_name") or row.get("name") or row.get("board_name") or row.get("theme_name"), default="")
        history_series = _lookup_history_series(history_map, sector_name)
        _, item = _score_sector(row, history_series)
        upstream_state = as_text(row.get("state") or row.get("source_state"), default="")
        if upstream_state in {"mainline", "watch", "alive"}:
            item["state"] = upstream_state
        candidates.append(item)

    candidates.sort(key=lambda item: (item.get("score") or 0, item.get("change") or 0), reverse=True)
    candidates = unique_by_name(candidates)

    mainline = [item for item in candidates if item.get("state") == "mainline"][:3]
    watch = [item for item in candidates if item.get("state") == "watch" and item not in mainline][:3]
    alive = [item for item in candidates if item.get("state") == "alive" and item not in mainline and item not in watch][:3]

    if not mainline and candidates:
        mainline = candidates[:1]
    if not watch and len(candidates) > len(mainline):
        watch = [item for item in candidates if item not in mainline][:2]
    if not alive and len(candidates) > len(mainline) + len(watch):
        alive = [item for item in candidates if item not in mainline and item not in watch][:3]

    drivers = {
        "mainline": [
            {
                "name": item["name"],
                "score": item["score"],
                "leader": item["leader"],
                "judgment": item["judgment"],
                "reasons": item.get("reasons", []),
            }
            for item in mainline[:3]
        ],
        "watch": [
            {
                "name": item["name"],
                "score": item["score"],
                "leader": item["leader"],
                "judgment": item["judgment"],
                "reasons": item.get("reasons", []),
            }
            for item in watch[:3]
        ],
        "alive": [
            {
                "name": item["name"],
                "score": item["score"],
                "leader": item["leader"],
                "judgment": item["judgment"],
                "reasons": item.get("reasons", []),
            }
            for item in alive[:3]
        ],
    }

    signals: list[str] = []
    if mainline:
        signals.append(f"主线数量 {len(mainline)}")
    if watch:
        signals.append(f"观察方向 {len(watch)} 个")
    if alive:
        signals.append(f"活口方向 {len(alive)} 个")

    return {
        "mainline": mainline,
        "watch": watch,
        "alive": alive,
        "signals": signals,
        "drivers": drivers,
        "all": candidates,
    }


def _build_stage_context(market_metrics: Optional[Mapping[str, Any]], sector_matrix: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    market_metrics = safe_dict(market_metrics)
    sector_matrix = safe_dict(sector_matrix)

    sh_change = to_float(market_metrics.get("sh_index_change"), None)
    sz_change = to_float(market_metrics.get("sz_index_change"), None)
    cyb_change = to_float(market_metrics.get("cyb_index_change"), None)
    limit_up_total = max(to_int(market_metrics.get("limit_up_total"), 0) or 0, 0)
    failed_bar_rate = to_float(market_metrics.get("failed_bar_rate"), 0.0) or 0.0
    limit_down_total = max(to_int(market_metrics.get("limit_down_total"), 0) or 0, 0)
    advance_rate = to_float(market_metrics.get("advance_rate"), 0.0) or 0.0
    max_series_boards = max(to_int(market_metrics.get("max_series_boards"), 0) or 0, 0)
    market_heat = to_float(market_metrics.get("market_heat") or market_metrics.get("heat"), None)
    theme_strength = mean([item.get("score") or 0.0 for item in sector_matrix.get("all", [])[:3]], 0.0)
    mainline_count = len(safe_list(sector_matrix.get("mainline")))
    watch_count = len(safe_list(sector_matrix.get("watch")))
    alive_count = len(safe_list(sector_matrix.get("alive")))

    score = 0.0
    drivers: list[dict[str, Any]] = []
    signals: list[str] = []

    def push_driver(name: str, value: Any, impact: float, reason: str) -> None:
        drivers.append({"name": name, "value": value, "impact": impact, "reason": reason})

    if limit_up_total >= 50:
        score += 22
        signals.append("涨停家数高位扩张")
        push_driver("涨停家数", limit_up_total, 22, "涨停家数高位扩张，情绪偏热")
    elif limit_up_total >= 30:
        score += 16
        signals.append("涨停家数扩散")
        push_driver("涨停家数", limit_up_total, 16, "涨停家数进入扩散区间")
    elif limit_up_total >= 15:
        score += 9
        signals.append("涨停家数回暖")
        push_driver("涨停家数", limit_up_total, 9, "涨停家数开始回暖")
    elif limit_up_total > 0:
        score += 4
        signals.append("仍有零散涨停")
        push_driver("涨停家数", limit_up_total, 4, "仍有零散涨停但强度有限")

    if failed_bar_rate >= 0.35:
        score -= 22
        signals.append("炸板率偏高")
        push_driver("炸板率", round(failed_bar_rate, 4), -22, "炸板率偏高，兑现压力加大")
    elif failed_bar_rate >= 0.2:
        score -= 12
        signals.append("炸板率抬升")
        push_driver("炸板率", round(failed_bar_rate, 4), -12, "炸板率开始抬升")
    elif failed_bar_rate >= 0.1:
        score -= 5
        signals.append("炸板率略有压力")
        push_driver("炸板率", round(failed_bar_rate, 4), -5, "炸板率略有压力")

    if limit_down_total >= 20:
        score -= 20
        signals.append("跌停扩散明显")
        push_driver("跌停数", limit_down_total, -20, "跌停扩散明显")
    elif limit_down_total >= 10:
        score -= 12
        signals.append("跌停数量偏多")
        push_driver("跌停数", limit_down_total, -12, "跌停数量偏多")
    elif limit_down_total >= 5:
        score -= 6
        signals.append("跌停仍需关注")
        push_driver("跌停数", limit_down_total, -6, "跌停仍需关注")

    if advance_rate >= 60:
        score += 10
        signals.append("上涨家数明显占优")
        push_driver("上涨率", round(advance_rate, 2), 10, "上涨家数明显占优")
    elif advance_rate >= 40:
        score += 7
        signals.append("市场广度偏强")
        push_driver("上涨率", round(advance_rate, 2), 7, "市场广度偏强")
    elif advance_rate > 0:
        score += 3
        signals.append("广度温和修复")
        push_driver("上涨率", round(advance_rate, 2), 3, "市场广度温和修复")
    elif advance_rate < 0:
        score -= 4
        signals.append("广度走弱")
        push_driver("上涨率", round(advance_rate, 2), -4, "市场广度走弱")

    if theme_strength >= 70:
        score += 18
        signals.append("主线强度高")
        push_driver("主线强度", round(theme_strength, 2), 18, "主线强度高")
    elif theme_strength >= 55:
        score += 12
        signals.append("主线强度清晰")
        push_driver("主线强度", round(theme_strength, 2), 12, "主线强度清晰")
    elif theme_strength >= 35:
        score += 6
        signals.append("主线仍在扩散")
        push_driver("主线强度", round(theme_strength, 2), 6, "主线仍在扩散")

    if mainline_count >= 3 and limit_up_total >= 20:
        score += 4
        signals.append("主线覆盖面较好")
        push_driver("主线覆盖", mainline_count, 4, "主线覆盖面较好")

    if market_heat is not None:
        if market_heat >= 70:
            score += 6
            signals.append("市场热度高")
            push_driver("市场热度", round(market_heat, 2), 6, "市场热度高")
        elif market_heat < 30:
            score -= 6
            signals.append("市场热度偏低")
            push_driver("市场热度", round(market_heat, 2), -6, "市场热度偏低")

    if max_series_boards >= 3:
        score += 4
        signals.append("连板梯队完整")
        push_driver("连板梯队", max_series_boards, 4, "连板梯队完整")

    if sh_change is not None:
        if sh_change <= -2:
            score -= 10
            signals.append("上证承压")
            push_driver("上证指数", round(sh_change, 2), -10, "上证指数承压")
        elif sh_change >= 1:
            score += 5
            signals.append("指数侧偏强")
            push_driver("上证指数", round(sh_change, 2), 5, "指数侧偏强")

    if sz_change is not None:
        if sz_change <= -2:
            score -= 6
            push_driver("深证成指", round(sz_change, 2), -6, "深证成指承压")
        elif sz_change >= 1:
            score += 3
            push_driver("深证成指", round(sz_change, 2), 3, "深证成指偏强")

    if cyb_change is not None:
        if cyb_change <= -2:
            score -= 4
            push_driver("创业板指", round(cyb_change, 2), -4, "创业板指承压")
        elif cyb_change >= 1:
            score += 2
            push_driver("创业板指", round(cyb_change, 2), 2, "创业板指偏强")

    score = int(round(clamp(score, 0.0, 100.0)))

    if limit_down_total >= 20 or (sh_change is not None and sh_change <= -1.8 and failed_bar_rate >= 0.35):
        stage = "退潮"
    elif failed_bar_rate >= 0.3 and limit_up_total >= 20:
        stage = "分歧"
    elif limit_up_total >= 50 and failed_bar_rate <= 0.18 and (sh_change or 0) >= 0 and theme_strength >= 60:
        stage = "高潮"
    elif limit_up_total >= 25 and advance_rate >= 40 and theme_strength >= 45:
        stage = "发酵"
    elif advance_rate >= 25 or limit_up_total >= 10 or (sh_change or 0) > -1:
        stage = "修复"
    else:
        stage = "冰点"

    description = STAGE_DESCRIPTIONS.get(stage, "市场结构待确认。")
    return {
        "stage": stage,
        "score": score,
        "description": description,
        "signals": signals[:8],
        "drivers": drivers[:8],
        "summary": {
            "sh_index_change": sh_change,
            "sz_index_change": sz_change,
            "cyb_index_change": cyb_change,
            "limit_up_total": limit_up_total,
            "failed_bar_rate": round(failed_bar_rate, 4),
            "limit_down_total": limit_down_total,
            "advance_rate": round(advance_rate, 2),
            "max_series_boards": max_series_boards,
            "market_heat": round(market_heat, 2) if market_heat is not None else None,
            "mainline_count": mainline_count,
            "watch_count": watch_count,
            "alive_count": alive_count,
        },
    }


def _build_risk_context(stage: Mapping[str, Any], market_metrics: Optional[Mapping[str, Any]], sector_matrix: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    market_metrics = safe_dict(market_metrics)
    sector_matrix = safe_dict(sector_matrix)

    failed_bar_rate = to_float(market_metrics.get("failed_bar_rate"), 0.0) or 0.0
    limit_down_total = max(to_int(market_metrics.get("limit_down_total"), 0) or 0, 0)
    limit_up_total = max(to_int(market_metrics.get("limit_up_total"), 0) or 0, 0)
    sh_change = to_float(market_metrics.get("sh_index_change"), 0.0) or 0.0
    market_heat = to_float(market_metrics.get("market_heat") or market_metrics.get("heat"), None)
    mainline_count = len(safe_list(sector_matrix.get("mainline")))
    watch_count = len(safe_list(sector_matrix.get("watch")))
    alive_count = len(safe_list(sector_matrix.get("alive")))
    stage_name = as_text(stage.get("stage"), default="")

    risk_score = 0
    warnings: list[str] = []
    signals: list[str] = []
    drivers: list[dict[str, Any]] = []

    def push_driver(name: str, value: Any, impact: float, reason: str) -> None:
        drivers.append({"name": name, "value": value, "impact": impact, "reason": reason})

    if failed_bar_rate >= 0.35:
        risk_score += 28
        warnings.append(f"炸板率偏高，{int(failed_bar_rate * 100)}% 的短线兑现压力加大。")
        signals.append("炸板率高")
        push_driver("炸板率", round(failed_bar_rate, 4), 28, "炸板率偏高，短线兑现压力加大")
    elif failed_bar_rate >= 0.2:
        risk_score += 18
        warnings.append("炸板率升高，分歧后的承接需要更谨慎。")
        signals.append("炸板率抬升")
        push_driver("炸板率", round(failed_bar_rate, 4), 18, "炸板率升高，分歧压力抬升")
    elif failed_bar_rate >= 0.1:
        risk_score += 10
        warnings.append("炸板数量仍在抬头，短线节奏需要更谨慎。")
        signals.append("炸板率略有压力")
        push_driver("炸板率", round(failed_bar_rate, 4), 10, "炸板率开始有压力")

    if limit_down_total >= 20:
        risk_score += 28
        warnings.append(f"跌停 {limit_down_total} 家，尾部风险扩散明显。")
        signals.append("跌停扩散明显")
        push_driver("跌停数", limit_down_total, 28, "跌停扩散明显，尾部风险增大")
    elif limit_down_total >= 10:
        risk_score += 18
        warnings.append(f"跌停 {limit_down_total} 家，防守位仍需保留。")
        signals.append("跌停数量偏多")
        push_driver("跌停数", limit_down_total, 18, "跌停数量偏多")
    elif limit_down_total >= 5:
        risk_score += 10
        warnings.append("跌停数量仍不低，弱势个股需要隔离。")
        signals.append("跌停仍需关注")
        push_driver("跌停数", limit_down_total, 10, "跌停仍需关注")

    if market_heat is not None and market_heat < 30 and limit_up_total < 20:
        risk_score += 14
        warnings.append("市场热度偏低且涨停不够，缩量风险抬头。")
        signals.append("缩量风险")
        push_driver("市场热度", round(market_heat, 2), 14, "热度不足且涨停偏少，缩量风险抬头")

    if sh_change < 0:
        risk_score += 8
        warnings.append("指数侧承压，追高容错率有限。")
        signals.append("广度偏弱")
        push_driver("指数变化", round(sh_change, 2), 8, "指数承压，追高容错率有限")

    if stage_name == "退潮":
        risk_score += 18
        warnings.append("市场已进入退潮阶段，仓位要明显收缩。")
        signals.append("阶段退潮")
        push_driver("市场阶段", stage_name, 18, "阶段已进入退潮，优先防守")
    elif stage_name == "分歧":
        risk_score += 10
        warnings.append("高位分歧加剧，强弱切换会更快。")
        signals.append("高位分歧")
        push_driver("市场阶段", stage_name, 10, "阶段处于分歧，强弱切换更快")

    mainline_items = safe_list(sector_matrix.get("mainline"))
    if len(mainline_items) <= 1 and limit_up_total >= 30:
        risk_score += 8
        warnings.append("主线数量偏少，一致性过高时要防切换。")
        signals.append("一致性偏高")
        push_driver("主线结构", len(mainline_items), 8, "主线数量偏少，一致性过高时要防切换")

    if watch_count + alive_count <= 2 and limit_up_total >= 30:
        signals.append("次线储备有限")

    if not warnings:
        warnings.append("暂无明显风险信号，仍需遵守仓位纪律。")

    if risk_score >= 80:
        risk_level = "极高"
    elif risk_score >= 55:
        risk_level = "高"
    elif risk_score >= 30:
        risk_level = "中"
    else:
        risk_level = "低"

    return {
        "risk_level": risk_level,
        "risk_score": min(risk_score, 100),
        "warnings": warnings[:6],
        "signals": signals[:8],
        "drivers": drivers[:8],
    }


def _build_ai_report(
    stage: Mapping[str, Any],
    risk: Mapping[str, Any],
    sector_matrix: Mapping[str, Any],
    market_metrics: Optional[Mapping[str, Any]],
    upstream_context: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    upstream_context = safe_dict(upstream_context)
    summary = safe_dict(upstream_context.get("summary"))
    if summary.get("text") or summary.get("markdown"):
        text = as_text(summary.get("text"), default="")
        markdown = as_text(summary.get("markdown"), default="")
        if text and markdown:
            return {"text": text, "markdown": markdown, "source": "upstream"}

    market_metrics = safe_dict(market_metrics)
    limit_up_total = max(to_int(market_metrics.get("limit_up_total"), 0) or 0, 0)
    failed_bar_rate = to_float(market_metrics.get("failed_bar_rate"), 0.0) or 0.0
    limit_down_total = max(to_int(market_metrics.get("limit_down_total"), 0) or 0, 0)
    sh_change = to_float(market_metrics.get("sh_index_change"), None)
    sz_change = to_float(market_metrics.get("sz_index_change"), None)
    cyb_change = to_float(market_metrics.get("cyb_index_change"), None)
    stage_name = as_text(stage.get("stage"), default="未知")
    stage_desc = as_text(stage.get("description"), default="市场结构待确认。")
    risk_level = as_text(risk.get("risk_level"), default="中")
    position = as_text(upstream_context.get("position") or upstream_context.get("cognition", {}).get("position"), default="")

    mainline_text = _join_names(safe_list(sector_matrix.get("mainline")))
    watch_text = _join_names(safe_list(sector_matrix.get("watch")), 2)
    index_parts = []
    for label, value in (("上证", sh_change), ("深证", sz_change), ("创业板", cyb_change)):
        if value is not None:
            index_parts.append(f"{label} {value:+.2f}%")

    index_clause = " / ".join(index_parts) if index_parts else "暂无指数快照"
    broken_pct = f"{failed_bar_rate * 100:.1f}%" if failed_bar_rate else "0.0%"
    position_text = position or POSITION_GUIDANCE.get(stage_name, "4成")

    text = (
        f"市场进入{stage_name}阶段，{stage_desc}。"
        f"主线聚焦 {mainline_text}，观察方向 {watch_text}。"
        f"{index_clause}。"
        f"涨停 {limit_up_total} 家、炸板率 {broken_pct}、跌停 {limit_down_total} 家。"
        f"当前风险 {risk_level}，建议 {position_text}。"
    )

    markdown = (
        "### AI 一句话总览\n"
        f"{text}\n\n"
        f"- 当前阶段：{stage_name}\n"
        f"- 核心主线：{mainline_text}\n"
        f"- 风险判断：{risk_level}\n"
    )
    return {"text": text, "markdown": markdown, "source": "main_hub_rules"}


def _build_dispatch_gate(market_context: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    market_context = safe_dict(market_context)
    stage_name = as_text(market_context.get("stage"), default="")
    risk_level = as_text(market_context.get("risk_level"), default="中")
    can_open_position = bool(
        stage_name not in {"退潮"} and risk_level in {"低", "中"} and not market_context.get("block_open", False)
    )
    return {
        "market_stage": stage_name,
        "emotion_score": market_context.get("emotion_score"),
        "risk_level": risk_level,
        "can_open_position": can_open_position,
        "position_suggestion": market_context.get("position_suggestion"),
        "stage_score": market_context.get("stage_score"),
        "mainline": [as_text(item.get("name"), default="") for item in safe_list(market_context.get("mainline")) if as_text(item.get("name"), default="")],
        "watch": [as_text(item.get("name"), default="") for item in safe_list(market_context.get("watch")) if as_text(item.get("name"), default="")],
        "alive": [as_text(item.get("name"), default="") for item in safe_list(market_context.get("alive")) if as_text(item.get("name"), default="")],
    }


def _build_audit_record(
    created_at: str,
    today_sectors: list[dict[str, Any]] | None,
    history_map: Optional[Mapping[str, Any]],
    market_metrics: Optional[Mapping[str, Any]],
    api_config: Optional[Mapping[str, Any]],
    upstream_context: Optional[Mapping[str, Any]],
    package: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "trace_id": uuid.uuid4().hex,
        "created_at": created_at,
        "source": "main_central_hub",
        "inputs": {
            "sector_count": len(safe_list(today_sectors)),
            "history_count": len(safe_dict(history_map)),
            "metric_keys": sorted(list(safe_dict(market_metrics).keys())),
            "api_config": _redact_mapping(safe_dict(api_config)),
        },
        "upstream": {
            "present": bool(upstream_context),
            "keys": sorted(list(safe_dict(upstream_context).keys())) if upstream_context else [],
            "status": as_text(safe_dict(upstream_context).get("status"), default="") if upstream_context else "",
        },
        "snapshot": {
            "status": as_text(package.get("status"), default=""),
            "market_stage": as_text(safe_dict(package.get("market_context")).get("stage"), default=""),
            "risk_level": as_text(safe_dict(package.get("market_context")).get("risk_level"), default=""),
        },
    }


def build_main_hub_package(
    today_sectors: list[dict[str, Any]] | None,
    history_map: Optional[Mapping[str, Any]],
    market_metrics: Optional[Mapping[str, Any]],
    api_config: Optional[Mapping[str, Any]] = None,
    upstream_context: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    created_at = _now_str()
    if not today_sectors and upstream_context:
        today_sectors = _extract_sector_rows_from_upstream(upstream_context)
    if not market_metrics and upstream_context:
        market_metrics = _extract_market_metrics_from_upstream(upstream_context)

    normalized_date = _normalize_date(
        safe_dict(market_metrics).get("trade_date")
        or safe_dict(upstream_context).get("resolved_date")
        or safe_dict(upstream_context).get("date")
    )
    sector_matrix = _build_sector_matrix(today_sectors, history_map)
    stage_context = _build_stage_context(market_metrics, sector_matrix)
    risk_context = _build_risk_context(stage_context, market_metrics, sector_matrix)
    rotation_context = build_rotation_context(
        sector_matrix,
        market_metrics,
        review_date=normalized_date,
        allow_live=False,
    )
    position_suggestion = POSITION_GUIDANCE.get(stage_context["stage"], "4成")

    if stage_context["stage"] == "退潮" or risk_context["risk_level"] in {"高", "极高"}:
        position_suggestion = "3成"
    elif stage_context["stage"] == "分歧":
        position_suggestion = "4~5成"
    elif stage_context["stage"] == "发酵" and risk_context["risk_level"] in {"低", "中"}:
        position_suggestion = "6成"
    elif stage_context["stage"] == "高潮" and risk_context["risk_level"] == "低":
        position_suggestion = "7成"
    elif stage_context["stage"] == "冰点":
        position_suggestion = "2~3成"

    market_context: dict[str, Any] = {
        "context_version": "v1",
        "date": normalized_date,
        "source_kind": "upstream" if upstream_context else "rules",
        "stage": stage_context["stage"],
        "stage_score": stage_context["score"],
        "stage_description": stage_context["description"],
        "emotion_score": stage_context["score"],
        "risk_level": risk_context["risk_level"],
        "risk_score": risk_context["risk_score"],
        "can_open_position": bool(stage_context["stage"] not in {"退潮"} and risk_context["risk_level"] in {"低", "中"}),
        "position_suggestion": position_suggestion,
        "market_weather": f"{stage_context['stage']} / {risk_context['risk_level']}",
        "mainline": deepcopy(sector_matrix.get("mainline", [])),
        "watch": deepcopy(sector_matrix.get("watch", [])),
        "alive": deepcopy(sector_matrix.get("alive", [])),
        "signals": {
            "stage": stage_context.get("signals", []),
            "theme": sector_matrix.get("signals", []),
            "risk": risk_context.get("signals", []),
            "strategy": [f"建议仓位 {position_suggestion}"],
        },
        "drivers": {
            "stage": stage_context.get("drivers", []),
            "theme": sector_matrix.get("drivers", {}),
            "risk": risk_context.get("drivers", []),
            "position": [
                {
                    "name": "仓位建议",
                    "value": position_suggestion,
                    "reason": "根据市场阶段与风险等级自动推导",
                }
            ],
        },
        "sector_matrix": {
            "mainline": deepcopy(sector_matrix.get("mainline", [])),
            "watch": deepcopy(sector_matrix.get("watch", [])),
            "alive": deepcopy(sector_matrix.get("alive", [])),
            "signals": deepcopy(sector_matrix.get("signals", [])),
        },
        "rotation": deepcopy(rotation_context),
        "capital_migration": _derive_capital_migration(safe_list(sector_matrix.get("all", []))),
        "history_snapshot": _build_history_snapshot(history_map),
        "market_metrics": deepcopy(safe_dict(market_metrics)),
        "updated_at": created_at,
        "upstream_context": {
            "present": bool(upstream_context),
            "keys": sorted(list(safe_dict(upstream_context).keys())) if upstream_context else [],
            "status": as_text(safe_dict(upstream_context).get("status"), default="") if upstream_context else "",
            "resolved_date": safe_dict(upstream_context).get("resolved_date") if upstream_context else None,
        },
    }

    if upstream_context:
        cognition = safe_dict(upstream_context.get("cognition"))
        if cognition:
            market_context["stage"] = as_text(cognition.get("stage"), default=market_context["stage"])
            market_context["stage_score"] = to_int(cognition.get("stage_score"), market_context["stage_score"])
            market_context["stage_description"] = as_text(cognition.get("stage_description"), default=market_context["stage_description"])
            market_context["risk_level"] = as_text(cognition.get("risk_level"), default=market_context["risk_level"])
            market_context["position_suggestion"] = as_text(cognition.get("position"), default=market_context["position_suggestion"])
            market_context["can_open_position"] = bool(
                market_context["stage"] not in {"退潮"} and market_context["risk_level"] in {"低", "中"}
            )
            market_context["signals"]["stage"] = safe_list(cognition.get("signals", {}).get("stage")) or market_context["signals"]["stage"]
            market_context["signals"]["theme"] = safe_list(cognition.get("signals", {}).get("theme")) or market_context["signals"]["theme"]
            market_context["signals"]["risk"] = safe_list(cognition.get("signals", {}).get("risk")) or market_context["signals"]["risk"]
            market_context["drivers"]["stage"] = safe_list(cognition.get("breakdown", {}).get("stage", {}).get("drivers")) or market_context["drivers"]["stage"]
            market_context["drivers"]["risk"] = safe_list(cognition.get("breakdown", {}).get("risk", {}).get("drivers")) or market_context["drivers"]["risk"]
        rotation = safe_dict(upstream_context.get("rotation"))
        if rotation:
            market_context["rotation"] = deepcopy(rotation)

    ai_report_view = _build_ai_report(stage_context, risk_context, sector_matrix, market_metrics, upstream_context)
    if upstream_context:
        upstream_summary = safe_dict(upstream_context.get("summary"))
        if upstream_summary.get("text") or upstream_summary.get("markdown"):
            ai_report_view = {
                "text": as_text(upstream_summary.get("text"), default=ai_report_view["text"]),
                "markdown": as_text(upstream_summary.get("markdown"), default=ai_report_view["markdown"]),
                "source": "upstream",
            }

    status = "DATA_READY" if safe_list(today_sectors) or safe_dict(market_metrics) or upstream_context else "NEEDS_REVIEW"

    package: dict[str, Any] = {
        "date": normalized_date,
        "status": status,
        "market_context": market_context,
        "ai_report_view": ai_report_view,
        "dispatch": _build_dispatch_gate(market_context),
        "meta": {
            "created_at": created_at,
            "source": "main_central_hub",
            "status": status,
            "resolved_date": normalized_date,
        },
        "data_source": {
            "hub": "main_central_hub",
            "input_mode": "upstream" if upstream_context else "rules",
            "updated_at": created_at,
            "resolved_date": normalized_date,
        },
    }

    package["audit"] = _build_audit_record(
        created_at=created_at,
        today_sectors=today_sectors,
        history_map=history_map,
        market_metrics=market_metrics,
        api_config=api_config,
        upstream_context=upstream_context,
        package=package,
    )
    return package


class MainCentralHub:
    """Robot-2/3/4/5 共用的中央中转与调度审计中心。"""

    def __init__(self, report_dir: Optional[Path] = None) -> None:
        self.report_dir = report_dir or Path(__file__).resolve().parents[1] / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.context_cache: Optional[dict[str, Any]] = None
        self.last_package: Optional[dict[str, Any]] = None

    def _snapshot_path(self, created_at: str, suffix: str = "json") -> Path:
        stamp = created_at.replace("-", "").replace("/", "").replace(":", "").replace(" ", "_")
        return self.report_dir / f"main_central_hub_{stamp}.{suffix}"

    def _latest_snapshot_path(self) -> Path:
        return self.report_dir / "main_central_hub_latest.json"

    def _persist(self, package: Mapping[str, Any]) -> None:
        payload = json.dumps(package, ensure_ascii=False, indent=2, default=str)
        created_at = as_text(safe_dict(package.get("meta")).get("created_at"), default=_now_str())
        self._latest_snapshot_path().write_text(payload, encoding="utf-8")
        self._snapshot_path(created_at).write_text(payload, encoding="utf-8")

    def load_latest_package(self) -> dict[str, Any]:
        path = self._latest_snapshot_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def receive_and_transit(
        self,
        today_sectors: list[dict[str, Any]] | None,
        history_map: Optional[Mapping[str, Any]],
        market_metrics: Optional[Mapping[str, Any]],
        api_config: Optional[Mapping[str, Any]] = None,
        upstream_context: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """接收上游数据，构建统一 market_context，并持久化后分发。"""
        package = build_main_hub_package(
            today_sectors=today_sectors,
            history_map=history_map,
            market_metrics=market_metrics,
            api_config=api_config,
            upstream_context=upstream_context,
        )
        self.context_cache = deepcopy(package.get("market_context", {}))
        self.last_package = deepcopy(package)
        self._persist(package)
        return package

    def dispatch_to_strategies(self, context: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """向下游策略机器人分发统一风控门禁。"""
        if context is None:
            context = self.context_cache or safe_dict(self.load_latest_package().get("market_context"))
        context = safe_dict(context)
        if not context:
            raise ValueError("❌ [Main Hub] 核心上下文尚未初始化，无法进行策略分发。")

        stage_name = as_text(context.get("stage"), default="")
        risk_level = as_text(context.get("risk_level"), default="中")
        can_open_position = bool(
            stage_name not in {"退潮"} and risk_level in {"低", "中"} and not context.get("block_open", False)
        )
        return {
            "market_stage": stage_name,
            "emotion_score": context.get("emotion_score"),
            "risk_level": risk_level,
            "can_open_position": can_open_position,
            "position_suggestion": context.get("position_suggestion"),
            "stage_score": context.get("stage_score"),
            "mainline": [as_text(item.get("name"), default="") for item in safe_list(context.get("mainline")) if as_text(item.get("name"), default="")],
            "watch": [as_text(item.get("name"), default="") for item in safe_list(context.get("watch")) if as_text(item.get("name"), default="")],
            "alive": [as_text(item.get("name"), default="") for item in safe_list(context.get("alive")) if as_text(item.get("name"), default="")],
        }


__all__ = ["MainCentralHub", "build_main_hub_package"]
