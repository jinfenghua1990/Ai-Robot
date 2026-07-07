from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, func, Date as SQLDate
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from db.models import SectorFlow, StockFlow, LeaderLifecycle
from api.auth import get_readonly_db, verify_api_key
from functools import lru_cache

router = APIRouter(prefix="/api/read-only", tags=["只读数据接口"])

def paginate_query(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total

def apply_filters(query, model, filters: Dict[str, Any]):
    for key, value in filters.items():
        if hasattr(model, key):
            if isinstance(value, str):
                if value.startswith('>='):
                    query = query.filter(getattr(model, key) >= value[2:])
                elif value.startswith('<='):
                    query = query.filter(getattr(model, key) <= value[2:])
                elif value.startswith('>'):
                    query = query.filter(getattr(model, key) > value[1:])
                elif value.startswith('<'):
                    query = query.filter(getattr(model, key) < value[1:])
                elif value.startswith('~'):
                    query = query.filter(getattr(model, key).ilike(f'%{value[1:]}%'))
                else:
                    query = query.filter(getattr(model, key) == value)
            elif isinstance(value, (int, float)):
                query = query.filter(getattr(model, key) == value)
            elif isinstance(value, date):
                query = query.filter(getattr(model, key) == value)
    return query

def apply_sort(query, model, sort_by: str, sort_dir: str = "desc"):
    if sort_by and hasattr(model, sort_by):
        order_func = desc if sort_dir.lower() == "desc" else asc
        query = query.order_by(order_func(getattr(model, sort_by)))
    return query

def model_to_dict(obj) -> Dict[str, Any]:
    result = {}
    for column in obj.__table__.columns:
        value = getattr(obj, column.name)
        if isinstance(value, (date, datetime)):
            result[column.name] = value.isoformat()
        elif isinstance(value, (int, float)):
            result[column.name] = float(value) if hasattr(value, '__float__') else value
        else:
            result[column.name] = value
    return result

@router.get("/health", summary="健康检查")
async def health():
    return {"status": "ok", "service": "readonly-api", "timestamp": datetime.now().isoformat()}

@router.get("/sector-flow", summary="板块资金流向")
async def get_sector_flow(
    trade_date: Optional[str] = Query(None, description="交易日期 YYYY-MM-DD"),
    sector: Optional[str] = Query(None, description="板块名称，支持模糊匹配（前缀~）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    sort_by: str = Query("trade_date", description="排序字段"),
    sort_dir: str = Query("desc", description="排序方向 asc/desc"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    query = db.query(SectorFlow)
    
    filters = {}
    if trade_date:
        filters["trade_date"] = trade_date
    if sector:
        if sector.startswith('~'):
            filters["sector"] = sector
        else:
            filters["sector"] = sector
    
    query = apply_filters(query, SectorFlow, filters)
    query = apply_sort(query, SectorFlow, sort_by, sort_dir)
    
    items, total = paginate_query(query, page, page_size)
    
    return {
        "code": 0,
        "message": "success",
        "data": [model_to_dict(item) for item in items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    }

@router.get("/sector-flow/latest", summary="最新板块资金流向")
async def get_latest_sector_flow(
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    latest_date = db.query(func.max(SectorFlow.trade_date)).scalar()
    if not latest_date:
        raise HTTPException(status_code=404, detail={"code": "NO_DATA", "message": "No data found"})
    
    query = db.query(SectorFlow).filter(SectorFlow.trade_date == latest_date)
    query = query.order_by(desc(SectorFlow.net_flow))
    items = query.limit(limit).all()
    
    return {
        "code": 0,
        "message": "success",
        "date": latest_date.isoformat(),
        "data": [model_to_dict(item) for item in items]
    }

@router.get("/stock-flow", summary="个股资金流向")
async def get_stock_flow(
    trade_date: Optional[str] = Query(None, description="交易日期 YYYY-MM-DD"),
    ts_code: Optional[str] = Query(None, description="股票代码"),
    sector: Optional[str] = Query(None, description="板块名称"),
    name: Optional[str] = Query(None, description="股票名称，支持模糊匹配（前缀~）"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    sort_by: str = Query("trade_date", description="排序字段"),
    sort_dir: str = Query("desc", description="排序方向 asc/desc"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    query = db.query(StockFlow)
    
    filters = {}
    if trade_date:
        filters["trade_date"] = trade_date
    if ts_code:
        filters["ts_code"] = ts_code
    if sector:
        filters["sector"] = sector
    if name:
        filters["name"] = name
    
    query = apply_filters(query, StockFlow, filters)
    query = apply_sort(query, StockFlow, sort_by, sort_dir)
    
    items, total = paginate_query(query, page, page_size)
    
    return {
        "code": 0,
        "message": "success",
        "data": [model_to_dict(item) for item in items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    }

@router.get("/stock-flow/latest", summary="最新个股资金流向")
async def get_latest_stock_flow(
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    sector: Optional[str] = Query(None, description="按板块筛选"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    latest_date = db.query(func.max(StockFlow.trade_date)).scalar()
    if not latest_date:
        raise HTTPException(status_code=404, detail={"code": "NO_DATA", "message": "No data found"})
    
    query = db.query(StockFlow).filter(StockFlow.trade_date == latest_date)
    if sector:
        query = query.filter(StockFlow.sector == sector)
    query = query.order_by(desc(StockFlow.main_force_inflow))
    items = query.limit(limit).all()
    
    return {
        "code": 0,
        "message": "success",
        "date": latest_date.isoformat(),
        "data": [model_to_dict(item) for item in items]
    }

@router.get("/leader-lifecycle", summary="龙头生命周期")
async def get_leader_lifecycle(
    trade_date: Optional[str] = Query(None, description="交易日期 YYYY-MM-DD"),
    ts_code: Optional[str] = Query(None, description="股票代码"),
    sector: Optional[str] = Query(None, description="板块名称"),
    stage: Optional[str] = Query(None, description="生命周期阶段：启动/发酵/主升/分歧/退潮"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    sort_by: str = Query("trade_date", description="排序字段"),
    sort_dir: str = Query("desc", description="排序方向 asc/desc"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    query = db.query(LeaderLifecycle)
    
    filters = {}
    if trade_date:
        filters["trade_date"] = trade_date
    if ts_code:
        filters["ts_code"] = ts_code
    if sector:
        filters["sector"] = sector
    if stage:
        filters["stage"] = stage
    
    query = apply_filters(query, LeaderLifecycle, filters)
    query = apply_sort(query, LeaderLifecycle, sort_by, sort_dir)
    
    items, total = paginate_query(query, page, page_size)
    
    return {
        "code": 0,
        "message": "success",
        "data": [model_to_dict(item) for item in items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size
        }
    }

@router.get("/leader-lifecycle/latest", summary="最新龙头生命周期")
async def get_latest_leader_lifecycle(
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    stage: Optional[str] = Query(None, description="按阶段筛选"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    latest_date = db.query(func.max(LeaderLifecycle.trade_date)).scalar()
    if not latest_date:
        raise HTTPException(status_code=404, detail={"code": "NO_DATA", "message": "No data found"})
    
    query = db.query(LeaderLifecycle).filter(LeaderLifecycle.trade_date == latest_date)
    if stage:
        query = query.filter(LeaderLifecycle.stage == stage)
    query = query.order_by(desc(LeaderLifecycle.strength))
    items = query.limit(limit).all()
    
    return {
        "code": 0,
        "message": "success",
        "date": latest_date.isoformat(),
        "data": [model_to_dict(item) for item in items]
    }

@router.get("/dates", summary="可用交易日期")
async def get_available_dates(
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    query = db.query(func.distinct(SectorFlow.trade_date)).order_by(SectorFlow.trade_date.desc())
    if start_date:
        query = query.filter(SectorFlow.trade_date >= start_date)
    if end_date:
        query = query.filter(SectorFlow.trade_date <= end_date)
    
    dates = [d[0].isoformat() for d in query.all()]
    
    return {
        "code": 0,
        "message": "success",
        "data": dates,
        "count": len(dates)
    }

@router.get("/sectors", summary="可用板块列表")
async def get_sectors(
    trade_date: Optional[str] = Query(None, description="指定日期获取该日存在的板块"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    query = db.query(func.distinct(SectorFlow.sector))
    if trade_date:
        query = query.filter(SectorFlow.trade_date == trade_date)
    query = query.order_by(SectorFlow.sector)
    
    sectors = [s[0] for s in query.all()]
    
    return {
        "code": 0,
        "message": "success",
        "data": sectors,
        "count": len(sectors)
    }

@router.get("/aggregation/sector-summary", summary="板块汇总统计")
async def get_sector_summary(
    trade_date: str = Query(..., description="交易日期"),
    db: Session = Depends(get_readonly_db),
    _ = Depends(verify_api_key)
):
    total_inflow = db.query(func.coalesce(func.sum(SectorFlow.money_inflow), 0)).filter(SectorFlow.trade_date == trade_date).scalar()
    total_outflow = db.query(func.coalesce(func.sum(SectorFlow.money_outflow), 0)).filter(SectorFlow.trade_date == trade_date).scalar()
    total_net_flow = db.query(func.coalesce(func.sum(SectorFlow.net_flow), 0)).filter(SectorFlow.trade_date == trade_date).scalar()
    sector_count = db.query(func.count(func.distinct(SectorFlow.sector))).filter(SectorFlow.trade_date == trade_date).scalar()
    
    top_inflow = db.query(SectorFlow).filter(SectorFlow.trade_date == trade_date).order_by(desc(SectorFlow.net_flow)).first()
    top_outflow = db.query(SectorFlow).filter(SectorFlow.trade_date == trade_date).order_by(asc(SectorFlow.net_flow)).first()
    
    return {
        "code": 0,
        "message": "success",
        "date": trade_date,
        "summary": {
            "total_sectors": int(sector_count),
            "total_inflow": float(total_inflow),
            "total_outflow": float(total_outflow),
            "total_net_flow": float(total_net_flow),
            "top_inflow_sector": model_to_dict(top_inflow) if top_inflow else None,
            "top_outflow_sector": model_to_dict(top_outflow) if top_outflow else None
        }
    }

@router.get("/docs", summary="接口文档")
async def get_api_docs():
    return {
        "code": 0,
        "message": "success",
        "base_url": "/api/read-only",
        "auth": {
            "header": "X-API-Key",
            "description": "在请求头中添加 X-API-Key: <你的密钥>"
        },
        "endpoints": [
            {"method": "GET", "path": "/health", "description": "健康检查"},
            {"method": "GET", "path": "/sector-flow", "description": "板块资金流向（支持分页、筛选、排序）"},
            {"method": "GET", "path": "/sector-flow/latest", "description": "最新板块资金流向"},
            {"method": "GET", "path": "/stock-flow", "description": "个股资金流向（支持分页、筛选、排序）"},
            {"method": "GET", "path": "/stock-flow/latest", "description": "最新个股资金流向"},
            {"method": "GET", "path": "/leader-lifecycle", "description": "龙头生命周期（支持分页、筛选、排序）"},
            {"method": "GET", "path": "/leader-lifecycle/latest", "description": "最新龙头生命周期"},
            {"method": "GET", "path": "/dates", "description": "可用交易日期列表"},
            {"method": "GET", "path": "/sectors", "description": "可用板块列表"},
            {"method": "GET", "path": "/aggregation/sector-summary", "description": "板块汇总统计"}
        ],
        "filter_syntax": {
            "exact": "field=value",
            "greater": "field=>=100",
            "less": "field=<100",
            "contains": "field=~keyword"
        },
        "response_format": {
            "code": "0表示成功，非0表示错误",
            "message": "提示信息",
            "data": "数据内容",
            "pagination": {"page": "当前页", "page_size": "每页大小", "total": "总记录数", "pages": "总页数"}
        },
        "error_codes": {
            "401": "UNAUTHORIZED - API密钥无效",
            "404": "NO_DATA - 未找到数据",
            "422": "VALIDATION_ERROR - 参数验证失败"
        }
    }
