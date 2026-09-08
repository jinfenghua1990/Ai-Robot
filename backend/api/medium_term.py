"""中线趋势纸面策略快照 API。"""
import json

from fastapi import APIRouter, HTTPException

from db.models import StrategyResult, StrategyRunLog
from db.session import get_db_session
from services.medium_term_strategy import (
    RULE_VERSION,
    STRATEGY_KEY,
    TARGET_POSITION_PCT,
    run_medium_term_snapshot,
)

router = APIRouter(prefix='/api/medium-term', tags=['medium_term'])


@router.get('/overview')
def get_medium_term_overview():
    """只读最近一次已持久化的中线纸面候选。"""
    with get_db_session() as db:
        run = db.query(StrategyRunLog).filter(
            StrategyRunLog.strategy_key == STRATEGY_KEY,
            StrategyRunLog.status == 'success',
        ).order_by(StrategyRunLog.trade_date.desc()).first()
        if run is None:
            return {
                'status': 'MISSING', 'source': 'database',
                'message': '尚未生成中线策略快照',
                'rule_version': RULE_VERSION,
            }
        rows = db.query(StrategyResult).filter_by(
            trade_date=run.trade_date, strategy_key=STRATEGY_KEY,
        ).order_by(StrategyResult.score.desc(), StrategyResult.ts_code).all()

    positions = []
    for row in rows:
        try:
            detail = json.loads(row.detail_json or '{}')
        except (TypeError, ValueError):
            detail = {}
        positions.append(detail)
    return {
        'status': 'READY',
        'source': 'database',
        'trade_date': run.trade_date.isoformat(),
        'data_as_of': run.trade_date.isoformat(),
        'rule_version': RULE_VERSION,
        'coverage': {
            'universe': run.candidate_count or 0,
            'selected': len(positions),
        },
        'target_positions': positions,
        'cash_target_pct': max(0.0, 100 - len(positions) * TARGET_POSITION_PCT),
        'message': '纸面中线候选；不连接自动下单。',
    }


@router.post('/run')
def run_medium_term():
    """按已完成的本地交易日重算并保存中线纸面快照。"""
    try:
        return run_medium_term_snapshot()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'中线策略快照失败: {exc}') from exc
