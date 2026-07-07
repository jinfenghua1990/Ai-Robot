"""4.0 信号分级引擎
基于 6 维评分（sentiment/momentum/mainForce/technical/sectorResonance/risk）
+ BS 信号 + 市场状态 + 生命周期 → 强买/观察买/禁止参与
"""
import logging
from typing import Tuple, Dict

logger = logging.getLogger(__name__)

# 信号分级阈值
STRONG_BUY_THRESHOLD = 70
WATCH_BUY_THRESHOLD = 50

# 6 维权重（sum=1.0）
WEIGHTS = {
    'sentiment': 0.20,
    'momentum': 0.20,
    'mainForce': 0.25,
    'technical': 0.15,
    'sector': 0.10,
    'risk': 0.10,  # 反向指标
}


def calc_final_score(signal: dict) -> Tuple[float, Dict[str, float]]:
    """6 维加权计算 final_score（0-100）
    复用 signal 中已计算的 sentiment/momentum/mainForce/technical/sectorResonance/risk
    risk 是反向指标（高分=危险），转换为正向：100 - risk.score
    返回 (final_score, score_detail)
    """
    s = (signal.get('sentiment') or {}).get('score', 50)
    m = (signal.get('momentum') or {}).get('score', 50)
    mf = (signal.get('mainForce') or {}).get('score', 50)
    t = (signal.get('technical') or {}).get('score', 50)
    sr = (signal.get('sectorResonance') or {}).get('score', 50)
    r = (signal.get('risk') or {}).get('score', 50)

    risk_positive = 100 - r

    final = (
        s * WEIGHTS['sentiment'] +
        m * WEIGHTS['momentum'] +
        mf * WEIGHTS['mainForce'] +
        t * WEIGHTS['technical'] +
        sr * WEIGHTS['sector'] +
        risk_positive * WEIGHTS['risk']
    )
    detail = {
        'sentiment': round(s, 1),
        'momentum': round(m, 1),
        'mainForce': round(mf, 1),
        'technical': round(t, 1),
        'sector': round(sr, 1),
        'risk': round(r, 1),
    }
    return round(final, 2), detail


def classify_signal_4(signal: dict, final_score: float) -> dict:
    """4.0 信号分级：强买 / 观察买 / 禁止参与
    一票否决条件（即使 final_score 高也降级为禁止参与）：
    - bs_signal == 'S' → 禁止参与
    - market_state == 'CHOPPY' 且 quality_status in ['劣质','中性'] → 禁止参与
    - 生命周期 stage in ['分歧','衰退','退潮'] → 禁止参与
    高危降级：
    - risk.stage in ['高危','极危'] → 降级为观察买
    """
    bs_signal = signal.get('bsSignal')
    market_state = (signal.get('marketState') or {}).get('market_state', '')
    quality = signal.get('qualityStatus', '')
    risk_stage = (signal.get('risk') or {}).get('stage', '')
    lifecycle = signal.get('lifecycleStage', '')

    forbid_reasons = []
    if bs_signal == 'S':
        forbid_reasons.append('BS卖出信号')
    if market_state == 'CHOPPY' and quality in ('劣质', '中性'):
        forbid_reasons.append(f'{market_state}+{quality}杂毛不参与')
    if lifecycle in ('分歧', '衰退', '退潮'):
        forbid_reasons.append(f'生命周期{lifecycle}谨慎参与')

    if forbid_reasons:
        return {
            'signal_4': 'FORBID', 'label': '禁止参与', 'color': '#6b7280',
            'reasons': forbid_reasons,
        }

    if risk_stage in ('高危', '极危'):
        return {
            'signal_4': 'WATCH_BUY', 'label': '观察买', 'color': '#eab308',
            'reasons': [f'风险等级{risk_stage}降级观察'],
        }

    if final_score >= STRONG_BUY_THRESHOLD:
        return {
            'signal_4': 'STRONG_BUY', 'label': '强买', 'color': '#ef4444',
            'reasons': [f'综合评分{final_score:.0f}≥{STRONG_BUY_THRESHOLD}'],
        }
    elif final_score >= WATCH_BUY_THRESHOLD:
        return {
            'signal_4': 'WATCH_BUY', 'label': '观察买', 'color': '#eab308',
            'reasons': [f'综合评分{final_score:.0f}∈[{WATCH_BUY_THRESHOLD},{STRONG_BUY_THRESHOLD})'],
        }
    else:
        return {
            'signal_4': 'FORBID', 'label': '禁止参与', 'color': '#6b7280',
            'reasons': [f'综合评分{final_score:.0f}<{WATCH_BUY_THRESHOLD}'],
        }
