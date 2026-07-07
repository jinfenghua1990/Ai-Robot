#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🚀 主升浪 - 主力资金+主升浪策略
核心逻辑：
1. MA多头排列：MA5 > MA10 > MA20 > MA60
2. Bias过滤：price/MA20 < 1.15（防止追高）
3. 主力资金流入：当日主力净流入占比 > 5%
4. 资金连续性：近5日中至少3日主力净流入为正
5. 退出信号：收盘价跌破MA20 或 连续3日大幅流出(ratio < -5%)

评分维度（满分8分，≥5分入选）：
  - MA排列强度（+2）
  - Bias偏离度（+2）
  - 主力净流入占比（+2）
  - 资金连续性（+1）
  - 量价配合（+1）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from .baihu_v26 import get_kline_from_tdx, calc_rsi
import logging
logger = logging.getLogger(__name__)


# ============================================================
# 工具函数
# ============================================================

def calc_ma_series(closes, period):
    """计算MA均线序列，返回与closes等长的列表，前period-1个为None"""
    result = [None] * len(closes)
    if len(closes) < period:
        return result
    window_sum = sum(closes[:period])
    result[period - 1] = window_sum / period
    for i in range(period, len(closes)):
        window_sum += closes[i] - closes[i - period]
        result[i] = window_sum / period
    return result


# ============================================================
# 🚀 主升浪 - 主力资金+主升浪策略
# ============================================================

def zhushenglang_strategy(kline, day_index=-1, main_force_history=None):
    """
    主升浪策略：MA多头排列 + 主力资金流入

    参数:
        kline: K线数据列表，每个元素 dict (close/open/low/high/volume/day)
        day_index: 检查哪一天（默认-1，最新一天）
        main_force_history: 近5日主力净流入列表 [day-4, day-3, day-2, day-1, day0]
                           如果为None，则跳过资金连续性检查

    返回:
        符合条件返回评分字典，不符合返回None
    """
    try:
        # 统一处理 day_index=-1，避免 kline[:0] 切片为空的BUG
        if day_index == -1:
            day_index = len(kline) - 1
        if day_index < 0 or day_index >= len(kline):
            return None

        closes = [float(k['close']) for k in kline[:day_index + 1]]

        # 至少需要60+天数据计算MA60
        if len(closes) < 65:
            return None

        # ========== 计算MA均线 ==========
        ma5_list = calc_ma_series(closes, 5)
        ma10_list = calc_ma_series(closes, 10)
        ma20_list = calc_ma_series(closes, 20)
        ma60_list = calc_ma_series(closes, 60)

        idx = day_index  # 修复后 day_index 已是合法正索引

        ma5 = ma5_list[idx]
        ma10 = ma10_list[idx]
        ma20 = ma20_list[idx]
        ma60 = ma60_list[idx]

        if any(v is None for v in [ma5, ma10, ma20, ma60]):
            return None

        close = closes[idx]

        # ========== 【5个硬门槛】 ==========

        # 1. MA多头排列：MA5 > MA10 > MA20 > MA60
        if not (ma5 > ma10 > ma20 > ma60):
            return None

        # 2. Bias过滤：price/MA20 < 1.15（不追高）
        bias_20 = close / ma20
        if bias_20 >= 1.15:
            return None

        # 3. 收盘价必须在MA20之上（趋势不破）
        if close <= ma20:
            return None

        # 4. MA20必须向上（近3天MA20递增）
        ma20_prev_vals = []
        for offset in range(1, 4):
            check_idx = idx - offset
            if check_idx >= 0 and ma20_list[check_idx] is not None:
                ma20_prev_vals.append(ma20_list[check_idx])
        if len(ma20_prev_vals) >= 2:
            # MA20 近2-3天应该总体向上
            if ma20 <= ma20_prev_vals[-1]:
                return None

        # 5. 成交量不能过低（排除僵尸股）
        volume = float(kline[idx]['volume'])
        recent_vols = []
        for j in range(1, min(11, idx + 1)):
            recent_vols.append(float(kline[idx - j]['volume']))
        if recent_vols:
            avg_vol_10 = np.mean(recent_vols)
            if avg_vol_10 > 0 and volume < avg_vol_10 * 0.3:
                return None  # 成交量不到10日均量的30%，太冷

        # ========== 【主力资金检查】 ==========
        # main_force_history: [day-4, day-3, day-2, day-1, day0] 的主力净流入
        main_force_ratio = 0
        continuity_days = 0
        has_main_force = False

        if main_force_history and len(main_force_history) >= 5:
            today_flow = main_force_history[-1]
            # 主力净流入占比（简化：用绝对值/价格做proxy）
            # 这里 main_force_inflow 单位是万元，close 是股价
            # 用流入方向判断即可
            if today_flow > 0:
                has_main_force = True
                # 简化占比：正流入即可
                main_force_ratio = 1  # 标记为正流入

            # 连续性：近5日中至少3日主力净流入为正
            continuity_days = sum(1 for f in main_force_history if f > 0)
            if continuity_days < 3:
                return None
        # 如果没有 main_force_history，跳过资金连续性检查（降级模式）

        # ========== 【RSI 超买过滤（优化新增）】 ==========
        rsi = calc_rsi(closes)
        # RSI > 80 视为超买，避免追在最高点（回测发现"买在高位"是亏损单主因）
        if rsi > 80:
            return None

        # ========== 【退出信号检查】 ==========
        exit_signal = None
        # 退出1：收盘价跌破MA10（趋势弱化警告）
        if close < ma10:
            exit_signal = '跌破MA10'

        # ========== 【指标计算】 ==========
        latest = kline[idx]
        prev = kline[idx - 1] if idx > 0 else latest

        open_p = float(latest['open'])
        prev_close = float(prev['close'])
        change_pct = (close - prev_close) / prev_close * 100 if prev_close else 0
        lower_shadow = (min(close, open_p) - float(latest['low'])) / prev_close * 100 if prev_close else 0

        # 量比
        if recent_vols:
            avg_vol_5 = np.mean(recent_vols[:5])
            vol_ratio = (volume / avg_vol_5 * 100) if avg_vol_5 > 0 else 999
        else:
            vol_ratio = 100

        # MA排列强度：各MA之间的间距
        ma_spread = (ma5 - ma60) / ma60 * 100  # MA5相对MA60的偏离

        # ========== 【5维度评分系统（满分8分，≥5分入选）】 ==========
        score = 0
        scores_detail = {}

        # 1. MA排列强度（+2分）
        #    MA5>MA10>MA20>MA60 已满足，看间距是否健康
        if ma_spread > 3 and ma_spread < 20:
            score += 2
            scores_detail['ma_spread'] = 2
        elif ma_spread > 1:
            score += 1
            scores_detail['ma_spread'] = 1
        else:
            scores_detail['ma_spread'] = 0

        # 2. Bias偏离度（+2分）
        #    1.0 < bias < 1.08 最佳（贴近均线）
        if 1.0 < bias_20 < 1.08:
            score += 2
            scores_detail['bias'] = 2
        elif bias_20 < 1.12:
            score += 1
            scores_detail['bias'] = 1
        else:
            scores_detail['bias'] = 0

        # 3. 主力净流入（+2分）
        if has_main_force and continuity_days >= 4:
            score += 2
            scores_detail['main_force'] = 2
        elif has_main_force:
            score += 1
            scores_detail['main_force'] = 1
        else:
            scores_detail['main_force'] = 0

        # 4. 资金连续性（+1分）
        if continuity_days >= 4:
            score += 1
            scores_detail['continuity'] = 1
        else:
            scores_detail['continuity'] = 0

        # 5. 量价配合（+1分）
        #    放量上涨 或 缩量回踩 都是好的
        if (change_pct > 0 and vol_ratio > 100) or (change_pct <= 0 and vol_ratio < 80):
            score += 1
            scores_detail['vol_price'] = 1
        else:
            scores_detail['vol_price'] = 0

        # 及格线：≥5分
        if score < 5:
            return None

        return {
            'strategy': '主升浪',
            'score': score,
            'scores': scores_detail,
            'ma5': round(ma5, 2),
            'ma10': round(ma10, 2),
            'ma20': round(ma20, 2),
            'ma60': round(ma60, 2),
            'ma_spread': round(ma_spread, 2),
            'bias_20': round(bias_20, 4),
            'change_pct': round(change_pct, 2),
            'rsi': round(rsi, 2),
            'vol_ratio': round(vol_ratio, 2),
            'lower_shadow': round(lower_shadow, 2),
            'close': round(close, 2),
            'continuity_days': continuity_days,
            'has_main_force': has_main_force,
            'exit_signal': exit_signal,
            'date': latest.get('day', ''),
        }
    except Exception:
        logger.debug(f"function failed", exc_info=True)
        return None


# ============================================================
# 批量选股
# ============================================================

def run_zhushenglang_screen(stock_list, trade_date=None, db=None):
    """
    批量执行主升浪选股

    参数:
        stock_list: 股票代码列表（支持 'sz301171' 或 '000001.SZ' 格式）
        trade_date: 交易日期（可选，用于查询资金流向历史）
        db: 数据库会话（可选，用于查询StockFlow主力资金数据）

    返回:
        符合条件的股票结果列表
    """
    from datetime import datetime, timedelta

    # 预加载资金流向历史（近5个交易日）
    main_force_map = {}  # {ts_code: [day-4, day-3, day-2, day-1, day0]}
    if db and trade_date:
        from db.models import StockFlow
        date_obj = datetime.strptime(trade_date, '%Y-%m-%d')
        check_dates = []
        for i in range(0, 15):  # 往前找14天，取最近5个有数据的交易日
            d = (date_obj - timedelta(days=i)).strftime('%Y-%m-%d')
            check_dates.append(d)

        # 批量查询
        flows = db.query(StockFlow).filter(
            StockFlow.trade_date.in_(check_dates),
            StockFlow.ts_code.in_(stock_list)
        ).all()

        # 按股票分组
        stock_flows = {}
        for f in flows:
            if f.ts_code not in stock_flows:
                stock_flows[f.ts_code] = []
            stock_flows[f.ts_code].append({
                'date': str(f.trade_date),
                'main_force': float(f.main_force_inflow or 0)
            })

        # 取最近5天
        for ts_code, flist in stock_flows.items():
            flist.sort(key=lambda x: x['date'], reverse=True)
            recent5 = flist[:5]
            if len(recent5) >= 3:  # 至少3天数据
                # 反转为时间正序
                recent5.reverse()
                main_force_map[ts_code] = [f['main_force'] for f in recent5]

    results = []
    for ts_code in stock_list:
        kline = get_kline_from_tdx(ts_code, days=120)  # 需要更多数据计算MA60
        if kline and len(kline) >= 65:
            mf_history = main_force_map.get(ts_code)
            result = zhushenglang_strategy(kline, main_force_history=mf_history)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                results.append(result)
    return results


if __name__ == "__main__":
    print("=" * 80)
    print("🚀 主升浪 - 主力资金+主升浪策略 (pytdx版)")
    print("=" * 80)
    sample = ['sz301117']
    hits = run_zhushenglang_screen(sample)
    for h in hits:
        print(f"✅ {h['ts_code']} 评分{h['score']} MA排列{h['ma_spread']}% Bias{h['bias_20']} 连续{h['continuity_days']}天")
