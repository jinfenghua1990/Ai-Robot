"""
持仓分析API（东财模拟盘 + 原模拟盘双源 + 历史快照）
- 优先读取东财模拟盘（mx-trading）持仓数据（用户主用账户）
- 若东财数据为空，回退到原模拟盘（SimPosition）持仓
- 构造与 /api/watchlist 口径一致的 signal 列表
- 支持 date 参数查询历史快照
"""
import time
import asyncio
import logging
from datetime import date, datetime
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from analyzers.strategy_engine import get_config, update_config
from db.session import get_db_session
from db.models import SimPositionSnapshot, SimAccountSnapshot
from api.trading import get_positions as _get_local_positions
from services.signal_builder import build_signal_for_stock

logger = logging.getLogger(__name__)

router = APIRouter()

# 信号缓存（30秒）
_signal_cache = {"data": None, "ts": 0}
_SIGNAL_CACHE_TTL = 30


def _today() -> date:
    return datetime.now().date()


def _parse_date(d: Optional[str]) -> Optional[date]:
    if not d:
        return None
    try:
        return date.fromisoformat(d)
    except ValueError:
        return None


async def _fetch_mx_positions_raw() -> tuple:
    """从东财妙想模拟盘（mx-trading）拉取持仓，返回 (positions, total_assets)"""
    from api.mx_trading import get_positions as _get_mx_positions
    try:
        data = await _get_mx_positions(force=1)
        return data.get('positions', []), data.get('totalAssets', 0)
    except Exception as e:
        logger.warning(f'fetch mx positions failed: {e}')
        return [], 0


async def _fetch_positions_raw():
    """优先取东财模拟盘持仓；为空时回退原模拟盘"""
    mx_positions, mx_assets = await _fetch_mx_positions_raw()
    if mx_positions:
        return mx_positions, mx_assets, 'mx'
    local_data = await _get_local_positions()
    local_positions = local_data.get('positions', []) if isinstance(local_data, dict) else (local_data or [])
    local_assets = local_data.get('totalAssets', 0) if isinstance(local_data, dict) else 0
    if local_positions:
        # 统一字段名：SimPosition dict 已是 secCode/secName 风格
        normalized = [{
            'secCode': str(p.get('secCode') or p.get('code') or '').zfill(6),
            'secName': p.get('secName') or p.get('name', ''),
            'secMkt': p.get('secMkt', 0),
            'count': p.get('count', 0),
            'availCount': p.get('availCount', 0),
            'price': p.get('price', 0),
            'costPrice': p.get('costPrice', 0),
            'value': p.get('value', 0),
            'dayProfit': p.get('dayProfit', 0),
            'dayProfitPct': p.get('dayProfitPct', 0),
            'profit': p.get('profit', 0),
            'profitPct': p.get('profitPct', 0),
            'posPct': p.get('posPct', 0),
        } for p in local_positions]
        return normalized, local_assets, 'local'
    return [], 0, 'empty'


def _load_snapshot(target_date: date) -> tuple:
    """从本地快照加载某日的持仓和账户数据，返回 (positions, total_assets, source)"""
    with get_db_session() as db:
        rows = db.query(SimPositionSnapshot).filter_by(trade_date=target_date).all()
        if not rows:
            return [], 0, 'empty'
        positions = [{
            'secCode': str(r.sec_code or '').zfill(6),
            'secName': r.sec_name or '',
            'secMkt': r.sec_mkt or 0,
            'count': int(r.count or 0),
            'availCount': int(r.avail_count or 0),
            'price': float(r.price or 0),
            'costPrice': float(r.cost_price or 0),
            'value': float(r.value or 0),
            'dayProfit': float(r.day_profit or 0),
            'dayProfitPct': float(r.day_profit_pct or 0),
            'profit': float(r.profit or 0),
            'profitPct': float(r.profit_pct or 0),
            'posPct': float(r.pos_pct or 0),
        } for r in rows]
        account = db.query(SimAccountSnapshot).filter_by(trade_date=target_date).first()
        total_assets = float(account.total_assets or 0) if account else 0
        return positions, total_assets, rows[0].source or 'mx'


def _build_snapshot_rows(positions: list, total_assets: float, source: str, target_date: date):
    """构造快照 ORM 对象列表"""
    return [SimPositionSnapshot(
        trade_date=target_date,
        source=source,
        sec_code=str(p.get('secCode') or p.get('code') or '').zfill(6),
        sec_name=p.get('secName') or p.get('name', ''),
        sec_mkt=p.get('secMkt', 0),
        count=p.get('count', 0),
        avail_count=p.get('availCount', 0),
        cost_price=p.get('costPrice', 0),
        price=p.get('price', 0),
        value=p.get('value', 0),
        day_profit=p.get('dayProfit', 0),
        day_profit_pct=p.get('dayProfitPct', 0),
        profit=p.get('profit', 0),
        profit_pct=p.get('profitPct', 0),
        pos_pct=p.get('posPct', 0),
    ) for p in positions]


async def snapshot_today_positions(target_date: date = None):
    """为指定日期（默认今天）创建东财模拟盘持仓快照。
    收盘归档时由 scheduler 调用。"""
    d = target_date or _today()
    positions, total_assets, source = await _fetch_positions_raw()
    try:
        with get_db_session() as db:
            # 幂等：先删后插
            db.query(SimPositionSnapshot).filter_by(trade_date=d).delete()
            db.query(SimAccountSnapshot).filter_by(trade_date=d).delete()

            if positions:
                for row in _build_snapshot_rows(positions, total_assets, source, d):
                    db.add(row)

            # 账户快照
            if source == 'mx':
                from api.mx_trading import get_balance as _get_mx_balance
                balance = await _get_mx_balance(force=1)
            else:
                from api.trading import get_balance as _get_local_balance
                balance = await _get_local_balance()
            db.add(SimAccountSnapshot(
                trade_date=d,
                source=source,
                acc_name=balance.get('accName', ''),
                acc_id=str(balance.get('accID', '')),
                init_money=balance.get('initMoney', 0),
                total_assets=balance.get('totalAssets', 0),
                avail_balance=balance.get('availBalance', 0),
                frozen_money=balance.get('frozenMoney', 0),
                total_pos_value=balance.get('totalPosValue', 0),
                total_pos_pct=balance.get('totalPosPct', 0),
                nav=balance.get('nav', 0),
                opr_days=balance.get('oprDays', 0),
            ))
            db.commit()
            print(f'[sim_snapshot] saved {len(positions)} positions for {d} (source={source})')
            return {'date': d.isoformat(), 'count': len(positions), 'source': source}
    except Exception as e:
        db.rollback()
        logger.exception(f'snapshot positions error: {e}')
        raise


def _build_signals_from_positions(positions: list, total_assets: float, source: str):
    """把持仓列表转换为统一 signal 列表（同步计算，不请求行情）"""
    if not positions:
        return []

    signals = []
    for pos in positions:
        profit_pct = float(pos.get('profitPct', 0))
        if profit_pct >= 5:
            signal_label, signal_key = '加仓', 'add'
        elif profit_pct <= -5:
            signal_label, signal_key = '减仓', 'reduce'
        else:
            signal_label, signal_key = '关注', 'watch'

        signals.append({
            'secCode': str(pos.get('secCode', '')).zfill(6),
            'secName': pos.get('secName', ''),
            'signal': signal_key,
            'signalLabel': signal_label,
            'signalColor': '#22c55e' if signal_key == 'add' else '#f97316' if signal_key == 'reduce' else '#6b7280',
            'riskLevel': 'high' if profit_pct <= -10 else 'medium' if profit_pct <= -5 else 'low',
            'score': 0,
            'reasons': [f'盈亏 {profit_pct:+.2f}%'],
            'positiveFactors': [],
            'negativeFactors': [],
            'sector': '',
            'sectorTrend': {'available': False},
            'position': {
                'count': pos.get('count', 0),
                'availCount': pos.get('availCount', 0),
                'price': pos.get('price', 0),
                'costPrice': pos.get('costPrice', 0),
                'value': pos.get('value', 0),
                'dayProfit': pos.get('dayProfit', 0),
                'dayProfitPct': pos.get('dayProfitPct', 0),
                'profit': pos.get('profit', 0),
                'profitPct': profit_pct,
                'posPct': pos.get('posPct', 0),
            },
            'marketState': {'market_state': 'PENDING', 'reasons': ['待计算']},
            'buyPower': {'score': 0, 'level': '待算', 'dimensions': {}, 'color': '#6b7280'},
            'qualityStatus': '普通',
            'quote': None,
            'bsSignal': None,
            '_source': source,
        })
    return signals


@router.get("/api/trading/signals")
async def get_signals(date: str = Query(None, description="历史日期 YYYY-MM-DD，默认今天实时")):
    """获取持仓分析信号（东财/原模拟盘双源 + 历史快照）"""
    target_date = _parse_date(date)

    # 只有查询今天实时数据时才使用内存缓存
    if not target_date or target_date == _today():
        now = time.time()
        if _signal_cache["data"] and now - _signal_cache["ts"] < _SIGNAL_CACHE_TTL:
            return _signal_cache["data"]

    try:
        if target_date and target_date != _today():
            # 历史日期：优先读取本地快照
            positions, total_assets, source = _load_snapshot(target_date)
            use_enrich = False  # 历史快照不再 enrich，避免行情/状态已变
        else:
            positions, total_assets, source = await _fetch_positions_raw()
            use_enrich = True
    except Exception as e:
        if (not target_date or target_date == _today()) and _signal_cache["data"]:
            return _signal_cache["data"]
        return {
            "signals": [],
            "summary": {"total": 0, "strong_sell": 0, "sell": 0, "hold": 0, "add": 0, "high_risk": 0},
            "config": get_config(),
            "generated_at": time.strftime('%Y-%m-%d %H:%M:%S'),
            "error": str(e),
        }

    if not positions:
        result = {
            "signals": [],
            "summary": {"total": 0, "strong_sell": 0, "sell": 0, "hold": 0, "add": 0, "high_risk": 0},
            "config": get_config(),
            "generated_at": time.strftime('%Y-%m-%d %H:%M:%S'),
            "source": source,
            "date": (target_date or _today()).isoformat(),
        }
        if not target_date or target_date == _today():
            _signal_cache["data"] = result
            _signal_cache["ts"] = time.time()
        return result

    if use_enrich:
        # 今天实时：用 build_signal_for_stock 增强为 18 字段 signal
        with get_db_session() as db:
            tasks = [build_signal_for_stock(
                str(p.get('secCode', '')),
                p.get('secName', ''),
                '',
                db,
            ) for p in positions]
            enriched = await asyncio.gather(*tasks, return_exceptions=True)

        signals = []
        for pos, sig in zip(positions, enriched):
            if isinstance(sig, Exception) or sig is None:
                continue
            sig['position'] = {
                'count': pos.get('count', 0),
                'availCount': pos.get('availCount', 0),
                'price': pos.get('price', 0),
                'costPrice': pos.get('costPrice', 0),
                'value': pos.get('value', 0),
                'dayProfit': pos.get('dayProfit', 0),
                'dayProfitPct': pos.get('dayProfitPct', 0),
                'profit': pos.get('profit', 0),
                'profitPct': pos.get('profitPct', 0),
                'posPct': pos.get('posPct', 0),
            }
            profit_pct = pos.get('profitPct', 0)
            if profit_pct >= 5:
                sig['signalLabel'] = '加仓'; sig['signal'] = 'add'; sig['signalColor'] = '#22c55e'
            elif profit_pct <= -5:
                sig['signalLabel'] = '减仓'; sig['signal'] = 'reduce'; sig['signalColor'] = '#f97316'
            else:
                sig['signalLabel'] = '关注'; sig['signal'] = 'watch'; sig['signalColor'] = '#6b7280'
            sig['_source'] = source
            signals.append(sig)
    else:
        signals = _build_signals_from_positions(positions, total_assets, source)

    summary = {
        "total": len(signals),
        "strong_sell": sum(1 for s in signals if s['position']['profitPct'] <= -10),
        "sell": sum(1 for s in signals if -10 < s['position']['profitPct'] <= -5),
        "hold": sum(1 for s in signals if -5 < s['position']['profitPct'] < 5),
        "add": sum(1 for s in signals if s['position']['profitPct'] >= 5),
        "high_risk": sum(1 for s in signals if s.get('riskLevel') == 'high'),
    }

    result = {
        "signals": signals,
        "summary": summary,
        "config": get_config(),
        "generated_at": time.strftime('%Y-%m-%d %H:%M:%S'),
        "source": source,
        "date": (target_date or _today()).isoformat(),
    }
    if not target_date or target_date == _today():
        _signal_cache["data"] = result
        _signal_cache["ts"] = time.time()
    return result


@router.get("/api/trading/history")
async def get_history_dates():
    """返回所有有快照的日期列表"""
    with get_db_session() as db:
        rows = db.query(SimAccountSnapshot.trade_date).order_by(SimAccountSnapshot.trade_date.desc()).all()
        return {'dates': [r[0].isoformat() for r in rows]}


@router.get("/api/trading/history/{date_str}")
async def get_history_by_date(date_str: str):
    """返回某一天的账户 + 持仓快照"""
    d = _parse_date(date_str)
    if not d:
        raise HTTPException(status_code=400, detail='日期格式错误，应为 YYYY-MM-DD')
    positions, total_assets, source = _load_snapshot(d)
    with get_db_session() as db:
        account = db.query(SimAccountSnapshot).filter_by(trade_date=d).first()
    return {
        'date': d.isoformat(),
        'source': source,
        'account': {
            'accName': account.acc_name if account else '',
            'accID': account.acc_id if account else '',
            'initMoney': float(account.init_money or 0) if account else 0,
            'totalAssets': float(account.total_assets or 0) if account else 0,
            'availBalance': float(account.avail_balance or 0) if account else 0,
            'frozenMoney': float(account.frozen_money or 0) if account else 0,
            'totalPosValue': float(account.total_pos_value or 0) if account else 0,
            'totalPosPct': float(account.total_pos_pct or 0) if account else 0,
            'nav': float(account.nav or 0) if account else 0,
            'oprDays': account.opr_days or 0 if account else 0,
        },
        'positions': positions,
    }


@router.get("/api/trading/strategy-config")
async def get_strategy_config():
    """获取当前策略参数"""
    return get_config()


class StrategyConfigUpdate(BaseModel):
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    add_position_pct: Optional[float] = None
    sector_heat_threshold: Optional[float] = None
    sector_trend_days: Optional[int] = None
    max_position_pct: Optional[float] = None
    sector_decline_days: Optional[int] = None


@router.post("/api/trading/strategy-config")
async def set_strategy_config(req: StrategyConfigUpdate):
    """更新策略参数"""
    update_config(req.dict(exclude_none=True))
    # 清除信号缓存，使下次请求重新计算
    _signal_cache["data"] = None
    return {"status": "ok", "config": get_config()}


async def refresh_signal_cache():
    """强制刷新信号缓存（基于原模拟盘持仓）"""
    _signal_cache["data"] = None
    try:
        await get_signals()
        print('[cache] signal cache refreshed')
    except Exception as e:
        print(f'[cache] signal refresh error: {e}')
