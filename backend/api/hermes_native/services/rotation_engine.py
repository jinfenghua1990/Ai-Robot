from __future__ import annotations

import os
import json
import re
import ssl
import sys
from copy import deepcopy
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode

from ._utils import as_text, mean, safe_dict, safe_list, to_float, to_int
from .ths_board_map import load_concept_board_registry


GS_BASE_URL = "https://dgzt.guosen.com.cn/skills"
GS_SOFT_NAME = "goldsun_skills"
GS_API_KEY = os.environ.get("GS_API_KEY", "").strip()
TIMEOUT_SECONDS = 10
TRACK_LIMIT_PER_BUCKET = 2
HISTORY_WINDOWS = (10, 5, 3, 2, 1)
REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
DB_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database")
if str(DB_ROOT) not in sys.path:
    sys.path.insert(0, str(DB_ROOT))
try:
    from api.hermes_native.db_connector import execute_query
except Exception:
    execute_query = None
_ROTATION_HISTORY_CACHE: dict[str, list[float]] = {}
_THEME_DIMENSION_CACHE: dict[str, Any] = {}
PREFERRED_THEME_NAMES = [
    "机器人",
    "半导体",
    "光伏",
    "电池",
    "AI",
    "面板",
    "玻璃基板",
    "有色金属",
    "房地产",
    "交通运输",
    "农林牧渔",
    "化工",
    "电子",
]
CONCEPT_META_EXCLUDE_KEYWORDS = (
    "融资融券",
    "转融券",
    "融资标的",
    "融券标的",
    "证金持股",
    "两融",
)
HOT_CONCEPT_EXCLUDE_KEYWORDS = (
    "昨日",
    "连板",
    "历史新高",
    "百元股",
    "预增",
    "高送转",
    "破净",
    "低价股",
    "次新股",
    "微盘股",
)
PREFERRED_INDUSTRY_NAMES = [
    "通信设备",
    "消费电子",
    "工业金属",
    "汽车零部件",
    "银行",
    "通用设备",
    "半导体设备",
    "光伏设备",
    "小金属",
    "锂",
    "元器件",
    "半导体",
    "电力",
    "电网设备",
    "证券",
    "白酒",
    "光学光电子",
    "煤炭开采加工",
    "电子化学品",
    "电池",
    "IT设备",
    "化工原料",
    "房地产",
    "交通运输",
    "农林牧渔",
    "软件开发",
    "专用机械",
    "玻璃",
    "食品饮料",
]
THEME_FAMILY_ALIASES: dict[str, list[str]] = {
    "机器人": ["机器人", "机器人概念", "人形机器人", "机器人执行器", "虚拟机器人", "工业机器人", "自动化设", "自动化设备", "通用设备", "专用设备", "工业母机", "电机Ⅱ", "机械设备", "工控设备"],
    "半导体": ["半导体", "半导体概念", "半导体设备", "半导体材料", "第三代半导体", "第四代半导体", "中芯概念", "集成电路封测", "集成电路", "芯片", "光刻胶", "存储芯片"],
    "电池": ["电池", "锂电池", "锂电池概念", "固态电池", "钠离子电池", "电池化学品", "动力电池回收", "蓄电池及其他电池", "BC电池", "TOPCon电池", "HJT电池", "钙钛矿电池", "麒麟电池", "电池技术"],
    "AI": ["AI", "人工智能", "AI应用", "AI智能体", "AI芯片", "AI语料", "多模态AI", "AIGC概念", "AIGC", "AI手机", "AI眼镜", "智谱AI", "智谱AI概念", "中国AI 50", "AIPC", "IT服务Ⅱ", "软件开发", "互联网服务", "游戏", "数字媒体", "数据要素", "云游戏", "算力"],
    "面板": ["面板", "光学光电", "显示技术", "OLED", "MiniLED", "折叠屏"],
    "玻璃基板": ["玻璃基板", "玻璃行业", "玻璃制造", "玻璃玻纤", "3D玻璃", "光学玻璃"],
    "光伏": ["光伏", "光伏概念", "光伏发电", "光伏设备", "光伏辅材", "光伏电池组件", "光伏加工设备"],
    "有色金属": ["有色金属", "小金属", "工业金属", "能源金属", "稀有金属", "铜", "镍"],
    "房地产": ["房地产", "房地产业", "地产开发"],
    "交通运输": ["交通运输", "物流", "航运港口", "铁路公路"],
    "农林牧渔": ["农林牧渔", "种植业", "养殖业", "渔业", "农产品加工"],
    "化工": ["基础化工", "化学原料", "化学制品", "化学纤维", "农化制品", "塑料", "橡胶"],
    "电子": ["电子", "消费电子", "元件"],
}
KLINE_AMOUNT_TO_YI_DIVISOR = 100000.0
KLINE_MARKETS = ("SH", "SZ", "BJ")
UPSTREAM_SOURCE = "upstream"
UPSTREAM_BOARD_SOURCE = "upstream_kline+ths_board_map"
UPSTREAM_STOCK_SOURCE = "upstream_kline+stock_list"
UPSTREAM_DAILY_DB_SOURCE = "upstream_daily_db"
UPSTREAM_ROTATION_FALLBACK_SOURCE = "upstream_rotation_fallback"


def _now_str() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def _is_trading_session(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    clock = now.time()
    morning_start = dt_time(9, 30)
    morning_end = dt_time(11, 30)
    afternoon_start = dt_time(13, 0)
    afternoon_end = dt_time(15, 0)
    return (morning_start <= clock <= morning_end) or (afternoon_start <= clock <= afternoon_end)


def _create_ssl_context() -> ssl.Optional[SSLContext]:
    try:
        ctx = ssl._create_unverified_context()
        try:
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
            ctx.set_ciphers("ALL:@SECLEVEL=0")
        except Exception:
            pass
        return ctx
    except Exception:
        return None


def _make_request(endpoint: str, params: Mapping[str, Any]) -> dict[str, Any]:
    if not GS_API_KEY:
        return {}

    payload = dict(params)
    payload["softName"] = GS_SOFT_NAME
    payload["apiKey"] = GS_API_KEY

    try:
        query = urlencode(payload)
        url = f"{GS_BASE_URL}{endpoint}?{query}"
        request = urllib_request.Request(url)
        ctx = _create_ssl_context()
        if ctx is not None:
            with urllib_request.urlopen(request, timeout=TIMEOUT_SECONDS, context=ctx) as response:
                body = response.read().decode("utf-8")
        else:
            with urllib_request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        if not body:
            return {}
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else {"data": parsed}
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, ValueError):
        return {}
    except Exception:
        return {}


def _extract_code(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    if match:
        return match.group(1)
    return None


def _infer_set_code(code: str) -> int:
    if not code:
        return 0
    if code.startswith("6"):
        return 1
    if code.startswith("8"):
        return 2
    if code.startswith("4"):
        return 0
    return 0


def _looks_like_quote(node: Mapping[str, Any]) -> bool:
    candidate_keys = {
        "price",
        "latestPrice",
        "lastPrice",
        "currentPrice",
        "changePct",
        "change_pct",
        "pct_chg",
        "chgPct",
        "volume",
        "vol",
        "amount",
        "turnover",
        "preClose",
        "pre_close",
        "name",
        "stock_name",
    }
    return any(key in node for key in candidate_keys)


def _find_first_quote(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        if _looks_like_quote(payload):
            return dict(payload)
        for value in payload.values():
            quote = _find_first_quote(value)
            if quote:
                return quote
    elif isinstance(payload, list):
        for value in payload:
            quote = _find_first_quote(value)
            if quote:
                return quote
    return {}


def _normalized_quote(payload: Mapping[str, Any], code: str, sector_name: str) -> dict[str, Any]:
    quote = _find_first_quote(payload)
    if not quote:
        return {}

    price = to_float(
        quote.get("price")
        or quote.get("latestPrice")
        or quote.get("lastPrice")
        or quote.get("currentPrice")
        or quote.get("close"),
        None,
    )
    pre_close = to_float(quote.get("preClose") or quote.get("pre_close") or quote.get("yclose"), None)
    change_pct = to_float(
        quote.get("changePct")
        or quote.get("change_pct")
        or quote.get("pct_chg")
        or quote.get("chgPct")
        or quote.get("increaseRate"),
        None,
    )
    if change_pct is None and price is not None and pre_close not in (None, 0):
        change_pct = round(((price - pre_close) / pre_close) * 100, 2)

    volume = to_float(quote.get("volume") or quote.get("vol") or quote.get("tradeVolume"), None)
    amount = to_float(quote.get("amount") or quote.get("turnover"), None)

    return {
        "code": code,
        "name": as_text(quote.get("name") or quote.get("stock_name") or quote.get("secName") or sector_name, default=sector_name or "数据暂缺"),
        "price": price,
        "change_pct": change_pct,
        "volume": volume,
        "amount": amount,
        "pre_close": pre_close,
        "time": as_text(quote.get("time") or quote.get("datetime") or quote.get("updateTime") or quote.get("tradeTime"), default=_now_str()),
        "raw": quote,
        "source": "guosen",
    }


def _fetch_single_quote(code: str, set_code: int) -> dict[str, Any]:
    if not code or not GS_API_KEY:
        return {}
    payload = _make_request(
        "/gsnews/market/agentbot/queryHQInfo/1.0",
        {
            "code": code,
            "setCode": set_code,
            "target": 0,
        },
    )
    return _normalized_quote(payload, code, "")


def _category_label(category: str) -> str:
    return {
        "mainline": "主线",
        "watch": "次主线",
        "alive": "活口",
    }.get(category, category)


def _bucket_items(sector_matrix: Mapping[str, Any], category: str) -> list[dict[str, Any]]:
    rows = [dict(item) for item in safe_list(safe_dict(sector_matrix).get(category))]
    return rows[:TRACK_LIMIT_PER_BUCKET]


def _average_change(items: list[dict[str, Any]], key: str) -> float:
    values = []
    for item in items:
        value = to_float(item.get(key), None)
        if value is not None:
            values.append(value)
    return mean(values, 0.0)


def _build_history_windows(series: list[float]) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    if not series:
        return windows

    available = list(series)
    for window in HISTORY_WINDOWS:
        if not available:
            break
        bucket = available[-window:] if len(available) >= window else available[:]
        if not bucket:
            continue
        first = bucket[0]
        last = bucket[-1]
        delta = last - first if len(bucket) > 1 else 0.0
        trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
        windows[str(window)] = {
            "label": f"近{window}天",
            "points": len(bucket),
            "first": round(first, 2),
            "last": round(last, 2),
            "delta": round(delta, 2),
            "avg": round(mean(bucket, 0.0), 2),
            "trend": trend,
        }
    return windows


def _theme_dimension_score(item: Mapping[str, Any]) -> Optional[float]:
    score = to_float(
        item.get("score")
        or item.get("strength")
        or item.get("change")
        or item.get("change_pct"),
        None,
    )
    if score is None:
        return None
    return round(score, 2)


def _theme_alias_matches(name: str, aliases: list[str]) -> bool:
    target = as_text(name, default="").strip()
    if not target:
        return False
    for alias in aliases:
        alias = as_text(alias, default="").strip()
        if not alias:
            continue
        # Keep one-way fuzzy match to avoid short tokens (e.g. "电池") accidentally
        # matching longer aliases in unrelated families (e.g. "光伏电池组件").
        if alias == target or alias in target:
            return True
    return False


def _assign_theme_family(name: str) -> Optional[str]:
    target = as_text(name, default="").strip()
    if not target:
        return None
    for family in PREFERRED_THEME_NAMES:
        aliases = THEME_FAMILY_ALIASES.get(family, [family])
        if _theme_alias_matches(target, aliases):
            return family
    return None


def _query_rows(sql: str, params: Optional[tuple[Any, ...]] = None) -> list[dict[str, Any]]:
    if execute_query is None:
        return []
    try:
        rows = execute_query(sql, params or ())
    except Exception:
        return []
    return [dict(row) for row in rows]


def _is_excluded_concept_board(board_name: str) -> bool:
    name = as_text(board_name, default="")
    if not name:
        return True
    return any(keyword in name for keyword in CONCEPT_META_EXCLUDE_KEYWORDS)


def _is_excluded_hot_concept_board(board_name: str) -> bool:
    name = as_text(board_name, default="")
    if not name:
        return True
    if _is_excluded_concept_board(name):
        return True
    return any(keyword in name for keyword in HOT_CONCEPT_EXCLUDE_KEYWORDS)


def _load_latest_hot_concept_rank_map(limit: int = 40) -> dict[str, dict[str, Any]]:
    rows = _query_rows(
        """
        WITH latest_day AS (
            SELECT MAX(trade_date) AS trade_date
            FROM concept_board_daily
            WHERE market = 'CN_A'
        )
        SELECT board_code,
               board_name,
               trade_date,
               change_pct,
               stock_count
        FROM concept_board_daily
        WHERE market = 'CN_A'
          AND trade_date = (SELECT trade_date FROM latest_day)
        ORDER BY change_pct DESC NULLS LAST, stock_count DESC NULLS LAST, board_name ASC
        """
    )
    rank_map: dict[str, dict[str, Any]] = {}
    hot_rank = 0
    for row in rows:
        board_code = as_text(row.get("board_code"), default="").strip()
        board_name = as_text(row.get("board_name"), default="").strip()
        if not board_code or not board_name or _is_excluded_hot_concept_board(board_name):
            continue
        if board_code in rank_map:
            continue
        hot_rank += 1
        rank_map[board_code] = {
            "board_code": board_code,
            "board_name": board_name,
            "hot_rank": hot_rank,
            "change_pct": to_float(row.get("change_pct"), None),
            "stock_count": to_int(row.get("stock_count"), 0) or 0,
            "trade_date": row.get("trade_date"),
        }
        if len(rank_map) >= limit:
            break
    return rank_map


def _money_yi(value: Any) -> Optional[float]:
    amount = to_float(value, None)
    if amount is None:
        return None
    return round(amount / 100000000.0, 2)


def _kline_amount_to_yi(value: Any) -> Optional[float]:
    amount = to_float(value, None)
    if amount is None:
        return None
    # Robot-1 kline_daily.amount uses "thousand yuan"; convert to "yi yuan".
    return round(amount / KLINE_AMOUNT_TO_YI_DIVISOR, 2)


def _build_amount_windows(series: list[float]) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    if not series:
        return windows

    available = list(series)
    for window in HISTORY_WINDOWS:
        if not available:
            break
        bucket = available[-window:] if len(available) >= window else available[:]
        if not bucket:
            continue
        first = bucket[0]
        last = bucket[-1]
        delta = last - first if len(bucket) > 1 else 0.0
        trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
        windows[str(window)] = {
            "label": f"近{window}天",
            "points": len(bucket),
            "first": round(first, 2),
            "last": round(last, 2),
            "delta": round(delta, 2),
            "avg": round(mean(bucket, 0.0), 2),
            "trend": trend,
        }
    return windows


def _build_rank_windows(series: list[int]) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    if not series:
        return windows

    available = list(series)
    for window in HISTORY_WINDOWS:
        if not available:
            break
        bucket = available[-window:] if len(available) >= window else available[:]
        if not bucket:
            continue
        first = bucket[0]
        last = bucket[-1]
        # Rank smaller means stronger.
        delta = first - last if len(bucket) > 1 else 0
        trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
        windows[str(window)] = {
            "label": f"近{window}天",
            "points": len(bucket),
            "first": int(first),
            "last": int(last),
            "delta": int(delta),
            "avg": round(mean(bucket, 0.0), 2),
            "trend": trend,
        }
    return windows


def _load_market_total_amount_map(seed_days: int = 180) -> dict[Any, float]:
    rows = _query_rows(
        f"""
        SELECT trade_date, SUM(amount) AS market_total_amount
        FROM kline_daily
        WHERE market IN ('SH', 'SZ', 'BJ')
          AND trade_date >= CURRENT_DATE - INTERVAL '{seed_days} days'
        GROUP BY trade_date
        """
    )
    totals: dict[Any, float] = {}
    for row in rows:
        day = row.get("trade_date")
        total = to_float(row.get("market_total_amount"), None)
        if day is None or total is None or total <= 0:
            continue
        totals[day] = total
    return totals


def _load_market_stock_count_map(seed_days: int = 180) -> dict[Any, int]:
    rows = _query_rows(
        f"""
        SELECT trade_date, COUNT(*) AS market_stock_count
        FROM kline_daily
        WHERE market IN ('SH', 'SZ', 'BJ')
          AND trade_date >= CURRENT_DATE - INTERVAL '{seed_days} days'
        GROUP BY trade_date
        """
    )
    counts: dict[Any, int] = {}
    for row in rows:
        day = row.get("trade_date")
        cnt = to_int(row.get("market_stock_count"), None)
        if day is None or cnt is None or cnt <= 0:
            continue
        counts[day] = int(cnt)
    return counts


def _build_theme_family_amount_state(family: str, raw_rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    aliases = THEME_FAMILY_ALIASES.get(family, [family])
    matched: list[dict[str, Any]] = []
    for row in raw_rows:
        theme_name = as_text(row.get("theme_name"), default="")
        if not _theme_alias_matches(theme_name, aliases):
            continue
        amount_yi = _money_yi(row.get("total_amount"))
        if amount_yi is None:
            continue
        matched.append(
            {
                "theme_name": theme_name,
                "amount_yi": amount_yi,
                "leader_count": to_int(row.get("leader_count"), 0) or 0,
            }
        )

    if not matched:
        return None

    matched.sort(key=lambda item: (item["amount_yi"], item["theme_name"]), reverse=True)
    values = [item["amount_yi"] for item in matched if item["amount_yi"] is not None]
    if not values:
        return None

    # 每个维度每天只保留一个代表值，不做多子主题金额合计
    single_value = round(max(values), 2)
    best_row = matched[0]
    if single_value >= 20:
        state = "main"
    elif single_value >= 8:
        state = "watch"
    else:
        state = "alive"

    return {
        "name": family,
        "amount_yi": single_value,
        "leader": best_row["theme_name"],
        "category": "主题",
        "state": state,
        "source": UPSTREAM_DAILY_DB_SOURCE,
        "actual": True,
    }


def _load_theme_dimension_rows_from_db(seed_days: int = 120) -> list[dict[str, Any]]:
    cache_key = f"theme_money_rows:{seed_days}"
    cached = _THEME_DIMENSION_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    registry = load_concept_board_registry(seed_days=max(seed_days, 365))
    board_codes = sorted(registry.keys())
    placeholders = ",".join("%s" for _ in board_codes) if board_codes else ""
    combined: list[dict[str, Any]] = []
    if board_codes:
        rows = _query_rows(
            f"""
            WITH kd_recent AS (
                SELECT trade_date, code, market, amount
                FROM kline_daily
                WHERE market IN ('SH', 'SZ', 'BJ')
                  AND trade_date >= CURRENT_DATE - INTERVAL '{seed_days} days'
            ),
            board_components AS (
                SELECT board_code,
                       board_name,
                       split_part(stock_code, '.', 1) AS stock_code,
                       split_part(stock_code, '.', 2) AS stock_market
                FROM concept_components
                WHERE market = 'CN_A'
                  AND board_code IN ({placeholders})
            ),
            joined AS (
                SELECT kd.trade_date,
                       bc.board_code,
                       bc.board_name,
                       kd.code AS stock_code,
                       kd.market AS stock_market,
                       kd.amount
                FROM kd_recent kd
                JOIN board_components bc
                  ON bc.stock_code = kd.code
                 AND bc.stock_market = kd.market
            ),
            agg AS (
                SELECT trade_date,
                       board_code,
                       board_name,
                       SUM(amount) AS total_amount,
                       COUNT(*) AS stock_count
                FROM joined
                GROUP BY trade_date, board_code, board_name
            ),
            leader AS (
                SELECT trade_date,
                       board_code,
                       board_name,
                       stock_code,
                       stock_market,
                       amount,
                       ROW_NUMBER() OVER (
                           PARTITION BY trade_date, board_code
                           ORDER BY amount DESC, stock_code ASC
                       ) AS rn
                FROM joined
            )
            SELECT agg.trade_date,
                   agg.board_code,
                   agg.board_name AS theme_name,
                   agg.total_amount,
                   agg.stock_count,
                   leader.stock_code,
                   leader.stock_market,
                   COALESCE(sl.name, leader.stock_code) AS leader_name,
                   leader.amount AS leader_amount
            FROM agg
            LEFT JOIN leader
              ON leader.trade_date = agg.trade_date
             AND leader.board_code = agg.board_code
             AND leader.rn = 1
            LEFT JOIN stock_list sl
              ON sl.symbol = leader.stock_code
             AND sl.exchange = leader.stock_market
            ORDER BY agg.trade_date ASC, agg.total_amount DESC, agg.board_name ASC
            """,
            tuple(board_codes),
        )
        combined = [dict(row) for row in rows]

    if not combined:
        fallback_rows = _query_rows(
            f"""
            SELECT trade_date,
                   concept_code AS board_code,
                   concept_name AS board_name,
                   amount AS total_amount,
                   1 AS stock_count,
                   COALESCE(NULLIF(TRIM(concept_name), ''), concept_code) AS leader_name,
                   NULL AS stock_code,
                   NULL AS stock_market,
                   'upstream_concept_data' AS source
            FROM concept_data
            WHERE trade_date >= CURRENT_DATE - INTERVAL '{seed_days} days'
            ORDER BY trade_date ASC, amount DESC, concept_name ASC
            """,
            (),
        )
        combined = [
            dict(row)
            for row in fallback_rows
            if not _is_excluded_concept_board(as_text(row.get("board_name"), default=""))
        ]
    combined.sort(key=lambda row: (str(row.get("trade_date") or ""), row.get("theme_name") or ""))
    _THEME_DIMENSION_CACHE[cache_key] = [dict(item) for item in combined]
    return [dict(item) for item in combined]


def _build_theme_dimension_snapshots_from_rows(rows: list[dict[str, Any]], limit_days: int = 30) -> list[dict[str, Any]]:
    cache_key = f"theme_amount_snapshots:{limit_days}"
    if not rows:
        _THEME_DIMENSION_CACHE[cache_key] = []
        return []

    registry = load_concept_board_registry()
    market_total_map = _load_market_total_amount_map(seed_days=max(180, limit_days * 8))
    source_name = as_text(next((row.get("source") for row in rows if row.get("source")), None), default=UPSTREAM_BOARD_SOURCE)
    date_values: list[Any] = []
    for row in rows:
        trade_date = row.get("trade_date")
        if trade_date is None:
            continue
        if isinstance(trade_date, datetime):
            date_values.append(trade_date.date())
        else:
            try:
                date_values.append(datetime.strptime(str(trade_date), "%Y-%m-%d").date())
            except Exception:
                continue

    if not date_values:
        _THEME_DIMENSION_CACHE[cache_key] = []
        return []

    day_axis = sorted(set(date_values))[-limit_days:]
    day_rows: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        trade_date = row.get("trade_date")
        if trade_date is None:
            continue
        if isinstance(trade_date, datetime):
            day_key = trade_date.date()
        else:
            try:
                day_key = datetime.strptime(str(trade_date), "%Y-%m-%d").date()
            except Exception:
                continue
        day_rows.setdefault(day_key, []).append(row)

    snapshots: list[dict[str, Any]] = []
    for day in day_axis:
        raw_rows = day_rows.get(day, [])
        market_total = to_float(market_total_map.get(day) or market_total_map.get(str(day)), None)
        ranked_rows = sorted(
            raw_rows,
            key=lambda row: (
                -(to_float(row.get("total_amount"), 0.0) or 0.0),
                as_text(row.get("theme_name"), default=""),
            ),
        )

        theme_map: dict[str, dict[str, Any]] = {}
        for rank_index, row in enumerate(ranked_rows, start=1):
            board_code = as_text(row.get("board_code"), default="").strip()
            registry_row = registry.get(board_code, {})
            theme_name = as_text(registry_row.get("board_name") or row.get("theme_name"), default="").strip()
            amount_raw = to_float(row.get("total_amount"), None)
            if not board_code or not theme_name or amount_raw is None or amount_raw <= 0:
                continue
            if _is_excluded_concept_board(theme_name):
                continue
            amount_yi = _kline_amount_to_yi(amount_raw)
            if amount_yi is None:
                continue

            ratio_pct = round((amount_raw / market_total) * 100.0, 4) if market_total and market_total > 0 else None
            leader_name = as_text(row.get("leader_name"), default="数据暂缺")
            leader_code = as_text(row.get("stock_code"), default="")
            if leader_code:
                leader_name = f"{leader_name}({leader_code})"

            state = "main" if rank_index <= 3 else "watch" if rank_index <= 8 else "alive"
            theme_map[theme_name] = {
                "code": board_code,
                "board_code": board_code,
                "board_name": theme_name,
                "board_type": "concept",
                "name": theme_name,
                "amount_yi": amount_yi,
                "ratio_pct": ratio_pct,
                "rank": rank_index,
                "leader": leader_name,
                "category": "概念",
                "state": state,
                "stock_count": to_int(row.get("stock_count"), 0) or 0,
                "market_total_amount_yi": _kline_amount_to_yi(market_total),
                "source": source_name,
                "board_source": "ths",
                "actual": True,
            }

        snapshots.append(
            {
                "timestamp": datetime.combine(day, dt_time(0, 0)),
                "label": day.strftime("%m-%d"),
                "themes": theme_map,
                "is_daily": True,
                "is_actual": bool(raw_rows),
                "market_total_amount_yi": _kline_amount_to_yi(market_total),
                "source": source_name,
            }
        )

    _THEME_DIMENSION_CACHE[cache_key] = [dict(item) for item in snapshots]
    return [dict(item) for item in snapshots]


def _load_theme_dimension_snapshots(limit_days: int = 30) -> list[dict[str, Any]]:
    cache_key = f"theme_amount_snapshots:{limit_days}"
    cached = _THEME_DIMENSION_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    rows = _load_theme_dimension_rows_from_db(seed_days=max(180, limit_days * 8))
    snapshots = _build_theme_dimension_snapshots_from_rows(rows, limit_days=limit_days)
    _THEME_DIMENSION_CACHE[cache_key] = [dict(item) for item in snapshots]
    return snapshots

def _load_industry_dimension_rows_from_db(seed_days: int = 120) -> list[dict[str, Any]]:
    cache_key = f"industry_money_rows:{seed_days}"
    cached = _THEME_DIMENSION_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    rows = _query_rows(
        f"""
        WITH base AS (
            SELECT kd.trade_date,
                   COALESCE(NULLIF(TRIM(sl.industry), ''), '未分类') AS industry_name,
                   kd.code AS stock_code,
                   kd.market AS stock_market,
                   kd.amount
            FROM kline_daily kd
            LEFT JOIN stock_list sl
              ON sl.symbol = kd.code
             AND sl.exchange = kd.market
            WHERE kd.market IN ('SH', 'SZ', 'BJ')
              AND kd.trade_date >= CURRENT_DATE - INTERVAL '{seed_days} days'
        ),
        code_map AS (
            SELECT DISTINCT ON (industry_name)
                   industry_name,
                   industry_code
            FROM industry_board_daily
            WHERE trade_date >= CURRENT_DATE - INTERVAL '{seed_days} days'
              AND industry_name IS NOT NULL
              AND industry_code IS NOT NULL
            ORDER BY industry_name, trade_date DESC
        ),
        agg AS (
            SELECT trade_date,
                   base.industry_name,
                   COALESCE(code_map.industry_code, '') AS industry_code,
                   SUM(amount) AS total_amount,
                   COUNT(*) AS stock_count
            FROM base
            LEFT JOIN code_map
              ON code_map.industry_name = base.industry_name
            GROUP BY trade_date, base.industry_name, code_map.industry_code
        ),
        leader AS (
            SELECT trade_date,
                   industry_name,
                   stock_code,
                   stock_market,
                   amount,
                   ROW_NUMBER() OVER (
                       PARTITION BY trade_date, industry_name
                       ORDER BY amount DESC, stock_code ASC
                   ) AS rn
            FROM base
        )
        SELECT agg.trade_date,
               agg.industry_code,
               agg.industry_name,
               agg.total_amount,
               agg.stock_count,
               leader.stock_code,
               leader.stock_market,
               COALESCE(sl.name, leader.stock_code) AS leader_name,
               leader.amount AS leader_amount
        FROM agg
        LEFT JOIN leader
          ON leader.trade_date = agg.trade_date
         AND leader.industry_name = agg.industry_name
         AND leader.rn = 1
        LEFT JOIN stock_list sl
          ON sl.symbol = leader.stock_code
         AND sl.exchange = leader.stock_market
        ORDER BY agg.trade_date ASC, agg.total_amount DESC, agg.industry_name ASC
        """
    )

    combined = [dict(row) for row in rows]
    combined.sort(key=lambda row: (str(row.get("trade_date") or ""), row.get("industry_name") or ""))
    _THEME_DIMENSION_CACHE[cache_key] = [dict(item) for item in combined]
    return [dict(item) for item in combined]


def _build_industry_dimension_snapshots_from_rows(rows: list[dict[str, Any]], limit_days: int = 30) -> list[dict[str, Any]]:
    cache_key = f"industry_amount_snapshots:{limit_days}"
    if not rows:
        _THEME_DIMENSION_CACHE[cache_key] = []
        return []

    market_total_map = _load_market_total_amount_map(seed_days=max(180, limit_days * 8))
    market_stock_count_map = _load_market_stock_count_map(seed_days=max(180, limit_days * 8))
    max_market_stock_count = max(market_stock_count_map.values(), default=0)
    min_coverage_ratio = 0.75
    date_values: list[Any] = []
    for row in rows:
        trade_date = row.get("trade_date")
        if trade_date is None:
            continue
        if isinstance(trade_date, datetime):
            date_values.append(trade_date.date())
        else:
            try:
                date_values.append(datetime.strptime(str(trade_date), "%Y-%m-%d").date())
            except Exception:
                continue

    if not date_values:
        _THEME_DIMENSION_CACHE[cache_key] = []
        return []

    day_axis = sorted(set(date_values))[-limit_days:]
    day_rows: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        trade_date = row.get("trade_date")
        if trade_date is None:
            continue
        if isinstance(trade_date, datetime):
            day_key = trade_date.date()
        else:
            try:
                day_key = datetime.strptime(str(trade_date), "%Y-%m-%d").date()
            except Exception:
                continue
        day_rows.setdefault(day_key, []).append(row)

    snapshots: list[dict[str, Any]] = []
    for day in day_axis:
        raw_rows = day_rows.get(day, [])
        market_total = to_float(market_total_map.get(day) or market_total_map.get(str(day)), None)
        day_stock_count = to_int(
            market_stock_count_map.get(day) or market_stock_count_map.get(str(day)),
            0,
        ) or 0
        coverage_ratio = (
            round(day_stock_count / max_market_stock_count, 4)
            if max_market_stock_count > 0
            else 1.0
        )
        scale_factor = round(1.0 / coverage_ratio, 6) if coverage_ratio > 0 else 1.0
        dimension_map: dict[str, dict[str, Any]] = {}
        ranked_rows = sorted(
            raw_rows,
            key=lambda row: (
                -(to_float(row.get("total_amount"), 0.0) or 0.0),
                as_text(row.get("industry_name"), default=""),
            ),
        )

        for rank_index, row in enumerate(ranked_rows, start=1):
            industry_name = as_text(row.get("industry_name"), default="").strip()
            amount_raw = to_float(row.get("total_amount"), None)
            if not industry_name or amount_raw is None or amount_raw <= 0:
                continue
            amount_yi = _kline_amount_to_yi(amount_raw)
            if amount_yi is None:
                continue
            comparable_amount_yi = round(amount_yi * scale_factor, 2)
            ratio_pct = round((amount_raw / market_total) * 100.0, 4) if market_total and market_total > 0 else None
            leader_name = as_text(row.get("leader_name"), default="数据暂缺")
            leader_code = as_text(row.get("stock_code"), default="")
            if leader_code:
                leader_name = f"{leader_name}({leader_code})"
            state = "main" if rank_index <= 3 else "watch" if rank_index <= 8 else "alive"
            dimension_map[industry_name] = {
                "board_type": "industry",
                "board_code": industry_name,
                "board_name": industry_name,
                "name": industry_name,
                "amount_yi": amount_yi,
                "comparable_amount_yi": comparable_amount_yi,
                "ratio_pct": ratio_pct,
                "rank": rank_index,
                "leader": leader_name,
                "category": "行业",
                "state": state,
                "stock_count": to_int(row.get("stock_count"), 0) or 0,
                "market_total_amount_yi": _kline_amount_to_yi(market_total),
                "source": UPSTREAM_STOCK_SOURCE,
                "board_source": "ths",
                "actual": True,
            }

        snapshots.append(
            {
                "timestamp": datetime.combine(day, datetime.min.time()),
                "label": day.strftime("%m-%d"),
                "dimensions": dimension_map,
                "is_daily": True,
                "is_actual": bool(raw_rows),
                "market_total_amount_yi": _kline_amount_to_yi(market_total),
                "source": UPSTREAM_STOCK_SOURCE,
                "market_stock_count": day_stock_count,
                "market_stock_coverage_ratio": coverage_ratio,
                "coverage_threshold": min_coverage_ratio,
                "coverage_mode": "comparable_amount",
            }
        )

    _THEME_DIMENSION_CACHE[cache_key] = [dict(item) for item in snapshots]
    return [dict(item) for item in snapshots]


def _build_theme_dimension_snapshots_from_current(
    current_by_category: Mapping[str, list[dict[str, Any]]],
    limit_days: int = 30,
) -> list[dict[str, Any]]:
    cache_key = f"theme_rotation_fallback_snapshots:{limit_days}"
    cached = _THEME_DIMENSION_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    rows: list[dict[str, Any]] = []
    for category, items in current_by_category.items():
        for item in safe_list(items):
            name = as_text(item.get("name"), default="").strip()
            if not name:
                continue
            raw_series = [to_float(value, None) for value in safe_list(item.get("history_series"))]
            if not raw_series:
                fallback_value = to_float(item.get("score"), to_float(item.get("strength"), 0.0)) or 0.0
                raw_series = [fallback_value]
            first_value = next((value for value in raw_series if value is not None), 0.0) or 0.0
            padded_series = list(raw_series[-limit_days:])
            if len(padded_series) < limit_days:
                padded_series = [first_value] * (limit_days - len(padded_series)) + padded_series
            if not padded_series:
                continue

            leader_name = as_text(item.get("leader"), default="数据暂缺")
            rows.append(
                {
                    "trade_date": None,
                    "board_code": f"rotation_{category}_{name}",
                    "board_name": name,
                    "board_type": "concept",
                    "total_amount": None,
                    "stock_count": 0,
                    "stock_code": "",
                    "stock_market": "",
                    "leader_name": leader_name,
                    "leader_amount": None,
                    "source": UPSTREAM_ROTATION_FALLBACK_SOURCE,
                    "history_series": padded_series,
                    "category": category,
                    "state": as_text(item.get("state"), default=category),
                }
            )

    if not rows:
        _THEME_DIMENSION_CACHE[cache_key] = []
        return []

    snapshots: list[dict[str, Any]] = []
    for index in range(limit_days):
        day_key = f"D-{limit_days - index - 1}" if index < limit_days - 1 else "今日"
        theme_map: dict[str, dict[str, Any]] = {}
        for rank_index, row in enumerate(rows, start=1):
            series = safe_list(row.get("history_series"))
            value = series[index] if index < len(series) else series[-1]
            amount_yi = to_float(value, None)
            if amount_yi is None:
                continue
            theme_map[as_text(row.get("board_name"), default="数据暂缺")] = {
                "code": as_text(row.get("board_code"), default=""),
                "board_code": as_text(row.get("board_code"), default=""),
                "board_type": as_text(row.get("board_type"), default="concept"),
                "board_name": as_text(row.get("board_name"), default=""),
                "theme_name": as_text(row.get("board_name"), default=""),
                "name": as_text(row.get("board_name"), default=""),
                "amount_yi": round(amount_yi, 2),
                "ratio_pct": None,
                "rank": rank_index,
                "leader": as_text(row.get("leader_name"), default="数据暂缺"),
                "category": "概念",
                "state": as_text(row.get("state"), default="watch"),
                "stock_count": 0,
                "market_total_amount_yi": None,
                "source": UPSTREAM_ROTATION_FALLBACK_SOURCE,
                "board_source": "ths",
                "actual": False,
            }
        snapshots.append(
            {
                "timestamp": datetime.combine(date.today(), dt_time(0, 0)),
                "label": day_key,
                "themes": theme_map,
                "is_daily": True,
                "is_actual": False,
                "market_total_amount_yi": None,
                "source": UPSTREAM_ROTATION_FALLBACK_SOURCE,
            }
        )

    _THEME_DIMENSION_CACHE[cache_key] = [dict(item) for item in snapshots]
    return [dict(item) for item in snapshots]


def _load_industry_dimension_snapshots(limit_days: int = 30) -> list[dict[str, Any]]:
    cache_key = f"industry_amount_snapshots:{limit_days}"
    cached = _THEME_DIMENSION_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

    rows = _load_industry_dimension_rows_from_db(seed_days=max(180, limit_days * 8))
    return _build_industry_dimension_snapshots_from_rows(rows, limit_days=limit_days)


def _snapshot_dimension_map(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return safe_dict(snapshot.get("dimensions") or snapshot.get("themes") or snapshot.get("items"))


def _build_dimension_curves_from_snapshots(
    snapshots: list[dict[str, Any]] | None,
    limit: int = 30,
    top_n: int = 12,
    source_name: str = "leader_stock_daily",
    preferred_order: Optional[list[str]] = None,
    dimension_type: str = "concept",
) -> dict[str, Any]:
    snapshots = [dict(item) for item in snapshots] if snapshots else []
    if not snapshots:
        return {
            "timeline": [],
            "dimensions": [],
            "source": source_name,
            "updated_at": _now_str(),
            "window_days": limit,
            "fill_mode": "actual_amount_daily",
            "unit": "亿",
        }

    timeline = [as_text(item.get("label"), default="") for item in snapshots]
    amount_series: dict[str, list[Optional[float]]] = {}
    comparable_amount_series: dict[str, list[Optional[float]]] = {}
    ratio_series: dict[str, list[Optional[float]]] = {}
    rank_series: dict[str, list[Optional[int]]] = {}
    theme_meta: dict[str, dict[str, Any]] = {}

    for index, snapshot in enumerate(snapshots):
        theme_map = _snapshot_dimension_map(snapshot)
        for name, info in theme_map.items():
            info = safe_dict(info)
            amount_yi = to_float(info.get("amount_yi"), None)
            if amount_yi is None:
                continue
            amount_bucket = amount_series.setdefault(name, [None] * len(snapshots))
            amount_bucket[index] = round(amount_yi, 2)
            comparable_amount_yi = to_float(info.get("comparable_amount_yi"), None)
            comparable_bucket = comparable_amount_series.setdefault(name, [None] * len(snapshots))
            comparable_bucket[index] = round(comparable_amount_yi, 2) if comparable_amount_yi is not None else None
            ratio_value = to_float(info.get("ratio_pct"), None)
            ratio_bucket = ratio_series.setdefault(name, [None] * len(snapshots))
            ratio_bucket[index] = round(ratio_value, 4) if ratio_value is not None else None
            rank_value = to_int(info.get("rank"), None)
            rank_bucket = rank_series.setdefault(name, [None] * len(snapshots))
            rank_bucket[index] = int(rank_value) if rank_value is not None else None
            theme_meta[name] = {
                "board_type": as_text(info.get("board_type"), default=dimension_type),
                "board_code": as_text(info.get("code") or info.get("board_code"), default=""),
                "leader": as_text(info.get("leader"), default="数据暂缺"),
                "category": as_text(info.get("category"), default=""),
                "state": as_text(info.get("state"), default=""),
                "stock_count": to_int(info.get("stock_count"), 0) or 0,
                "market_total_amount_yi": to_float(info.get("market_total_amount_yi"), None),
            }

    hot_rank_map = _load_latest_hot_concept_rank_map(limit=max(top_n * 3, 40)) if dimension_type == "concept" else {}
    hot_rank_name_map = {item["board_name"]: item for item in hot_rank_map.values()}
    preferred_order_map = {name: index for index, name in enumerate(preferred_order or [])}
    latest_ranks = {
        name: next((value for value in reversed(values) if value is not None), None)
        for name, values in rank_series.items()
    }
    latest_values = {
        name: next((value for value in reversed(values) if value is not None), None)
        for name, values in amount_series.items()
    }
    latest_ratio_values = {
        name: next((value for value in reversed(values) if value is not None), None)
        for name, values in ratio_series.items()
    }
    cumulative_values = {
        name: round(sum(value for value in values if value is not None), 2)
        for name, values in amount_series.items()
    }
    candidate_names = list(amount_series.keys())
    if dimension_type == "concept" and hot_rank_map:
        hot_candidate_names = [
            name for name in candidate_names
            if theme_meta.get(name, {}).get("board_code") in hot_rank_map or name in hot_rank_name_map
        ]
        if hot_candidate_names:
            candidate_names = hot_candidate_names
    ranked_names = sorted(
        candidate_names,
        key=lambda name: (
            (
                hot_rank_map.get(theme_meta.get(name, {}).get("board_code", ""), {}).get("hot_rank")
                or hot_rank_name_map.get(name, {}).get("hot_rank")
                or 9_999
            ),
            latest_ranks.get(name, 9_999) if latest_ranks.get(name, None) is not None else 9_999,
            -(latest_ratio_values.get(name) or 0.0),
            -(latest_values.get(name) or 0.0),
            0 if name in preferred_order_map else 1,
            preferred_order_map.get(name, 999),
            -(cumulative_values.get(name) or 0.0),
        ),
    )[:top_n]

    dimensions: list[dict[str, Any]] = []
    for index, name in enumerate(ranked_names):
        raw_series = amount_series.get(name, [])
        raw_comparable_series = comparable_amount_series.get(name, [])
        raw_ratio_series = ratio_series.get(name, [])
        raw_rank_series = rank_series.get(name, [])
        actual_values = [float(value) for value in raw_series if value is not None]
        comparable_values = [float(value) for value in raw_comparable_series if value is not None]
        actual_ratios = [float(value) for value in raw_ratio_series if value is not None]
        actual_ranks = [int(value) for value in raw_rank_series if value is not None]
        if not actual_values:
            continue

        if not any(value is not None for value in raw_series):
            continue

        latest_actual = actual_values[-1]
        latest_comparable = comparable_values[-1] if comparable_values else None
        first_actual = actual_values[0]
        delta = latest_actual - first_actual if len(actual_values) > 1 else 0.0
        if comparable_values:
            first_comparable = comparable_values[0]
            comparable_delta = latest_comparable - first_comparable if len(comparable_values) > 1 else 0.0
        else:
            comparable_delta = None
        trend = "up" if delta > 0 else "down" if delta < 0 else "flat"
        windows = _build_amount_windows(actual_values)
        ratio_windows = _build_amount_windows(actual_ratios) if actual_ratios else {}
        rank_windows = _build_rank_windows(actual_ranks) if actual_ranks else {}
        meta = theme_meta.get(name, {})
        latest_day_info = next(
            (_snapshot_dimension_map(snapshot).get(name) for snapshot in reversed(snapshots) if name in _snapshot_dimension_map(snapshot)),
            {},
        )
        board_code = as_text(meta.get("board_code") or safe_dict(latest_day_info).get("code") or safe_dict(latest_day_info).get("board_code"), default="")
        hot_info = hot_rank_map.get(board_code) or hot_rank_name_map.get(name, {})
        display_name = as_text(hot_info.get("board_name"), default=name) or name
        leader_name = as_text(safe_dict(latest_day_info).get("leader"), default=meta.get("leader", "数据暂缺"))
        family_state = meta.get("state", "alive")
        if not family_state:
            family_state = "main" if index < 3 else "watch" if index < 7 else "alive"
        latest_ratio = actual_ratios[-1] if actual_ratios else None
        first_ratio = actual_ratios[0] if actual_ratios else None
        ratio_delta = (latest_ratio - first_ratio) if latest_ratio is not None and first_ratio is not None else None
        latest_rank = actual_ranks[-1] if actual_ranks else None
        first_rank = actual_ranks[0] if actual_ranks else None
        rank_delta = (first_rank - latest_rank) if latest_rank is not None and first_rank is not None else None
        dimensions.append(
            {
                "name": display_name,
                "board_code": board_code,
                "board_name": name,
                "board_type": as_text(meta.get("board_type"), default=dimension_type),
                "display_name": display_name,
                "leader": leader_name,
                "category": meta.get("category", ""),
                "source_type": dimension_type,
                "state": family_state,
                "series": [round(value, 2) if value is not None else None for value in raw_series],
                "series_comparable_amount_yi": [round(value, 2) if value is not None else None for value in raw_comparable_series],
                "latest": round(latest_actual, 2),
                "delta": round(delta, 2),
                "peak": round(max(actual_values), 2),
                "points": len(actual_values),
                "actual_points": len(actual_values),
                "filled_points": len(raw_series),
                "trend": trend,
                "windows": windows,
                "ratio_windows": ratio_windows,
                "rank_windows": rank_windows,
                "series_ratio_pct": [round(value, 4) if value is not None else None for value in raw_ratio_series],
                "series_rank": [int(value) if value is not None else None for value in raw_rank_series],
                "unit": "亿",
                "latest_amount_yi": round(latest_actual, 2),
                "delta_amount_yi": round(delta, 2),
                "peak_amount_yi": round(max(actual_values), 2),
                "latest_comparable_amount_yi": round(latest_comparable, 2) if latest_comparable is not None else None,
                "delta_comparable_amount_yi": round(comparable_delta, 2) if comparable_delta is not None else None,
                "latest_ratio_pct": round(latest_ratio, 4) if latest_ratio is not None else None,
                "delta_ratio_pct": round(ratio_delta, 4) if ratio_delta is not None else None,
                "latest_rank": latest_rank,
                "rank_delta": rank_delta,
                "hot_rank": to_int(hot_info.get("hot_rank"), None),
                "hot_change_pct": round(to_float(hot_info.get("change_pct"), 0.0) or 0.0, 2) if hot_info else None,
                "stock_count": meta.get("stock_count", 0),
                "market_total_amount_yi": meta.get("market_total_amount_yi"),
                "source": source_name,
            }
        )

    return {
        "timeline": timeline,
        "dimensions": dimensions,
        "source": source_name,
        "window_days": limit,
        "fill_mode": "amount_share_rank_daily",
        "ranking_basis": "ths_hot_concept_change_pct" if dimension_type == "concept" and hot_rank_map else "amount_share_rank_daily",
        "coverage_mode": "comparable_amount"
        if any(snapshot.get("coverage_mode") == "comparable_amount" for snapshot in snapshots)
        else "raw_amount",
        "market_stock_coverage_ratio": next(
            (to_float(snapshot.get("market_stock_coverage_ratio"), None) for snapshot in reversed(snapshots) if snapshot.get("market_stock_coverage_ratio") is not None),
            None,
        ),
        "unit": "亿",
        "updated_at": _now_str(),
    }


def _build_theme_dimension_curves(
    current_by_category: Mapping[str, list[dict[str, Any]]],
    limit: int = 30,
    top_n: int = 12,
    snapshots_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshots = [dict(item) for item in snapshots_override] if snapshots_override else _load_theme_dimension_snapshots(limit_days=limit)
    if not snapshots:
        snapshots = _build_theme_dimension_snapshots_from_current(current_by_category, limit_days=limit)
    source_name = as_text(safe_dict(snapshots[-1] if snapshots else {}).get("source"), default=UPSTREAM_BOARD_SOURCE)
    return _build_dimension_curves_from_snapshots(
        snapshots,
        limit=limit,
        top_n=top_n,
        source_name=source_name,
        preferred_order=PREFERRED_THEME_NAMES,
        dimension_type="concept",
    )


def _build_industry_dimension_curves(
    limit: int = 30,
    top_n: int = 12,
    snapshots_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshots = [dict(item) for item in snapshots_override] if snapshots_override else _load_industry_dimension_snapshots(limit_days=limit)
    source_name = as_text(safe_dict(snapshots[-1] if snapshots else {}).get("source"), default=UPSTREAM_STOCK_SOURCE)
    return _build_dimension_curves_from_snapshots(
        snapshots,
        limit=limit,
        top_n=top_n,
        source_name=source_name,
        preferred_order=PREFERRED_INDUSTRY_NAMES,
        dimension_type="industry",
    )


def _parse_snapshot_time(value: Any) -> Optional[datetime]:
    text = as_text(value, default="").strip()
    if not text:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d_%H%M%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _load_rotation_history_curve(category: str, limit: int = 20) -> list[float]:
    cache_key = f"{category}:{limit}"
    if cache_key in _ROTATION_HISTORY_CACHE:
        return list(_ROTATION_HISTORY_CACHE[cache_key])

    samples: list[tuple[datetime, float]] = []
    if REPORTS_DIR.exists():
        for path in sorted(REPORTS_DIR.glob("main_central_hub_*.json")):
            if path.name == "main_central_hub_latest.json":
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue

            market_context = safe_dict(payload.get("market_context"))
            rows = [dict(item) for item in safe_list(market_context.get(category))]
            if not rows:
                continue

            leader = max(
                rows,
                key=lambda item: to_float(item.get("score") or item.get("strength") or item.get("change"), -10_000.0) or -10_000.0,
            )
            value = to_float(leader.get("score") or leader.get("strength") or leader.get("change"), None)
            if value is None:
                continue

            created_at = _parse_snapshot_time(safe_dict(payload.get("meta")).get("created_at"))
            if created_at is None:
                created_at = _parse_snapshot_time(market_context.get("updated_at")) or datetime.fromtimestamp(path.stat().st_mtime)
            samples.append((created_at, round(value, 2)))

    samples.sort(key=lambda item: item[0])
    series = [value for _, value in samples[-limit:]]
    _ROTATION_HISTORY_CACHE[cache_key] = series
    return list(series)


def _build_category_signal(
    category: str,
    previous_items: list[dict[str, Any]],
    current_items: list[dict[str, Any]],
    market_metrics: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    market_metrics = safe_dict(market_metrics)
    failed_bar_rate = to_float(market_metrics.get("failed_bar_rate"), 0.0) or 0.0
    limit_down_total = max(to_int(market_metrics.get("limit_down_total"), 0) or 0, 0)

    prev_avg = _average_change(previous_items, "change")
    current_avg = _average_change(current_items, "live_change")
    if not current_items or all(item.get("live_change") is None for item in current_items):
        current_avg = _average_change(current_items, "previous_change")

    if failed_bar_rate >= 0.3 or limit_down_total >= 10:
        signal = "防守"
        note = f"风险偏高，{_category_label(category)}更适合观察承接。"
    elif category == "mainline" and current_avg >= 0.8:
        signal = "延续"
        note = f"主线承接尚可，盘中仍在确认核心方向。"
    elif category == "watch" and current_avg > max(prev_avg, 0.0):
        signal = "切换"
        note = f"次主线开始加强，注意是否承接主线资金。"
    elif category == "alive" and current_avg > 0 and prev_avg <= 0:
        signal = "补涨"
        note = f"活口修复，适合继续盯盘中轮动。"
    elif current_avg > prev_avg:
        signal = "延续"
        note = f"盘中强于昨收，方向保持延续。"
    elif current_avg < prev_avg and current_avg > 0:
        signal = "补涨"
        note = f"仍有正反馈，但力度较昨收收敛。"
    else:
        signal = "观望"
        note = f"暂未形成有效切换，等待进一步确认。"

    return {
        "signal": signal,
        "note": note,
        "previous_avg": round(prev_avg, 2),
        "current_avg": round(current_avg, 2),
        "realtime_allowed": bool(GS_API_KEY and _is_trading_session()),
    }


def _summarize_category(items: list[dict[str, Any]], use_live: bool) -> str:
    if not items:
        return "暂无"
    parts: list[str] = []
    for item in items[:2]:
        name = as_text(item.get("name"), default="数据暂缺")
        leader = as_text(item.get("leader"), default="")
        if leader and leader != "数据暂缺":
            name = f"{name} · {leader}"
        pct = item.get("live_change") if use_live else item.get("change")
        pct_num = to_float(pct, None)
        if pct_num is not None:
            name = f"{name} {pct_num:+.2f}%"
        parts.append(name)
    return " / ".join(parts)


def build_rotation_context(
    sector_matrix: Optional[Mapping[str, Any]],
    market_metrics: Optional[Mapping[str, Any]] = None,
    review_date: Optional[str] = None,
    allow_live: bool = True,
    current_time: Optional[datetime] = None,
    concept_dimension_snapshots: list[dict[str, Any]] | None = None,
    theme_dimension_snapshots: list[dict[str, Any]] | None = None,
    industry_dimension_snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    构建板块轮动上下文。

    只在板块轮动层允许使用国信实时行情，其他市场结构仍保持 Robot-1 盘后底座。
    """
    sector_matrix = safe_dict(sector_matrix)
    market_metrics = safe_dict(market_metrics)
    now = current_time or datetime.now()
    session_open = _is_trading_session(now)
    live_allowed = bool(allow_live and session_open and GS_API_KEY)

    current_by_category: dict[str, list[dict[str, Any]]] = {}
    previous_by_category: dict[str, list[dict[str, Any]]] = {}
    signal_by_category: dict[str, dict[str, Any]] = {}
    quote_pool: dict[str, dict[str, Any]] = {}

    tracked_quotes: list[tuple[str, str, int]] = []
    seen_codes: set[str] = set()
    if live_allowed:
        history_curves = {
            category: _load_rotation_history_curve(category, limit=20)
            for category in ("mainline", "watch", "alive")
        }
    else:
        history_curves = {category: [] for category in ("mainline", "watch", "alive")}

    for category in ("mainline", "watch", "alive"):
        previous_rows = _bucket_items(sector_matrix, category)
        previous_by_category[category] = [
            {
                "name": as_text(item.get("name"), default="数据暂缺"),
                "leader": as_text(item.get("leader"), default="数据暂缺"),
                "change": to_float(item.get("change"), None),
                "strength": to_float(item.get("strength"), None),
                "state": as_text(item.get("state"), default=category),
                "judgment": as_text(item.get("judgment"), default=""),
                "score": to_float(item.get("score"), None),
                "history": safe_dict(item.get("history")),
                "history_windows": safe_dict(item.get("history_windows")),
                "history_series": safe_list(item.get("history_series")),
                "source": item.get("source_type") or UPSTREAM_SOURCE,
            }
            for item in previous_rows
        ]
        if history_curves.get(category):
            for item in previous_by_category[category]:
                if not item.get("history_series"):
                    item["history_series"] = list(history_curves[category])

        if live_allowed:
            for item in previous_rows:
                leader_code = _extract_code(as_text(item.get("leader"), default=""))
                if not leader_code or leader_code in seen_codes:
                    continue
                seen_codes.add(leader_code)
                tracked_quotes.append((leader_code, as_text(item.get("name"), default=""), _infer_set_code(leader_code)))

    if live_allowed:
        for code, sector_name, set_code in tracked_quotes:
            quote = _fetch_single_quote(code, set_code)
            if quote:
                quote["sector_name"] = sector_name
                quote_pool[code] = quote

    for category in ("mainline", "watch", "alive"):
        current_rows: list[dict[str, Any]] = []
        for item in previous_by_category.get(category, []):
            leader_code = _extract_code(item.get("leader") or "")
            live_quote = quote_pool.get(leader_code or "")
            live_change = to_float(live_quote.get("change_pct"), None) if live_quote else None
            current_rows.append(
                {
                    "name": item.get("name"),
                    "leader": item.get("leader"),
                    "leader_code": leader_code,
                    "state": item.get("state"),
                    "previous_change": item.get("change"),
                    "previous_strength": item.get("strength"),
                    "live_change": live_change,
                    "live_price": to_float(live_quote.get("price"), None) if live_quote else None,
                    "live_volume": to_float(live_quote.get("volume"), None) if live_quote else None,
                    "live_amount": to_float(live_quote.get("amount"), None) if live_quote else None,
                    "live_time": live_quote.get("time") if live_quote else None,
                    "signal": None,
                    "reason": None,
                    "history": item.get("history", {}),
                    "history_windows": item.get("history_windows", {}),
                    "history_series": safe_list(item.get("history_series")),
                    "source": "guosen" if live_quote else UPSTREAM_SOURCE,
                }
            )
        if history_curves.get(category):
            for item in current_rows:
                if not item.get("history_series"):
                    item["history_series"] = list(history_curves[category])
        signal_by_category[category] = _build_category_signal(category, previous_by_category.get(category, []), current_rows, market_metrics)
        for item in current_rows:
            item["signal"] = signal_by_category[category]["signal"]
            item["reason"] = signal_by_category[category]["note"]
        current_by_category[category] = current_rows

    if live_allowed:
        concept_dimensions = _build_theme_dimension_curves(
            current_by_category,
            limit=30,
            top_n=20,
            snapshots_override=concept_dimension_snapshots or theme_dimension_snapshots,
        )
        industry_dimensions = _build_industry_dimension_curves(
            limit=30,
            top_n=20,
            snapshots_override=industry_dimension_snapshots,
        )
    else:
        fallback_snapshots = concept_dimension_snapshots or theme_dimension_snapshots
        if not fallback_snapshots:
            fallback_snapshots = _build_theme_dimension_snapshots_from_current(current_by_category, limit_days=30)

        concept_dimensions = _build_dimension_curves_from_snapshots(
            fallback_snapshots,
            limit=30,
            top_n=20,
            source_name=UPSTREAM_ROTATION_FALLBACK_SOURCE,
            preferred_order=PREFERRED_THEME_NAMES,
            dimension_type="concept",
        )
        industry_dimensions = _build_dimension_curves_from_snapshots(
            industry_dimension_snapshots or fallback_snapshots,
            limit=30,
            top_n=20,
            source_name=UPSTREAM_ROTATION_FALLBACK_SOURCE,
            preferred_order=PREFERRED_INDUSTRY_NAMES,
            dimension_type="industry",
        )

    main_current_avg = signal_by_category.get("mainline", {}).get("current_avg", 0.0)
    watch_current_avg = signal_by_category.get("watch", {}).get("current_avg", 0.0)
    alive_current_avg = signal_by_category.get("alive", {}).get("current_avg", 0.0)
    failed_bar_rate = to_float(market_metrics.get("failed_bar_rate"), 0.0) or 0.0
    limit_down_total = max(to_int(market_metrics.get("limit_down_total"), 0) or 0, 0)
    limit_up_total = max(to_int(market_metrics.get("limit_up_total"), 0) or 0, 0)
    market_heat = to_float(market_metrics.get("market_heat") or market_metrics.get("heat"), None)

    if failed_bar_rate >= 0.3 or limit_down_total >= 10:
        conclusion = "风险偏高，盘中轮动以防守和兑现为主。"
    elif main_current_avg >= 0.8 and main_current_avg >= watch_current_avg:
        if watch_current_avg > 0.6:
            conclusion = "主线延续，次主线开始跟随补涨。"
        else:
            conclusion = "主线延续，围绕核心低吸。"
    elif watch_current_avg > main_current_avg and watch_current_avg > 0:
        conclusion = "资金切向次主线，关注承接和回封。"
    elif alive_current_avg > 0 and main_current_avg <= 0:
        conclusion = "活口修复优先，等待主线重新确认。"
    elif limit_up_total >= 50 and (market_heat or 0) >= 60:
        conclusion = "情绪仍在扩散，轮动可能继续沿主线外溢。"
    else:
        conclusion = "分歧轮动中，先看前一日收盘方向是否被盘中确认。"

    basis = [
        f"主线 {_summarize_category(current_by_category.get('mainline', []), True)}",
        f"次主线 {_summarize_category(current_by_category.get('watch', []), True)}",
        f"活口 {_summarize_category(current_by_category.get('alive', []), True)}",
    ]

    history_windows = {
        category: safe_dict(rows[0].get("history_windows")) if rows else {}
        for category, rows in current_by_category.items()
    }

    summary_text = (
        f"今日盘中轮动以 {_summarize_category(current_by_category.get('mainline', []), True)} 为核心，"
        f"昨收结构对应 {_summarize_category(previous_by_category.get('mainline', []), False)}。"
        f"当前结论：{conclusion}"
    )

    return {
        "policy": "realtime_only_for_sector_rotation",
        "mode": "realtime" if live_allowed and quote_pool else "fallback",
        "session": "trading" if session_open else "closed",
        "updated_at": _now_str(),
        "review_date": review_date,
        "realtime_allowed": live_allowed,
        "current": current_by_category,
        "previous_close": previous_by_category,
        "comparison": {
            "conclusion": conclusion,
            "basis": basis,
            "realtime_allowed": live_allowed,
            "by_category": signal_by_category,
        },
        "history_windows": history_windows,
        "theme_dimensions": deepcopy(concept_dimensions),
        "concept_dimensions": deepcopy(concept_dimensions),
        "industry_dimensions": deepcopy(industry_dimensions),
        "summary": {
            "text": summary_text,
            "source": "guosen" if quote_pool else UPSTREAM_SOURCE,
        },
        "source": {
            "current": "guosen" if quote_pool else UPSTREAM_SOURCE,
            "previous_close": UPSTREAM_SOURCE,
            "policy": "board_rotation_only",
        },
    }


__all__ = ["build_rotation_context"]
