#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🐉 青龙 - MA10主升浪回踩策略
从 /Users/gino/Downloads/青龙白虎双策略核心选股代码(1).py 迁移
数据源：新浪API → pytdx（collectors.tdx_collector）

核心逻辑：
1. MA10连续3天向上
2. 近20日累计涨幅 > 30%（超强主升浪）
3. 收盘价 > MA10（不破位）
4. 最低价 ≤ MA10（真回踩）
5. 偏离MA10 < 5%
5维度评分（下影线/涨幅/量比/RSI/偏离度），≥5分入选
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from .baihu_v26 import get_kline_from_tdx, calc_rsi


# ============================================================
# 工具函数
# ============================================================

def calc_ma(kline, day_index, period):
    """计算指定日期的MA均线"""
    closes = []
    for i in range(max(0, day_index - period + 1), day_index + 1):
        closes.append(float(kline[i]['close']))
    return sum(closes) / len(closes) if closes else 0


# ============================================================
# 🐉 青龙 - MA10主升浪回踩策略
# ============================================================

def qinglong_strategy(kline, day_index=-1):
    """
    青龙策略：MA10主升浪回踩
    特点：高弹性，抓翻倍股，89%概率赚20%+

    参数:
        kline: K线数据列表，每个元素是 dict，需包含 close/open/low/high/volume 字段
        day_index: 检查哪一天（默认-1，即最新一天）

    返回:
        符合条件返回评分字典，不符合返回None
    """
    try:
        # ========== 【5个必过硬门槛】 ==========

        # 1. MA10连续3天向上
        ma10_list = []
        for i in range(max(0, day_index - 4), day_index + 1):
            ma10 = calc_ma(kline, i, 10)
            if ma10 > 0:
                ma10_list.append(ma10)

        if len(ma10_list) < 3:
            return None
        if not all(ma10_list[j] < ma10_list[j + 1] for j in range(len(ma10_list) - 3, len(ma10_list) - 1)):
            return None

        # 2. 近20日累计涨幅 > 30%（必须是超强主升浪）
        closes = [float(k['close']) for k in kline[:day_index + 1]]
        if len(closes) < 21:
            return None
        close_20day_ago = closes[-21]
        recent_20day_gain = (closes[-1] - close_20day_ago) / close_20day_ago * 100
        if recent_20day_gain < 30:
            return None

        latest = kline[day_index]
        prev = kline[day_index - 1]

        close = float(latest['close'])
        low = float(latest['low'])
        ma10 = ma10_list[-1]

        # 3. 收盘价 > MA10（不能破位）
        if close <= ma10:
            return None

        # 4. 最低价 ≤ MA10（必须真回踩，不能离太远）
        if low > ma10:
            return None

        # 5. 收盘价偏离MA10 < 5%（更贴近均线）
        deviation = (close - ma10) / ma10 * 100
        if deviation >= 5:
            return None

        # ========== 【其他指标计算】 ==========
        open_p = float(latest['open'])
        prev_close = float(prev['close'])
        volume = float(latest['volume'])

        change_pct = (close - prev_close) / prev_close * 100
        lower_shadow = (min(close, open_p) - low) / prev_close * 100

        rsi = calc_rsi(closes)

        recent_vols = [float(kline[day_index - j]['volume']) for j in range(1, 6)]
        avg_vol = np.mean(recent_vols)
        vol_ratio = (volume / avg_vol * 100) if avg_vol > 0 else 999

        # ========== 【5维度评分系统（满分8分，≥5分入选）】 ==========
        score = 0

        # 1. 下影线 > 0.5%（+2分）
        if lower_shadow > 0.5:
            score += 2

        # 2. 当日涨幅 -2% ~ 4%（+2分）
        if -2 <= change_pct <= 4:
            score += 2

        # 3. 量比 < 100%（+1分）
        if vol_ratio < 100:
            score += 1

        # 4. RSI 30 ~ 65（+1分）
        if 30 <= rsi <= 65:
            score += 1

        # 5. 偏离MA10 0% ~ 3%（+2分）
        if 0 < deviation < 3:
            score += 2

        # 及格线：≥5分
        if score < 5:
            return None

        return {
            'strategy': '青龙',
            'score': score,
            '20day_gain': round(recent_20day_gain, 2),
            'deviation': round(deviation, 2),
            'change_pct': round(change_pct, 2),
            'rsi': round(rsi, 2),
            'vol_ratio': round(vol_ratio, 2),
            'lower_shadow': round(lower_shadow, 2),
            'ma10': round(ma10, 2),
            'close': round(close, 2),
            'date': latest.get('day', ''),
        }
    except Exception:
        return None


# ============================================================
# 批量选股
# ============================================================

def run_qinglong_screen(stock_list, trade_date=None):
    """
    批量执行青龙选股
    参数:
        stock_list: 股票代码列表（支持 'sz301171' 或 '000001.SZ' 格式）
        trade_date: 交易日期（可选，仅用于记录，不影响筛选逻辑）
    返回:
        符合条件的股票结果列表，每个元素含评分字典 + ts_code
    """
    results = []
    for ts_code in stock_list:
        kline = get_kline_from_tdx(ts_code)
        if kline and len(kline) >= 30:
            result = qinglong_strategy(kline)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                results.append(result)
    return results


if __name__ == "__main__":
    print("=" * 80)
    print("🐉 青龙 - MA10主升浪回踩策略 (pytdx版)")
    print("=" * 80)
    sample = ['sz301117']
    hits = run_qinglong_screen(sample)
    for h in hits:
        print(f"✅ {h['ts_code']} 评分{h['score']} 偏离{h['deviation']}% 量比{h['vol_ratio']}%")
