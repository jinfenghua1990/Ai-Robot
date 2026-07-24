"""
个股决策仪表盘 API
GET /api/stock-dashboard/{code}
GET /api/stock-dashboard/batch?codes=000001.SZ,600536.SH

基于真实数据计算 8 维指数 + 操作建议标签，给自选个股详情页"看得懂该怎么办"的能力。

8 维指数：
  1. 趋势强度    — 基于 close_vs_ma20 + trend_consistency + higher_high
  2. 资金动能    — 主力净流入方向/幅度/连续性
  3. 板块共振    — 个股 vs 板块资金方向一致性
  4. 量能健康度  — 量比是否在合理区间
  5. 波动健康度  — ATR 是否在健康范围
  6. 相对强度    — 个股涨幅是否跑赢板块平均
  7. 回撤状态    — 近 20 日最高点回撤幅度
  8. 机构信号    — 特大单+主力买卖方向（StockMoneyFlowDetail）

操作建议标签：🟢 可持有/加仓 / 🟡 观望 / 🟠 减仓观察 / 🔴 远离

数据来源：StockFeaturesDaily + StockFlow + SectorFlow + StockMoneyFlowDetail + StockDailyKline
（全部现成，零新增采集）
"""
import asyncio
import logging
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
from sqlalchemy import func, desc

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from db.session import get_db_session
from typing import Optional
from db.models import (
    StockFeaturesDaily, StockFlow, SectorFlow, StockMoneyFlowDetail, StockDailyKline,
    RealtimeStockFlow, StockMoneyFlowRealtime, RealtimeSectorFlow,
)
from analyzers.stock_scores import calc_technical
from analyzers.strategy_engine import _find_sector_for_stock
from services.indicators import calc_kdj, calc_macd

router = APIRouter()
logger = logging.getLogger(__name__)


# ===== 进程内 TTL 缓存 =====
# 策略中心 / 共振页等列表会同时为 N 只股票各发一次 /api/stock-dashboard/{code}，
# 单只冷算 1-3s，110 只全走完要几十秒。盘后（end-of-day）数据按交易日固定、不会中途变化，
# 因此把 TTL 拉到 6 小时：同一交易日的股票只冷算一次，之后 6h 内任意次加载都瞬时返回，
# 彻底消除"每次打开都要等几十秒重算"的卡顿。仅当用户手动"重试 / 触发扫描"后想看最新值时，
# 前端带 refresh=1 绕过缓存强制重算。
# 用进程内 dict + 时间戳实现（不能用 @cached，会阻塞 event loop——项目历史教训）。
_DASH_CACHE = {}
_DASH_CACHE_TTL = 21600  # 6 小时（盘后数据按交易日固定，无需 5min 短缓存）
_DASH_CACHE_MAX = 500  # 最多缓存 500 只，防止内存膨胀


# 并发保护：batch 改为线程池并行后，多个 worker 会同时读写此进程内缓存 dict，必须加锁。
_DASH_CACHE_LOCK = threading.Lock()


def _dash_cache_get(code: str):
    """读缓存：返回 None 或 cached dict。命中时刷新时间戳。"""
    with _DASH_CACHE_LOCK:
        now = _time.time()
        item = _DASH_CACHE.get(code)
        if not item:
            return None
        if now - item['ts'] > _DASH_CACHE_TTL:
            _DASH_CACHE.pop(code, None)
            return None
        return item['data']


def _dash_cache_set(code: str, data: dict):
    with _DASH_CACHE_LOCK:
        if len(_DASH_CACHE) >= _DASH_CACHE_MAX:
            # FIFO 驱逐：删最旧的一条
            try:
                oldest = next(iter(_DASH_CACHE))
                _DASH_CACHE.pop(oldest, None)
            except StopIteration:
                pass
        _DASH_CACHE[code] = {'ts': _time.time(), 'data': data}


def _dash_cache_pop(code: str):
    """强制刷新时清除缓存（加锁，避免与并发读竞态）。"""
    with _DASH_CACHE_LOCK:
        _DASH_CACHE.pop(code, None)


# ===== 技术指标 KDJ / MACD =====
def _compute_technical_indicators(ts_code: str, db, target_date) -> dict:
    """计算 KDJ / MACD 技术指标及买卖信号。

    取近 60 个交易日 K 线（覆盖 MACD slow=26 + signal=9 + 余量），
    返回最新一日的指标值、前一日值（用于金叉/死叉判断）、以及信号标签。

    Returns:
        {
            'available': bool,
            'kdj': {'k': float, 'd': float, 'j': float, 'prev_k', 'prev_d', 'signal': str},
            'macd': {'dif': float, 'dea': float, 'macd': float, 'prev_dif', 'prev_dea', 'signal': str},
        }
    """
    klines = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
    ).order_by(StockDailyKline.trade_date.asc()).limit(60).all()

    if len(klines) < 35:  # MACD 最少需要 26+9 个点
        return {'available': False}

    highs = [float(k.high or 0) for k in klines]
    lows = [float(k.low or 0) for k in klines]
    closes = [float(k.close or 0) for k in klines]

    # KDJ
    k_vals, d_vals, j_vals = calc_kdj(highs, lows, closes)
    # MACD
    dif_arr, dea_arr, macd_arr = calc_macd(closes)

    # 取最后两个有效值（今日 + 昨日）判断金叉/死叉
    def _last_two(arr):
        valid = [(i, v) for i, v in enumerate(arr) if v is not None]
        if len(valid) < 2:
            return None, None
        return valid[-2][1], valid[-1][1]

    prev_k, cur_k = _last_two(k_vals)
    prev_d, cur_d = _last_two(d_vals)
    cur_j = j_vals[-1] if j_vals and j_vals[-1] is not None else None

    prev_dif, cur_dif = _last_two(dif_arr)
    prev_dea, cur_dea = _last_two(dea_arr)
    cur_macd = macd_arr[-1] if macd_arr and macd_arr[-1] is not None else None

    # KDJ 信号判断
    kdj_signal = '中性'
    if prev_k is not None and prev_d is not None and cur_k is not None and cur_d is not None:
        if prev_k <= prev_d and cur_k > cur_d:
            kdj_signal = '金叉'
        elif prev_k >= prev_d and cur_k < cur_d:
            kdj_signal = '死叉'
        elif cur_k > cur_d:
            kdj_signal = '多头'
        elif cur_k < cur_d:
            kdj_signal = '空头'
        # J 值超买/超卖
        if cur_j is not None:
            if cur_j > 100:
                kdj_signal = f'{kdj_signal}·超买'
            elif cur_j < 0:
                kdj_signal = f'{kdj_signal}·超卖'

    # MACD 信号判断
    macd_signal = '中性'
    if prev_dif is not None and prev_dea is not None and cur_dif is not None and cur_dea is not None:
        if prev_dif <= prev_dea and cur_dif > cur_dea:
            macd_signal = '金叉'
        elif prev_dif >= prev_dea and cur_dif < cur_dea:
            macd_signal = '死叉'
        elif cur_dif > cur_dea:
            macd_signal = '多头'
        elif cur_dif < cur_dea:
            macd_signal = '空头'
        # 红绿柱
        if cur_macd is not None:
            if cur_macd > 0 and macd_signal in ('多头', '金叉'):
                macd_signal = f'{macd_signal}·红柱'
            elif cur_macd < 0 and macd_signal in ('空头', '死叉'):
                macd_signal = f'{macd_signal}·绿柱'

    def _round(v):
        return round(v, 3) if v is not None else None

    return {
        'available': True,
        'kdj': {
            'k': _round(cur_k), 'd': _round(cur_d), 'j': _round(cur_j),
            'prev_k': _round(prev_k), 'prev_d': _round(prev_d),
            'signal': kdj_signal,
        },
        'macd': {
            'dif': _round(cur_dif), 'dea': _round(cur_dea), 'macd': _round(cur_macd),
            'prev_dif': _round(prev_dif), 'prev_dea': _round(prev_dea),
            'signal': macd_signal,
        },
    }


# ===== BS 区间档案（含区间内日 K 序列，供前端 sparkline）=====
def _compute_bs_interval(ts_code: str, current_price: float, db, target_date) -> dict:
    """计算 BS 区间档案 + 区间内日 K 序列

    复用 _generate_bs_signals（SuperTrend）生成 B/S 信号序列，
    再调 _calc_bs_interval 提取当前区间（持仓中/已平仓），
    最后从 StockDailyKline 取区间期间的日 K（含 B 起点 → S 终点/今天）暴露给前端画 sparkline。

    Returns:
        {
            'state': 'holding' | 'empty' | 'unknown',
            'start_date': str, 'start_price': float,
            'end_date': str, 'end_price': float,
            'hold_days': int, 'pnl_pct': float,
            'klines': [{'date': str, 'open': float, 'close': float,
                        'high': float, 'low': float, 'volume': float}, ...],
        }
    """
    from api.bs_signals import _generate_bs_signals
    from services.signal_builder import _calc_bs_interval

    # 取近 150 根日 K（与 bs_signals API 同口径，确保 EMA/MACD 收敛）
    kline_rows = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
    ).order_by(StockDailyKline.trade_date.asc()).limit(150).all()

    if len(kline_rows) < 35:
        return {'state': 'unknown', 'klines': []}

    klines = [{
        'date': k.trade_date.strftime('%Y-%m-%d') if hasattr(k.trade_date, 'strftime') else str(k.trade_date),
        'open': float(k.open or 0),
        'close': float(k.close or 0),
        'high': float(k.high or 0),
        'low': float(k.low or 0),
        'volume': float(k.volume or 0),
    } for k in kline_rows]

    try:
        bs_signals, *_ = _generate_bs_signals(klines)
    except Exception:
        logger.debug(f"[bs_interval] _generate_bs_signals failed for {ts_code}", exc_info=True)
        return {'state': 'unknown', 'klines': []}

    if not bs_signals:
        return {'state': 'unknown', 'klines': []}

    interval = _calc_bs_interval(bs_signals, current_price)
    interval['klines'] = []

    # 统一日期格式为 YYYY-MM-DD（klines 已是此格式）
    start_date = interval.get('start_date', '')
    end_date = interval.get('end_date', '')
    if not start_date:
        return interval

    sd_norm = start_date[:10]
    ed_norm = end_date[:10] if end_date else None

    # 显示最近 60 天日 K（提供 B 点前的趋势上下文），而不是只从 B 点开始
    # 60 个交易日约等于 3 个月，足够看清 BS 区间全貌+前期走势
    DISPLAY_DAYS = 60
    in_range = []
    total_klines = len(klines)
    start_idx = max(0, total_klines - DISPLAY_DAYS)
    for i in range(start_idx, total_klines):
        in_range.append(klines[i])

    interval['klines'] = in_range
    return interval


# ===== 工具 =====
def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def _features_to_dict(f) -> dict:
    return {
        'rsi_14': f.rsi_14,
        'volume_ratio': f.volume_ratio,
        'close_vs_ma20': f.close_vs_ma20,
        'higher_high_flag': f.higher_high_flag,
        'higher_low_flag': f.higher_low_flag,
        'trend_consistency_score': f.trend_consistency_score,
        'ma20_slope': f.ma20_slope,
        'main_net_inflow_1d': f.main_net_inflow_1d,
        'main_net_inflow_3d': f.main_net_inflow_3d,
        'main_net_inflow_5d': f.main_net_inflow_5d,
        'flow_continuity': f.flow_continuity,
        'sector_strength': f.sector_strength,
        'noise_ratio': f.noise_ratio,
        'atr_14': f.atr_14,
    }


# ===== 兜底：StockFeaturesDaily 缺失时，从 K 线 + StockFlow 现场算近似特征 =====
# 解决「共振列表 90%+ 股票不在 watchlist，features_daily 未被采集」导致 dashboard 不可用的问题。
# 仅覆盖 dashboard 用到的核心指标：MA/ATR/RSI/close_vs_ma20/volume_ratio/higher_high/momentum/连续性。
# sector_strength / noise_ratio 等仅在 features 里有真值，缺失时给中性默认（0.5 / 1.0）。
def _features_from_kline_fallback(ts_code: str, target_date, db) -> Optional[dict]:
    """从 K 线 + 资金流现场合成 features 字典，返回 None 表示 K 线不足。"""
    klines = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
    ).order_by(StockDailyKline.trade_date.asc()).limit(120).all()
    if len(klines) < 30:
        return None

    closes = [float(k.close or 0) for k in klines if k.close is not None]
    volumes = [float(k.volume or 0) for k in klines if k.volume is not None]
    highs = [float(k.high or 0) for k in klines if k.high is not None]
    lows = [float(k.low or 0) for k in klines if k.low is not None]

    if len(closes) < 30:
        return None

    close = closes[-1]
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else close
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else close
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else close
    close_vs_ma20 = (close / ma20 - 1) if ma20 > 0 else 0
    # MA20 斜率：今日 ma20 vs 5 日前 ma20 的变化率
    if len(closes) >= 25:
        ma20_5d_ago = sum(closes[-25:-5]) / 20
        ma20_slope = (ma20 / ma20_5d_ago - 1) if ma20_5d_ago > 0 else 0
    else:
        ma20_slope = 0

    # ATR(14)：True Range 14 日平均
    trs = []
    for i in range(-14, 0):
        if i == -14:
            continue
        h = highs[i]
        l = lows[i]
        pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr_14 = sum(trs) / len(trs) if trs else 0

    # Volume ratio：今日 vol / 20日均量
    vol_20_avg = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else (volumes[-1] if volumes else 1)
    volume_ratio = (volumes[-1] / vol_20_avg) if vol_20_avg > 0 else 1

    # higher_high / higher_low_flag：今日 high/low 是否创 20 日新高/新低（严格 > / <）
    high_20 = max(highs[-20:]) if len(highs) >= 20 else highs[-1]
    low_20 = min(lows[-20:]) if len(lows) >= 20 else lows[-1]
    higher_high_flag = 1 if highs[-1] > high_20 else 0
    higher_low_flag = 1 if lows[-1] > low_20 else 0

    # trend_consistency_score：近 20 日 close > ma20 的占比（0-1）
    if len(closes) >= 20:
        above = sum(1 for i in range(-20, 0) if closes[i] > ma20)
        trend_consistency_score = above / 20
    else:
        trend_consistency_score = 0.5

    # RSI(14)：Wilder 平滑
    rsi_14 = 50
    if len(closes) >= 15:
        gains, losses = [], []
        for i in range(-14, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0))
            losses.append(max(-diff, 0))
        avg_gain = sum(gains) / 14
        avg_loss = sum(losses) / 14
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi_14 = 100 - 100 / (1 + rs)
        else:
            rsi_14 = 100 if avg_gain > 0 else 50

    # 资金流连续性：近 5 日 StockFlow 主力净流入正的天数
    code6 = ts_code.split('.')[0]
    flows = db.query(StockFlow).filter(
        StockFlow.ts_code == ts_code,
        StockFlow.trade_date <= target_date,
    ).order_by(StockFlow.trade_date.desc()).limit(5).all()
    inflow_1d = float(flows[0].main_force_inflow or 0) if len(flows) >= 1 else 0
    inflow_3d = sum(float(f.main_force_inflow or 0) for f in flows[:3]) if flows else 0
    inflow_5d = sum(float(f.main_force_inflow or 0) for f in flows[:5]) if flows else 0
    flow_continuity = sum(1 for f in flows if float(f.main_force_inflow or 0) > 0) if flows else 0

    return {
        'rsi_14': round(rsi_14, 2),
        'volume_ratio': round(volume_ratio, 2),
        'close_vs_ma20': round(close_vs_ma20, 4),
        'higher_high_flag': higher_high_flag,
        'higher_low_flag': higher_low_flag,
        'trend_consistency_score': round(trend_consistency_score, 2),
        'ma20_slope': round(ma20_slope, 4),
        'main_net_inflow_1d': inflow_1d,
        'main_net_inflow_3d': inflow_3d,
        'main_net_inflow_5d': inflow_5d,
        'flow_continuity': flow_continuity,
        'sector_strength': 0,      # 兜底默认中性
        'noise_ratio': 1.0,        # 兜底默认中性
        'atr_14': round(atr_14, 4),
        # 同步供 _compute_dashboard 后续用（避免再查一次）
        '_close': close,
    }


# ===== 实时维度计算 =====
def _compute_realtime(code: str, sector: str, db) -> dict:
    """从 RealtimeStockFlow / RealtimeSectorFlow / StockMoneyFlowRealtime 算实时维度分。

    取「最近一个有实时快照的交易日」而非严格今天，使盘后/非交易时段也能看到
    最近一个交易时段的实时数据（避免非交易时段实时列恒为空白）。

    live 标记：仅当快照所属交易日 == 今天 且 当前处于交易时段(09:30-15:00) 时才为 True，
    否则为「上一交易日收盘快照」，前端据此诚实标注，不把历史数据伪装成实时。
    """
    latest_rt = db.query(func.max(RealtimeStockFlow.trade_date)).filter(
        RealtimeStockFlow.ts_code.like(f'{code}.%')
    ).scalar()
    if not latest_rt:
        return {'available': False}
    today = latest_rt

    now = datetime.now()
    cur_time = now.time()
    in_session = cur_time >= datetime.strptime('09:30', '%H:%M').time() and \
                 cur_time <= datetime.strptime('15:00', '%H:%M').time()
    live = (today == date.today()) and in_session

    rt_flow = db.query(RealtimeStockFlow).filter(
        RealtimeStockFlow.ts_code.like(f'{code}.%'),
        RealtimeStockFlow.trade_date == today,
    ).order_by(RealtimeStockFlow.snapshot_time.desc()).first()

    if not rt_flow:
        return {'available': False}

    rt_pct_chg = float(rt_flow.price_chg or 0)
    rt_main_force = float(rt_flow.main_force_inflow or 0) * 10000  # 万元→元
    rt_snapshot_time = rt_flow.snapshot_time

    # 机构
    rt_money = db.query(StockMoneyFlowRealtime).filter(
        StockMoneyFlowRealtime.ts_code.like(f'{code}.%'),
        StockMoneyFlowRealtime.trade_date == today,
    ).order_by(StockMoneyFlowRealtime.snapshot_time.desc()).first()

    rt_main_net = float(rt_money.main_net or 0) if rt_money else 0

    # 板块
    rt_sector = db.query(RealtimeSectorFlow).filter(
        RealtimeSectorFlow.sector == sector,
        RealtimeSectorFlow.trade_date == today,
    ).order_by(RealtimeSectorFlow.snapshot_time.desc()).first() if sector else None

    rt_sector_net = float(rt_sector.net_flow or 0) if rt_sector else 0
    rt_sector_rise = float(rt_sector.rise_ratio or 0) if rt_sector else 0

    # ---- 5 个可算维度 ----
    trend_rt = _clamp(50 + rt_pct_chg * (10 if rt_pct_chg >= 0 else 8), 0, 100)

    mag_bonus = min(abs(rt_main_force) / 1e8, 3) * 10 if rt_main_force > 0 else \
                -min(abs(rt_main_force) / 1e8, 2) * 8
    capital_rt = _clamp(50 + mag_bonus, 0, 100)

    same_dir = (rt_main_force > 0) == (rt_sector_net > 0)
    resonance_rt = 75 if (same_dir and abs(rt_main_force) > 1e6) else \
                   55 if abs(rt_main_force) < 1e6 else 25

    relative_rt = _clamp(50 + (rt_pct_chg - rt_sector_rise) * 12, 0, 100)

    inst_rt = _clamp(
        50 + (rt_main_net > 0) * 20 + min(abs(rt_main_net) / 5e7 * 15, 15) * (1 if rt_main_net > 0 else -1),
        0, 100,
    ) if rt_money else None

    # ---- 当日分时序列（真正的实时时间维度）：价格 + 主力净流入随快照时间变化 ----
    rt_series = db.query(RealtimeStockFlow).filter(
        RealtimeStockFlow.ts_code.like(f'{code}.%'),
        RealtimeStockFlow.trade_date == today,
    ).order_by(RealtimeStockFlow.snapshot_time.asc()).all()
    intraday = [{
        't': r.snapshot_time.strftime('%H:%M') if r.snapshot_time else None,
        'price': round(float(r.price or 0), 2) if r.price is not None else None,
        'pct_chg': round(float(r.price_chg or 0), 2) if r.price_chg is not None else None,
        'main_force': round(float(r.main_force_inflow or 0) * 10000) if r.main_force_inflow is not None else None,  # 万元→元
    } for r in rt_series]

    # ---- 从日内价格序列补齐剩余 3 个维度，使盘后/实时左右 8 维对齐 ----
    prices = [float(r.price or 0) for r in rt_series if r.price is not None]
    if len(prices) >= 2:
        rt_high = max(prices)
        rt_low = min(prices)
        rt_current = prices[-1]

        # 波动健康：日内振幅（与盘后 ATR/close 口径不同但语义一致）
        if rt_low > 0:
            amplitude_pct = (rt_high - rt_low) / rt_low * 100
            if 1.0 <= amplitude_pct <= 5.0:
                volatility_rt = 80
            elif 0.5 <= amplitude_pct <= 8.0:
                volatility_rt = 60
            else:
                volatility_rt = 35
        else:
            volatility_rt = 50

        # 回撤状态：当前价相对日内高点的回撤
        if rt_high > 0:
            rt_dd = (rt_current - rt_high) / rt_high * 100  # 负值=回撤
            drawdown_rt = _clamp(100 + rt_dd * 8, 0, 100)
        else:
            drawdown_rt = 100
    else:
        volatility_rt = 50
        drawdown_rt = 100

    # 量能健康：实时无逐笔成交量比，用主力净流入强度代理（与资金动能同向但口径不同）
    if abs(rt_main_force) > 1e6:
        vol_bonus = min(abs(rt_main_force) / 1e8, 3) * 10
        volume_rt = _clamp(50 + (1 if rt_main_force > 0 else -1) * vol_bonus, 0, 100)
    else:
        volume_rt = 50

    return {
        'available': True,
        'live': live,
        # 三种状态，供前端诚实标注：
        #   live         —— 今天盘中且处于交易时段，实时数据滚动更新
        #   closed_today —— 今天有实时数据但已收盘（或尚未开盘前），定格在今天最后 1 分钟快照，
        #                   即「盘后」视图，一直挂到下一个开盘才重新计算
        #   previous     —— 今天尚无任何实时数据（如周末/休市/开盘前），回退到最近一个交易日
        'mode': 'live' if live else ('closed_today' if today == date.today() else 'previous'),
        'date': today.isoformat(),
        'snapshot_time': rt_snapshot_time.strftime('%Y-%m-%dT%H:%M') if rt_snapshot_time else None,
        'trend_strength': round(trend_rt, 1),
        'capital_momentum': round(capital_rt, 1),
        'sector_resonance': round(resonance_rt, 1),
        'relative_strength': round(relative_rt, 1),
        'volume_health': round(volume_rt, 1),
        'volatility_health': round(volatility_rt, 1),
        'drawdown_status': round(drawdown_rt, 1),
        'institution_signal': round(inst_rt, 1) if inst_rt is not None else None,
        'price_chg': round(rt_pct_chg, 2),
        # 资金流向拆解（实时端仅主力/散户/板块有，4 档拆解实时暂无）
        'main_net': round(rt_main_net),
        'retail_net': round(float(rt_money.retail_net or 0)) if rt_money else None,
        'sector_net': round(rt_sector_net * 10000) if rt_sector else None,  # 万元→元
        'sector_rise': round(rt_sector_rise, 2) if rt_sector else None,  # 板块实时涨幅%（供前端「个股 vs 板块」对照）
        # 当日分时序列（真实时间维度）
        'intraday': intraday,
    }


# ===== 主力净流入累计（多周期） =====
def _compute_cumulative(ts_code: str, sector: str, db, target_date, periods=(1, 2, 3, 5, 10, 20)) -> dict:
    """按最近 N 个有数据的交易日累加主力净流入（个股用 main_net，板块用 net_flow），单位元。

    说明：交易所有休市/停牌，故"近N日"=最近 N 个有数据的交易日，而非自然日。
    若历史交易日不足 N 个，则该周期返回 None（前端显示为空，不做虚假补全）。
    """
    max_p = max(periods)

    # 个股：取最近 max_p 个交易日的 main_net
    stock_dates = [d[0] for d in db.query(StockMoneyFlowDetail.trade_date).filter(
        StockMoneyFlowDetail.ts_code == ts_code,
        StockMoneyFlowDetail.trade_date <= target_date,
    ).distinct().order_by(StockMoneyFlowDetail.trade_date.desc()).limit(max_p).all()]

    stock = {}
    for p in periods:
        if len(stock_dates) >= p:
            sel = stock_dates[:p]
            s = db.query(func.sum(StockMoneyFlowDetail.main_net)).filter(
                StockMoneyFlowDetail.ts_code == ts_code,
                StockMoneyFlowDetail.trade_date.in_(sel),
            ).scalar() or 0
            stock[p] = round(float(s))
        else:
            stock[p] = None

    # 板块：取最近 max_p 个交易日的 net_flow
    sector_cum = {}
    if sector:
        sec_dates = [d[0] for d in db.query(SectorFlow.trade_date).filter(
            SectorFlow.sector == sector,
            SectorFlow.trade_date <= target_date,
        ).distinct().order_by(SectorFlow.trade_date.desc()).limit(max_p).all()]
        for p in periods:
            if len(sec_dates) >= p:
                sel = sec_dates[:p]
                s = db.query(func.sum(SectorFlow.net_flow)).filter(
                    SectorFlow.sector == sector,
                    SectorFlow.trade_date.in_(sel),
                ).scalar() or 0
                sector_cum[p] = round(float(s))
            else:
                sector_cum[p] = None
    else:
        for p in periods:
            sector_cum[p] = None

    return {'periods': list(periods), 'stock': stock, 'sector': sector_cum}


def _compute_sector_rotation(sector: str, db, target_date, lookback_days: int = 10) -> Optional[dict]:
    """板块轮动完整版计算——基于历史 N 日数据计算轮动阶段、资金连续性、龙头持续性等信号。

    返回字段：
    - consecutive_inflow_days: 连续净流入天数（≥1 表示持续入场）
    - consecutive_outflow_days: 连续净流出天数
    - cumulative_net_flow: N 日累计净流入金额（万元）
    - avg_daily_inflow: 日均净流入金额
    - inflow_strength: 资金入场强度评分 0-100（综合连续性 + 累计规模）
    - heat_slope_5d: 5日热度斜率（升温速率）
    - heat_trend: 热度趋势 'accel_up' / 'steady_up' / 'stable' / 'cooling_down' / 'accel_down'
    - leader_continuity_days: 龙头连续领涨天数
    - leader_changed: 龙头是否切换（与昨日对比）
    - cumulative_chg_5d: 5日累计涨幅
    - cumulative_chg_10d: 10日累计涨幅
    - rotation_signal: 综合轮动信号标签（犀利操作建议）
    - rotation_color: 标签颜色
    - rotation_icon: 标签图标
    - days_to_buy: 预计还需多少天可买（基于入场强度推算，吸筹期信号）
    """
    if not sector:
        return None

    # 取最近 lookback_days 个交易日的板块数据
    rows = db.query(SectorFlow).filter(
        SectorFlow.sector == sector,
        SectorFlow.trade_date <= target_date,
    ).order_by(SectorFlow.trade_date.desc()).limit(lookback_days).all()

    if not rows:
        return None

    # rows[0] = 今日，rows[1] = 昨日，...
    today = rows[0]
    net_flows = [float(r.net_flow or 0) for r in rows]  # 万元
    heat_scores = [float(r.heat_score) if r.heat_score is not None else None for r in rows]
    leader_stocks = [r.leader_stock for r in rows]
    leader_strengths = [float(r.leader_strength) if r.leader_strength is not None else None for r in rows]
    avg_chgs = [float(r.avg_chg) if r.avg_chg is not None else 0 for r in rows]
    limit_up_counts = [int(r.limit_up_count or 0) for r in rows]

    # 1. 资金连续性
    consecutive_inflow_days = 0
    for f in net_flows:
        if f > 0:
            consecutive_inflow_days += 1
        else:
            break
    consecutive_outflow_days = 0
    for f in net_flows:
        if f < 0:
            consecutive_outflow_days += 1
        else:
            break

    # N 日累计净流入
    cumulative_net_flow = round(sum(net_flows), 2)
    avg_daily_inflow = round(cumulative_net_flow / len(net_flows), 2) if net_flows else 0

    # 资金入场强度评分 0-100
    # 算法：连续性天数权重50% + 累计规模权重50%
    inflow_strength = 0
    if consecutive_inflow_days > 0:
        # 连续性：3天=50分，5天=70分，7天=85分，10天=100分
        consec_score = min(100, consecutive_inflow_days * 15 + 10)
        # 累计规模：1亿=50分，5亿=80分，10亿=100分（万元单位）
        abs_cum = abs(cumulative_net_flow)
        if cumulative_net_flow > 0:
            scale_score = min(100, abs_cum / 100000 * 50 + 30)  # 10万=30分，10亿=100分
        else:
            scale_score = 0
        inflow_strength = round(consec_score * 0.5 + scale_score * 0.5)

    # 2. 热度趋势
    heat_slope_5d = None
    if len(heat_scores) >= 5 and all(h is not None for h in heat_scores[:5]):
        recent_5 = heat_scores[:5]
        # 线性回归斜率：(y2-y1) / (x2-x1)，简化为首尾差
        heat_slope_5d = round((recent_5[0] - recent_5[-1]) / 5, 2)

    heat_trend = 'stable'
    if heat_slope_5d is not None:
        # 加速度：近3日斜率 vs 远3日斜率
        if len(heat_scores) >= 6:
            recent_3 = heat_scores[:3]
            far_3 = heat_scores[3:6]
            recent_slope = (recent_3[0] - recent_3[-1]) / 3 if all(h is not None for h in recent_3) else 0
            far_slope = (far_3[0] - far_3[-1]) / 3 if all(h is not None for h in far_3) else 0
            accel = recent_slope - far_slope
            if heat_slope_5d > 3 and accel > 1:
                heat_trend = 'accel_up'  # 加速升温
            elif heat_slope_5d > 3:
                heat_trend = 'steady_up'  # 匀速升温
            elif heat_slope_5d < -3 and accel < -1:
                heat_trend = 'accel_down'  # 加速降温
            elif heat_slope_5d < -3:
                heat_trend = 'cooling_down'  # 匀速降温
        else:
            if heat_slope_5d > 3:
                heat_trend = 'steady_up'
            elif heat_slope_5d < -3:
                heat_trend = 'cooling_down'

    # 3. 龙头持续性
    leader_continuity_days = 0
    today_leader = leader_stocks[0] if leader_stocks else None
    for ls in leader_stocks:
        if ls and today_leader and ls == today_leader:
            leader_continuity_days += 1
        else:
            break
    leader_changed = (len(leader_stocks) >= 2 and
                     leader_stocks[0] and leader_stocks[1] and
                     leader_stocks[0] != leader_stocks[1])

    # 4. 累计涨幅
    cumulative_chg_5d = round(sum(avg_chgs[:5]), 2) if len(avg_chgs) >= 5 else None
    cumulative_chg_10d = round(sum(avg_chgs[:10]), 2) if len(avg_chgs) >= 10 else None

    # 5. 综合轮动信号（核心）
    rotation_signal = None
    rotation_color = '#94a3b8'
    rotation_icon = '⏳'
    days_to_buy = None

    today_leader_strength = leader_strengths[0] if leader_strengths else None

    # 金额格式化：万→亿
    def _fmt_flow(wan):
        abs_w = abs(wan)
        if abs_w >= 10000:
            return f'{wan/10000:.2f}亿'
        return f'{wan:.0f}万'

    cum_flow_str = _fmt_flow(cumulative_net_flow)
    # 详情字符串：天数+累计金额（前端单独展示，避免信号过长换行）
    flow_direction = '流入' if cumulative_net_flow >= 0 else '流出'
    rotation_detail = f'{consecutive_inflow_days if cumulative_net_flow >= 0 else consecutive_outflow_days}天{flow_direction}·累计{cum_flow_str}'

    if consecutive_inflow_days >= 7 and cumulative_net_flow >= 200000:
        # 连续7天+流入且累计≥20亿 → 主升浪
        rotation_signal = f'主升浪·持股待涨'
        rotation_color = '#dc2626'
        rotation_icon = '🚀'
    elif consecutive_inflow_days >= 5 and cumulative_net_flow >= 100000:
        # 连续5天+流入且累计≥10亿 → 主力建仓完毕
        days_to_buy = max(0, 7 - consecutive_inflow_days)
        rotation_signal = f'主力建仓·即将启动'
        rotation_color = '#ef4444'
        rotation_icon = '💰'
    elif consecutive_inflow_days >= 3 and cumulative_net_flow >= 50000:
        # 连续3天+流入且累计≥5亿 → 吸筹中
        days_to_buy = max(1, 5 - consecutive_inflow_days)
        rotation_signal = f'主力吸筹·再等{days_to_buy}天可买'
        rotation_color = '#f97316'
        rotation_icon = '🔍'
    elif consecutive_inflow_days >= 2 and cumulative_net_flow >= 10000:
        # 连续2天+流入且累计≥1亿 → 试探性建仓
        days_to_buy = max(2, 5 - consecutive_inflow_days)
        rotation_signal = f'主力试探·观察{days_to_buy}天确认'
        rotation_color = '#eab308'
        rotation_icon = '👀'
    elif consecutive_inflow_days >= 1:
        # 单日流入
        rotation_signal = f'资金流入·观察'
        rotation_color = '#3b82f6'
        rotation_icon = '💧'
    elif consecutive_outflow_days >= 5 and cumulative_net_flow <= -100000:
        # 连续5天+流出且累计≥10亿 → 主力出货
        rotation_signal = f'主力出货·坚决回避'
        rotation_color = '#22c55e'
        rotation_icon = '🏃'
    elif consecutive_outflow_days >= 3 and cumulative_net_flow <= -50000:
        # 连续3天+流出且累计≥5亿 → 资金撤退
        rotation_signal = f'资金撤退·减仓'
        rotation_color = '#3b82f6'
        rotation_icon = '📉'
    elif consecutive_outflow_days >= 1:
        # 单日流出
        rotation_signal = f'资金流出·谨慎'
        rotation_color = '#94a3b8'
        rotation_icon = '💧'
    else:
        rotation_signal = '资金中性·观望'
        rotation_color = '#94a3b8'
        rotation_icon = '⏳'
        rotation_detail = ''

    # 龙头信号覆写：龙头断板或切换时加注警示
    if today_leader_strength is not None and today_leader_strength < 3 and consecutive_inflow_days >= 3:
        rotation_signal = f'龙头断板·见顶信号 / {rotation_signal}'
        rotation_color = '#dc2626'
        rotation_icon = '⚠️'
    elif leader_changed and consecutive_inflow_days >= 3:
        rotation_signal = f'龙头切换·分歧加剧 / {rotation_signal}'
        rotation_color = '#f97316'
        rotation_icon = '🔀'

    # 热度趋势加注
    heat_trend_label = {
        'accel_up': '热度加速',
        'steady_up': '热度升温',
        'stable': '热度稳定',
        'cooling_down': '热度降温',
        'accel_down': '热度急降',
    }.get(heat_trend, '热度未知')

    return {
        'consecutive_inflow_days': consecutive_inflow_days,
        'consecutive_outflow_days': consecutive_outflow_days,
        'cumulative_net_flow_wan': cumulative_net_flow,  # 万元
        'avg_daily_inflow_wan': avg_daily_inflow,
        'inflow_strength': inflow_strength,
        'heat_slope_5d': heat_slope_5d,
        'heat_trend': heat_trend,
        'heat_trend_label': heat_trend_label,
        'leader_continuity_days': leader_continuity_days,
        'leader_changed': leader_changed,
        'cumulative_chg_5d': cumulative_chg_5d,
        'cumulative_chg_10d': cumulative_chg_10d,
        'rotation_signal': rotation_signal,
        'rotation_color': rotation_color,
        'rotation_icon': rotation_icon,
        'rotation_detail': rotation_detail,
        'days_to_buy': days_to_buy,
    }



# ===== 8 维盘后计算（原有） =====
def _compute_dashboard(code: str, db) -> Optional[dict]:
    """核心计算——单只股票的 8 维指数 + 操作建议"""
    # 容错：剥掉 ts_code 后缀（.SZ/.SH/.BJ/.sh/.sz/.bj），兼容前端传入 6位或 9位
    # stock_features_daily.stock_code 与 stock_flow 的 LIKE 'XXX.%' 都按 6 位存
    code6 = code.split('.')[0] if code else ''
    if not code6:
        return None

    # 优先按 StockFlow 定位最新交易日（覆盖全市场，比 features_daily 范围广得多）
    # features_daily 只覆盖自选股（113 只/日），共振列表 250+ 只无法命中。
    # 但 StockFlow 是全市场入库的，所以先查 StockFlow，再回退 features_daily。
    latest_flow = db.query(StockFlow).filter(
        StockFlow.ts_code.like(f'{code6}.%')
    ).order_by(StockFlow.trade_date.desc()).first()
    if latest_flow:
        target_date = latest_flow.trade_date
        ts_code = latest_flow.ts_code
    else:
        # 兜底：features_daily 推日（自选股场景）
        feat_date_str = db.query(func.max(StockFeaturesDaily.trade_date)).filter(
            StockFeaturesDaily.stock_code == code6
        ).scalar()
        if not feat_date_str:
            return None
        target_date = datetime.strptime(feat_date_str, '%Y%m%d').date()
        # 找 ts_code（按 features_daily 的 trade_date 找最近一条 kline）
        k = db.query(StockDailyKline).filter(
            StockDailyKline.trade_date <= target_date
        ).filter(StockDailyKline.ts_code.like(f'{code6}.%')).order_by(
            StockDailyKline.trade_date.desc()).first()
        if k:
            ts_code = k.ts_code
        else:
            # 真没有 ts_code 信息则放弃
            return None
    date_str = target_date.strftime('%Y%m%d')

    # StockFeaturesDaily：首选（值最准），缺失时回退 K 线现场计算
    feat = db.query(StockFeaturesDaily).filter(
        StockFeaturesDaily.stock_code == code6,
        StockFeaturesDaily.trade_date == date_str,
    ).first()

    if feat:
        features = _features_to_dict(feat)
        cv = float(feat.close_vs_ma20 or 0)
        tc = float(feat.trend_consistency_score or 0)
        hh = int(feat.higher_high_flag or 0)
        rsi = float(feat.rsi_14 or 50)
        inflow_3d = float(feat.main_net_inflow_3d or 0)
        flow_cont = int(feat.flow_continuity or 0)
        close = float(feat.close or 1)
        atr = float(feat.atr_14 or 0)
        vr = float(feat.volume_ratio or 1)
    else:
        # 兜底：从 K 线 + 资金流现场算近似 features
        kline_feats = _features_from_kline_fallback(ts_code, target_date, db)
        if not kline_feats:
            return None
        features = {k: v for k, v in kline_feats.items() if not k.startswith('_')}
        cv = float(features.get('close_vs_ma20', 0) or 0)
        tc = float(features.get('trend_consistency_score', 0) or 0)
        hh = int(features.get('higher_high_flag', 0) or 0)
        rsi = float(features.get('rsi_14', 50) or 50)
        inflow_3d = float(features.get('main_net_inflow_3d', 0) or 0)
        flow_cont = int(features.get('flow_continuity', 0) or 0)
        close = float(kline_feats.get('_close', 1) or 1)
        atr = float(features.get('atr_14', 0) or 0)
        vr = float(features.get('volume_ratio', 1) or 1)
        logger.info(f"[stock_dashboard] {ts_code} features_daily 缺失，使用 K 线兜底（cv={cv:.3f}, tc={tc:.2f}, rsi={rsi:.1f}）")

    # StockFlow（板块、涨幅、主力净流入）
    flow = db.query(StockFlow).filter(
        StockFlow.trade_date == target_date,
    ).filter(StockFlow.ts_code == ts_code).first()
    if not flow:
        # 兜底：features_daily 路径下没找到 flow，尝试最新日
        flow = latest_flow or db.query(StockFlow).filter(
            StockFlow.ts_code == ts_code,
        ).order_by(StockFlow.trade_date.desc()).first()
    if not flow:
        return None

    # 板块归属：复用 strategy_engine 的解析（从 stock_flow 取最近一个非空 sector），
    # 与顶部 sectorTrend 同口径；最新行 sector 为空时也能正确回退，避免板块名对不上导致查不到。
    sector = _find_sector_for_stock(db, ts_code) or flow.sector or ''
    main_inflow = float(flow.main_force_inflow or 0)
    own_chg = float(flow.price_chg or 0)
    price = float(flow.price or close)

    # calc_technical（复用现有技术形态评分）
    technical = calc_technical(features)
    tech_score = (technical or {}).get('score', 50)

    # 1. 趋势强度 0-100
    trend_strength = _clamp(
        tech_score * 0.5 + (cv * 200 + 50) * 0.3 + tc * 100 * 0.2,
        0, 100,
    )

    # 2. 资金动能 0-100
    mag_bonus = min(abs(main_inflow) / 1e8, 3) * 10 if main_inflow > 0 else \
                -min(abs(main_inflow) / 1e8, 2) * 8
    capital_momentum = _clamp(
        50 + mag_bonus + flow_cont * 5 + (inflow_3d > 0) * 10,
        0, 100,
    )

    # 3. 板块共振 0-100
    # 板块净流入：与顶部 sectorTrend.total_net_flow 完全同口径 —— 近 7 日 SectorFlow.net_flow 累加
    # （strategy_engine._get_sector_trend 即 limit(7) 后 sum(net_flows)）
    sector_net = 0.0
    if sector:
        srows = db.query(SectorFlow.net_flow).filter(
            SectorFlow.sector == sector,
        ).order_by(SectorFlow.trade_date.desc()).limit(7).all()
        sector_net = float(sum((r[0] or 0) for r in srows))
    # 单日板块概览（平均涨幅 / 涨停数）：取该板块最近一个交易日
    sf = db.query(SectorFlow).filter(
        SectorFlow.sector == sector,
    ).order_by(SectorFlow.trade_date.desc()).first() if sector else None
    sector_avg_chg = float(sf.avg_chg or 0) if sf else 0
    sector_limit_up = int(sf.limit_up_count or 0) if sf else 0
    same_direction = (main_inflow > 0) == (sector_net > 0)
    resonance = 75 if (same_direction and abs(main_inflow) > 1e6) else \
                (55 if abs(main_inflow) < 1e6 else 25)

    # 4. 量能健康度 0-100
    if 0.8 <= vr <= 2.5:
        volume_health = 85
    elif 0.5 <= vr <= 3.0:
        volume_health = 60
    else:
        volume_health = 35

    # 5. 波动健康度 0-100
    if close > 0 and atr > 0:
        vh_pct = atr / close * 100
        if 1.0 <= vh_pct <= 5.0:
            volatility_health = 80
        elif 0.5 <= vh_pct <= 8.0:
            volatility_health = 60
        else:
            volatility_health = 35
    else:
        volatility_health = 50

    # 6. 相对强度 0-100（个股涨幅 vs 板块平均涨幅）
    diff = own_chg - sector_avg_chg
    relative_strength = _clamp(50 + diff * 12, 0, 100)

    # 7. 回撤状态 0-100
    klines = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
    ).order_by(StockDailyKline.trade_date.desc()).limit(20).all()
    if klines:
        n_high = max(float(k.high or 0) for k in klines)
        if n_high > 0:
            dd = (close - n_high) / n_high * 100  # 负值=回撤
        else:
            dd = 0
    else:
        dd = 0
    drawdown_status = _clamp(100 + dd * 8, 0, 100)  # dd=-5% → 60; dd=-10% → 20

    # 8. 机构信号 0-100
    inst = db.query(StockMoneyFlowDetail).filter(
        StockMoneyFlowDetail.trade_date == target_date,
        StockMoneyFlowDetail.ts_code == ts_code,
    ).first()
    inst_detail = {
        'has_data': False,
        'super_large_net': 0, 'large_net': 0, 'medium_net': 0,
        'small_net': 0, 'tiny_net': 0,
        'main_net': 0, 'main_buy': 0, 'main_sell': 0,
        'retail_net': 0, 'retail_buy': 0, 'retail_sell': 0,
    }
    if inst:
        super_large = float(inst.super_large_net or 0)
        large = float(inst.large_net or 0)
        medium = float(inst.medium_net or 0)
        small = float(inst.small_net or 0)
        tiny = float(inst.tiny_net or 0)
        mn = float(inst.main_net or 0)
        inst_score = _clamp(
            50 + (super_large > 0) * 20 + (mn > 0) * 10 +
            min(abs(super_large) / 5e7 * 15, 15) * (1 if super_large > 0 else -1),
            0, 100,
        )
        inst_detail = {
            'has_data': True,
            'super_large_net': super_large,
            'large_net': large,
            'medium_net': medium,
            'small_net': small,
            'tiny_net': tiny,
            'main_net': mn,
            'main_buy': float(inst.main_buy or 0),
            'main_sell': float(inst.main_sell or 0),
            'retail_net': float(inst.retail_net or 0),
            'retail_buy': float(inst.retail_buy or 0),
            'retail_sell': float(inst.retail_sell or 0),
        }
    else:
        inst_score = 50  # 无数据→中性

    # ===== 操作建议标签 =====
    core_avg = (trend_strength + capital_momentum + resonance + relative_strength) / 4
    # 8 维综合评分（0-100）：与 watchlist API 的 overallScore 对齐
    overall_score = round((trend_strength + capital_momentum + resonance + relative_strength
                           + volume_health + volatility_health + drawdown_status + inst_score) / 8, 1)
    if trend_strength >= 60 and capital_momentum >= 50 and resonance >= 50 and drawdown_status >= 60:
        action_label = '可持有 / 加仓'
        action_color = '#22c55e'
    elif core_avg >= 48:
        action_label = '观望'
        action_color = '#eab308'
    elif core_avg >= 32:
        action_label = '减仓观察'
        action_color = '#f97316'
    else:
        action_label = '远离'
        action_color = '#ef4444'

    return {
        'trend_strength': round(trend_strength, 1),
        'capital_momentum': round(capital_momentum, 1),
        'sector_resonance': round(resonance, 1),
        'volume_health': round(volume_health, 1),
        'volatility_health': round(volatility_health, 1),
        'relative_strength': round(relative_strength, 1),
        'drawdown_status': round(drawdown_status, 1),
        'institution_signal': round(inst_score, 1),
        'overall_score': overall_score,  # 8 维综合评分（与 watchlist API 对齐）
        'action_label': action_label,
        'action_color': action_color,
        'sector_flow': {
            'sector': sector,
            'net_flow': sector_net,
            'avg_chg': sector_avg_chg,
            'limit_up_count': sector_limit_up,
            'rise_ratio': float(sf.rise_ratio) if sf and sf.rise_ratio is not None else None,
            'leader_stock': sf.leader_stock if sf else None,
            'leader_strength': float(sf.leader_strength) if sf and sf.leader_strength is not None else None,
            'heat_score': float(sf.heat_score) if sf and sf.heat_score is not None else None,
        },
        'institution_flow': inst_detail,
        'realtime': _compute_realtime(code6, sector, db),
        'main_net_cumulative': _compute_cumulative(ts_code, sector, db, target_date),
        'sector_rotation': _compute_sector_rotation(sector, db, target_date),
        'technical_indicators': _compute_technical_indicators(ts_code, db, target_date),
        'bs_interval': _compute_bs_interval(ts_code, close, db, target_date),
        'features': features,
        'quote': {
            'price': price,
            'change': own_chg,
            'name': flow.name or code6,
        },
        'date': target_date.isoformat(),
        'code': code,
    }


# ===== 线程池：并行计算未命中缓存的股票 =====
# 单只 _compute_dashboard 是纯本地 PostgreSQL 只读查询（无外部网络 IO），耗时主要在 DB 往返 +
# 指标计算。串行 50 只需 40s+；改为线程池并行（独立 session / 独立 psycopg2 连接，线程安全）
# 后，墙钟时间随并发数线性下降。连接池 15，取 12 留余量给其他并发请求。
_DASH_EXECUTOR = None


def _get_executor():
    global _DASH_EXECUTOR
    if _DASH_EXECUTOR is None:
        _DASH_EXECUTOR = ThreadPoolExecutor(max_workers=12, thread_name_prefix="dash-worker")
    return _DASH_EXECUTOR


def _compute_one(code: str):
    """线程池 worker：独立 DB session + 受锁保护的缓存写入。纯只读 + 本地表，线程安全。"""
    try:
        with get_db_session() as db:
            r = _compute_dashboard(code, db)
        if r:
            _dash_cache_set(code, r)  # 内部已加锁
            return code, r
        return code, {"error": "该股票暂无特征数据，请确认已加入自选或当日数据已采集", "code": code}
    except Exception as e:
        logger.exception(f"[stock-dashboard-batch] {code} 计算失败: {e}")
        return code, {"error": str(e)[:200], "code": code}


@router.get("/api/stock-dashboard/batch")
async def stock_dashboard_batch(
    codes: str = Query(..., description="逗号分隔的 ts_code 列表，最多 50 只"),
    refresh: bool = Query(False, description="true 时强制重算并刷新缓存（手动重试 / 扫描后拉最新）"),
):
    """批量获取股票决策仪表盘：用于策略中心 / 共振页一次性渲染多只股票。

    返回 {results: {code: dashboard_dict 或 {error: ...}}}，顺序与 codes 一致。
    命中 6h 缓存瞬时返回；未命中部分交线程池并行计算（独立 session，线程安全）。
    """
    code_list = [c.strip() for c in codes.split(',') if c.strip()]
    code_list = code_list[:50]  # 上限 50，防止滥用

    # 1) 先处理 refresh 清理 + 缓存命中（加锁），划分命中 / 未命中
    results = {}
    miss = []
    for code in code_list:
        if refresh:
            _dash_cache_pop(code)
        cached = _dash_cache_get(code)  # 内部已加锁
        if cached is not None:
            results[code] = cached
        else:
            miss.append(code)

    # 2) 未命中部分交给线程池并行计算（独立 DB session，线程安全）
    if miss:
        loop = asyncio.get_running_loop()
        ex = _get_executor()
        futures = [loop.run_in_executor(ex, _compute_one, code) for code in miss]
        for code, r in await asyncio.gather(*futures):
            results[code] = r

    # 3) 按请求顺序组装，保证与 codes 一一对应
    ordered = {c: results.get(c, {"error": "计算未完成", "code": c}) for c in code_list}
    return {"results": ordered, "count": len(ordered)}


@router.get("/api/stock-dashboard/{code}")
async def stock_dashboard(code: str, refresh: bool = Query(False, description="true 时强制重算并刷新缓存")):
    """单个股票决策仪表盘（8维指数 + 操作建议）"""
    # 0) 强制刷新：清掉旧缓存
    if refresh:
        _dash_cache_pop(code)
    # 1) 缓存命中直接返回
    cached = _dash_cache_get(code)
    if cached is not None:
        return cached
    # 2) 缓存未命中，正常计算并写入缓存
    with get_db_session() as db:
        result = _compute_dashboard(code, db)
    if not result:
        return {"error": "该股票暂无特征数据，请确认已加入自选或当日数据已采集", "code": code}
    _dash_cache_set(code, result)
    return result
