"""个股级资讯接口。

查询接口只读取采集器已经写入 ``stock_news_search`` 的妙想资讯存档；
缺少存档时明确返回 MISSING，不在页面请求期间调用任何外部数据源。
"""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from db.models import StockNewsSearch
from db.session import get_db_session


router = APIRouter()


def _search_items(raw: str | None) -> list[dict[str, Any]]:
    """Extract Miaoxiang search rows from the two observed response envelopes."""
    if not raw:
        return []
    try:
        payload: Any = json.loads(raw)
    except (TypeError, ValueError):
        return []

    for _ in range(3):
        if not isinstance(payload, dict):
            return []
        response = payload.get("llmSearchResponse")
        if isinstance(response, dict):
            rows = response.get("data")
            return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        payload = payload.get("data")
    return []


def _search_error(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return "INVALID_ARCHIVE"
    if not isinstance(payload, dict):
        return "INVALID_ARCHIVE"
    code = payload.get("code")
    message = str(payload.get("message") or "")
    if code == 113 or "调用次数" in message or "免费版用户" in message:
        return "UPSTREAM_LIMIT"
    return "UPSTREAM_ERROR" if not _search_items(raw) else None


def _database_news(code: str, limit: int) -> dict[str, Any]:
    with get_db_session() as db:
        searches = (
            db.query(StockNewsSearch)
            .filter(StockNewsSearch.stock_code == code)
            .order_by(StockNewsSearch.search_time.desc(), StockNewsSearch.id.desc())
            .limit(100)
            .all()
        )

        news: list[dict[str, Any]] = []
        announcements: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        content_as_of = None
        for search in searches:
            items = _search_items(search.result_raw)
            if items and content_as_of is None:
                content_as_of = search.search_time
            for item in items:
                title = str(item.get("title") or "").strip()
                date = str(item.get("date") or "").strip()
                url = str(item.get("jumpUrl") or "").strip()
                if not title:
                    continue
                identity = (title, date, url)
                if identity in seen:
                    continue
                seen.add(identity)

                info_type = str(item.get("informationType") or "").upper()
                if info_type == "NOTICE":
                    announcements.append({
                        "date": date[:10],
                        "title": title,
                        "type": "公告",
                        "url": url,
                    })
                else:
                    news.append({
                        "title": title,
                        "summary": str(item.get("content") or item.get("showText") or "").strip(),
                        "time": date,
                        "source": info_type or "妙想资讯",
                        "url": url,
                    })

        collection_as_of = searches[0].search_time if searches else None
        latest_error = _search_error(searches[0].result_raw) if searches else None
        has_data = bool(news or announcements)
        if has_data and latest_error:
            status = "STALE"
        elif has_data:
            status = "READY"
        elif latest_error:
            status = latest_error
        else:
            status = "MISSING"

        return {
            "news": news[:limit],
            "announcements": announcements[:max(5, limit)],
            "dataAsOf": content_as_of.isoformat() if content_as_of else None,
            "collectionAsOf": collection_as_of.isoformat() if collection_as_of else None,
            "status": status,
            "message": (
                "数据库中最近采集记录为妙想调用额度不足，暂无可用资讯数据"
                if status == "UPSTREAM_LIMIT"
                else "最近一次妙想采集失败，当前展示数据库中的较早存档"
                if status == "STALE" and latest_error
                else None
            ),
        }


@router.get("/api/stock/{code}/news")
def stock_news(code: str, limit: int = Query(10, ge=1, le=30)):
    """Return the latest persisted stock news and announcements."""
    base = "".join(ch for ch in str(code) if ch.isdigit())
    if not base:
        raise HTTPException(400, "invalid code")
    result = _database_news(base, limit)
    return {"code": base, "source": "database", **result}
