# -*- coding: utf-8 -*-
"""横盘蓄势：板块过滤（概念板块等权合成指数）

板块条件（满足大部分）：
  1. 板块指数 > MA20
  2. 板块 MA20 向上
  3. 板块 20 日涨幅处于行业前 30%
  4. 板块最近 5 日成交额没有明显下降（5日/20日均额 >= 0.7）
  5. 板块内站上 MA20 的股票占比 >= 50%

硬性规则：板块弱 → 个股只观察，不进交易池。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _sector_series(df: pd.DataFrame, members: List[str]) -> Optional[pd.DataFrame]:
    """板块等权合成指数（成分股 close/amount 按日取均值）"""
    sub = df[df["ts_code"].isin(members)]
    if len(sub) < 5:
        return None
    g = sub.groupby("trade_date")[["close", "amount"]].mean()
    return g.sort_index()


def build_sector_metrics(
    df: pd.DataFrame, sector_members: Dict[str, List[str]]
) -> Tuple[Dict[str, Dict], Dict[str, str]]:
    """计算各板块指标 + 每只股票所属的最强板块

    返回:
      sector_metrics: {板块名: {index_close, ma20, ma20_slope, ret_20d, vol_ratio_5_20,
                                above_ma20_ratio, ok, score(20分制)}}
      stock_sector: {ts_code: 最强板块名}（板块强度=板块评分排序取最强）
    """
    metrics: Dict[str, Dict] = {}
    # 每只股票 → 它所属板块列表
    stock_boards: Dict[str, List[str]] = {}
    last_day = df["trade_date"].max()

    # 预先算好每只股票的 MA20（一次性向量化，避免板块循环内重复 transform）
    df = df.copy()
    df["ma20"] = df.groupby("ts_code")["close"].transform(
        lambda x: x.rolling(20).mean()
    )
    # 每只股票"是否站上自身 MA20"，按最新交易日
    _last = df[df["trade_date"] == last_day]
    _above_by_code = (_last["close"] > _last["ma20"]).groupby(_last["ts_code"]).max()
    _above_by_code = _above_by_code.astype(bool).to_dict()

    for name, members in sector_members.items():
        s = _sector_series(df, members)
        if s is None or len(s) < 25:
            continue
        idx = s["close"]
        ma20 = idx.rolling(20).mean()
        if ma20.iloc[-1] != ma20.iloc[-1]:  # NaN
            continue
        slope = (ma20.iloc[-1] - ma20.iloc[-6]) / ma20.iloc[-6] * 100 if len(ma20) >= 6 else 0.0
        ret20 = (idx.iloc[-1] / idx.iloc[-21] - 1) * 100 if len(idx) >= 21 else 0.0
        amt = s["amount"]
        vol_ratio = amt.iloc[-5:].mean() / amt.iloc[-20:].mean() if len(amt) >= 20 else 1.0

        # 站上 MA20 占比：直接用一次性算好的每股 ma20 判断成员股
        with_ma = [m for m in members if m in _above_by_code]
        above = sum(1 for m in with_ma if _above_by_code[m]) / len(with_ma) if with_ma else 0.0

        conds = {
            "板块指数>MA20": bool(idx.iloc[-1] > ma20.iloc[-1]),
            "板块MA20向上": bool(slope >= 0),
            "20日涨幅前30%": None,  # 全局排名后填
            "5日成交额未降": bool(vol_ratio >= 0.7),
            "站上MA20占比>=50%": bool(above >= 0.5),
        }
        score = 4 * sum(1 for k, v in conds.items() if v is True)
        metrics[name] = {
            "index_close": round(float(idx.iloc[-1]), 2),
            "ma20": round(float(ma20.iloc[-1]), 2),
            "ma20_slope": round(slope, 3),
            "ret_20d": round(ret20, 2),
            "vol_ratio_5_20": round(float(vol_ratio), 2),
            "above_ma20_ratio": round(above * 100, 1),
            "score": score,
            "ok": bool(idx.iloc[-1] > ma20.iloc[-1] and slope >= 0 and above >= 0.5),
            "conds": conds,
        }
        for m in members:
            stock_boards.setdefault(m, []).append(name)

    # 20日涨幅前 30% 排名（板块之间比较）
    rets = sorted(((m, v["ret_20d"]) for m, v in metrics.items()), key=lambda x: x[1], reverse=True)
    top30 = set(m for m, _ in rets[: max(1, int(len(rets) * 0.30))])
    for m in metrics:
        metrics[m]["conds"]["20日涨幅前30%"] = m in top30
        metrics[m]["ok"] = metrics[m]["ok"] and m in top30
        metrics[m]["score"] = 4 * sum(
            1 for k, v in metrics[m]["conds"].items() if v is True
        )

    # 每股归属最强板块（按板块 ok + score 排序）
    stock_sector: Dict[str, str] = {}
    for code, boards in stock_boards.items():
        best = max(boards, key=lambda b: (metrics[b]["ok"], metrics[b]["score"], metrics[b]["ret_20d"]))
        stock_sector[code] = best

    return metrics, stock_sector


def sector_rank_pct(sector: str, metrics: Dict[str, Dict]) -> Optional[float]:
    """板块 20 日涨幅排名百分位（0-100，越小越靠前）"""
    if not metrics or sector not in metrics:
        return None
    ordered = sorted(metrics.values(), key=lambda v: v["ret_20d"], reverse=True)
    pos = sum(1 for v in ordered if v["ret_20d"] > metrics[sector]["ret_20d"])
    return round(pos / len(ordered) * 100, 1)
