#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一数据源层。

原先 get_kline_from_tdx / _parse_ts_code 都寄生在 baihu_v30.py 中，
导致其余 5 个选股策略全部依赖 baihu_v30（无法独立删除/重构）。
现收敛到本模块，所有选股策略统一从此处获取 K 线，换数据源只改这一处。
"""
import logging

logger = logging.getLogger(__name__)


def _parse_ts_code(ts_code):
    """将 ts_code（含/不含交易所后缀）解析为 (market, pure_code) 二元组。

    market: 0=深圳, 1=上海；无法识别返回 (None, None)。
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
    if code.isdigit():
        return (1, code) if code.startswith('6') else (0, code)
    return None, None


def get_kline_from_tdx(code, days=90):
    """从 TDX collector 拉取单只股票日 K 线。

    返回 oldest-first 的 K 线列表，每元素含
    close/open/high/low/volume/ma_price20/ma_price10/ma_price5/day。
    拉取失败或数据不足时返回 None。
    """
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
        logger.debug(f"get_kline_from_tdx failed", exc_info=True)
        return None
    finally:
        if api:
            try:
                api.disconnect()
            except Exception as e:
                logger.debug(f'[data_feed] pytdx disconnect 失败: {e}')
