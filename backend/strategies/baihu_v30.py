#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
logger = logging.getLogger(__name__)
"""
🐯 白虎 V3.0 - 科创板/创业板适配版
基于 V2.6 回测数据优化，针对20%涨跌幅板块

核心改进：
1. 及格线从4分提高到6分（V2.6低分胜率仅11%）
2. 加入缩量验证（缩量回踩更健康）
3. 偏离度细分（0-3%最佳，5-8%风险大降分）
4. 加入下影线强度细分（>2%金针探底加分）
5. 涨幅区间细分（0-3%最佳，3-6%次之）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np


logger = logging.getLogger(__name__)

def calc_rsi(closes, period=14):
    """计算RSI指标"""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def baihu_strategy_v30(kline, day_index=-1):
    """
    白虎V3.0选股策略（科创板/创业板适配版）

    参数:
        kline: K线数据列表，每个元素需包含 close/open/low/high/volume/ma_price20
        day_index: 检查哪一天（默认-1，即最新一天）

    返回:
        符合条件返回评分字典，不符合返回None
    """
    try:
        # 统一处理 day_index=-1，避免 kline[:0] 切片为空的BUG
        if day_index == -1:
            day_index = len(kline) - 1
        if day_index < 0 or day_index >= len(kline):
            return None

        # ========== 【5个必过硬门槛（与V2.6一致）】 ==========

        # 1. MA20连续4天向上
        ma20_list = []
        for i in range(max(0, day_index - 5), day_index + 1):
            ma = kline[i].get('ma_price20')
            if ma and float(ma) > 0:
                ma20_list.append(float(ma))

        if len(ma20_list) < 4:
            return None
        if not all(ma20_list[j] < ma20_list[j + 1] for j in range(len(ma20_list) - 4, len(ma20_list) - 1)):
            return None

        # 2. 近20日累计涨幅 > 20%
        closes = [float(k['close']) for k in kline[:day_index + 1]]
        if len(closes) < 21:
            return None
        close_20day_ago = closes[-21]
        recent_20day_gain = (closes[-1] - close_20day_ago) / close_20day_ago * 100
        if recent_20day_gain < 20:
            return None

        latest = kline[day_index]
        prev = kline[day_index - 1]

        close = float(latest['close'])
        low = float(latest['low'])
        ma20 = float(latest['ma_price20'])

        # 3. 收盘价 > MA20（不破位）
        if close <= ma20:
            return None

        # 4. 最低价 ≤ MA20（真回踩）
        if low > ma20:
            return None

        # 5. 偏离MA20 < 8%
        deviation = (close - ma20) / ma20 * 100
        if deviation >= 8:
            return None

        # ========== 【V3.0 优化评分系统（满分10分，≥6分入选）】 ==========

        open_p = float(latest['open'])
        prev_close = float(prev['close'])
        volume = float(latest['volume'])

        change_pct = (close - prev_close) / prev_close * 100
        lower_shadow = (min(close, open_p) - low) / prev_close * 100

        rsi = calc_rsi(closes)

        # 量比：当前成交量 / 近5日平均成交量
        recent_vols = [float(kline[day_index - j]['volume']) for j in range(1, 6)]
        avg_vol = np.mean(recent_vols)
        vol_ratio = (volume / avg_vol * 100) if avg_vol > 0 else 999

        score = 0

        # 1. 下影线评分（0-3分）
        #    V3.0细分：>2%金针探底(+3)，1-2%普通下影线(+2)，<1%无下影线(+0)
        if lower_shadow > 2:
            score += 3  # 金针探底，洗盘最充分
        elif lower_shadow > 1:
            score += 2  # 普通下影线
        # else: 无下影线，不加分

        # 2. 涨幅评分（0-2分）
        #    V3.0细分：0-3%最佳(+2)，3-6%次之(+1)，>6%或<0不加分
        if 0 <= change_pct <= 3:
            score += 2  # 小幅调整，最健康
        elif 3 < change_pct <= 6:
            score += 1  # 中等涨幅
        # else: 不加分

        # 3. 缩量验证（0-2分）★ V3.0新增
        #    缩量回踩更健康，放量回踩可能是出货
        if vol_ratio < 80:
            score += 2  # 明显缩量，洗盘充分
        elif vol_ratio < 120:
            score += 1  # 温和缩量或平量
        # else: 放量回踩，不加分（可能是出货）

        # 4. RSI评分（0-1分）
        if 30 <= rsi <= 55:
            score += 1  # 不超买，还有空间
        # else: 不加分

        # 5. 偏离度评分（0-2分）
        #    V3.0细分：0-3%贴近MA20(+2)，3-5%次之(+1)，5-8%风险大(+0)
        if 0 < deviation <= 3:
            score += 2  # 贴着均线，盈亏比最高
        elif 3 < deviation <= 5:
            score += 1  # 稍有偏离
        # else: 5-8%偏离太大，不加分

        # V3.0及格线：≥6分入选（V2.6是≥4分）
        if score < 6:
            return None

        return {
            'strategy': '白虎V3',
            'score': score,
            '20day_gain': round(recent_20day_gain, 2),
            'deviation': round(deviation, 2),
            'change_pct': round(change_pct, 2),
            'rsi': round(rsi, 2),
            'vol_ratio': round(vol_ratio, 2),
            'lower_shadow': round(lower_shadow, 2),
            'ma20': round(ma20, 2),
            'close': round(close, 2),
            'date': latest.get('day', ''),
            # V3.0评分分解
            'scores': {
                'shadow': 3 if lower_shadow > 2 else (2 if lower_shadow > 1 else 0),
                'change': 2 if 0 <= change_pct <= 3 else (1 if 3 < change_pct <= 6 else 0),
                'volume': 2 if vol_ratio < 80 else (1 if vol_ratio < 120 else 0),
                'rsi': 1 if 30 <= rsi <= 55 else 0,
                'deviation': 2 if 0 < deviation <= 3 else (1 if 3 < deviation <= 5 else 0),
            },
        }
    except Exception:
        logger.debug(f"function failed", exc_info=True)
        return None


# ============================================================
# pytdx 数据源（复用V2.6）
# ============================================================

def _parse_ts_code(ts_code):
    code = str(ts_code).strip().lower()
    if '.' in code:
        pure_code, exchange = code.split('.')
        if exchange.startswith('sz'):
            return 0, pure_code
        elif exchange.startswith('sh'):
            return 1, pure_code
        return None, None
    if code.startswith('sz') or code.startswith('sh'):
        prefix = code[:2]
        pure_code = code[2:]
        market = 0 if prefix == 'sz' else 1
        return market, pure_code
    if code.isdigit():
        return (1, code) if code.startswith('6') else (0, code)
    return None, None


def get_kline_from_tdx(code, days=90):
    from collectors.tdx_collector import connect_with_retry
    api, server = connect_with_retry()
    if not api:
        return None
    try:
        market, pure_code = _parse_ts_code(code)
        if market is None:
            return None
        bars = api.get_security_bars(4, market, pure_code, 0, days)
        if not bars or len(bars) < 30:
            return None
        # pytdx 实测返回 oldest-first（bars[0] 最早），无需 reversed，直接使用
        kline = []
        closes_history = []
        ma20_sum = 0.0
        for b in bars:
            close = float(b['close'])
            open_p = float(b['open'])
            high = float(b['high'])
            low = float(b['low'])
            volume = float(b.get('vol', b.get('volume', 0)))
            day = b.get('datetime', '')
            if not day and b.get('year'):
                day = f"{b['year']:04d}-{b['month']:02d}-{b['day']:02d}"
            closes_history.append(close)
            ma20_sum += close
            if len(closes_history) > 20:
                ma20_sum -= closes_history[-21]
            ma20 = ma20_sum / 20.0 if len(closes_history) >= 20 else 0.0
            kline.append({
                'close': close, 'open': open_p, 'high': high, 'low': low,
                'volume': volume, 'ma_price20': ma20 if ma20 > 0 else None, 'day': day,
            })
        return kline
    except Exception:
        logger.debug(f"function failed", exc_info=True)
        return None
    finally:
        if api:
            try:
                api.disconnect()
            except Exception as e:
                logger.debug(f'[baihu_v30] pytdx disconnect 失败: {e}')


def run_baihu_v30_screen(stock_list, trade_date=None):
    """批量执行白虎V3.0选股"""
    results = []
    for ts_code in stock_list:
        kline = get_kline_from_tdx(ts_code, 360)
        if kline and len(kline) >= 30:
            result = baihu_strategy_v30(kline)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                results.append(result)
    return results


if __name__ == "__main__":
    print("=" * 80)
    print("🐯 白虎 V3.0 - 科创板/创业板适配版")
    print("=" * 80)
    sample = ['sz301171']
    hits = run_baihu_v30_screen(sample)
    for h in hits:
        print(f"✅ {h['ts_code']} 评分{h['score']} 偏离{h['deviation']}% 量比{h['vol_ratio']}%")