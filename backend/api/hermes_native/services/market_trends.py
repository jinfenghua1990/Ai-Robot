"""近N日市场趋势查询服务 — 直连 PostgreSQL"""

import os
import json
from datetime import datetime, timedelta
from typing import Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "hermes"),
    "user": os.getenv("DB_USER", "gino"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def _get_conn():
    return psycopg2.connect(**DB_CONFIG)


def get_market_trends(date_str: str = "", days: int = 30) -> dict[str, Any]:
    """获取近N日市场趋势数据"""
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        result: dict[str, Any] = {
            "date": date_str,
            "days": days,
            "updated_at": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "indices": _get_index_trends(cur, days),
            "sentiment": _get_sentiment_trends(cur, days),
            "limit_up": _get_limit_up_trend(cur, days),
        }

        cur.close()
        conn.close()
        return result
    except Exception as e:
        return {"error": str(e), "date": date_str, "days": days}


def _get_index_trends(cur, days: int) -> list[dict]:
    """获取三大指数近N日走势"""
    indices = [
        ("000001.SH", "上证指数"),
        ("399001.SZ", "深证成指"),
        ("399006.SZ", "创业板指"),
    ]
    result = []
    for code, name in indices:
        cur.execute(
            """
            SELECT trade_date, close, change_pct, volume
            FROM index_data
            WHERE market = 'CN_A' AND index_code = %s
            ORDER BY trade_date DESC
            LIMIT %s
            """,
            (code, days),
        )
        rows = cur.fetchall()
        series = []
        for row in reversed(rows):
            series.append({
                "date": str(row["trade_date"])[-5:],
                "close": float(row["close"]) if row["close"] else 0,
                "change_pct": float(row.get("change_pct") or 0),
                "volume": float(row.get("volume") or 0),
            })
        latest = series[-1] if series else {}
        result.append({
            "name": name,
            "code": code,
            "latest_close": latest.get("close"),
            "latest_change": latest.get("change_pct"),
            "series": series,
        })
    return result


def _get_sentiment_trends(cur, days: int) -> dict:
    """获取近N日情绪趋势"""
    cur.execute(
        """
        SELECT trade_date, sentiment_score, sentiment_label,
               advance_count, decline_count, up_limit_count, down_limit_count
        FROM market_sentiment_daily
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        (days,),
    )
    rows = list(reversed(cur.fetchall()))
    series = []
    for row in rows:
        series.append({
            "date": str(row["trade_date"])[-5:],
            "score": float(row["sentiment_score"]) if row["sentiment_score"] else 0,
            "label": row.get("sentiment_label", ""),
            "advance": int(row.get("advance_count") or 0),
            "decline": int(row.get("decline_count") or 0),
            "up_limit": int(row.get("up_limit_count") or 0),
            "down_limit": int(row.get("down_limit_count") or 0),
        })

    latest = series[-1] if series else {}
    return {
        "latest_score": latest.get("score"),
        "latest_label": latest.get("label"),
        "latest_advance": latest.get("advance"),
        "latest_decline": latest.get("decline"),
        "series": series,
    }


def _get_limit_up_trend(cur, days: int) -> dict:
    """获取近N日涨停趋势"""
    cur.execute(
        """
        SELECT trade_date, COUNT(*) as cnt
        FROM limit_up_pool_daily
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT %s
        """,
        (days,),
    )
    rows = list(reversed(cur.fetchall()))
    series = []
    for row in rows:
        series.append({
            "date": str(row["trade_date"])[-5:],
            "count": int(row["cnt"]) if row["cnt"] else 0,
        })

    return {
        "latest_count": series[-1]["count"] if series else 0,
        "series": series,
    }