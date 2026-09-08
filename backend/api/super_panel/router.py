"""
个股全聚合单页面接口（双轨制中转层 - 聚合轨）

- GET /api/v1/stock/super_panel?code=600xxx  →  静态 + 实时 一次返回
- GET /api/v1/stock/super_panel?code=600xxx&section=realtime  →  仅返回实时（3 秒轮询用）

为什么单点聚合而不是让前端拼装:
- 盘后静态 7 个表, 1 次 JOIN 完成 vs 前端 N 次请求
- 盘中实时读取采集器已落库快照
- 前端只读不拼, 失败降级统一在服务端处理
"""
import logging
from datetime import datetime, timedelta, time as dtime
from fastapi import APIRouter, Query

from db.session import get_db_session
from db.models import (
    YuziQuantSignal, YuziSeatDaily, YuziDict, YuziLifecycleTracker,
    ConceptSector, ConceptSectorFlow, RealtimeStockFlow, StockRealtimeTick, Watchlist,
)

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
    """读取最近一条已落库盘中快照，并保持字段的时间和单位口径一致。"""
    with get_db_session() as db:
        tick = db.query(StockRealtimeTick).filter(
            StockRealtimeTick.ts_code == ts_code,
        ).order_by(StockRealtimeTick.snapshot_time.desc()).first()
        flow = db.query(RealtimeStockFlow).filter(
            RealtimeStockFlow.ts_code == ts_code,
        ).order_by(RealtimeStockFlow.snapshot_time.desc()).first()
    latest_time = max(
        (value for value in (
            tick.snapshot_time if tick else None,
            flow.snapshot_time if flow else None,
        ) if value is not None),
        default=None,
    )
    trading_hours = _is_trading_hours()
    if latest_time is None:
        if trading_hours:
            return {
                'available': False,
                'status': 'missing',
                'source': 'database',
                'message': '数据库暂无盘中快照，请等待采集任务入库',
            }
        return {
            'available': False,
            'status': 'missing',
            'source': 'database',
            'message': '数据库暂无盘中快照',
        }

    # 两个表由不同任务写入。只把距离最新快照 1 分钟内的数据当作同一轮快照，
    # 避免“新价格 + 旧资金”或跨时点盘口在一个卡片里混用。
    def is_current_snapshot(snapshot_time):
        return snapshot_time is not None and (latest_time - snapshot_time).total_seconds() <= 60

    tick_current = bool(tick and is_current_snapshot(tick.snapshot_time))
    flow_current = bool(flow and is_current_snapshot(flow.snapshot_time))
    tick_is_derived = bool(tick and tick.source == 'realtime_stock_flow')
    tick_is_fallback = bool(tick and tick.source == 'fallback')
    flow_is_fallback = bool(flow and (flow.source or '').strip().lower() == 'fallback')
    # 聚合器会把 realtime_stock_flow 同步写成兼容 tick。若其源 flow 是 fallback，
    # 该 tick 中的 0 仍然只是占位，不得反过来认定为真实实时资金。
    derived_tick_is_fallback = tick_is_derived and flow_current and flow_is_fallback
    tick_has_live_flow = tick_current and not tick_is_fallback and not derived_tick_is_fallback
    has_live_flow = (
        (flow_current and not flow_is_fallback and flow.main_force_inflow is not None)
        or (tick_has_live_flow and tick_is_derived and tick.main_force_inflow is not None)
    )
    stale = trading_hours and (datetime.now() - latest_time).total_seconds() > 300

    # realtime_stock_flow 的兼容 tick 只承载价格和主力资金，盘口/成交量字段的 0 是占位，
    # 必须返回 null，不能在界面上伪装成真实的 0。
    tick_has_orderbook = tick_current and not tick_is_derived and not tick_is_fallback
    current_price = (
        float(tick.price) if tick_current and tick.price is not None else
        float(flow.price) if flow_current and flow.price is not None else None
    )
    main_force_inflow = (
        float(tick.main_force_inflow)
        if tick_has_live_flow and tick_is_derived and tick.main_force_inflow is not None
        else float(flow.main_force_inflow) * 10000
        if flow_current and not flow_is_fallback and flow.main_force_inflow is not None
        else float(tick.main_force_inflow)
        if tick_has_live_flow and tick.main_force_inflow is not None
        else None
    )
    return {
        'available': current_price is not None,
        'status': (
            'stale' if stale else
            'ready' if trading_hours and has_live_flow else
            'price_only' if trading_hours else 'closed_snapshot'
        ),
        'data_quality': 'flow' if has_live_flow else 'price_only',
        'current_price': current_price,
        'pct_chg': float(flow.price_chg) if flow_current and not flow_is_fallback and flow.price_chg is not None else None,
        'volume': int(tick.volume) if tick_has_orderbook and tick.volume is not None else None,
        'amount': float(tick.amount) if tick_has_orderbook and tick.amount is not None else None,
        'bid_price_1': float(tick.bid_price_1) if tick_has_orderbook and tick.bid_price_1 is not None else None,
        'bid_vol_1': int(tick.bid_vol_1) if tick_has_orderbook and tick.bid_vol_1 is not None else None,
        'ask_price_1': float(tick.ask_price_1) if tick_has_orderbook and tick.ask_price_1 is not None else None,
        'ask_vol_1': int(tick.ask_vol_1) if tick_has_orderbook and tick.ask_vol_1 is not None else None,
        'turnover_rate': float(tick.turnover_rate) if tick_has_orderbook and tick.turnover_rate is not None else None,
        'main_force_inflow': main_force_inflow,
        'snapshot_time': latest_time.isoformat(),
        'price_as_of': tick.snapshot_time.isoformat() if tick_current else flow.snapshot_time.isoformat() if flow_current else None,
        'flow_as_of': flow.snapshot_time.isoformat() if flow_current and not flow_is_fallback else None,
        'source': 'database',
        'upstream_source': flow.source if flow_current else tick.source if tick_current else None,
    }


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
    realtime_data = _realtime_section(ts_code)
    realtime_health = realtime_data.get('status', 'missing')

    if section == 'realtime':
        return {
            'ts_code': ts_code,
            'update_time': update_time,
            'realtime_intraday': realtime_data,
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
        'realtime_intraday': realtime_data,
    }


@router.get('/api/v1/stock/super_panel/health')
def super_panel_health():
    """健康检查：返回数据库最新实时快照覆盖。"""
    from sqlalchemy import func
    from collectors.scheduler import _is_intraday_trading_hours
    with get_db_session() as db:
        latest = db.query(func.max(RealtimeStockFlow.snapshot_time)).scalar()
        codes = [row[0] for row in db.query(RealtimeStockFlow.ts_code).filter(
            RealtimeStockFlow.snapshot_time == latest
        ).limit(20).all()] if latest else []
        count = db.query(func.count(RealtimeStockFlow.id)).filter(
            RealtimeStockFlow.snapshot_time == latest
        ).scalar() if latest else 0
    return {
        'realtime_state_count': int(count or 0),
        'trading_hours': _is_intraday_trading_hours(),
        'ts_codes_sample': codes,
        'latest_snapshot_time': latest.isoformat() if latest else None,
        'source': 'database',
        'check_time': datetime.now().isoformat(timespec='seconds'),
    }
