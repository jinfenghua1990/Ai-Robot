"""
妙想 Skills API 封装
- mx-xuangu: 智能选股（自然语言）
- mx-zixuan: 自选股管理（查询/添加/删除）
- mx-search: 资讯搜索
- mx-data:   金融数据查询
- mx-moni:   经验交流发帖（模拟盘的交易/查询已在 trading.py 实现，此处只补发帖）

设计原则：
1. 复用 ~/skills/ 下的 skill 模块做响应解析，skill 升级自动同步
2. 妙想 API 调用统一用 httpx 异步，错误降级不抛 500
3. 60秒内存缓存，避免浪费付费 API 额度
"""
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)
import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from config import MX_APIKEY, MX_API_URL

# ===== 加载 ~/skills/ 下的妙想 skill 模块 =====
_SKILLS_ROOT = Path.home() / "skills"
for _d in ("mx-xuangu", "mx-zixuan", "mx-search", "mx-data", "mx-moni"):
    _p = str(_SKILLS_ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mx_xuangu   # noqa: E402
import mx_search   # noqa: E402
import mx_data     # noqa: E402
import mx_moni     # noqa: E402
from api.stock_research import save_news_search, save_data_query  # noqa: E402
from api.watchlist._shared import _get_http_client

router = APIRouter()

# 60 秒缓存，避免重复调用付费 API
_mx_cache: dict = {}
_MX_CACHE_TTL = 60


def _cache_get(key: str):
    c = _mx_cache.get(key)
    if c and time.time() - c[1] < _MX_CACHE_TTL:
        return c[0]
    return None


def _cache_set(key: str, val):
    _mx_cache[key] = (val, time.time())


def _ensure_apikey():
    if not MX_APIKEY:
        raise HTTPException(status_code=500, detail="MX_APIKEY未配置")


async def _mx_post(endpoint: str, payload: dict, timeout: int = 30) -> dict:
    """统一调用妙想 API，返回原始 JSON。失败抛 HTTPException。"""
    _ensure_apikey()
    url = f"{MX_API_URL}{endpoint}" if endpoint.startswith("/api/") else endpoint
    try:
        client = _get_http_client()
        resp = await client.post(
            url,
            json=payload,
            headers={
                "apikey": MX_APIKEY,
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        return resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="妙想API请求超时")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"妙想API请求失败: {e}")


# ========== 数据模型 ==========

class NLQuery(BaseModel):
    query: str
    force: bool = False  # 跳过缓存
    stock_code: str = ''   # 关联个股（从个股详情页搜索时传入，用于存库沉淀）
    stock_name: str = ''


class ZixuanManage(BaseModel):
    query: str  # 自然语言，如"把贵州茅台加入自选"


class MoniPost(BaseModel):
    text: str
    force: bool = False


# ========== mx-xuangu 智能选股 ==========

@router.post("/api/mx/xuangu")
async def mx_xuangu_screen(req: NLQuery):
    """妙想智能选股 - 自然语言选股
    示例 query: "股价大于10元的A股" / "半导体板块成分股" / "推荐低PE高ROE的股票"
    """
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="查询不能为空")

    cache_key = f"xuangu:{q}"
    if not req.force:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    result = await _mx_post("/api/claw/stock-screen", {"query": q})

    # 用 skill 模块的解析逻辑提取结构化行
    try:
        mx = mx_xuangu.MXSelectStock()
        rows, data_source, err = mx.extract_data(result)
    except Exception as e:
        return {"query": q, "error": f"解析失败: {e}", "raw": result}

    if err:
        return {"query": q, "error": err, "raw": result}

    response = {
        "query": q,
        "rows": rows,
        "count": len(rows),
        "data_source": data_source,
        "columns": list(rows[0].keys()) if rows else [],
    }
    _cache_set(cache_key, response)
    return response


# ========== mx-zixuan 自选股管理 ==========

def _parse_zixuan_list(raw: dict) -> list:
    """从妙想 self-select/get 响应中提取自选股列表
    妙想字段：SECURITY_CODE, SECURITY_SHORT_NAME, NEWEST_PRICE, CHG(涨跌额),
              PCHG(涨跌幅), MARKET_SHORT_NAME,
              以及动态字段 010000_TURNOVER_RATE<70>{date}, 010000_LIANGBI<70>{date}
    """
    try:
        all_results = raw.get("data", {}).get("allResults", {})
        if isinstance(all_results, dict):
            result = all_results.get("result", {})
        elif isinstance(all_results, list) and all_results:
            result = all_results[0].get("result", {})
        else:
            result = {}
        data_list = result.get("dataList", []) if isinstance(result, dict) else []
    except Exception:
        logger.debug(f"_parse_zixuan_list fallback", exc_info=True)
        data_list = []

    def _find_dynamic(item, prefix):
        """匹配带日期后缀的动态字段，如 010000_TURNOVER_RATE<70>{2026-06-25}"""
        for k, v in item.items():
            if k.startswith(prefix):
                return v
        return None

    stocks = []
    for item in data_list:
        stocks.append({
            "stock_code": str(item.get("SECURITY_CODE", "")).strip(),
            "stock_name": str(item.get("SECURITY_SHORT_NAME", "")).strip(),
            "market": str(item.get("MARKET_SHORT_NAME", "")).strip(),
            "last_price": item.get("NEWEST_PRICE"),
            "change_pct": item.get("PCHG"),
            "change_amount": item.get("CHG"),
            "turnover_rate": _find_dynamic(item, "010000_TURNOVER_RATE"),
            "volume_ratio": _find_dynamic(item, "010000_LIANGBI"),
        })
    return stocks


@router.get("/api/mx/zixuan")
async def mx_zixuan_query(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """查询妙想自选股列表"""
    if not force:
        cached = _cache_get("zixuan:list")
        if cached:
            return cached

    raw = await _mx_post("/api/claw/self-select/get", {})
    stocks = _parse_zixuan_list(raw)
    response = {"count": len(stocks), "stocks": stocks, "raw": raw}
    _cache_set("zixuan:list", response)
    return response


@router.post("/api/mx/zixuan/manage")
async def mx_zixuan_manage(req: ZixuanManage):
    """添加/删除妙想自选股（自然语言）
    示例 query: "把贵州茅台加入自选" / "从自选中删除 600519"
    """
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="操作指令不能为空")

    raw = await _mx_post("/api/claw/self-select/manage", {"query": q})
    # 操作后清缓存
    _mx_cache.pop("zixuan:list", None)
    return {"query": q, "raw": raw}


# ========== mx-search 资讯搜索 ==========

@router.post("/api/mx/search")
async def mx_search_query(req: NLQuery):
    """妙想资讯搜索 - 金融新闻/公告/研报/政策
    示例 query: "贵州茅台最新公告" / "半导体板块政策利好" / "美联储加息影响"
    """
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="搜索词不能为空")

    cache_key = f"search:{q}"
    if not req.force:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    raw = await _mx_post("/api/claw/news-search", {"query": q})
    try:
        content = mx_search.MXSearch.extract_content(raw)
    except Exception:
        logger.debug(f"mx_search_query fallback", exc_info=True)
        content = ""

    response = {"query": q, "content": content, "raw": raw}
    _cache_set(cache_key, response)
    # 存库（供 AI 数据沉淀）：从个股详情页发起的搜索才存
    if req.stock_code:
        try:
            logger.debug('handled exception', exc_info=True)
            save_news_search(req.stock_code, req.stock_name, q, content, raw)
        except Exception as e:
            logger.warning(f'保存新闻搜索记录失败: {e}', exc_info=True)
    return response

# ========== mx-data 金融数据查询 ==========

@router.post("/api/mx/data")
async def mx_data_query(req: NLQuery):
    """妙想金融数据查询 - 行情/财务/关系经营数据
    示例 query: "东方财富最新价" / "贵州茅台近3年ROE" / "宁德时代十大股东"
    """
    q = req.query.strip()
    if not q:
        raise HTTPException(status_code=400, detail="查询不能为空")

    cache_key = f"data:{q}"
    if not req.force:
        cached = _cache_get(cache_key)
        if cached:
            return cached

    raw = await _mx_post("/api/claw/query", {"toolQuery": q})
    try:
        tables, condition_parts, total_rows, err = mx_data.MXData.parse_result(raw)
    except Exception as e:
        return {"query": q, "error": f"解析失败: {e}", "raw": raw}

    response = {
        "query": q,
        "tables": tables,
        "condition": " ".join(condition_parts) if condition_parts else "",
        "total_rows": total_rows,
        "error": err,
        "raw": raw,
    }
    _cache_set(cache_key, response)
    # 存库（供 AI 数据沉淀）：从个股详情页发起的查询才存
    if req.stock_code:
        try:
            save_data_query(req.stock_code, req.stock_name, q, tables, raw)
        except Exception as e:
            logger.warning(f'[mx_skills] save_data_query 失败 code={req.stock_code}: {e}')
    return response


# ========== mx-moni 经验交流发帖（trading.py 未覆盖的部分） ==========

@router.post("/api/mx/moni/post")
async def mx_moni_post(req: MoniPost):
    """妙想模拟盘经验交流发帖
    用户可分享操作心得、调仓体会、交易经验等
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="发帖内容不能为空")

    raw = await _mx_post("/api/claw/mockTrading/newPost", {"text": text})
    return {"text": text, "raw": raw}


@router.post("/api/mx/moni/auto-post")
async def mx_moni_auto_post():
    """盘后自动生成操作总结并发帖（mx_moni.auto_post_at_close 的 HTTP 入口）"""
    try:
        # auto_post_at_close 是同步函数，用线程池跑
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, mx_moni.auto_post_at_close)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"自动发帖失败: {e}")