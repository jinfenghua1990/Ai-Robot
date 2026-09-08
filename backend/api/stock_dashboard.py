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

数据来源：StockFeaturesDaily + StockFlow + SectorFlow + StockMoneyFlowDetail + StockDailyKline。
历史个股资金评分统一以 StockMoneyFlowDetail 为准；StockFlow 仅承担行情快照、名称与板块归属。
（全部现成，零新增采集）
"""
import asyncio
import logging
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
from zoneinfo import ZoneInfo
from sqlalchemy import func, desc

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from db.session import get_db_session
from typing import Optional
from db.models import (
    StockFeaturesDaily, StockFlow, SectorFlow, StockMoneyFlowDetail, StockDailyKline, Watchlist,
    RealtimeStockFlow, StockMoneyFlowRealtime, RealtimeSectorFlow,
)
from analyzers.stock_scores import calc_technical
from analyzers.strategy_engine import _find_sector_for_stock
from services.indicators import calc_kdj, calc_macd
from utils import should_defer_current_daily_analysis

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


# ===== 沪深300 当日涨跌（强弱对比用） =====
# 复用 index_flow 的 stock_flow 成分股 DB 聚合（纯本地，无外部采集），
# 与页面「指数资金流向 rank」同口径；按交易日固定，缓存 6 小时。
_INDEX_CHG_CACHE = {'ts': 0, 'value': None}
_INDEX_CHG_CACHE_TTL = 21600
_INDEX_CHG_LOCK = threading.Lock()


def _hs300_pct_live_fallback():
    """现场聚合兜底：index_daily 表未就绪时从 stock_flow 实时算沪深300涨幅。"""
    value = None
    try:
        from api.index_flow import MAJOR_INDICES, _resolve_index_members
        idx_def = next(i for i in MAJOR_INDICES if i['ts_code'] == '000300.SH')
        members = _resolve_index_members(idx_def, allow_remote_constituents=False)
        with get_db_session() as db:
            recent_days = [r[0] for r in db.query(StockFlow.trade_date).distinct().order_by(
                StockFlow.trade_date.desc()).limit(8)]
            rows = db.query(StockFlow.trade_date, func.avg(StockFlow.price_chg).label('chg')).filter(
                StockFlow.trade_date.in_(recent_days),
                StockFlow.ts_code.in_(members),
            ).group_by(StockFlow.trade_date).order_by(StockFlow.trade_date.desc()).all()
            for r in rows:
                chg = float(r.chg or 0)
                if abs(chg) > 1e-6:
                    value = round(chg, 2)
                    break
    except Exception as e:
        logger.debug(f'[dashboard] hs300 live fallback error: {e}')
    return value


def _fetch_hs300_pct():
    """沪深300 最近一个有效交易日的涨跌幅（%）。

    常规读 index_daily（每日定时落库，纯 DB 无外部采集）；表未就绪时现场聚合兜底。
    """
    with _INDEX_CHG_LOCK:
        now = _time.time()
        if _INDEX_CHG_CACHE['value'] is not None and now - _INDEX_CHG_CACHE['ts'] < _INDEX_CHG_CACHE_TTL:
            return _INDEX_CHG_CACHE['value']
        value = None
        try:
            from api.index_daily import get_index_daily_pct
            value = get_index_daily_pct('000300.SH')
        except Exception as e:
            logger.debug(f'[dashboard] index_daily read error: {e}')
        if value is None:
            value = _hs300_pct_live_fallback()
        _INDEX_CHG_CACHE['ts'] = now
        _INDEX_CHG_CACHE['value'] = value
        return value


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
        StockDailyKline.high.isnot(None),
        StockDailyKline.low.isnot(None),
        StockDailyKline.close.isnot(None),
    ).order_by(StockDailyKline.trade_date.desc()).limit(60).all()[::-1]

    if len(klines) < 35:  # MACD 最少需要 26+9 个点
        return {'available': False}

    highs = [float(k.high) for k in klines]
    lows = [float(k.low) for k in klines]
    closes = [float(k.close) for k in klines]

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
        StockDailyKline.open.isnot(None),
        StockDailyKline.close.isnot(None),
        StockDailyKline.high.isnot(None),
        StockDailyKline.low.isnot(None),
        StockDailyKline.volume.isnot(None),
    ).order_by(StockDailyKline.trade_date.desc()).limit(150).all()[::-1]

    if len(kline_rows) < 35:
        return {'state': 'unknown', 'klines': []}

    klines = [{
        'date': k.trade_date.strftime('%Y-%m-%d') if hasattr(k.trade_date, 'strftime') else str(k.trade_date),
        'open': float(k.open),
        'close': float(k.close),
        'high': float(k.high),
        'low': float(k.low),
        'volume': float(k.volume),
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


def _optional_float(value):
    return float(value) if value is not None else None


def _optional_int(value):
    return int(value) if value is not None else None


def _round_optional(value, digits: int = 1):
    return round(value, digits) if value is not None else None


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
# sector_strength / noise_ratio 没有对应数据库字段时保持空值。
def _features_from_kline_fallback(ts_code: str, target_date, db) -> Optional[dict]:
    """从 K 线 + 资金流现场合成 features 字典，返回 None 表示 K 线不足。"""
    klines = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
        StockDailyKline.open.isnot(None),
        StockDailyKline.close.isnot(None),
        StockDailyKline.high.isnot(None),
        StockDailyKline.low.isnot(None),
    ).order_by(StockDailyKline.trade_date.desc()).limit(120).all()[::-1]
    if len(klines) < 30:
        return None

    closes = [float(k.close) for k in klines]
    highs = [float(k.high) for k in klines]
    lows = [float(k.low) for k in klines]

    if len(closes) < 30:
        return None

    close = closes[-1]
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else close
    close_vs_ma20 = (close / ma20 - 1) if ma20 > 0 else None
    # MA20 斜率：今日 ma20 vs 5 日前 ma20 的变化率
    if len(closes) >= 25:
        ma20_5d_ago = sum(closes[-25:-5]) / 20
        ma20_slope = (ma20 / ma20_5d_ago - 1) if ma20_5d_ago > 0 else None
    else:
        ma20_slope = None

    # ATR(14)：True Range 14 日平均（range(-14,0) 即为最近 14 个交易日，无需跳过）
    trs = []
    for i in range(-14, 0):
        h = highs[i]
        l = lows[i]
        pc = closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr_14 = sum(trs) / len(trs) if trs else None

    # Volume ratio：今日 vol / 20日均量
    recent_volumes = [k.volume for k in klines[-20:]]
    if len(recent_volumes) == 20 and all(value is not None for value in recent_volumes):
        volumes = [float(value) for value in recent_volumes]
        vol_20_avg = sum(volumes) / 20
        volume_ratio = (volumes[-1] / vol_20_avg) if vol_20_avg > 0 else None
    else:
        volume_ratio = None

    # higher_high / higher_low_flag：今日 high/low 是否创 20 日新高/新低（严格 > / <）
    if len(highs) >= 21:
        previous_high_20 = max(highs[-21:-1])
        previous_low_20 = min(lows[-21:-1])
        higher_high_flag = 1 if highs[-1] > previous_high_20 else 0
        higher_low_flag = 1 if lows[-1] > previous_low_20 else 0
    else:
        higher_high_flag = None
        higher_low_flag = None

    # trend_consistency_score：近 20 日 close > ma20 的占比（0-1）
    if len(closes) >= 20:
        above = sum(1 for i in range(-20, 0) if closes[i] > ma20)
        trend_consistency_score = above / 20
    else:
        trend_consistency_score = None

    # RSI(14)：Wilder 平滑（与 StockFeaturesDaily 同口径：首段 SMA 打底，之后逐日递推平滑）
    rsi_14 = None
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        if len(gains) >= 14:
            avg_gain = sum(gains[:14]) / 14
            avg_loss = sum(losses[:14]) / 14
            for g, l in zip(gains[14:], losses[14:]):
                avg_gain = (avg_gain * 13 + g) / 14
                avg_loss = (avg_loss * 13 + l) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi_14 = 100 - 100 / (1 + rs)
            else:
                rsi_14 = 100 if avg_gain > 0 else 50

    # 资金流连续性：只接受与最近 K 线交易日逐日对齐的 StockFlow。
    # 资金表滞后时不能把旧日资金冒充为当前日资金。
    flows = db.query(StockFlow).filter(
        StockFlow.ts_code == ts_code,
        StockFlow.trade_date <= target_date,
    ).order_by(StockFlow.trade_date.desc()).limit(5).all()
    expected_flow_dates = [k.trade_date for k in klines[-5:]][::-1]
    flow_values = []
    for expected_date, flow in zip(expected_flow_dates, flows):
        if flow.trade_date != expected_date or flow.main_force_inflow is None:
            break
        flow_values.append(float(flow.main_force_inflow))

    def exact_flow_sum(period: int):
        values = flow_values[:period]
        if len(values) < period or any(value is None for value in values):
            return None
        return sum(values)

    inflow_1d = flow_values[0] if flow_values and flow_values[0] is not None else None
    inflow_3d = exact_flow_sum(3)
    inflow_5d = exact_flow_sum(5)
    if not flow_values:
        flow_continuity = None
    else:
        flow_continuity = 0
        for value in flow_values:
            if value > 0:
                flow_continuity += 1
            else:
                break

    return {
        'rsi_14': round(rsi_14, 2) if rsi_14 is not None else None,
        'volume_ratio': round(volume_ratio, 2) if volume_ratio is not None else None,
        'close_vs_ma20': round(close_vs_ma20, 4) if close_vs_ma20 is not None else None,
        'higher_high_flag': higher_high_flag,
        'higher_low_flag': higher_low_flag,
        'trend_consistency_score': round(trend_consistency_score, 2) if trend_consistency_score is not None else None,
        'ma20_slope': round(ma20_slope, 4) if ma20_slope is not None else None,
        'main_net_inflow_1d': inflow_1d,
        'main_net_inflow_3d': inflow_3d,
        'main_net_inflow_5d': inflow_5d,
        'flow_continuity': flow_continuity,
        'sector_strength': None,
        'noise_ratio': None,
        'atr_14': round(atr_14, 4) if atr_14 is not None else None,
        # 同步供 _compute_dashboard 后续用（避免再查一次）
        '_close': close,
    }


def _canonical_money_flow_inputs(ts_code: str, target_date, db, days: int = 5) -> dict:
    """读取同一交易日序列的个股历史资金输入，单位统一为元。

    StockFlow 是东方财富快照表，StockMoneyFlowDetail 是有完整分单明细的日频落库表。
    页面资金明细、机构信号和资金评分必须使用后者，避免同一页面出现正负方向相反的“主力资金”。
    """
    kline_dates = [row[0] for row in db.query(StockDailyKline.trade_date).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
        StockDailyKline.close.isnot(None),
    ).order_by(StockDailyKline.trade_date.desc()).limit(days).all()]
    if not kline_dates:
        return {
            'current': None, 'inflow_3d': None, 'inflow_5d': None,
            'continuity': None, 'detail': None,
        }

    detail_rows = db.query(StockMoneyFlowDetail).filter(
        StockMoneyFlowDetail.ts_code == ts_code,
        StockMoneyFlowDetail.trade_date.in_(kline_dates),
    ).all()
    by_date = {row.trade_date: row for row in detail_rows}
    values = []
    for trade_date in kline_dates:
        detail = by_date.get(trade_date)
        if detail is None or detail.main_net is None:
            break
        values.append(float(detail.main_net))

    def exact_sum(period: int):
        return sum(values[:period]) if len(values) >= period else None

    continuity = None
    if values:
        continuity = 0
        for value in values:
            if value > 0:
                continuity += 1
            else:
                break

    return {
        'current': values[0] if values else None,
        'inflow_3d': exact_sum(3),
        'inflow_5d': exact_sum(5),
        'continuity': continuity,
        'detail': by_date.get(target_date),
    }


# ===== 实时维度计算 =====
def _compute_realtime(ts_code: str, sector: str, db) -> dict:
    """从 RealtimeStockFlow / RealtimeSectorFlow / StockMoneyFlowRealtime 算实时维度分。

    取「最近一个有实时快照的交易日」而非严格今天，使盘后/非交易时段也能看到
    最近一个交易时段的实时数据（避免非交易时段实时列恒为空白）。

    live 标记：仅当快照所属交易日 == 今天 且 当前处于交易时段(09:30-15:00) 时才为 True，
    否则为「上一交易日收盘快照」，前端据此诚实标注，不把历史数据伪装成实时。
    """
    latest_rt = db.query(func.max(RealtimeStockFlow.trade_date)).filter(
        RealtimeStockFlow.ts_code == ts_code
    ).scalar()
    if not latest_rt:
        return {'available': False}
    today = latest_rt

    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    now_date = now.date()
    cur_time = now.time()
    in_session = cur_time >= datetime.strptime('09:30', '%H:%M').time() and \
                 cur_time <= datetime.strptime('15:00', '%H:%M').time()
    live = (today == now_date) and in_session

    rt_flow = db.query(RealtimeStockFlow).filter(
        RealtimeStockFlow.ts_code == ts_code,
        RealtimeStockFlow.trade_date == today,
    ).order_by(RealtimeStockFlow.snapshot_time.desc()).first()

    if not rt_flow:
        return {'available': False}

    rt_pct_chg = float(rt_flow.price_chg) if rt_flow.price_chg is not None else None
    rt_main_force = (
        float(rt_flow.main_force_inflow) * 10000
        if rt_flow.main_force_inflow is not None else None
    )  # 万元→元
    rt_snapshot_time = rt_flow.snapshot_time

    # 机构
    rt_money = db.query(StockMoneyFlowRealtime).filter(
        StockMoneyFlowRealtime.ts_code == ts_code,
        StockMoneyFlowRealtime.trade_date == today,
    ).order_by(StockMoneyFlowRealtime.snapshot_time.desc()).first()

    rt_main_net = float(rt_money.main_net) if rt_money and rt_money.main_net is not None else None

    # 板块
    rt_sector = db.query(RealtimeSectorFlow).filter(
        RealtimeSectorFlow.sector == sector,
        RealtimeSectorFlow.trade_date == today,
    ).order_by(RealtimeSectorFlow.snapshot_time.desc()).first() if sector else None

    rt_sector_net = float(rt_sector.net_flow) if rt_sector and rt_sector.net_flow is not None else None
    rt_sector_rise = float(rt_sector.rise_ratio) if rt_sector and rt_sector.rise_ratio is not None else None

    # ---- 5 个可算维度 ----
    trend_rt = (
        _clamp(50 + rt_pct_chg * (10 if rt_pct_chg >= 0 else 8), 0, 100)
        if rt_pct_chg is not None else None
    )

    if rt_main_force is not None:
        mag_bonus = min(abs(rt_main_force) / 1e8, 3) * 10 if rt_main_force > 0 else \
                    -min(abs(rt_main_force) / 1e8, 2) * 8
        capital_rt = _clamp(50 + mag_bonus, 0, 100)
    else:
        capital_rt = None

    if rt_main_force is not None and rt_sector_net is not None:
        same_dir = (rt_main_force > 0) == (rt_sector_net > 0)
        # 与盘后 resonance 同口径：强同向=75；弱流向(<1e6)无论方向=50；强反向=25
        resonance_rt = 75 if (same_dir and abs(rt_main_force) > 1e6) else \
                       (50 if abs(rt_main_force) <= 1e6 else 25)
    else:
        resonance_rt = None

    relative_rt = (
        _clamp(50 + (rt_pct_chg - rt_sector_rise) * 12, 0, 100)
        if rt_pct_chg is not None and rt_sector_rise is not None else None
    )

    inst_rt = _clamp(
        50 + (rt_main_net > 0) * 20 + min(abs(rt_main_net) / 5e7 * 15, 15) * (1 if rt_main_net > 0 else -1),
        0, 100,
    ) if rt_main_net is not None else None

    # ---- 当日分时序列（真正的实时时间维度）：价格 + 主力净流入随快照时间变化 ----
    rt_series = db.query(RealtimeStockFlow).filter(
        RealtimeStockFlow.ts_code == ts_code,
        RealtimeStockFlow.trade_date == today,
    ).order_by(RealtimeStockFlow.snapshot_time.asc()).all()
    intraday = [{
        't': r.snapshot_time.strftime('%H:%M') if r.snapshot_time else None,
        'price': round(float(r.price), 2) if r.price is not None else None,
        'pct_chg': round(float(r.price_chg), 2) if r.price_chg is not None else None,
        'main_force': round(float(r.main_force_inflow) * 10000) if r.main_force_inflow is not None else None,  # 万元→元
    } for r in rt_series]

    # ---- 从日内价格序列补齐剩余 3 个维度，使盘后/实时左右 8 维对齐 ----
    prices = [float(r.price) for r in rt_series if r.price is not None]
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
            volatility_rt = None

        # 回撤状态：当前价相对日内高点的回撤
        if rt_high > 0:
            rt_dd = (rt_current - rt_high) / rt_high * 100  # 负值=回撤
            drawdown_rt = _clamp(100 + rt_dd * 8, 0, 100)
        else:
            drawdown_rt = None
    else:
        volatility_rt = None
        drawdown_rt = None

    # 实时快照没有成交量比，量能健康度保持空值，不能用资金流强度冒充成交量。
    volume_rt = None

    dimensions = {
        'trend_strength': trend_rt,
        'capital_momentum': capital_rt,
        'sector_resonance': resonance_rt,
        'relative_strength': relative_rt,
        'volume_health': volume_rt,
        'volatility_health': volatility_rt,
        'drawdown_status': drawdown_rt,
        'institution_signal': inst_rt,
    }
    missing_dimensions = [key for key, value in dimensions.items() if value is None]

    return {
        'available': True,
        'live': live,
        # 三种状态，供前端诚实标注：
        #   live         —— 今天盘中且处于交易时段，实时数据滚动更新
        #   closed_today —— 今天有实时数据但已收盘（或尚未开盘前），定格在今天最后 1 分钟快照，
        #                   即「盘后」视图，一直挂到下一个开盘才重新计算
        #   previous     —— 今天尚无任何实时数据（如周末/休市/开盘前），回退到最近一个交易日
        'mode': 'live' if live else ('closed_today' if today == now_date else 'previous'),
        'date': today.isoformat(),
        'snapshot_time': rt_snapshot_time.strftime('%Y-%m-%dT%H:%M') if rt_snapshot_time else None,
        'status': 'PARTIAL' if missing_dimensions else 'READY',
        'source': 'database',
        'missing_dimensions': missing_dimensions,
        'trend_strength': round(trend_rt, 1) if trend_rt is not None else None,
        'capital_momentum': round(capital_rt, 1) if capital_rt is not None else None,
        'sector_resonance': round(resonance_rt, 1) if resonance_rt is not None else None,
        'relative_strength': round(relative_rt, 1) if relative_rt is not None else None,
        'volume_health': None,
        'volatility_health': round(volatility_rt, 1) if volatility_rt is not None else None,
        'drawdown_status': round(drawdown_rt, 1) if drawdown_rt is not None else None,
        'institution_signal': round(inst_rt, 1) if inst_rt is not None else None,
        'price_chg': round(rt_pct_chg, 2) if rt_pct_chg is not None else None,
        # 资金流向拆解（实时端仅主力/散户/板块有，4 档拆解实时暂无）
        'main_net': round(rt_main_net) if rt_main_net is not None else None,
        'retail_net': round(float(rt_money.retail_net)) if rt_money and rt_money.retail_net is not None else None,
        'sector_net': round(rt_sector_net * 10000) if rt_sector_net is not None else None,  # 万元→元
        'sector_rise': round(rt_sector_rise, 2) if rt_sector_rise is not None else None,  # 板块实时涨幅%（供前端「个股 vs 板块」对照）
        # 当日分时序列（真实时间维度）
        'intraday': intraday,
    }


# ===== 主力净流入累计（多周期） =====
def _compute_cumulative(ts_code: str, sector: str, db, target_date, periods=(1, 2, 3, 5, 10, 20)) -> dict:
    """按日K交易日序列累加主力净流入（个股用 main_net，板块用 net_flow），单位元。

    缺任一对应交易日即返回 None：不能把“最近 N 个有资金数据的日期”伪装成“近 N 日”。
    """
    max_p = max(periods)

    expected_dates = [row[0] for row in db.query(StockDailyKline.trade_date).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
        StockDailyKline.close.isnot(None),
    ).order_by(StockDailyKline.trade_date.desc()).limit(max_p).all()]

    stock_rows = db.query(StockMoneyFlowDetail).filter(
        StockMoneyFlowDetail.ts_code == ts_code,
        StockMoneyFlowDetail.trade_date.in_(expected_dates),
    ).all() if expected_dates else []
    stock_by_date = {row.trade_date: _optional_float(row.main_net) for row in stock_rows}

    def exact_sum(values_by_date: dict, period: int):
        dates = expected_dates[:period]
        if len(dates) < period:
            return None
        values = [values_by_date.get(trade_date) for trade_date in dates]
        return round(sum(values)) if all(value is not None for value in values) else None

    stock = {period: exact_sum(stock_by_date, period) for period in periods}

    sector_cum = {}
    if sector and expected_dates:
        sector_rows = db.query(SectorFlow).filter(
            SectorFlow.sector == sector,
            SectorFlow.trade_date.in_(expected_dates),
        ).all()
        # SectorFlow.net_flow 存储单位为万元；接口统一返回元。
        sector_by_date = {
            row.trade_date: (_optional_float(row.net_flow) * 10000 if row.net_flow is not None else None)
            for row in sector_rows
        }
        sector_cum = {period: exact_sum(sector_by_date, period) for period in periods}
    else:
        sector_cum = {period: None for period in periods}

    return {'periods': list(periods), 'stock': stock, 'sector': sector_cum}


def _compute_sector_rotation(
    sector: str,
    db,
    target_date,
    ts_code: Optional[str] = None,
    lookback_days: int = 10,
) -> Optional[dict]:
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

    # 以当前个股的日 K 交易日序列为准。若板块缺某天，不能把较早记录挤进来伪装成“近 N 日”。
    expected_dates = []
    if ts_code:
        expected_dates = [row[0] for row in db.query(StockDailyKline.trade_date).filter(
            StockDailyKline.ts_code == ts_code,
            StockDailyKline.trade_date <= target_date,
            StockDailyKline.close.isnot(None),
        ).order_by(StockDailyKline.trade_date.desc()).limit(lookback_days).all()]

    if expected_dates:
        sector_rows = db.query(SectorFlow).filter(
            SectorFlow.sector == sector,
            SectorFlow.trade_date.in_(expected_dates),
        ).all()
        by_date = {row.trade_date: row for row in sector_rows}
        missing_dates = [trade_date for trade_date in expected_dates if trade_date not in by_date]
        if missing_dates:
            return {
                'status': 'PARTIAL',
                'source': 'database',
                'data_as_of': target_date.isoformat(),
                'coverage_days': len(sector_rows),
                'lookback_days': len(expected_dates),
                'missing_dates': [trade_date.isoformat() for trade_date in missing_dates],
                'rotation_signal': '板块资金数据不足',
                'rotation_color': '#94a3b8',
                'rotation_icon': '⏳',
                'rotation_detail': f'缺少 {len(missing_dates)} 个对应交易日，未生成轮动结论',
                'days_to_buy': None,
            }
        rows = [by_date[trade_date] for trade_date in expected_dates]
    else:
        # 兼容内部直接调用；主页面始终传 ts_code，因此不会走到这个分支。
        rows = db.query(SectorFlow).filter(
            SectorFlow.sector == sector,
            SectorFlow.trade_date <= target_date,
        ).order_by(SectorFlow.trade_date.desc()).limit(lookback_days).all()

    if not rows:
        return None

    # rows[0] = 今日，rows[1] = 昨日，...
    today = rows[0]
    net_flows = [float(r.net_flow) if r.net_flow is not None else None for r in rows]  # 万元
    heat_scores = [float(r.heat_score) if r.heat_score is not None else None for r in rows]
    leader_stocks = [r.leader_stock for r in rows]
    leader_strengths = [float(r.leader_strength) if r.leader_strength is not None else None for r in rows]
    avg_chgs = [float(r.avg_chg) if r.avg_chg is not None else None for r in rows]

    if any(value is None for value in net_flows):
        return {
            'status': 'PARTIAL',
            'source': 'database',
            'data_as_of': today.trade_date.isoformat(),
            'rotation_signal': '资金流数据不足',
            'rotation_color': '#94a3b8',
            'rotation_icon': '⏳',
            'rotation_detail': '数据库存在空值，未生成轮动结论',
            'days_to_buy': None,
        }

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
    cumulative_chg_5d = round(sum(avg_chgs[:5]), 2) if len(avg_chgs) >= 5 and all(v is not None for v in avg_chgs[:5]) else None
    cumulative_chg_10d = round(sum(avg_chgs[:10]), 2) if len(avg_chgs) >= 10 and all(v is not None for v in avg_chgs[:10]) else None

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
    # 详情必须描述当前连续方向；累计值只说明最近窗口的总体结果，不能反过来决定“流入/流出”。
    if consecutive_inflow_days:
        flow_direction = '流入'
        flow_days = consecutive_inflow_days
    elif consecutive_outflow_days:
        flow_direction = '流出'
        flow_days = consecutive_outflow_days
    else:
        flow_direction = '中性'
        flow_days = 0
    rotation_detail = f'{flow_days}天{flow_direction} · 近{len(rows)}日累计{cum_flow_str}'

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
        # 单日回流不足以反转窗口总体流出，文案必须把两者区分开。
        if cumulative_net_flow < 0:
            rotation_signal = '单日回流·仍待确认'
            rotation_color = '#eab308'
            rotation_icon = '👀'
        else:
            rotation_signal = '资金流入·观察'
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
        # 与单日回流对称：总体仍流入时不能直接写成撤退。
        if cumulative_net_flow > 0:
            rotation_signal = '单日流出·分歧观察'
            rotation_color = '#eab308'
            rotation_icon = '👀'
        else:
            rotation_signal = '资金流出·谨慎'
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
        'status': 'READY' if len(rows) >= lookback_days else 'PARTIAL',
        'source': 'database',
        'data_as_of': today.trade_date.isoformat(),
        'coverage_days': len(rows),
        'lookback_days': lookback_days,
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
def _daily_analysis_inputs_ready(code6: str, ts_code: str, target_date, db) -> bool:
    """日度评分所需的特征和分单资金是否已按同一交易日落库。"""
    date_str = target_date.strftime('%Y%m%d')
    feature_ready = db.query(StockFeaturesDaily.id).filter(
        StockFeaturesDaily.stock_code == code6,
        StockFeaturesDaily.trade_date == date_str,
    ).first() is not None
    money_ready = db.query(StockMoneyFlowDetail.id).filter(
        StockMoneyFlowDetail.ts_code == ts_code,
        StockMoneyFlowDetail.trade_date == target_date,
    ).first() is not None
    return feature_ready and money_ready


def _fetch_sector_peers(sector: str, current_code6: str, db, limit: int = 8) -> list:
    """全市场同板块标的（复用库内 stock_flow 板块映射，纯 DB，无外部请求）。

    在最新一个有效交易日里，从 stock_flow 查板块相同、但非当前股的股票，
    剔除 price_chg 为空的行，按涨幅降序取前 limit 只。
    返回 [{code, name, chg}]。
    """
    if not sector:
        return []
    try:
        rows = db.query(StockFlow).filter(
            StockFlow.sector == sector,
            StockFlow.ts_code != f'{current_code6}.SH',
            StockFlow.ts_code != f'{current_code6}.SZ',
            StockFlow.ts_code != f'{current_code6}.BJ',
        ).order_by(StockFlow.trade_date.desc(), StockFlow.price_chg.desc()).all()
    except Exception as e:
        logger.warning(f'[dashboard] sector peers query error: {e}')
        return []
    peers = []
    seen_date = None
    for r in rows:
        if seen_date is None:
            seen_date = r.trade_date
        elif r.trade_date != seen_date:
            break  # 只取最新一个交易日
        if r.price_chg is None:
            continue
        peers.append({
            'code': r.ts_code.split('.')[0],
            'name': r.name or r.ts_code.split('.')[0],
            'chg': float(r.price_chg),
        })
        if len(peers) >= limit:
            break
    return peers


def _compute_dashboard(code: str, db) -> Optional[dict]:
    """核心计算——单只股票的 8 维指数 + 操作建议"""
    # 容错：剥掉 ts_code 后缀（.SZ/.SH/.BJ/.sh/.sz/.bj），兼容前端传入 6位或 9位
    # stock_features_daily.stock_code 与 stock_flow 的 LIKE 'XXX.%' 都按 6 位存
    code6 = code.split('.')[0] if code else ''
    if not code6:
        return None

    # 交易日以有效日线为准。StockFlow 可能比日线迟一批入库，不能以它决定整页日期，
    # 否则会把 8/24 的评分、8/25 的价位和盘中报价混在同一个页面。
    latest_kline = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code.like(f'{code6}.%'),
        StockDailyKline.close.isnot(None),
        StockDailyKline.close > 0,
    ).order_by(StockDailyKline.trade_date.desc()).first()
    latest_flow = db.query(StockFlow).filter(
        StockFlow.ts_code.like(f'{code6}.%')
    ).order_by(StockFlow.trade_date.desc()).first()
    if latest_kline:
        target_date = latest_kline.trade_date
        ts_code = latest_kline.ts_code
        # 当日盘中 K 线只是实时采集过程中的半成品。只有特征和日资金明细
        # 同日落库后才可以进入评分；否则始终保留上一交易日的完整分析。
        if should_defer_current_daily_analysis(
            target_date,
            _daily_analysis_inputs_ready(code6, ts_code, target_date, db),
        ):
            prior_kline = db.query(StockDailyKline).filter(
                StockDailyKline.ts_code == ts_code,
                StockDailyKline.trade_date < target_date,
                StockDailyKline.close.isnot(None),
                StockDailyKline.close > 0,
            ).order_by(StockDailyKline.trade_date.desc()).first()
            if prior_kline:
                target_date = prior_kline.trade_date
    elif latest_flow:
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

    # 指标数据口径：'features_daily'(精确入库) / 'kline_fallback'(K线现场近似)
    metric_source = 'features_daily'
    if feat:
        features = _features_to_dict(feat)
        cv = _optional_float(feat.close_vs_ma20)
        tc = _optional_float(feat.trend_consistency_score)
        hh = _optional_int(feat.higher_high_flag)
        rsi = _optional_float(feat.rsi_14)
        close = _optional_float(feat.close)
        atr = _optional_float(feat.atr_14)
        vr = _optional_float(feat.volume_ratio)
    else:
        # 兜底：从 K 线 + 资金流现场算近似 features
        metric_source = 'kline_fallback'
        kline_feats = _features_from_kline_fallback(ts_code, target_date, db)
        if not kline_feats:
            return None
        features = {k: v for k, v in kline_feats.items() if not k.startswith('_')}
        cv = _optional_float(features.get('close_vs_ma20'))
        tc = _optional_float(features.get('trend_consistency_score'))
        hh = _optional_int(features.get('higher_high_flag'))
        rsi = _optional_float(features.get('rsi_14'))
        close = _optional_float(kline_feats.get('_close'))
        atr = _optional_float(features.get('atr_14'))
        vr = _optional_float(features.get('volume_ratio'))
        logger.info(f"[stock_dashboard] {ts_code} features_daily 缺失，使用数据库 K 线计算")

    # StockFlow 只用于板块、名称和日行情。历史资金分数统一取分单明细表，
    # 与页面中的“个股资金明细”和机构信号保持同一条数据库口径。
    flow = db.query(StockFlow).filter(
        StockFlow.trade_date == target_date,
    ).filter(StockFlow.ts_code == ts_code).first()
    # 仅同日资金流可进入资金、板块评分；旧行只用来回填名称/板块归属。
    flow_reference = flow or latest_flow
    watchlist_name = db.query(Watchlist.stock_name).filter(
        Watchlist.stock_code == code6,
        Watchlist.stock_name.isnot(None),
    ).scalar()

    # 板块归属：复用 strategy_engine 的解析（从 stock_flow 取最近一个非空 sector），
    # 与顶部 sectorTrend 同口径；最新行 sector 为空时也能正确回退，避免板块名对不上导致查不到。
    sector = _find_sector_for_stock(db, ts_code) or (flow_reference.sector if flow_reference else '') or ''
    canonical_flow = _canonical_money_flow_inputs(ts_code, target_date, db)
    inst = canonical_flow['detail']
    main_inflow = canonical_flow['current']
    inflow_3d = canonical_flow['inflow_3d']
    flow_cont = canonical_flow['continuity']
    features = {
        **features,
        'main_net_inflow_1d': main_inflow,
        'main_net_inflow_3d': inflow_3d,
        'main_net_inflow_5d': canonical_flow['inflow_5d'],
        'flow_continuity': flow_cont,
    }
    flow_price = _optional_float(flow.price) if flow else None
    latest_kline = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
        StockDailyKline.close.isnot(None),
        StockDailyKline.close > 0,
    ).order_by(StockDailyKline.trade_date.desc()).first()
    kline_price = _optional_float(latest_kline.close) if latest_kline else None
    kline_change = _optional_float(latest_kline.pct_chg) if latest_kline else None
    # StockFlow 某些批次的行情列会整批写成 0，但资金流列仍有效。
    # 价格无效时只在数据库内部回退到同日/最近日 K 线。
    price = flow_price if flow_price is not None and flow_price > 0 else (kline_price or close)
    own_chg = (
        _optional_float(flow.price_chg)
        if flow is not None and flow_price is not None and flow_price > 0 else kline_change
    )

    # calc_technical（复用现有技术形态评分）
    technical_inputs = (
        hh,
        features.get('higher_low_flag'),
        tc,
        cv,
        features.get('ma20_slope'),
        rsi,
        vr,
    )
    technical = calc_technical(features) if all(value is not None for value in technical_inputs) else None
    tech_score = (technical or {}).get('score')

    # 1. 趋势强度 0-100
    trend_strength = (
        _clamp(
            tech_score * 0.5 + (cv * 200 + 50) * 0.3 + tc * 100 * 0.2,
            0, 100,
        )
        if None not in (tech_score, cv, tc) else None
    )

    # 2. 资金动能 0-100
    if None not in (main_inflow, flow_cont, inflow_3d):
        mag_bonus = min(abs(main_inflow) / 1e8, 3) * 10 if main_inflow > 0 else \
                    -min(abs(main_inflow) / 1e8, 2) * 8
        capital_momentum = _clamp(
            50 + mag_bonus + flow_cont * 5 + (inflow_3d > 0) * 10,
            0, 100,
        )
    else:
        capital_momentum = None

    # 3. 板块共振 0-100
    # 板块净流入：与顶部 sectorTrend.total_net_flow 完全同口径 —— 近 7 日 SectorFlow.net_flow 累加
    # （strategy_engine._get_sector_trend 即 limit(7) 后 sum(net_flows)）
    sector_dates = [
        row[0] for row in db.query(StockDailyKline.trade_date).filter(
            StockDailyKline.ts_code == ts_code,
            StockDailyKline.trade_date <= target_date,
            StockDailyKline.close.isnot(None),
        ).order_by(StockDailyKline.trade_date.desc()).limit(7).all()
    ]
    srows = db.query(SectorFlow).filter(
        SectorFlow.sector == sector,
        SectorFlow.trade_date.in_(sector_dates),
    ).order_by(SectorFlow.trade_date.desc()).all() if sector and sector_dates else []
    sector_row_dates = [row.trade_date for row in srows]
    sector_missing_fields = sorted({
        field for row in srows for field in ('net_flow', 'avg_chg', 'rise_ratio', 'heat_score')
        if getattr(row, field) is None
    })
    sector_ready = (
        bool(sector_dates) and sector_row_dates == sector_dates and not sector_missing_fields
    )
    # SectorFlow.net_flow 存万元，接口契约（main_net_cumulative 等同接口）统一返回元
    sector_net = (
        float(sum(row.net_flow for row in srows) * 10000) if sector_ready else None
    )
    # 单日板块概览必须与个股目标交易日相同，禁止回退到旧日期参与评分。
    sf = srows[0] if sector_ready else None
    sector_avg_chg = _optional_float(sf.avg_chg) if sf else None
    sector_limit_up = _optional_int(sf.limit_up_count) if sf else None
    if main_inflow is not None and sector_net is not None:
        same_direction = (main_inflow > 0) == (sector_net > 0)
        resonance = 75 if (same_direction and abs(main_inflow) > 1e6) else \
                    (50 if abs(main_inflow) <= 1e6 else 25)
    else:
        resonance = None

    # 4. 量能健康度 0-100
    if vr is None:
        volume_health = None
    elif 0.8 <= vr <= 2.5:
        volume_health = 85
    elif 0.5 <= vr <= 3.0:
        volume_health = 60
    else:
        volume_health = 35

    # 5. 波动健康度 0-100
    if close is not None and atr is not None and close > 0 and atr > 0:
        vh_pct = atr / close * 100
        if 1.0 <= vh_pct <= 5.0:
            volatility_health = 80
        elif 0.5 <= vh_pct <= 8.0:
            volatility_health = 60
        else:
            volatility_health = 35
    else:
        volatility_health = None

    # 6. 相对强度 0-100（个股涨幅 vs 板块平均涨幅）
    relative_strength = (
        _clamp(50 + (own_chg - sector_avg_chg) * 12, 0, 100)
        if own_chg is not None and sector_avg_chg is not None else None
    )

    # 7. 回撤状态 0-100
    klines = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code == ts_code,
        StockDailyKline.trade_date <= target_date,
        StockDailyKline.high.isnot(None),
    ).order_by(StockDailyKline.trade_date.desc()).limit(20).all()
    if klines and close is not None:
        n_high = max(float(k.high) for k in klines)
        dd = (close - n_high) / n_high * 100 if n_high > 0 else None
    else:
        dd = None
    drawdown_status = _clamp(100 + dd * 8, 0, 100) if dd is not None else None

    # 8. 机构信号 0-100
    inst_detail = {
        'has_data': False,
        'status': 'MISSING', 'source': 'database',
        'super_large_net': None, 'large_net': None, 'medium_net': None,
        'small_net': None, 'tiny_net': None,
        'main_net': None, 'main_buy': None, 'main_sell': None,
        'retail_net': None, 'retail_buy': None, 'retail_sell': None,
    }
    if inst:
        super_large = _optional_float(inst.super_large_net)
        large = _optional_float(inst.large_net)
        medium = _optional_float(inst.medium_net)
        small = _optional_float(inst.small_net)
        tiny = _optional_float(inst.tiny_net)
        mn = _optional_float(inst.main_net)
        inst_score = (
            _clamp(
                50 + (super_large > 0) * 20 + (mn > 0) * 10 +
                min(abs(super_large) / 5e7 * 15, 15) * (1 if super_large > 0 else -1),
                0, 100,
            )
            if super_large is not None and mn is not None else None
        )
        inst_detail = {
            'has_data': True,
            'status': 'READY' if all(value is not None for value in (
                inst.super_large_net, inst.large_net, inst.medium_net,
                inst.small_net, inst.tiny_net, inst.main_net,
            )) else 'PARTIAL',
            'source': 'database',
            'super_large_net': super_large,
            'large_net': large,
            'medium_net': medium,
            'small_net': small,
            'tiny_net': tiny,
            'main_net': mn,
            'main_buy': _optional_float(inst.main_buy),
            'main_sell': _optional_float(inst.main_sell),
            'retail_net': _optional_float(inst.retail_net),
            'retail_buy': _optional_float(inst.retail_buy),
            'retail_sell': _optional_float(inst.retail_sell),
        }
    else:
        inst_score = None

    # ===== 风险等级（独立反向维：分数越高越危险，不并入 higher=better 的综合分）=====
    risk = {'has_data': False, 'status': 'MISSING', 'score': None, 'level': None, 'note': None}
    if close is not None and atr is not None and close > 0:
        atr_pct = atr / close * 100
        vol_risk = _clamp((atr_pct - 0.5) / 9.5 * 100)
        noise = features.get('noise_ratio')
        if noise is not None:
            risk['score'] = round(vol_risk * 0.6 + _clamp(noise / 3 * 100) * 0.4)
            risk['status'] = 'READY'
        else:
            risk['score'] = round(vol_risk)
            risk['status'] = 'PARTIAL'
            risk['note'] = '噪声比暂无，风险仅按波动评估'
        rs = risk['score']
        risk['level'] = '安全' if rs < 30 else '中等' if rs < 50 else '偏高' if rs < 70 else '高危'
        risk['has_data'] = True

    # ===== 操作建议标签 =====
    dimensions = {
        'trend_strength': trend_strength,
        'capital_momentum': capital_momentum,
        'sector_resonance': resonance,
        'volume_health': volume_health,
        'volatility_health': volatility_health,
        'relative_strength': relative_strength,
        'drawdown_status': drawdown_status,
        'institution_signal': inst_score,
    }
    missing_dimensions = [key for key, value in dimensions.items() if value is None]
    if missing_dimensions:
        overall_score = None
        action_label = '数据不足'
        action_color = '#94a3b8'
    else:
        # 8 维加权综合分：突出趋势/资金/共振/回撤四主维，量能/波动/机构轻权重。
        # 建议标签与综合分同一口径，消除“分数高却建议观望”的观感矛盾。
        W = {
            'trend_strength': 0.20, 'capital_momentum': 0.20, 'sector_resonance': 0.15,
            'relative_strength': 0.10, 'volume_health': 0.05, 'volatility_health': 0.05,
            'drawdown_status': 0.15, 'institution_signal': 0.10,
        }
        overall_score = round(sum(dimensions[k] * W[k] for k in dimensions), 1)
        if trend_strength >= 60 and capital_momentum >= 50 and resonance >= 50 and drawdown_status >= 60:
            action_label = '可持有 / 加仓'
            action_color = '#22c55e'
        elif overall_score >= 55:
            action_label = '观望'
            action_color = '#eab308'
        elif overall_score >= 40:
            action_label = '减仓观察'
            action_color = '#f97316'
        else:
            action_label = '远离'
            action_color = '#ef4444'

    return {
        'status': 'PARTIAL' if missing_dimensions else 'READY',
        'source': 'database',
        'data_as_of': target_date.isoformat(),
        'missing_dimensions': missing_dimensions,
        'trend_strength': _round_optional(trend_strength),
        'capital_momentum': _round_optional(capital_momentum),
        'sector_resonance': _round_optional(resonance),
        'volume_health': _round_optional(volume_health),
        'volatility_health': _round_optional(volatility_health),
        'relative_strength': _round_optional(relative_strength),
        'drawdown_status': _round_optional(drawdown_status),
        'institution_signal': _round_optional(inst_score),
        'overall_score': overall_score,  # 8 维加权综合分，与建议标签同口径
        'action_label': action_label,
        'action_color': action_color,
        'metric_source': metric_source,   # 'features_daily' | 'kline_fallback'（K线近似）
        'risk': risk,
        'index_chg': _fetch_hs300_pct(),  # 沪深300 当日涨跌幅（%），强弱对比用；从 stock_flow DB 聚合
        'sector_flow': {
            'sector': sector,
            'source': 'database',
            'status': (
                'READY' if sector_ready else
                'PARTIAL' if sector_missing_fields else
                'STALE' if srows else 'MISSING'
            ),
            'data_as_of': srows[0].trade_date.isoformat() if srows else None,
            'expected_data_as_of': target_date.isoformat(),
            'coverage': {
                'available_periods': len(srows),
                'required_periods': len(sector_dates),
            },
            'missing_fields': sector_missing_fields,
            'net_flow': sector_net,
            'avg_chg': sector_avg_chg,
            'limit_up_count': sector_limit_up,
            'rise_ratio': float(sf.rise_ratio) if sf and sf.rise_ratio is not None else None,
            'leader_stock': sf.leader_stock if sf else None,
            'leader_strength': float(sf.leader_strength) if sf and sf.leader_strength is not None else None,
            'heat_score': float(sf.heat_score) if sf and sf.heat_score is not None else None,
        },
        'institution_flow': inst_detail,
        'realtime': _compute_realtime(ts_code, sector, db),
        'main_net_cumulative': _compute_cumulative(ts_code, sector, db, target_date),
        'sector_rotation': _compute_sector_rotation(sector, db, target_date, ts_code=ts_code),
        'technical_indicators': _compute_technical_indicators(ts_code, db, target_date),
        'bs_interval': _compute_bs_interval(ts_code, price, db, target_date),
        'features': features,
        'quote': {
            'price': price,
            'change': own_chg,
            'name': (flow_reference.name if flow_reference else None) or watchlist_name or code6,
            'source': 'database',
            'upstream_source': 'stock_flow' if flow is not None and flow_price is not None and flow_price > 0 else 'stock_daily_kline',
            'status': 'READY' if price is not None and own_chg is not None else 'PARTIAL',
        },
        'date': target_date.isoformat(),
        'code': code,
        'sector_peers': _fetch_sector_peers(sector, code6, db),
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
def stock_dashboard(code: str, refresh: bool = Query(False, description="true 时强制重算并刷新缓存")):
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
