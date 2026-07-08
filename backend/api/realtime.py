"""
实时数据 API
- /api/realtime/status         实时采集状态
- /api/realtime/latest-sectors  最新板块快照
- /api/realtime/latest-stocks   最新个股快照（Top N）
- /api/realtime/sector-trend    板块盘中趋势（多个快照点）
- /api/realtime/stock-trend     个股盘中趋势
- /api/realtime/trigger         手动触发一次实时采集
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import List
from sqlalchemy import func, desc
from datetime import datetime, date
from db.connection import get_db
from db.session import get_db_session
from db.models import RealtimeSectorFlow, RealtimeStockFlow, RealtimeConceptSectorFlow, RealtimeMoneyFlowSnapshot
from collectors.realtime_collector import collect_realtime_snapshot
from collectors.money_flow_middleman import get_money_flow_response, collect_realtime_money_flow_snapshot
from utils.cache import cached

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


@cached("realtime.status", ttl=60)
def _query_status():
    """实时采集状态（缓存 60s；快照每 5 分钟才更新，轮询命中率极高）"""
    with get_db_session() as db:
        latest_sector_time = db.query(func.max(RealtimeSectorFlow.snapshot_time)).scalar()
        latest_stock_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).scalar()
        sector_count = db.query(RealtimeSectorFlow).count()
        stock_count = db.query(RealtimeStockFlow).count()

        # 今天的快照次数
        today = date.today()
        today_snapshots = db.query(RealtimeSectorFlow.snapshot_time).filter(
            RealtimeSectorFlow.trade_date == today
        ).distinct().count()

        return {
            "latest_sector_time": latest_sector_time,
            "latest_stock_time": latest_stock_time,
            "total_sector_snapshots": sector_count,
            "total_stock_snapshots": stock_count,
            "today_snapshots": today_snapshots,
        }


@router.get("/status")
def realtime_status():
    """实时采集状态"""
    s = _query_status()
    return {
        "latest_sector_time": s["latest_sector_time"].strftime('%Y-%m-%d %H:%M:%S') if s["latest_sector_time"] else None,
        "latest_stock_time": s["latest_stock_time"].strftime('%Y-%m-%d %H:%M:%S') if s["latest_stock_time"] else None,
        "total_sector_snapshots": s["total_sector_snapshots"],
        "total_stock_snapshots": s["total_stock_snapshots"],
        "today_snapshots": s["today_snapshots"],
        "is_trading_hours": _is_trading_hours(),
    }


@cached("realtime.latest_sectors", ttl=60, key_fn=lambda trade_date=None: trade_date or "today")
def _query_latest_sectors(target_date):
    """最新板块快照（缓存 60s）"""
    with get_db_session() as db:
        latest_time = db.query(func.max(RealtimeSectorFlow.snapshot_time)).filter(
            RealtimeSectorFlow.trade_date == target_date
        ).scalar()

        if not latest_time:
            return {"snapshot_time": None, "sectors": [], "trade_date": target_date.isoformat()}

        sectors = db.query(RealtimeSectorFlow).filter_by(
            trade_date=target_date, snapshot_time=latest_time
        ).order_by(desc(RealtimeSectorFlow.net_flow)).all()

        return {
            "snapshot_time": latest_time.strftime('%Y-%m-%d %H:%M:%S'),
            "trade_date": target_date.isoformat(),
            "count": len(sectors),
            "sectors": [{
                "sector": s.sector,
                "net_flow": float(s.net_flow or 0),
                "money_inflow": float(s.money_inflow or 0),
                "money_outflow": float(s.money_outflow or 0),
                "rise_ratio": float(s.rise_ratio or 0),
                "source": s.source,
            } for s in sectors],
        }


@router.get("/latest-sectors")
def latest_sectors(trade_date: str = Query(None, description="YYYY-MM-DD，默认今天")):
    """最新板块快照"""
    target_date = datetime.strptime(trade_date, '%Y-%m-%d').date() if trade_date else date.today()
    return _query_latest_sectors(target_date)


@cached("realtime.latest_stocks", ttl=60,
        key_fn=lambda trade_date=None, limit=100, sort_by="main_force_inflow", sector=None: f"{trade_date}:{limit}:{sort_by}:{sector}")
def _query_latest_stocks(target_date, limit, sort_by, sector):
    """最新个股快照 Top N（缓存 60s）"""
    with get_db_session() as db:
        latest_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter(
            RealtimeStockFlow.trade_date == target_date
        ).scalar()

        if not latest_time:
            return {"snapshot_time": None, "stocks": [], "trade_date": target_date.isoformat()}

        q = db.query(RealtimeStockFlow).filter_by(
            trade_date=target_date, snapshot_time=latest_time
        )
        if sector:
            q = q.filter(RealtimeStockFlow.sector == sector)

        sort_col = getattr(RealtimeStockFlow, sort_by, RealtimeStockFlow.main_force_inflow)
        stocks = q.order_by(desc(sort_col)).limit(limit).all()

        return {
            "snapshot_time": latest_time.strftime('%Y-%m-%d %H:%M:%S'),
            "trade_date": target_date.isoformat(),
            "count": len(stocks),
            "stocks": [{
                "ts_code": s.ts_code,
                "name": s.name,
                "sector": s.sector,
                "price": float(s.price or 0),
                "price_chg": float(s.price_chg or 0),
                "main_force_inflow": float(s.main_force_inflow or 0),
                "net_inflow": float(s.net_inflow or 0),
                "retail_flow": float(s.retail_flow or 0),
                "source": s.source,
                "confidence": s.confidence,
                "sources_count": s.sources_count,
                "sources_used": s.sources_used,
                "deviation_pct": float(s.deviation_pct) if s.deviation_pct else 0,
                "is_corrected": s.is_corrected,
            } for s in stocks],
        }


@router.get("/latest-stocks")
def latest_stocks(
    trade_date: str = Query(None),
    limit: int = Query(100, le=500),
    sort_by: str = Query("main_force_inflow", description="main_force_inflow | net_inflow | price_chg"),
    sector: str = Query(None, description="按板块过滤"),
):
    """最新个股快照（Top N）"""
    target_date = datetime.strptime(trade_date, '%Y-%m-%d').date() if trade_date else date.today()
    return _query_latest_stocks(target_date, limit, sort_by, sector)


@cached("realtime.concept_sectors", ttl=60, key_fn=lambda trade_date=None: trade_date or "today")
def _query_concept_sectors(target_date):
    """最新概念板块快照（缓存 60s）"""
    with get_db_session() as db:
        latest_time = db.query(func.max(RealtimeConceptSectorFlow.snapshot_time)).filter(
            RealtimeConceptSectorFlow.trade_date == target_date
        ).scalar()

        if not latest_time:
            return {"snapshot_time": None, "sectors": [], "trade_date": target_date.isoformat()}

        sectors = db.query(RealtimeConceptSectorFlow).filter_by(
            trade_date=target_date, snapshot_time=latest_time
        ).order_by(desc(RealtimeConceptSectorFlow.net_flow)).all()

        return {
            "snapshot_time": latest_time.strftime('%Y-%m-%d %H:%M:%S'),
            "trade_date": target_date.isoformat(),
            "count": len(sectors),
            "sectors": [{
                "sector": s.concept_name,
                "net_flow": float(s.net_flow or 0),
                "money_inflow": float(s.money_inflow or 0),
                "money_outflow": float(s.money_outflow or 0),
                "rise_ratio": float(s.rise_ratio or 0),
                "source": s.source,
            } for s in sectors],
        }


@router.get("/concept-sectors")
def concept_sectors(trade_date: str = Query(None, description="YYYY-MM-DD，默认今天")):
    """最新概念板块快照"""
    target_date = datetime.strptime(trade_date, '%Y-%m-%d').date() if trade_date else date.today()
    return _query_concept_sectors(target_date)


@router.get("/sector-trend")
def sector_trend(
    sector: str = Query(..., description="板块名称"),
    trade_date: str = Query(None),
):
    """板块盘中趋势（多个快照点）"""
    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        records = db.query(RealtimeSectorFlow).filter_by(
            trade_date=target_date, sector=sector
        ).order_by(RealtimeSectorFlow.snapshot_time.asc()).all()

        return {
            "sector": sector,
            "trade_date": target_date.isoformat(),
            "points": [{
                "time": r.snapshot_time.strftime('%H:%M'),
                "net_flow": float(r.net_flow or 0),
                "money_inflow": float(r.money_inflow or 0),
                "money_outflow": float(r.money_outflow or 0),
                "rise_ratio": float(r.rise_ratio or 0),
            } for r in records],
        }


@router.get("/concept-sector-trend")
def concept_sector_trend(
    sector: str = Query(..., description="概念板块名称"),
    trade_date: str = Query(None),
):
    """概念板块盘中趋势（多个快照点）"""
    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        records = db.query(RealtimeConceptSectorFlow).filter_by(
            trade_date=target_date, concept_name=sector
        ).order_by(RealtimeConceptSectorFlow.snapshot_time.asc()).all()

        return {
            "sector": sector,
            "trade_date": target_date.isoformat(),
            "points": [{
                "time": r.snapshot_time.strftime('%H:%M'),
                "net_flow": float(r.net_flow or 0),
                "money_inflow": float(r.money_inflow or 0),
                "money_outflow": float(r.money_outflow or 0),
                "rise_ratio": float(r.rise_ratio or 0),
            } for r in records],
        }


@router.get("/leader-trend")
def leader_trend(
    sector: str = Query(..., description="板块或概念名称"),
    trade_date: str = Query(None),
):
    """主力资金净流入领先板块趋势（概念优先，无则查行业）"""
    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        # 优先查概念板块
        records = db.query(RealtimeConceptSectorFlow).filter_by(
            trade_date=target_date, concept_name=sector
        ).order_by(RealtimeConceptSectorFlow.snapshot_time.asc()).all()

        source = 'concept'
        if not records:
            # 回退到行业板块
            records = db.query(RealtimeSectorFlow).filter_by(
                trade_date=target_date, sector=sector
            ).order_by(RealtimeSectorFlow.snapshot_time.asc()).all()
            source = 'industry'

        return {
            "sector": sector,
            "trade_date": target_date.isoformat(),
            "source": source,
            "points": [{
                "time": r.snapshot_time.strftime('%H:%M'),
                "net_flow": float(r.net_flow or 0),
                "money_inflow": float(r.money_inflow or 0),
                "money_outflow": float(r.money_outflow or 0),
                "rise_ratio": float(r.rise_ratio or 0),
            } for r in records],
        }


class LeaderTrendsRequest(BaseModel):
    sectors: List[str]
    trade_date: str = None


@router.post("/leader-trends")
def leader_trends(payload: LeaderTrendsRequest):
    """批量查询板块/概念趋势（概念优先，无则查行业）"""
    with get_db_session() as db:
        if payload.trade_date:
            target_date = datetime.strptime(payload.trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        sector_list = [s.strip() for s in payload.sectors if s.strip()]

        # 一次性查出当日全部概念/行业记录，按名称分组，减少 N+1 查询
        concept_records = db.query(RealtimeConceptSectorFlow).filter(
            RealtimeConceptSectorFlow.trade_date == target_date
        ).order_by(RealtimeConceptSectorFlow.snapshot_time.asc()).all()
        concept_map = {}
        for r in concept_records:
            concept_map.setdefault(r.concept_name, []).append(r)

        industry_records = db.query(RealtimeSectorFlow).filter(
            RealtimeSectorFlow.trade_date == target_date
        ).order_by(RealtimeSectorFlow.snapshot_time.asc()).all()
        industry_map = {}
        for r in industry_records:
            industry_map.setdefault(r.sector, []).append(r)

        result = []
        for sector in sector_list:
            records = concept_map.get(sector)
            source = 'concept'
            if not records:
                records = industry_map.get(sector)
                source = 'industry'

            result.append({
                "sector": sector,
                "trade_date": target_date.isoformat(),
                "source": source,
                "points": [{
                    "time": r.snapshot_time.strftime('%H:%M'),
                    "net_flow": float(r.net_flow or 0),
                    "money_inflow": float(r.money_inflow or 0),
                    "money_outflow": float(r.money_outflow or 0),
                    "rise_ratio": float(r.rise_ratio or 0),
                } for r in (records or [])],
            })

        return {"trade_date": target_date.isoformat(), "count": len(result), "trends": result}


@router.post("/concept-sector-trends")
def concept_sector_trends(payload: LeaderTrendsRequest):
    """批量查询纯概念板块趋势（不回退行业）"""
    with get_db_session() as db:
        if payload.trade_date:
            target_date = datetime.strptime(payload.trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        sector_list = [s.strip() for s in payload.sectors if s.strip()]

        concept_records = db.query(RealtimeConceptSectorFlow).filter(
            RealtimeConceptSectorFlow.trade_date == target_date
        ).order_by(RealtimeConceptSectorFlow.snapshot_time.asc()).all()
        concept_map = {}
        for r in concept_records:
            concept_map.setdefault(r.concept_name, []).append(r)

        result = []
        for sector in sector_list:
            records = concept_map.get(sector) or []
            result.append({
                "sector": sector,
                "trade_date": target_date.isoformat(),
                "source": "concept",
                "points": [{
                    "time": r.snapshot_time.strftime('%H:%M'),
                    "net_flow": float(r.net_flow or 0),
                    "money_inflow": float(r.money_inflow or 0),
                    "money_outflow": float(r.money_outflow or 0),
                    "rise_ratio": float(r.rise_ratio or 0),
                } for r in records],
            })

        return {"trade_date": target_date.isoformat(), "count": len(result), "trends": result}


@router.get("/money-flow-trend")
def money_flow_trend(
    sector: str = Query(..., description="板块名称"),
    dimension: str = Query('concept', description="维度: concept / industry"),
    trade_date: str = Query(None),
):
    """中转层板块趋势（纯新浪直采，分钟级）"""
    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        records = db.query(RealtimeMoneyFlowSnapshot).filter_by(
            trade_date=target_date, dimension=dimension, block_name=sector
        ).order_by(RealtimeMoneyFlowSnapshot.minute.asc()).all()
        return {
            "sector": sector,
            "trade_date": target_date.isoformat(),
            "source": "middleman",
            "points": [{"time": r.minute, "net_flow": float(r.net_inflow_yi or 0) * 10000} for r in records],
        }


@router.post("/money-flow-trends")
def money_flow_trends(payload: LeaderTrendsRequest):
    """批量查询中转层板块趋势（纯新浪直采）"""
    with get_db_session() as db:
        if payload.trade_date:
            target_date = datetime.strptime(payload.trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()
        sector_list = [s.strip() for s in payload.sectors if s.strip()]
        records = db.query(RealtimeMoneyFlowSnapshot).filter(
            RealtimeMoneyFlowSnapshot.trade_date == target_date,
            RealtimeMoneyFlowSnapshot.dimension == 'concept',
            RealtimeMoneyFlowSnapshot.block_name.in_(sector_list)
        ).order_by(RealtimeMoneyFlowSnapshot.minute.asc()).all()
        sector_map = {}
        for r in records:
            sector_map.setdefault(r.block_name, []).append(r)
        result = []
        for sector in sector_list:
            recs = sector_map.get(sector) or []
            result.append({
                "sector": sector,
                "trade_date": target_date.isoformat(),
                "source": "middleman",
                "points": [{"time": r.minute, "net_flow": float(r.net_inflow_yi or 0) * 10000} for r in recs],
            })
        return {"trade_date": target_date.isoformat(), "count": len(result), "trends": result}


@router.get("/stock-trend")
def stock_trend(
    ts_code: str = Query(..., description="股票代码，如 600519.SH"),
    trade_date: str = Query(None),
):
    """个股盘中趋势"""
    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        records = db.query(RealtimeStockFlow).filter_by(
            trade_date=target_date, ts_code=ts_code
        ).order_by(RealtimeStockFlow.snapshot_time.asc()).all()

        return {
            "ts_code": ts_code,
            "trade_date": target_date.isoformat(),
            "points": [{
                "time": r.snapshot_time.strftime('%H:%M'),
                "price": float(r.price or 0),
                "price_chg": float(r.price_chg or 0),
                "main_force_inflow": float(r.main_force_inflow or 0),
                "net_inflow": float(r.net_inflow or 0),
            } for r in records],
        }


@router.get("/stock-flow-detail")
def stock_flow_detail(
    ts_code: str = Query(..., description="股票代码，如 600519.SH"),
    trade_date: str = Query(None),
):
    """个股资金流向组合数据：分时趋势 + 主力净流入 + 持仓变化 + 延迟监控"""
    from db.models import StockFeaturesDaily

    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        # 1. 分时趋势（RealtimeStockFlow 用 ts_code + Date 类型 trade_date）
        records = db.query(RealtimeStockFlow).filter_by(
            trade_date=target_date, ts_code=ts_code
        ).order_by(RealtimeStockFlow.snapshot_time.asc()).all()
        intraday_points = [{
            "time": r.snapshot_time.strftime('%H:%M'),
            "price": float(r.price or 0),
            "main_force_inflow": float(r.main_force_inflow or 0),
            "net_inflow": float(r.net_inflow or 0),
        } for r in records]

        # 2. 主力净流入金额（1d/3d/5d）+ 持仓连续性
        # StockFeaturesDaily 用 stock_code（纯数字）+ String(8) YYYYMMDD trade_date
        stock_code_pure = ts_code.split('.')[0]
        target_date_str = target_date.strftime('%Y%m%d')
        features = db.query(StockFeaturesDaily).filter(
            StockFeaturesDaily.stock_code == stock_code_pure,
            StockFeaturesDaily.trade_date <= target_date_str
        ).order_by(StockFeaturesDaily.trade_date.desc()).first()

        main_force = {
            "inflow_1d": float(features.main_net_inflow_1d or 0) if features else 0,
            "inflow_3d": float(features.main_net_inflow_3d or 0) if features else 0,
            "inflow_5d": float(features.main_net_inflow_5d or 0) if features else 0,
            "flow_continuity": int(features.flow_continuity or 0) if features else 0,
        }

        # 3. 数据新鲜度（延迟检查，超过 5 分钟视为陈旧）
        latest_time = records[-1].snapshot_time if records else None
        is_stale = False
        delay_seconds = None
        if latest_time:
            delay_seconds = int((datetime.now() - latest_time).total_seconds())
            is_stale = delay_seconds > 300

        return {
            "ts_code": ts_code,
            "trade_date": target_date.isoformat(),
            "intraday_points": intraday_points,
            "main_force": main_force,
            "latest_time": latest_time.strftime('%Y-%m-%d %H:%M:%S') if latest_time else None,
            "is_stale": is_stale,
            "delay_seconds": delay_seconds,
        }


@router.post("/trigger")
def trigger_snapshot():
    """手动触发一次实时快照采集"""
    today = datetime.now().strftime('%Y-%m-%d')
    result = collect_realtime_snapshot(today)
    return {"status": "ok", "result": result, "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}


@router.get("/v1/money-flow")
def money_flow(
    dimension: str = Query("concept", description="concept 或 industry"),
    top_n: int = Query(10, ge=1, le=50),
    bottom_n: int = Query(5, ge=0, le=50),
):
    """
    资金流向中转接口：返回净流入前 N 和净流出前 N 的板块全天分时序列
    数据来自内存缓存，首次调用会从数据库恢复当天历史数据
    """
    return get_money_flow_response(dimension=dimension, top_n=top_n, bottom_n=bottom_n)


@router.post("/v1/money-flow/trigger")
def trigger_money_flow(
    dimension: str = Query("concept", description="concept 或 industry"),
    force: bool = Query(False, description="是否强制在非交易时段采集"),
):
    """手动触发一次 money-flow 数据中转采集"""
    today = date.today()
    saved = collect_realtime_money_flow_snapshot(dimension=dimension, trade_date=today, force=force)
    return {
        "status": "ok",
        "dimension": dimension,
        "saved": saved,
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def _is_trading_hours():
    """判断是否在交易时段"""
    from utils import is_trading_time
    return is_trading_time()
