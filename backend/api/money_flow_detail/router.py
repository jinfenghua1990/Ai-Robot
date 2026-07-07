"""
个股 4 档资金流接口
- GET /api/stock/{code}/money-flow-detail?date=20260706
- 返回当前日 + 近 5 日的特/大/小/散单净流入
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Query
from collectors.moneyflow_detail import (
    get_stock_moneyflow_detail,
    fetch_moneyflow_for_date,
    backfill_moneyflow_detail,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_ts_code(code: str) -> str:
    if not code:
        return ''
    code = str(code).strip()
    if '.' in code:
        return code.upper()
    if code.startswith('6') or code.startswith('9'):
        return f'{code}.SH'
    if code.startswith('8') or code.startswith('4'):
        return f'{code}.BJ'
    return f'{code}.SZ'


@router.get('/api/stock/{code}/money-flow-detail')
def stock_money_flow_detail(
    code: str,
    date: str = Query(None, description='YYYYMMDD,留空取最新一日'),
):
    """查询个股 4 档资金流(特/大/小/散单净流入)+ 主力/散户拆分"""
    ts_code = _normalize_ts_code(code)
    if not ts_code:
        return {'error': 'invalid code'}

    data = get_stock_moneyflow_detail(ts_code, date)
    if not data:
        return {
            'ts_code': ts_code,
            'available': False,
            'message': '暂无 4 档资金流数据,系统每日 17:30 自动更新,可在指令信号日报页点击"补刷"',
        }
    return {
        'ts_code': ts_code,
        'available': True,
        **data,
    }


@router.get('/api/watchlist/money-flow')
def watchlist_money_flow(
    codes: str = Query(..., description='逗号分隔的股票代码列表, 如 600519,000001,002415'),
    date: str = Query(None, description='YYYYMMDD,留空取最新一日'),
):
    """批量获取自选股的 4 档资金流(单次请求,避免 N+1)

    返回:
    - trade_date: 数据日期
    - rows: [{ts_code, name, main_net, super_large, large, small, tiny, main_pct, available, message}]
    """
    from db.session import get_db_session
    from db.models import StockMoneyFlowDetail
    from sqlalchemy import and_

    raw_codes = [c.strip() for c in codes.split(',') if c.strip()]
    if not raw_codes:
        return {'trade_date': None, 'rows': []}
    ts_codes = [_normalize_ts_code(c) for c in raw_codes]

    with get_db_session() as db:
        if date:
            td = datetime.strptime(date, '%Y%m%d').date()
        else:
            # 找 stock_money_flow_detail 表中最新日期
            latest = db.query(StockMoneyFlowDetail.trade_date)\
                .order_by(StockMoneyFlowDetail.trade_date.desc()).first()
            if not latest:
                return {'trade_date': None, 'rows': []}
            td = latest[0]

        rows_db = db.query(StockMoneyFlowDetail).filter(
            StockMoneyFlowDetail.trade_date == td,
            StockMoneyFlowDetail.ts_code.in_(ts_codes),
        ).all()
        data_map = {r.ts_code: r for r in rows_db}

        # 关联 watchlist 取股票名
        from db.models import Watchlist
        wl_rows = db.query(Watchlist).filter(Watchlist.stock_code.in_(
            [c for c in raw_codes]
        )).all()
        name_map = {w.stock_code: w.stock_name for w in wl_rows if w.stock_name}

    rows = []
    for raw, ts in zip(raw_codes, ts_codes):
        r = data_map.get(ts)
        if not r:
            rows.append({
                'ts_code': ts,
                'name': name_map.get(raw, raw),
                'available': False,
                'message': '无数据',
                'main_net': 0, 'super_large': 0, 'large': 0,
                'small': 0, 'tiny': 0,
                'turnover_rate': 0,
            })
            continue
        def y2w(v):
            return round(float(v or 0) / 10000, 2)
        main_net = y2w(r.main_net)
        super_large = y2w(r.super_large_net)
        large = y2w(r.large_net)
        small = y2w(r.small_net)
        tiny = y2w(r.tiny_net)
        rows.append({
            'ts_code': ts,
            'name': name_map.get(raw, raw) or raw,
            'available': True,
            'main_net': main_net,
            'super_large': super_large,
            'large': large,
            'small': small,
            'tiny': tiny,
            'main_buy': y2w(r.main_buy),
            'main_sell': y2w(r.main_sell),
            'turnover_rate': float(r.turnover_rate or 0),
        })

    # 按主力净流入降序
    rows.sort(key=lambda x: x.get('main_net', 0), reverse=True)

    return {
        'trade_date': td.strftime('%Y%m%d'),
        'rows': rows,
    }


@router.post('/api/stock/money-flow-detail/backfill')
def backfill_money_flow_detail(
    start: str = Query(..., description='YYYYMMDD'),
    end: str = Query(..., description='YYYYMMDD'),
):
    """手动回填 4 档资金流(管理员用)"""
    results = backfill_moneyflow_detail(start, end)
    total = sum(r.get('written', 0) for r in results)
    return {
        'days': len(results),
        'total_written': total,
        'results': results,
    }


@router.post('/api/stock/money-flow-detail/refresh')
def refresh_today_money_flow(date: str = Query(..., description='YYYYMMDD')):
    """手动触发某日 4 档资金流采集"""
    r = fetch_moneyflow_for_date(date)
    return {'date': date, **r}
