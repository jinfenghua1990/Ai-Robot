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
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Body
from sqlalchemy import desc, func

from db.session import get_db_session
from db.models import YuziLifecycleTracker, YuziSeatDaily

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


def _attach_boss_exits(db, rows: list) -> None:
    """给每个 tracker row 附上 boss_exits + 离场/归档判定

    boss_exits: {YYYYMMDD: [{alias, net}]}  D1 大佬在后续哪天卖了
    all_bosses_exited: bool                 D1 大佬是否全部已离场
    last_exit_date: str | None              最后一个大佬离场日期
    new_entries_after_exit: list            离场后新游资买入记录
    archived: bool                          全部离场 + 无新入场 + 距离≥3天 → 归档
    """
    if not rows:
        return
    ts_codes = list({r['ts_code'] for r in rows})
    earliest = min(r['trigger_date'] for r in rows)
    # 一次拉所有相关 SELL + BUY 记录
    seats = db.query(YuziSeatDaily).filter(
        YuziSeatDaily.ts_code.in_(ts_codes),
        YuziSeatDaily.trade_date >= earliest,
    ).all()
    # 按 ts_code + side 分组
    sell_by_code = defaultdict(list)
    buy_by_code = defaultdict(list)
    for s in seats:
        if s.side == 'SELL':
            sell_by_code[s.ts_code].append(s)
        elif s.side == 'BUY':
            buy_by_code[s.ts_code].append(s)

    for r in rows:
        bosses = set(r['boss_list_d1'] or [])
        code_sells = sell_by_code.get(r['ts_code'], [])
        exits = defaultdict(list)
        for s in code_sells:
            if s.yuzi_alias in bosses and s.trade_date >= r['trigger_date']:
                exits[s.trade_date].append({
                    'alias': s.yuzi_alias,
                    'net': round(float(s.net_amount or 0), 2),
                })
        r['boss_exits'] = dict(exits)

        # 离场判定: D1 大佬全部出现在 boss_exits 中
        exited_aliases = set()
        for _date, sells in exits.items():
            for sl in sells:
                exited_aliases.add(sl['alias'])
        all_bosses_exited = bool(bosses) and bosses.issubset(exited_aliases)
        r['all_bosses_exited'] = all_bosses_exited

        # 最后离场日期
        last_exit_date = max(exits.keys()) if exits else None
        r['last_exit_date'] = last_exit_date

        # 离场后新游资入场检测
        new_entries = []
        if all_bosses_exited and last_exit_date:
            code_buys = buy_by_code.get(r['ts_code'], [])
            for b in code_buys:
                if b.trade_date > last_exit_date and b.yuzi_alias:
                    new_entries.append({
                        'alias': b.yuzi_alias,
                        'date': b.trade_date,
                        'net': round(float(b.net_amount or 0), 2),
                    })
            new_entries.sort(key=lambda x: x['date'], reverse=True)
        r['new_entries_after_exit'] = new_entries

        # 归档判定: 全部离场 + 无新入场 + 距最后离场日≥3天
        if all_bosses_exited and last_exit_date and not new_entries:
            try:
                last_dt = datetime.strptime(last_exit_date, '%Y%m%d')
                days_since = (datetime.now() - last_dt).days
                r['archived'] = days_since >= 3
            except ValueError:
                r['archived'] = False
        else:
            r['archived'] = False


@router.get("/api/yuzi/tracker")
def get_tracker(
    min_score: float = 0.0,
    outcome: Optional[str] = None,
    days_back: int = 30,
    limit: int = 200,
    include_archived: bool = False,
):
    """
    20 天跟踪矩阵数据(供心电图前端)
    默认拉最近 30 天的所有 tracker, 覆盖 20 个交易日
    每行包含 boss_exits / all_bosses_exited / archived 等离场判定字段

    排序: 活跃(D1大佬未全离场) → 离场(全部离场但未归档) → 归档(离场3天无新入场)
    include_archived=False 时归档股票从 rows 中排除, 单独放 archived_rows
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
        # 附上大佬卖出记录 + 离场/归档判定
        _attach_boss_exits(db, data)

        # 三组分区排序: 活跃 → 离场 → 归档
        active = [d for d in data if not d.get('all_bosses_exited')]
        exited = [d for d in data if d.get('all_bosses_exited') and not d.get('archived')]
        archived = [d for d in data if d.get('archived')]

        # 活跃组: 按 quant_score_d1 desc (已是 DB 排序, 保持)
        # 离场组: 按 last_exit_date desc
        exited.sort(key=lambda x: x.get('last_exit_date') or '', reverse=True)
        # 归档组: 按 last_exit_date desc
        archived.sort(key=lambda x: x.get('last_exit_date') or '', reverse=True)

        active_rows = active + exited
        if include_archived:
            active_rows = active + exited + archived

        # 汇总统计(仅活跃+离场, 不含归档)
        total = len(active_rows)
        by_outcome = {}
        for d in active_rows:
            o = d['final_outcome']
            by_outcome[o] = by_outcome.get(o, 0) + 1
        avg_20d = round(sum(d['net_return_20d'] for d in active_rows) / total, 2) if total else 0
        high_score_count = sum(1 for d in active_rows if d['quant_score_d1'] >= 85)
        return {
            'count': total,
            'archived_count': len(archived),
            'avg_20d_return': avg_20d,
            'high_score_count': high_score_count,
            'by_outcome': by_outcome,
            'rows': active_rows,
            'archived_rows': archived if not include_archived else [],
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
