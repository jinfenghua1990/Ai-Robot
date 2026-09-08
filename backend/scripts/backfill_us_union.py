import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from sqlalchemy import func

sys.path.insert(0, "backend")
from market_quant.universe import get_members
from us_quant.universe import get_universe_members
from us_quant.collector import collect_symbol
from us_quant.repository import USStockDaily
from db.session import get_db_session

symbols = sorted(set(get_members("US", "CORE")) | set(get_members("US", "CORE_B")) |
                 set(get_members("US", "RESEARCH")) | set(get_universe_members("US_WATCHLIST")))
with get_db_session() as db:
    rows = db.query(USStockDaily.symbol, func.count(USStockDaily.id),
                    func.min(USStockDaily.trade_date), func.max(USStockDaily.trade_date)) \
        .filter(USStockDaily.symbol.in_(symbols)).group_by(USStockDaily.symbol).all()
complete = {r[0] for r in rows if r[1] >= 180 and r[2] <= date(2025, 8, 7) and r[3] >= date(2026, 8, 7)}
needed = [s for s in symbols if s not in complete]
print(f"union={len(symbols)} complete={len(complete)} needed={len(needed)}", flush=True)
failed = []
for offset in range(0, len(needed), 50):
    batch = needed[offset:offset + 50]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(collect_symbol, s, force_backfill=True, compute_factors=False): s for s in batch}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                future.result()
            except Exception as exc:
                failed.append((symbol, str(exc)))
    print(f"processed={min(offset + 50, len(needed))}/{len(needed)} failed={len(failed)}", flush=True)
print("FAILED", failed, flush=True)
