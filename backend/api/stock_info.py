"""个股级资讯接口（东财）。

提供给「个股分析页」使用，解决原新闻区调用通用研报流（与研报中心重复）的问题：
返回该股票自身的东财新闻 + 公告，均为按代码拉取的个股专属数据。

- 新闻：akshare.stock_news_em（东财搜索接口，懒导入并缓存）
- 公告：东财公告公开接口，纯 requests，稳定
异常时返回空列表而非 500，保证前端始终可渲染。
"""
from fastapi import APIRouter, Query, HTTPException
import requests
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# akshare 懒导入缓存（首次调用时导入，约 1s）
_AK = None


def _ak():
    global _AK
    if _AK is None:
        import akshare as ak  # noqa: F811
        _AK = ak
    return _AK


def _fetch_news(code: str, limit: int = 10) -> list:
    """个股东财新闻（最近 limit 条）。"""
    try:
        ak = _ak()
        df = ak.stock_news_em(symbol=code)
        if df is None or df.empty:
            return []
        rows = df.head(limit).to_dict("records")
        out = []
        for r in rows:
            out.append({
                "title": (r.get("新闻标题") or "").strip(),
                "summary": (r.get("新闻内容") or "").strip(),
                "time": (r.get("发布时间") or "").strip(),
                "source": (r.get("文章来源") or "").strip(),
                "url": (r.get("新闻链接") or "").strip(),
            })
        return out
    except Exception as e:
        logger.warning(f"[stock_info] news failed for {code}: {e}", exc_info=False)
        return []


def _fetch_announcements(code: str, limit: int = 15) -> list:
    """个股东财公告（最近 limit 条）。"""
    try:
        r = requests.get(
            "https://np-anotice-stock.eastmoney.com/api/security/ann",
            params={"sr": -1, "page_size": limit, "page_index": 1, "ann_type": "A",
                    "client_source": "web", "stock_list": code, "f_node": 0, "s_node": 0},
            headers={"User-Agent": UA}, timeout=20,
        )
        lst = (r.json().get("data") or {}).get("list") or []
        out = []
        for a in lst:
            cols = [c.get("column_name") for c in (a.get("columns") or []) if c.get("column_name")]
            art = a.get("art_code", "")
            out.append({
                "date": (a.get("notice_date", "") or "")[:10],
                "title": (a.get("title", "") or "").strip(),
                "type": cols[0] if cols else "",
                "url": f"https://data.eastmoney.com/notices/detail/{code}/{art}.html" if art else "",
            })
        return out
    except Exception as e:
        logger.warning(f"[stock_info] announcements failed for {code}: {e}", exc_info=False)
        return []


@router.get("/api/stock/{code}/news")
def stock_news(code: str, limit: int = Query(10, le=30)):
    """个股新闻 + 公告（东财，真实按代码拉取）。"""
    base = "".join(ch for ch in str(code) if ch.isdigit())
    if not base:
        raise HTTPException(400, "invalid code")
    return {
        "code": base,
        "news": _fetch_news(base, limit=limit),
        "announcements": _fetch_announcements(base, limit=max(5, limit)),
    }
