"""组合风控引擎
- 单票风险 ≤ 2%（position_engine 已保证）
- 总仓位 ≤ 30-50%（情绪退潮降仓）
- 高位股禁止重仓：连板≥4 或 偏离MA20>15% → 仓位上限 3%
"""
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# 情绪 → 总仓位上限映射
SENTIMENT_TOTAL_CAP = {
    '恐慌': 30.0, '谨慎': 30.0,
    '中性': 40.0,
    '乐观': 50.0,
    '狂热': 30.0,
}

HIGH_POSITION_MAX_PCT = 3.0


def is_high_position_stock(signal: dict) -> Tuple[bool, str]:
    """判断是否高位股
    - 连板 ≥ 4（lifecycle stage == '主升' 且 consecutive_days ≥ 4）
    - 偏离 MA20 > 15%（close_vs_ma20 > 0.15）
    """
    lifecycle = signal.get('lifecycleStage', '')
    consecutive = (signal.get('position') or {}).get('count', 0) or 0
    features = (signal.get('marketState') or {}).get('features') or {}
    close_vs_ma20 = features.get('close_vs_ma20', 0) or 0

    if lifecycle == '主升' and consecutive >= 4:
        return True, f'{consecutive}连板高位'
    if close_vs_ma20 > 0.15:
        return True, f'偏离MA20 {close_vs_ma20*100:.1f}%高位'
    return False, ''


def assess_portfolio_risk(
    signals_4: List[dict],
    market_sentiment: str = '中性',
) -> Dict:
    """组合风控评估
    输入：当日所有候选股票的 4.0 信号列表（每项含 signal_raw, signal_4, final_score, position_pct）
    输出：风控状态 + 总仓位建议 + 各股风控调整
    """
    total_cap = SENTIMENT_TOTAL_CAP.get(market_sentiment, 40.0)

    buyable = [s for s in signals_4 if s.get('signal_4') in ('STRONG_BUY', 'WATCH_BUY')]
    buyable.sort(key=lambda x: (
        -1 if x['signal_4'] == 'STRONG_BUY' else 0,
        -x.get('final_score', 0),
    ))

    total_position_pct = 0.0
    adjusted = []
    warnings = []

    for sig in buyable:
        original_pct = sig.get('position_pct', 0)
        raw = sig.get('signal_raw') or {}
        is_high, reason = is_high_position_stock(raw)

        if is_high:
            original_pct = min(original_pct, HIGH_POSITION_MAX_PCT)
            warnings.append(f'{sig.get("name", sig.get("ts_code", ""))} 高位股({reason})，仓位降至{original_pct}%')
            sig['risk_status'] = 'warn'
            sig['risk_reasons'] = [reason]
        else:
            sig['risk_status'] = 'ok'
            sig['risk_reasons'] = []

        remaining = total_cap - total_position_pct
        if remaining <= 0:
            warnings.append(f'总仓位已达{total_cap}%上限，{sig.get("name", sig.get("ts_code", ""))}不再分配')
            sig['position_pct'] = 0
            sig['position_amount'] = 0
            sig['risk_status'] = 'forbid'
            sig['risk_reasons'] = ['总仓位已满']
            adjusted.append(sig)
            continue

        final_pct = min(original_pct, remaining)
        total_position_pct += final_pct
        sig['position_pct'] = round(final_pct, 2)
        sig['position_amount'] = round(final_pct * 10000, 2)
        adjusted.append(sig)

    return {
        'total_position_pct': round(total_position_pct, 2),
        'total_cap_pct': total_cap,
        'sentiment': market_sentiment,
        'buyable_count': len(buyable),
        'warnings': warnings,
        'adjusted_signals': adjusted,
    }
