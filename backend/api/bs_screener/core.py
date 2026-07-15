"""BS 选股扫描核心：候选池 + 单只扫描 + 通用过滤器"""
import asyncio
import time
from datetime import datetime
from sqlalchemy import func as sql_func

from db.models import StockFlow
from api.bs_signals import _fetch_kline, _generate_bs_signals, _calc_ma
from analyzers.strategy_engine import _find_sector_for_stock, _get_sector_trend
import logging
from utils.http_constants import SINA_HEADERS_SHORT
from api.watchlist._shared import _get_http_client
logger = logging.getLogger(__name__)

# 结果缓存（避免重复扫描）
_scan_cache = {'data': None, 'ts': 0, 'params_key': ''}

# K线数据缓存（code -> {data, ts}），TTL 30分钟
_kline_cache: dict = {}
_KLINE_CACHE_TTL = 1800


async def _fetch_kline_cached(code: str, datalen: int = 80):
    """带缓存的 K 线获取"""
    cache_key = f"{code}_{datalen}"
    now = time.time()
    cached = _kline_cache.get(cache_key)
    if cached and now - cached['ts'] < _KLINE_CACHE_TTL:
        return cached['data']
    klines = await _fetch_kline(code, datalen)
    _kline_cache[cache_key] = {'data': klines, 'ts': now}
    if len(_kline_cache) > 200:
        oldest = min(_kline_cache.items(), key=lambda x: x[1]['ts'])
        _kline_cache.pop(oldest[0], None)
    return klines


async def _get_quote(code: str):
    """获取新浪实时行情"""
    sina_code = f'sh{code}' if code[0] in ('6', '9') else f'sz{code}'
    url = f"https://hq.sinajs.cn/list={sina_code}"
    try:
        client = _get_http_client()
        resp = await client.get(url, headers=SINA_HEADERS_SHORT)
        resp.encoding = 'gbk'
        text = resp.text
        parts = text.split('"')[1].split(',')
        if len(parts) < 10:
            return None
        yesterday_close = float(parts[1])
        current_price = float(parts[3])
        change = current_price - yesterday_close
        change_pct = (change / yesterday_close * 100) if yesterday_close else 0
        return {
            'price': current_price,
            'changePct': round(change_pct, 2),
            'name': parts[0],
        }
    except Exception:
        logger.debug(f"_get_quote failed", exc_info=True)
        return None


async def _scan_single_stock(code: str, name: str, sector: str, period: int, multiplier: float, signal_type: str,
                             volume_filter: bool = False, ma20_filter: bool = False,
                             ma60_trend: bool = False, rsi_filter: bool = False, strong_volume: bool = False,
                             macd_filter: bool = False, kdj_filter: bool = False,
                             rsi_lower: int = 30, rsi_upper: int = 70):
    """扫描单只股票的 BS 信号"""
    try:
        klines = await _fetch_kline_cached(code, 120)
        if len(klines) < 20:
            return None

        bs_signals, dif, dea, macd, ma5, ma20, k_vals, d_vals, j_vals, support, resistance, trend = \
            _generate_bs_signals(klines, period, multiplier)

        if not bs_signals:
            return None

        last_signal = bs_signals[-1]
        if signal_type != 'ALL' and last_signal['type'] != signal_type:
            return None

        ma60 = None
        rsi_vals = None
        if ma60_trend:
            ma60 = _calc_ma(klines, 60)
        if rsi_filter:
            from api.bs_signals import _calc_rsi
            rsi_vals = _calc_rsi(klines, 14)

        sig_idx = None
        for i, k in enumerate(klines):
            if k['date'] == last_signal['date']:
                sig_idx = i
                break

        if sig_idx is not None and sig_idx > 0:
            if volume_filter and last_signal['type'] == 'B' and sig_idx >= 5:
                vol_today = klines[sig_idx]['volume']
                vol_avg5 = sum(klines[sig_idx - 5 + j]['volume'] for j in range(5)) / 5
                if vol_today < vol_avg5:
                    return None
            if strong_volume and last_signal['type'] == 'B' and sig_idx >= 5:
                vol_today = klines[sig_idx]['volume']
                vol_avg5 = sum(klines[sig_idx - 5 + j]['volume'] for j in range(5)) / 5
                if vol_today < vol_avg5 * 2:
                    return None
            if ma20_filter and last_signal['type'] == 'B' and ma20 and sig_idx > 0:
                if ma20[sig_idx] is None or ma20[sig_idx - 1] is None:
                    return None
                if ma20[sig_idx] <= ma20[sig_idx - 1]:
                    return None
            if ma60_trend and last_signal['type'] == 'B' and ma60 and sig_idx > 0:
                if ma60[sig_idx] is None:
                    return None
                if klines[sig_idx]['close'] < ma60[sig_idx]:
                    return None
            if rsi_filter and last_signal['type'] == 'B' and rsi_vals and sig_idx > 0:
                rsi = rsi_vals[sig_idx]
                if rsi is None or rsi < rsi_lower or rsi > rsi_upper:
                    return None
            if macd_filter and last_signal['type'] == 'B' and sig_idx > 0:
                if macd[sig_idx] is None or macd[sig_idx] <= 0:
                    return None
            if kdj_filter and last_signal['type'] == 'B' and sig_idx > 0:
                if k_vals[sig_idx] is None or k_vals[sig_idx] >= 80:
                    return None

        quote = await _get_quote(code)
        price = quote['price'] if quote else last_signal['price']
        change_pct = quote['changePct'] if quote else 0

        return {
            'code': code,
            'name': quote['name'] if quote else name,
            'sector': sector,
            'signal': last_signal['type'],
            'signal_date': last_signal['date'],
            'signal_price': last_signal['price'],
            'reasons': last_signal.get('reasons', []),
            'price': price,
            'change_pct': change_pct,
            'trend': '多头' if trend[-1] == 1 else '空头',
        }
    except Exception:
        logger.debug(f"function failed", exc_info=True)
        return None


async def _execute_bs_scan_core(
    db, *,
    atr_period: int = 10,
    atr_multiplier: float = 1.0,
    scan_limit: int = 50,
    sector: str = '',
    signal_type: str = 'B',
    volume_filter: bool = False,
    ma20_filter: bool = False,
    ma60_trend: bool = False,
    rsi_filter: bool = False,
    strong_volume: bool = False,
    macd_filter: bool = False,
    kdj_filter: bool = False,
    rsi_lower: int = 30,
    rsi_upper: int = 70,
    dimension: str = '',
) -> dict:
    """BS 选股扫描核心逻辑（端点 + 预计算共用）"""
    latest_subq = db.query(
        sql_func.max(StockFlow.id).label('max_id')
    ).group_by(StockFlow.ts_code).subquery()

    query = db.query(StockFlow).join(
        latest_subq, StockFlow.id == latest_subq.c.max_id
    ).filter(StockFlow.main_force_inflow > 0)

    if dimension == 'star':
        query = query.filter(StockFlow.ts_code.like('688%'))
    elif dimension == 'chinext':
        query = query.filter(StockFlow.ts_code.like('300%'))
    elif dimension == 'all':
        pass

    if sector:
        sector_list = [s.strip() for s in sector.split(',') if s.strip()]
        if sector_list:
            query = query.filter(StockFlow.sector.in_(sector_list))
    if dimension in ('all', 'star', 'chinext'):
        candidates = query.order_by(StockFlow.main_force_inflow.desc()).all()
    else:
        candidates = query.order_by(StockFlow.main_force_inflow.desc()).limit(scan_limit).all()

    if not candidates:
        return {
            'signals': [],
            'summary': {'total': 0, 'buy': 0, 'sell': 0, 'watch': 0, 'high_risk': 0, 'scanned': 0},
            'scanned': 0,
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    semaphore = asyncio.Semaphore(10)

    async def scan_with_limit(c):
        async with semaphore:
            return await _scan_single_stock(
                c.ts_code.replace('.SH', '').replace('.SZ', ''),
                c.name, c.sector,
                atr_period, atr_multiplier, signal_type,
                volume_filter, ma20_filter, ma60_trend, rsi_filter, strong_volume,
                macd_filter, kdj_filter, rsi_lower, rsi_upper
            )

    tasks = [scan_with_limit(c) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    hits = []
    for r in results:
        if r and not isinstance(r, Exception):
            hits.append(r)

    signals = []
    buy_count = 0
    sell_count = 0
    watch_count = 0

    for h in hits:
        ts_code = h['code']
        ts_code_full = f"{ts_code}.SH" if ts_code[0] in ('6', '9') else f"{ts_code}.SZ"

        stock_sector = _find_sector_for_stock(db, ts_code_full) or h['sector']
        sector_trend = _get_sector_trend(db, stock_sector, 7) if stock_sector else {"sector": "", "available": False}

        if h['signal'] == 'B':
            signal_label = '加仓'
            signal_color = '#22c55e'
            signal_type_val = 'ADD'
            buy_count += 1
        elif h['signal'] == 'S':
            signal_label = '减仓'
            signal_color = '#f97316'
            signal_type_val = 'SELL'
            sell_count += 1
        else:
            signal_label = '关注'
            signal_color = '#3b82f6'
            signal_type_val = 'WATCH'
            watch_count += 1

        positive_factors = []
        negative_factors = []

        if h['signal'] == 'B':
            positive_factors.append({'factor': 'BS买入', 'detail': h['reasons'][0] if h['reasons'] else 'SuperTrend突破', 'weight': 2})
        if h['signal'] == 'S':
            negative_factors.append({'factor': 'BS卖出', 'detail': h['reasons'][0] if h['reasons'] else 'SuperTrend跌破', 'weight': -2})
        if h['change_pct'] > 0:
            positive_factors.append({'factor': '当日上涨', 'detail': f'涨幅 {h["change_pct"]:+.2f}%', 'weight': 1})
        if h['change_pct'] < 0:
            negative_factors.append({'factor': '当日下跌', 'detail': f'跌幅 {h["change_pct"]:+.2f}%', 'weight': -1})
        if sector_trend.get('available') and sector_trend.get('heat_trend') == 'up':
            positive_factors.append({'factor': '板块升温', 'detail': f'板块热度上升至 {sector_trend["latest_heat"]:.1f}', 'weight': 1})
        if sector_trend.get('available') and sector_trend.get('heat_trend') == 'down':
            negative_factors.append({'factor': '板块降温', 'detail': f'板块热度下降至 {sector_trend["latest_heat"]:.1f}', 'weight': -1})

        score = len(positive_factors) - len(negative_factors)
        reasons = list(h['reasons'])
        reasons.append(f'信号日期: {h["signal_date"]}')
        reasons.append(f'当前趋势: {h["trend"]}')
        reasons.append(f'综合评分: {"看多" if score > 0 else "看空" if score < 0 else "中性"} → {signal_label}')

        signals.append({
            'secCode': ts_code,
            'secName': h['name'],
            'signal': signal_type_val,
            'signalLabel': signal_label,
            'signalColor': signal_color,
            'riskLevel': 'low',
            'score': score,
            'reasons': reasons,
            'positiveFactors': positive_factors,
            'negativeFactors': negative_factors,
            'sector': stock_sector or h['sector'] or '',
            'sectorTrend': sector_trend,
            'position': {
                'profitPct': h['change_pct'],
                'posPct': 0,
                'dayProfit': 0,
                'dayProfitPct': h['change_pct'],
                'count': 0,
                'price': h['price'],
                'costPrice': 0,
                'value': 0,
                'profit': 0,
            },
            'signalDate': h['signal_date'],
            'signalPrice': h['signal_price'],
            'trend': h['trend'],
        })

    priority = {'ADD': 0, 'SELL': 1, 'WATCH': 2}
    signals.sort(key=lambda x: (priority.get(x['signal'], 9), -x['score']))

    return {
        'signals': signals,
        'summary': {
            'total': len(signals),
            'buy': buy_count,
            'sell': sell_count,
            'watch': watch_count,
            'high_risk': 0,
            'scanned': len(candidates),
        },
        'scanned': len(candidates),
        'params': {
            'atr_period': atr_period,
            'atr_multiplier': atr_multiplier,
            'scan_limit': scan_limit,
            'sector': sector,
            'signal_type': signal_type,
            'volume_filter': volume_filter,
            'ma20_filter': ma20_filter,
        },
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
