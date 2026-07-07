#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📊 MACD 金叉策略 (macd_golden_cross)
核心逻辑：
1. MACD 金叉：DIF 由下穿 DEA 转为上穿（昨天下穿、今天上穿）
2. 柱状线由负转正或已为正
3. 收盘价站上 MA20
4. MA20 向上

与现有策略差异：
- 白虎/青龙/主升浪都偏"已上涨"型，本策略捕捉"刚启动"型
- DIF/DEA 是中期趋势指标，与 MA 类短期指标互补
- 金叉比"金叉后第 N 天"信号更早

评分（满分 8 分，≥ 5 分入选）：
- 金叉强度（+2）：DIF-DEA 交叉点接近 0
- 柱状线状态（+2）：柱状线 > 0 且增大
- 价格站上 MA20（+1）
- MA20 向上（+1）
- 量能配合（+2）：成交量 ≥ 近 5 日均量 × 1.2
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import logging
logger = logging.getLogger(__name__)


def calc_ema(series, period):
    """计算 EMA（指数移动平均）"""
    if len(series) < period:
        return []
    ema = [sum(series[:period]) / period]
    multiplier = 2 / (period + 1)
    for price in series[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calc_macd(closes, short=12, long_=26, signal=9):
    """计算 MACD（DIF, DEA, HIST）"""
    if len(closes) < long_ + signal:
        return None, None, None
    ema_short = calc_ema(closes, short)
    ema_long = calc_ema(closes, long_)
    # 对齐到 ema_long 的索引
    offset = len(ema_short) - len(ema_long)
    dif = [ema_short[i + offset] - ema_long[i] for i in range(len(ema_long))]
    dea = calc_ema(dif, signal)
    offset2 = len(dif) - len(dea)
    hist = [(dif[i + offset2] - dea[i]) * 2 for i in range(len(dea))]
    return dif, dea, hist


def macd_golden_cross_strategy(kline, day_index=-1):
    try:
        if day_index == -1:
            day_index = len(kline) - 1
        if day_index < 0 or day_index >= len(kline):
            return None

        if day_index < 35:  # 需要 26+9+缓冲
            return None

        closes = [float(k['close']) for k in kline[:day_index + 1]]
        dif, dea, hist = calc_macd(closes)
        if dif is None or len(dif) < 3:
            return None

        latest_close = closes[-1]
        latest = kline[day_index]
        prev = kline[day_index - 1] if day_index > 0 else latest

        # 1. 金叉：昨天 DIF <= DEA，今天 DIF > DEA
        if dif[-2] is None or dea[-2] is None:
            return None
        if not (dif[-2] <= dea[-2] and dif[-1] > dea[-1]):
            return None

        # 2. 柱状线：最近一天 >= 0（如果 hist[-1] < 0 但 DIF>DEA 极弱，丢弃）
        if hist[-1] < 0:
            return None

        # 3. 收盘价站上 MA20
        ma20 = sum(closes[-20:]) / 20
        if latest_close <= ma20:
            return None

        # 4. MA20 向上
        ma20_prev = sum(closes[-21:-1]) / 20
        if ma20 <= ma20_prev:
            return None

        # 5. 量能：今天成交量 >= 近 5 日均量 × 1.2
        volume = float(latest['volume'])
        recent_vols = [float(kline[day_index - j]['volume']) for j in range(1, 6)]
        avg_vol_5 = np.mean(recent_vols) if recent_vols else 0
        if avg_vol_5 <= 0:
            return None
        vol_ratio = volume / avg_vol_5

        # 评分
        score = 0
        scores = {}
        # 金叉强度：DIF-DEA 接近 0 加分
        cross_gap = abs(dif[-1] - dea[-1])
        if cross_gap < 0.05:
            score += 2
            scores['cross'] = 2
        elif cross_gap < 0.15:
            score += 1
            scores['cross'] = 1
        # 柱状线
        if hist[-1] > 0:
            score += 2
            scores['hist'] = 2
        # 价格站上 MA20
        if latest_close > ma20:
            score += 1
            scores['above_ma20'] = 1
        # MA20 向上
        if ma20 > ma20_prev:
            score += 1
            scores['ma20_up'] = 1
        # 量能
        if vol_ratio >= 1.2:
            score += 2
            scores['vol'] = 2
        elif vol_ratio >= 1.0:
            score += 1
            scores['vol'] = 1

        if score < 5:
            return None

        return {
            'strategy': 'MACD金叉',
            'score': score,
            'dif': round(dif[-1], 4),
            'dea': round(dea[-1], 4),
            'hist': round(hist[-1], 4),
            'vol_ratio': round(vol_ratio, 2),
            'ma20': round(ma20, 2),
            'close': round(latest_close, 2),
            'date': latest.get('day', ''),
        }
    except Exception:
        logger.debug(f"function failed", exc_info=True)
        return None


def run_macd_golden_cross_screen(stock_list, trade_date=None):
    from .baihu_v26 import get_kline_from_tdx
    results = []
    for ts_code in stock_list:
        kline = get_kline_from_tdx(ts_code)
        if kline and len(kline) >= 60:
            r = macd_golden_cross_strategy(kline)
            if r:
                r['ts_code'] = ts_code
                if trade_date:
                    r['trade_date'] = trade_date
                results.append(r)
    return results


if __name__ == '__main__':
    print('📊 MACD 金叉策略 - 单股测试')
    r = run_macd_golden_cross_screen(['600110.SH'])
    for h in r:
        print(f"  ✅ {h['ts_code']} 评分{h['score']} DIF={h['dif']} DEA={h['dea']} HIST={h['hist']}")
