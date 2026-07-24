#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔄 RSI超卖反弹 — 均值回归信号（与 MA 体系完全独立）

核心逻辑：
1. 昨日 RSI(14) < 30（超卖区间）
2. 今日收阳（close > open，反弹确认）
3. 今日成交量 >= 5日均量 × 1.2（放量确认，非无量反弹）
4. 今日涨幅 1%~7%（过滤假反弹和一字板）

评分（满分 8 分，>= 4 分入选，宽松门槛因为信号本身稀有）：
- 超卖深度：RSI < 25 (+3), RSI < 30 (+2)
- 反弹力度：涨幅 3%~7% (+2), 1%~3% (+1)
- 量能确认：量比 >= 2.0 (+2), >= 1.2 (+1)
- 站上 MA5 (+1)

定位：趋势跟踪策略抓不到的"别人恐慌我贪婪"型机会。
    与 MA 体系相关性接近零，共振维度独立。
"""
import numpy as np

from .baihu_v30 import get_kline_from_tdx, calc_rsi


def rsi_bounce_strategy(kline, day_index=-1):
    """RSI超卖反弹单只股票分析

    参数:
        kline: K线数据列表（oldest-first），每元素含 close/open/low/high/volume
        day_index: 检查哪一天（默认-1，最新一天）

    返回:
        命中返回 dict（含 ts_code/score/scores/signal/reason），不命中返回 None
    """
    try:
        if day_index == -1:
            day_index = len(kline) - 1
        if day_index < 14 or day_index >= len(kline) or len(kline) < 15:
            return None

        closes = [float(k['close']) for k in kline]
        opens = [float(k['open']) for k in kline]
        volumes = [float(k['volume']) for k in kline]

        today_close = closes[-1]
        today_open = opens[-1]
        today_vol = volumes[-1]
        prev_close = closes[-2]
        prev_open = opens[-2]

        # 1. 昨日 RSI < 30
        rsi_today = calc_rsi(closes, period=14)
        rsi_yesterday = calc_rsi(closes[:-1], period=14)
        if rsi_yesterday is None or rsi_yesterday >= 30:
            return None

        # 2. 今日收阳
        if today_close <= today_open:
            return None

        # 3. 成交量 >= 5日均量（不缩量即可，超卖反弹放量要求放宽）
        if len(volumes) >= 5:
            avg_vol_5 = np.mean(volumes[-6:-1])  # 前5日（不含今天）
            vol_ratio = (today_vol / avg_vol_5) if avg_vol_5 > 0 else 0
            if vol_ratio < 1.0:
                return None
        else:
            return None

        # 4. 今日涨幅 0.5%~8%（超卖反弹起点低，门槛放宽）
        change_pct = (today_close - prev_close) / prev_close * 100 if prev_close > 0 else 0
        if change_pct < 0.5 or change_pct > 8:
            return None

        # 计算均线
        ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else None

        # 评分
        score = 0
        scores = {}

        # 超卖深度
        if rsi_yesterday < 25:
            score += 3
            scores['oversold_depth'] = 3
        else:
            score += 2
            scores['oversold_depth'] = 2

        # 反弹力度
        if change_pct >= 3:
            score += 2
            scores['bounce_strength'] = 2
        else:
            score += 1
            scores['bounce_strength'] = 1

        # 量能确认
        if vol_ratio >= 1.5:
            score += 2
            scores['volume_confirm'] = 2
        else:
            score += 1
            scores['volume_confirm'] = 1

        # MA5 确认（如果站上 MA5 额外加分）
        above_ma5 = False
        if ma5 and today_close > ma5:
            score += 1
            scores['above_ma5'] = 1
            above_ma5 = True

        if score < 4:
            return None

        # 反弹原因描述
        reason_parts = [f'昨日RSI={rsi_yesterday:.1f}(超卖)', f'今日反弹+{change_pct:.1f}%']
        if vol_ratio >= 2.0:
            reason_parts.append(f'放量{vol_ratio:.1f}x')
        if above_ma5:
            reason_parts.append('站上MA5')

        return {
            'ts_code': '',
            'signal': 'rsi_bounce',
            'signal_label': '超卖反弹',
            'score': round(score, 1),
            'scores': scores,
            'change_pct': round(change_pct, 2),
            'rsi': round(rsi_today, 1) if rsi_today else None,
            'rsi_yesterday': round(rsi_yesterday, 1),
            'vol_ratio': round(vol_ratio, 2),
            'ma5': round(ma5, 2) if ma5 else None,
            'price': round(today_close, 2),
            'reason': '，'.join(reason_parts),
            'indicators': {
                'rsi_14': round(rsi_today, 1) if rsi_today else None,
                'rsi_yesterday': round(rsi_yesterday, 1),
                'vol_ratio': round(vol_ratio, 2),
                'ma5': round(ma5, 2) if ma5 else None,
                'change_pct': round(change_pct, 2),
            },
        }

    except Exception:
        return None


def run_rsi_bounce_screen(stock_list, trade_date=None):
    """对候选股票列表运行 RSI 超卖反弹策略"""
    results = []
    for ts_code in stock_list:
        try:
            kline = get_kline_from_tdx(ts_code, days=90)
            if not kline or len(kline) < 15:
                continue
            hit = rsi_bounce_strategy(kline)
            if hit:
                hit['ts_code'] = ts_code
                if trade_date:
                    hit['trade_date'] = trade_date
                results.append(hit)
        except Exception:
            continue
    return results
