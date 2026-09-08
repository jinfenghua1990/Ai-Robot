# -*- coding: utf-8 -*-
"""横盘蓄势：历史逐日重建扫描 和/或 走势跟踪回填

用法:
    python strategies/horizontal/backfill_horizontal.py                 # scan+track 一整年
    python strategies/horizontal/backfill_horizontal.py --scan-only     # 只重建 signal
    python strategies/horizontal/backfill_horizontal.py --track-only    # 只补 track
    python strategies/horizontal/backfill_horizontal.py 2026-08-01 2026-08-26 [--scan-only|--track-only]
开区间起止日期（含）都传。scan 以"截至当日"重建 signal；track 从 signal 生成走势。

全程纯 DB。scan 幂等（按 ts_code+trade_date upsert），track 幂等（按 ts_code+trade_date+hold merge）。
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date

sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger('horizontal.backfill')


def all_trade_dates(start: str, end: str):
    from sqlalchemy import text
    from db.connection import engine
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT DISTINCT trade_date FROM stock_daily_kline "
            "WHERE trade_date>=:a AND trade_date<=:b ORDER BY trade_date"
        ), {"a": start, "b": end}).fetchall()
    return [r[0] for r in rows]


def do_scan(dates):
    from strategies.horizontal.runner import run_scan
    logger.info("[scan] 开始 %d 个交易日回填", len(dates))
    t0 = time.time()
    for i, d in enumerate(dates, 1):
        ds = str(d)
        try:
            r = run_scan(ds)
            st = r.get("stats", {})
            logger.info("[scan %3d/%d] %s boxed=%s sig=%s tradable=%s (%ds)"
                        % (i, len(dates), ds, st.get("boxed"), st.get("signals"),
                           st.get("tradable"), time.time() - t0))
        except Exception as e:
            logger.error("[scan %d] %s failed: %s", i, ds, e)
    logger.info("[scan] 完成 %d 天", len(dates))


def do_track():
    from strategies.horizontal.tracker import backfill_all_track
    logger.info("[track] 全量回填走势跟踪")
    r = backfill_all_track()
    logger.info("[track] done: %s", r)


def main():
    args = [a for a in sys.argv[1:]]
    scan_only = "--scan-only" in args
    track_only = "--track-only" in args
    pos = [a for a in args if not a.startswith("--")]

    today = date.today()
    default_end = str(today)
    default_start = str(today.replace(year=today.year - 1))
    start = pos[0] if len(pos) >= 1 else default_start
    end = pos[1] if len(pos) >= 2 else default_end

    if not track_only:
        dates = all_trade_dates(start, end)
        do_scan(dates)
    if not scan_only:
        do_track()


if __name__ == "__main__":
    main()