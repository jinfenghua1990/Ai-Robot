"""US Quant System — 行业轮动评分

13个行业ETF评分体系：
  指标                    | 分数
  -----------------------|-----
  5日收益                 | 10
  20日收益                | 20
  60日收益                | 20
  相对SPY 20日强度        | 15
  相对SPY 60日强度        | 15
  均线趋势                | 10
  成交量活跃度            | 10

等级：
  80-100: 强势主线
  70-79:  重点关注
  60-69:  观察
  <60:    不优先
"""

from __future__ import annotations

from typing import Optional

from .contracts import IndexQuote, SectorScore

# 13个行业ETF
SECTOR_ETFS = [
    ("XLK", "科技", "Technology"),
    ("SMH", "半导体", "Semiconductors"),
    ("SOXX", "芯片", "Chips"),
    ("XLC", "通信", "Communication"),
    ("XLY", "消费", "Consumer Cyclical"),
    ("XLF", "金融", "Financial"),
    ("XLI", "工业", "Industrial"),
    ("XLV", "医疗", "Health Care"),
    ("XLE", "能源", "Energy"),
    ("XLB", "材料", "Materials"),
    ("XLP", "必需消费", "Consumer Defensive"),
    ("XLU", "公用事业", "Utilities"),
    ("XLRE", "房地产", "Real Estate"),
]


def score_sector(
    etf_symbol: str,
    etf_name: str,
    industry: str,
    closes_5d: Optional[list[float]] = None,
    closes_20d: Optional[list[float]] = None,
    closes_60d: Optional[list[float]] = None,
    spy_closes_20d: Optional[list[float]] = None,
    spy_closes_60d: Optional[list[float]] = None,
    volumes_20d: Optional[list[float]] = None,
    avg_volume_20d: Optional[float] = None,
    ma20: Optional[float] = None,
    ma50: Optional[float] = None,
    current_price: Optional[float] = None,
    rank: int = 0,
) -> SectorScore:
    """计算单个行业评分"""

    def _ret(closes) -> float:
        if not closes or len(closes) < 2:
            return 0.0
        return (closes[-1] - closes[0]) / closes[0] * 100

    ret_5d = _ret(closes_5d) if closes_5d else 0.0
    ret_20d = _ret(closes_20d) if closes_20d else 0.0
    ret_60d = _ret(closes_60d) if closes_60d else 0.0
    spy_ret_20d = _ret(spy_closes_20d) if spy_closes_20d else 0.0
    spy_ret_60d = _ret(spy_closes_60d) if spy_closes_60d else 0.0

    # 相对强度
    rel_20d = ret_20d - spy_ret_20d if spy_closes_20d else 0.0
    rel_60d = ret_60d - spy_ret_60d if spy_closes_60d else 0.0

    # 均线趋势
    ma_trend = 0.0
    if ma20 and ma50 and current_price:
        if current_price > ma20 > ma50:
            ma_trend = 10.0
        elif current_price > ma20 and ma20 > ma50:
            ma_trend = 8.0
        elif current_price > ma20:
            ma_trend = 6.0
        elif current_price > ma50:
            ma_trend = 4.0
        else:
            ma_trend = 2.0

    # 成交量活跃度
    vol_activity = 0.0
    if volumes_20d and avg_volume_20d and avg_volume_20d > 0:
        recent_avg = sum(volumes_20d) / len(volumes_20d)
        ratio = recent_avg / avg_volume_20d
        if ratio > 1.5:
            vol_activity = 10.0
        elif ratio > 1.2:
            vol_activity = 8.0
        elif ratio > 0.8:
            vol_activity = 6.0
        else:
            vol_activity = 3.0

    # 分项评分
    def _score_ret(v: float, max_ret: float = 10.0) -> float:
        if v > max_ret:
            return 1.0
        return max(0.0, v / max_ret)

    def _score_rel(v: float, max_rel: float = 5.0) -> float:
        if v > max_rel:
            return 1.0
        return max(0.0, v / max_rel)

    score_5d = round(_score_ret(ret_5d, 8.0) * 10, 1)
    score_20d = round(_score_ret(ret_20d, 15.0) * 20, 1)
    score_60d = round(_score_ret(ret_60d, 25.0) * 20, 1)
    score_rel_20d = round(_score_rel(rel_20d, 8.0) * 15, 1)
    score_rel_60d = round(_score_rel(rel_60d, 12.0) * 15, 1)

    total = round(score_5d + score_20d + score_60d + score_rel_20d + score_rel_60d + ma_trend + vol_activity, 1)

    # 等级
    if total >= 80:
        grade = "强势主线"
    elif total >= 70:
        grade = "重点关注"
    elif total >= 60:
        grade = "观察"
    else:
        grade = "不优先"

    return SectorScore(
        etf_symbol=etf_symbol,
        etf_name=etf_name,
        industry=industry,
        ret_5d=round(ret_5d, 2),
        ret_20d=round(ret_20d, 2),
        ret_60d=round(ret_60d, 2),
        rel_strength_20d=round(rel_20d, 2),
        rel_strength_60d=round(rel_60d, 2),
        ma_trend=ma_trend,
        volume_activity=vol_activity,
        total_score=total,
        rank=rank,
        grade=grade,
    )


def rank_sectors(sectors: list[SectorScore]) -> list[SectorScore]:
    """按总评分排序并分配排名"""
    sorted_sectors = sorted(sectors, key=lambda s: s.total_score, reverse=True)
    for i, s in enumerate(sorted_sectors):
        object.__setattr__(s, "rank", i + 1)
    return sorted_sectors