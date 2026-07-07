"""
批量回填: 对 daily_kline 范围每个交易日都跑 update_lifecycle
确保所有 tracker 的 d1..d11 全部填满(能填到 7-6 触发的股)
"""
from datetime import datetime, timedelta
from db.session import get_db_session
from db.models import StockDailyKline
from collectors.lifecycle_tracker import update_lifecycle

with get_db_session() as db:
    days = [d[0] for d in db.query(StockDailyKline.trade_date).distinct().order_by(StockDailyKline.trade_date).all()]
    print(f'daily_kline trade dates: {len(days)} days, {days[0]} ~ {days[-1]}')

for d in days:
    ds = d.strftime('%Y%m%d') if hasattr(d, 'strftime') else str(d).replace('-', '')
    r = update_lifecycle(ds)
    print(f'  {ds}: updated={r["updated"]} skipped={r["skipped"]} finalized={r["finalized"]}')
print('done')
