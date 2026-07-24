from __future__ import annotations

import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from ._utils import as_text, safe_dict, safe_list, to_float, to_int

ROOT_DIR = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT_DIR / "data" / "market"
DB_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database")
if str(DB_ROOT) not in sys.path:
    sys.path.insert(0, str(DB_ROOT))
try:
    from api.hermes_native.db_connector import execute_query
except Exception:
    execute_query = None

TECH_KEYWORDS = (
    "ai",
    "人工智能",
    "机器人",
    "半导体",
    "芯片",
    "算力",
    "液冷",
    "cpo",
    "光通信",
    "元件",
    "电子",
    "光学",
    "光电",
    "储能",
    "电池",
    "新能源",
    "低空",
)
CONSUMER_KEYWORDS = ("白酒", "消费", "食品", "家电", "零售", "医药", "旅游")
DEFENSE_KEYWORDS = ("银行", "电力", "煤炭", "公用事业", "白酒", "交通运输")


def _now_str() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def _fmt_pct(value: Any) -> str:
    num = to_float(value, None)
    if num is None:
        return "数据暂缺"
    return f"{num:+.2f}%"


def _fmt_yi(value: Any, default: str = "数据暂缺") -> str:
    num = to_float(value, None)
    if num is None:
        return default
    return f"{num:+.2f}亿"


def _fmt_value(value: Any, digits: int = 2, default: str = "数据暂缺") -> str:
    num = to_float(value, None)
    if num is None:
        return default
    return f"{num:.{digits}f}"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)


def _normalize_name_key(value: Any) -> str:
    text = as_text(value, default="")
    return "".join(ch for ch in text.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _query_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if execute_query is None:
        return []
    try:
        rows = execute_query(sql, params)
    except Exception:
        return []
    return [dict(row) for row in rows]


def _load_board_change_maps(review_date: str) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    concept_rows = _query_rows(
        """
        SELECT board_name, change_pct, stock_count, trade_date
        FROM concept_board_daily
        WHERE trade_date = (
            SELECT MAX(trade_date) FROM concept_board_daily WHERE trade_date <= %s
        )
        """,
        (review_date,),
    )
    industry_rows = _query_rows(
        """
        SELECT industry_name, change_pct, stock_count, trade_date
        FROM industry_board_daily
        WHERE trade_date = (
            SELECT MAX(trade_date) FROM industry_board_daily WHERE trade_date <= %s
        )
        """,
        (review_date,),
    )

    concept_map: dict[str, dict[str, Any]] = {}
    for row in concept_rows:
        key = _normalize_name_key(row.get("board_name"))
        if not key:
            continue
        concept_map[key] = {
            "change_pct": to_float(row.get("change_pct"), None),
            "stock_count": to_int(row.get("stock_count"), None),
            "trade_date": row.get("trade_date"),
        }

    industry_map: dict[str, dict[str, Any]] = {}
    for row in industry_rows:
        key = _normalize_name_key(row.get("industry_name"))
        if not key:
            continue
        industry_map[key] = {
            "change_pct": to_float(row.get("change_pct"), None),
            "stock_count": to_int(row.get("stock_count"), None),
            "trade_date": row.get("trade_date"),
        }

    return concept_map, industry_map


def _lookup_board_change(name_key: str, source_map: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if not name_key:
        return {}
    direct = safe_dict(source_map.get(name_key))
    if direct:
        return direct

    best_payload: dict[str, Any] = {}
    best_score = 0
    for key, payload in source_map.items():
        if not key:
            continue
        if name_key in key or key in name_key:
            score = min(len(name_key), len(key))
            if score > best_score:
                best_score = score
                best_payload = safe_dict(payload)
    return best_payload


def _build_index_map(market: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in safe_list(safe_dict(market).get("indices")):
        if not isinstance(row, Mapping):
            continue
        name = as_text(row.get("name"), default="")
        if not name:
            continue
        result[name] = dict(row)
    return result


def _pick_index(index_map: Mapping[str, Mapping[str, Any]], name: str) -> dict[str, Any]:
    row = safe_dict(index_map.get(name))
    return {
        "name": name,
        "value": to_float(row.get("value"), None),
        "change_pct": to_float(row.get("change"), None),
        "trade_date": row.get("trade_date"),
    }


def _to_rotation_name_rows(rows: Any, flow_field: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in safe_list(rows):
        data = safe_dict(row)
        name = as_text(data.get("sector_name") or data.get("name"), default="")
        if not name:
            continue
        output.append(
            {
                "name": name,
                "flow_yi": to_float(data.get(flow_field), None),
            }
        )
    return output


def _build_hot_board_top10(
    review: Mapping[str, Any],
    flow_map: Mapping[str, Optional[float]],
    concept_change_map: Mapping[str, Mapping[str, Any]],
    industry_change_map: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rotation = safe_dict(review.get("rotation"))
    concept_rows = safe_list(safe_dict(rotation.get("concept_dimensions")).get("dimensions"))
    industry_rows = safe_list(safe_dict(rotation.get("industry_dimensions")).get("dimensions"))
    theme_rows = safe_list(safe_dict(rotation.get("theme_dimensions")).get("dimensions"))
    theme_map: dict[str, dict[str, Any]] = {}
    for bucket in ("mainline", "watch", "alive"):
        for row in safe_list(safe_dict(review.get("themes")).get(bucket)):
            if not isinstance(row, Mapping):
                continue
            name = as_text(row.get("name"), default="")
            if name:
                theme_map[name] = dict(row)

    combined = [*concept_rows, *industry_rows, *theme_rows]
    dedup: dict[str, dict[str, Any]] = {}
    for row in combined:
        item = safe_dict(row)
        name = as_text(item.get("name"), default="")
        if not name:
            continue
        latest_amount = to_float(item.get("latest_amount_yi"), None)
        latest_ratio = to_float(item.get("latest_ratio_pct"), None)
        base = {
            "name": name,
            "category": as_text(item.get("category") or item.get("source_type"), default="board"),
            "change_pct": to_float(item.get("hot_change_pct"), None),
            "ratio_change_pct": to_float(item.get("delta_ratio_pct"), None),
            "turnover_yi": latest_amount,
            "main_flow_yi": flow_map.get(name),
            "super_large_flow_yi": None,
            "strength_rank": to_int(item.get("latest_rank"), None),
            "latest_ratio_pct": latest_ratio,
        }
        existed = dedup.get(name)
        if existed is None:
            dedup[name] = base
            continue
        old_amount = to_float(existed.get("turnover_yi"), -1e99) or -1e99
        new_amount = to_float(base.get("turnover_yi"), -1e99) or -1e99
        if new_amount > old_amount:
            dedup[name] = base

    def sort_key(item: Mapping[str, Any]) -> tuple[float, float]:
        return (
            to_float(item.get("turnover_yi"), -1e99) or -1e99,
            to_float(item.get("latest_ratio_pct"), -1e99) or -1e99,
        )

    ordered = sorted(dedup.values(), key=sort_key, reverse=True)[:10]
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(ordered, start=1):
        row = dict(item)
        name_key = _normalize_name_key(row.get("name"))
        concept_change = _lookup_board_change(name_key, concept_change_map)
        industry_change = _lookup_board_change(name_key, industry_change_map)
        source_type = as_text(row.get("category") or row.get("source_type"), default="")
        board_change = {}
        if source_type.startswith("concept"):
            board_change = concept_change or industry_change
        elif source_type.startswith("industry"):
            board_change = industry_change or concept_change
        else:
            board_change = concept_change or industry_change

        if row.get("change_pct") is None:
            theme_row = theme_map.get(as_text(row.get("name"), default=""))
            if isinstance(theme_row, Mapping):
                row["change_pct"] = to_float(theme_row.get("change"), None)
        if row.get("change_pct") is None:
            row["change_pct"] = to_float(board_change.get("change_pct"), None)
        if row.get("change_pct") is None:
            row["change_pct"] = to_float(row.get("ratio_change_pct"), None)
        if row.get("stock_count") is None:
            row["stock_count"] = to_int(board_change.get("stock_count"), row.get("stock_count"))
        if row.get("source_date") is None:
            row["source_date"] = board_change.get("trade_date")
        row["rank"] = idx
        result.append(row)
    return result


def _build_style_bias(review: Mapping[str, Any], market_metrics: Mapping[str, Any], top10: list[dict[str, Any]]) -> dict[str, Any]:
    market = safe_dict(review.get("market"))
    index_map = _build_index_map(market)
    sh = to_float(safe_dict(index_map.get("上证指数")).get("change"), None)
    cyb = to_float(safe_dict(index_map.get("创业板指")).get("change"), None)
    growth_bias = None
    if sh is not None and cyb is not None:
        growth_bias = round(cyb - sh, 2)

    theme_names = " ".join(
        as_text(item.get("name"), default="")
        for item in safe_list(safe_dict(review.get("themes")).get("mainline"))
    )
    tech_hit = _contains_any(theme_names, TECH_KEYWORDS)
    consumer_hit = _contains_any(theme_names, CONSUMER_KEYWORDS)
    style_tc = "科技占优" if tech_hit and not consumer_hit else "消费占优" if consumer_hit and not tech_hit else "科技消费均衡"

    risk_level = as_text(safe_dict(review.get("cognition")).get("risk_level"), default="")
    stage = as_text(safe_dict(review.get("cognition")).get("stage"), default="")

    if "高" in risk_level or stage in {"退潮", "分歧"}:
        attack_vs_defense = "防御优先"
    elif stage in {"发酵", "高潮"}:
        attack_vs_defense = "进攻优先"
    else:
        attack_vs_defense = "均衡偏进攻"

    big_small = "大盘偏强" if (sh is not None and sh > 0) else "小盘活跃" if (cyb is not None and cyb > 0) else "大小盘均衡"
    growth_value = "成长偏强" if (growth_bias is not None and growth_bias > 0) else "价值偏强" if (growth_bias is not None and growth_bias < 0) else "成长价值均衡"
    conclusion = f"{growth_value}，{big_small}，{style_tc}，当前节奏 {attack_vs_defense}。"

    return {
        "growth_vs_value": growth_value,
        "big_vs_small": big_small,
        "tech_vs_consumer": style_tc,
        "attack_vs_defense": attack_vs_defense,
        "conclusion": conclusion,
    }


def _build_money_behavior(review: Mapping[str, Any], top10: list[dict[str, Any]], outflow_names: list[str], inflow_names: list[str]) -> dict[str, Any]:
    absorb: list[dict[str, Any]] = []
    distribute: list[dict[str, Any]] = []
    defense: list[dict[str, Any]] = []

    for item in top10:
        name = as_text(item.get("name"), default="")
        change_pct = to_float(item.get("change_pct"), None)
        main_flow = to_float(item.get("main_flow_yi"), None)
        if main_flow is not None and main_flow > 0 and (change_pct is None or change_pct < 3):
            absorb.append({"name": name, "reason": f"净流入 {_fmt_yi(main_flow)}，涨幅 {_fmt_pct(change_pct)}。"})
        if main_flow is not None and main_flow < 0 and (change_pct is None or change_pct <= 0):
            distribute.append({"name": name, "reason": f"净流出 {_fmt_yi(main_flow)}，涨幅 {_fmt_pct(change_pct)}。"})
        if _contains_any(name, DEFENSE_KEYWORDS):
            defense.append({"name": name, "reason": "防御属性板块，资金偏保守。"})

    if not absorb:
        for name in inflow_names[:2]:
            absorb.append({"name": name, "reason": "轮动流入方向，观察是否形成吸筹。"})
    if not distribute:
        for name in outflow_names[:2]:
            distribute.append({"name": name, "reason": "轮动流出方向，警惕高位兑现。"})
    if not defense:
        defense = [{"name": "防御板块", "reason": "当前样本未识别到显著防御抱团，保持跟踪。"}]

    high_low_switch = {
        "from": outflow_names[:3] if outflow_names else ["暂无"],
        "to": inflow_names[:3] if inflow_names else ["暂无"],
        "text": f"{' / '.join(outflow_names[:3] or ['暂无'])} -> {' / '.join(inflow_names[:3] or ['暂无'])}",
    }

    return {
        "absorb_pattern": absorb[:5],
        "distribute_pattern": distribute[:5],
        "defense_pattern": defense[:5],
        "high_low_switch": high_low_switch,
    }


def _build_resonance(review: Mapping[str, Any], style_bias: Mapping[str, Any], inflow_name_set: set[str]) -> list[dict[str, Any]]:
    themes = safe_dict(review.get("themes"))
    candidates = safe_list(themes.get("mainline"))[:5]
    result: list[dict[str, Any]] = []

    for item in candidates:
        row = safe_dict(item)
        name = as_text(row.get("name"), default="")
        change = to_float(row.get("change"), None)
        board_strength_ok = change is not None and change >= 1.0
        capital_ok = name in inflow_name_set
        style_ok = True
        conclusion = as_text(style_bias.get("conclusion"), default="")
        if "防御优先" in conclusion and _contains_any(name, TECH_KEYWORDS):
            style_ok = False

        result.append(
            {
                "sector": name or "数据暂缺",
                "board_strength": {
                    "pass": board_strength_ok,
                    "detail": f"涨幅 {_fmt_pct(change)}",
                },
                "capital_strength": {
                    "pass": capital_ok,
                    "detail": "位于轮动流入方向" if capital_ok else "未进入轮动流入前列",
                },
                "style_match": {
                    "pass": style_ok,
                    "detail": "匹配当前风格" if style_ok else "与当前风格有背离",
                },
                "resonance": "强共振" if (board_strength_ok and capital_ok and style_ok) else "待确认",
            }
        )

    if not result:
        result.append(
            {
                "sector": "暂无",
                "board_strength": {"pass": False, "detail": "数据暂缺"},
                "capital_strength": {"pass": False, "detail": "数据暂缺"},
                "style_match": {"pass": False, "detail": "数据暂缺"},
                "resonance": "待确认",
            }
        )
    return result


def build_market_rotation_report(review: Mapping[str, Any]) -> dict[str, Any]:
    review = safe_dict(review)
    date_value = as_text(review.get("resolved_date") or review.get("date"), default=datetime.now().strftime("%Y-%m-%d"))
    market = safe_dict(review.get("market"))
    cognition = safe_dict(review.get("cognition"))
    fund_flow = safe_dict(review.get("fund_flow"))
    rotation = safe_dict(review.get("rotation"))
    main_hub = safe_dict(review.get("main_hub"))
    market_context = safe_dict(main_hub.get("market_context"))
    market_metrics = safe_dict(market_context.get("market_metrics"))

    index_map = _build_index_map(market)
    breadth = safe_dict(market.get("breadth"))
    limit_up = safe_dict(market.get("limit_up"))

    industry_dimensions = safe_dict(rotation.get("industry_dimensions"))
    dimension_rows = safe_list(industry_dimensions.get("dimensions"))
    market_total_amount_yi = to_float(safe_dict(dimension_rows[0]).get("market_total_amount_yi"), None) if dimension_rows else None

    cap_migration = safe_dict(market_context.get("capital_migration"))
    outflow_rows = _to_rotation_name_rows(cap_migration.get("outflow_from"), "capital_flow_yi")
    inflow_rows = _to_rotation_name_rows(cap_migration.get("inflow_to"), "capital_flow_yi")
    outflow_names = [row["name"] for row in outflow_rows]
    inflow_names = [row["name"] for row in inflow_rows]
    flow_map = {row["name"]: row["flow_yi"] for row in outflow_rows + inflow_rows}

    concept_change_map, industry_change_map = _load_board_change_maps(date_value)
    top10 = _build_hot_board_top10(review, flow_map, concept_change_map, industry_change_map)
    style_bias = _build_style_bias(review, market_metrics, top10)
    money_behavior = _build_money_behavior(review, top10, outflow_names, inflow_names)
    resonance = _build_resonance(review, style_bias, set(inflow_names))

    stage = as_text(cognition.get("stage") or market_context.get("stage"), default="未知")
    stage_desc = as_text(cognition.get("stage_description") or market_context.get("stage_description"), default="数据暂缺")
    risk_level = as_text(cognition.get("risk_level") or market_context.get("risk_level"), default="未知")
    summary_text = as_text(safe_dict(review.get("summary")).get("text"), default="暂无")

    tomorrow = safe_dict(review.get("tomorrow_plan"))

    report = {
        "title": "板块轮动与主力动向收盘复盘报告",
        "date": date_value,
        "generated_at": _now_str(),
        "source": "robot1",
        "summary": summary_text,
        "sections": {
            "market_overview": {
                "indices": [
                    _pick_index(index_map, "上证指数"),
                    _pick_index(index_map, "深证成指"),
                    _pick_index(index_map, "创业板指"),
                    _pick_index(index_map, "北证50"),
                    _pick_index(index_map, "沪深300"),
                ],
                "breadth": {
                    "up": to_int(breadth.get("up"), None),
                    "down": to_int(breadth.get("down"), None),
                    "flat": to_int(breadth.get("flat"), None),
                },
                "turnover_total_yi": market_total_amount_yi,
                "volume_change_pct": None,
                "stage": stage,
                "stage_description": stage_desc,
                "risk_level": risk_level,
            },
            "hot_boards_top10": top10,
            "money_behavior": money_behavior,
            "style_bias": style_bias,
            "rotation_path": {
                "outflow": outflow_names[:5],
                "inflow": inflow_names[:5],
                "path_text": money_behavior.get("high_low_switch", {}).get("text"),
            },
            "resonance_check": resonance,
            "sentiment_metrics": {
                "limit_up_count": to_int(limit_up.get("limit_up"), to_int(market_metrics.get("limit_up_total"), None)),
                "limit_down_count": to_int(limit_up.get("limit_down"), to_int(market_metrics.get("limit_down_total"), None)),
                "max_board_height": to_int(market_metrics.get("max_series_boards"), None),
                "broken_rate": to_float(market_metrics.get("failed_bar_rate"), None),
                "yesterday_limit_up_perf": to_float(market_metrics.get("yesterday_premium"), None),
                "emotion_stage": as_text(safe_dict(review.get("emotion")).get("display_stage") or safe_dict(review.get("emotion")).get("stage"), default=stage),
                "emotion_score": to_float(market_context.get("emotion_score"), to_float(safe_dict(review.get("emotion")).get("score"), None)),
            },
            "tomorrow_plan": {
                "attack": safe_list(tomorrow.get("attack")),
                "watch": safe_list(tomorrow.get("secondary")),
                "avoid": safe_list(tomorrow.get("defense")),
                "position": as_text(tomorrow.get("position"), default="数据暂缺"),
            },
        },
    }
    return report


def render_market_rotation_report_markdown(report: Mapping[str, Any]) -> str:
    report = safe_dict(report)
    sections = safe_dict(report.get("sections"))
    market_overview = safe_dict(sections.get("market_overview"))
    top10 = safe_list(sections.get("hot_boards_top10"))
    money_behavior = safe_dict(sections.get("money_behavior"))
    style_bias = safe_dict(sections.get("style_bias"))
    rotation_path = safe_dict(sections.get("rotation_path"))
    resonance = safe_list(sections.get("resonance_check"))
    sentiment = safe_dict(sections.get("sentiment_metrics"))
    tomorrow = safe_dict(sections.get("tomorrow_plan"))

    lines: list[str] = []
    lines.append(f"# {as_text(report.get('title'), default='板块轮动与主力动向收盘复盘报告')}")
    lines.append(f"- 日期: {as_text(report.get('date'), default='数据暂缺')}")
    lines.append(f"- 生成时间: {as_text(report.get('generated_at'), default='数据暂缺')}")
    lines.append("")
    lines.append("## 一、大盘概览")
    for idx in safe_list(market_overview.get("indices")):
        row = safe_dict(idx)
        lines.append(f"- {as_text(row.get('name'), default='指数')}: {_fmt_value(row.get('value'), 2)} ({_fmt_pct(row.get('change_pct'))})")
    breadth = safe_dict(market_overview.get("breadth"))
    lines.append(
        f"- 涨跌家数: 上涨 {to_int(breadth.get('up'), 0)} / 下跌 {to_int(breadth.get('down'), 0)} / 平盘 {to_int(breadth.get('flat'), 0)}"
    )
    lines.append(f"- 两市成交额: {_fmt_yi(market_overview.get('turnover_total_yi'))}")
    lines.append(f"- 市场阶段: {as_text(market_overview.get('stage'), default='未知')} | {as_text(market_overview.get('stage_description'), default='数据暂缺')}")
    lines.append("")

    lines.append("## 二、今日热门板块 TOP10")
    if top10:
        for row in top10:
            item = safe_dict(row)
            lines.append(
                f"- {to_int(item.get('rank'), 0)}. {as_text(item.get('name'), default='数据暂缺')} | 涨幅 {_fmt_pct(item.get('change_pct'))} | 成交额 {_fmt_yi(item.get('turnover_yi'))} | 主力净额 {_fmt_yi(item.get('main_flow_yi'))}"
            )
    else:
        lines.append("- 暂无数据")
    lines.append("")

    lines.append("## 三、主力资金行为识别")
    lines.append("- 吸筹模式")
    for row in safe_list(money_behavior.get("absorb_pattern"))[:5]:
        item = safe_dict(row)
        lines.append(f"  - {as_text(item.get('name'), default='数据暂缺')}: {as_text(item.get('reason'), default='')}")
    lines.append("- 出货模式")
    for row in safe_list(money_behavior.get("distribute_pattern"))[:5]:
        item = safe_dict(row)
        lines.append(f"  - {as_text(item.get('name'), default='数据暂缺')}: {as_text(item.get('reason'), default='')}")
    lines.append("- 防守模式")
    for row in safe_list(money_behavior.get("defense_pattern"))[:5]:
        item = safe_dict(row)
        lines.append(f"  - {as_text(item.get('name'), default='数据暂缺')}: {as_text(item.get('reason'), default='')}")
    lines.append(f"- 高低切: {as_text(safe_dict(money_behavior.get('high_low_switch')).get('text'), default='数据暂缺')}")
    lines.append("")

    lines.append("## 四、风格偏向分析")
    lines.append(f"- 成长 vs 价值: {as_text(style_bias.get('growth_vs_value'), default='数据暂缺')}")
    lines.append(f"- 大盘 vs 小盘: {as_text(style_bias.get('big_vs_small'), default='数据暂缺')}")
    lines.append(f"- 科技 vs 消费: {as_text(style_bias.get('tech_vs_consumer'), default='数据暂缺')}")
    lines.append(f"- 进攻 vs 防御: {as_text(style_bias.get('attack_vs_defense'), default='数据暂缺')}")
    lines.append(f"- 结论: {as_text(style_bias.get('conclusion'), default='数据暂缺')}")
    lines.append("")

    lines.append("## 五、轮动路径分析")
    lines.append(f"- 轮动路径: {as_text(rotation_path.get('path_text'), default='数据暂缺')}")
    lines.append("")

    lines.append("## 六、三要素共振检测")
    if resonance:
        for row in resonance[:5]:
            item = safe_dict(row)
            board = safe_dict(item.get("board_strength"))
            capital = safe_dict(item.get("capital_strength"))
            style = safe_dict(item.get("style_match"))
            lines.append(f"- {as_text(item.get('sector'), default='数据暂缺')} ({as_text(item.get('resonance'), default='待确认')})")
            lines.append(f"  - 板块维度: {as_text(board.get('detail'), default='数据暂缺')}")
            lines.append(f"  - 资金维度: {as_text(capital.get('detail'), default='数据暂缺')}")
            lines.append(f"  - 风格维度: {as_text(style.get('detail'), default='数据暂缺')}")
    else:
        lines.append("- 暂无数据")
    lines.append("")

    lines.append("## 七、市场情绪指标")
    lines.append(f"- 涨停数量: {to_int(sentiment.get('limit_up_count'), 0)}")
    lines.append(f"- 跌停数量: {to_int(sentiment.get('limit_down_count'), 0)}")
    lines.append(f"- 连板高度: {to_int(sentiment.get('max_board_height'), 0)}")
    broken = to_float(sentiment.get("broken_rate"), None)
    lines.append(f"- 炸板率: {f'{broken * 100:.2f}%' if broken is not None else '数据暂缺'}")
    lines.append(f"- 昨日涨停表现: {_fmt_pct(sentiment.get('yesterday_limit_up_perf'))}")
    lines.append(f"- 情绪判断: {as_text(sentiment.get('emotion_stage'), default='数据暂缺')} (score={_fmt_value(sentiment.get('emotion_score'), 1)})")
    lines.append("")

    lines.append("## 八、明日操作方向")
    lines.append(f"- 主攻方向: {'、'.join(as_text(x, default='') for x in safe_list(tomorrow.get('attack')) if as_text(x, default='')) or '数据暂缺'}")
    lines.append(f"- 观察方向: {'、'.join(as_text(x, default='') for x in safe_list(tomorrow.get('watch')) if as_text(x, default='')) or '数据暂缺'}")
    lines.append(f"- 回避方向: {'、'.join(as_text(x, default='') for x in safe_list(tomorrow.get('avoid')) if as_text(x, default='')) or '数据暂缺'}")
    lines.append(f"- 仓位建议: {as_text(tomorrow.get('position'), default='数据暂缺')}")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def write_market_rotation_report(report: Mapping[str, Any], base_dir: Optional[Path] = None) -> dict[str, str]:
    target_dir = base_dir or REPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    report_date = as_text(safe_dict(report).get("date"), default=datetime.now().strftime("%Y-%m-%d"))
    report_date_compact = report_date.replace("-", "")

    latest_json = target_dir / "market_rotation_report.json"
    latest_md = target_dir / "market_rotation_report.md"
    history_json = target_dir / f"market_rotation_report_{report_date_compact}.json"
    history_md = target_dir / f"market_rotation_report_{report_date_compact}.md"

    payload = deepcopy(safe_dict(report))
    payload.setdefault("paths", {})
    payload["paths"]["json"] = str(latest_json)
    payload["paths"]["markdown"] = str(latest_md)
    payload["paths"]["history_json"] = str(history_json)
    payload["paths"]["history_markdown"] = str(history_md)

    markdown = render_market_rotation_report_markdown(payload)

    latest_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest_md.write_text(markdown, encoding="utf-8")
    history_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    history_md.write_text(markdown, encoding="utf-8")

    return {
        "json": str(latest_json),
        "markdown": str(latest_md),
        "history_json": str(history_json),
        "history_markdown": str(history_md),
    }
