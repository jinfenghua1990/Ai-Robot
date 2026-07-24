from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_CUSTOM_STRATEGY_KEYS = ["baihu", "qinglong"]

STRATEGY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "baihu",
        "id": "robot-6",
        "name": "白虎-科创创业V26",
        "emoji": "🐯",
        "color": "amber",
        "desc": "MA20强势回调选股",
        "market": "A股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "baihu", "result.json"),
        "script_name": "run_robot6.sh",
        "default_custom": True,
    },
    {
        "key": "qinglong",
        "id": "robot-7",
        "name": "青龙白虎",
        "emoji": "🐉",
        "color": "rose",
        "desc": "MA10主升浪 + MA20第二波",
        "market": "A股",
        "data_key": "stocks",
        "data_adapter": "qinglong",
        "path_parts": ("data", "strategies", "output", "qinglong", "result.json"),
        "script_name": "run_robot7.sh",
        "default_custom": True,
    },
    {
        "key": "theme_momentum",
        "id": "robot-10",
        "name": "题材动量",
        "emoji": "⚡",
        "color": "purple",
        "desc": "题材与趋势联动",
        "market": "A股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "theme_momentum", "result.json"),
        "script_name": "run_robot10.sh",
    },
    {
        "key": "score",
        "id": "robot-11",
        "name": "智能评分",
        "emoji": "📊",
        "color": "cyan",
        "desc": "技术指标综合评分选股",
        "market": "A股",
        "data_key": "results",
        "path_parts": ("data", "strategies", "output", "score", "result.json"),
        "script_name": "run_robot11.sh",
    },
    {
        "key": "hk_sector_leader",
        "id": "robot-19",
        "name": "港股板块龙头",
        "emoji": "🇭🇰",
        "color": "cyan",
        "desc": "港股板块强势龙头筛选",
        "market": "港股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "hk_sector_leader", "result.json"),
    },
    {
        "key": "hk_turtle",
        "id": "robot-20",
        "name": "港股海龟趋势",
        "emoji": "🐢",
        "color": "indigo",
        "desc": "港股趋势跟随选股",
        "market": "港股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "hk_turtle", "result.json"),
    },
    {
        "key": "us_baihu",
        "id": "robot-21",
        "name": "美股白虎",
        "emoji": "🇺🇸",
        "color": "rose",
        "desc": "美股强势回调选股",
        "market": "美股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "us_baihu", "result.json"),
    },
    {
        "key": "us_qinglong",
        "id": "robot-22",
        "name": "美股青龙",
        "emoji": "🇺🇸",
        "color": "rose",
        "desc": "美股主升趋势选股",
        "market": "美股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "us_qinglong", "result.json"),
    },
    {
        "key": "us_tech_factor",
        "id": "robot-23",
        "name": "美股科技因子",
        "emoji": "💻",
        "color": "purple",
        "desc": "美股科技因子选股",
        "market": "美股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "us_tech_factor", "result.json"),
    },
    {
        "key": "us_sector_leader",
        "id": "robot-24",
        "name": "美股板块龙头",
        "emoji": "🗽",
        "color": "emerald",
        "desc": "美股板块领涨龙头",
        "market": "美股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "us_sector_leader", "result.json"),
    },
    {
        "key": "us_turtle",
        "id": "robot-25",
        "name": "美股海龟趋势",
        "emoji": "🐢",
        "color": "indigo",
        "desc": "美股趋势跟随选股",
        "market": "美股",
        "data_key": "stocks",
        "path_parts": ("data", "strategies", "output", "us_turtle", "result.json"),
    },
]


def _resolve_strategy_path(hermes_home: Path, path_parts: tuple[str, ...]) -> Path:
    return hermes_home.joinpath(*path_parts)


def _make_display_name(definition: dict[str, Any]) -> str:
    return definition["name"]


def build_robot_strategy_map(hermes_home: Path) -> dict[str, dict[str, Any]]:
    strategy_map: dict[str, dict[str, Any]] = {}
    for definition in STRATEGY_DEFINITIONS:
        record = dict(definition)
        record["path"] = _resolve_strategy_path(hermes_home, record.pop("path_parts"))
        record["display_name"] = _make_display_name(definition)
        strategy_map[record["key"]] = record
    return strategy_map


def build_robot_id_to_key(strategy_map: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        info["id"]: key
        for key, info in strategy_map.items()
    }


def build_all_robot_ids(strategy_map: dict[str, dict[str, Any]]) -> list[str]:
    def _sort_key(kv):
        try:
            return int(str(kv[1]["id"]).split("-")[1])
        except (ValueError, IndexError):
            return 999
    return [
        info["id"]
        for _key, info in sorted(
            strategy_map.items(),
            key=_sort_key,
        )
    ]


def build_strategy_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for definition in STRATEGY_DEFINITIONS:
        catalog.append(
            {
                "id": definition["id"],
                "key": definition["key"],
                "name": definition["name"],
                "display_name": _make_display_name(definition),
                "emoji": definition["emoji"],
                "color": definition["color"],
                "desc": definition["desc"],
                "market": definition.get("market", ""),
                "data_key": definition.get("data_key", "stocks"),
                "default_custom": bool(definition.get("default_custom", False)),
                "runnable": bool(definition.get("script_name")),
                "hidden": bool(definition.get("hidden", False)),
            }
        )
    return catalog

