# -*- coding: utf-8 -*-
"""横盘蓄势：每日扫描编排

流程：数据加载 → 大盘过滤 → 板块合成 → 每股（箱体/量价/信号/评分）→ 落库
落库表：horizontal_signal（ts_code+trade_date 唯一，幂等 upsert）
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from db.connection import init_db
from db.session import get_db_session
from db.models import HorizontalSignal
from strategies.horizontal.market_filter import (
    LOOKBACK_DAYS,
    load_daily_frame,
    load_sector_members,
    market_filter,
)
from strategies.horizontal.sector_filter import build_sector_metrics, sector_rank_pct
from strategies.horizontal.box import find_box, volume_price
from strategies.horizontal.signals import classify_signal
from strategies.horizontal.scoring import score_stock

logger = logging.getLogger(__name__)


def _native(v):
    """numpy 标量 → Python 原生类型。

    指标计算过程会产生 np.float64/np.int64，psycopg2 无法把 numpy 标量绑定为
    占位参数（会渲染成 `np.float64(..)` 导致 PostgreSQL 报 schema "np" 不存在）。
    入库前统一转成 Python 原生标量。
    """
    if v is None:
        return None
    return v.item() if hasattr(v, "item") else v


def _fetch_names(codes: List[str]) -> Dict[str, str]:
    """从库内 stock_flow 取股票名称（纯 DB，符合"所有采集经过数据库"）。

    优先按名称聚合，取最新一条含名称的记录映射 ts_code→name。
    相比旧版走腾讯外呼，历史回填与当日扫描都无需依赖外部接口。
    """
    from db.models import StockFlow
    out: Dict[str, str] = {}
    if not codes:
        return out
    with get_db_session() as db:
        rows = (
            db.query(StockFlow.ts_code, StockFlow.name)
            .filter(StockFlow.ts_code.in_(codes), StockFlow.name.isnot(None))
            .all()
        )
    for ts, name in rows:
        if name and ts not in out:
            out[ts] = name
    return out


def _is_st(name: str) -> bool:
    n = (name or "").upper()
    return "ST" in n or "退" in n


def run_scan(trade_date: Optional[str] = None, persist: bool = True) -> Dict:
    """执行一次全市场横盘扫描

    trade_date 缺省 = 库内最新交易日。返回统计信息。
    """
    t0 = time.time()
    init_db()  # 确保 horizontal_signal 表存在
    df = load_daily_frame(trade_date=trade_date)
    if df.empty:
        return {"ok": False, "error": "日线数据为空"}
    latest = str(df["trade_date"].max())
    target = str(trade_date) if trade_date else latest
    logger.info("横盘扫描 %s 加载 %d 行", target, len(df))

    # 1. 大盘过滤
    mkt = market_filter(df)
    logger.info("大盘: ok=%s score=%s 上涨占比=%s%%",
                mkt["ok"], mkt["score"], mkt.get("up_ratio"))

    # 2. 板块过滤
    members = load_sector_members()
    sector_metrics, stock_sector = build_sector_metrics(df, members)
    logger.info("板块: %d 个有效，%d 只有归属", len(sector_metrics), len(stock_sector))

    # 3. 逐股计算（按 ts_code 分组）
    results: List[Dict] = []
    stats = {"boxed": 0, "signals": {"A": 0, "B": 0, "C": 0, "D": 0}, "tradable": 0}
    groups = {c: g for c, g in df.groupby("ts_code")}

    for ts_code, g in groups.items():
        if len(g) < 90:
            continue  # 次新不足
        g = g.reset_index(drop=True)
        box = find_box(g)
        if not box:
            continue
        vp = volume_price(g, box)
        # 注入信号所需字段
        box["vol_ratio_5_20"] = vp.get("vol_ratio_5_20")
        box["prev_close"] = float(g["close"].iloc[-2]) if len(g) >= 2 else float(g["close"].iloc[-1])
        sig = classify_signal(g, box)
        close = float(g["close"].iloc[-1])
        amt20 = float(g["amount"].iloc[-20:].mean()) if len(g) >= 20 else float(g["amount"].iloc[-1])
        sector = stock_sector.get(ts_code, "")
        sec_m = sector_metrics.get(sector)
        sc = score_stock(
            market_score=mkt["score"],
            sector_metrics=sec_m,
            box=box,
            vp=vp,
            close=close,
            vol20=box.get("vol_20") or 0,
            amt20=amt20,
        )
        stats["boxed"] += 1
        if sig["code"]:
            stats["signals"][sig["code"]] = stats["signals"].get(sig["code"], 0) + 1
        # 放宽可交易门槛：信号 A/B/C 且（大盘 OK 或 板块 OK）即视为可交易。
        # 原严格口径（大盘+板块+信号 全满足）会让可交易标的屈指可数、实用价值低。
        sig_trade = sig["code"] in ("A", "B", "C")
        tradable = bool(sig_trade and (mkt["ok"] or (sec_m and sec_m["ok"])))
        if tradable:
            stats["tradable"] += 1
        results.append({
            "ts_code": ts_code,
            "trade_date": target,
            "box": box,
            "vp": vp,
            "sig": sig,
            "sc": sc,
            "close": close,
            "pct_chg": float(g["pct_chg"].iloc[-1]) if g["pct_chg"].iloc[-1] == g["pct_chg"].iloc[-1] else None,
            "sector": sector,
            "sec_m": sec_m,
            "amt20": amt20,
            "market_ok": mkt["ok"],
            "tradable": tradable,
        })

    logger.info("箱体命中 %d 只，信号 %s，可交易 %d",
                stats["boxed"], stats["signals"], stats["tradable"])

    # 4. 名称（腾讯批量，仅对命中股票）
    names: Dict[str, str] = {}
    if results:
        codes = sorted({r["ts_code"] for r in results})
        names = _fetch_names(codes)
    logger.info("名称获取 %d/%d", len(names), len(results))

    # 5. 落库（幂等 upsert）
    if persist and results:
        with get_db_session() as db:
            existing = {
                r[0] for r in db.query(HorizontalSignal.ts_code).filter(
                    HorizontalSignal.trade_date == date.fromisoformat(target)
                ).all()
            }
            for r in results:
                code = r["ts_code"]
                if code in existing:
                    continue
                name = names.get(code, "")
                if _is_st(name):
                    continue
                row = HorizontalSignal(
                    ts_code=code,
                    trade_date=date.fromisoformat(target),
                    name=name,
                    sector=r["sector"],
                    state=r["sig"]["state"],
                    signal_code=r["sig"]["code"],
                    signal_detail=r["sig"]["detail"],
                    grade=r["sc"]["grade"],
                    score=_native(r["sc"]["score"]),
                    score_detail=json.dumps(r["sc"]["detail"], ensure_ascii=False),
                    tradable=bool(r["tradable"]),
                    box_high=_native(r["box"]["box_high"]),
                    box_low=_native(r["box"]["box_low"]),
                    box_days=_native(r["box"]["box_days"]),
                    amplitude=_native(r["box"]["amplitude"]),
                    dist_to_break=_native(r["sc"]["dist_to_break"]),
                    close_pos_in_box=_native(r["box"]["close_pos_in_box"]),
                    ma20_drift=_native(r["box"]["ma20_drift"]),
                    atr_ratio=_native(r["box"]["atr_ratio"]),
                    up_dn_vol_ratio=_native(r["vp"].get("up_dn_vol_ratio")),
                    vol_ratio_5_20=_native(r["vp"].get("vol_ratio_5_20")),
                    price_gravity=_native(r["vp"].get("price_gravity")),
                    risk_reward=_native(r["sc"]["risk_reward"]),
                    market_ok=r["market_ok"],
                    sector_ok=bool(r["sec_m"] and r["sec_m"]["ok"]),
                    sector_rank_pct=_native(sector_rank_pct(r["sector"], sector_metrics)),
                    close=_native(r["close"]),
                    pct_chg=_native(r["pct_chg"]),
                    amount_20=round(_native(r["amt20"]) or 0, 0),
                )
                db.add(row)
            db.commit()
        logger.info("落库完成 %s", target)

    return {
        "ok": True,
        "trade_date": target,
        "market": mkt,
        "sectors": len(sector_metrics),
        "stats": {
            "boxed": stats["boxed"],
            "signals": stats["signals"],
            "tradable": stats["tradable"],
            "persisted": len(results) if persist else 0,
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
