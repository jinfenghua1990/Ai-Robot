from __future__ import annotations

from typing import Any, Mapping, Optional

from ._utils import as_text, clamp, mean, safe_dict, safe_list, to_float, to_int, unique_by_name


THEME_CANONICAL_OVERRIDES: dict[str, str] = {
    "华为手机": "消费电子",
    "华为终端": "消费电子",
    "华为概念": "消费电子",
    "苹果概念": "消费电子",
    "AI手机": "消费电子",
    "AIPC": "消费电子",
    "折叠屏": "消费电子",
    "智能穿戴": "消费电子",
}

EVENT_THEME_KEYWORDS: tuple[str, ...] = (
    "预增",
    "预减",
    "年报",
    "一季报",
    "中报",
    "三季报",
    "业绩",
    "快报",
    "分红",
    "送转",
    "摘帽",
    "ST",
    "*ST",
)


def _canonicalize_theme_name(name: str) -> str:
    target = as_text(name, default="").strip()
    if not target:
        return "数据暂缺"

    direct_override = THEME_CANONICAL_OVERRIDES.get(target)
    if direct_override:
        return direct_override

    if "手机" in target or "终端" in target or "穿戴" in target:
        return "消费电子"
    if "华为" in target and "能源" in target:
        return "电力"
    if "华为" in target and "汽车" in target:
        return "汽车零部件"

    return target


def _is_event_theme(name: str) -> bool:
    text = as_text(name, default="").strip().upper()
    if not text:
        return True
    return any(keyword.upper() in text for keyword in EVENT_THEME_KEYWORDS)


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
        timeline = {}
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


def _match_leader(board_name: str, leaders: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    target = board_name.strip()
    if not target:
        return None
    for row in leaders:
        leader_theme = as_text(row.get("theme_name"), default="")
        if not leader_theme:
            continue
        if target == leader_theme or target in leader_theme or leader_theme in target:
            return row
    return None


def _candidate_score(row: Mapping[str, Any], leader_rows: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    raw_name = as_text(row.get("industry_name") or row.get("board_name") or row.get("sector_name") or row.get("concept_name") or row.get("theme_name"))
    family_name = _canonicalize_theme_name(raw_name)
    display_name = raw_name or family_name
    change = to_float(row.get("change_pct"), 0.0) or 0.0
    stock_count = max(to_int(row.get("stock_count"), 0) or 0, 0)
    up_count = max(to_int(row.get("up_count"), 0) or 0, 0)
    down_count = max(to_int(row.get("down_count"), 0) or 0, 0)
    turnover_rate = to_float(row.get("turnover_rate"), 0.0) or 0.0

    matched_leader = _match_leader(family_name, leader_rows) or _match_leader(raw_name, leader_rows)
    leader_name = "数据暂缺"
    leader_score = 0.0
    consecutive_days = 0
    if matched_leader:
        leader_name = as_text(matched_leader.get("stock_name"))
        if matched_leader.get("stock_code"):
            leader_name = f"{leader_name}({matched_leader.get('stock_code')})"
        leader_score = to_float(matched_leader.get("leadership_score"), 0.0) or 0.0
        consecutive_days = max(to_int(matched_leader.get("consecutive_days"), 0) or 0, 0)

    score = 0.0
    score += clamp(change, -2.0, 8.0) * 8.5
    # 板块规模只能作为辅助因子，不能让“大盘子”直接压过真实热度。
    score += min(stock_count, 120) * 0.12
    score += max(up_count - down_count, 0) * 1.15
    score += min(turnover_rate, 20.0) * 1.3
    score += min(leader_score, 100.0) * 0.35
    score += min(consecutive_days, 10) * 4.0
    if matched_leader:
        score += 6.0
    if change >= 5:
        score += 4.0
    elif change < 0:
        score -= 4.0
    if raw_name != family_name:
        score -= 1.5
    source_type = str(row.get("source_type") or "").strip().lower()
    if source_type == "concept":
        score += 2.0
    elif source_type == "industry":
        score -= 2.5

    reasons = [
        f"涨幅 {change:+.2f}%",
        f"龙头活跃度 {leader_score:.1f}",
    ]
    if stock_count > 0:
        reasons.insert(1, f"板块股票数 {stock_count}")
    else:
        reasons.insert(1, "成分数暂缺")
    if up_count or down_count:
        reasons.append(f"涨跌结构 {up_count}/{down_count}")
    if consecutive_days:
        reasons.append(f"连续性 {consecutive_days} 天")
    if turnover_rate:
        reasons.append(f"换手率 {turnover_rate:.2f}")
    if raw_name != family_name:
        reasons.append(f"归一为 {family_name}")

    state = "watch"
    if score >= 65 and change >= 0.5:
        state = "main"
    elif score >= 35:
        state = "watch"
    elif score >= 20 or (change > 0 and matched_leader):
        state = "alive"

    if score >= 70 and consecutive_days >= 2:
        judgment = "主升延续，资金仍在核心板块。"
    elif score >= 55:
        judgment = "热度足够，仍在主线确认区。"
    elif score >= 40:
        judgment = "有轮动热度，适合盯补涨。"
    else:
        judgment = "偏观察位，等进一步确认。"

    source_type = str(row.get("source_type") or "").strip().lower()
    if source_type not in {"industry", "concept"}:
        if row.get("industry_name"):
            source_type = "industry"
        elif row.get("concept_name") or row.get("board_name") or row.get("sector_name") or row.get("theme_name"):
            source_type = "concept"
        else:
            source_type = "unknown"

    is_event = _is_event_theme(raw_name) or _is_event_theme(family_name)

    item = {
        "name": display_name,
        "family_name": family_name,
        "raw_name": raw_name,
        "change": round(change, 2) if row.get("change_pct") is not None else None,
        "strength": int(clamp(score, 0.0, 100.0)),
        "leader": leader_name,
        "hot": int(clamp(score, 0.0, 100.0)),
        "state": state,
        "judgment": judgment,
        "score": round(score, 2),
        "reasons": reasons,
        "capital_flow_timeline": _normalize_capital_flow_timeline(
            row.get("capital_flow_timeline") or row.get("capital_flow_series") or row.get("capital_timeline")
        ),
        "source_type": source_type,
        "is_event_theme": is_event,
    }
    return score, item


def _rank_and_slice(candidates: list[dict[str, Any]], threshold: float, limit: int) -> list[dict[str, Any]]:
    filtered = [item for item in candidates if (item.get("score") or 0) >= threshold and not item.get("is_event_theme")]
    filtered.sort(key=lambda item: (item.get("score") or 0, item.get("change") or 0), reverse=True)
    return unique_by_name(filtered[:limit])


def build_theme_sections(
    industry_rows: list[dict[str, Any]] | None,
    concept_rows: list[dict[str, Any]] | None,
    leader_rows: list[dict[str, Any]] | None,
    market: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    industry_rows = list(industry_rows or [])
    concept_rows = list(concept_rows or [])
    leader_rows = list(leader_rows or [])
    market = safe_dict(market)

    candidates: list[dict[str, Any]] = []
    for row in industry_rows:
        score, item = _candidate_score(row, leader_rows)
        item["score"] = round(score, 2)
        candidates.append(item)
    for row in concept_rows:
        score, item = _candidate_score(row, leader_rows)
        item["score"] = round(score, 2)
        candidates.append(item)

    merged_candidates: dict[str, dict[str, Any]] = {}
    for item in candidates:
        canonical_name = as_text(item.get("family_name") or _canonicalize_theme_name(item.get("name")))
        merged = dict(item)
        merged.setdefault("raw_name", item.get("raw_name") or item.get("name"))
        merged["family_name"] = canonical_name
        existed = merged_candidates.get(canonical_name)
        if existed is None:
            merged_candidates[canonical_name] = merged
            continue
        existed_score = to_float(existed.get("score"), 0.0) or 0.0
        merged_score = to_float(merged.get("score"), 0.0) or 0.0
        existed_change = to_float(existed.get("change"), 0.0) or 0.0
        merged_change = to_float(merged.get("change"), 0.0) or 0.0
        if (
            (merged_score, merged_change) > (existed_score, existed_change)
            or (
                merged.get("source_type") == "concept"
                and existed.get("source_type") != "concept"
                and merged_score >= existed_score - 5
            )
        ):
            merged_candidates[canonical_name] = merged

    candidates = sorted(merged_candidates.values(), key=lambda item: (item.get("score") or 0, item.get("change") or 0), reverse=True)
    candidates = [item for item in candidates if not item.get("is_event_theme")]

    mainline = _rank_and_slice(candidates, 60, 3)
    watch = _rank_and_slice([item for item in candidates if item not in mainline], 40, 3)
    alive = _rank_and_slice([item for item in candidates if item not in mainline and item not in watch], 25, 3)

    if not mainline and candidates:
        concept_candidates = [item for item in candidates if as_text(item.get("source_type"), default="") == "concept"]
        mainline = unique_by_name(concept_candidates[:2]) if concept_candidates else unique_by_name(candidates[:1])
    if not watch and len(candidates) > len(mainline):
        watch = unique_by_name(candidates[len(mainline): len(mainline) + 2])
    if not alive and len(candidates) > len(mainline) + len(watch):
        alive = unique_by_name(candidates[len(mainline) + len(watch): len(mainline) + len(watch) + 3])

    signal_parts: list[str] = []
    if mainline:
        signal_parts.append(f"主线数量 {len(mainline)}")
    if watch:
        signal_parts.append(f"观察方向 {len(watch)} 个")
    if alive:
        signal_parts.append(f"活口方向 {len(alive)} 个")
    if market.get("limit_up", {}).get("limit_up") is not None:
        signal_parts.append(f"涨停家数 {market.get('limit_up', {}).get('limit_up')}")

    return {
        "mainline": mainline,
        "watch": watch,
        "alive": alive,
        "signals": signal_parts,
        "drivers": {
            "mainline": [{"name": item["name"], "raw_name": item.get("raw_name"), "score": item["score"], "leader": item["leader"], "judgment": item["judgment"], "reasons": item.get("reasons", [])} for item in mainline[:3]],
            "watch": [{"name": item["name"], "raw_name": item.get("raw_name"), "score": item["score"], "leader": item["leader"], "judgment": item["judgment"], "reasons": item.get("reasons", [])} for item in watch[:3]],
            "alive": [{"name": item["name"], "raw_name": item.get("raw_name"), "score": item["score"], "leader": item["leader"], "judgment": item["judgment"], "reasons": item.get("reasons", [])} for item in alive[:3]],
        },
    }
