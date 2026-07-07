"""
游资 20 天生命周期跟踪 API 路由
- GET  /api/yuzi/tracker             矩阵数据(心电图用)
- GET  /api/yuzi/tracker/cluster     大妖股/A杀退潮画像(为 AI 聚类)
- POST /api/yuzi/tracker/run         手动触发一次完整 run(d1+update)
- POST /api/yuzi/tracker/d1          手动触发 D1
- POST /api/yuzi/tracker/update      手动触发 update
- POST /api/yuzi/tracker/backfill    历史回填
- GET  /api/yuzi/tracker/stock       某只股票的完整 20 天轨迹
"""
import json
import logging
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Body
from sqlalchemy import desc, func

from db.session import get_db_session
from db.models import YuziLifecycleTracker

logger = logging.getLogger(__name__)
router = APIRouter()


def _row_to_dict(r: YuziLifecycleTracker) -> dict:
    try:
        lifecycle = json.loads(r.lifecycle_data or '{}')
    except (ValueError, TypeError):
        lifecycle = {}
    return {
        'id': r.id,
        'trigger_date': r.trigger_date,
        'ts_code': r.ts_code,
        'stock_name': r.stock_name or '',
        'quant_score_d1': float(r.quant_score_d1 or 0),
        'boss_list_d1': (r.boss_list_d1 or '').split(',') if r.boss_list_d1 else [],
        'resonance_count_d1': r.resonance_count_d1 or 0,
        'lifecycle_data': lifecycle,
        'final_outcome': r.final_outcome or '未结束',
        'net_return_20d': float(r.net_return_20d or 0),
        'day_filled': r.day_filled or 1,
    }


@router.get("/api/yuzi/tracker")
def get_tracker(
    min_score: float = 0.0,
    outcome: Optional[str] = None,
    days_back: int = 30,
    limit: int = 200,
):
    """
    20 天跟踪矩阵数据(供心电图前端)
    默认拉最近 30 天的所有 tracker, 覆盖 20 个交易日
    """
    with get_db_session() as db:
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
        q = db.query(YuziLifecycleTracker).filter(
            YuziLifecycleTracker.trigger_date >= cutoff,
        )
        if min_score:
            q = q.filter(YuziLifecycleTracker.quant_score_d1 >= min_score)
        if outcome:
            q = q.filter(YuziLifecycleTracker.final_outcome == outcome)
        rows = q.order_by(desc(YuziLifecycleTracker.quant_score_d1)).limit(limit or 200).all()
        data = [_row_to_dict(r) for r in rows]

        # 汇总统计
        total = len(data)
        by_outcome = {}
        for d in data:
            o = d['final_outcome']
            by_outcome[o] = by_outcome.get(o, 0) + 1
        avg_20d = round(sum(d['net_return_20d'] for d in data) / total, 2) if total else 0
        high_score_count = sum(1 for d in data if d['quant_score_d1'] >= 85)
        return {
            'count': total,
            'avg_20d_return': avg_20d,
            'high_score_count': high_score_count,
            'by_outcome': by_outcome,
            'rows': data,
        }


@router.get("/api/yuzi/tracker/cluster")
def cluster_profile(
    outcome: str = Query(..., description="结局类型:大妖股/A杀退潮/横盘/高位震荡/弱势回调"),
    limit: int = 100,
):
    """
    某结局类型的画像(为后续 AI 聚类)
    - avg_score_d1, avg_resonance_count
    - boss 出现频次(Top 10)
    - 平均每天的价格状态分布
    """
    with get_db_session() as db:
        rows = db.query(YuziLifecycleTracker).filter(
            YuziLifecycleTracker.final_outcome == outcome,
        ).order_by(desc(YuziLifecycleTracker.quant_score_d1)).limit(limit or 100).all()
        data = [_row_to_dict(r) for r in rows]

        if not data:
            return {'outcome': outcome, 'count': 0, 'profile': {}}

        n = len(data)
        avg_score = round(sum(d['quant_score_d1'] for d in data) / n, 2)
        avg_resonance = round(sum(d['resonance_count_d1'] for d in data) / n, 2)
        avg_net = round(sum(d['net_return_20d'] for d in data) / n, 2)

        # boss 频次
        from collections import Counter
        boss_counter = Counter()
        for d in data:
            for b in d['boss_list_d1']:
                if b:
                    boss_counter[b] += 1
        top_bosses = [{'alias': k, 'count': v, 'rate': round(v / n * 100, 1)} for k, v in boss_counter.most_common(10)]

        # 每天价格状态分布
        day_dist = {}
        for d in data:
            lc = d['lifecycle_data']
            for k in ['d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7']:
                if k in lc and 'price_stage' in lc[k]:
                    stage = lc[k]['price_stage']
                    day_dist.setdefault(k, Counter())[stage] += 1
        # 转成百分比
        day_dist_pct = {}
        for k, cnt in day_dist.items():
            total_k = sum(cnt.values())
            day_dist_pct[k] = [{'stage': s, 'count': c, 'rate': round(c / total_k * 100, 1)} for s, c in cnt.most_common()]

        return {
            'outcome': outcome,
            'count': n,
            'profile': {
                'avg_score_d1': avg_score,
                'avg_resonance_count': avg_resonance,
                'avg_net_return_20d': avg_net,
                'top_bosses': top_bosses,
                'day_distribution': day_dist_pct,
            },
            'sample_stocks': [{
                'ts_code': d['ts_code'],
                'name': d['stock_name'],
                'trigger_date': d['trigger_date'],
                'score_d1': d['quant_score_d1'],
                'net_return_20d': d['net_return_20d'],
            } for d in data[:10]],
        }


@router.get("/api/yuzi/tracker/stock")
def stock_tracker(
    ts_code: str = Query(..., description="股票代码"),
    days_back: int = 60,
):
    """某只股票的所有历史触发 + 20 天轨迹(60 天窗口覆盖 20 个交易日)"""
    with get_db_session() as db:
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
        rows = db.query(YuziLifecycleTracker).filter(
            YuziLifecycleTracker.ts_code == ts_code,
            YuziLifecycleTracker.trigger_date >= cutoff,
        ).order_by(desc(YuziLifecycleTracker.trigger_date)).all()
        return {
            'ts_code': ts_code,
            'count': len(rows),
            'history': [_row_to_dict(r) for r in rows],
        }


@router.post("/api/yuzi/tracker/run")
def tracker_run(date: Optional[str] = Body(None, embed=True)):
    """一站式: D1 触发 + D2-D7 更新"""
    from collectors.lifecycle_tracker import run_all
    if not date:
        date = datetime.now().strftime('%Y%m%d')
    r = run_all(date)
    return r


@router.post("/api/yuzi/tracker/d1")
def tracker_d1(date: str = Body(..., embed=True)):
    """单独触发 D1"""
    from collectors.lifecycle_tracker import trigger_d1
    n = trigger_d1(date)
    return {'date': date, 'inserted': n}


@router.post("/api/yuzi/tracker/update")
def tracker_update(date: str = Body(..., embed=True)):
    """单独跑 update"""
    from collectors.lifecycle_tracker import update_lifecycle
    r = update_lifecycle(date)
    return r


@router.post("/api/yuzi/tracker/backfill")
def tracker_backfill(
    start_date: str = Body(..., embed=True),
    end_date: str = Body(..., embed=True),
):
    """历史回填 D1 + update"""
    from collectors.lifecycle_tracker import backfill_history
    rs = backfill_history(start_date, end_date)
    return {'count': len(rs), 'results': rs}
