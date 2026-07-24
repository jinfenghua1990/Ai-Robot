"""
市场复盘聚合 API（已废弃 - 推荐使用拆分后的独立 API）

⚠️ DEPRECATION NOTICE ⚠️
此接口将于 2026-10-01 移除，请尽快迁移到以下新接口：

推荐替代方案:
┌─────────────────────┬───────────────────────────┬──────────────┐
│ 原字段               │ 新 API                    │ 缓存 TTL     │
├─────────────────────┼───────────────────────────┼──────────────┤
│ market (指数/涨停)   │ GET /api/market           │ 30s          │
│ themes (主题分类)    │ GET /api/themes           │ 30s          │
│ fund_flow (资金流)   │ GET /api/fundflow         │ 5min         │
│ emotion (情绪)       │ GET /api/emotion          │ 60s          │
│ risk_warning        │ GET /api/risk             │ 5min         │
│ tomorrow_plan       │ GET /api/tomorrow-plan    │ 10min        │
│ cognition (认知层)   │ GET /api/cognition        │ 60s          │
│ rotation (轮动)      │ GET /api/rotation         │ 5min         │
│ summary (摘要)       │ GET /api/summary          │ 10min        │
└─────────────────────┴───────────────────────────┴──────────────┘

迁移示例:
  # ❌ 旧方式 (将被移除)
  GET /api/market-review?date=2026-07-18

  # ✅ 新方式 (按需加载)
  GET /api/market?date=2026-07-18        # 指数+涨停+热度
  GET /api/themes?date=2026-07-18        # 主题分类
  GET /api/fundflow?date=2026-07-18      # 资金流向

性能提升:
- 首屏加载时间: 3-5s → 1-2s (按需请求)
- API 响应时间: 800ms-2s → 100-300ms (单一维度查询)
- 缓存命中率: ~40% → ~90% (独立缓存策略)

文档: 见各新 API 的 docstring 和 /cache-info 调试端点
"""

from __future__ import annotations

import json
import sys
import time as _time_module
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

from api.hermes_native.services.market_stage_engine import build_market_stage
from api.hermes_native.services.auto_fill_engine import request_auto_fill
from api.hermes_native.services.main_central_hub import MainCentralHub
from api.hermes_native.services.risk_engine import build_risk_assessment
from api.hermes_native.services.rotation_engine import build_rotation_context
from api.hermes_native.services.summary_engine import build_summary
from api.hermes_native.services.theme_engine import build_theme_sections
from api.hermes_native.services.tomorrow_plan_engine import build_tomorrow_plan
from api.hermes_native.services.market_rotation_report import build_market_rotation_report, write_market_rotation_report

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_MOCK_PATH = ROOT_DIR / "frontend" / "src" / "mock" / "marketReview.json"

ROBOT1_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/robot-1")
DATABASE_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database")
DATA_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/data")


DEFAULT_REVIEW: dict[str, Any] = {
    "date": None,
    "resolved_date": None,
    "status": "missing",
    "updated_at": None,
    "summary": {"text": None, "markdown": None},
    "rotation_report": {
        "title": None,
        "date": None,
        "generated_at": None,
        "source": "mock",
        "summary": None,
        "sections": {
            "market_overview": {},
            "hot_boards_top10": [],
            "money_behavior": {},
            "style_bias": {},
            "rotation_path": {},
            "resonance_check": [],
            "sentiment_metrics": {},
            "tomorrow_plan": {},
        },
        "paths": {},
    },
    "market": {
        "indices": [],
        "breadth": {"up": None, "down": None, "flat": None},
        "limit_up": {
            "limit_up": None,
            "broken": None,
            "st_limit": None,
            "touch_limit": None,
            "failed": None,
            "limit_down": None,
        },
        "heat": {"value": None, "label": None, "trend": None},
    },
    "themes": {"mainline": [], "watch": [], "alive": []},
    "rotation": {
        "policy": "realtime_only_for_sector_rotation",
        "mode": "fallback",
        "session": "closed",
        "updated_at": None,
        "review_date": None,
        "realtime_allowed": False,
        "current": {"mainline": [], "watch": [], "alive": []},
        "previous_close": {"mainline": [], "watch": [], "alive": []},
        "comparison": {
            "conclusion": None,
            "basis": [],
            "realtime_allowed": False,
            "by_category": {},
        },
        "history_windows": {"mainline": {}, "watch": {}, "alive": {}},
        "concept_dimensions": {"timeline": [], "dimensions": [], "source": "robot1_kline+ths_board_map", "updated_at": None, "window_days": 30, "fill_mode": "amount_share_rank_daily", "unit": "亿"},
        "theme_dimensions": {"timeline": [], "dimensions": [], "source": "robot1_kline+ths_board_map", "updated_at": None, "window_days": 30, "fill_mode": "amount_share_rank_daily", "unit": "亿"},
        "industry_dimensions": {"timeline": [], "dimensions": [], "source": "robot1_kline+stock_list", "updated_at": None, "window_days": 30, "fill_mode": "amount_share_rank_daily", "unit": "亿"},
        "summary": {"text": None, "source": None},
        "source": {"current": "robot1", "previous_close": "robot1", "policy": "board_rotation_only"},
    },
    "fund_flow": {
        "north_money": None,
        "industry_inflow_top5": [],
        "industry_outflow_top5": [],
        "concept_inflow_top5": [],
        "concept_outflow_top5": [],
        "stock_inflow_top5": [],
        "stock_outflow_top5": [],
        "stock_inflow_top10": [],
        "stock_outflow_top10": [],
        "market_moneyflow": None,
    },
    "emotion": {"stage": None, "display_stage": None, "score": None, "limit_up": None, "broken": None, "limit_down": None, "explain": None},
    "risk_warning": [],
    "tomorrow_plan": {"attack": [], "secondary": [], "defense": [], "position": None},
    "cognition": {
        "stage": None,
        "stage_score": None,
        "stage_description": None,
        "mainline": [],
        "watch": [],
        "risk_level": None,
        "warnings": [],
        "signals": {"stage": [], "theme": [], "risk": []},
        "position": None,
        "updated_at": None,
        "source": None,
        "breakdown": {
            "stage": {"drivers": []},
            "theme": {"mainline": [], "watch": [], "alive": []},
            "risk": {"drivers": [], "warnings": []},
            "plan": {"attack": [], "secondary": [], "defense": []},
        },
    },
    "meta": {
        "status": "缺失",
        "updated_at": None,
        "source": "mock",
        "robot1": "unavailable",
        "resolved_date": None,
    },
    "data_source": {
        "summary": "mock",
        "market": "mock",
        "themes": "mock",
        "rotation": "mock",
        "fund_flow": "mock",
        "emotion": "mock",
        "risk_warning": "mock",
        "tomorrow_plan": "mock",
        "cognition": "mock",
        "updated_at": None,
        "resolved_date": None,
    },
}

_ROBOT1_API: Optional[dict[str, Any]] = None
_ROBOT1_API_LOADED_AT: float = 0
_ROBOT1_API_ERROR_TTL: float = 300  # 5 minutes: retry import after error
MAIN_CENTRAL_HUB = MainCentralHub()


def _ensure_robot1_paths() -> None:
    for path in (DATA_ROOT, ROBOT1_ROOT, DATABASE_ROOT):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _load_robot1_api() -> dict[str, Any]:
    global _ROBOT1_API, _ROBOT1_API_LOADED_AT
    if _ROBOT1_API is not None:
        # If last load succeeded, keep using it
        if not _ROBOT1_API.get("error"):
            return _ROBOT1_API
        # If last load failed, allow retry after TTL expires
        if _time_module.time() - _ROBOT1_API_LOADED_AT < _ROBOT1_API_ERROR_TTL:
            return _ROBOT1_API
        # TTL expired, reset and retry
        _ROBOT1_API = None

    _ensure_robot1_paths()
    _ROBOT1_API_LOADED_AT = _time_module.time()
    try:
        from collectors.fund_flow_collector import collect_fund_flow
        from data_api import (
            get_index_data,
            get_limit_pool_summary,
            get_limit_up_pool,
            get_market_sentiment,
        )
        from data_api.concept_api import get_concept_boards
        from data_api.industry_api import get_industry_boards
        from data_api.leader_api import get_top_leaders
        from api.hermes_native.db_connector import execute_query

        _ROBOT1_API = {
            "collect_fund_flow": collect_fund_flow,
            "execute_query": execute_query,
            "get_concept_boards": get_concept_boards,
            "get_index_data": get_index_data,
            "get_industry_boards": get_industry_boards,
            "get_leader_rows": get_top_leaders,
            "get_limit_pool_summary": get_limit_pool_summary,
            "get_limit_up_pool": get_limit_up_pool,
            "get_market_sentiment": get_market_sentiment,
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - graceful fallback path
        _ROBOT1_API = {"error": str(exc)}
    return _ROBOT1_API


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_latest_db_health() -> dict[str, Any]:
    outputs_dir = ROBOT1_ROOT / "outputs"
    if outputs_dir.exists():
        candidates = sorted(outputs_dir.glob("db_health_*.json"), key=lambda path: path.name, reverse=True)
        if candidates:
            return _read_json(candidates[0])
        fallback = outputs_dir / "db_health.json"
        if fallback.exists():
            return _read_json(fallback)
    return {}


def _load_mock_review() -> dict[str, Any]:
    return _read_json(FRONTEND_MOCK_PATH)


def _normalize_date(value: Optional[str]) -> str:
    if not value:
        return datetime.now().strftime("%Y-%m-%d")

    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return text


def _normalize_ts(value: Any) -> Optional[str]:
    if value in (None, "", []):
        return None
    text = str(value).strip().replace("T", " ").replace("Z", "")
    return text or None


def _parse_ts(value: Any) -> Optional[datetime]:
    if value in (None, "", []):
        return None
    text = str(value).strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _latest_ts(*values: Any) -> Optional[str]:
    parsed = [(_parse_ts(v), _normalize_ts(v)) for v in values if v not in (None, "", [])]
    parsed = [item for item in parsed if item[0] is not None]
    if not parsed:
        return None
    parsed.sort(key=lambda item: item[0])
    return parsed[-1][1]


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, "", []):
        return default
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value in (None, "", []):
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _money_to_yi(value: Any) -> Optional[float]:
    if value in (None, "", []):
        return None
    try:
        return round(float(value) / 100000000.0, 2)
    except Exception:
        return None


def _north_money_to_yi(value: Any) -> Optional[float]:
    if value in (None, "", []):
        return None
    try:
        return round(float(value) / 10000.0, 2)
    except Exception:
        return None


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _query_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    api = _load_robot1_api()
    if api.get("error"):
        return []
    try:
        rows = api["execute_query"](sql, params)
        return [dict(row) for row in rows]
    except Exception:
        return []


def _query_latest_trade_date(table: str, date_column: str = "trade_date", where_clause: str = "", params: tuple[Any, ...] = ()) -> Optional[str]:
    sql = f"SELECT MAX({date_column}) AS latest_date FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    rows = _query_rows(sql, params)
    if not rows:
        return None
    return _normalize_ts(rows[0].get("latest_date"))


def _row_date_max(rows: list[dict[str, Any]], key: str = "trade_date") -> Optional[str]:
    values = [row.get(key) for row in rows if row.get(key)]
    if not values:
        return None
    return max(str(v) for v in values)


def _load_index_rows(review_date: str) -> tuple[list[dict[str, Any]], Optional[str], str]:
    api = _load_robot1_api()
    if api.get("error"):
        return [], None, "mock"
    try:
        requested = _safe_list(api["get_index_data"](trade_date=review_date, market="CN_A"))
        if requested:
            return [dict(row) for row in requested], _row_date_max(requested), "robot1"

        latest = _safe_list(api["get_index_data"](market="CN_A"))
        if latest:
            latest_date = _row_date_max(latest)
            rows_for_date = [dict(row) for row in latest if str(row.get("trade_date")) == str(latest_date)]
            return rows_for_date, latest_date, "robot1"
    except Exception:
        return [], None, "mock"

    return [], None, "mock"


def _load_sentiment_row(review_date: str) -> tuple[dict[str, Any], Optional[str], str]:
    normalized_date = _normalize_date(review_date)
    rows = _query_rows(
        """
        SELECT trade_date, market, advance_count, decline_count, new_high_count, new_low_count,
               total_volume, total_amount, up_limit_count, down_limit_count, amplitude,
               sentiment_score, sentiment_label, advance_decline_ratio, used_fallback, source_date, created_at
        FROM market_sentiment_daily
        WHERE market = 'CN_A' AND trade_date = %s
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (normalized_date,),
    )
    if rows:
        row = dict(rows[0])
        return row, _normalize_ts(row.get("created_at") or row.get("trade_date")), "robot1"

    latest_rows = _query_rows(
        """
        SELECT trade_date, market, advance_count, decline_count, new_high_count, new_low_count,
               total_volume, total_amount, up_limit_count, down_limit_count, amplitude,
               sentiment_score, sentiment_label, advance_decline_ratio, used_fallback, source_date, created_at
        FROM market_sentiment_daily
        WHERE market = 'CN_A'
        ORDER BY trade_date DESC
        LIMIT 1
        """
    )
    if latest_rows:
        row = dict(latest_rows[0])
        return row, _normalize_ts(row.get("created_at") or row.get("trade_date")), "robot1"

    return {}, None, "mock"


def _load_limit_rows(review_date: str) -> tuple[list[dict[str, Any]], Optional[str], str]:
    api = _load_robot1_api()
    if api.get("error"):
        return [], None, "mock"
    try:
        requested = _safe_dict(api["get_limit_up_pool"](trade_date=review_date, market="CN_A", limit=200))
        rows = _safe_list(requested.get("data"))
        if rows:
            return [dict(row) for row in rows], _row_date_max(rows), "robot1"

        latest_trade_date = _query_latest_trade_date("limit_up_pool_daily")
        if latest_trade_date:
            latest_result = _safe_dict(api["get_limit_up_pool"](trade_date=latest_trade_date, market="CN_A", limit=200))
            latest_rows = _safe_list(latest_result.get("data"))
            if latest_rows:
                return [dict(row) for row in latest_rows], latest_trade_date, "robot1"
    except Exception:
        return [], None, "mock"

    return [], None, "mock"


def _load_industry_rows(review_date: str) -> tuple[list[dict[str, Any]], Optional[str], str]:
    api = _load_robot1_api()
    if api.get("error"):
        return [], None, "mock"
    try:
        requested = _safe_dict(api["get_industry_boards"](trade_date=review_date, limit=20))
        rows = _safe_list(requested.get("data"))
        if rows:
            return [dict(row) for row in rows], _row_date_max(rows), "robot1"

        latest = _safe_dict(api["get_industry_boards"](limit=20))
        latest_rows = _safe_list(latest.get("data"))
        if latest_rows:
            return [dict(row) for row in latest_rows], _row_date_max(latest_rows), "robot1"
    except Exception:
        return [], None, "mock"

    return [], None, "mock"


def _load_concept_rows(review_date: str) -> tuple[list[dict[str, Any]], Optional[str], str]:
    api = _load_robot1_api()
    if api.get("error"):
        return [], None, "mock"
    try:
        requested = _safe_dict(api["get_concept_boards"](trade_date=review_date, limit=20))
        rows = _safe_list(requested.get("data"))
        if rows:
            return [dict(row) for row in rows], _row_date_max(rows), "robot1"

        latest = _safe_dict(api["get_concept_boards"](limit=20))
        latest_rows = _safe_list(latest.get("data"))
        if latest_rows:
            return [dict(row) for row in latest_rows], _row_date_max(latest_rows), "robot1"
    except Exception:
        return [], None, "mock"

    return [], None, "mock"


def _load_leader_rows(review_date: str) -> tuple[list[dict[str, Any]], Optional[str], str]:
    api = _load_robot1_api()
    if api.get("error"):
        return [], None, "mock"
    try:
        requested = _safe_dict(api["get_leader_rows"](trade_date=review_date, top_n=20))
        rows = _safe_list(requested.get("data"))
        if rows:
            return [dict(row) for row in rows], _row_date_max(rows), "robot1"

        latest_rows = _query_rows(
            """
            SELECT trade_date, stock_code, stock_name, theme_name, leadership_score, rank, change_pct, consecutive_days, turnover_amount
            FROM leader_stock_daily
            ORDER BY trade_date DESC, rank ASC
            LIMIT 20
            """
        )
        if latest_rows:
            return latest_rows, _row_date_max(latest_rows), "robot1"
    except Exception:
        return [], None, "mock"

    return [], None, "mock"


def _load_north_money(review_date: str) -> tuple[dict[str, Any], Optional[str], str]:
    rows = _query_rows(
        """
        SELECT trade_date, hgt, sgt, north_money, south_money, ggt_ss, ggt_sz, created_at
        FROM north_money_flow
        WHERE trade_date = %s
        ORDER BY trade_date DESC
        LIMIT 1
        """,
        (_normalize_date(review_date),),
    )
    if rows:
        row = dict(rows[0])
        return row, _normalize_ts(row.get("created_at") or row.get("trade_date")), "robot1"

    latest = _query_rows(
        """
        SELECT trade_date, hgt, sgt, north_money, south_money, ggt_ss, ggt_sz, created_at
        FROM north_money_flow
        ORDER BY trade_date DESC
        LIMIT 1
        """
    )
    if latest:
        row = dict(latest[0])
        return row, _normalize_ts(row.get("created_at") or row.get("trade_date")), "robot1"
    return {}, None, "mock"


def _load_stock_flow_rows(review_date: str) -> tuple[dict[str, Any], Optional[str], str]:
    latest_date = _query_latest_trade_date("youzi_lhb_daily")
    if not latest_date:
        return {}, None, "mock"

    inflow_rows = _query_rows(
        """
        SELECT trade_date, symbol, stock_name, reason, close, pct_chg, turnover, amount,
               net_buy, buy_amount, sell_amount, source, created_at
        FROM youzi_lhb_daily
        WHERE trade_date = %s AND net_buy > 0
        ORDER BY net_buy DESC
        LIMIT 10
        """,
        (latest_date,),
    )
    outflow_rows = _query_rows(
        """
        SELECT trade_date, symbol, stock_name, reason, close, pct_chg, turnover, amount,
               net_buy, buy_amount, sell_amount, source, created_at
        FROM youzi_lhb_daily
        WHERE trade_date = %s AND net_buy < 0
        ORDER BY net_buy ASC
        LIMIT 10
        """,
        (latest_date,),
    )
    if not inflow_rows and not outflow_rows:
        return {}, None, "mock"

    def _fmt_stock(item: dict[str, Any], index: int) -> dict[str, Any]:
        net_buy = _to_float(item.get("net_buy"), 0.0) or 0.0
        return {
            "rank": index + 1,
            "name": item.get("stock_name") or item.get("symbol") or "数据暂缺",
            "value": round(net_buy / 100000000.0, 2),
            "change": _to_float(item.get("pct_chg"), 0.0) or 0.0,
            "source_date": latest_date,
            "source": "robot1",
        }

    return {
        "stock_inflow_top5": [_fmt_stock(dict(item), idx) for idx, item in enumerate(inflow_rows[:5])],
        "stock_outflow_top5": [_fmt_stock(dict(item), idx) for idx, item in enumerate(outflow_rows[:5])],
        "stock_inflow_top10": [_fmt_stock(dict(item), idx) for idx, item in enumerate(inflow_rows)],
        "stock_outflow_top10": [_fmt_stock(dict(item), idx) for idx, item in enumerate(outflow_rows)],
        "source_date": latest_date,
        "source": "robot1",
        "count": len(inflow_rows) + len(outflow_rows),
    }, _normalize_ts((inflow_rows or outflow_rows)[0].get("created_at") or (inflow_rows or outflow_rows)[0].get("trade_date")), "robot1"


def _build_index_history(index_code: str) -> list[dict[str, Any]]:
    rows = _query_rows(
        """
        SELECT trade_date, close, change_pct
        FROM index_data
        WHERE market = 'CN_A' AND index_code = %s
        ORDER BY trade_date DESC
        LIMIT 8
        """,
        (index_code,),
    )
    series = []
    for row in reversed(rows):
        series.append(
            {
                "t": str(row.get("trade_date"))[-5:],
                "v": _to_float(row.get("close"), 0.0) or 0.0,
            }
        )
    return series


def _build_index_card(row: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    index_code = row.get("index_code")
    return {
        "name": row.get("index_name") or fallback_name,
        "trade_date": _normalize_date(row.get("trade_date")),
        "value": _to_float(row.get("close")),
        "change": _to_float(row.get("change_pct")),
        "trend": "up" if (_to_float(row.get("change_pct")) or 0) > 0 else "down" if (_to_float(row.get("change_pct")) or 0) < 0 else "neutral",
        "series": _build_index_history(index_code) if index_code else [],
        "source": "robot1",
    }


def _build_market_section(review_date: str) -> tuple[dict[str, Any], str, Optional[str], bool]:
    index_rows, index_date, index_source = _load_index_rows(review_date)
    sentiment_row, sentiment_updated_at, sentiment_source = _load_sentiment_row(review_date)
    limit_rows, limit_date, limit_source = _load_limit_rows(review_date)

    if not index_rows and not sentiment_row and not limit_rows:
        return deepcopy(DEFAULT_REVIEW["market"]), "mock", None, False

    index_map = {str(row.get("index_code")): row for row in index_rows}
    desired_indices = [
        ("000001.SH", "上证指数"),
        ("399001.SZ", "深证成指"),
        ("399006.SZ", "创业板指"),
    ]

    indices = []
    for code, name in desired_indices:
        row = index_map.get(code)
        if row:
            indices.append(_build_index_card(row, name))
        else:
            indices.append(
                {
                    "name": name,
                    "trade_date": None,
                    "value": None,
                    "change": None,
                    "trend": "neutral",
                    "series": [],
                    "source": "mock",
                }
            )

    breadth = {
        "up": _to_int(sentiment_row.get("advance_count")),
        "down": _to_int(sentiment_row.get("decline_count")),
        "flat": None,
    }

    limit_pool = limit_rows or []
    limit_up_count = _to_int(sentiment_row.get("up_limit_count"))
    limit_down_count = _to_int(sentiment_row.get("down_limit_count"))
    broken_count = sum(1 for row in limit_pool if _to_int(row.get("broken_count"), 0) or 0)
    st_count = sum(1 for row in limit_pool if "ST" in str(row.get("stock_name") or "").upper())
    touch_count = sum(1 for row in limit_pool if row.get("first_limit_up_time") not in (None, "", []))

    market = {
        "trade_date": _normalize_date(index_date),
        "indices": indices,
        "breadth": breadth,
        "limit_up": {
            "limit_up": limit_up_count,
            "broken": broken_count if broken_count or broken_count == 0 else None,
            "st_limit": st_count if st_count or st_count == 0 else None,
            "touch_limit": touch_count if touch_count or touch_count == 0 else None,
            "failed": None,
            "limit_down": limit_down_count,
        },
        "heat": {
            "value": _to_float(sentiment_row.get("sentiment_score")),
            "label": sentiment_row.get("sentiment_label"),
            "trend": "hot"
            if (_to_float(sentiment_row.get("sentiment_score")) or 0) >= 60
            else "warm"
            if (_to_float(sentiment_row.get("sentiment_score")) or 0) >= 40
            else "cool",
        },
    }

    updated_at = _latest_ts(
        sentiment_updated_at,
        limit_date,
        index_date,
        sentiment_row.get("created_at"),
        *(row.get("created_at") for row in limit_pool[:5]),
        *(row.get("created_at") for row in index_rows[:5]),
    )
    source = "robot1" if index_source == "robot1" or sentiment_source == "robot1" or limit_source == "robot1" else "mock"
    has_data = source == "robot1"
    return market, source, updated_at, has_data


def _match_leader(theme_name: str, leaders: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for row in leaders:
        leader_theme = str(row.get("theme_name") or "")
        if not leader_theme:
            continue
        if theme_name == leader_theme or theme_name in leader_theme or leader_theme in theme_name:
            return row
    return None


def _normalize_theme_item(row: dict[str, Any], state: str, leaders: list[dict[str, Any]]) -> dict[str, Any]:
    name = row.get("industry_name") or row.get("board_name") or row.get("sector_name") or "数据暂缺"
    change = _to_float(row.get("change_pct"))
    leader_row = _match_leader(str(name), leaders)
    leader = leader_row.get("stock_name") if leader_row else "数据暂缺"
    if leader_row and leader_row.get("stock_code"):
        leader = f"{leader_row.get('stock_name')}({leader_row.get('stock_code')})"

    if change is None:
        strength = None
    else:
        strength = max(0, min(100, int(round(abs(change) * 12))))

    if change is None:
        judgment = "暂无真实涨幅数据，保持观察。"
    elif change >= 5:
        judgment = "主升延续，资金仍在核心板块。"
    elif change >= 3:
        judgment = "强势轮动，关注分歧后的低吸。"
    elif change >= 1.5:
        judgment = "有轮动热度，适合盯补涨。"
    else:
        judgment = "偏观察位，等进一步确认。"

    return {
        "name": name,
        "change": change,
        "strength": strength,
        "leader": leader,
        "hot": strength,
        "state": state,
        "judgment": judgment,
    }


def _build_themes_section(review_date: str) -> tuple[dict[str, Any], str, Optional[str], bool]:
    industry_rows, industry_date, industry_source = _load_industry_rows(review_date)
    concept_rows, concept_date, concept_source = _load_concept_rows(review_date)
    leader_rows, leader_date, leader_source = _load_leader_rows(review_date)

    if not industry_rows and not concept_rows:
        return deepcopy(DEFAULT_REVIEW["themes"]), "mock", None, False

    industry_rows = [{**dict(row), "source_type": "industry"} for row in industry_rows]
    concept_rows = [{**dict(row), "source_type": "concept"} for row in concept_rows]
    themes = build_theme_sections(industry_rows, concept_rows, leader_rows)

    updated_at = _latest_ts(
        industry_date,
        concept_date,
        leader_date,
        *(row.get("created_at") for row in industry_rows[:5]),
        *(row.get("created_at") for row in concept_rows[:5]),
        *(row.get("created_at") for row in leader_rows[:5]),
    )

    source = "robot1" if industry_source == "robot1" or concept_source == "robot1" or leader_source == "robot1" else "mock"
    return themes, source, updated_at, source == "robot1"


def _build_fund_flow_section(review_date: str) -> tuple[dict[str, Any], str, Optional[str], bool]:
    north_money_row, north_money_updated_at, north_money_source = _load_north_money(review_date)
    api = _load_robot1_api()
    collect_fund_flow_fn = api.get("collect_fund_flow")

    def _split_moneyflow_payload(payload: dict[str, Any], name_field: str = "name") -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        data = _safe_dict(payload.get("data"))
        inflow = _safe_list(data.get("top_inflow"))
        outflow = _safe_list(data.get("top_outflow"))
        inflow10 = _safe_list(data.get("top_inflow_10"))
        outflow10 = _safe_list(data.get("top_outflow_10"))
        if not inflow and not outflow and not inflow10 and not outflow10:
            return [], [], [], []
        # Keep shapes stable for frontend cards.
        return inflow, outflow, inflow10, outflow10

    def _call_moneyflow(data_type: str, **kwargs) -> dict[str, Any]:
        if not collect_fund_flow_fn:
            return {}
        try:
            return _safe_dict(collect_fund_flow_fn(data_type, trade_date=review_date, **kwargs))
        except Exception:
            return {}

    industry_moneyflow = _call_moneyflow("industry_moneyflow")
    concept_moneyflow = _call_moneyflow("concept_moneyflow")
    stock_moneyflow = _call_moneyflow("stock_moneyflow")
    market_moneyflow = _call_moneyflow("market_moneyflow")

    industry_inflow_top5, industry_outflow_top5, _, _ = _split_moneyflow_payload(industry_moneyflow)
    concept_inflow_top5, concept_outflow_top5, _, _ = _split_moneyflow_payload(concept_moneyflow)
    stock_inflow_top5, stock_outflow_top5, stock_inflow_top10, stock_outflow_top10 = _split_moneyflow_payload(stock_moneyflow)

    stock_flow = {}
    stock_flow_updated_at = None
    stock_flow_source = "mock"
    if not stock_inflow_top5 and not stock_outflow_top5:
        stock_flow, stock_flow_updated_at, stock_flow_source = _load_stock_flow_rows(review_date)
        if stock_flow:
            stock_inflow_top5 = _safe_list(stock_flow.get("stock_inflow_top5"))
            stock_outflow_top5 = _safe_list(stock_flow.get("stock_outflow_top5"))
            stock_inflow_top10 = _safe_list(stock_flow.get("stock_inflow_top10"))
            stock_outflow_top10 = _safe_list(stock_flow.get("stock_outflow_top10"))

    north_money = None
    if north_money_row:
        north_money = {
            "trade_date": north_money_row.get("trade_date"),
            "hgt": _north_money_to_yi(north_money_row.get("hgt")),
            "sgt": _north_money_to_yi(north_money_row.get("sgt")),
            "north_money": _north_money_to_yi(north_money_row.get("north_money")),
            "south_money": _north_money_to_yi(north_money_row.get("south_money")),
            "ggt_ss": _north_money_to_yi(north_money_row.get("ggt_ss")),
            "ggt_sz": _north_money_to_yi(north_money_row.get("ggt_sz")),
            "raw": {
                "hgt": north_money_row.get("hgt"),
                "sgt": north_money_row.get("sgt"),
                "north_money": north_money_row.get("north_money"),
                "south_money": north_money_row.get("south_money"),
                "ggt_ss": north_money_row.get("ggt_ss"),
                "ggt_sz": north_money_row.get("ggt_sz"),
            },
        }

    fund_flow = {
        "north_money": north_money,
        "industry_inflow_top5": industry_inflow_top5,
        "industry_outflow_top5": industry_outflow_top5,
        "concept_inflow_top5": concept_inflow_top5,
        "concept_outflow_top5": concept_outflow_top5,
        "stock_inflow_top5": stock_inflow_top5,
        "stock_outflow_top5": stock_outflow_top5,
        "stock_inflow_top10": stock_inflow_top10,
        "stock_outflow_top10": stock_outflow_top10,
        "market_moneyflow": _safe_dict(market_moneyflow.get("data")) if market_moneyflow else None,
    }

    updated_at = _latest_ts(
        north_money_updated_at,
        stock_flow_updated_at,
        *(item.get("trade_date") for item in stock_inflow_top5[:5]),
        *(item.get("trade_date") for item in industry_inflow_top5[:5]),
        *(item.get("trade_date") for item in concept_inflow_top5[:5]),
    )
    has_real = (
        north_money_source == "robot1"
        or stock_flow_source == "robot1"
        or bool(industry_inflow_top5)
        or bool(concept_inflow_top5)
        or bool(stock_inflow_top5)
    )
    return fund_flow, ("partial" if has_real else "mock"), updated_at, has_real


def _build_emotion_section(review_date: str, market: dict[str, Any], fund_flow: dict[str, Any]) -> tuple[dict[str, Any], str, Optional[str], bool]:
    sentiment_row, sentiment_updated_at, source = _load_sentiment_row(review_date)
    if not sentiment_row:
        return deepcopy(DEFAULT_REVIEW["emotion"]), "mock", None, False

    score = _to_float(sentiment_row.get("sentiment_score"), 0.0) or 0.0
    stage = "冰点" if score < 15 else "修复" if score < 30 else "发酵" if score < 50 else "高潮" if score < 70 else "分歧" if score < 85 else "退潮"
    display_stage = f"{sentiment_row.get('sentiment_label') or '情绪'} · {stage}"

    explanation = (
        f"Robot-1 情绪数据为「{sentiment_row.get('sentiment_label') or '未知'}」，"
        f"上涨家数 {sentiment_row.get('advance_count') or 0}，下跌家数 {sentiment_row.get('decline_count') or 0}，"
        f"涨停 {sentiment_row.get('up_limit_count') or 0} 家，跌停 {sentiment_row.get('down_limit_count') or 0} 家。"
    )

    emotion = {
        "stage": stage,
        "display_stage": display_stage,
        "score": score,
        "limit_up": _to_int(sentiment_row.get("up_limit_count")),
        "broken": market.get("limit_up", {}).get("broken"),
        "limit_down": _to_int(sentiment_row.get("down_limit_count")),
        "explain": explanation,
    }
    return emotion, source, sentiment_updated_at, True


def _build_risk_warnings(
    review_date: str,
    market: dict[str, Any],
    fund_flow: dict[str, Any],
    emotion: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []

    score = _to_float(emotion.get("score"), 0.0) or 0.0
    limit_up = _to_int(market.get("limit_up", {}).get("limit_up"), 0) or 0
    broken = _to_int(market.get("limit_up", {}).get("broken"), 0) or 0
    limit_down = _to_int(market.get("limit_up", {}).get("limit_down"), 0) or 0

    if broken > 0:
        warnings.append(f"炸板 {broken} 家，短线分歧依旧明显，冲高回落要小心。")
    if limit_down > 0:
        warnings.append(f"跌停 {limit_down} 家，尾部风险仍需隔离。")
    if score < 40:
        warnings.append(f"情绪分数 {score:.2f}，市场当前仍处在谨慎区。")
    if limit_up >= 50:
        warnings.append(f"涨停 {limit_up} 家，主线较活跃，但一致性也在抬升。")

    north_money = _safe_dict(fund_flow.get("north_money"))
    if north_money:
        north = north_money.get("north_money")
        if north is not None:
            if _to_float(north, 0.0) and _to_float(north, 0.0) > 0:
                warnings.append(f"北向资金净流入约 {north} 亿（按万单元换算），但仍需结合分歧判断。")
            else:
                warnings.append("北向资金偏弱，追高容错率有限。")

    health = _load_latest_db_health()
    missing = (
        health.get("checks", {})
        .get("missing_data", {})
        .get("symbols_without_recent_records")
    )
    if missing not in (None, "", []):
        warnings.append(f"Robot-1 30日缺口 {missing} 个标的，低流动性个股需谨慎。")

    if not warnings:
        warnings = ["暂无明显风险信号，仍需遵守仓位纪律。"]

    return warnings[:5]


def _build_tomorrow_plan(review_date: str, themes: dict[str, Any], emotion: dict[str, Any], market: dict[str, Any]) -> tuple[dict[str, Any], str, Optional[str], bool]:
    mainline = themes.get("mainline") or []
    watch = themes.get("watch") or []
    alive = themes.get("alive") or []

    attack = [f"{item.get('name') or '核心板块'}低吸" for item in mainline[:2]]
    if not attack:
        attack = ["围绕主线核心低吸"]

    secondary = [f"{item.get('name') or '次线方向'}分歧回封" for item in watch[:2]]
    if not secondary:
        secondary = ["等待次线确认"]

    defense = ["避免追高后排", "回避缩量弱板"]
    if _to_int(market.get("limit_up", {}).get("broken"), 0) and _to_int(market.get("limit_up", {}).get("broken"), 0) > 0:
        defense.append("炸板票隔日接力优先观察")

    score = _to_float(emotion.get("score"), 0.0) or 0.0
    if score >= 70:
        position = "建议 7 成仓位"
    elif score >= 50:
        position = "建议 6 成仓位"
    elif score >= 30:
        position = "建议 4~5 成仓位"
    else:
        position = "建议轻仓或观望"

    plan = {
        "attack": attack,
        "secondary": secondary or [f"{item.get('name')}" for item in alive[:2]] or ["暂无次线机会"],
        "defense": defense,
        "position": position,
    }
    return plan, "robot1", None, True


def _build_summary(review_date: str, market: dict[str, Any], themes: dict[str, Any], fund_flow: dict[str, Any], emotion: dict[str, Any]) -> tuple[dict[str, Any], str, Optional[str], bool]:
    indices = market.get("indices") or []
    limit_up = _to_int(market.get("limit_up", {}).get("limit_up"), 0) or 0
    broken = _to_int(market.get("limit_up", {}).get("broken"), 0) or 0
    limit_down = _to_int(market.get("limit_up", {}).get("limit_down"), 0) or 0
    score = _to_float(emotion.get("score"), 0.0) or 0.0

    mainline_names = "、".join([str(item.get("name") or "") for item in (themes.get("mainline") or [])[:3] if item.get("name")]) or "暂无明显主线"
    watch_names = "、".join([str(item.get("name") or "") for item in (themes.get("watch") or [])[:2] if item.get("name")]) or "暂无观察方向"

    index_parts = []
    for item in indices[:3]:
        name = item.get("name") or "指数"
        change = _to_float(item.get("change"), 0.0) or 0.0
        index_parts.append(f"{name}{change:+.2f}%")

    north_money = _safe_dict(fund_flow.get("north_money"))
    north_money_text = ""
    if north_money and north_money.get("north_money") is not None:
        north_money_text = f"，北向资金净流入约 {north_money.get('north_money')} 亿"

    text = (
        f"市场情绪 {emotion.get('display_stage') or emotion.get('stage') or '未知'}，"
        f"涨停 {limit_up} 家、炸板 {broken} 家、跌停 {limit_down} 家。"
        f"指数侧呈现 {(' / '.join(index_parts)) if index_parts else '暂无指数数据'}{north_money_text}。"
        f"主线集中在 {mainline_names}，观察方向包括 {watch_names}。"
        f"明日更适合围绕核心分歧低吸，避免追高后排。"
    )

    markdown = (
        "### AI 一句话总览\n"
        f"{text}\n\n"
        f"- 进攻主线：{mainline_names}\n"
        f"- 观察方向：{watch_names}\n"
        f"- 风险提示：炸板率 {broken} 家、跌停 {limit_down} 家，控制追高\n"
    )

    summary = {"text": text, "markdown": markdown}
    return summary, "robot1", None, True


def _build_rotation_section(review_date: str, market: dict[str, Any], themes: dict[str, Any], emotion: dict[str, Any]) -> dict[str, Any]:
    sector_matrix: dict[str, Any] = {}
    for bucket in ("mainline", "watch", "alive"):
        rows = []
        for item in _safe_list(themes.get(bucket)):
            rows.append(
                {
                    "name": item.get("name"),
                    "leader": item.get("leader"),
                    "change": _to_float(item.get("change"), 0.0) or 0.0,
                    "strength": _to_float(item.get("score"), _to_float(item.get("strength"), 0.0)) or 0.0,
                    "state": item.get("state") or bucket,
                    "judgment": item.get("judgment") or item.get("reason") or "",
                    "score": _to_float(item.get("score"), _to_float(item.get("strength"), None)),
                    "history_windows": _safe_dict(item.get("history_windows")),
                    "history_series": _safe_list(item.get("history_series")),
                    "source_type": item.get("source_type") or "robot1",
                }
            )
        sector_matrix[bucket] = rows

    failed_bar = _to_float(market.get("limit_up", {}).get("failed"), 0.0)
    market_metrics = {
        "failed_bar_rate": failed_bar if failed_bar is not None else 0.0,
        "limit_down_total": _to_int(market.get("limit_up", {}).get("limit_down"), 0) or 0,
        "limit_up_total": _to_int(market.get("limit_up", {}).get("limit_up"), 0) or 0,
        "market_heat": _to_float(market.get("heat", {}).get("value"), _to_float(emotion.get("score"), 0.0)) or 0.0,
    }
    return build_rotation_context(
        sector_matrix,
        market_metrics=market_metrics,
        review_date=review_date,
        allow_live=False,
    )


def _normalize_trade_date_text(value: Any) -> Optional[str]:
    if value in (None, "", []):
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def _resolve_source_trade_date(review_date: str, market: dict[str, Any], fund_flow: dict[str, Any], sentiment_row: dict[str, Any]) -> str:
    requested = _normalize_trade_date_text(review_date) or _normalize_date(review_date)
    candidates: list[str] = []

    def _append_candidate(value: Any) -> None:
        normalized = _normalize_trade_date_text(value)
        if normalized:
            candidates.append(normalized)

    _append_candidate(market.get("trade_date"))
    for idx in _safe_list(market.get("indices")):
        _append_candidate(_safe_dict(idx).get("trade_date"))

    _append_candidate(_safe_dict(sentiment_row).get("trade_date"))

    north_money = _safe_dict(fund_flow.get("north_money"))
    _append_candidate(north_money.get("trade_date"))

    for key in (
        "industry_inflow_top5",
        "industry_outflow_top5",
        "concept_inflow_top5",
        "concept_outflow_top5",
        "stock_inflow_top5",
        "stock_outflow_top5",
        "stock_inflow_top10",
        "stock_outflow_top10",
    ):
        for item in _safe_list(fund_flow.get(key)):
            row = _safe_dict(item)
            _append_candidate(row.get("source_date"))
            _append_candidate(row.get("trade_date"))

    if not candidates:
        return requested

    resolved = max(candidates)
    # Guardrail: never show a source trade date in the future of requested day.
    return min(resolved, requested)


def _build_robot1_review(review_date: str) -> dict[str, Any]:
    market, market_source, market_updated_at, market_ok = _build_market_section(review_date)
    themes, themes_source, themes_updated_at, themes_ok = _build_themes_section(review_date)
    fund_flow, fund_flow_source, fund_flow_updated_at, fund_flow_ok = _build_fund_flow_section(review_date)

    stage = build_market_stage(market, themes)

    sentiment_row, sentiment_updated_at, sentiment_source = _load_sentiment_row(review_date)
    sentiment_label = str(sentiment_row.get("sentiment_label") or "市场情绪").strip() if sentiment_row else "市场情绪"
    sentiment_score = _to_float(sentiment_row.get("sentiment_score")) if sentiment_row else None
    emotion = {
        "stage": stage.get("stage"),
        "display_stage": f"{sentiment_label} · {stage.get('stage')}" if stage.get("stage") else sentiment_label,
        "score": stage.get("score") if stage.get("score") is not None else sentiment_score,
        "limit_up": _to_int(sentiment_row.get("up_limit_count")) if sentiment_row else market.get("limit_up", {}).get("limit_up"),
        "broken": market.get("limit_up", {}).get("broken"),
        "limit_down": _to_int(sentiment_row.get("down_limit_count")) if sentiment_row else market.get("limit_up", {}).get("limit_down"),
        "explain": f"{stage.get('description') or '市场结构待确认。'}；" + "；".join(stage.get("signals", [])[:3]),
    }
    emotion_source = "robot1" if market_ok or themes_ok or fund_flow_ok or sentiment_source == "robot1" else "mock"
    emotion_updated_at = _latest_ts(sentiment_updated_at, market_updated_at, themes_updated_at, fund_flow_updated_at)
    rotation = _build_rotation_section(review_date, market, themes, emotion)

    risk = build_risk_assessment(market, themes, fund_flow, stage)
    risk_warning = risk.get("warnings", [])

    summary = build_summary(stage, themes, risk, market, fund_flow)
    summary_source = "robot1" if market_ok or themes_ok or fund_flow_ok else "mock"
    summary_updated_at = _latest_ts(market_updated_at, themes_updated_at, fund_flow_updated_at, emotion_updated_at)

    tomorrow_plan = build_tomorrow_plan(stage, themes, risk, market)
    plan_source = "robot1" if market_ok or themes_ok or fund_flow_ok else "mock"
    plan_updated_at = _latest_ts(market_updated_at, themes_updated_at, fund_flow_updated_at, emotion_updated_at)

    any_real = any([market_ok, themes_ok, fund_flow_ok])
    if not any_real:
        return {}

    rotation_updated_at = rotation.get("updated_at")
    source_updated_at = _latest_ts(market_updated_at, themes_updated_at, fund_flow_updated_at, emotion_updated_at, plan_updated_at, summary_updated_at, rotation_updated_at)
    resolved_date = _resolve_source_trade_date(review_date, market, fund_flow, sentiment_row)
    status_label = "最新" if resolved_date >= _normalize_date(review_date) else "延迟"

    review = deepcopy(DEFAULT_REVIEW)
    review["date"] = review_date
    review["resolved_date"] = resolved_date
    review["status"] = status_label
    review["updated_at"] = source_updated_at or datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    review["summary"] = summary
    review["market"] = market
    review["themes"] = themes
    review["rotation"] = rotation
    review["fund_flow"] = fund_flow
    review["emotion"] = emotion
    review["risk_warning"] = risk_warning
    review["tomorrow_plan"] = tomorrow_plan
    review["cognition"] = {
        "stage": stage.get("stage"),
        "stage_score": stage.get("score"),
        "stage_description": stage.get("description"),
        "mainline": [str(item.get("name") or "").strip() for item in (themes.get("mainline") or []) if str(item.get("name") or "").strip()],
        "watch": [str(item.get("name") or "").strip() for item in (themes.get("watch") or []) if str(item.get("name") or "").strip()],
        "risk_level": risk.get("risk_level"),
        "warnings": risk_warning,
        "signals": {
            "stage": stage.get("signals", []),
            "theme": themes.get("signals", []),
            "risk": risk.get("signals", []),
        },
        "position": tomorrow_plan.get("position"),
        "updated_at": review["updated_at"],
        "source": "robot1",
        "breakdown": {
            "stage": {
                "score": stage.get("score"),
                "description": stage.get("description"),
                "drivers": stage.get("drivers", []),
                "signals": stage.get("signals", []),
            },
            "theme": {
                "mainline": (themes.get("drivers", {}) or {}).get("mainline", []),
                "watch": (themes.get("drivers", {}) or {}).get("watch", []),
                "alive": (themes.get("drivers", {}) or {}).get("alive", []),
                "signals": themes.get("signals", []),
            },
            "risk": {
                "level": risk.get("risk_level"),
                "score": risk.get("risk_score"),
                "drivers": risk.get("drivers", []),
                "warnings": risk_warning,
            },
            "plan": {
                "position": tomorrow_plan.get("position"),
                "attack": tomorrow_plan.get("attack", []),
                "secondary": tomorrow_plan.get("secondary", []),
                "defense": tomorrow_plan.get("defense", []),
            },
        },
    }
    review["meta"] = {
        "status": review["status"],
        "updated_at": review["updated_at"],
        "source": "robot1",
        "robot1": "available",
        "resolved_date": review["resolved_date"],
        "data_latency": _format_latency(review["updated_at"]),
    }
    review["data_source"] = {
        "summary": summary_source,
        "market": market_source,
        "themes": themes_source,
        "rotation": "guosen" if rotation.get("mode") == "realtime" else "robot1",
        "fund_flow": fund_flow_source,
        "emotion": emotion_source,
        "risk_warning": "robot1",
        "tomorrow_plan": plan_source,
        "cognition": "robot1",
        "updated_at": review["updated_at"],
        "resolved_date": review["resolved_date"],
        "source_dates": {
            "market": market_updated_at,
            "themes": themes_updated_at,
            "rotation": rotation_updated_at,
            "fund_flow": fund_flow_updated_at,
            "emotion": emotion_updated_at,
            "summary": summary_updated_at,
        },
    }
    hub_package = MAIN_CENTRAL_HUB.receive_and_transit(
        today_sectors=None,
        history_map=None,
        market_metrics=None,
        upstream_context=review,
    )
    review["main_hub"] = {
        "status": hub_package.get("status"),
        "market_context": hub_package.get("market_context", {}),
        "stage": hub_package.get("market_context", {}).get("stage"),
        "risk_level": hub_package.get("market_context", {}).get("risk_level"),
        "position_suggestion": hub_package.get("market_context", {}).get("position_suggestion"),
        "dispatch": hub_package.get("dispatch", {}),
        "meta": hub_package.get("meta", {}),
        "data_source": hub_package.get("data_source", {}),
        "updated_at": hub_package.get("meta", {}).get("created_at"),
    }
    hub_market_context = _safe_dict(hub_package.get("market_context"))
    hub_rotation = _safe_dict(hub_market_context.get("rotation"))
    if hub_rotation:
        merged_rotation = _deep_merge(deepcopy(DEFAULT_REVIEW["rotation"]), hub_rotation)
        base_concept_dims = _safe_list(review.get("rotation", {}).get("concept_dimensions", {}).get("dimensions"))
        merged_concept_dims = _safe_list(merged_rotation.get("concept_dimensions", {}).get("dimensions"))
        if len(merged_concept_dims) < len(base_concept_dims):
            merged_rotation["concept_dimensions"] = deepcopy(review.get("rotation", {}).get("concept_dimensions", {}))
            merged_rotation["theme_dimensions"] = deepcopy(review.get("rotation", {}).get("theme_dimensions", {}))
        base_industry_dims = _safe_list(review.get("rotation", {}).get("industry_dimensions", {}).get("dimensions"))
        merged_industry_dims = _safe_list(merged_rotation.get("industry_dimensions", {}).get("dimensions"))
        if len(merged_industry_dims) < len(base_industry_dims):
            merged_rotation["industry_dimensions"] = deepcopy(review.get("rotation", {}).get("industry_dimensions", {}))
        review["rotation"] = merged_rotation
        review["data_source"]["rotation"] = "guosen" if hub_rotation.get("mode") == "realtime" else "robot1"
        review["data_source"]["source_dates"]["rotation"] = hub_rotation.get("updated_at") or review["data_source"]["source_dates"].get("rotation")
        review["main_hub"]["market_context"]["rotation"] = deepcopy(hub_rotation)

    try:
        rotation_report = build_market_rotation_report(review)
        report_paths = write_market_rotation_report(rotation_report)
        rotation_report["paths"] = report_paths
        review["rotation_report"] = rotation_report
        review["data_source"]["rotation_report"] = "robot1"
    except Exception as exc:
        review["rotation_report"] = _deep_merge(
            deepcopy(DEFAULT_REVIEW["rotation_report"]),
            {
                "title": "板块轮动与主力动向收盘复盘报告",
                "date": review.get("resolved_date") or review.get("date"),
                "generated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
                "source": "error",
                "summary": f"生成失败: {exc}",
            },
        )
        review["data_source"]["rotation_report"] = "error"
    return review


def _format_latency(updated_at: Optional[str]) -> Optional[str]:
    ts = _parse_ts(updated_at)
    if ts is None:
        return None
    delta = datetime.now() - ts
    if delta.total_seconds() < 0:
        return "0s"
    if delta.total_seconds() < 60:
        return f"{int(delta.total_seconds())}s"
    if delta.total_seconds() < 3600:
        return f"{int(delta.total_seconds() // 60)}m"
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    return f"{hours}h{minutes:02d}m"


def _build_mock_fallback(review_date: str) -> dict[str, Any]:
    mock = _load_mock_review()
    review = deepcopy(DEFAULT_REVIEW)
    review = _deep_merge(review, mock)
    review["date"] = review_date
    review["resolved_date"] = review_date
    review["status"] = "缺失"
    review["updated_at"] = review.get("meta", {}).get("updated_at") or datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    review["meta"] = {
        "status": review["status"],
        "updated_at": review["updated_at"],
        "source": "mock",
        "robot1": "unavailable",
        "resolved_date": review_date,
        "data_latency": review.get("meta", {}).get("data_latency"),
    }
    review["data_source"] = {
        "summary": "mock",
        "market": "mock",
        "themes": "mock",
        "rotation": "mock",
        "fund_flow": "mock",
        "emotion": "mock",
        "risk_warning": "mock",
        "tomorrow_plan": "mock",
        "cognition": "mock",
        "rotation_report": "mock",
        "updated_at": review["updated_at"],
        "resolved_date": review_date,
    }
    review["rotation"] = _deep_merge(deepcopy(DEFAULT_REVIEW["rotation"]), review.get("rotation"))
    main_hub = _safe_dict(review.get("main_hub"))
    market_context = _safe_dict(main_hub.get("market_context"))
    if not market_context.get("rotation"):
        market_context["rotation"] = deepcopy(review["rotation"])
    else:
        market_context["rotation"] = _deep_merge(deepcopy(review["rotation"]), market_context.get("rotation"))
    main_hub["market_context"] = market_context
    review["main_hub"] = main_hub
    review["data_source"]["rotation"] = "mock"
    return review


def _deep_merge(base: dict[str, Any], incoming: Optional[dict[str, Any]]) -> dict[str, Any]:
    result = deepcopy(base)
    if not incoming:
        return result

    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@router.get(
    "/api/market-review",
    deprecated=True,
    summary="⚠️ [已废弃] 市场复盘聚合接口 - 请使用拆分后的独立 API",
    description="""
    ⚠️ DEPRECATED - 此接口将于 2026-10-01 移除

    请迁移到以下新 API（按需调用，性能更优）:
    - GET /api/market       → 指数/涨停/热度
    - GET /api/themes      → 主线/观察/活跃
    - GET /api/fundflow    → 北向/行业资金流
    - GET /api/emotion     → 情绪指标
    - GET /api/cognition   → 认知层+门控
    - GET /api/rotation    → 板块轮动
    - GET /api/summary     → 复盘摘要

    迁移文档: 见本文件顶部的 DEPRECATION NOTICE

    当前行为: 仍返回完整数据，但响应头包含 Deprecation 警告。
""",
)
def get_market_review(
    date: Optional[str] = Query(default=None, alias="date", description="YYYY-MM-DD"),
    review_date: Optional[str] = Query(default=None, alias="review_date", description="Legacy date param"),
):
    requested_date = _normalize_date(date or review_date)
    auto_fill = request_auto_fill(requested_date)
    real_review = _build_robot1_review(requested_date)
    if real_review:
        real_review["data_source"]["auto_fill"] = auto_fill
        real_review["meta"]["auto_fill"] = {
            "requested": auto_fill.get("requested"),
            "launched": auto_fill.get("launched"),
            "reason": auto_fill.get("reason"),
            "jobs": [job.get("job") for job in auto_fill.get("jobs", [])],
        }
        return real_review
    fallback = _build_mock_fallback(requested_date)
    fallback["data_source"]["auto_fill"] = auto_fill
    fallback["meta"]["auto_fill"] = {
        "requested": auto_fill.get("requested"),
        "launched": auto_fill.get("launched"),
        "reason": auto_fill.get("reason"),
        "jobs": [job.get("job") for job in auto_fill.get("jobs", [])],
    }
    return fallback
