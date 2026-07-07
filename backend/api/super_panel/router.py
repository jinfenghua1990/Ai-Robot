"""
个股全聚合单页面接口（双轨制中转层 - 聚合轨）

- GET /api/v1/stock/super_panel?code=600xxx  →  静态 + 实时 一次返回
- GET /api/v1/stock/super_panel?code=600xxx&section=realtime  →  仅返回实时（3 秒轮询用）

为什么单点聚合而不是让前端拼装:
- 盘后静态 7 个表, 1 次 JOIN 完成 vs 前端 N 次请求
- 盘中实时走内存 dict, 0 DB
- 前端只读不拼, 失败降级统一在服务端处理
"""
import logging
from datetime import datetime, timedelta, time as dtime
from fastapi import APIRouter, Query

from db.session import get_db_session
from db.models import (
    YuziQuantSignal, YuziSeatDaily, YuziDict, YuziLifecycleTracker,
    ConceptSector, ConceptSectorFlow, Watchlist,
)
from collectors.realtime_aggregator import serialize_state, REALTIME_STATE

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_ts_code(code: str) -> str:
    """6 位代码 → ts_code 格式"""
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


def _is_trading_hours() -> bool:
    """是否在盘中交易时段(9:30-11:30 / 13:00-15:00)"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return (dtime(9, 30) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))


def _load_post_market_base(ts_code: str) -> dict:
    """盘后静态数据(7 个表 → 1 次聚合, 全部 DB 读)"""
    stock_code = ts_code.split('.')[0]
    out = {
        'quant_score': None,
        'quant_rank': None,
        'total_net_buy_wan': 0,
        'resonance_count': 0,
        'concept_sector': '',
        'sector_hot_money_count': 0,
        'sector_heat_score': None,
        'lifecycle_7d': [],
        'lifecycle_20d': [],
        'yesterday_bosses': [],
        'in_watchlist': False,
        'note': '',
    }
    try:
        with get_db_session() as db:
            # 1) 量化共振分(游资维度)
            sig = db.query(YuziQuantSignal).filter(
                YuziQuantSignal.ts_code == ts_code
            ).order_by(YuziQuantSignal.trade_date.desc()).first()
            if sig:
                out['quant_score'] = float(sig.quant_score or 0) if sig.quant_score else None
                out['total_net_buy_wan'] = float(sig.total_net_buy or 0) if sig.total_net_buy else 0
                out['resonance_count'] = int(sig.resonance_count or 0) if sig.resonance_count else 0
                out['concept_sector'] = sig.sector or ''
                out['stock_name'] = sig.stock_name or ''
                out['change_pct'] = float(sig.change_pct or 0) if sig.change_pct else None
                out['list_reason'] = sig.list_reason or ''

            # 2) 昨日 / 近期游资席位(从席位明细倒推)
            seat_rows = db.query(YuziSeatDaily).filter(
                YuziSeatDaily.ts_code == ts_code
            ).order_by(YuziSeatDaily.trade_date.desc()).limit(20).all()

            # 按 (seat_name, trade_date) 聚合 → 找"最近 1 个交易日"
            seen_dates = sorted({r.trade_date for r in seat_rows}, reverse=True)
            latest_date = seen_dates[0] if seen_dates else None
            if latest_date:
                latest_seats = [r for r in seat_rows if r.trade_date == latest_date]
                # 关联 yuzi_dict 拿别名
                seat_names = list({r.seat_name for r in latest_seats})
                alias_map = {}
                if seat_names:
                    for d in db.query(YuziDict).filter(YuziDict.seat_name.in_(seat_names)).all():
                        alias_map[d.seat_name] = d.yuzi_alias

                bosses = []
                for r in latest_seats:
                    alias = alias_map.get(r.seat_name) or r.yuzi_alias or r.seat_name
                    net = float(r.net_amount or 0) if r.net_amount else 0
                    # 推断 action: net > 0 新进, =0 锁仓, <0 砸盘
                    if net > 100:
                        action = '新进'
                    elif net < -100:
                        action = '砸盘'
                    else:
                        action = '锁仓'
                    bosses.append({
                        'name': alias,
                        'seat': r.seat_name,
                        'action': action,
                        'net_buy_wan': round(net, 2),
                    })
                # 净买入降序
                bosses.sort(key=lambda x: x['net_buy_wan'], reverse=True)
                out['yesterday_bosses'] = bosses[:8]
                out['yesterday_trade_date'] = latest_date

            # 3) 板块热度(从 concept_sector_flow 找最近 1 日)
            if out['concept_sector']:
                cs = db.query(ConceptSector).filter(
                    ConceptSector.name == out['concept_sector']
                ).first()
                if cs:
                    from db.models import ConceptSectorFlow
                    latest_sector_flow = db.query(ConceptSectorFlow).filter(
                        ConceptSectorFlow.concept_sector_id == cs.id
                    ).order_by(ConceptSectorFlow.trade_date.desc()).first()
                    if latest_sector_flow:
                        out['sector_heat_score'] = float(latest_sector_flow.heat_score or 0) if latest_sector_flow.heat_score else None
                        # 同板块共振股数(quant_score >= 70 视为游资共振)
                        out['sector_hot_money_count'] = db.query(YuziQuantSignal).filter(
                            YuziQuantSignal.sector == out['concept_sector'],
                            YuziQuantSignal.quant_score >= 70,
                        ).count()

            # 4) 20 个交易日生命周期(YuziLifecycleTracker)
            # 覆盖一个完整中期波段(建仓→主升→派发),与机构月度复盘周期对齐
            tracker = db.query(YuziLifecycleTracker).filter(
                YuziLifecycleTracker.ts_code == ts_code
            ).order_by(YuziLifecycleTracker.trigger_date.desc()).first()
            if tracker and tracker.lifecycle_data:
                # lifecycle_data 是 JSONB dict, 形如 {d1:..., d2:..., d3:...}
                lc = tracker.lifecycle_data if isinstance(tracker.lifecycle_data, dict) else {}
                trigger = tracker.trigger_date
                # 后续 d2-d20 算实际日期
                try:
                    base = datetime.strptime(trigger, '%Y%m%d').date()
                except Exception:
                    base = datetime.now().date()
                for d in range(1, 21):
                    day = base + timedelta(days=d - 1)
                    key = f'd{d}'
                    info = lc.get(key) or {}
                    stage = info.get('price_stage') or info.get('stage') or '—'
                    score = info.get('quant_score') or info.get('score')
                    day_data = {
                        'date': day.strftime('%Y%m%d'),
                        'stage': stage,
                        'score': float(score) if score else None,
                    }
                    out['lifecycle_7d'].append(day_data)
                    out['lifecycle_20d'].append(day_data)

            # 5) 自选状态
            wl = db.query(Watchlist).filter_by(stock_code=stock_code).first()
            if wl:
                out['in_watchlist'] = True
                out['note'] = wl.note or ''
                out['watchlist_group'] = wl.group_name or '默认'

    except Exception as e:
        logger.error(f'[super_panel] load post_market_base failed for {ts_code}: {e}', exc_info=True)
        out['error'] = str(e)
    return out


def _realtime_section(ts_code: str) -> dict:
    """盘中实时(从内存 REALTIME_STATE dict 读, 0 DB)"""
    state = REALTIME_STATE.get(ts_code)
    if not state:
        # 占位: 收盘或未采集
        if _is_trading_hours():
            return {
                'available': False,
                'status': 'pending',
                'message': '盘中实时数据采集中, 请稍候 3 秒',
            }
        return {
            'available': False,
            'status': 'closed',
            'message': '非交易时段, 实时数据未采集',
        }
    s = serialize_state(ts_code)
    s['available'] = True
    s['status'] = 'live'
    # 计算 pct_chg 需要昨收价, 取自 state.last_close 字段
    last_close = getattr(state, 'last_close', 0) or 0
    if last_close and s.get('current_price'):
        s['pct_chg'] = round((s['current_price'] - last_close) / last_close * 100, 2)
    return s


@router.get('/api/v1/stock/super_panel')
def super_panel(code: str = Query(..., description='股票代码, 6位 或 ts_code 格式'),
                section: str = Query('all', description='all / realtime / static')):
    """
    个股全聚合单页面接口
    - section=all: 静态+实时全部返回
    - section=static: 只返回盘后静态
    - section=realtime: 只返回盘中实时(前端 3 秒轮询用)
    """
    ts_code = _normalize_ts_code(code)
    if not ts_code:
        return {'error': 'invalid code'}

    update_time = datetime.now().isoformat(timespec='seconds')
    state = REALTIME_STATE.get(ts_code)
    realtime_health = 'live' if state else ('closed' if not _is_trading_hours() else 'stale')

    if section == 'realtime':
        return {
            'ts_code': ts_code,
            'update_time': update_time,
            'realtime_intraday': _realtime_section(ts_code),
            'source_health': {'static': 'ok', 'realtime': realtime_health},
        }

    if section == 'static':
        return {
            'ts_code': ts_code,
            'update_time': update_time,
            'post_market_base': _load_post_market_base(ts_code),
            'source_health': {'static': 'ok', 'realtime': realtime_health},
        }

    # section=all
    return {
        'ts_code': ts_code,
        'update_time': update_time,
        'source_health': {
            'static': 'ok',
            'realtime': realtime_health,
        },
        'post_market_base': _load_post_market_base(ts_code),
        'realtime_intraday': _realtime_section(ts_code),
    }


@router.get('/api/v1/stock/super_panel/health')
def super_panel_health():
    """健康检查: 返回当前 REALTIME_STATE 中股票数 + 调度状态"""
    from collectors.scheduler import _is_intraday_trading_hours
    return {
        'realtime_state_count': len(REALTIME_STATE),
        'trading_hours': _is_intraday_trading_hours(),
        'ts_codes_sample': list(REALTIME_STATE.keys())[:20],
        'check_time': datetime.now().isoformat(timespec='seconds'),
    }
