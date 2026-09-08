"""
股价购买力评分（100分制）
5维度加权: 流动性 + 价格位置 + 资金流入 + 板块热度 + 技术形态
高分 = 强购买力（可放心买的大资金标的）
低分 = 杂毛（小市值/低流动性/冷门板块/技术破位）
"""
from typing import Optional


def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def _score_volume(volume_ratio: float) -> float:
    """
    流动性分（30%权重）
    volume_ratio = 当前成交量 / 5日均量
    1.0 = 平均；1.5 = 放量；0.5 = 缩量
    """
    if volume_ratio is None:
        return 50  # 无数据给中性分
    # 0.3倍→0分，1.0倍→50分，1.5倍→75分，2.5倍→100分
    if volume_ratio < 0.3:
        return 0
    if volume_ratio < 1.0:
        return _clamp(50 * (volume_ratio - 0.3) / 0.7)
    if volume_ratio < 2.5:
        return _clamp(50 + 50 * (volume_ratio - 1.0) / 1.5)
    return 100


def _score_price_position(price_pos_pct: float) -> float:
    """
    价格位置分（25%权重）
    price_pos_pct = (现价 - 20日最低) / (20日最高 - 20日最低) * 100
    0 = 20日最低（潜在底部）；50 = 中位；100 = 20日最高（追高风险）
    理想买点：30-70 分（突破中位但未到顶）
    """
    if price_pos_pct is None:
        return 50
    # 30-70 区间给高分，两端给低分
    if price_pos_pct < 10:
        return _clamp(price_pos_pct * 2)  # 0-10 → 0-20
    if price_pos_pct < 30:
        return _clamp(20 + (price_pos_pct - 10) * 2)  # 10-30 → 20-60
    if price_pos_pct < 70:
        return _clamp(60 + (price_pos_pct - 30) * 1.0)  # 30-70 → 60-100
    if price_pos_pct < 90:
        return _clamp(100 - (price_pos_pct - 70) * 2.5)  # 70-90 → 100-50
    return _clamp(50 - (price_pos_pct - 90) * 5)  # 90-100 → 50-0


def _score_money_flow(net_flow_pct: float) -> float:
    """
    资金流入分（20%权重）
    net_flow_pct = 主力净流入 / 流通市值 * 100（百分比）
    >0 流入；<0 流出
    """
    if net_flow_pct is None:
        return 50
    # -2% → 0分，0% → 50分，+2% → 100分
    return _clamp(50 + net_flow_pct * 25)


def _score_sector_heat(heat: float) -> float:
    """
    板块热度分（15%权重）
    heat = 板块最新热度（0-100）
    """
    if heat is None or heat <= 0:
        return 30
    return _clamp(heat)


def _score_tech(ma_bull: bool, macd_golden: bool, kdj_zone: str) -> float:
    """
    技术形态分（10%权重）
    ma_bull: MA5 > MA20 (多头排列)
    macd_golden: MACD 金叉
    kdj_zone: 'overbought' | 'oversold' | 'middle'（超买/超卖/中位）
    """
    score = 50
    if ma_bull:
        score += 20
    if macd_golden:
        score += 15
    if kdj_zone == 'middle':
        score += 15
    elif kdj_zone == 'oversold':
        score += 5
    # 超买不加分
    return _clamp(score)


def calculate_buy_power(
    volume_ratio: Optional[float] = None,
    price_pos_pct: Optional[float] = None,
    net_flow_pct: Optional[float] = None,
    sector_heat: Optional[float] = None,
    ma_bull: bool = False,
    macd_golden: bool = False,
    kdj_zone: str = 'middle',
) -> dict:
    """
    计算股价购买力评分（100分制）

    返回 dict: { score, level, dimensions: {...} }
    """
    vol = _score_volume(volume_ratio)
    pos = _score_price_position(price_pos_pct)
    flow = _score_money_flow(net_flow_pct)
    heat = _score_sector_heat(sector_heat)
    tech = _score_tech(ma_bull, macd_golden, kdj_zone)

    score = vol * 0.30 + pos * 0.25 + flow * 0.20 + heat * 0.15 + tech * 0.10
    score = round(score, 1)

    if score >= 80:
        level = '极强'
        color = '#ef4444'
    elif score >= 65:
        level = '强'
        color = '#f97316'
    elif score >= 50:
        level = '中'
        color = '#eab308'
    elif score >= 35:
        level = '弱'
        color = '#3b82f6'
    else:
        level = '极弱'
        color = '#6b7280'

    return {
        'score': score,
        'level': level,
        'color': color,
        'dimensions': {
            'volume': round(vol, 1),
            'position': round(pos, 1),
            'flow': round(flow, 1),
            'heat': round(heat, 1),
            'tech': round(tech, 1),
        },
    }


def is_junk_stock(
    stock_name: str = '',
    list_days: Optional[int] = None,
    market_cap: Optional[float] = None,
    avg_turnover: Optional[float] = None,
    sector_heat: Optional[float] = None,
    consecutive_decline_days: int = 0,
) -> dict:
    """
    检测是否为"杂毛"（不可重仓的标的）

    满足任一即标记:
    1. ST 类（股票名含「ST」）
    2. 次新股（上市<60天）
    3. 小市值（<50亿）
    4. 低流动性（日均成交<1亿）
    5. 冷门板块（热度<30）
    6. 连续阴跌（≥3天连续下跌）

    返回: { is_junk: bool, reasons: [str], junk_score: 0-100 (越高越杂毛) }
    """
    reasons = []
    score = 0  # 杂毛分（越高越差）

    # 1. ST
    if 'ST' in (stock_name or '').upper():
        reasons.append('ST')
        score += 30

    # 2. 次新股
    if list_days is not None and list_days < 60:
        reasons.append(f'次新({list_days}天)')
        score += 15

    # 3. 小市值
    if market_cap is not None and market_cap < 50:
        reasons.append(f'小市值({market_cap:.0f}亿)')
        score += 20

    # 4. 低流动性（成交额=0 视为数据缺失，跳过判定）
    if avg_turnover is not None and avg_turnover > 0 and avg_turnover < 1:
        reasons.append(f'低成交({avg_turnover:.2f}亿)')
        score += 25

    # 5. 冷门板块（热度=0 视为数据缺失，跳过判定）
    if sector_heat is not None and sector_heat > 0 and sector_heat < 30:
        reasons.append(f'冷板块(热度{sector_heat:.0f})')
        score += 10

    # 6. 连续阴跌
    if consecutive_decline_days >= 3:
        reasons.append(f'连跌{consecutive_decline_days}天')
        score += 15

    return {
        'is_junk': len(reasons) > 0,
        'reasons': reasons,
        'junk_score': min(score, 100),
    }


def calc_buy_power_for_signal(quote: dict, sector_trend: dict, bs_signal: str = None) -> dict:
    """根据 quote + sector_trend + bs_signal 计算购买力评分（100分制）
    与自选股/模拟盘共用的统一入口，确保两端数据维度一致。
    - quote: 新浪实时行情 dict（可为 None，退化为中性分）
    - sector_trend: 板块趋势 dict（含 latest_heat, available）
    - bs_signal: 'B' | 'S' | None（SuperTrend 信号，None 时 ma_bull/macd_golden 为 False）
    """
    if not quote:
        return calculate_buy_power()
    change_pct = quote.get('changePct', 0) or 0
    price_pos_pct = max(0, min(100, 50 + change_pct * 5))  # ±10%→0-100
    sector_heat = sector_trend.get('latest_heat', 0) if sector_trend.get('available') else 0
    ma_bull = bs_signal == 'B'
    macd_golden = bs_signal == 'B'
    kdj_zone = 'middle' if 20 < sector_heat < 80 else 'overbought' if sector_heat >= 80 else 'oversold'
    return calculate_buy_power(
        volume_ratio=1.0,            # 新浪行情无 volume_ratio，与自选股口径一致
        price_pos_pct=price_pos_pct,
        net_flow_pct=0,              # 新浪行情无 main_net_inflow_pct，与自选股口径一致
        sector_heat=sector_heat,
        ma_bull=ma_bull,
        macd_golden=macd_golden,
        kdj_zone=kdj_zone,
    )
