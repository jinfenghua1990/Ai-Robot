"""
日 K 线同步：将 Tushare daily 接口数据落地到 stock_daily_kline 表

用法:
    python -m collectors.sync_daily_kline --start 20260625 --end 20260706
"""
import logging
import argparse
from datetime import datetime, timedelta

from db.connection import engine
from db.session import get_db_session
from db.models import StockDailyKline
from sqlalchemy import text

logger = logging.getLogger(__name__)


def sync_daily_kline(start_date: str, end_date: str) -> dict:
    """
    拉取区间内每个交易日的全市场日线 → upsert 到 stock_daily_kline
    使用 Tushare daily 接口,一次调用获取全市场 ~5000 条
    """
    from collectors.tdx_collector import call_tushare_mcp

    sd = datetime.strptime(start_date, '%Y%m%d')
    ed = datetime.strptime(end_date, '%Y%m%d')
    if sd > ed:
        sd, ed = ed, sd

    total_inserted = 0
    total_updated = 0
    days_done = 0
    cur = sd
    while cur <= ed:
        d = cur.strftime('%Y%m%d')
        try:
            rows = call_tushare_mcp(
                api_name='daily',
                params={'trade_date': d},
                fields=['ts_code', 'trade_date', 'open', 'high', 'low', 'close',
                        'pre_close', 'pct_chg', 'vol', 'amount'],
            )
            if not rows:
                logger.info(f'[{d}] 无数据(非交易日?)')
                cur += timedelta(days=1)
                continue

            # upsert: 一次性 insert on conflict do update
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            with get_db_session() as db:
                stmt = pg_insert(StockDailyKline.__table__).values([
                    {
                        'ts_code': r['ts_code'],
                        'trade_date': datetime.strptime(r['trade_date'], '%Y%m%d').date(),
                        'open': r.get('open'),
                        'high': r.get('high'),
                        'low': r.get('low'),
                        'close': r.get('close'),
                        'volume': r.get('vol'),
                        'amount': r.get('amount'),
                        'pct_chg': r.get('pct_chg'),
                    } for r in rows
                ])
                stmt = stmt.on_conflict_do_update(
                    index_elements=['ts_code', 'trade_date'],
                    set_={
                        'open': stmt.excluded.open,
                        'high': stmt.excluded.high,
                        'low': stmt.excluded.low,
                        'close': stmt.excluded.close,
                        'volume': stmt.excluded.volume,
                        'amount': stmt.excluded.amount,
                        'pct_chg': stmt.excluded.pct_chg,
                    },
                )
                db.execute(stmt)
                db.commit()
            total_inserted += len(rows)
            days_done += 1
            logger.info(f'[{d}] 写入 {len(rows)} 条')
        except Exception as e:
            logger.error(f'[{d}] 同步失败: {e}', exc_info=True)
        cur += timedelta(days=1)

    return {'days_done': days_done, 'rows_synced': total_inserted}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    r = sync_daily_kline(args.start, args.end)
    print(r)
