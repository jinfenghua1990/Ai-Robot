#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging
logger = logging.getLogger(__name__)
"""
🐯 白虎 V3.0 - 全市场适配版
吸收 CodeBuddy 量价筛选报告思路：
- 缩量回踩仍守20日线（低位承接）
- 放量突破不破5/10日线（右侧确认）

核心改进：
1. 双模式门槛区分：回踩重缩量和守线，突破重放量和不破短期均线
2. 20日涨幅按模式区分（回踩>15%，突破>10%），避免漏掉刚启动的突破型
3. 回踩涨幅放宽到-5%~10%，涨停回踩也能识别
4. 突破涨幅放宽到0%~12%，避免错过9%放量转强
5. 偏离度放宽到12%，给强势股回踩留足空间
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
    吸收量价筛选报告思路：既抓“缩量回踩守20日线”，也抓“放量突破不破5/10日线”。

    参数:
        kline: K线数据列表，每个元素需包含 close/open/low/high/volume/ma_price20/ma_price10/ma_price5
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

        # 1. MA20连续4天向上（趋势基础）
        ma20_list = []
        for i in range(max(0, day_index - 5), day_index + 1):
            ma = kline[i].get('ma_price20')
            if ma and float(ma) > 0:
                ma20_list.append(float(ma))
        if len(ma20_list) < 4:
            return None
        if not all(ma20_list[j] < ma20_list[j + 1] for j in range(len(ma20_list) - 4, len(ma20_list) - 1)):
            return None

        latest = kline[day_index]
        prev = kline[day_index - 1]

        close = float(latest['close'])
        low = float(latest['low'])
        high = float(latest['high'])
        open_p = float(latest['open'])
        ma20 = float(latest['ma_price20'])
        ma10 = float(latest['ma_price10'] or 0)
        ma5 = float(latest['ma_price5'] or 0)
        prev_close = float(prev['close'])
        volume = float(latest['volume'])

        # 2. 收盘价必须在 MA20 上方（不破位，两种模式共同要求）
        if close <= ma20:
            return None

        closes = [float(k['close']) for k in kline[:day_index + 1]]
        if len(closes) < 21:
            return None
        recent_20day_gain = (closes[-1] - closes[-21]) / closes[-21] * 100
        change_pct = (close - prev_close) / prev_close * 100
        lower_shadow = (min(close, open_p) - low) / prev_close * 100
        upper_shadow = (high - max(close, open_p)) / prev_close * 100
        rsi = calc_rsi(closes)

        # 量比：当前成交量 / 近5日平均成交量
        recent_vols = [float(kline[day_index - j]['volume']) for j in range(1, 6)]
        avg_vol = np.mean(recent_vols)
        vol_ratio = (volume / avg_vol * 100) if avg_vol > 0 else 999

        # 距20日高点幅度（突破型需要）
        high_20 = max(closes[-20:])
        distance_to_high_20 = (high_20 - close) / high_20 * 100

        deviation = (close - ma20) / ma20 * 100

        # ========== 【两种盈利模式】 ==========
        mode = None
        score = 0
        scores_breakdown = {}

        # 模式A：缩量回踩仍守20日线（低位承接）
        #   最低价 ≤ MA20 视为对20日线的真实回踩，偏离放宽到12%
        is_pullback = low <= ma20 and deviation < 12 and recent_20day_gain > 15
        # 模式B：放量突破不破5/10日线（右侧确认）
        #   收盘在5/10日线上方，接近20日高点，20日涨幅门槛放宽到10%
        is_breakout = close > ma5 and close > ma10 and distance_to_high_20 <= 5 and recent_20day_gain > 10

        if is_pullback:
            mode = 'pullback'
            # 下影线（承接力度）
            if lower_shadow > 2:
                scores_breakdown['shadow'] = 3
                score += 3
            elif lower_shadow > 1:
                scores_breakdown['shadow'] = 2
                score += 2
            elif lower_shadow > 0.5:
                scores_breakdown['shadow'] = 1
                score += 1
            else:
                scores_breakdown['shadow'] = 0

            # 涨幅（涨停回踩也允许，-5%~12%最佳，12%~15%次之）
            if -5 <= change_pct <= 12:
                scores_breakdown['change'] = 2
                score += 2
            elif 12 < change_pct <= 15:
                scores_breakdown['change'] = 1
                score += 1
            else:
                scores_breakdown['change'] = 0

            # 量能（缩量回踩更健康，<120%都算良性）
            if vol_ratio < 80:
                scores_breakdown['volume'] = 2
                score += 2
            elif vol_ratio < 120:
                scores_breakdown['volume'] = 1
                score += 1
            else:
                scores_breakdown['volume'] = 0

        elif is_breakout:
            mode = 'breakout'
            # 涨幅（突破日-3%~9%最佳，允许回调蓄势；9~12%次之）
            if -3 <= change_pct <= 9:
                scores_breakdown['change'] = 2
                score += 2
            elif 9 < change_pct <= 12:
                scores_breakdown['change'] = 1
                score += 1
            else:
                scores_breakdown['change'] = 0

            # 量能（放量突破，≥80%即认可）
            if vol_ratio >= 150:
                scores_breakdown['volume'] = 3
                score += 3
            elif vol_ratio >= 120:
                scores_breakdown['volume'] = 2
                score += 2
            elif vol_ratio >= 80:
                scores_breakdown['volume'] = 1
                score += 1
            else:
                scores_breakdown['volume'] = 0

            # 突破强度（越接近20日高点越好）
            if distance_to_high_20 <= 1:
                scores_breakdown['breakout'] = 2
                score += 2
            elif distance_to_high_20 <= 3:
                scores_breakdown['breakout'] = 1
                score += 1
            else:
                scores_breakdown['breakout'] = 0

            # 上影线不能太长，避免冲高回落
            if upper_shadow <= 2:
                scores_breakdown['upper_shadow'] = 1
                score += 1
            else:
                scores_breakdown['upper_shadow'] = 0

        if mode is None:
            return None

        # 公共评分项
        # RSI（30~55 最佳；突破型可放宽到70，回踩型可放宽到65）
        if 30 <= rsi <= 55:
            scores_breakdown['rsi'] = 1
            score += 1
        elif mode == 'breakout' and 55 < rsi <= 70:
            scores_breakdown['rsi'] = 1
            score += 1
        elif mode == 'pullback' and 55 < rsi <= 65:
            scores_breakdown['rsi'] = 1
            score += 1
        else:
            scores_breakdown['rsi'] = 0

        # 偏离度（回踩型贴线最好；突破型允许偏离大一些）
        if 0 < deviation <= 3:
            scores_breakdown['deviation'] = 2
            score += 2
        elif 3 < deviation <= 10:
            scores_breakdown['deviation'] = 1
            score += 1
        elif mode == 'breakout' and 10 < deviation <= 20:
            scores_breakdown['deviation'] = 1
            score += 1
        else:
            scores_breakdown['deviation'] = 0

        # 及格线：≥5分入选
        if score < 5:
            return None

        return {
            'strategy': '白虎V3',
            'mode': mode,
            'score': score,
            '20day_gain': round(recent_20day_gain, 2),
            'deviation': round(deviation, 2),
            'change_pct': round(change_pct, 2),
            'rsi': round(rsi, 2),
            'vol_ratio': round(vol_ratio, 2),
            'lower_shadow': round(lower_shadow, 2),
            'distance_to_high_20': round(distance_to_high_20, 2),
            'ma20': round(ma20, 2),
            'ma10': round(ma10, 2),
            'ma5': round(ma5, 2),
            'close': round(close, 2),
            'date': latest.get('day', ''),
            'scores': scores_breakdown,
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
        ma10_sum = 0.0
        ma5_sum = 0.0
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
            ma10_sum += close
            ma5_sum += close
            if len(closes_history) > 20:
                ma20_sum -= closes_history[-21]
            if len(closes_history) > 10:
                ma10_sum -= closes_history[-11]
            if len(closes_history) > 5:
                ma5_sum -= closes_history[-6]
            ma20 = ma20_sum / 20.0 if len(closes_history) >= 20 else 0.0
            ma10 = ma10_sum / 10.0 if len(closes_history) >= 10 else 0.0
            ma5 = ma5_sum / 5.0 if len(closes_history) >= 5 else 0.0
            kline.append({
                'close': close, 'open': open_p, 'high': high, 'low': low,
                'volume': volume,
                'ma_price20': ma20 if ma20 > 0 else None,
                'ma_price10': ma10 if ma10 > 0 else None,
                'ma_price5': ma5 if ma5 > 0 else None,
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
                logger.debug(f'[baihu_v30] pytdx disconnect 失败: {e}')


def run_baihu_v30_screen(stock_list, trade_date=None, max_workers=20):
    """批量执行白虎V3.0选股（线程池并发，复用 baihu.py 同款逻辑）"""
    import concurrent.futures

    def _screen_one(ts_code):
        try:
            kline = get_kline_from_tdx(ts_code, 360)
            if kline and len(kline) >= 30:
                result = baihu_strategy_v30(kline)
                if result:
                    result['ts_code'] = ts_code
                    if trade_date:
                        result['trade_date'] = trade_date
                    return result
        except Exception:
            logger.debug(f"run_baihu_v30_screen _screen_one failed {ts_code}", exc_info=True)
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
                logger.debug("run_baihu_v30_screen future failed", exc_info=True)
    return results


if __name__ == "__main__":
    print("=" * 80)
    print("🐯 白虎 V3.0 - 科创板/创业板适配版")
    print("=" * 80)
    sample = ['sz301171']
    hits = run_baihu_v30_screen(sample)
    for h in hits:
        print(f"✅ {h['ts_code']} 评分{h['score']} 偏离{h['deviation']}% 量比{h['vol_ratio']}%")