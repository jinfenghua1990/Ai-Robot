#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📋 量价报告策略 - 按 CodeBuddy 量价筛选报告逻辑实现

报告核心：
1. 5种形态分类：缩量回踩 / 放量突破 / 趋势延续 / 缩量修复 / 结构偏弱
2. 3层分层：优先买入 / 等回踩确认 / 暂不参与
3. 关键指标：日涨跌、近5日涨跌、20日量比、距20日高点、均线乖离
4. 交易计划：每只股票输出具体买入价位 + 止损价位

执行规则（报告原文）：
- 开盘高开>3%不追，等第一次回踩不破分时均线
- 优先看5日线和10日线附近缩量承接
- 突破型必须放量站上前高或平台上沿
- 放量跌破20日线，短线计划失效
"""
import logging
import concurrent.futures
import numpy as np

logger = logging.getLogger(__name__)


def calc_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def liangjia_report_strategy(kline, day_index=-1, main_force_history=None):
    """量价报告策略主函数

    参数:
        kline: K线数据列表
        day_index: 检查哪一天（默认-1）
        main_force_history: 近5日主力净流入列表（来自StockFlow，可选）

    返回 dict（含 pattern/tier/gain5d/vol_ratio_20/distance_to_high_20/trade_plan 等）或 None
    """
    try:
        if day_index == -1:
            day_index = len(kline) - 1
        if day_index < 0 or day_index >= len(kline) or day_index < 20:
            return None

        latest = kline[day_index]
        prev = kline[day_index - 1]

        close = float(latest['close'])
        low = float(latest['low'])
        high = float(latest['high'])
        open_p = float(latest['open'])
        ma20 = float(latest.get('ma_price20') or 0)
        ma10 = float(latest.get('ma_price10') or 0)
        ma5 = float(latest.get('ma_price5') or 0)
        prev_close = float(prev['close'])
        volume = float(latest['volume'])

        if ma20 <= 0 or ma10 <= 0 or ma5 <= 0:
            return None

        closes = [float(k['close']) for k in kline[:day_index + 1]]
        if len(closes) < 21:
            return None

        # ===== 关键指标计算 =====
        change_pct = (close - prev_close) / prev_close * 100
        gain5d = (close - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 else 0
        gain20d = (close - closes[-21]) / closes[-21] * 100

        # 20日量比（报告口径：当日成交量 / 过去20个交易日均量）
        recent_vols = [float(kline[day_index - j]['volume']) for j in range(1, 21) if day_index - j >= 0]
        avg_vol_20 = np.mean(recent_vols) if recent_vols else 0
        vol_ratio_20 = (volume / avg_vol_20) if avg_vol_20 > 0 else 999

        # 距20日高点
        high_20 = max(closes[-20:])
        distance_to_high_20 = (high_20 - close) / high_20 * 100

        # 均线乖离
        deviation_ma20 = (close - ma20) / ma20 * 100
        deviation_ma5 = (close - ma5) / ma5 * 100

        # MA20趋势（连续4天向上）
        ma20_list = []
        for i in range(max(0, day_index - 5), day_index + 1):
            ma = kline[i].get('ma_price20')
            if ma and float(ma) > 0:
                ma20_list.append(float(ma))
        ma20_rising = len(ma20_list) >= 4 and all(ma20_list[j] < ma20_list[j + 1] for j in range(len(ma20_list) - 4, len(ma20_list) - 1))

        # 多头排列
        bull_alignment = ma5 > ma10 > ma20

        # 突破10日新高（来自 volume_breakout 策略核心维度）
        high_10d = max(float(k['high']) for k in kline[max(0, day_index - 10):day_index]) if day_index >= 10 else 0
        breakout_10d = (close > high_10d) if high_10d > 0 else False
        breakout_pct = (close - high_10d) / high_10d * 100 if high_10d > 0 else 0

        # 下影线/上影线
        lower_shadow = (min(close, open_p) - low) / prev_close * 100
        upper_shadow = (high - max(close, open_p)) / prev_close * 100

        rsi = calc_rsi(closes)

        # ===== 5种形态分类 =====
        pattern = None
        pattern_desc = ''

        # 1. 缩量回踩：最低价触及MA20，缩量，收盘仍守MA20上方
        if low <= ma20 and close > ma20 and vol_ratio_20 < 1.0 and ma20_rising:
            pattern = 'pullback'
            pattern_desc = '缩量回踩守20日线'

        # 2. 放量突破：收盘站上MA5/MA10，放量，接近20日高点
        elif close > ma5 and close > ma10 and vol_ratio_20 >= 1.5 and distance_to_high_20 <= 5:
            pattern = 'breakout'
            pattern_desc = '放量突破不破5/10日线'

        # 3. 趋势延续：多头排列，均线结构尚可
        elif bull_alignment and close > ma20 and ma20_rising:
            pattern = 'trend'
            pattern_desc = '趋势延续，均线结构尚可'

        # 4. 缩量修复：缩量，跌破MA5或MA10，但守MA20
        elif vol_ratio_20 < 0.8 and close < ma5 and close > ma20:
            pattern = 'repair'
            pattern_desc = '缩量修复，短线跌破关键均线'

        # 5. 结构偏弱：跌破MA20 或 双线破位
        elif close < ma20 or (close < ma5 and close < ma10):
            pattern = 'weak'
            pattern_desc = '结构偏弱或追高风险偏大'

        if pattern is None:
            return None

        # ===== 3层分层 =====
        # 优先买入：缩量回踩 + 放量突破 + 趋势延续(乖离<15%)
        # 等回踩确认：趋势延续(乖离>15%) + 放量突破(距高点>5%但<10%)
        # 暂不参与：结构偏弱 + 缩量修复 + 趋势延续(距高点>15%)
        tier = None
        tier_label = ''

        if pattern in ('pullback', 'breakout'):
            # 缩量回踩和放量突破默认优先买入
            # 但放量突破如果距高点>5%，降级到等回踩
            if pattern == 'breakout' and distance_to_high_20 > 5:
                tier = 'wait'
                tier_label = '等回踩确认'
            else:
                tier = 'priority'
                tier_label = '优先买入'

        elif pattern == 'trend':
            # 趋势延续：乖离>15% 或 距高点>10% 降级到等回踩
            if deviation_ma20 > 15 or distance_to_high_20 > 10:
                tier = 'wait'
                tier_label = '等回踩确认'
            elif deviation_ma20 > 20 or distance_to_high_20 > 15:
                tier = 'avoid'
                tier_label = '暂不参与'
            else:
                tier = 'priority'
                tier_label = '优先买入'

        elif pattern == 'repair':
            # 缩量修复：默认等回踩，若已破MA20则暂不参与
            if close < ma20:
                tier = 'avoid'
                tier_label = '暂不参与'
            else:
                tier = 'wait'
                tier_label = '等回踩确认'

        elif pattern == 'weak':
            tier = 'avoid'
            tier_label = '暂不参与'

        if tier is None:
            return None

        # ===== 交易计划生成 =====
        trade_plan = _gen_trade_plan(
            pattern, tier, close, ma5, ma10, ma20,
            distance_to_high_20, deviation_ma20
        )

        # ===== 综合评分（用于同层内排序） =====
        score = 0
        # 趋势分（MA20向上+多头排列）
        if ma20_rising:
            score += 2
        if bull_alignment:
            score += 2
        # 量价配合分
        if pattern == 'pullback' and vol_ratio_20 < 0.8:
            score += 3
        elif pattern == 'breakout' and vol_ratio_20 >= 2.0:
            score += 3
        elif pattern == 'breakout' and vol_ratio_20 >= 1.5:
            score += 2
        # 位置分（距高点越近越好，但回踩型相反）
        if pattern == 'breakout' and distance_to_high_20 <= 2:
            score += 2
        elif pattern == 'pullback' and 3 <= distance_to_high_20 <= 10:
            score += 2
        # 5日动能分
        if 0 < gain5d < 15:
            score += 1
        # RSI健康度
        if 30 <= rsi <= 65:
            score += 1

        # === 合并吸收的评分维度 ===
        # 突破强度（来自 volume_breakout）：突破10日新高加分
        if breakout_10d and 0 < breakout_pct <= 5:
            score += 2
        # 主力连续流入（来自 zhushenglang）：近5日≥3日主力净流入为正
        main_force_days = 0
        has_main_force = False
        if main_force_history and len(main_force_history) >= 3:
            main_force_days = sum(1 for f in main_force_history if f > 0)
            has_main_force = main_force_history[-1] > 0 if main_force_history else False
            if main_force_days >= 4:
                score += 2
            elif main_force_days >= 3:
                score += 1

        return {
            'strategy': '白虎V4.0',
            'pattern': pattern,
            'pattern_desc': pattern_desc,
            'tier': tier,
            'tier_label': tier_label,
            'score': score,
            'close': round(close, 2),
            'change_pct': round(change_pct, 2),
            'gain5d': round(gain5d, 2),
            'gain20d': round(gain20d, 2),
            'vol_ratio_20': round(vol_ratio_20, 2),
            'distance_to_high_20': round(distance_to_high_20, 2),
            'deviation_ma20': round(deviation_ma20, 2),
            'deviation_ma5': round(deviation_ma5, 2),
            'lower_shadow': round(lower_shadow, 2),
            'upper_shadow': round(upper_shadow, 2),
            'rsi': round(rsi, 2),
            'ma5': round(ma5, 2),
            'ma10': round(ma10, 2),
            'ma20': round(ma20, 2),
            'ma20_rising': ma20_rising,
            'bull_alignment': bull_alignment,
            'breakout_10d': breakout_10d,
            'breakout_pct': round(breakout_pct, 2),
            'main_force_days': main_force_days,
            'has_main_force': has_main_force,
            'trade_plan': trade_plan,
            'date': latest.get('day', ''),
        }
    except Exception:
        logger.debug('liangjia_report_strategy failed', exc_info=True)
        return None


def _gen_trade_plan(pattern, tier, close, ma5, ma10, ma20, dist_high, dev_ma20):
    """生成具体交易计划（买入价位 + 止损价位）

    按报告模板：
    - 缩量回踩：靠近10日线 X 至20日线 Y 区间缩量企稳再买。有效跌破20日线 Y 失效。
    - 放量突破：放量站稳 Z 上方，或回踩不破5日线 W 再试错。跌回10日线 X 且放量转弱则止损。
    - 趋势延续：盘中回踩 X 附近承接强，再小仓试。跌破20日线 Y 不再恋战。
    - 缩量修复/结构偏弱：明天不主动买，除非放量反包并重新站回5/10日线。
    """
    if pattern == 'pullback':
        buy_zone = f"靠近10日线 {ma10:.2f} 至20日线 {ma20:.2f} 区间缩量企稳再买"
        stop_loss = f"有效跌破20日线 {ma20:.2f} 失效"
        return {'buy': buy_zone, 'stop': stop_loss, 'action': '低吸'}

    if pattern == 'breakout':
        buy_zone = f"放量站稳 {close:.2f} 上方，或回踩不破5日线 {ma5:.2f} 再试错"
        stop_loss = f"跌回10日线 {ma10:.2f} 且放量转弱则止损"
        return {'buy': buy_zone, 'stop': stop_loss, 'action': '右侧确认'}

    if pattern == 'trend':
        if tier == 'priority':
            buy_zone = f"不追开盘冲高；若盘中回踩 {ma10:.2f} 附近承接强，再小仓试"
            stop_loss = f"跌破20日线 {ma20:.2f} 不再恋战"
            return {'buy': buy_zone, 'stop': stop_loss, 'action': '回踩试错'}
        else:
            buy_zone = f"等回踩确认：靠近10日线 {ma10:.2f} 至20日线 {ma20:.2f} 区间缩量企稳再买"
            stop_loss = f"跌破20日线 {ma20:.2f} 不再恋战"
            return {'buy': buy_zone, 'stop': stop_loss, 'action': '等回踩'}

    if pattern == 'repair':
        buy_zone = f"等缩量修复完成：重新站回5日线 {ma5:.2f} 上方再考虑"
        stop_loss = f"有效跌破20日线 {ma20:.2f} 失效"
        return {'buy': buy_zone, 'stop': stop_loss, 'action': '观望'}

    # weak
    return {
        'buy': f"明天不主动买，除非放量反包并重新站回5/10日线",
        'stop': f"若已持有，重点看20日线 {ma20:.2f}",
        'action': '减仓观望',
    }


# ============================================================
# pytdx 数据源（复用 baihu_v30）
# ============================================================
def _parse_ts_code(ts_code):
    from strategies.baihu_v30 import _parse_ts_code as _parse
    return _parse(ts_code)


def get_kline_from_tdx(code, days=90):
    from strategies.baihu_v30 import get_kline_from_tdx as _get
    return _get(code, days)


def run_liangjia_report_screen(stock_list, trade_date=None, max_workers=20, db=None):
    """批量执行量价报告选股（线程池并发）

    参数:
        stock_list: 股票代码列表
        trade_date: 交易日期 (YYYY-MM-DD)
        max_workers: 线程池大小
        db: 数据库会话（可选，用于查 StockFlow 主力资金历史）
    """
    # 预加载主力资金历史（近5个交易日）
    main_force_map = {}
    if db and trade_date:
        from db.models import StockFlow as SF
        from datetime import datetime, timedelta
        date_obj = datetime.strptime(trade_date, '%Y-%m-%d')
        check_dates = []
        for i in range(0, 15):
            d = (date_obj - timedelta(days=i)).strftime('%Y-%m-%d')
            check_dates.append(d)
        flows = db.query(SF).filter(
            SF.trade_date.in_(check_dates),
            SF.ts_code.in_(stock_list),
        ).all()
        sf_grouped = {}
        for f in flows:
            sf_grouped.setdefault(f.ts_code, []).append({
                'date': str(f.trade_date),
                'main_force': float(f.main_force_inflow or 0),
            })
        for ts_code, flist in sf_grouped.items():
            flist.sort(key=lambda x: x['date'], reverse=True)
            recent5 = flist[:5]
            if len(recent5) >= 3:
                recent5.reverse()
                main_force_map[ts_code] = [f['main_force'] for f in recent5]

    def _screen_one(ts_code):
        try:
            kline = get_kline_from_tdx(ts_code, 60)
            if kline and len(kline) >= 30:
                mf_history = main_force_map.get(ts_code)
                result = liangjia_report_strategy(kline, main_force_history=mf_history)
                if result:
                    result['ts_code'] = ts_code
                    if trade_date:
                        result['trade_date'] = trade_date
                    return result
        except Exception:
            logger.debug(f'liangjia _screen_one failed {ts_code}', exc_info=True)
        return None

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_screen_one, code): code for code in stock_list}
        for future in concurrent.futures.as_completed(futures, timeout=120):
            try:
                result = future.result(timeout=10)
                if result:
                    results.append(result)
            except Exception:
                logger.debug('liangjia future failed', exc_info=True)
    return results


if __name__ == '__main__':
    print('=' * 80)
    print('📋 量价报告策略 - 测试')
    print('=' * 80)
    sample = ['sz301171', 'sh603211', 'sz002050']
    hits = run_liangjia_report_screen(sample)
    for h in hits:
        print(f"  {h['ts_code']} | {h['pattern_desc']} | {h['tier_label']} | 评分{h['score']}")
        print(f"    买入: {h['trade_plan']['buy']}")
        print(f"    止损: {h['trade_plan']['stop']}")
