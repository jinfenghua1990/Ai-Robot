#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔥 放量突破策略 (volume_breakout)
核心逻辑：
1. 收盘价突破近 20 日最高价（v1：过于严苛；v2：放宽到近 10 日）
2. 成交量 ≥ 近 5 日均量 × 1.5（v1：2.0；v2：1.5）
3. 涨幅 1% ~ 9%（v1：2~9%；v2：1~9%）
4. MA20 向上
5. 排除一字板

评分（满分 8 分，≥ 4 分入选 v2）：
- 突破强度（+2）：突破幅度 0~5%
- 放量倍数（+2）：vol_ratio ≥ 2.0
- 涨幅健康度（+2）：3~7%
- MA20 趋势（+1）：斜率 > 0
- 突破日数（+1）：突破 10 日新高即可
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import logging
logger = logging.getLogger(__name__)


def volume_breakout_strategy(kline, day_index=-1):
    try:
        if day_index == -1:
            day_index = len(kline) - 1
        if day_index < 0 or day_index >= len(kline):
            return None

        if day_index < 11:
            return None

        latest = kline[day_index]
        prev = kline[day_index - 1] if day_index > 0 else latest
        closes = [float(k['close']) for k in kline[:day_index + 1]]

        close = float(latest['close'])
        open_p = float(latest['open'])
        high = float(latest['high'])
        low = float(latest['low'])
        volume = float(latest['volume'])
        prev_close = float(prev['close'])

        # 1. 收盘价突破近 10 日最高
        high_10d = max(float(k['high']) for k in kline[day_index - 10:day_index])
        if close <= high_10d:
            return None
        # 突破幅度
        breakout_pct = (close - high_10d) / high_10d * 100
        if breakout_pct > 5:
            return None  # 突破过猛易回调

        # 2. 排除一字板
        if high == low and close == open_p:
            return None

        # 3. 涨幅 1~9%
        change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0
        if change_pct < 1 or change_pct > 9:
            return None

        # 4. 成交量 ≥ 近 5 日均量 × 1.5
        recent_vols = [float(kline[day_index - j]['volume']) for j in range(1, 6)]
        avg_vol_5 = np.mean(recent_vols)
        if avg_vol_5 <= 0:
            return None
        vol_ratio = volume / avg_vol_5
        if vol_ratio < 1.5:
            return None

        # 5. MA20 向上
        ma20_now = float(latest.get('ma_price20') or 0)
        if ma20_now <= 0:
            if len(closes) >= 20:
                ma20_now = sum(closes[-20:]) / 20
            else:
                return None
        ma20_prev = sum(closes[-21:-1]) / 20
        if ma20_now <= ma20_prev:
            return None

        # 6. 排除妖股
        if vol_ratio > 8:
            return None

        # 评分
        score = 0
        scores = {}
        if 0 < breakout_pct <= 5:
            score += 2
            scores['breakout'] = 2
        if vol_ratio >= 2.0:
            score += 2
            scores['volume'] = 2
        elif vol_ratio >= 1.5:
            score += 1
            scores['volume'] = 1
        if 3 <= change_pct <= 7:
            score += 2
            scores['change'] = 2
        elif 1 <= change_pct < 3 or 7 < change_pct <= 9:
            score += 1
            scores['change'] = 1
        if ma20_now > ma20_prev:
            score += 1
            scores['ma20'] = 1
        # v2: 突破 10 日新高的额外奖励
        score += 1
        scores['breakout_10d'] = 1

        if score < 4:
            return None

        return {
            'strategy': '放量突破',
            'score': score,
            'breakout_pct': round(breakout_pct, 2),
            'vol_ratio': round(vol_ratio, 2),
            'change_pct': round(change_pct, 2),
            'ma20_now': round(ma20_now, 2),
            'ma20_prev': round(ma20_prev, 2),
            'close': round(close, 2),
            'date': latest.get('day', ''),
        }
    except Exception:
        logger.debug(f"function failed", exc_info=True)
        return None


def run_volume_breakout_screen(stock_list, trade_date=None):
    from .baihu_v26 import get_kline_from_tdx
    results = []
    for ts_code in stock_list:
        kline = get_kline_from_tdx(ts_code)
        if kline and len(kline) >= 30:
            r = volume_breakout_strategy(kline)
            if r:
                r['ts_code'] = ts_code
                if trade_date:
                    r['trade_date'] = trade_date
                results.append(r)
    return results


if __name__ == '__main__':
    print('🔥 放量突破策略 - 单股测试')
    r = run_volume_breakout_screen(['600110.SH'])
    for h in r:
        print(f"  ✅ {h['ts_code']} 评分{h['score']} 突破{h['breakout_pct']}% 量比{h['vol_ratio']}")
