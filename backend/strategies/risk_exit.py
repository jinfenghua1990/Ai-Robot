#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🛡️ 风险退出模块 - 从 wave_band 卖出信号独立出来

卖出信号（任一触发即预警）：
1. 单日跌幅 > 5%（止损线）
2. RSI6 > 75 且收盘跌破 MA5（短线见顶）
3. 收盘跌破 MA10 × 97%（趋势走坏）

定位：不是选股策略，而是持仓风险预警模块。
    不产生"买入"信号，只产生"退出/减仓"预警。
    在个股详情页和自选股列表展示。
"""
import logging

logger = logging.getLogger(__name__)


def risk_exit_check(kline, day_index=-1):
    """
    风险退出检查

    参数:
        kline: K线数据列表（oldest-first），每个元素含 close/open/low/high/volume 字段
        day_index: 检查哪一天（默认-1，最新一天）

    返回:
        有风险信号返回 dict，无信号返回 None
    """
    try:
        if day_index == -1:
            day_index = len(kline) - 1
        if day_index < 0 or day_index >= len(kline) or len(kline) < 21:
            return None

        closes = [float(k['close']) for k in kline]
        last_close = closes[-1]

        # 计算 MA
        ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
        ma10 = sum(closes[-10:]) / 10 if len(closes) >= 10 else None

        # 计算 RSI6
        from strategies.baihu_v30 import calc_rsi
        rsi6 = calc_rsi(closes, period=6)

        # 当日涨幅
        change_pct = ((last_close - closes[-2]) / closes[-2] * 100) if len(closes) >= 2 else 0

        # 逐条检查退出信号
        signals = []

        if change_pct < -5:
            signals.append({
                'type': 'stop_loss',
                'severity': 'critical',
                'label': '止损',
                'reason': f'单日跌幅 {change_pct:.2f}%，触发止损',
            })

        if rsi6 is not None and rsi6 > 75 and ma5 and last_close < ma5:
            signals.append({
                'type': 'overbought',
                'severity': 'warning',
                'label': '见顶预警',
                'reason': f'RSI6={rsi6:.1f}>75 + 跌破MA5({ma5:.2f})，短线见顶',
            })

        if ma10 and last_close < ma10 * 0.97:
            signals.append({
                'type': 'trend_broken',
                'severity': 'warning',
                'label': '趋势走坏',
                'reason': f'收盘 {last_close:.2f} 跌破MA10×97%({ma10:.2f})，趋势走坏',
            })

        if not signals:
            return None

        # 严重度排序：critical > warning
        severity_order = {'critical': 0, 'warning': 1}
        signals.sort(key=lambda s: severity_order.get(s['severity'], 9))

        return {
            'strategy': '风险退出',
            'signal': 'sell',
            'score': 0,  # 退出模块不做评分
            'signals': signals,
            'worst_severity': signals[0]['severity'],
            'worst_label': signals[0]['label'],
            'worst_reason': signals[0]['reason'],
            'ma5': round(ma5, 2) if ma5 else None,
            'ma10': round(ma10, 2) if ma10 else None,
            'rsi6': round(rsi6, 2) if rsi6 is not None else None,
            'change_pct': round(change_pct, 2),
            'close': round(last_close, 2),
            'date': kline[-1].get('day', ''),
        }
    except Exception:
        logger.debug('risk_exit_check failed', exc_info=True)
        return None


def run_risk_exit_screen(stock_list, trade_date=None):
    """批量执行风险退出检查

    参数:
        stock_list: ts_code 列表
        trade_date: 交易日期（可选）

    返回:
        有风险信号的股票结果列表
    """
    from strategies.baihu_v30 import get_kline_from_tdx
    results = []
    for ts_code in stock_list:
        kline = get_kline_from_tdx(ts_code, days=30)
        if kline and len(kline) >= 21:
            result = risk_exit_check(kline)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                results.append(result)
    return results


if __name__ == '__main__':
    print('🛡️ 风险退出模块 - 测试')
    sample = ['sz301171', 'sh603211']
    hits = run_risk_exit_screen(sample)
    for h in hits:
        print(f"  ⚠️ {h['ts_code']} {h['worst_label']}: {h['worst_reason']}")
