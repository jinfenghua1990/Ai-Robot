import time
import logging
from fastapi import APIRouter, Query, HTTPException, Response
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow
from datetime import datetime
from sqlalchemy import select
from utils.cache import BoundedDict

logger = logging.getLogger(__name__)
router = APIRouter()

# 内存缓存：{ cache_key: (result, timestamp) }
_cache = BoundedDict(maxsize=100)
_flow_trend_cache = BoundedDict(maxsize=50)
_flow_rank_cache = BoundedDict(maxsize=50)
_CACHE_TTL = 300  # 5分钟


def _resolve_trade_date(db, raw_date):
    """若 raw_date 当天无数据，向前查找最近一个交易日。返回 (实际日期, 字符串形式)。"""
    if raw_date:
        try:
            end_date = datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-%d format")
    else:
        end_date = datetime.now().date()

    latest = db.query(SectorFlow.trade_date).filter(
        SectorFlow.trade_date <= end_date
    ).order_by(SectorFlow.trade_date.desc()).first()

    if not latest:
        return None, None
    actual = latest[0]
    return actual, actual.strftime('%Y-%m-%d')


@router.get("/api/heatmap")
def get_heatmap(response: Response, date: str = Query(None), days: int = Query(5)):
    """返回热力图数据：日期×板块的heat_score矩阵（正序：旧→新）"""
    # 输入验证
    if days < 1 or days > 30:
        raise HTTPException(status_code=400, detail="days must be between 1 and 30")
    if date:
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD format")

    # 缓存检查
    cache_key = f"{date}_{days}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "HIT"
        return cached[0]

    with get_db_session() as db:
        end_date = datetime.strptime(date, '%Y-%m-%d') if date else datetime.now()

        # 一次查询获取所需日期范围内的所有数据，避免两次独立查询
        # 先用子查询找到最近的 N 个交易日
        available_dates_subq = (
            select(SectorFlow.trade_date)
            .filter(SectorFlow.trade_date <= end_date.date())
            .distinct()
            .order_by(SectorFlow.trade_date.desc())
            .limit(days)
            .scalar_subquery()
        )

        # 直接查询这些日期的所有数据
        sectors = db.query(SectorFlow).filter(
            SectorFlow.trade_date.in_(available_dates_subq)
        ).all()

        # 提取日期并排序（旧→新）
        date_set = sorted(set(s.trade_date for s in sectors))
        dates = [d.strftime('%Y-%m-%d') for d in date_set]

        if not dates:
            result = {'dates': [], 'sectors': [], 'values': [], 'actual_date': None}
            _cache[cache_key] = (result, time.time())
            response.headers["Cache-Control"] = "public, max-age=300"
            response.headers["X-Cache"] = "MISS"
            return result

        # 用字典做 O(1) 查找，用 sorted 保证顺序确定
        date_index = {d: i for i, d in enumerate(dates)}
        sector_names = sorted(set(s.sector for s in sectors))
        sector_index = {s: i for i, s in enumerate(sector_names)}
        values = []
        for s in sectors:
            date_str = s.trade_date.strftime('%Y-%m-%d')
            x = date_index.get(date_str, -1)
            if x >= 0:
                y = sector_index.get(s.sector, -1)
                if y >= 0:
                    values.append([x, y, float(s.heat_score or 0)])

        result = {
            'dates': dates,
            'sectors': sector_names,
            'values': values,
            'actual_date': dates[-1],
        }

        # 写入缓存
        _cache[cache_key] = (result, time.time())
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "MISS"
        return result


@router.get("/api/sector-flow-trend")
def get_sector_flow_trend(
    response: Response,
    date: str = Query(None),
    days: int = Query(5),
    sectors: str = Query(None),
):
    """返回指定板块最近 N 个交易日的 net_flow 时间序列（旧→新）"""
    if days < 1 or days > 30:
        raise HTTPException(status_code=400, detail="days must be between 1 and 30")
    if date:
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-%d format")

    sector_list = [s.strip() for s in (sectors or '').split(',') if s.strip()]
    if not sector_list:
        raise HTTPException(status_code=400, detail="sectors is required")

    cache_key = f"{date}_{days}_{','.join(sector_list)}"
    cached = _flow_trend_cache.get(cache_key)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "HIT"
        return cached[0]

    with get_db_session() as db:
        end_date = datetime.strptime(date, '%Y-%m-%d') if date else datetime.now()

        available_dates_subq = (
            select(SectorFlow.trade_date)
            .filter(SectorFlow.trade_date <= end_date.date())
            .distinct()
            .order_by(SectorFlow.trade_date.desc())
            .limit(days)
            .scalar_subquery()
        )

        records = db.query(SectorFlow).filter(
            SectorFlow.trade_date.in_(available_dates_subq),
            SectorFlow.sector.in_(sector_list),
        ).all()

        date_set = sorted(set(r.trade_date for r in records))
        dates = [d.strftime('%Y-%m-%d') for d in date_set]

        if not dates:
            result = {'dates': [], 'series': [], 'actual_date': None}
            _flow_trend_cache[cache_key] = (result, time.time())
            response.headers["Cache-Control"] = "public, max-age=300"
            response.headers["X-Cache"] = "MISS"
            return result

        date_index = {d: i for i, d in enumerate(dates)}
        data_map = {(r.sector, date_index[r.trade_date.strftime('%Y-%m-%d')]): float(r.net_flow or 0) for r in records}

        series = []
        for name in sector_list:
            values = [data_map.get((name, i), 0) for i in range(len(dates))]
            series.append({'sector': name, 'values': values})

        result = {'dates': dates, 'series': series, 'actual_date': dates[-1]}
        _flow_trend_cache[cache_key] = (result, time.time())
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "MISS"
        return result


@router.get("/api/sector-flow-rank")
def get_sector_flow_rank(response: Response, date: str = Query(None)):
    """返回指定交易日板块资金流向排名（按 net_flow 降序）。若当天无数据，回退到最近交易日。"""
    cache_key = f"rank_{date or ''}"
    cached = _flow_rank_cache.get(cache_key)
    if cached and time.time() - cached[1] < _CACHE_TTL:
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "HIT"
        return cached[0]

    with get_db_session() as db:
        actual_date, actual_date_str = _resolve_trade_date(db, date)
        if not actual_date:
            result = {'date': date, 'actual_date': None, 'sectors': []}
            _flow_rank_cache[cache_key] = (result, time.time())
            response.headers["Cache-Control"] = "public, max-age=300"
            response.headers["X-Cache"] = "MISS"
            return result

        records = db.query(SectorFlow).filter_by(trade_date=actual_date).order_by(SectorFlow.net_flow.desc()).all()
        sectors = [
            {
                'sector': r.sector,
                'net_flow': float(r.net_flow or 0),
                'money_inflow': float(r.money_inflow or 0),
                'money_outflow': float(r.money_outflow or 0),
                'rise_ratio': float(r.rise_ratio or 0),
                'heat_score': float(r.heat_score or 0),
                'limit_up_count': int(r.limit_up_count or 0),
                'leader_stock': r.leader_stock or '',
                'leader_strength': float(r.leader_strength or 0),
            }
            for r in records
        ]
        result = {'date': date, 'actual_date': actual_date_str, 'sectors': sectors}
        _flow_rank_cache[cache_key] = (result, time.time())
        response.headers["Cache-Control"] = "public, max-age=300"
        response.headers["X-Cache"] = "MISS"
        return result


class _MockResponse:
    """缓存预热用：模拟 Response 对象接收 headers"""
    def __init__(self):
        self.headers = {}


def refresh_heatmap_cache():
    """预热/刷新 heatmap + sector-flow-rank 缓存（纯DB，盘后稳定）"""
    try:
        mock = _MockResponse()
        # 预热常用 heatmap（None_5天、None_10天）
        for days in (5, 10):
            get_heatmap(mock, date=None, days=days)
        # 预热 sector-flow-rank（latest）
        get_sector_flow_rank(mock, date=None)
        print('[cache] heatmap + sector-flow-rank refreshed')
    except Exception as e:
        logger.warning(f'[cache] heatmap refresh error: {e}', exc_info=True)
