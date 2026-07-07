#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
logger = logging.getLogger(__name__)
"""
🐯 白虎 V2.6 - 强势回调选股策略
从 /Users/gino/Downloads/白虎V2.6选股策略_核心代码(1).py 迁移
数据源：新浪API → pytdx（collectors.tdx_collector）

核心逻辑：
1. MA20连续4天向上
2. 近20日累计涨幅 > 20%
3. 收盘价 > MA20（不破位）
4. 最低价 ≤ MA20（真回踩）
5. 偏离MA20 < 8%
5维度评分（下影线/涨幅/量比/RSI/偏离度），≥4分入选
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np


logger = logging.getLogger(__name__)

# ============================================================
# 工具函数
# ============================================================

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


# ============================================================
# 🐯 V2.6 核心选股策略
# ============================================================

def baihu_strategy_v26(kline, day_index=-1):
    """
    白虎V2.6选股策略

    参数:
        kline: K线数据列表，每个元素是 dict，需包含 close/open/low/high/volume/ma_price20 字段
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

        # ========== 【5个必过硬门槛】 ==========

        # 1. MA20连续4天向上
        ma20_list = []
        for i in range(max(0, day_index - 5), day_index + 1):
            ma = kline[i].get('ma_price20')
            if ma and float(ma) > 0:
                ma20_list.append(float(ma))

        if len(ma20_list) < 4:
            return None
        # 连续4天向上
        if not all(ma20_list[j] < ma20_list[j + 1] for j in range(len(ma20_list) - 4, len(ma20_list) - 1)):
            return None

        # 2. 近20日累计涨幅 > 20%（先证明是牛股）
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

        # 3. 收盘价 > MA20（不能破位）
        if close <= ma20:
            return None

        # 4. 最低价 ≤ MA20（必须真回踩碰到均线，金针探底最佳）
        if low > ma20:
            return None

        # 5. 收盘价偏离MA20 < 8%（贴着均线买，盈亏比最高）
        deviation = (close - ma20) / ma20 * 100
        if deviation >= 8:
            return None

        # ========== 【其他指标计算】 ==========
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

        # ========== 【5维度评分系统（满分8分，≥4分入选）】 ==========
        score = 0

        # 1. 下影线 > 1%（+2分）：金针探底，洗盘最充分，支撑最强
        if lower_shadow > 1:
            score += 2

        # 2. 当日涨幅 0% ~ 6%（+2分）：小阴小阳，健康调整，不是暴跌也不是爆拉
        if 0 <= change_pct <= 6:
            score += 2

        # 3. 量比 < 130%（+1分）：缩量或温和放量
        #    V2.6优化：关键支撑位收阳线时放量反而是好事，说明有资金承接
        if vol_ratio < 130:
            score += 1

        # 4. RSI 25 ~ 60（+1分）：不超买，还有上涨空间
        if 25 <= rsi <= 60:
            score += 1

        # 5. 偏离MA20 0% ~ 8%（+2分）：位置安全，盈亏比高
        if 0 < deviation < 8:
            score += 2

        # 及格线：≥4分入选
        if score < 4:
            return None

        return {
            'strategy': '白虎',
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
        }
    except Exception:
        logger.debug(f"function failed", exc_info=True)
        return None


# ============================================================
# pytdx 数据源
# ============================================================

def _parse_ts_code(ts_code):
    """
    解析股票代码为 (market, code)
    支持:
      - 'sz301171' / 'sh688523' (sina格式)
      - '000001.SZ' / '600000.SH' (tushare格式)
    market: 0=深圳, 1=上海
    """
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
    # 纯数字代码：6开头为上海，其余为深圳
    if code.isdigit():
        return (1, code) if code.startswith('6') else (0, code)
    return None, None


def get_kline_from_tdx(code, days=90):
    """
    通过pytdx获取K线数据，返回与原始策略一致的格式。
    每个元素是 dict，包含 close/open/low/high/volume/ma_price20/day 字段。
    """
    from collectors.tdx_collector import connect_with_retry
    api, server = connect_with_retry()
    if not api:
        return None
    try:
        market, pure_code = _parse_ts_code(code)
        if market is None:
            return None
        # category=4 日线
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
            # 日期：pytdx 提供 datetime 字符串 'YYYY-MM-DD' 或 year/month/day
            day = b.get('datetime', '')
            if not day and b.get('year'):
                day = f"{b['year']:04d}-{b['month']:02d}-{b['day']:02d}"
            closes_history.append(close)
            ma20_sum += close
            if len(closes_history) > 20:
                ma20_sum -= closes_history[-21]
            # 计算 MA20（滑动窗口，O(1)）
            ma20 = ma20_sum / 20.0 if len(closes_history) >= 20 else 0.0
            kline.append({
                'close': close,
                'open': open_p,
                'high': high,
                'low': low,
                'volume': volume,
                'ma_price20': ma20 if ma20 > 0 else None,
                'day': day,
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
                logger.debug(f'[baihu_v26] pytdx disconnect 失败: {e}')


# ============================================================
# 批量选股
# ============================================================

def run_baihu_screen(stock_list, trade_date=None):
    """
    批量执行白虎V2.6选股
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
            result = baihu_strategy_v26(kline)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                results.append(result)
    return results


if __name__ == "__main__":
    print("=" * 80)
    print("🐯 白虎 V2.6 - 强势回调选股策略 (pytdx版)")
    print("=" * 80)
    # 示例
    sample = ['sz301171']
    hits = run_baihu_screen(sample)
    for h in hits:
        print(f"✅ {h['ts_code']} 评分{h['score']} 偏离{h['deviation']}% 量比{h['vol_ratio']}%")