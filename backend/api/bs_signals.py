"""
BS点信号API
1. 从新浪财经获取K线数据（多取历史数据用于EMA收敛，返回最近N天）
2. 基于SuperTrend(超级趋势指标)生成B/S操盘线信号
3. 从东方财富获取用户模拟盘交易记录，标记在K线上

BS点生成逻辑（SuperTrend单信号源）：
- B点: SuperTrend从空头转多头（收盘突破上轨）
- S点: SuperTrend从多头转空头（收盘跌破下轨）
- 辅助reason: MACD金叉/死叉、DIF拐头、KDJ金叉/死叉
- 单信号源天然交替(B→S→B→S)，无需去噪
"""
import time
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from db.session import get_db_session
from db.models import StockFlow
from analyzers.strategy_engine import _find_sector_for_stock, _get_sector_trend
from utils.cache import BoundedDict
from services.indicators import (
    calc_ma as _calc_ma_impl,
    calc_macd as _calc_macd_impl,
    calc_rsi as _calc_rsi_impl,
    calc_kdj as _calc_kdj_impl,
    calc_supertrend as _calc_supertrend_impl,
)

import logging
from api.watchlist._shared import (
    _candidate_ts_codes,
    batch_get_quotes,
    fetch_kline_cached,
    get_quote,
)
logger = logging.getLogger(__name__)

router = APIRouter()

# 计算用历史数据天数（需远大于EMA26周期，确保EMA收敛）
CALC_DATALEN = 150


async def _fetch_kline(stock_code: str, datalen: int = CALC_DATALEN):
    """只读取 stock_daily_kline；数据不足时返回已有行，不触发外采。"""
    return await fetch_kline_cached(stock_code, datalen)


def _generate_bs_signals(klines, period=10, multiplier=1.0):
    """
    基于SuperTrend(超级趋势指标)生成BS点
    - B点: SuperTrend从空头转多头(收盘突破上轨)
    - S点: SuperTrend从多头转空头(收盘跌破下轨)
    辅助reason: MACD金叉/死叉、DIF拐头、KDJ金叉/死叉
    单信号源，天然交替(B→S→B→S)，无需去噪
    可配置参数: period(ATR周期), multiplier(乘数)
    """
    closes = [k['close'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]

    # 主信号源: SuperTrend
    support, resistance, trend, atr = _calc_supertrend_impl(highs, lows, closes, period, multiplier)

    # 辅助指标(用于reason和indicators返回)
    dif, dea, macd = _calc_macd_impl(closes)
    ma5 = _calc_ma_impl(closes, 5)
    ma20 = _calc_ma_impl(closes, 20)
    k_vals, d_vals, j_vals = _calc_kdj_impl(highs, lows, closes, 9, 3, 3)

    signals = []
    for i in range(1, len(klines)):
        if trend[i] == trend[i-1]:
            continue  # 无变轨，无信号

        signal_type = 'B' if trend[i] == 1 else 'S'
        date = klines[i]['date']
        reasons = []

        # 主信号reason
        if signal_type == 'B':
            reasons.append(f'SuperTrend多头: 收盘{klines[i]["close"]:.2f}突破阻力线{resistance[i-1]:.2f}')
        else:
            reasons.append(f'SuperTrend空头: 收盘{klines[i]["close"]:.2f}跌破支撑线{support[i-1]:.2f}')

        # 辅助reason: MACD交叉
        if dif[i] is not None and dea[i] is not None and dif[i-1] is not None and dea[i-1] is not None:
            if signal_type == 'B' and dif[i-1] <= dea[i-1] and dif[i] > dea[i]:
                reasons.append('MACD金叉: DIF上穿DEA')
            elif signal_type == 'S' and dif[i-1] >= dea[i-1] and dif[i] < dea[i]:
                reasons.append('MACD死叉: DIF下穿DEA')

        # 辅助reason: DIF拐头
        if dif[i] is not None and dif[i-1] is not None and dif[i-2] is not None:
            if signal_type == 'B' and dif[i-2] > dif[i-1] and dif[i] > dif[i-1]:
                reasons.append(f'DIF底拐头: {dif[i-1]:.4f}→{dif[i]:.4f}')
            elif signal_type == 'S' and dif[i-2] < dif[i-1] and dif[i] < dif[i-1]:
                reasons.append(f'DIF顶拐头: {dif[i-1]:.4f}→{dif[i]:.4f}')

        # 辅助reason: KDJ交叉
        if k_vals[i] is not None and d_vals[i] is not None and k_vals[i-1] is not None and d_vals[i-1] is not None:
            if signal_type == 'B' and k_vals[i-1] <= d_vals[i-1] and k_vals[i] > d_vals[i]:
                reasons.append('KDJ金叉: K上穿D')
            elif signal_type == 'S' and k_vals[i-1] >= d_vals[i-1] and k_vals[i] < d_vals[i]:
                reasons.append('KDJ死叉: K下穿D')

        signals.append({
            'date': date,
            'type': signal_type,
            'price': klines[i]['close'],
            'reasons': reasons,
            'macd': round(macd[i], 4) if macd[i] is not None else None,
            'dif': round(dif[i], 4) if dif[i] is not None else None,
            'dea': round(dea[i], 4) if dea[i] is not None else None,
            'kdj_k': round(k_vals[i], 2) if k_vals[i] is not None else None,
            'kdj_d': round(d_vals[i], 2) if d_vals[i] is not None else None,
            'kdj_j': round(j_vals[i], 2) if j_vals[i] is not None else None,
        })

    return signals, dif, dea, macd, ma5, ma20, k_vals, d_vals, j_vals, support, resistance, trend


async def _fetch_trade_records(stock_code: str):
    """从已落库的妙想委托快照读取成交记录。"""
    bare, _ = _candidate_ts_codes(stock_code)
    if not bare:
        return []

    def _read():
        from db.models import SimOrder
        with get_db_session() as db:
            rows = db.query(SimOrder).filter(
                SimOrder.sec_code == bare,
                SimOrder.status.in_((3, 4)),
            ).order_by(SimOrder.time.asc(), SimOrder.id.asc()).all()
            return [{
                "date": row.time.date().isoformat() if row.time else "",
                "type": "B" if int(row.drt or 0) == 1 else "S",
                "price": float(row.trade_price if row.trade_price is not None else row.price or 0),
                "quantity": int(row.trade_count or 0),
                "order_id": row.external_order_id or str(row.id),
            } for row in rows]

    return await asyncio.to_thread(_read)


@router.get("/api/trading/bs-signals")
async def get_bs_signals(
    stockCode: str = Query(..., description="6位股票代码"),
    datalen: int = Query(60, description="返回K线天数，默认60天"),
    as_of: Optional[str] = Query(None, description="日线计算截止日 YYYY-MM-DD"),
):
    """
    获取BS点信号数据
    返回: K线 + 技术指标BS点 + 交易记录BS点 + MACD/MA/KDJ数据
    内部获取150天数据用于EMA收敛，返回最近datalen天
    """
    cutoff = None
    if as_of:
        try:
            cutoff = datetime.strptime(as_of[:10], '%Y-%m-%d').date()
        except ValueError:
            raise HTTPException(status_code=400, detail='as_of 必须为 YYYY-MM-DD')

    try:
        # 1. 获取K线数据（多取用于计算）
        all_klines = await _fetch_kline(stockCode, CALC_DATALEN)
        # 个股分析页的评分、关键位和日K必须来自同一份已完成日度快照。
        # 盘中已写入的当日半成品 K 线不能参与 B/S、MACD、KDJ 的日线计算。
        if cutoff:
            all_klines = [row for row in all_klines if row.get('date') and row['date'] <= cutoff.isoformat()]

        # MACD/SuperTrend 至少需要一段稳定历史。数据不足时保留数据库已有
        # K 线给前端展示，但不把缺失指标伪装成可用结果。
        if len(all_klines) < 60:
            trade_records = await _fetch_trade_records(stockCode)
            return {
                'stockCode': stockCode,
                'klines': all_klines[-datalen:],
                'indicators': {},
                'techSignals': [],
                'tradeRecords': trade_records,
                'source': 'database',
                'dataAsOf': all_klines[-1]['date'] if all_klines else None,
                'status': 'INSUFFICIENT',
                'summary': {
                    'status': 'INSUFFICIENT',
                    'requiredKlineCount': 60,
                    'availableKlineCount': len(all_klines),
                    'klineCount': min(len(all_klines), datalen),
                    'techSignalCount': 0,
                    'latestSignal': None,
                    'tradeRecordCount': len(trade_records),
                    'detail': f'数据库仅有 {len(all_klines)} 根日线，至少需要 60 根计算技术指标',
                },
            }

        # 2. 计算技术指标BS点（在全量数据上计算）
        tech_signals, dif, dea, macd, ma5, ma20, k_vals, d_vals, j_vals, support, resistance, trend = _generate_bs_signals(all_klines)

        # 3. 获取已经落库的交易记录
        try:
            trade_records = await _fetch_trade_records(stockCode)
        except Exception as e:
            logger.warning(f'[bs_signals] 交易记录获取失败 {stockCode}: {e}')
            trade_records = []

        # 4. 截取最近datalen天的数据返回
        total = len(all_klines)
        show_start = max(0, total - datalen)

        klines = all_klines[show_start:]
        dif_show = dif[show_start:]
        dea_show = dea[show_start:]
        macd_show = macd[show_start:]
        ma5_show = ma5[show_start:]
        ma20_show = ma20[show_start:]
        k_show = k_vals[show_start:]
        d_show = d_vals[show_start:]
        j_show = j_vals[show_start:]

        # SuperTrend操盘线：多头时画支撑线，空头时画阻力线
        supertrend_show = []
        for i in range(show_start, total):
            if trend[i] == 1:
                val = support[i]
            else:
                val = resistance[i]
            supertrend_show.append(round(val, 2) if val is not None else None)

        # 只返回显示区间内的信号
        show_dates = {k['date'] for k in klines}
        tech_signals_show = [s for s in tech_signals if s['date'] in show_dates]

        # 5. 组装返回
        return {
            'stockCode': stockCode,
            'klines': klines,
            'source': 'database',
            'dataAsOf': klines[-1]['date'] if klines else None,
            'status': 'READY',
            'indicators': {
                'dif': [round(d, 4) if d is not None else None for d in dif_show],
                'dea': [round(d, 4) if d is not None else None for d in dea_show],
                'macd': [round(d, 4) if d is not None else None for d in macd_show],
                'ma5': [round(m, 2) if m is not None else None for m in ma5_show],
                'ma20': [round(m, 2) if m is not None else None for m in ma20_show],
                'kdj_k': [round(k, 2) if k is not None else None for k in k_show],
                'kdj_d': [round(d, 2) if d is not None else None for d in d_show],
                'kdj_j': [round(j, 2) if j is not None else None for j in j_show],
                'supertrend': supertrend_show,
            },
            'techSignals': tech_signals_show,
            'tradeRecords': trade_records,
            'summary': {
                'status': 'READY',
                'requiredKlineCount': 60,
                'availableKlineCount': len(all_klines),
                'klineCount': len(klines),
                'techSignalCount': len(tech_signals_show),
                'latestSignal': tech_signals_show[-1] if tech_signals_show else None,
                'tradeRecordCount': len(trade_records),
            },
        }
    except Exception as e:
        logger.error(f'[bs_signals] 计算失败 {stockCode}: {e}', exc_info=True)
        return {
            'stockCode': stockCode,
            'klines': [],
            'indicators': {},
            'techSignals': [],
            'tradeRecords': [],
            'summary': {'klineCount': 0, 'techSignalCount': 0, 'latestSignal': None, 'tradeRecordCount': 0, 'detail': f'计算异常已降级: {str(e)[:200]}'},
        }


# ==================== 分时数据（K线弹窗右侧用）====================

_sector_today_cache = {}  # sector -> [(timestamp_seconds, avg_chg_pct), ...]


def _ts_code_to_6digit(ts_code: str) -> str:
    """600519.SH / 000001.SZ -> 600519 / 000001"""
    if not ts_code:
        return ''
    return ts_code.split('.')[0]


async def _fetch_sector_today_intraday(sector: str):
    """
    合成板块当天实时热度折线：
    1. 从 stock_flow 取该板块最近交易日的成分股
    2. 用 hq.sinajs.cn 批量拉取实时行情
    3. 计算成分股相对昨日收盘的平均涨跌幅
    4. 每30秒采样一个点，保留当天数据形成折线
    """
    if not sector:
        return []

    # 查找板块成分股（最近交易日）
    try:
        with get_db_session() as db:
            latest_date = db.query(StockFlow.trade_date).filter(
                StockFlow.sector == sector
            ).order_by(StockFlow.trade_date.desc()).first()
            if not latest_date:
                return []
            rows = db.query(StockFlow.ts_code).filter(
                StockFlow.sector == sector,
                StockFlow.trade_date == latest_date[0]
            ).distinct().limit(50).all()
            codes = [_ts_code_to_6digit(r[0]) for r in rows if r[0]]
    except Exception as e:
        logger.debug(f'[bs_signals] 板块成分股查询失败 {sector}: {e}')
        return []

    if not codes:
        return []

    # 行情来自同一批数据库快照，避免板块折线与个股价格使用不同截止时间。
    avg_chg = None
    try:
        quotes = await batch_get_quotes(codes)
        chgs = [
            float(quote['changePct'])
            for quote in quotes.values()
            if quote is not None and quote.get('changePct') is not None
        ]
        if chgs:
            avg_chg = round(sum(chgs) / len(chgs), 3)
    except Exception as exc:
        logger.warning('[bs_signals] 板块数据库行情读取失败 %s: %s', sector, exc)

    if avg_chg is None:
        return []

    now_ts = int(datetime.now().timestamp())
    # 初始化或清理跨天数据
    cache = _sector_today_cache.get(sector, [])
    today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    cache = [(t, v) for t, v in cache if t >= today_start]
    # 去重：同一分钟内只保留最新
    last_min = cache[-1][0] // 60 if cache else None
    if last_min != now_ts // 60:
        cache.append((now_ts, avg_chg))
    else:
        cache[-1] = (now_ts, avg_chg)
    _sector_today_cache[sector] = cache
    return [{"time": datetime.fromtimestamp(t).strftime('%H:%M'), "value": v, "ts": t} for t, v in cache]


_intraday_cache = BoundedDict(maxsize=200)  # code -> (data, ts)


def _read_intraday_from_db(code: str) -> tuple[list[dict], str | None]:
    """从分钟资金流快照聚合最近两个交易日的 5 分钟 OHLC。"""
    from db.models import RealtimeStockFlow

    bare, candidates = _candidate_ts_codes(code)
    if not bare:
        return [], None
    rows = []
    with get_db_session() as db:
        for ts_code in candidates:
            dates = db.query(RealtimeStockFlow.trade_date).filter(
                RealtimeStockFlow.ts_code == ts_code,
                RealtimeStockFlow.price.isnot(None),
            ).distinct().order_by(RealtimeStockFlow.trade_date.desc()).limit(2).all()
            if not dates:
                continue
            rows = db.query(
                RealtimeStockFlow.snapshot_time,
                RealtimeStockFlow.price,
            ).filter(
                RealtimeStockFlow.ts_code == ts_code,
                RealtimeStockFlow.trade_date.in_([item[0] for item in dates]),
                RealtimeStockFlow.price.isnot(None),
            ).order_by(RealtimeStockFlow.snapshot_time.asc()).all()
            if rows:
                break

    buckets = {}
    for row in rows:
        timestamp = row.snapshot_time
        if timestamp is None:
            continue
        bucket_time = timestamp.replace(
            minute=(timestamp.minute // 5) * 5,
            second=0,
            microsecond=0,
        )
        price = float(row.price)
        item = buckets.get(bucket_time)
        if item is None:
            buckets[bucket_time] = {
                "time": bucket_time.strftime("%Y-%m-%d %H:%M:%S"),
                "open": price,
                "close": price,
                "high": price,
                "low": price,
            }
        else:
            item["close"] = price
            item["high"] = max(item["high"], price)
            item["low"] = min(item["low"], price)
    bars = [buckets[key] for key in sorted(buckets)][-48:]
    data_as_of = rows[-1].snapshot_time.isoformat() if rows else None
    return bars, data_as_of


@router.get("/api/trading/intraday/{code}")
async def get_intraday(code: str):
    """获取当天分时K线（5分钟线）+ 大盘指数实时数据
    用于K线BS点弹窗右侧：当日分时走势 + 指数参数
    """
    # 30秒缓存（分时数据秒级变化，30秒足够）
    bare, _ = _candidate_ts_codes(code)
    if not bare:
        raise HTTPException(status_code=400, detail="无效的股票代码")
    cached = _intraday_cache.get(bare)
    if cached and time.time() - cached[1] < 30:
        return cached[0]

    # 1. 从已落库的分钟快照聚合 5 分钟 K 线（48 根 = 2 个交易日）
    try:
        intraday, data_as_of = await asyncio.to_thread(_read_intraday_from_db, bare)
    except Exception as e:
        logger.warning('[bs_signals] 分时数据库读取失败 %s: %s', bare, e)
        intraday, data_as_of = [], None

    # 2. 个股行情与列表页使用同一个数据库批次。
    stock_quote = await get_quote(bare)

    # 3. 查询该股所属板块的近期热度趋势（7天折线图数据）
    sector_info = {"name": "", "heat_series": [], "latest_heat": 0, "heat_trend": ""}
    sector_today_series = []
    try:
        with get_db_session() as db:
            ts_code = f"{bare}.SH" if bare[0] in ('5', '6', '9') else (
                f"{bare}.BJ" if bare[0] in ('4', '8') else f"{bare}.SZ"
            )
            sector = _find_sector_for_stock(db, ts_code)
            if sector:
                trend = _get_sector_trend(db, sector, 7)
                if trend.get('available'):
                    sector_info = {
                        'name': sector,
                        'heat_series': trend.get('heat_series', []),
                        'latest_heat': trend.get('latest_heat', 0),
                        'heat_trend': trend.get('heat_trend', ''),
                    }
        if sector:
            sector_today_series = await _fetch_sector_today_intraday(sector)
    except Exception as e:
        logger.debug(f'[bs_signals] 板块热度查询失败 {code}: {e}')

    result = {
        'stockCode': bare,
        'intraday': intraday,
        'stockQuote': stock_quote,
        'sector': sector_info,
        'sector_today_series': sector_today_series,
        'source': 'database',
        'status': 'READY' if intraday or stock_quote else 'MISSING',
        'dataAsOf': data_as_of or (stock_quote or {}).get('dataAsOf'),
        'fetchedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    _intraday_cache[bare] = (result, time.time())
    return result
