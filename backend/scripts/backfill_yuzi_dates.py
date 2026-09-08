"""
龙虎榜历史回填脚本：补过去 N 天的 yuzi_seat_daily + yuzi_quant_signals
用法: PYTHONPATH=. python scripts/backfill_yuzi_dates.py 30
"""
import sys, os, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import get_db_session
from db.models import YuziSeatDaily
from collectors.dragon_tiger_collector import backfill_yuzi


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    # 先看当前 DB 里 yuzi_seat_daily 已有哪些日期
    with get_db_session() as db:
        existing = sorted({r[0] for r in db.query(YuziSeatDaily.trade_date).distinct().all()})
    print(f'[backfill_yuzi] existing dates: {len(existing)}')
    if existing:
        print(f'  earliest: {existing[0]}, latest: {existing[-1]}')

    print(f'[backfill_yuzi] backfilling {start_date} ~ {end_date} ({days} days)...')
    results = backfill_yuzi(start_date, end_date)
    success = sum(1 for r in results if r.get('matched', 0) > 0)
    no_data = sum(1 for r in results if r.get('matched', 0) == 0)
    total_signals = sum(r.get('signals', 0) for r in results)
    print(f'[backfill_yuzi] done: {success} days with data, {no_data} days no-data, '
          f'{len(results)} days total, {total_signals} signals written')


if __name__ == '__main__':
    main()
