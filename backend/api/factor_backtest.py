"""因子回测评估 API —— 移植自 tickflow-stock-panel (MIT) 的 backtest/factor.py 设计。

功能：
  1. IC 分析：截面 Rank IC（因子 rank vs 下期收益 rank 的 Spearman），IR = IC均值/IC标准差
  2. 分层回测：n_groups 分组净值曲线 + 统计（总收益/年化/回撤/夏普/胜率）
  3. 多空组合：做多最高组 + 做空最低组，各 50% 资金

数据源：A股本地 stock_daily_kline（候选池=主力流入池），美股批量采集（候选池=CORE_A/B）。
"""
from __future__ import annotations

import asyncio
import math
import sys
import os
import time
from datetime import date, timedelta
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Query  # noqa: E402

router = APIRouter()

# 可用因子（与 TSP FACTOR_COLUMNS 对齐）
FACTOR_COLUMNS: List[dict] = [
    {"id": "momentum_5d", "label": "5日动量", "group": "动量", "desc": "5日涨跌幅"},
    {"id": "momentum_10d", "label": "10日动量", "group": "动量", "desc": "10日涨跌幅"},
    {"id": "momentum_20d", "label": "20日动量", "group": "动量", "desc": "月度涨跌幅"},
    {"id": "momentum_30d", "label": "30日动量", "group": "动量", "desc": "30日涨跌幅"},
    {"id": "momentum_60d", "label": "60日动量", "group": "动量", "desc": "季度涨跌幅"},
    {"id": "rsi_6", "label": "RSI(6)", "group": "超买超卖", "desc": "6日相对强弱"},
    {"id": "rsi_14", "label": "RSI(14)", "group": "超买超卖", "desc": "14日相对强弱"},
    {"id": "rsi_24", "label": "RSI(24)", "group": "超买超卖", "desc": "24日相对强弱"},
    {"id": "annual_vol_20d", "label": "20日年化波动率", "group": "波动率", "desc": "20日收益率年化波动"},
    {"id": "atr_14", "label": "ATR(14)", "group": "波动率", "desc": "14日平均真实波幅"},
    {"id": "vol_ratio_5d", "label": "量比(5日)", "group": "量价", "desc": "当日量/5日均量"},
    {"id": "change_pct", "label": "日涨跌幅", "group": "基础", "desc": "当日涨跌幅"},
    {"id": "amplitude", "label": "日振幅", "group": "基础", "desc": "(最高-最低)/昨收"},
]


@router.get("/api/factor-backtest/factors")
def factors_list():
    return {"ok": True, "data": FACTOR_COLUMNS, "error": None}


# ================================================================
# 因子计算（纯 Python，输入个股 {date,open,high,low,close,volume} 列表）
# ================================================================

def _sma(vals: List[float], w: int) -> Optional[float]:
    if len(vals) < w or w <= 0:
        return None
    return sum(vals[-w:]) / w


def _ema(vals: List[float], span: int) -> List[float]:
    out: List[float] = []
    k = 2.0 / (span + 1)
    prev = None
    for v in vals:
        prev = v if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def _rsi_series(vals: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(vals)
    if len(vals) < period + 1:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        d = vals[i] - vals[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_g, avg_l = gains / period, losses / period
    out[period] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(period + 1, len(vals)):
        d = vals[i] - vals[i - 1]
        avg_g = (avg_g * (period - 1) + max(d, 0.0)) / period
        avg_l = (avg_l * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def _atr_series(highs, lows, closes, period=14) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(closes)
    n = len(closes)
    if n < period + 1:
        return out
    trs = []
    for i in range(1, n):
        trs.append(max(highs[i] - lows[i],
                       abs(highs[i] - closes[i - 1]),
                       abs(lows[i] - closes[i - 1])))
    atr = sum(trs[:period]) / period
    out[period] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i + 1] = atr
    return out


def compute_factor_series(klines: List[dict], factor: str) -> List[Optional[float]]:
    """计算单只股票的因子序列（与 K线等长，前置段为 None）。"""
    n = len(klines)
    if n == 0:
        return []
    closes = [float(k.get("close") or 0) for k in klines]
    opens = [float(k.get("open") or 0) for k in klines]
    highs = [float(k.get("high") or 0) for k in klines]
    lows = [float(k.get("low") or 0) for k in klines]
    vols = [float(k.get("volume") or 0) for k in klines]

    if factor == "change_pct":
        out = [None] * n
        for i in range(1, n):
            if closes[i - 1] > 0:
                out[i] = closes[i] / closes[i - 1] - 1
        return out
    if factor == "amplitude":
        out = [None] * n
        for i in range(1, n):
            if closes[i - 1] > 0:
                out[i] = (highs[i] - lows[i]) / closes[i - 1]
        return out
    if factor.startswith("momentum_"):
        w = int(factor.split("_")[1].replace("d", ""))
        out = [None] * n
        for i in range(w, n):
            if closes[i - w] > 0:
                out[i] = closes[i] / closes[i - w] - 1
        return out
    if factor.startswith("rsi_"):
        period = int(factor.split("_")[1])
        return _rsi_series(closes, period)
    if factor == "annual_vol_20d":
        rets = [None] * n
        for i in range(1, n):
            if closes[i - 1] > 0:
                rets[i] = closes[i] / closes[i - 1] - 1
        out = [None] * n
        for i in range(20, n):
            win = rets[i - 19:i + 1]
            valid = [r for r in win if r is not None]
            if len(valid) >= 5:
                mean = sum(valid) / len(valid)
                var = sum((r - mean) ** 2 for r in valid) / len(valid)
                out[i] = math.sqrt(var) * math.sqrt(252)
        return out
    if factor == "atr_14":
        return _atr_series(highs, lows, closes, 14)
    if factor == "vol_ratio_5d":
        out = [None] * n
        for i in range(5, n):
            avg5 = sum(vols[i - 5:i]) / 5
            if avg5 > 0:
                out[i] = vols[i] / avg5
        return out
    return [None] * n


# ================================================================
# 面板构建 + 统计
# ================================================================

def _spearman_rank_corr(x: List[float], y: List[float]) -> Optional[float]:
    """两序列的 Rank 相关系数（Spearman）。"""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None and a == a and b == b]
    if len(pairs) < 5:
        return None

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    n = len(pairs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    dy = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _max_drawdown(nav: List[float]) -> float:
    peak, mdd = 1.0, 0.0
    for v in nav:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd


def run_factor_panel(panel, factor: str, n_groups: int, rebalance: str, start: date, end: date) -> dict:
    """panel: {symbol: [(date_str, close, factor_val), ...]}（已按日期升序）。"""
    # 汇总所有交易日
    all_dates = sorted({d for rows in panel.values() for d, _, _ in rows if start <= _pyd(d) <= end})
    if not all_dates:
        return {"error": "无数据，请检查日期范围"}

    # 调仓日集合
    reb_dates: List[str] = []
    if rebalance == "daily":
        reb_dates = all_dates
    elif rebalance == "weekly":
        for d in all_dates:
            if _pyd(d).weekday() == 0:  # 周一
                reb_dates.append(d)
    else:  # monthly: 每月首个交易日
        seen = set()
        for d in all_dates:
            m = d[:7]
            if m not in seen:
                seen.add(m)
                reb_dates.append(d)
    if not reb_dates:
        return {"error": "所选区间内无调仓日"}

    # 下一调仓日映射
    next_reb = {reb_dates[i]: reb_dates[i + 1] for i in range(len(reb_dates) - 1)}

    # 每个调仓日：截面 {symbol: (factor, next_return)}
    cross: dict = {}
    for d in reb_dates[:-1]:
        nd = next_reb[d]
        rows = {}
        for sym, krows in panel.items():
            fv = None
            cv = None
            nv = None
            for (kd, c, f) in krows:
                if kd == d:
                    fv, cv = f, c
                elif kd == nd:
                    nv = c
            if fv is not None and nv is not None and cv and nv > 0 and cv > 0:
                rows[sym] = (fv, nv / cv - 1)
        if len(rows) >= 5:
            cross[d] = rows

    if not cross:
        return {"error": "有效截面数据不足（需要 ≥5 只股票/调仓日）"}

    # ── 1. IC 分析 ──
    ic_series = []
    ic_values = []
    for d, rows in cross.items():
        syms = list(rows.keys())
        fvals = [rows[s][0] for s in syms]
        rvals = [rows[s][1] for s in syms]
        ic = _spearman_rank_corr(fvals, rvals)
        if ic is not None:
            ic_series.append({"date": d, "ic": round(ic, 4)})
            ic_values.append(ic)
    ic_mean = sum(ic_values) / len(ic_values) if ic_values else None
    ic_std = math.sqrt(sum((v - ic_mean) ** 2 for v in ic_values) / len(ic_values)) if len(ic_values) > 1 else None
    ir = (ic_mean / ic_std) if (ic_mean is not None and ic_std and ic_std > 1e-8) else None
    ic_win_rate = (sum(1 for v in ic_values if v > 0) / len(ic_values)) if ic_values else None

    # ── 2. 分层回测 ──
    # 每调仓日按因子排序分 n_groups 组（ord 分桶）
    group_rets: dict = {g: [] for g in range(1, n_groups + 1)}  # g -> [(date, ret)]
    for d, rows in cross.items():
        ranked = sorted(rows.items(), key=lambda kv: kv[1][0])
        total = len(ranked)
        for idx, (sym, (fv, ret)) in enumerate(ranked):
            g = min(int(idx * n_groups / total), n_groups - 1) + 1
            group_rets[g].append((d, ret))

    group_nav: List[dict] = []
    nav_vals = {g: 1.0 for g in range(1, n_groups + 1)}
    seen_dates = sorted({d for g in group_rets.values() for (d, _) in g})
    for d in seen_dates:
        entry = {"date": d}
        for g in range(1, n_groups + 1):
            rets = [r for (dd, r) in group_rets[g] if dd == d]
            if rets:
                nav_vals[g] *= (1 + sum(rets) / len(rets))
            entry[f"Q{g}"] = round(nav_vals[g], 4)
        group_nav.append(entry)

    # 组统计
    years = max((end - start).days, 1) / 365.25
    ann = {"daily": 252, "weekly": 52, "monthly": 12}.get(rebalance, 252)
    group_stats = []
    for g in range(1, n_groups + 1):
        vals = [e[f"Q{g}"] for e in group_nav if e.get(f"Q{g}") is not None]
        if not vals:
            continue
        total_ret = vals[-1] - 1
        annual_ret = (vals[-1]) ** (1 / max(years, 0.01)) - 1 if vals[-1] > 0 else 0.0
        mdd = _max_drawdown(vals)
        period_rets = []
        for j in range(1, len(vals)):
            if vals[j - 1] > 0:
                period_rets.append(vals[j] / vals[j - 1] - 1)
        if period_rets:
            mean_r = sum(period_rets) / len(period_rets)
            var_r = sum((r - mean_r) ** 2 for r in period_rets) / len(period_rets)
            std_r = math.sqrt(var_r)
            sharpe = (mean_r / std_r) * math.sqrt(ann) if std_r > 0 else 0.0
            win_rate = sum(1 for r in period_rets if r > 0) / len(period_rets)
        else:
            sharpe, win_rate = 0.0, 0.0
        group_stats.append({
            "group": g, "label": f"Q{g}",
            "total_return": round(total_ret, 4),
            "annual_return": round(annual_ret, 4),
            "max_drawdown": round(mdd, 4),
            "sharpe": round(sharpe, 2),
            "win_rate": round(win_rate, 4),
        })

    # ── 3. 多空组合（做多 Q{max} + 做空 Q1，各 50%）──
    ls_value = 1.0
    prev_top, prev_bot = 1.0, 1.0
    peak, max_dd = 1.0, 0.0
    ls_nav: List[dict] = []
    for e in group_nav:
        top = e.get(f"Q{n_groups}", 1.0)
        bot = e.get("Q1", 1.0)
        top_ret = top / prev_top - 1 if prev_top > 0 else 0.0
        bot_ret = -(bot / prev_bot - 1) if prev_bot > 0 else 0.0
        ls_ret = (top_ret + bot_ret) / 2
        ls_value *= (1 + ls_ret)
        prev_top, prev_bot = top, bot
        peak = max(peak, ls_value)
        max_dd = min(max_dd, (ls_value - peak) / peak if peak > 0 else 0.0)
        ls_nav.append({"date": e["date"], "value": round(ls_value, 4)})

    return {
        "error": None,
        "ic_mean": round(ic_mean, 4) if ic_mean is not None else None,
        "ic_std": round(ic_std, 4) if ic_std is not None else None,
        "ir": round(ir, 4) if ir is not None else None,
        "ic_win_rate": round(ic_win_rate, 4) if ic_win_rate is not None else None,
        "ic_series": ic_series,
        "group_stats": group_stats,
        "group_nav": group_nav,
        "long_short_nav": ls_nav,
        "long_short_stats": {
            "total_return": round(ls_value - 1, 4),
            "max_drawdown": round(max_dd, 4),
            "top_group": f"Q{n_groups}",
            "bottom_group": "Q1",
        },
        "n_dates": len(seen_dates),
    }


def _pyd(d: str) -> date:
    return date.fromisoformat(d[:10])


# ================================================================
# 数据加载
# ================================================================

async def _load_a_panel(symbols: List[str], start: date, end: date, factor: str):
    """A股：本地 stock_daily_kline 批量加载。"""
    from db.session import get_db_session
    from db.models import StockDailyKline
    out: dict = {}
    with get_db_session() as db:
        rows = db.query(StockDailyKline).filter(
            StockDailyKline.ts_code.in_(symbols),
            StockDailyKline.trade_date >= start,
            StockDailyKline.trade_date <= end,
        ).order_by(StockDailyKline.ts_code, StockDailyKline.trade_date).all()
    by_sym: dict = {}
    for r in rows:
        by_sym.setdefault(r.ts_code, []).append({
            "date": str(r.trade_date)[:10],
            "open": float(r.open or 0), "high": float(r.high or 0),
            "low": float(r.low or 0), "close": float(r.close or 0),
            "volume": float(r.volume or 0),
        })
    for sym, klines in by_sym.items():
        if len(klines) < 30:
            continue
        fs = compute_factor_series(klines, factor)
        out[sym] = [(k["date"], k["close"], f) for k, f in zip(klines, fs)]
    return out


async def _load_us_panel(symbols: List[str], start: date, end: date, factor: str):
    """美股：批量采集（数据库→多源）。"""
    from us_quant.data_provider import get_klines_batch
    batch = symbols[:40]
    kl_map = await asyncio.to_thread(get_klines_batch, batch, "2y")
    out: dict = {}
    for sym, klines in kl_map.items():
        if not klines or len(klines) < 30:
            continue
        fs = compute_factor_series(klines, factor)
        out[sym] = [(str(k["date"])[:10], k["close"], f) for k, f in zip(klines, fs)]
    return out


async def _a_symbols(limit: int) -> List[str]:
    from db.session import get_db_session
    from db.models import StockFlow
    from sqlalchemy import func as sql_func
    out: List[str] = []
    with get_db_session() as db:
        latest = db.query(sql_func.max(StockFlow.id).label("max_id")).group_by(StockFlow.ts_code).subquery()
        rows = db.query(StockFlow).join(
            latest, StockFlow.id == latest.c.max_id
        ).filter(StockFlow.main_force_inflow > 0).order_by(
            StockFlow.main_force_inflow.desc()).limit(limit).all()
        out = [r.ts_code for r in rows]
    return out


async def _us_symbols(limit: int) -> List[str]:
    try:
        # Factor history is stored in USStockDaily and the US quant pools are
        # the authoritative candidate source for this backtest.  The unified
        # market pool may contain symbols without a USStockDaily history row.
        from us_quant.universe import get_universe_members
        a = list(get_universe_members("CORE_A_300"))[:limit]
        b = list(get_universe_members("CORE_B_500"))[:limit]
        return list(dict.fromkeys(a + b))[:limit]
    except Exception:
        try:
            from market_quant.universe import get_members
            return list(dict.fromkeys(get_members("US", "CORE")))[:limit]
        except Exception:
            return []


@router.get("/api/factor-backtest/run")
async def factor_backtest(
    market: str = Query("a", description="a= A股, us= 美股"),
    factor: str = Query("rsi_14", description="因子 id，见 /factors"),
    start: str = Query("", description="开始日期 YYYY-MM-DD，默认近 2 年"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    n_groups: int = Query(5, ge=2, le=10),
    rebalance: str = Query("monthly", description="调仓频率 daily/weekly/monthly"),
    symbols: str = Query("", description="逗号分隔的代码列表（留空=候选池）"),
):
    """运行因子回测评估：IC/IR + 分层 + 多空。"""
    try:
        if factor not in {f["id"] for f in FACTOR_COLUMNS}:
            return {"ok": False, "data": None, "error": f"未知因子 {factor}"}
        if rebalance not in ("daily", "weekly", "monthly"):
            return {"ok": False, "data": None, "error": "rebalance 必须为 daily/weekly/monthly"}

        t0 = time.time()
        end_d = date.fromisoformat(end[:10]) if end else date.today()
        start_d = date.fromisoformat(start[:10]) if start else end_d - timedelta(days=730)

        # 候选池
        if symbols.strip():
            code_list = [s.strip() for s in symbols.split(",") if s.strip()]
            if market == "a":
                code_list = [c if c.endswith((".SH", ".SZ", ".BJ")) else
                             (c + ".SH" if c[0] in ("6", "9") else c + ".SZ") for c in code_list]
        else:
            code_list = await _a_symbols(120) if market == "a" else await _us_symbols(40)
        if not code_list:
            return {"ok": False, "data": None, "error": "候选池为空"}

        if market == "a":
            panel = await _load_a_panel(code_list, start_d, end_d, factor)
        else:
            panel = await _load_us_panel(code_list, start_d, end_d, factor)
        if not panel:
            return {"ok": False, "data": None, "error": "无可用K线数据（数据不足或候选池为空）"}

        result = run_factor_panel(panel, factor, n_groups, rebalance, start_d, end_d)
        if result.get("error"):
            return {"ok": False, "data": None, "error": result["error"]}
        result["n_symbols"] = len(panel)
        result["factor"] = factor
        result["start"] = str(start_d)
        result["end"] = str(end_d)
        result["rebalance"] = rebalance
        result["elapsed_ms"] = round((time.time() - t0) * 1000, 0)
        return {"ok": True, "data": result, "error": None}
    except Exception as e:
        return {"ok": False, "data": None, "error": str(e)}
