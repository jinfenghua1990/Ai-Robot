"""
游资龙虎榜路由
- GET  /api/yuzi/seats              席位字典列表
- POST /api/yuzi/seats              新增席位
- PUT  /api/yuzi/seats/{id}         修改席位
- DELETE /api/yuzi/seats/{id}       删除席位
- GET  /api/yuzi/billboard          当日资金动向榜（按大佬聚合）
- GET  /api/yuzi/resonance          当日共振信号池（按股聚合，quant_score 排序）
- GET  /api/yuzi/seat-stats         某游资近 N 日战绩
- GET  /api/yuzi/stock-history      某股近 N 日游资介入记录
- POST /api/yuzi/refresh            触发盘后清洗
- GET  /api/yuzi/dates              DB 已有数据日期列表
"""
import json
import logging
from collections import defaultdict
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel

from db.session import get_db_session
from db.models import YuziDict, YuziQuantSignal, YuziSeatDaily

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# 席位字典 CRUD
# ============================================================
class SeatIn(BaseModel):
    seat_name: str
    yuzi_alias: str
    yuzi_group: Optional[str] = '实力游资'
    region: Optional[str] = ''
    tags: Optional[List[str]] = []
    is_active: Optional[bool] = True
    hot_score: Optional[int] = 50
    note: Optional[str] = ''


@router.get("/api/yuzi/seats")
def list_seats(
    group: Optional[str] = None,
    active_only: bool = True,
    search: Optional[str] = None,
):
    """席位字典列表（支持 group 过滤/active 过滤/名字模糊搜索）"""
    with get_db_session() as db:
        q = db.query(YuziDict)
        if active_only:
            q = q.filter(YuziDict.is_active == True)  # noqa
        if group:
            q = q.filter(YuziDict.yuzi_group == group)
        if search:
            kw = f'%{search}%'
            q = q.filter((YuziDict.seat_name.like(kw)) | (YuziDict.yuzi_alias.like(kw)))
        rows = q.order_by(YuziDict.hot_score.desc(), YuziDict.yuzi_alias).all()
        return {
            'count': len(rows),
            'seats': [{
                'id': r.id,
                'seat_name': r.seat_name,
                'yuzi_alias': r.yuzi_alias,
                'yuzi_group': r.yuzi_group,
                'region': r.region or '',
                'tags': json.loads(r.tags or '[]'),
                'is_active': r.is_active,
                'hot_score': r.hot_score or 50,
                'note': r.note or '',
                'updated_at': r.updated_at.strftime('%Y-%m-%d %H:%M:%S') if r.updated_at else '',
            } for r in rows]
        }


@router.post("/api/yuzi/seats")
def add_seat(seat: SeatIn):
    """新增席位（已存在则返回 409）"""
    with get_db_session() as db:
        if db.query(YuziDict).filter(YuziDict.seat_name == seat.seat_name).first():
            raise HTTPException(409, detail=f"seat_name 已存在: {seat.seat_name}")
        row = YuziDict(
            seat_name=seat.seat_name,
            yuzi_alias=seat.yuzi_alias,
            yuzi_group=seat.yuzi_group or '实力游资',
            region=seat.region or '',
            tags=json.dumps(seat.tags or [], ensure_ascii=False),
            is_active=seat.is_active if seat.is_active is not None else True,
            hot_score=seat.hot_score or 50,
            note=seat.note or '',
        )
        db.add(row)
        db.commit()
        return {'id': row.id, 'seat_name': row.seat_name, 'ok': True}


@router.put("/api/yuzi/seats/{seat_id}")
def update_seat(seat_id: int, seat: SeatIn):
    """修改席位"""
    with get_db_session() as db:
        row = db.query(YuziDict).filter(YuziDict.id == seat_id).first()
        if not row:
            raise HTTPException(404, detail=f"seat id {seat_id} not found")
        row.seat_name = seat.seat_name
        row.yuzi_alias = seat.yuzi_alias
        row.yuzi_group = seat.yuzi_group or '实力游资'
        row.region = seat.region or ''
        row.tags = json.dumps(seat.tags or [], ensure_ascii=False)
        if seat.is_active is not None:
            row.is_active = seat.is_active
        row.hot_score = seat.hot_score or 50
        row.note = seat.note or ''
        db.commit()
        return {'id': row.id, 'ok': True}


@router.delete("/api/yuzi/seats/{seat_id}")
def delete_seat(seat_id: int):
    """软删（is_active=False），物理删除需手动 SQL"""
    with get_db_session() as db:
        row = db.query(YuziDict).filter(YuziDict.id == seat_id).first()
        if not row:
            raise HTTPException(404, detail=f"seat id {seat_id} not found")
        row.is_active = False
        db.commit()
        return {'id': seat_id, 'ok': True, 'soft_deleted': True}


# ============================================================
# 当日资金动向榜（按大佬聚合）
# ============================================================
@router.get("/api/yuzi/billboard")
def get_billboard(
    date: Optional[str] = None,
    group: Optional[str] = None,
    style: Optional[str] = None,
    min_net: Optional[float] = 0.0,
):
    """
    资金动向榜（按大佬聚合）
    date: YYYYMMDD，默认 DB 最新一日
    group: 顶级游资/实力游资/机构/假游资（None=全部）
    style: 稳健/一日游/砸盘/接力/低吸/趋势/首板/机构（None=全部）
    返回：[{alias, group, style, region, hot_score, stocks(逐股明细), total_net, total_buy, total_sell,
             buy_count, sell_count, win_count, loss_count}, ...]
    """
    with get_db_session() as db:
        target_date = date
        if not target_date:
            from sqlalchemy import func
            target_date = db.query(func.max(YuziSeatDaily.trade_date)).scalar()
        if not target_date:
            return {'date': '', 'billboard': [], 'summary': {}}

        # 关联 YuziDict 拿 group / style / hot_score
        q = db.query(YuziSeatDaily, YuziDict).outerjoin(
            YuziDict, YuziSeatDaily.seat_name == YuziDict.seat_name
        ).filter(YuziSeatDaily.trade_date == target_date)
        rows = q.all()

        # 按 alias 聚合
        agg = defaultdict(lambda: {
            'group': '', 'style': '', 'region': '', 'hot_score': 50,
            'seat_names': set(),
            'stocks': [],
            'total_net': 0.0, 'total_buy': 0.0, 'total_sell': 0.0,
            'buy_count': 0, 'sell_count': 0,
        })
        for seat, dict_row in rows:
            alias = (dict_row.yuzi_alias if dict_row else seat.yuzi_alias) or '未匹配'
            row_group = (dict_row.yuzi_group if dict_row else '') or ''
            row_style = (dict_row.style if dict_row else '') or ''
            if group and row_group != group:
                continue
            if style and row_style != style:
                continue
            a = agg[alias]
            a['group'] = row_group
            a['style'] = row_style
            a['region'] = (dict_row.region if dict_row else '') or ''
            a['hot_score'] = (dict_row.hot_score if dict_row else 50) or 50
            a['seat_names'].add(seat.seat_name)
            a['total_net'] += float(seat.net_amount or 0)
            a['total_buy'] += float(seat.buy_amount or 0)
            a['total_sell'] += float(seat.sell_amount or 0)
            if seat.side == 'BUY':
                a['buy_count'] += 1
            else:
                a['sell_count'] += 1
            a['stocks'].append({
                'ts_code': seat.ts_code,
                'name': seat.stock_name or '',
                'side': seat.side,
                'net': round(float(seat.net_amount or 0), 2),
                'buy': round(float(seat.buy_amount or 0), 2),
                'sell': round(float(seat.sell_amount or 0), 2),
                'reason': seat.list_reason or '',
            })

        result = []
        for alias, a in agg.items():
            if a['total_net'] < min_net:
                continue
            result.append({
                'alias': alias,
                'group': a['group'] or '未匹配',
                'style': a['style'] or '未分类',
                'region': a['region'],
                'hot_score': a['hot_score'],
                'seat_names': sorted(a['seat_names']),
                'total_net': round(a['total_net'], 2),
                'total_buy': round(a['total_buy'], 2),
                'total_sell': round(a['total_sell'], 2),
                'stock_count': len(a['stocks']),
                'buy_count': a['buy_count'],
                'sell_count': a['sell_count'],
                'stocks': sorted(a['stocks'], key=lambda x: -x['net']),
            })
        result.sort(key=lambda x: -x['total_net'])

        # 汇总
        total_net_all = sum(r['total_net'] for r in result)
        net_in = sum(r['total_net'] for r in result if r['total_net'] > 0)
        net_out = sum(r['total_net'] for r in result if r['total_net'] < 0)

        # 按 style 聚合统计（供前端展示风格分布）
        style_dist = defaultdict(lambda: {'count': 0, 'net': 0.0})
        for r in result:
            s = r['style']
            style_dist[s]['count'] += 1
            style_dist[s]['net'] += r['total_net']
        style_summary = [
            {'style': k, 'count': v['count'], 'net': round(v['net'], 2)}
            for k, v in sorted(style_dist.items(), key=lambda x: -x[1]['net'])
        ]

        return {
            'date': target_date,
            'count': len(result),
            'total_net': round(total_net_all, 2),
            'net_in': round(net_in, 2),
            'net_out': round(net_out, 2),
            'group_filter': group,
            'style_filter': style,
            'style_distribution': style_summary,
            'billboard': result,
        }


# ============================================================
# 当日共振信号池（按股聚合）
# ============================================================
@router.get("/api/yuzi/resonance")
def get_resonance(
    date: Optional[str] = None,
    min_score: Optional[float] = 0.0,
    min_resonance: Optional[int] = 1,
    limit: Optional[int] = 100,
):
    """
    共振信号池（按股聚合，quant_score 降序）
    date: YYYYMMDD，默认 DB 最新一日
    min_score / min_resonance: 过滤
    """
    with get_db_session() as db:
        target_date = date
        if not target_date:
            from sqlalchemy import func
            target_date = db.query(func.max(YuziQuantSignal.trade_date)).scalar()
        if not target_date:
            return {'date': '', 'signals': [], 'summary': {}}

        q = db.query(YuziQuantSignal).filter(
            YuziQuantSignal.trade_date == target_date,
            YuziQuantSignal.total_net_buy > 0,
        )
        if min_resonance:
            q = q.filter(YuziQuantSignal.resonance_count >= min_resonance)
        rows = q.order_by(YuziQuantSignal.quant_score.desc()).limit(limit or 100).all()

        signals = []
        for r in rows:
            signals.append({
                'ts_code': r.ts_code,
                'name': r.stock_name or '',
                'sector': r.sector or '',
                'total_net_buy': float(r.total_net_buy or 0),
                'total_buy': float(r.total_buy or 0),
                'total_sell': float(r.total_sell or 0),
                'resonance_count': r.resonance_count or 0,
                'boss_list': (r.boss_list or '').split(',') if r.boss_list else [],
                'seat_detail': json.loads(r.seat_detail or '[]'),
                'quant_score': float(r.quant_score or 0),
                'score_factors': json.loads(r.score_factors or '{}'),
                'change_pct': float(r.change_pct or 0),
                'close_price': float(r.close_price or 0),
                'turnover_rate': float(r.turnover_rate or 0),
                'limit_up_flag': bool(r.limit_up_flag),
                'amount': float(r.amount or 0),
                'list_reason': r.list_reason or '',
                'list_tag': r.list_tag or '',
            })

        # 过滤 min_score
        if min_score:
            signals = [s for s in signals if s['quant_score'] >= min_score]

        # 汇总
        return {
            'date': target_date,
            'count': len(signals),
            'total_net': round(sum(s['total_net_buy'] for s in signals), 2),
            'avg_score': round(sum(s['quant_score'] for s in signals) / len(signals), 2) if signals else 0,
            'resonance_2plus': sum(1 for s in signals if s['resonance_count'] >= 2),
            'limit_up_count': sum(1 for s in signals if s['limit_up_flag']),
            'signals': signals,
        }


# ============================================================
# 某游资近 N 日战绩
# ============================================================
@router.get("/api/yuzi/seat-stats")
def seat_stats(
    alias: str = Query(..., description="游资别名（必填）"),
    days: int = 10,
):
    """
    某游资近 N 日战绩（默认 10 个交易日）
    """
    with get_db_session() as db:
        from sqlalchemy import desc
        rows = db.query(YuziSeatDaily).filter(
            YuziSeatDaily.yuzi_alias == alias,
        ).order_by(desc(YuziSeatDaily.trade_date)).limit(200).all()

        # 按日期聚合
        by_date = defaultdict(lambda: {
            'stocks': [], 'total_net': 0.0, 'buy_count': 0, 'sell_count': 0,
        })
        for r in rows:
            d = r.trade_date
            by_date[d]['total_net'] += float(r.net_amount or 0)
            by_date[d]['stocks'].append({
                'ts_code': r.ts_code, 'name': r.stock_name or '',
                'side': r.side, 'net': round(float(r.net_amount or 0), 2),
            })
            if r.side == 'BUY':
                by_date[d]['buy_count'] += 1
            else:
                by_date[d]['sell_count'] += 1

        sorted_dates = sorted(by_date.keys(), reverse=True)[:days]
        result = []
        win_count = 0
        for d in sorted_dates:
            data = by_date[d]
            result.append({
                'date': d,
                'total_net': round(data['total_net'], 2),
                'buy_count': data['buy_count'],
                'sell_count': data['sell_count'],
                'stock_count': len(data['stocks']),
                'stocks': data['stocks'],
            })
            if data['total_net'] > 0:
                win_count += 1

        total_records = len(rows)
        total_net_all = round(sum(float(r.net_amount or 0) for r in rows), 2)
        avg_daily_net = round(total_net_all / len(sorted_dates), 2) if sorted_dates else 0

        return {
            'alias': alias,
            'days': days,
            'total_records': total_records,
            'total_net': total_net_all,
            'avg_daily_net': avg_daily_net,
            'win_days': win_count,
            'win_rate': round(win_count / len(sorted_dates) * 100, 1) if sorted_dates else 0,
            'history': result,
        }


# ============================================================
# 某股近 N 日游资介入记录
# ============================================================
@router.get("/api/yuzi/stock-history")
def stock_history(
    ts_code: str = Query(..., description="股票 ts_code"),
    days: int = 20,
):
    """某股近 N 日游资介入记录"""
    with get_db_session() as db:
        from sqlalchemy import desc
        rows = db.query(YuziSeatDaily).filter(
            YuziSeatDaily.ts_code == ts_code,
        ).order_by(desc(YuziSeatDaily.trade_date)).limit(500).all()

        by_date = defaultdict(list)
        for r in rows:
            by_date[r.trade_date].append(r)

        sorted_dates = sorted(by_date.keys(), reverse=True)[:days]
        result = []
        all_bosses = set()
        for d in sorted_dates:
            day_list = by_date[d]
            net_total = sum(float(r.net_amount or 0) for r in day_list)
            bosses_today = set((r.yuzi_alias or '') for r in day_list)
            all_bosses.update(bosses_today)
            result.append({
                'date': d,
                'total_net': round(net_total, 2),
                'yuzi_count': len(set((r.yuzi_alias or '') for r in day_list)),
                'seats': [{
                    'alias': r.yuzi_alias or '',
                    'side': r.side,
                    'net': round(float(r.net_amount or 0), 2),
                    'reason': r.list_reason or '',
                } for r in day_list],
            })

        return {
            'ts_code': ts_code,
            'days': days,
            'appeared_days': len(sorted_dates),
            'all_bosses': sorted(all_bosses),
            'history': result,
        }


# ============================================================
# 触发盘后清洗
# ============================================================
@router.post("/api/yuzi/refresh")
def trigger_refresh(date: Optional[str] = Body(None, embed=True)):
    """触发盘后清洗（同步执行，立即返回结果）"""
    from collectors.dragon_tiger_collector import run_today
    result = run_today(force_date=date)
    return result


@router.post("/api/yuzi/backfill")
def trigger_backfill(
    start_date: str = Body(..., embed=True),
    end_date: str = Body(..., embed=True),
):
    """历史回填"""
    from collectors.dragon_tiger_collector import backfill_yuzi
    results = backfill_yuzi(start_date, end_date)
    return {'count': len(results), 'results': results}


# ============================================================
# DB 已有日期
# ============================================================
@router.get("/api/yuzi/dates")
def list_dates(limit: int = 30):
    """DB 已有数据日期列表（按 trade_date desc）"""
    with get_db_session() as db:
        from sqlalchemy import func, desc
        rows = db.query(
            YuziQuantSignal.trade_date,
            func.count(YuziQuantSignal.id).label('signal_count'),
        ).group_by(YuziQuantSignal.trade_date).order_by(desc(YuziQuantSignal.trade_date)).limit(limit).all()
        seat_rows = db.query(
            YuziSeatDaily.trade_date,
            func.count(YuziSeatDaily.id).label('seat_count'),
        ).group_by(YuziSeatDaily.trade_date).order_by(desc(YuziSeatDaily.trade_date)).limit(limit).all()
        seat_dict = {r[0]: r[1] for r in seat_rows}
        return {
            'dates': [{
                'date': r[0],
                'signal_count': r[1],
                'seat_count': seat_dict.get(r[0], 0),
            } for r in rows]
        }
