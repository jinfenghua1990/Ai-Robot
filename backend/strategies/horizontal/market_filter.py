# -*- coding: utf-8 -*-
"""横盘蓄势：数据加载与大盘过滤

大盘过滤（首版简单可回测条件）：
  1. 全市场等权指数（成分股 close 均值序列）> MA20
  2. MA20 最近 5 日斜率 >= 0
  3. 全市场上涨股票占比 >= 40%

大盘不满足 → 全市场不产生买入信号，仅进观察池。
"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from sqlalchemy import func as sql_func

from db.session import get_db_session
from db.models import StockDailyKline

logger = logging.getLogger(__name__)

# 计算所需的历史长度（交易日）：60 日窗口 + 60 日均线 + 缓冲
LOOKBACK_DAYS = 150

# 大盘快照缓存（数据源日频不变，盘后无需重复计算）
_MKT_CACHE: Dict = {"ts": 0.0, "data": None}
MKT_CACHE_TTL = 300  # 秒


# 大盘过滤所需的最小历史（交易日）
MKT_LOOKBACK_DAYS = 30


def load_daily_frame(trade_date: Optional[str] = None) -> pd.DataFrame:
    """加载 stock_daily_kline 最近 N 个交易日全市场数据 → DataFrame

    trade_date: 截止交易日（含当日及之前）；缺省=库内最新。历史回填时传入指定日，
    以便按"截至当日"重建横盘信号（此时用截至当日判定 box/信号）。
    列: ts_code, trade_date, open, high, low, close, volume, amount, pct_chg
    按 trade_date 升序、ts_code 分组排序后返回。
    """
    with get_db_session() as db:
        dates_q = db.query(StockDailyKline.trade_date).distinct()
        if trade_date:
            dates_q = dates_q.filter(StockDailyKline.trade_date <= date.fromisoformat(str(trade_date)))
        dates = [r[0] for r in dates_q.order_by(StockDailyKline.trade_date.desc()).limit(LOOKBACK_DAYS).all()]
        if not dates:
            return pd.DataFrame()
        rows = (
            db.query(
                StockDailyKline.ts_code,
                StockDailyKline.trade_date,
                StockDailyKline.open,
                StockDailyKline.high,
                StockDailyKline.low,
                StockDailyKline.close,
                StockDailyKline.volume,
                StockDailyKline.amount,
                StockDailyKline.pct_chg,
            )
            .filter(StockDailyKline.trade_date.in_(dates))
            .all()
        )
    df = pd.DataFrame(rows, columns=[
        "ts_code", "trade_date", "open", "high", "low",
        "close", "volume", "amount", "pct_chg",
    ])
    for c in ("open", "high", "low", "close", "volume", "amount", "pct_chg"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def latest_trade_date() -> Optional[str]:
    """最近一个交易日 YYYY-MM-DD"""
    with get_db_session() as db:
        d = db.query(StockDailyKline.trade_date).order_by(StockDailyKline.trade_date.desc()).first()
        return str(d[0]) if d else None


def market_snapshot() -> Dict:
    """大盘环境快照（SQL 聚合版，毫秒级）+ 300s 缓存

    与 market_filter(df) 完全相同的三条件口径：
      1. 等权指数（每日全部股票 close 均值）> MA20
      2. MA20 最近 5 日斜率 >= 0
      3. 最新交易日全市场上涨占比 >= 40%
    """
    now = time.time()
    if _MKT_CACHE["data"] and now - _MKT_CACHE["ts"] < MKT_CACHE_TTL:
        return _MKT_CACHE["data"]

    with get_db_session() as db:
        # 最近 N 个交易日（date 去重排序）
        dates = [
            r[0]
            for r in db.query(StockDailyKline.trade_date)
            .distinct()
            .order_by(StockDailyKline.trade_date.desc())
            .limit(MKT_LOOKBACK_DAYS)
            .all()
        ]
        if not dates:
            return {"ok": False, "score": 0, "details": {"reason": "无行情数据"}}
        # 等权指数：SQL 直接聚合每日 close 均值（避免全量加载到 Python）
        idx_rows = (
            db.query(
                StockDailyKline.trade_date,
                sql_func.avg(StockDailyKline.close).label("avg_close"),
            )
            .filter(StockDailyKline.trade_date.in_(dates))
            .group_by(StockDailyKline.trade_date)
            .order_by(StockDailyKline.trade_date)
            .all()
        )
        if len(idx_rows) < 25:
            return {"ok": False, "score": 0, "details": {"reason": "数据不足"}}
        idx = pd.Series({str(d): float(v) for d, v in idx_rows}, dtype=float)
        # 最新交易日上涨占比（pct_chg > 0）
        last_day = dates[0]
        up_cnt = (
            db.query(sql_func.count())
            .filter(
                StockDailyKline.trade_date == last_day,
                StockDailyKline.pct_chg > 0,
            )
            .scalar()
        )
        tot_cnt = (
            db.query(sql_func.count())
            .filter(StockDailyKline.trade_date == last_day)
            .scalar()
        )

    ma20 = idx.rolling(20).mean()
    slope5 = (ma20.iloc[-1] - ma20.iloc[-6]) / ma20.iloc[-6] * 100 if len(ma20) >= 6 else 0.0
    cond1 = bool(idx.iloc[-1] > ma20.iloc[-1])
    cond2 = bool(slope5 >= 0)
    up_ratio = float(up_cnt / tot_cnt) if tot_cnt else 0.0
    cond3 = bool(up_ratio >= 0.40)
    score = int(cond1) * 4 + int(cond2) * 3 + int(cond3) * 3
    ok = bool(cond1 and cond2 and cond3)

    result = {
        "ok": ok,
        "score": score,
        "index_close": round(float(idx.iloc[-1]), 2),
        "index_ma20": round(float(ma20.iloc[-1]), 2),
        "ma20_slope5": round(slope5, 3),
        "up_ratio": round(up_ratio * 100, 1),
        "trade_date": str(last_day),
        "details": {
            "指数>MA20": cond1,
            "MA20斜率>=0": cond2,
            "上涨占比>=40%": cond3,
        },
    }
    _MKT_CACHE["ts"] = now
    _MKT_CACHE["data"] = result
    return result


def _market_index(df: pd.DataFrame) -> pd.Series:
    """全市场等权指数：每日全部股票 close 均值（按 trade_date）"""
    idx = df.groupby("trade_date")["close"].mean()
    return idx.sort_index()


def market_filter(df: pd.DataFrame) -> Dict:
    """大盘过滤三条件 → {ok, score(10分制), details}"""
    idx = _market_index(df)
    if len(idx) < 25:
        return {"ok": False, "score": 0, "details": {"reason": "数据不足"}}
    ma20 = idx.rolling(20).mean()
    slope5 = (ma20.iloc[-1] - ma20.iloc[-6]) / ma20.iloc[-6] * 100 if len(ma20) >= 6 else 0.0

    cond1 = idx.iloc[-1] > ma20.iloc[-1]          # 指数 > MA20
    cond2 = slope5 >= 0                            # MA20 斜率 >= 0
    # 上涨占比：最新交易日 pct_chg > 0 比例
    last_day = idx.index[-1]
    day = df[df["trade_date"] == last_day]
    up_ratio = float((day["pct_chg"] > 0).mean()) if len(day) else 0.0
    cond3 = up_ratio >= 0.40                       # 上涨占比 >= 40%

    score = int(cond1) * 4 + int(cond2) * 3 + int(cond3) * 3
    ok = bool(cond1 and cond2 and cond3)
    return {
        "ok": ok,
        "score": score,
        "index_close": round(float(idx.iloc[-1]), 2),
        "index_ma20": round(float(ma20.iloc[-1]), 2),
        "ma20_slope5": round(slope5, 3),
        "up_ratio": round(up_ratio * 100, 1),
        "trade_date": str(last_day),
        "details": {
            "指数>MA20": bool(cond1),
            "MA20斜率>=0": bool(cond2),
            "上涨占比>=40%": bool(cond3),
        },
    }


# 属性/风格型板块（非行业概念，不参与板块强度过滤）
_STYLE_BOARD_KEYWORDS = (
    "重仓", "融资", "融券", "超大盘", "中大盘", "小盘", "微盘",
    "含", "转债", "预盈", "预亏", "预增", "预升", "破净", "绩优",
    "基金", "保险", "社保", "QFII", "沪股通", "深股通", "证金", "汇金",
    "MSCI", "富时", "标普", "H股", "B股", "质押", "增持",
    "回购", "举牌", "壳资源", "股权转让", "国家队", "融资融券",
    "AH", "ST", "转债", "昨日", "连板", "涨停", "跌停", "参股",
    "央企", "整体上市", "股权激励", "业绩", "本地", "承诺", "重组",
    "次新", "低价", "高价", "中价", "破发", "填权", "除权", "送转",
)


def load_sector_members() -> Dict[str, List[str]]:
    """概念板块 → 成分股 ts_code 列表（来自 concept_sectors）

    过滤属性/风格型板块（重仓/融资/超大盘等非行业概念），仅保留行业题材板块。
    """
    from db.models import ConceptSector
    out = {}
    with get_db_session() as db:
        for name, stocks in db.query(ConceptSector.name, ConceptSector.stocks).all():
            if any(k in name for k in _STYLE_BOARD_KEYWORDS):
                continue
            members = [s.strip() for s in (stocks or "").split(",") if s.strip()]
            if len(members) >= 5:  # 成分太少无统计意义
                out[name] = members
    return out
