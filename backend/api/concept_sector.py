import time
from fastapi import APIRouter, Query, HTTPException, Response
from db.connection import get_db
from db.session import get_db_session
from db.models import ConceptSectorFlow, RealtimeConceptSectorFlow
from db.concept_descriptions import ALL_CONCEPT_DESCRIPTIONS
from datetime import datetime, date, timedelta
from sqlalchemy import func, select

router = APIRouter()

_cache = {}
_trend_cache = {}
_realtime_cache = {}
_hot_cache = {}
_CACHE_TTL = 300
_HOT_CACHE_TTL = 600


def _resolve_trade_date(db, raw_date):
    """若 raw_date 当天无数据，向前查找最近交易日"""
    if raw_date:
        try:
            end_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD format")
    else:
        end_date = datetime.now().date()

    latest = db.query(func.max(ConceptSectorFlow.trade_date)).filter(
        ConceptSectorFlow.trade_date <= end_date
    ).scalar()

    if not latest:
        return None, None
    actual = latest
    return actual, actual.strftime('%Y-%m-%d')


@router.get("/api/concept-sector-flow-rank")
def get_concept_sector_flow_rank(response: Response, date: str = Query(None)):
    """返回指定交易日概念板块资金流向排名"""
    cache_key = date or 'latest'
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "HIT"
        return cached[0]

    with get_db_session() as db:
        actual_date, actual_date_str = _resolve_trade_date(db, date)
        if not actual_date:
            result = {'date': date, 'actual_date': None, 'sectors': []}
            _cache[cache_key] = (result, time.time())
            return result

        records = db.query(ConceptSectorFlow).filter_by(trade_date=actual_date).order_by(
            ConceptSectorFlow.net_flow.desc()
        ).all()

        sectors = [
            {
                'sector': r.concept_name,
                'concept_sector_id': r.concept_sector_id,
                'net_flow': float(r.net_flow or 0),
                'money_inflow': float(r.money_inflow or 0),
                'money_outflow': float(r.money_outflow or 0),
                'rise_ratio': float(r.rise_ratio or 0),
                'heat_score': float(r.heat_score or 0),
                'limit_up_count': int(r.limit_up_count or 0),
            }
            for r in records
        ]
        result = {'date': date, 'actual_date': actual_date_str, 'sectors': sectors}
        _cache[cache_key] = (result, time.time())
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "MISS"
        return result


@router.get("/api/concept-sector-flow-trend")
def get_concept_sector_flow_trend(
    response: Response,
    date: str = Query(None),
    days: int = Query(20),
    sectors: str = Query(None),
):
    """返回指定概念板块最近 N 个交易日的 net_flow 时间序列"""
    if days < 1 or days > 60:
        raise HTTPException(status_code=400, detail="days must be between 1 and 60")
    if date:
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD format")

    sector_list = [s.strip() for s in (sectors or '').split(',') if s.strip()]
    if not sector_list:
        raise HTTPException(status_code=400, detail="sectors is required")

    cache_key = f"{date}_{days}_{','.join(sector_list)}"
    cached = _trend_cache.get(cache_key)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "HIT"
        return cached[0]

    with get_db_session() as db:
        end_date = datetime.strptime(date, '%Y-%m-%d') if date else datetime.now()

        available_dates_subq = (
            select(ConceptSectorFlow.trade_date)
            .filter(ConceptSectorFlow.trade_date <= end_date.date())
            .distinct()
            .order_by(ConceptSectorFlow.trade_date.desc())
            .limit(days)
            .scalar_subquery()
        )

        records = db.query(ConceptSectorFlow).filter(
            ConceptSectorFlow.trade_date.in_(available_dates_subq),
            ConceptSectorFlow.concept_name.in_(sector_list),
        ).all()

        date_set = sorted(set(r.trade_date for r in records))
        dates = [d.strftime('%Y-%m-%d') for d in date_set]

        if not dates:
            result = {'dates': [], 'series': [], 'actual_date': None}
            _trend_cache[cache_key] = (result, time.time())
            return result

        date_index = {d: i for i, d in enumerate(dates)}
        data_map = {}
        for r in records:
            key = (r.concept_name, date_index[r.trade_date.strftime('%Y-%m-%d')])
            data_map[key] = float(r.net_flow or 0)

        series = []
        for name in sector_list:
            values = [data_map.get((name, i), None) for i in range(len(dates))]
            if any(v is not None for v in values):
                series.append({'sector': name, 'values': values})

        result = {'dates': dates, 'series': series, 'actual_date': dates[-1]}
        _trend_cache[cache_key] = (result, time.time())
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "MISS"
        return result


@router.get("/api/concept-sector-hot")
def get_concept_sector_hot(response: Response, days: int = Query(60, description="回溯天数")):
    """返回近 N 天按平均波动活跃度排序的概念板块列表，用于筛选器排序。

    排序指标：avg(|avg_chg|) 平均绝对涨幅，反映市场关注度与参与活跃度。
    不使用 heat_score（受涨停数绝对值影响，大筐概念如"专精特新"398只成分股会虚高）。
    """
    if days < 1 or days > 120:
        raise HTTPException(status_code=400, detail="days must be between 1 and 120")

    cache_key = str(days)
    cached = _hot_cache.get(cache_key)
    if cached and time.time() - cached[1] < _HOT_CACHE_TTL:
        response.headers["Cache-Control"] = "public, max-age=600"
        response.headers["X-Cache"] = "HIT"
        return cached[0]

    with get_db_session() as db:
        cutoff = date.today() - timedelta(days=days)
        rows = db.query(
            ConceptSectorFlow.concept_name,
            func.avg(func.abs(ConceptSectorFlow.avg_chg)).label('avg_activity'),
            func.avg(ConceptSectorFlow.heat_score).label('avg_heat'),
            func.avg(ConceptSectorFlow.net_flow).label('avg_net_flow'),
            func.sum(ConceptSectorFlow.net_flow).label('total_net_flow'),
            func.max(ConceptSectorFlow.trade_date).label('latest_date'),
            func.count(ConceptSectorFlow.id).label('days_count'),
        ).filter(
            ConceptSectorFlow.trade_date >= cutoff
        ).group_by(
            ConceptSectorFlow.concept_name
        ).order_by(
            func.avg(func.abs(ConceptSectorFlow.avg_chg)).desc()
        ).all()

        result = []
        for r in rows:
            result.append({
                'sector': r.concept_name,
                'description': ALL_CONCEPT_DESCRIPTIONS.get(r.concept_name, ''),
                'avg_activity': round(float(r.avg_activity or 0), 2),
                'avg_heat': round(float(r.avg_heat or 0), 2),
                'avg_net_flow': round(float(r.avg_net_flow or 0), 0),
                'total_net_flow': round(float(r.total_net_flow or 0), 0),
                'latest_date': r.latest_date.isoformat() if r.latest_date else None,
                'days_count': int(r.days_count or 0),
            })
        payload = {'days': days, 'count': len(result), 'sectors': result}
        _hot_cache[cache_key] = (payload, time.time())
        response.headers["Cache-Control"] = "public, max-age=600"
        response.headers["X-Cache"] = "MISS"
        return payload


def _refresh_hot_cache():
    """预热/刷新 concept-sector-hot 缓存（盘后数据稳定，TTL 10分钟）"""
    try:
        with get_db_session() as db:
            for days in (60, 120):
                cutoff = date.today() - timedelta(days=days)
                rows = db.query(
                    ConceptSectorFlow.concept_name,
                    func.avg(func.abs(ConceptSectorFlow.avg_chg)).label('avg_activity'),
                    func.avg(ConceptSectorFlow.heat_score).label('avg_heat'),
                    func.avg(ConceptSectorFlow.net_flow).label('avg_net_flow'),
                    func.sum(ConceptSectorFlow.net_flow).label('total_net_flow'),
                    func.max(ConceptSectorFlow.trade_date).label('latest_date'),
                    func.count(ConceptSectorFlow.id).label('days_count'),
                ).filter(
                    ConceptSectorFlow.trade_date >= cutoff
                ).group_by(
                    ConceptSectorFlow.concept_name
                ).order_by(
                    func.avg(func.abs(ConceptSectorFlow.avg_chg)).desc()
                ).all()
                result = []
                for r in rows:
                    result.append({
                        'sector': r.concept_name,
                        'description': ALL_CONCEPT_DESCRIPTIONS.get(r.concept_name, ''),
                        'avg_activity': round(float(r.avg_activity or 0), 2),
                        'avg_heat': round(float(r.avg_heat or 0), 2),
                        'avg_net_flow': round(float(r.avg_net_flow or 0), 0),
                        'total_net_flow': round(float(r.total_net_flow or 0), 0),
                        'latest_date': r.latest_date.isoformat() if r.latest_date else None,
                        'days_count': int(r.days_count or 0),
                    })
                _hot_cache[str(days)] = ({'days': days, 'count': len(result), 'sectors': result}, time.time())
            print('[cache] concept-sector-hot refreshed (days=60,120)')
    except Exception as e:
        print(f'[cache] concept-sector-hot refresh error: {e}')


@router.get("/api/realtime/concept-sectors")
def latest_concept_sectors(response: Response, trade_date: str = Query(None)):
    """最新概念板块资金流向快照"""
    cache_key = trade_date or 'latest'
    cached = _realtime_cache.get(cache_key)
    if cached and time.time() - cached[1] < 30:
        response.headers["Cache-Control"] = "public, max-age=30"
        response.headers["X-Cache"] = "HIT"
        return cached[0]

    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = datetime.now().date()

        latest_time = db.query(func.max(RealtimeConceptSectorFlow.snapshot_time)).filter(
            RealtimeConceptSectorFlow.trade_date == target_date
        ).scalar()

        if not latest_time:
            return {"snapshot_time": None, "trade_date": trade_date or target_date.isoformat(), "sectors": []}

        records = db.query(RealtimeConceptSectorFlow).filter_by(
            trade_date=target_date, snapshot_time=latest_time
        ).order_by(RealtimeConceptSectorFlow.net_flow.desc()).all()

        result = {
            "snapshot_time": latest_time.strftime('%Y-%m-%d %H:%M:%S'),
            "trade_date": target_date.isoformat(),
            "count": len(records),
            "sectors": [{
                "sector": r.concept_name,
                "concept_sector_id": r.concept_sector_id,
                "net_flow": float(r.net_flow or 0),
                "money_inflow": float(r.money_inflow or 0),
                "money_outflow": float(r.money_outflow or 0),
                "rise_ratio": float(r.rise_ratio or 0),
            } for r in records],
        }
        _realtime_cache[cache_key] = (result, time.time())
        response.headers["Cache-Control"] = "public, max-age=30"
        response.headers["X-Cache"] = "MISS"
        return result
