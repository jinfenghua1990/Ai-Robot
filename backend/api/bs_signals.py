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
import httpx
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Request
from config import MX_APIKEY, MX_API_URL
from db.connection import get_db
from db.session import get_db_session
from db.models import StockFlow
from analyzers.strategy_engine import _find_sector_for_stock, _get_sector_trend
from utils import stock_code_to_sina
from services.indicators import (
    calc_ma as _calc_ma_impl,
    calc_ema as _calc_ema_impl,
    calc_macd as _calc_macd_impl,
    calc_rsi as _calc_rsi_impl,
    calc_kdj as _calc_kdj_impl,
    calc_atr as _calc_atr_impl,
    calc_supertrend as _calc_supertrend_impl,
)

import logging
from utils.http_constants import SINA_HEADERS_SHORT
from api.watchlist._shared import _get_http_client
logger = logging.getLogger(__name__)

router = APIRouter()

# 计算用历史数据天数（需远大于EMA26周期，确保EMA收敛）
CALC_DATALEN = 150


def _stock_code_to_sina(stock_code: str) -> str:
    """DEPRECATED: use utils.stock_code_to_sina"""
    return stock_code_to_sina(stock_code)


async def _fetch_kline(stock_code: str, datalen: int = CALC_DATALEN):
    """从新浪财经获取日K线数据，带文件缓存"""
    import os, json as _json
    cache_dir = '/tmp/kline_cache'
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = f"{cache_dir}/{stock_code}.json"
    # 命中缓存
    if os.path.exists(cache_file):
        mtime = os.path.getmtime(cache_file)
        # 缓存有效期：7 天
        if time.time() - mtime < 7 * 86400:
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    klines = _json.load(f)
                if klines and len(klines) >= 100:
                    return klines[:datalen] if datalen < len(klines) else klines
            except Exception as e:
                logger.debug(f'[bs_signals] 读取本地 K线缓存失败 {stock_code}: {e}')

    sina_code = _stock_code_to_sina(stock_code)
    if not sina_code:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen={datalen}"
    try:
        client = _get_http_client()
        resp = await client.get(url)
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取K线数据失败: {str(e)}")

    if not data:
        raise HTTPException(status_code=404, detail="未找到K线数据")

    # 转换格式
    klines = []
    for k in data:
        klines.append({
            'date': k['day'][:10],
            'open': float(k['open']),
            'close': float(k['close']),
            'high': float(k['high']),
            'low': float(k['low']),
            'volume': int(float(k['volume'])),
        })

    # 写缓存（仅当日线数 >= 100 时）
    if klines and len(klines) >= 100:
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                _json.dump(klines, f, ensure_ascii=False)
        except Exception as e:
            logger.debug(f'[bs_signals] 写入本地 K线缓存失败 {stock_code}: {e}')

    return klines


def _calc_ema(values, period):
    """DEPRECATED: use services.indicators.calc_ema directly"""
    return _calc_ema_impl(values, period)


def _calc_macd(klines):
    """DEPRECATED: use services.indicators.calc_macd directly"""
    closes = [k['close'] for k in klines]
    return _calc_macd_impl(closes)


def _calc_ma(klines, period):
    """DEPRECATED: use services.indicators.calc_ma directly"""
    closes = [k['close'] for k in klines]
    return _calc_ma_impl(closes, period)


def _calc_rsi(klines, period=14):
    """DEPRECATED: use services.indicators.calc_rsi directly"""
    closes = [k['close'] for k in klines]
    return _calc_rsi_impl(closes, period)


def _calc_kdj(klines, n=9, m1=3, m2=3):
    """DEPRECATED: use services.indicators.calc_kdj directly"""
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    closes = [k['close'] for k in klines]
    return _calc_kdj_impl(highs, lows, closes, n, m1, m2)


def _calc_atr(klines, period=10):
    """DEPRECATED: use services.indicators.calc_atr directly"""
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    closes = [k['close'] for k in klines]
    return _calc_atr_impl(highs, lows, closes, period)


def _calc_supertrend(klines, period=10, multiplier=3):
    """DEPRECATED: use services.indicators.calc_supertrend directly"""
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]
    closes = [k['close'] for k in klines]
    return _calc_supertrend_impl(highs, lows, closes, period, multiplier)


def _generate_bs_signals(klines, period=10, multiplier=1.0):
    """
    基于SuperTrend(超级趋势指标)生成BS点
    - B点: SuperTrend从空头转多头(收盘突破上轨)
    - S点: SuperTrend从多头转空头(收盘跌破下轨)
    辅助reason: MACD金叉/死叉、DIF拐头、KDJ金叉/死叉
    单信号源，天然交替(B→S→B→S)，无需去噪
    可配置参数: period(ATR周期), multiplier(乘数)
    """
    # 主信号源: SuperTrend
    support, resistance, trend, atr = _calc_supertrend(klines, period, multiplier)

    # 辅助指标(用于reason和indicators返回)
    dif, dea, macd = _calc_macd(klines)
    ma5 = _calc_ma(klines, 5)
    ma20 = _calc_ma(klines, 20)
    k_vals, d_vals, j_vals = _calc_kdj(klines, 9, 3, 3)

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
    """从东方财富获取该股票的交易记录"""
    if not MX_APIKEY:
        return []

    try:
        client = _get_http_client()
        resp = await client.post(
            f"{MX_API_URL}/api/claw/mockTrading/orders",
            json={'fltOrderDrt': 0, 'fltOrderStatus': 0},
            headers={"apikey": MX_APIKEY, "Content-Type": "application/json; charset=UTF-8"},
        )
        data = resp.json()
    except Exception:
        logger.debug(f"_fetch_trade_records failed", exc_info=True)
        return []

    if str(data.get('code', '')) not in ('0', '200'):
        return []

    orders = data.get('data', {}).get('orders') or []
    records = []
    for o in orders:
        if o.get('secCode') != stock_code:
            continue
        price_dec = o.get('priceDec', 2)
        trade_price = o.get('tradePrice')
        if trade_price:
            trade_price = trade_price / (10 ** price_dec)
        order_price = o.get('price', 0) / (10 ** price_dec)
        # 只记录已成交的
        if o.get('status') in (4, 3):  # 已成、部成
            records.append({
                'date': '',  # 需要从时间戳转换
                'type': 'B' if o.get('drt') == 1 else 'S',
                'price': trade_price or order_price,
                'quantity': o.get('tradeCount', 0),
                'order_id': o.get('id', ''),
            })
    return records


@router.get("/api/trading/bs-signals")
async def get_bs_signals(
    stockCode: str = Query(..., description="6位股票代码"),
    datalen: int = Query(60, description="返回K线天数，默认60天"),
):
    """
    获取BS点信号数据
    返回: K线 + 技术指标BS点 + 交易记录BS点 + MACD/MA/KDJ数据
    内部获取150天数据用于EMA收敛，返回最近datalen天
    """
    # 1. 获取K线数据（多取用于计算）
    all_klines = await _fetch_kline(stockCode, CALC_DATALEN)

    # 2. 计算技术指标BS点（在全量数据上计算）
    tech_signals, dif, dea, macd, ma5, ma20, k_vals, d_vals, j_vals, support, resistance, trend = _generate_bs_signals(all_klines)

    # 3. 获取交易记录
    trade_records = await _fetch_trade_records(stockCode)

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
            'klineCount': len(klines),
            'techSignalCount': len(tech_signals_show),
            'latestSignal': tech_signals_show[-1] if tech_signals_show else None,
            'tradeRecordCount': len(trade_records),
        },
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

    sina_codes = [c for c in (_stock_code_to_sina(c) for c in codes) if c]
    if not sina_codes:
        return []

    # 批量拉取行情（hq.sinajs.cn 支持多个 code，用逗号分隔）
    avg_chg = None
    try:
        quotes_url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
        client = _get_http_client()
        resp = await client.get(quotes_url, headers=SINA_HEADERS_SHORT)
        resp.encoding = 'gbk'
        text = resp.text
        chgs = []
        for line in text.split(';'):
            if '"' not in line:
                continue
            parts = line.split('"')
            if len(parts) < 2:
                continue
            vals = parts[1].split(',')
            if len(vals) < 5:
                continue
            try:
                price = float(vals[3])
                yclose = float(vals[2])
                if yclose:
                    chgs.append((price - yclose) / yclose * 100)
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
            avg_chg = round(sum(chgs) / len(chgs), 3)
    except Exception:
        logger.warning(f"function failed", exc_info=True)

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


_intraday_cache = {}  # code -> (data, ts)


@router.get("/api/trading/intraday/{code}")
async def get_intraday(code: str):
    """获取当天分时K线（5分钟线）+ 大盘指数实时数据
    用于K线BS点弹窗右侧：当日分时走势 + 指数参数
    """
    # 30秒缓存（分时数据秒级变化，30秒足够）
    cached = _intraday_cache.get(code)
    if cached and time.time() - cached[1] < 30:
        return cached[0]

    sina_code = _stock_code_to_sina(code)
    if not sina_code:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    # 1. 拉取5分钟K线（48根 = 2个交易日）
    intraday_url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale=5&ma=no&datalen=48"
    intraday = []
    try:
        client = _get_http_client()
        resp = await client.get(intraday_url)
        raw = resp.json()
        for k in raw:
            intraday.append({
                'time': k['day'],
                'open': float(k['open']),
                'close': float(k['close']),
                'high': float(k['high']),
                'low': float(k['low']),
            })
    except Exception as e:
        logger.debug(f'[bs_signals] 分时K线解析失败 {code}: {e}')

    # 2. 拉取个股实时行情（新浪 hq.sinajs.cn）
    quotes_url = f"https://hq.sinajs.cn/list={sina_code}"
    stock_quote = None
    try:
        client = _get_http_client()
        resp = await client.get(quotes_url, headers=SINA_HEADERS_SHORT)
        resp.encoding = 'gbk'
        text = resp.text
        if '"' in text:
            parts = text.split('"')[1].split(',')
            if len(parts) >= 10:
                price = float(parts[3])
                yclose = float(parts[2])
                chg_pct = (price - yclose) / yclose * 100 if yclose else 0
                stock_quote = {
                    'name': parts[0], 'price': price, 'changePct': round(chg_pct, 2),
                }
    except Exception as e:
        logger.debug(f'[bs_signals] 个股实时行情拉取失败 {code}: {e}')

    # 3. 查询该股所属板块的近期热度趋势（7天折线图数据）
    sector_info = {"name": "", "heat_series": [], "latest_heat": 0, "heat_trend": ""}
    sector_today_series = []
    try:
        with get_db_session() as db:
            ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
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
                # 板块当天实时热度（成分股实时行情合成）
    except Exception as e:
        logger.debug(f'[bs_signals] 板块热度查询失败 {code}: {e}')

    result = {
        'stockCode': code,
        'intraday': intraday,
        'stockQuote': stock_quote,
        'sector': sector_info,
        'sector_today_series': sector_today_series,
        'fetchedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    _intraday_cache[code] = (result, time.time())
    return result