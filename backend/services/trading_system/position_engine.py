"""动态仓位引擎
公式：仓位 = ATR仓位 × 信号强度系数 × 情绪系数 × 板块热度系数
ATR 风险预算法：单股风险 ≤ 总资金 × 2%（2% 法则）
"""
import logging
from typing import Dict

logger = logging.getLogger(__name__)

DEFAULT_TOTAL_CAPITAL = 1_000_000
SINGLE_RISK_PCT = 2.0
MAX_TOTAL_POSITION_PCT = 50.0
MIN_POSITION_PCT = 1.0
MAX_POSITION_PCT = 10.0

SENTIMENT_COEF = {
    '恐慌': 0.3, '谨慎': 0.5, '中性': 0.7, '乐观': 0.9, '狂热': 0.6,
}


def calc_dynamic_position(
    signal: dict,
    signal_4: str,
    final_score: float,
    total_capital: float = DEFAULT_TOTAL_CAPITAL,
    single_risk_pct: float = SINGLE_RISK_PCT,
) -> Dict:
    """动态仓位计算
    1. 信号强度系数：强买 1.0 / 观察买 0.6 / 禁止 0
    2. 情绪系数：恐慌0.3/谨慎0.5/中性0.7/乐观0.9/狂热0.6（退潮降仓）
    3. 板块热度系数：latest_heat / 100，钳制 [0.3, 1.0]
    4. ATR 风险预算法：仓位金额 = (总资金 × 2%) / (ATR% × 1.5乘数)
    5. 最终仓位 = ATR仓位 × 三系数，受单票上下限约束
    6. 止损 = ATR × 1.5 / 价格，钳制 [3%, 10%]
    7. 止盈 = 2 × 止损（1:2 盈亏比）
    """
    if signal_4 == 'FORBID':
        return {
            'position_pct': 0, 'position_amount': 0,
            'stop_loss_pct': 0, 'take_profit_pct': 0,
            'atr_14': 0, 'risk_per_share': 0,
            'coefficients': {}, 'reason': '禁止参与，0仓位',
        }

    price = (signal.get('quote') or {}).get('price', 0)
    if price <= 0:
        return {
            'position_pct': 0, 'position_amount': 0,
            'stop_loss_pct': 0, 'take_profit_pct': 0,
            'atr_14': 0, 'risk_per_share': 0,
            'coefficients': {}, 'reason': '无实时价格',
        }

    # 1. 信号强度系数
    strength_coef = 1.0 if signal_4 == 'STRONG_BUY' else 0.6

    # 2. 情绪系数
    sentiment_stage = (signal.get('sentiment') or {}).get('stage', '中性')
    sentiment_coef = SENTIMENT_COEF.get(sentiment_stage, 0.7)

    # 3. 板块热度系数
    sector_trend = signal.get('sectorTrend') or {}
    heat = sector_trend.get('latest_heat', 50) if sector_trend.get('available') else 50
    sector_coef = max(0.3, min(1.0, heat / 100))

    # 4. ATR 风险预算法
    features = (signal.get('marketState') or {}).get('features') or {}
    atr_14 = features.get('atr_14', 0) or 0
    atr_pct = (atr_14 / price) if price > 0 else 0.03
    atr_multiplier = 1.5

    risk_amount = total_capital * single_risk_pct / 100
    stop_loss_ratio = atr_pct * atr_multiplier
    stop_loss_ratio = max(0.03, min(0.10, stop_loss_ratio))

    atr_position_amount = risk_amount / stop_loss_ratio if stop_loss_ratio > 0 else 0

    # 5. 最终仓位 = ATR仓位 × 三系数
    position_amount = atr_position_amount * strength_coef * sentiment_coef * sector_coef
    position_pct = (position_amount / total_capital * 100) if total_capital > 0 else 0

    # 钳制到上下限
    min_pct = MIN_POSITION_PCT if signal_4 == 'STRONG_BUY' else 0
    position_pct = max(min_pct, min(MAX_POSITION_PCT, position_pct))
    position_amount = total_capital * position_pct / 100

    # 6. 止损止盈
    stop_loss_pct = -stop_loss_ratio * 100
    take_profit_pct = stop_loss_ratio * 2 * 100

    return {
        'position_pct': round(position_pct, 2),
        'position_amount': round(position_amount, 2),
        'stop_loss_pct': round(stop_loss_pct, 2),
        'take_profit_pct': round(take_profit_pct, 2),
        'atr_14': round(atr_14, 3),
        'risk_per_share': round(risk_amount, 2),
        'coefficients': {
            'strength': strength_coef,
            'sentiment': sentiment_coef,
            'sector': round(sector_coef, 2),
        },
    }
