"""US Quant System — 市场环境引擎

5种市场状态：
  STRONG_BREADTH       — 强势普涨
  LEADER_CONCENTRATION  — 龙头集中
  HIGH_LEVEL_RANGE      — 高位震荡
  WEAK_REBOUND          — 弱势反弹
  RISK_OFF              — 风险回避

从 SPY/QQQ/IWM/RSP/VIX 等 ETF 判断。
"""

from __future__ import annotations

from typing import Optional

from .contracts import IndexQuote, MarketRegime


def assess_market_regime(
    spy: Optional[IndexQuote] = None,
    qqq: Optional[IndexQuote] = None,
    iwm: Optional[IndexQuote] = None,
    rsp: Optional[IndexQuote] = None,
    vix: Optional[float] = None,
    advancers_pct: Optional[float] = None,  # 上涨股票占比 0-100
    new_high_pct: Optional[float] = None,   # 新高股票占比 0-100
) -> MarketRegime:
    """
    评估市场环境状态。
    各参数可空，缺失时使用默认值（保守估计）。
    """
    # 默认值（保守）
    spy = spy or IndexQuote(symbol="SPY", name="SPY", price=0, change_pct=0)
    qqq = qqq or IndexQuote(symbol="QQQ", name="QQQ", price=0, change_pct=0)
    iwm = iwm or IndexQuote(symbol="IWM", name="IWM", price=0, change_pct=0)
    rsp = rsp or IndexQuote(symbol="RSP", name="RSP", price=0, change_pct=0)
    vix = vix or 20.0
    advancers_pct = advancers_pct if advancers_pct is not None else 50.0
    new_high_pct = new_high_pct if new_high_pct is not None else 50.0

    # 计算各维度
    spy_above_ma20 = spy.ma20 is not None and spy.price > spy.ma20
    qqq_above_ma20 = qqq.ma20 is not None and qqq.price > qqq.ma20
    rsp_above_ma20 = rsp.ma20 is not None and rsp.price > rsp.ma20
    spy_ma20_up = spy.ma20 is not None and spy.ma50 is not None and spy.ma20 > spy.ma50

    # 市场宽度
    breadth_ok = advancers_pct > 50.0
    new_high_ok = new_high_pct > 10.0

    # VIX 风险
    vix_low = vix < 20.0
    vix_medium = 20.0 <= vix < 30.0
    vix_high = vix >= 30.0

    # 强弱对比
    rsp_weak = rsp.ma20 is not None and (rsp.price <= rsp.ma20 * 0.98)
    iwm_weak = iwm.ma20 is not None and (iwm.price <= iwm.ma20 * 0.98)

    # ─── 判断市场状态 ─────────────────────────────────────────────────────────

    # RISK_OFF: 破位 + 宽度恶化 + 高VIX
    if (not spy_above_ma20 or not qqq_above_ma20) and (vix_high or not breadth_ok):
        return MarketRegime(
            regime="RISK_OFF",
            score=max(0, min(30, _calc_score(0, 0, 0, vix))),
            label="风险回避",
            allow_new_positions=False,
            reason="指数破位 + 市场宽度恶化 + 高VIX，仅允许减仓和平仓",
            breakout_mult=0.0,
            pullback_mult=0.0,
            earnings_gap_mult=0.0,
        )

    # WEAK_REBOUND: 短线反弹但中期弱
    if (spy_above_ma20 or qqq_above_ma20) and (not rsp_above_ma20 or iwm_weak) and (vix_medium or not breadth_ok):
        return MarketRegime(
            regime="WEAK_REBOUND",
            score=31.50,
            label="弱势反弹",
            allow_new_positions=True,
            reason="短线反弹但中期趋势未修复，宽度未确认",
            breakout_mult=0.0,
            pullback_mult=0.30,
            earnings_gap_mult=0.30,
        )

    # HIGH_LEVEL_RANGE: 指数高位 + 波动扩大
    if spy_above_ma20 and qqq_above_ma20 and (not breadth_ok or not new_high_ok) and (vix_medium or iwm_weak):
        return MarketRegime(
            regime="HIGH_LEVEL_RANGE",
            score=51.65,
            label="高位震荡",
            allow_new_positions=True,
            reason="指数高位，波动扩大，市场宽度下降",
            breakout_mult=0.40,
            pullback_mult=0.70,
            earnings_gap_mult=0.40,
        )

    # LEADER_CONCENTRATION: 指数涨但宽度弱
    if (spy_above_ma20 or qqq_above_ma20) and (rsp_weak or iwm_weak) and (not breadth_ok or not new_high_ok):
        return MarketRegime(
            regime="LEADER_CONCENTRATION",
            score=52.75,
            label="龙头集中",
            allow_new_positions=True,
            reason="指数上涨但宽度不足，上涨集中于少数大盘龙头",
            breakout_mult=0.70,
            pullback_mult=0.80,
            earnings_gap_mult=0.60,
        )

    # STRONG_BREADTH: 强势普涨
    if spy_above_ma20 and qqq_above_ma20 and rsp_above_ma20 and spy_ma20_up and breadth_ok and new_high_ok and vix_low:
        return MarketRegime(
            regime="STRONG_BREADTH",
            score=85.90,
            label="强势普涨",
            allow_new_positions=True,
            reason="指数趋势向上，市场宽度改善，多数行业上涨",
            breakout_mult=1.0,
            pullback_mult=1.0,
            earnings_gap_mult=1.0,
        )

    # 默认：中性震荡
    return MarketRegime(
        regime="HIGH_LEVEL_RANGE",
        score=50.50,
        label="中性震荡",
        allow_new_positions=True,
        reason="市场中性震荡，各维度信号不明确",
        breakout_mult=0.50,
        pullback_mult=0.60,
        earnings_gap_mult=0.50,
    )


def _calc_score(trend: float, breadth: float, vix_score: float, vix: float) -> float:
    """计算综合评分"""
    vix_part = max(0, 100 - vix * 3)  # VIX 越低分越高
    return round((trend * 0.4 + breadth * 0.3 + vix_part * 0.3), 1)


def get_regime_multipliers(regime: str) -> dict[str, float]:
    """获取各策略在当前市场状态下的乘数"""
    mults = {
        "STRONG_BREADTH": {"breakout": 1.0, "pullback": 1.0, "earnings_gap": 1.0},
        "LEADER_CONCENTRATION": {"breakout": 0.70, "pullback": 0.80, "earnings_gap": 0.60},
        "HIGH_LEVEL_RANGE": {"breakout": 0.40, "pullback": 0.70, "earnings_gap": 0.40},
        "WEAK_REBOUND": {"breakout": 0.0, "pullback": 0.30, "earnings_gap": 0.30},
        "RISK_OFF": {"breakout": 0.0, "pullback": 0.0, "earnings_gap": 0.0},
    }
    return mults.get(regime, {"breakout": 0.5, "pullback": 0.5, "earnings_gap": 0.5})