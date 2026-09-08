"""
个股市场状态判定引擎（CHOPPY / TREND / IMPULSE）
从本地 stock_daily_kline 表读取日K线，计算6类特征数据，输出3态判定。

数据来源：stock_daily_kline 表（由 tdx_collector 每日采集）
资金流来源：stock_money_flow_detail 表；缺失时保持空值，不用 0 代替
"""
import json
from datetime import datetime
from db.session import get_db_session
from db.models import StockFeaturesDaily, StockDailyKline, StockMoneyFlowDetail
from services.indicators import calc_rsi
import logging
logger = logging.getLogger(__name__)


async def _fetch_kline(stock_code: str, datalen: int = 120):
    """只从 stock_daily_kline 表读取日K线。
    返回 [{day, open, close, high, low, volume}, ...]（按日期升序）
    """
    ts_code = _stock_code_to_tushare(stock_code)
    try:
        with get_db_session() as db:
            rows = db.query(StockDailyKline).filter(
                StockDailyKline.ts_code == ts_code,
                StockDailyKline.open.isnot(None),
                StockDailyKline.close.isnot(None),
                StockDailyKline.high.isnot(None),
                StockDailyKline.low.isnot(None),
                StockDailyKline.volume.isnot(None),
            ).order_by(StockDailyKline.trade_date.desc()).limit(datalen).all()
            rows = rows[::-1]  # 升序
    except Exception:
        logger.debug(f"_fetch_kline DB failed for {stock_code}", exc_info=True)
        rows = []
    return [{
        'day': str(row.trade_date),
        'open': float(row.open),
        'close': float(row.close),
        'high': float(row.high),
        'low': float(row.low),
        'volume': int(row.volume),
    } for row in rows]


def _stock_code_to_tushare(stock_code: str) -> str:
    """A股代码转 Tushare 格式：6/9 开头→.SH，0/3 开头→.SZ，4/8 开头→.BJ。"""
    code = (stock_code or '').strip().split('.')[0]
    if code.startswith('92'):
        return f'{code}.BJ'
    if code.startswith(('5', '6', '9')):
        return f'{code}.SH'
    if code.startswith(('4', '8')):
        return f'{code}.BJ'
    return f'{code}.SZ'


def _fetch_money_flow(stock_code: str, days: int = 5) -> dict:
    """从日频分单资金表读取主力资金流数据（单位：元）。

    资金日期以该股票的日 K 交易日序列为准，不能把缺失交易日静默压缩成“近 N 日”。
    页面资金明细、市场状态和评分共用 ``StockMoneyFlowDetail.main_net``，避免同页出现
    两种定义或不同单位的主力资金。

    返回 {main_net_inflow_1d, main_net_inflow_3d, main_net_inflow_5d, flow_continuity, flow_strength}
    """
    ts_code = _stock_code_to_tushare(stock_code)
    with get_db_session() as db:
        kline_dates = [row[0] for row in db.query(StockDailyKline.trade_date).filter(
            StockDailyKline.ts_code == ts_code,
            StockDailyKline.close.isnot(None),
        ).order_by(StockDailyKline.trade_date.desc()).limit(days).all()]

        if not kline_dates:
            return {
                'main_net_inflow_1d': None,
                'main_net_inflow_3d': None,
                'main_net_inflow_5d': None,
                'flow_continuity': None,
                'flow_strength': None,
                'status': 'MISSING',
                'source': 'database',
                'data_as_of': None,
                'table': 'stock_money_flow_detail',
                'coverage': {'requested_days': days, 'rows': 0, 'valid_rows': 0},
            }

        detail_rows = db.query(StockMoneyFlowDetail).filter(
            StockMoneyFlowDetail.ts_code == ts_code,
            StockMoneyFlowDetail.trade_date.in_(kline_dates),
        ).all()
        detail_by_date = {row.trade_date: row for row in detail_rows}
        inflows = []
        for trade_date in kline_dates:
            row = detail_by_date.get(trade_date)
            inflows.append(float(row.main_net) if row and row.main_net is not None else None)

        def exact_sum(period: int):
            values = inflows[:period]
            if len(values) < period or any(value is None for value in values):
                return None
            return round(sum(values), 0)

        inflow_1d = round(inflows[0], 0) if inflows[0] is not None else None
        inflow_3d = exact_sum(3)
        inflow_5d = exact_sum(5)

        # 连续为正天数
        continuity = 0
        for v in inflows:
            if v is None:
                continuity = None
                break
            if v > 0:
                continuity += 1
            else:
                break

        valid_rows = sum(value is not None for value in inflows)
        status = (
            'READY' if len(kline_dates) >= days and valid_rows >= days else
            'PARTIAL' if valid_rows else 'MISSING'
        )

        return {
            'main_net_inflow_1d': inflow_1d,
            'main_net_inflow_3d': inflow_3d,
            'main_net_inflow_5d': inflow_5d,
            'flow_continuity': continuity,
            'flow_strength': inflow_5d,
            'status': status,
            'source': 'database',
            'data_as_of': str(kline_dates[0]),
            'table': 'stock_money_flow_detail',
            'coverage': {
                'requested_days': days,
                'rows': len(detail_rows),
                'valid_rows': valid_rows,
                'available_kline_days': len(kline_dates),
            },
        }


# ===================== 指标计算 =====================

def _calc_ma(values: list, period: int) -> list:
    """简单移动平均"""
    ma = []
    for i in range(len(values)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(values[i - period + 1: i + 1]) / period)
    return ma


def _calc_atr(klines: list, period: int = 14) -> float:
    """ATR(14) - 平均真实波幅"""
    if len(klines) < period + 1:
        return 0
    trs = []
    for i in range(1, len(klines)):
        high = klines[i]['high']
        low = klines[i]['low']
        prev_close = klines[i - 1]['close']
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period if len(trs) >= period else 0


def _calc_noise_ratio(klines: list, period: int = 5) -> float:
    """噪音比 = (上影线 + 下影线) / 实体，取近5日均值"""
    recent = klines[-period:] if len(klines) >= period else klines
    ratios = []
    for k in recent:
        body = abs(k['close'] - k['open'])
        if body < 0.001:
            ratios.append(2.0)  # 十字星，噪音极高
            continue
        upper_shadow = k['high'] - max(k['close'], k['open'])
        lower_shadow = min(k['close'], k['open']) - k['low']
        ratios.append((upper_shadow + lower_shadow) / body)
    return sum(ratios) / len(ratios) if ratios else 0


def compute_features(klines: list, sector_strength: float = None, money_flow: dict = None) -> dict:
    """从K线列表计算6类特征数据，返回字典"""
    if len(klines) < 60:
        return None

    closes = [k['close'] for k in klines]
    volumes = [k['volume'] for k in klines]
    highs = [k['high'] for k in klines]
    lows = [k['low'] for k in klines]

    # ① 价格结构
    ma5_list = _calc_ma(closes, 5)
    ma20_list = _calc_ma(closes, 20)
    ma60_list = _calc_ma(closes, 60)

    close = closes[-1]
    ma5 = ma5_list[-1]
    ma20 = ma20_list[-1]
    ma60 = ma60_list[-1]

    # MA20斜率（5日前vs现在，归一化）
    ma20_5d_ago = ma20_list[-6] if len(ma20_list) >= 6 and ma20_list[-6] else ma20
    ma20_slope = (ma20 - ma20_5d_ago) / ma20_5d_ago if ma20_5d_ago > 0 else 0

    close_vs_ma20 = (close - ma20) / ma20 if ma20 > 0 else 0

    # 近20日新高突破次数（当日high突破前20日最高价）
    high_break_20d = 0
    if len(highs) >= 25:
        for i in range(20, len(highs)):
            prev_20d_high = max(highs[i - 20: i])
            if highs[i] > prev_20d_high:
                high_break_20d += 1

    # ② 成交量
    volume = volumes[-1]
    volume_ma20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else (sum(volumes) / len(volumes) if volumes else 1)
    volume_ratio = volume / volume_ma20 if volume_ma20 > 0 else 1.0

    # ③ 资金流（从 StockFlow 表读取主力净流入）
    mf = money_flow or {}
    main_net_inflow_1d = mf.get('main_net_inflow_1d')
    main_net_inflow_3d = mf.get('main_net_inflow_3d')
    main_net_inflow_5d = mf.get('main_net_inflow_5d')
    flow_continuity = mf.get('flow_continuity')  # 连续净流入天数

    # ④ 波动结构
    atr_14 = _calc_atr(klines, 14)
    noise_ratio = _calc_noise_ratio(klines, 5)

    # RSI(14) - 用于技术形态 7 段判定（顶部判断）
    rsi_list = calc_rsi(closes, 14)
    rsi_14 = rsi_list[-1] if rsi_list and rsi_list[-1] is not None else None

    # ⑤ 趋势一致性
    if len(highs) >= 10:
        recent_5_high = max(highs[-5:])
        prev_5_high = max(highs[-10:-5])
        higher_high_flag = 1 if recent_5_high > prev_5_high else 0

        recent_5_low = min(lows[-5:])
        prev_5_low = min(lows[-10:-5])
        higher_low_flag = 1 if recent_5_low > prev_5_low else 0
    else:
        higher_high_flag = 0
        higher_low_flag = 0

    # 趋势一致性评分：近10日上涨日占比
    up_count = sum(1 for i in range(-10, 0) if closes[i] > closes[i - 1]) if len(closes) >= 11 else 0
    trend_consistency_score = up_count / 10

    return {
        'close': round(close, 3),
        'ma5': round(ma5, 3) if ma5 else None,
        'ma20': round(ma20, 3) if ma20 else None,
        'ma60': round(ma60, 3) if ma60 else None,
        'ma20_slope': round(ma20_slope, 4),
        'close_vs_ma20': round(close_vs_ma20, 4),
        'high_break_20d': high_break_20d,
        'volume': volume,
        'volume_ma20': int(volume_ma20),
        'volume_ratio': round(volume_ratio, 2),
        'main_net_inflow_1d': main_net_inflow_1d,
        'main_net_inflow_3d': main_net_inflow_3d,
        'main_net_inflow_5d': main_net_inflow_5d,
        'flow_continuity': flow_continuity,
        'atr_14': round(atr_14, 3),
        'noise_ratio': round(noise_ratio, 2),
        'higher_high_flag': higher_high_flag,
        'higher_low_flag': higher_low_flag,
        'trend_consistency_score': round(trend_consistency_score, 2),
        'sector_strength': round(sector_strength, 2) if sector_strength is not None else None,
        'rsi_14': round(rsi_14, 2) if rsi_14 else None,
    }


# ===================== 3态判定 =====================

def classify_market_state(f: dict) -> tuple:
    """
    判定市场状态：CHOPPY / TREND / IMPULSE
    返回 (state, reasons_list)
    """
    if not f:
        return ('UNKNOWN', ['数据不足'])

    reasons = []

    # ---- IMPULSE（主升）：趋势 + 加速 + 资金连续 + 板块共振 ----
    impulse_score = 0
    if f['close_vs_ma20'] > 0.03:
        impulse_score += 1; reasons.append('close高于MA20 3%+')
    if f['ma20_slope'] > 0.01:
        impulse_score += 1; reasons.append('MA20快速上行')
    if f['volume_ratio'] > 1.5:
        impulse_score += 1; reasons.append(f"放量({f['volume_ratio']}倍)")
    if f.get('flow_continuity') is not None and f['flow_continuity'] >= 3:
        impulse_score += 1; reasons.append(f"连续{f['flow_continuity']}日主力净流入")
    if f['higher_high_flag'] and f['higher_low_flag']:
        impulse_score += 1; reasons.append('高低点同步抬高')
    if f['noise_ratio'] < 1.0:
        impulse_score += 1; reasons.append(f"走势干净(noise={f['noise_ratio']})")
    if f.get('sector_strength') is not None and f['sector_strength'] > 2:
        impulse_score += 1; reasons.append(f"板块强势({f['sector_strength']}%)")

    if impulse_score >= 5:
        return ('IMPULSE', reasons[:4])

    # ---- TREND（趋势）：有方向 + 有延续资金 ----
    trend_score = 0
    trend_reasons = []
    if f['close_vs_ma20'] > 0:
        trend_score += 1; trend_reasons.append('close>MA20')
    if f['ma20'] and f['ma60'] and f['ma20'] > f['ma60']:
        trend_score += 1; trend_reasons.append('MA20>MA60')
    if f['ma20_slope'] > 0:
        trend_score += 1; trend_reasons.append('MA20正斜率')
    if f['volume_ratio'] > 1.2:
        trend_score += 1; trend_reasons.append(f"温和放量({f['volume_ratio']}倍)")
    if f.get('main_net_inflow_3d') is not None and f['main_net_inflow_3d'] > 0:
        trend_score += 1; trend_reasons.append('3日主力净流入为正')
    if f['higher_high_flag']:
        trend_score += 1; trend_reasons.append('创新高')

    if trend_score >= 4:
        return ('TREND', trend_reasons[:4])

    # ---- CHOPPY（杂毛）：没方向 + 资金断 + 走势乱 ----
    choppy_reasons = []
    if abs(f['close_vs_ma20']) < 0.02:
        choppy_reasons.append('close在MA20附近横盘')
    if abs(f['ma20_slope']) < 0.005:
        choppy_reasons.append('MA20斜率≈0')
    if not f['higher_high_flag']:
        choppy_reasons.append('无higher high')
    if f['noise_ratio'] > 1.5:
        choppy_reasons.append(f"噪音高(noise={f['noise_ratio']})")
    if f.get('main_net_inflow_3d') is not None and f['main_net_inflow_3d'] <= 0:
        choppy_reasons.append('3日主力资金不连续')
    if f['volume_ratio'] < 0.8:
        choppy_reasons.append(f"缩量({f['volume_ratio']}倍)")

    # 默认就是 CHOPPY（不满足 TREND/IMPULSE 的都是杂毛）
    if not choppy_reasons:
        choppy_reasons.append('未达趋势标准')
    return ('CHOPPY', choppy_reasons[:4])


# ===================== 数据库读写 =====================

def save_features(stock_code: str, trade_date: str, features: dict, state: str, reasons: list):
    """保存特征数据到数据库（upsert）"""
    stock_code = (stock_code or '').strip().split('.')[0]
    try:
        with get_db_session() as db:
            existing = db.query(StockFeaturesDaily).filter_by(
                stock_code=stock_code, trade_date=trade_date
            ).first()
            if existing:
                for k, v in features.items():
                    setattr(existing, k, v)
                existing.market_state = state
                existing.state_reasons = json.dumps(reasons, ensure_ascii=False)
            else:
                row = StockFeaturesDaily(
                    stock_code=stock_code,
                    trade_date=trade_date,
                    market_state=state,
                    state_reasons=json.dumps(reasons, ensure_ascii=False),
                    **features,
                )
                db.add(row)
            db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f'[market_state] save error for {stock_code}: {e}', exc_info=True)


def get_latest_state(stock_code: str) -> dict:
    """读取个股最新市场状态"""
    stock_code = (stock_code or '').strip().split('.')[0]
    with get_db_session() as db:
        row = db.query(StockFeaturesDaily).filter_by(
            stock_code=stock_code
        ).order_by(StockFeaturesDaily.trade_date.desc()).first()
        if not row:
            return None
        flow_values = (
            row.main_net_inflow_1d,
            row.main_net_inflow_3d,
            row.main_net_inflow_5d,
            row.flow_continuity,
        )
        flow_status = (
            'READY' if all(value is not None for value in flow_values)
            else 'PARTIAL' if any(value is not None for value in flow_values)
            else 'MISSING'
        )
        try:
            from market_quant.calendar import latest_completed_session
            expected_date = latest_completed_session('A').strftime('%Y%m%d')
        except Exception:
            expected_date = None
        freshness_status = (
            'STALE' if expected_date and row.trade_date < expected_date else 'READY'
        )
        status = freshness_status if freshness_status == 'STALE' else (
            'READY' if flow_status == 'READY' else 'PARTIAL'
        )
        detail = None
        if freshness_status == 'STALE':
            detail = f'数据库最新 {row.trade_date}，应到 {expected_date}'
        elif flow_status != 'READY':
            detail = f'资金流特征状态为 {flow_status}'
        return {
            'market_state': row.market_state,
            'reasons': json.loads(row.state_reasons) if row.state_reasons else [],
            'features': {
                'close': row.close,
                'ma20': row.ma20,
                'ma60': row.ma60,
                'ma20_slope': row.ma20_slope,
                'close_vs_ma20': row.close_vs_ma20,
                'volume_ratio': row.volume_ratio,
                'main_net_inflow_3d': row.main_net_inflow_3d,
                'flow_continuity': row.flow_continuity,
                'atr_14': row.atr_14,
                'noise_ratio': row.noise_ratio,
                'higher_high_flag': row.higher_high_flag,
                'higher_low_flag': row.higher_low_flag,
                'trend_consistency_score': row.trend_consistency_score,
                'sector_strength': row.sector_strength,
                'flow_data_status': flow_status,
            },
            'trade_date': row.trade_date,
            'data_as_of': row.trade_date,
            'source': 'database',
            'status': status,
            'detail': detail,
        }


async def update_stock_state(stock_code: str, sector_strength: float = None) -> dict:
    """完整流程：拉K线 → 读取资金流 → 计算 → 判定 → 存库。返回判定结果"""
    stock_code = (stock_code or '').strip().split('.')[0]
    klines = await _fetch_kline(stock_code, 120)
    if len(klines) < 60:
        return {
            'market_state': 'UNKNOWN',
            'reasons': ['K线数据不足'],
            'source': 'database',
            'status': 'INSUFFICIENT',
            'data_as_of': klines[-1]['day'] if klines else None,
            'coverage': {'required_bars': 60, 'available_bars': len(klines)},
        }

    # 从日频分单资金表读取主力资金流（与页面资金明细同一数据库口径）
    money_flow = _fetch_money_flow(stock_code, days=5)

    features = compute_features(klines, sector_strength, money_flow)
    if not features:
        return {'market_state': 'UNKNOWN', 'reasons': ['特征计算失败']}

    state, reasons = classify_market_state(features)
    trade_date = klines[-1]['day'].replace('-', '') if klines[-1].get('day') else datetime.now().strftime('%Y%m%d')
    save_features(stock_code, trade_date, features, state, reasons)

    return {
        'market_state': state,
        'reasons': reasons,
        'trade_date': trade_date,
        'data_as_of': trade_date,
        'source': 'database',
        'status': 'READY' if money_flow.get('status') == 'READY' else 'PARTIAL',
        'flow_status': money_flow.get('status'),
        'flow_coverage': money_flow.get('coverage'),
    }


def compute_quality_from_features(market_state: str, features: dict, is_junk: bool = False) -> str:
    """根据 market_state + 特征数据细化映射到 quality_status（7段，新命名）
    - CHOPPY: noise_ratio>1.5 → 劣质，否则 中性
    - TREND:  弱趋势→偏强，中趋势→强势，强趋势+放量→极强
    - IMPULSE: 弱主升→强势，强主升+资金连续→核心
    - PENDING/无数据: 中性
    手动标记"淘汰"由调用方在外部保留（不进入本函数）。
    """
    if market_state == 'CHOPPY':
        if is_junk or (features.get('noise_ratio') or 0) > 1.5:
            return '劣质'
        return '中性'
    if market_state == 'TREND':
        close_vs_ma20 = features.get('close_vs_ma20') or 0
        volume_ratio = features.get('volume_ratio') or 0
        if close_vs_ma20 >= 0.05 and volume_ratio >= 1.5:
            return '极强'
        if close_vs_ma20 >= 0.03:
            return '强势'
        return '偏强'
    if market_state == 'IMPULSE':
        volume_ratio = features.get('volume_ratio') or 0
        flow_continuity = features.get('flow_continuity') or 0
        if volume_ratio >= 2.0 and flow_continuity >= 3:
            return '核心'
        return '极强'
    # PENDING / UNKNOWN / None
    return '中性'
