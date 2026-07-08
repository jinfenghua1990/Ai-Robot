"""
个股研究数据沉淀 API
- 资讯搜索历史存取（妙想 mx-search 结果）
- 金融数据查询历史存取（妙想 mx-data 结果）
- AI 分析数据读取接口（供后续 AI 机器人全面分析）
"""
import json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db.connection import get_db
from db.session import get_db_session
from db.models import StockNewsSearch, StockDataQuery, AIAnalysisCache, Watchlist
import logging
logger = logging.getLogger(__name__)

router = APIRouter()


# ===== 存库函数（供 mx_skills 调用） =====

def save_news_search(stock_code: str, stock_name: str, query_keyword: str, content: str, raw: dict):
    """资讯搜索结果存库（供 AI 数据沉淀）"""
    try:
        with get_db_session() as db:
            db.add(StockNewsSearch(
                stock_code=stock_code,
                stock_name=stock_name,
                query_keyword=query_keyword,
                search_time=datetime.now(),
                result_summary=(content or '')[:500],
                result_raw=json.dumps(raw, ensure_ascii=False, default=str) if raw else '',
            ))
            db.commit()
    except Exception:
        logger.warning(f"save_news_search db error", exc_info=True)


def save_data_query(stock_code: str, stock_name: str, query_keyword: str, tables: list, raw: dict):
    """金融数据查询结果存库（供 AI 数据沉淀）"""
    try:
        with get_db_session() as db:
            db.add(StockDataQuery(
                stock_code=stock_code,
                stock_name=stock_name,
                query_keyword=query_keyword,
                query_time=datetime.now(),
                result_tables=json.dumps({'tables': tables, 'raw': raw}, ensure_ascii=False, default=str),
            ))
            db.commit()
    except Exception:
        logger.warning(f"save_data_query db error", exc_info=True)


# ===== 资讯搜索历史读取 =====

@router.get("/api/stock/{code}/research/news")
def get_news_history(code: str, limit: int = Query(50, le=200)):
    """读取某股票的资讯搜索历史"""
    with get_db_session() as db:
        rows = db.query(StockNewsSearch).filter(
            StockNewsSearch.stock_code == code
        ).order_by(StockNewsSearch.search_time.desc()).limit(limit).all()
        return {"stock_code": code, "count": len(rows), "history": [
            {
                "id": r.id,
                "query": r.query_keyword,
                "time": r.search_time.isoformat() if r.search_time else None,
                "summary": r.result_summary,
                "stock_name": r.stock_name,
            } for r in rows
        ]}


@router.get("/api/stock/{code}/research/data")
def get_data_history(code: str, limit: int = Query(50, le=200)):
    """读取某股票的金融数据查询历史"""
    with get_db_session() as db:
        rows = db.query(StockDataQuery).filter(
            StockDataQuery.stock_code == code
        ).order_by(StockDataQuery.query_time.desc()).limit(limit).all()
        return {"stock_code": code, "count": len(rows), "history": [
            {
                "id": r.id,
                "query": r.query_keyword,
                "time": r.query_time.isoformat() if r.query_time else None,
                "stock_name": r.stock_name,
            } for r in rows
        ]}


# ===== AI 数据沉淀接口 =====

@router.get("/api/ai/stock/{code}/history")
def get_ai_history(code: str):
    """AI 读取某股票的全部研究数据（资讯+金融数据），供 AI 全面分析

    返回该股票的所有历史搜索关键词、结果摘要、完整结果JSON。
    AI 机器人可据此做综合分析。
    """
    with get_db_session() as db:
        news = db.query(StockNewsSearch).filter(
            StockNewsSearch.stock_code == code
        ).order_by(StockNewsSearch.search_time.desc()).all()
        data = db.query(StockDataQuery).filter(
            StockDataQuery.stock_code == code
        ).order_by(StockDataQuery.query_time.desc()).all()
        return {
            "stock_code": code,
            "news_count": len(news),
            "data_count": len(data),
            "news": [
                {
                    "query": n.query_keyword,
                    "time": n.search_time.isoformat() if n.search_time else None,
                    "summary": n.result_summary,
                    "raw": n.result_raw,
                } for n in news
            ],
            "data": [
                {
                    "query": d.query_keyword,
                    "time": d.query_time.isoformat() if d.query_time else None,
                    "tables": d.result_tables,
                } for d in data
            ],
        }


@router.get("/api/ai/stock/{code}/analysis")
def get_ai_analysis(code: str):
    """读取某股票的 AI 分析结果"""
    with get_db_session() as db:
        rows = db.query(AIAnalysisCache).filter(
            AIAnalysisCache.stock_code == code
        ).order_by(AIAnalysisCache.created_at.desc()).all()
        return {"stock_code": code, "count": len(rows), "analyses": [
            {
                "id": r.id,
                "type": r.analysis_type,
                "data": r.analysis_data,
                "data_sources": r.data_sources,
                "model": r.model,
                "time": r.created_at.isoformat() if r.created_at else None,
            } for r in rows
        ]}


class AIAnalysisRequest(BaseModel):
    analysis_type: str          # news/financial/technical/comprehensive
    analysis_data: str         # AI分析结果JSON
    data_sources: str = ''     # 引用的历史搜索id列表JSON
    model: str = ''            # AI模型标识


@router.post("/api/ai/stock/{code}/analysis")
def post_ai_analysis(code: str, req: AIAnalysisRequest):
    """AI 写入分析结果（供后续 AI 机器人调用）"""
    try:
        with get_db_session() as db:
            db.add(AIAnalysisCache(
                stock_code=code,
                analysis_type=req.analysis_type,
                analysis_data=req.analysis_data,
                data_sources=req.data_sources,
                model=req.model,
            ))
            db.commit()
            return {"success": True, "stock_code": code, "type": req.analysis_type}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ===================== 市场状态（CHOPPY/TREND/IMPULSE）=====================

@router.get("/api/stock/{code}/market-state")
async def get_market_state(code: str):
    """读取个股最新市场状态"""
    from analyzers.market_state import get_latest_state
    result = get_latest_state(code)
    if not result:
        return {"market_state": "PENDING", "reasons": ["尚未计算，请等待盘后定时任务或手动触发"], "trade_date": None}
    return result


@router.post("/api/stock/{code}/market-state/refresh")
async def refresh_market_state(code: str):
    """手动触发单只股票市场状态更新"""
    from analyzers.market_state import update_stock_state
    result = await update_stock_state(code)
    return result


@router.post("/api/market-state/refresh-all")
async def refresh_all_market_state():
    """手动触发所有自选股市场状态更新（异步，立即返回）"""
    import asyncio
    from analyzers.market_state import update_stock_state
    with get_db_session() as db:
        stocks = db.query(Watchlist).all()
        codes = [s.stock_code for s in stocks]

    async def _bg():
        for i, code in enumerate(codes):
            try:
                await update_stock_state(code)
                if (i + 1) % 10 == 0:
                    print(f'[market-state] {i+1}/{len(codes)} done')
            except Exception as e:
                print(f'[market-state] error {code}: {e}')

    asyncio.create_task(_bg())
    return {"success": True, "total": len(codes), "message": "后台更新中，约需1-2分钟"}
