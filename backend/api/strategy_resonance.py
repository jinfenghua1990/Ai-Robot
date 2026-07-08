"""
🎯 多策略共振 API
- GET /api/strategy-resonance  聚合当日所有策略命中，按共振数排序

共振 = 同一只股票被多个策略同时命中，不同维度共振意味着更强信号。
"""
from datetime import datetime, date
from collections import defaultdict

from fastapi import APIRouter, Query
from sqlalchemy import desc

from db.session import get_db_session
from db.models import StrategyResult
from services.strategy_runner import STRATEGIES, get_strategy_meta
from api.validators import validate_date
import logging
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/strategy-resonance")
def get_strategy_resonance(
    date: str = Query(None, description="YYYY-MM-DD，默认今天"),
    min_count: int = Query(2, description="最小共振数过滤，默认2"),
):
    """返回当日被多个策略同时命中的股票，按共振数降序排序"""
    trade_date_str = validate_date(date)

    with get_db_session() as db:
        rows = db.query(StrategyResult).filter(
            StrategyResult.trade_date == trade_date_str
        ).order_by(desc(StrategyResult.score)).all()

        if not rows:
            return {
                'trade_date': trade_date_str,
                'total_stocks': 0,
                'total_hits': 0,
                'strategy_meta': _build_strategy_meta(),
                'stocks': [],
            }

        # 按 ts_code 分组
        grouped = defaultdict(lambda: {'name': '', 'sector': '', 'strategies': [], 'total_score': 0})
        for r in rows:
            key = r.ts_code
            meta = get_strategy_meta(r.strategy_key) or {'icon': '📌'}
            score = float(r.score) if r.score else 0
            grouped[key]['name'] = r.name or ''
            grouped[key]['sector'] = r.sector or ''
            grouped[key]['strategies'].append({
                'strategy_key': r.strategy_key,
                'strategy_name': r.strategy_name or meta.get('name', r.strategy_key),
                'icon': meta.get('icon', '📌'),
                'score': score,
            })
            grouped[key]['total_score'] += score

        # 构建股票列表并过滤
        stocks = []
        for ts_code, info in grouped.items():
            resonance_count = len(info['strategies'])
            if resonance_count < min_count:
                continue
            stocks.append({
                'ts_code': ts_code,
                'secCode': ts_code.split('.')[0],
                'name': info['name'],
                'sector': info['sector'],
                'resonance_count': resonance_count,
                'total_score': round(info['total_score'], 2),
                'strategies': info['strategies'],
            })

        # 按共振数降序 → 总分降序
        stocks.sort(key=lambda x: (x['resonance_count'], x['total_score']), reverse=True)

        return {
            'trade_date': trade_date_str,
            'total_stocks': len(stocks),
            'total_hits': len(rows),
            'strategy_meta': _build_strategy_meta(),
            'stocks': stocks,
        }


def _build_strategy_meta():
    """构建策略元数据图例"""
    return [
        {'key': s['key'], 'name': s['name'], 'icon': s.get('icon', '📌')}
        for s in STRATEGIES
    ]
