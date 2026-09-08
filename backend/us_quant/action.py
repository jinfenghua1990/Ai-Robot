"""美股自选股操作方向评估（与状态区分开：状态=阶段，方向=怎么操作）。

输入：全套技术指标（评分/均线结构/RSI/MACD/KDJ/52周位置/量比/动量/支撑阻力/止损价）
输出：action 方向 + 理由列表，供前端卡片醒目展示。

方向优先级（从上到下命中即返回，越靠前越强）：
  止损卖出 > 退潮卖出 > 超买减仓 > 空头观望 > 超卖低吸 > 多头加仓 > 多头持有 > 中性观望
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActionVerdict:
    action: str                       # stop / sell / reduce / watch / buy / hold / scoop
    label: str                        # 止损 / 卖出 / 减仓 / 观望 / 买入 / 持有 / 低吸
    color: str                        # 前端徽章色
    strength: int                     # 0-100 强度
    reasons: list[str] = field(default_factory=list)
    note: str = ""


def evaluate_action(ind: dict) -> ActionVerdict:
    """根据指标字典评估操作方向。ind 为 _watchlist_indicators 产出的字段集。"""
    reasons: list[str] = []
    price = ind.get("_price")
    stop = ind.get("stop_loss")
    score = ind.get("score")
    ma_struct = ind.get("ma_struct")
    rsi = ind.get("rsi")
    macd = ind.get("macd") or {}
    kdj = ind.get("kdj") or {}
    pct_high = ind.get("pct_from_high")
    rel_vol = ind.get("rel_vol")
    chg_5d = ind.get("chg_5d")
    chg_20d = ind.get("chg_20d")
    support = ind.get("support")
    state_label = ind.get("state_label")

    def _add(cond, text):
        if cond:
            reasons.append(text)

    # ── 1. 止损（最优先）：现价跌破止损价 ──
    if price is not None and stop is not None and price <= stop:
        return ActionVerdict("stop", "止损", "#ef4444", 95,
                             [f"现价 {price} 已跌破止损位 {stop}", *reasons])

    # ── 2. 退潮状态：趋势走弱 ──
    if state_label in ("退潮",):
        return ActionVerdict("sell", "卖出", "#ef4444", 85, [
            "状态退潮，趋势走弱", "持仓考虑减仓或退出，不建议新开仓", *reasons])

    # ── 3. 超买回调风险 ──
    if rsi is not None and rsi >= 75:
        _add(kdj.get("status") == "超买", f"KDJ 超买（J={kdj.get('j')}）")
        return ActionVerdict("reduce", "减仓", "#f97316", 70, [
            f"RSI {rsi} 超买，短线回调风险大", *reasons, "持仓可逢高减仓，空仓勿追高"])

    # ── 4. 空头排列：中期趋势向下 ──
    if ma_struct == "空头排列":
        _add(score is not None and score <= 45, f"综合评分 {score} 偏低")
        _add(macd.get("status") == "空头", "MACD 空头")
        return ActionVerdict("watch", "观望", "#94a3b8", 55, [
            "均线空头排列，中期趋势向下", *reasons, "等待企稳信号，暂不参与"])

    # ── 5. 超卖低吸机会（需价格仍在均线附近/有支撑） ──
    if rsi is not None and rsi <= 30:
        _add(kdj.get("status") == "超卖", f"KDJ 超卖（J={kdj.get('j')}）")
        _add(support is not None, f"近20日支撑位 {support}")
        return ActionVerdict("scoop", "低吸", "#22c55e", 60, [
            f"RSI {rsi} 超卖，短线或有反弹", *reasons, "激进者可小仓试错，设好止损"])

    # ── 6. 多头排列 + 高分：加仓/持有 ──
    if ma_struct == "多头排列":
        strong = score is not None and score >= 60
        _add(macd.get("status") in ("多头", "中性"), f"MACD {macd.get('status')}")
        _add(rel_vol is not None and rel_vol >= 1.2, f"量比 {rel_vol} 放量")
        _add(chg_5d is not None and chg_5d > 3, f"5日涨 {chg_5d}%")
        base = ["均线多头排列", *reasons]
        if strong and macd.get("status") == "多头":
            return ActionVerdict("buy", "买入", "#ef4444", 80, [*base, f"综合评分 {score}，趋势+动量共振"])
        if strong:
            return ActionVerdict("buy", "买入", "#ef4444", 70, [*base, f"综合评分 {score}"])
        return ActionVerdict("hold", "持有", "#f59e0b", 62, [*base, "评分一般，持仓可持有，空仓等待回踩"])

    # ── 7. 中性：纠缠 ──
    if ma_struct == "纠缠":
        _add(score is not None and score >= 60, f"综合评分 {score}")
        _add(pct_high is not None and pct_high > -10, f"距52周高仅 {pct_high}%")
        if score is not None and score >= 60:
            return ActionVerdict("hold", "持有", "#f59e0b", 55, ["均线纠缠但评分尚可", *reasons, "持仓持有，空仓观察突破"])
        return ActionVerdict("watch", "观望", "#94a3b8", 45, ["均线纠缠，方向未明", *reasons, "等待方向选择"])

    # ── 8. 兜底 ──
    if score is not None and score >= 60:
        return ActionVerdict("hold", "持有", "#f59e0b", 55, ["综合评分尚可，结构未明", "持仓持有，空仓等待信号"])
    return ActionVerdict("watch", "观望", "#94a3b8", 40, ["数据有限或信号不明", "继续观察"])


def summarize_action(ind: dict) -> dict:
    """给 _watchlist_indicators 产出的指标字典附加操作方向字段。"""
    ind = dict(ind)
    price = ind.get("price")
    verdict = evaluate_action({**ind, "_price": price})
    return {
        "action": verdict.action,
        "action_label": verdict.label,
        "action_color": verdict.color,
        "action_strength": verdict.strength,
        "action_reasons": verdict.reasons,
    }


# ─── 买卖信号提醒（比 action 更具体：金叉/死叉/破位/超buy超卖/放量） ─────────

def _kdj_series(closes, highs, lows, period: int = 9):
    """KDJ 全序列（k, d, j）——用于判断金叉/死叉。"""
    from services.indicators import calc_kdj

    ks, ds, _ = calc_kdj(highs, lows, closes, n=period)
    return ks, ds


def _recent_cross(series_a: list, series_b: list) -> Optional[str]:
    """最近两根是否发生金叉/死叉。a 上穿 b → 'gold'；a 下穿 b → 'dead'。"""
    if len(series_a) < 2 or len(series_b) < 2:
        return None
    a0, a1 = series_a[-2], series_a[-1]
    b0, b1 = series_b[-2], series_b[-1]
    if a0 is None or a1 is None or b0 is None or b1 is None:
        return None
    if a0 <= b0 and a1 > b1:
        return "gold"
    if a0 >= b0 and a1 < b1:
        return "dead"
    return None


def build_signal_alerts(closes, highs, lows, volumes, ind: dict) -> list[dict]:
    """生成具体买卖信号提醒列表。

    返回 [{level: 'buy'|'sell'|'warn'|'info', text}]，供前端表格"提醒"列展示。
    buy=买入信号 / sell=卖出信号 / warn=风险提醒 / info=中性观察。
    """
    from services.indicators import calc_macd
    alerts: list[dict] = []
    price = ind.get("price") or closes[-1]
    rsi = ind.get("rsi")
    relvol = ind.get("rel_vol")
    chg5 = ind.get("chg_5d")
    chg20 = ind.get("chg_20d")
    support = ind.get("support")
    resistance = ind.get("resistance")
    stop = ind.get("stop_loss")
    pct_high = ind.get("pct_from_high")

    # ── 止损触发/逼近（最高优先级） ──
    if price and stop:
        if price <= stop:
            alerts.append({"level": "sell", "text": f"已跌破止损 {stop:.2f}"})
        elif (stop / price - 1) > -0.03:
            alerts.append({"level": "warn", "text": f"临近止损位({100 * (price - stop) / price:.1f}%)"})

    # ── 支撑/阻力突破 ──
    if price and resistance and price > resistance:
        alerts.append({"level": "buy", "text": f"突破阻力 {resistance:.2f}"})
    if price and support and price < support:
        alerts.append({"level": "warn", "text": f"跌破支撑 {support:.2f}"})

    # ── RSI 超卖/超买 ──
    if rsi is not None:
        if rsi <= 30:
            alerts.append({"level": "buy", "text": f"RSI {rsi:.0f} 超卖，超跌反弹窗口"})
        elif rsi >= 75:
            alerts.append({"level": "sell", "text": f"RSI {rsi:.0f} 超买，短线回调风险"})
        elif 45 >= rsi >= 40 and chg20 is not None and chg20 > 0:
            alerts.append({"level": "info", "text": f"RSI {rsi:.0f} 中性偏低"})

    # ── MACD / KDJ 金叉死叉 ──
    try:
        dif_line, dea_line, _ = calc_macd(closes)
        cross = _recent_cross(dif_line, dea_line)
        if cross == "gold":
            alerts.append({"level": "buy", "text": "MACD 金叉，动能转多"})
        elif cross == "dead":
            alerts.append({"level": "sell", "text": "MACD 死叉，动能转空"})
    except Exception:
        pass
    try:
        ks, ds = _kdj_series(closes, highs, lows)
        cross = _recent_cross(ks, ds)
        if cross == "gold":
            alerts.append({"level": "buy", "text": f"KDJ 金叉 (K={ks[-1]:.0f})"})
        elif cross == "dead":
            alerts.append({"level": "sell", "text": f"KDJ 死叉 (K={ks[-1]:.0f})"})
    except Exception:
        pass

    # ── 放量异动 ──
    if relvol is not None and volumes and len(volumes) >= 6:
        prev = sum(volumes[-6:-1]) / 5
        if prev > 0 and volumes[-1] / prev >= 2.0:
            direction = "放量上涨" if closes[-1] >= closes[-2] else "放量下跌"
            level = "buy" if closes[-1] >= closes[-2] else "sell"
            alerts.append({"level": level, "text": f"{direction} (量比 {relvol})"})

    # ── 动量 ──
    if chg20 is not None and chg20 >= 15:
        alerts.append({"level": "info", "text": f"20日大涨 {chg20:.1f}%，注意追高"})
    if chg5 is not None and chg5 <= -10:
        alerts.append({"level": "warn", "text": f"5日急跌 {chg5:.1f}%，观察止跌"})

    return alerts[:6]
