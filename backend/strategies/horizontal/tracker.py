# -*- coding: utf-8 -*-
"""横盘蓄势：信号后走势跟踪（用于评估策略胜率/盈亏比）

对 horizontal_signal 中已记录的信号（重点 A/B/C），从库内 stock_daily_kline
按持有 5/10/20 个交易日统计后续实际收益、最大涨幅与最大回撤，写入 horizontal_track。

全程纯 DB（符合"所有采集经过数据库"），可用于每日维护与历史回填。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.dialects.postgresql import insert

from db.connection import init_db
from db.session import get_db_session
from db.models import HorizontalSignal, HorizontalTrack, StockDailyKline

logger = logging.getLogger(__name__)

HOLD_DAYS = [5, 10, 20]


def _kline_series(db, ts_code: str, since: date) -> List[tuple]:
    """取出某只股票 since 之后的 (trade_date, close, high, low) 序列（升序，值转 float）"""
    rows = (
        db.query(StockDailyKline.trade_date, StockDailyKline.close,
                 StockDailyKline.high, StockDailyKline.low)
        .filter(StockDailyKline.ts_code == ts_code,
                StockDailyKline.trade_date >= since)
        .order_by(StockDailyKline.trade_date)
        .all()
    )
    return [(d, float(cl), float(h), float(l)) for d, cl, h, l in rows]


def _track_one(db, ts_code: str, trade_date: date, entry_px: float, signal_code: str, klines: List[tuple]) -> None:
    """对一条信号按 HOLD_DAYS 各持有期计算走势并列写入"""
    # klines 以 >= trade_date 开头，跳过当日（当日收盘即入场），取之后交易日
    after = [k for k in klines if k[0] > trade_date]
    if not after:
        return
    for hold in HOLD_DAYS:
        if len(after) < hold:
            continue  # 后续 K 线不足该持有期，跳过
        window = after[:hold]
        exit_px = window[-1][1]
        if not entry_px or entry_px <= 0:
            continue
        ret_pct = round((exit_px / entry_px - 1) * 100, 2)
        highs = [w[2] for w in window] + [entry_px]
        lows = [w[3] for w in window] + [entry_px]
        max_gain = round((max(highs) / entry_px - 1) * 100, 2)
        min_px = min(lows)
        max_dd = round((min_px / entry_px - 1) * 100, 2)
        out = "胜" if ret_pct > 0 else ("平" if abs(ret_pct) < 1e-6 else "负")
        # 幂等 upsert（ts_code+trade_date+hold 唯一）。
        # 不用 db.merge：session 内已挂同一自然键的 pending 对象时 merge 会再插入一条，
        # 触发 uq_ht_code_date_hold 冲突（000404.SZ/2026-08-10 实测）。
        db.execute(
            insert(HorizontalTrack)
            .values(
                ts_code=ts_code, trade_date=trade_date, signal_code=signal_code,
                entry_px=round(float(entry_px), 3), hold=hold,
                exit_px=round(float(exit_px), 3), ret_pct=ret_pct,
                max_gain=max_gain, max_drawdown=max_dd, out=out,
            )
            .on_conflict_do_update(
                constraint="uq_ht_code_date_hold",
                set_={
                    "signal_code": signal_code,
                    "entry_px": round(float(entry_px), 3),
                    "exit_px": round(float(exit_px), 3),
                    "ret_pct": ret_pct,
                    "max_gain": max_gain,
                    "max_drawdown": max_dd,
                    "out": out,
                },
            )
        )
    db.commit()


def backfill_track(target_date: Optional[str] = None, only_tradeable: bool = False,
                   signal_codes: Optional[List[str]] = None) -> Dict:
    """为 horizontal_signal 信号补充走势跟踪

    target_date: 指定信号日（默认全部已有信号）
    only_tradeable: 仅统计可交易(放宽后)信号
    signal_codes: 仅统计指定信号码（默认 A/B/C/D/None 全算，但通常只关心 A/B/C）
    """
    init_db()
    codes = [c for c in (signal_codes or ["A", "B", "C", "D"]) if c]
    q_filters = [HorizontalSignal.trade_date == date.fromisoformat(target_date)] if target_date else []
    if only_tradeable:
        q_filters.append(HorizontalSignal.tradable.is_(True))

    written = 0
    skipped = {"no_signal": 0, "no_kline": 0}
    with get_db_session() as db:
        sig_rows = (
            db.query(HorizontalSignal.ts_code, HorizontalSignal.trade_date,
                     HorizontalSignal.close, HorizontalSignal.signal_code)
            .filter(*q_filters) if q_filters else
            db.query(HorizontalSignal.ts_code, HorizontalSignal.trade_date,
                     HorizontalSignal.close, HorizontalSignal.signal_code)
        )
        sig_list = [(r.ts_code, r.trade_date, r.close, r.signal_code) for r in sig_rows.all()]

        # 按 ts_code 缓存 K 线序列，避免重复查询
        kline_cache: Dict[str, List[tuple]] = {}
        for ts_code, trade_date, close, sig_code in sig_list:
            if sig_code not in codes:
                skipped["no_signal"] += 1
                continue
            if not close:
                continue
            klines = kline_cache.get(ts_code)
            if klines is None:
                klines = _kline_series(db, ts_code, date(2020, 1, 1))
                kline_cache[ts_code] = klines
            if not klines:
                skipped["no_kline"] += 1
                continue
            _track_one(db, ts_code, trade_date, float(close), sig_code, klines)
            written += 1

    return {"ok": True, "written_signals": written, "skipped": skipped}


def backfill_all_track(signal_codes: Optional[List[str]] = None) -> Dict:
    """对全部 signal 生成走势跟踪（无 target 过滤，全量幂等）。"""
    return backfill_track(target_date=None, only_tradeable=False, signal_codes=signal_codes)


def track_summary() -> Dict:
    """信号后走势汇总（胜率/盈亏比），供分析用"""
    with get_db_session() as db:
        rows = (
            db.query(HorizontalTrack.hold, HorizontalTrack.ret_pct, HorizontalTrack.out)
            .filter(HorizontalTrack.signal_code.in_(["A", "B", "C"]))
            .all()
        )
    summary = {}
    for hold in HOLD_DAYS:
        rs = [(r.out, r.ret_pct) for r in rows if r.hold == hold]
        if not rs:
            summary[str(hold)] = {"n": 0}
            continue
        wins = [r for o, r in rs if o == "胜"]
        losses = [r for o, r in rs if o == "负"]
        flats = [r for o, r in rs if o == "平"]
        wr = len(wins) / len(rs) * 100
        avg_win = (sum(wins) / len(wins)) if wins else 0
        avg_loss = (sum(losses) / len(losses)) if losses else 0
        plr = (avg_win / abs(avg_loss)) if avg_loss else float("inf")
        summary[str(hold)] = {
            "n": len(rs),
            "win_rate": round(wr, 1),
            "avg_ret": round(sum(r for _, r in rs) / len(rs), 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_loss_ratio": round(plr, 2) if plr != float("inf") else None,
        }
    return {"summary": summary}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("track summary:", track_summary())
    print("backfill:", backfill_track(only_tradeable=False))