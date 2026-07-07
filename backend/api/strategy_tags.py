"""
策略标签 & 健康检查 API
- GET /api/strategy-health           返回各策略最近运行状态（健康检查）
- GET /api/stock-strategies/{code}   返回个股今日符合的策略 + 近10天命中历史
- POST /api/strategy-scan/trigger    手动触发策略扫描（运维用）
"""
import json
from datetime import datetime, date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import func, desc

from db.connection import get_db
from db.session import get_db_session
from db.models import StrategyResult, StrategyRunLog
from services.strategy_runner import STRATEGIES, get_strategy_meta, run_all_strategies, has_run_today
import logging
logger = logging.getLogger(__name__)

router = APIRouter()


def _decimal_default(o):
    """JSON 序列化辅助"""
    if isinstance(o, (Decimal,)):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o)} is not JSON serializable")


# ============================================================
# 健康检查
# ============================================================

@router.get("/api/strategy-health")
def get_strategy_health(days: int = Query(7, description="返回近 N 天的运行记录")):
    """返回各策略最近运行状态（健康检查）
    用于策略中心「策略运行状态」面板。
    """
    with get_db_session() as db:
        today = datetime.now().date()
        cutoff = today - timedelta(days=days)

        # 查近 N 天的运行日志
        logs = db.query(StrategyRunLog).filter(
            StrategyRunLog.trade_date >= cutoff
        ).order_by(
            StrategyRunLog.trade_date.desc(),
            StrategyRunLog.strategy_key
        ).all()

        # 按 strategy_key 分组，取每个策略最近一次运行
        latest_by_key = {}
        for log in logs:
            if log.strategy_key not in latest_by_key:
                latest_by_key[log.strategy_key] = log

        # 构造返回（包含所有注册策略，即使从未跑过）
        strategies = []
        for s in STRATEGIES:
            log = latest_by_key.get(s['key'])
            if log:
                strategies.append({
                    'key': s['key'],
                    'name': s['name'],
                    'icon': s['icon'],
                    'status': log.status,
                    'trade_date': str(log.trade_date) if log.trade_date else None,
                    'started_at': log.started_at.isoformat() if log.started_at else None,
                    'finished_at': log.finished_at.isoformat() if log.finished_at else None,
                    'duration_seconds': float(log.duration_seconds) if log.duration_seconds else None,
                    'candidate_count': log.candidate_count,
                    'hit_count': log.hit_count,
                    'error_msg': log.error_msg,
                    'is_today': log.trade_date == today if log.trade_date else False,
                })
            else:
                strategies.append({
                    'key': s['key'],
                    'name': s['name'],
                    'icon': s['icon'],
                    'status': 'never_run',
                    'trade_date': None,
                    'is_today': False,
                })

        # 今日是否全部跑完
        all_done = all(has_run_today(s['key'], today) for s in STRATEGIES)

        # 今日各策略命中数（用于汇总）
        today_hits = db.query(
            StrategyResult.strategy_key,
            func.count(StrategyResult.id).label('cnt')
        ).filter(
            StrategyResult.trade_date == today
        ).group_by(StrategyResult.strategy_key).all()
        today_hit_map = {r.strategy_key: r.cnt for r in today_hits}

        return {
            'trade_date': str(today),
            'all_done': all_done,
            'strategies': strategies,
            'today_hits': today_hit_map,
            'today_total_hits': sum(today_hit_map.values()),
        }


# ============================================================
# 个股策略标签
# ============================================================

@router.get("/api/stock-strategies/{code}")
def get_stock_strategies(code: str, days: int = Query(10, description="返回近 N 天命中历史")):
    """返回个股今日符合的策略 + 近 N 天命中历史
    用于个股详情页「策略标签」展示。
    """
    # 标准化代码：支持 688981 / 688981.SH / sz688981 等格式
    code = code.strip()
    if '.' not in code:
        if code.startswith('6'):
            code = f'{code}.SH'
        else:
            code = f'{code}.SZ'

    with get_db_session() as db:
        today = datetime.now().date()
        cutoff = today - timedelta(days=days)

        # 查近 N 天该股票的策略命中记录
        rows = db.query(StrategyResult).filter(
            StrategyResult.ts_code == code,
            StrategyResult.trade_date >= cutoff
        ).order_by(
            StrategyResult.trade_date.desc(),
            desc(StrategyResult.score)
        ).all()

        # 按日期分组
        by_date = {}
        for r in rows:
            d = str(r.trade_date)
            if d not in by_date:
                by_date[d] = []
            meta = get_strategy_meta(r.strategy_key) or {'icon': '📌'}
            try:
                scores = json.loads(r.scores_json) if r.scores_json else {}
            except Exception:
                logger.debug(f"function fallback", exc_info=True)
                scores = {}
            try:
                detail = json.loads(r.detail_json) if r.detail_json else {}
            except Exception:
                logger.debug(f"function fallback", exc_info=True)
                detail = {}
            by_date[d].append({
                'strategy_key': r.strategy_key,
                'strategy_name': r.strategy_name,
                'icon': meta['icon'],
                'score': float(r.score) if r.score else 0,
                'scores': scores,
                'detail': detail,
                'exit_signal': r.exit_signal,
                'name': r.name,
                'sector': r.sector,
                'trade_date': d,
            })

        today_str = str(today)
        today_strategies = by_date.get(today_str, [])

        # 历史列表（按日期降序，排除今天）
        history = [
            {'trade_date': d, 'strategies': items}
            for d, items in by_date.items() if d != today_str
        ]
        history.sort(key=lambda x: x['trade_date'], reverse=True)

        return {
            'code': code,
            'today_strategies': today_strategies,
            'today_count': len(today_strategies),
            'history': history,
            'total_history_days': len(by_date),
        }


# ============================================================
# 手动触发扫描（运维用）
# ============================================================

@router.post("/api/strategy-scan/trigger")
def trigger_strategy_scan(date: str = Query(None, description="指定日期 YYYY-MM-DD，默认今天")):
    """手动触发策略扫描（运维用，正常由 scheduler 自动跑）"""
    try:
        result = run_all_strategies(date)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
