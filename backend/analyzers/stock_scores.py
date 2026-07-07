"""个股状态评分引擎

6 个维度，每个返回 {stage, score}:
- 情绪温度 (sentiment): 恐慌→谨慎→中性→乐观→狂热
- 资金动能 (momentum): 流出→弱流→平衡→流入→强入（板块资金面）
- 主力资金 (mainForce): 减仓→观望→平衡→建仓→强仓（个股主力资金专项）
- 技术形态 (technical): 破位→弱势→震荡→偏多→多头
- 板块共振 (sector): 冷门→跟随→联动→协同→共振
- 风险等级 (risk): 安全→低危→中等→高危→极危

5段状态一致性标准：
- 所有 5 段指标统一使用 20/40/60/80 分界线
- 0-20: 极弱/极差/极 negative；20-40: 弱/差；40-60: 中性/平衡；
  60-80: 强/积极；80-100: 极强/极积极
- 风险等级为反向指标：低分=安全，高分=危险
"""
import math
from typing import Optional, Dict


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def _norm(raw, lo, hi):
    """归一化到 0-100"""
    if raw is None:
        return 50
    return _clamp((raw - lo) / (hi - lo) * 100)


def _score_to_stage(score: int, stages: list) -> dict:
    """0-100 分映射到 N 段阶段（等比分界）"""
    n = len(stages)
    if n <= 1:
        return {'stage': stages[0] if stages else '', 'score': score}
    step = 100 / n
    idx = min(int(score / step), n - 1)
    return {
        'stage': stages[idx],
        'score': score,
    }


# ===== 7 段阶段定义（统一标准）=====
SENTIMENT_STAGES = ['冰点', '恐慌', '谨慎', '中性', '乐观', '狂热', '过热']
RISK_STAGES = ['极安', '安全', '低危', '中等', '高危', '极危', '崩盘']
MOMENTUM_STAGES = ['暴跌', '流出', '弱流', '平衡', '流入', '强入', '暴入']
MAIN_FORCE_STAGES = ['出逃', '减仓', '观望', '平衡', '建仓', '强仓', '锁仓']
TECHNICAL_STAGES = ['破位', '弱势', '震荡', '偏多', '多头', '突破', '顶部']
SECTOR_STAGES = ['冷门', '跟随', '联动', '协同', '共振', '领涨', '极热']


def calc_sentiment(quote: Optional[dict], sector_trend: Optional[dict],
                   features: Optional[dict]) -> Optional[dict]:
    """情绪温度：综合涨跌、板块热度、资金方向、量比"""
    if not quote and not sector_trend:
        return None

    change_pct = quote.get('changePct', 0) if quote else 0
    heat = sector_trend.get('latest_heat', 50) if sector_trend and sector_trend.get('available') else 50
    flow_dir = sector_trend.get('flow_direction', '') if sector_trend else ''
    vol_ratio = features.get('volume_ratio', 1.0) if features else 1.0

    score = (
        _norm(change_pct, -10, 10) * 0.3 +
        _norm(heat, 0, 100) * 0.3 +
        (80 if flow_dir == 'inflow' else 20 if flow_dir == 'outflow' else 50) * 0.2 +
        _norm(vol_ratio, 0, 3) * 0.2
    )
    return _score_to_stage(round(_clamp(score)), SENTIMENT_STAGES)


def calc_risk(features: Optional[dict], buy_power: Optional[dict],
              position: Optional[dict]) -> Optional[dict]:
    """风险等级：噪声比、ATR、仓位集中度、持仓比例（反向指标：低分=安全）"""
    if not features and not buy_power and not position:
        return None

    noise = features.get('noise_ratio', 1.0) if features else 1.0
    atr_pct = features.get('atr_pct', 0.03) if features else 0.03
    pos_score = (buy_power.get('dimensions', {}).get('position', 50)
                 if buy_power and buy_power.get('dimensions') else 50)
    pos_pct = position.get('posPct', 0) if position else 0

    # 风险分 = 高噪声 + 高波动 + 低形态 + 高仓位 → 分数越高越危险
    score = (
        _norm(noise, 0, 3) * 0.3 +
        _norm(atr_pct, 0, 0.1) * 0.3 +
        (100 - pos_score) * 0.2 +
        _norm(pos_pct, 0, 100) * 0.2
    )
    return _score_to_stage(round(_clamp(score)), RISK_STAGES)


def calc_momentum(sector_trend: Optional[dict],
                  features: Optional[dict]) -> Optional[dict]:
    """资金动能（板块资金面）：板块净流入、资金方向、3日主力流入、资金连续性"""
    if not sector_trend and not features:
        return None

    net_flow = sector_trend.get('total_net_flow', 0) if sector_trend and sector_trend.get('available') else 0
    flow_dir = sector_trend.get('flow_direction', '') if sector_trend else ''
    inflow_3d = features.get('main_net_inflow_3d', 0) if features else 0
    continuity = features.get('flow_continuity', 0) if features else 0

    score = (
        _norm(net_flow / 10000, -50, 50) * 0.3 +
        (80 if flow_dir == 'inflow' else 20 if flow_dir == 'outflow' else 50) * 0.2 +
        _norm(inflow_3d / 10000, -30, 30) * 0.3 +
        _norm(continuity, 0, 10) * 0.2
    )
    return _score_to_stage(round(_clamp(score)), MOMENTUM_STAGES)


def calc_main_force(quote: Optional[dict], features: Optional[dict],
                    sector_trend: Optional[dict]) -> Optional[dict]:
    """主力资金专项：主力资金流向、持仓变化、大单交易特征

    独立于板块资金动能，聚焦个股层面的主力行为：
    - 3日主力净流入强度（主力资金流向）
    - 资金连续性（持仓变化趋势，连续流入天数）
    - 量比放大（大单交易活跃度代理指标）
    - 涨跌配合度（量价齐升=主力建仓，量增价跌=主力减仓）
    """
    if not features and not quote:
        return None

    inflow_3d = features.get('main_net_inflow_3d', 0) if features else 0
    continuity = features.get('flow_continuity', 0) if features else 0
    vol_ratio = features.get('volume_ratio', 1.0) if features else 1.0
    change_pct = quote.get('changePct', 0) if quote else 0

    # 量价配合度：量增+价涨=建仓(高)；量增+价跌=减仓(低)
    if vol_ratio > 1.5 and change_pct > 0:
        vp_score = 80
    elif vol_ratio > 1.5 and change_pct < -1:
        vp_score = 20
    elif vol_ratio < 0.8:
        vp_score = 40  # 缩量，主力不活跃
    else:
        vp_score = 50

    # 连续性：>3天=强趋势，<0天=反向
    if continuity >= 5:
        cont_score = 90
    elif continuity >= 3:
        cont_score = 75
    elif continuity >= 1:
        cont_score = 60
    elif continuity == 0:
        cont_score = 50
    elif continuity >= -2:
        cont_score = 30
    else:
        cont_score = 15

    score = (
        _norm(inflow_3d / 10000, -30, 30) * 0.35 +
        cont_score * 0.25 +
        _norm(vol_ratio, 0, 3) * 0.15 +
        vp_score * 0.25
    )
    return _score_to_stage(round(_clamp(score)), MAIN_FORCE_STAGES)


def _technical_score_to_stage(score: int, features: Optional[dict]) -> dict:
    """7段技术形态映射：基础 5 段按分数，突破/顶部按条件覆盖"""
    if not features:
        return _score_to_stage(score, TECHNICAL_STAGES[:5])

    rsi = features.get('rsi_14', 50) or 50
    vol_ratio = features.get('volume_ratio', 1.0) or 1.0
    close_vs_ma20 = features.get('close_vs_ma20', 0) or 0
    higher_high = features.get('higher_high_flag', 0)

    # 顶部：RSI>=70 且量价背离（量大但 close_vs_ma20 收窄）
    if rsi >= 70 and vol_ratio > 1.5 and close_vs_ma20 < 0.05:
        return {'stage': '顶部', 'score': score}
    # 突破：多头（score>=75）且新高突破且量能放大
    if score >= 75 and higher_high == 1 and vol_ratio > 1.2:
        return {'stage': '突破', 'score': score}
    # 否则按 5 段映射（取前 5 段）
    return _score_to_stage(score, TECHNICAL_STAGES[:5])


def calc_technical(features: Optional[dict]) -> Optional[dict]:
    """技术形态：新高新低、趋势一致性、均线位置、均线斜率、RSI、量价配合（7段）"""
    if not features:
        return None

    hh = 1 if features.get('higher_high_flag') else 0
    hl = 1 if features.get('higher_low_flag') else 0
    consistency = features.get('trend_consistency_score', 50)
    close_vs_ma20 = features.get('close_vs_ma20', 0)
    ma20_slope = features.get('ma20_slope', 0)

    score = (
        hh * 20 +
        hl * 20 +
        _norm(consistency, 0, 100) * 0.3 +
        _norm(close_vs_ma20, -0.1, 0.1) * 0.15 +
        _norm(ma20_slope, -2, 2) * 0.15
    )
    return _technical_score_to_stage(round(_clamp(score)), features)


def calc_sector_resonance(sector_trend: Optional[dict],
                          features: Optional[dict]) -> Optional[dict]:
    """板块共振：板块热度、热度趋势、上涨家数比、板块强度"""
    if not sector_trend or not sector_trend.get('available'):
        return None

    heat = sector_trend.get('latest_heat', 50)
    heat_trend = sector_trend.get('heat_trend', 'stable')
    rise_ratio = sector_trend.get('rise_ratio', 0)
    sector_strength = features.get('sector_strength', 50) if features else 50

    score = (
        _norm(heat, 0, 100) * 0.3 +
        (80 if heat_trend == 'up' else 20 if heat_trend == 'down' else 50) * 0.25 +
        _norm(rise_ratio, -5, 5) * 0.2 +
        _norm(sector_strength, 0, 100) * 0.25
    )
    return _score_to_stage(round(_clamp(score)), SECTOR_STAGES)
