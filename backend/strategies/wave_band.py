#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌊 波段信号 - MA多头排列 + RSI + 量比 买卖点策略
迁移自 hermes-cockpit wave_signal.py，适配 9000 策略体系

核心逻辑：
  buy1: 多头排列(收盘>MA5>MA10>MA20) + 回踩MA10(±3%) + 缩量(量比<1.5) + RSI6<70
  buy2: 放量突破MA20(+5%) + 量比>1.5 + 涨幅>3%
  sell:  单日跌幅<-5% / RSI6>75+跌破MA5 / 跌破MA10×97%
  hold:  其他

数据源：pytdx（collectors.tdx_collector），复用 baihu_v26 的 get_kline_from_tdx / calc_rsi
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .baihu_v26 import get_kline_from_tdx, calc_rsi
import logging
logger = logging.getLogger(__name__)


# ============================================================
# 工具函数
# ============================================================

def _compute_ma(prices, window):
    """计算最近一个交易日的 MA"""
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def _compute_vol_ratio(vols):
    """量比 = 今日量 / 5日均量"""
    if len(vols) < 6:
        return 0.0
    avg_vol_5 = sum(vols[-6:-1]) / 5
    return (vols[-1] / avg_vol_5) if avg_vol_5 > 0 else 0.0


# ============================================================
# 🌊 波段信号 - 单股判定
# ============================================================

def wave_band_strategy(kline):
    """
    波段信号策略：MA+RSI+量比 买卖点判定

    参数:
        kline: K线数据列表（oldest-first），每个元素含 close/volume 字段

    返回:
        buy 信号返回评分字典，sell/hold 返回 None（选股只取 buy）
        sell 信号通过 exit_signal 字段标记
    """
    try:
        if not kline or len(kline) < 21:
            return None

        closes = [float(k['close']) for k in kline]
        vols = [float(k.get('volume', 0)) for k in kline]
        last_close = closes[-1]
        last_vol = vols[-1]

        ma5 = _compute_ma(closes, 5)
        ma10 = _compute_ma(closes, 10)
        ma20 = _compute_ma(closes, 20)
        rsi6 = calc_rsi(closes, period=6)
        change_pct = ((last_close - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0
        vol_ratio = _compute_vol_ratio(vols)

        if ma5 is None or ma10 is None or ma20 is None:
            return None

        # ── 信号判定 ──────────────────────────────────────────────
        signal = "hold"
        reason = ""
        confidence = 50.0

        # 卖出条件（优先级高）
        if change_pct < -5:
            signal = "sell"
            reason = f"单日跌幅 {change_pct:.2f}%，触发止损"
            confidence = 90.0
        elif rsi6 is not None and rsi6 > 75 and last_close < ma5:
            signal = "sell"
            reason = f"RSI6={rsi6:.1f}>75 + 跌破MA5，短线见顶"
            confidence = 75.0
        elif last_close < ma10 * 0.97:
            signal = "sell"
            reason = f"收盘 {last_close:.2f} 跌破MA10×97%({ma10:.2f})，趋势走坏"
            confidence = 70.0
        # 买入条件1：多头排列 + 回踩MA10缩量
        elif (
            last_close > ma5 > ma10 > ma20
            and rsi6 is not None and rsi6 < 70
            and 0.97 < (last_close / ma10) < 1.03  # 回踩MA10 ±3%
            and vol_ratio < 1.5  # 缩量
        ):
            signal = "buy"
            reason = f"多头排列 + 回踩MA10({ma10:.2f})缩量，RSI6={rsi6:.1f}"
            confidence = 75.0
        # 买入条件2：放量突破MA20
        elif (
            ma5 > ma20
            and last_close > ma20 * 1.05
            and vol_ratio > 1.5
            and change_pct > 3
        ):
            signal = "buy"
            reason = f"放量突破MA20({ma20:.2f}) + 涨幅{change_pct:.2f}%"
            confidence = 65.0
        else:
            if last_close > ma5 > ma10 > ma20:
                reason = "多头排列，持仓观望"
                confidence = 60
            elif last_close < ma5 < ma10 < ma20:
                reason = "空头排列，观望"
                confidence = 40
            else:
                reason = f"震荡中 MA5={ma5:.2f} MA10={ma10:.2f}"
                confidence = 50

        # 选股只返回 buy 信号
        if signal != "buy":
            return None

        return {
            'strategy': '波段信号',
            'signal': signal,
            'score': int(confidence),
            'confidence': confidence,
            'reason': reason,
            'ma5': round(ma5, 2),
            'ma10': round(ma10, 2),
            'ma20': round(ma20, 2),
            'rsi6': round(rsi6, 2) if rsi6 is not None else None,
            'change_pct': round(change_pct, 2),
            'vol_ratio': round(vol_ratio, 2),
            'close': round(last_close, 2),
            'date': kline[-1].get('day', ''),
        }
    except Exception:
        logger.debug("wave_band_strategy failed", exc_info=True)
        return None


# ============================================================
# 批量选股
# ============================================================

def run_wave_band_screen(stock_list, trade_date=None):
    """
    批量执行波段信号选股

    参数:
        stock_list: ts_code 列表（支持 'sz301171' 或 '000001.SZ' 格式）
        trade_date: 交易日期（可选，仅用于记录）

    返回:
        命中 buy 信号的股票结果列表
    """
    results = []
    for ts_code in stock_list:
        kline = get_kline_from_tdx(ts_code, days=30)
        if kline and len(kline) >= 21:
            result = wave_band_strategy(kline)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                results.append(result)
    return results


if __name__ == "__main__":
    print("=" * 80)
    print("🌊 波段信号 - MA+RSI+量比 买卖点策略 (pytdx版)")
    print("=" * 80)
    sample = ['sz300502', 'sz300308', 'sh688183']
    hits = run_wave_band_screen(sample)
    for h in hits:
        print(f"✅ {h['ts_code']} 信号{h['signal']} 评分{h['score']} {h['reason']}")
