"""股东户数/户均持股采集（Tushare stk_holdernumber）"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import SessionLocal
from db.models import StockHolderNumber
from sqlalchemy.dialects.postgresql import insert as pg_insert
import tushare as ts


def fetch_holder_number(ts_code: str = None, start_date: str = None, end_date: str = None, token: str = None):
    """从 Tushare 拉取股东户数数据"""
    if token is None:
        token = os.getenv('TUSHARE_TOKEN')
    if not token:
        raise RuntimeError('TUSHARE_TOKEN not set')
    pro = ts.pro_api(token)
    params = {}
    if ts_code:
        params['ts_code'] = ts_code
    if start_date:
        params['start_date'] = start_date
    if end_date:
        params['end_date'] = end_date
    df = pro.stk_holdernumber(**params)
    if df is None or df.empty:
        return []
    import math
    rows = []
    for _, r in df.iterrows():
        def _int(v):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return 0
            return int(v)
        def _float(v):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return 0.0
            return float(v)
        rows.append({
            'ts_code': r.get('ts_code'),
            'name': r.get('name'),
            'ann_date': _parse_date(r.get('ann_date')),
            'end_date': _parse_date(r.get('end_date')),
            'holder_num': _int(r.get('holder_num')),
            'avg_shares': _float(r.get('avg_shares')),
        })
    return rows


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, str):
        return datetime.strptime(v, '%Y%m%d').date()
    return v


def save_rows(rows):
    if not rows:
        return 0
    db = SessionLocal()
    try:
        for row in rows:
            stmt = pg_insert(StockHolderNumber).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=['ts_code', 'ann_date'],
                set_={
                    'name': stmt.excluded.name,
                    'end_date': stmt.excluded.end_date,
                    'holder_num': stmt.excluded.holder_num,
                    'avg_shares': stmt.excluded.avg_shares,
                }
            )
            db.execute(stmt)
        db.commit()
        return len(rows)
    finally:
        db.close()


def run_full_refresh():
    """全量：拉最近 5 年数据"""
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=365 * 5)).strftime('%Y%m%d')
    rows = fetch_holder_number(start_date=start, end_date=end)
    return save_rows(rows)


def run_daily():
    """增量：拉最近 90 天，覆盖最新一期"""
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
    rows = fetch_holder_number(start_date=start, end_date=end)
    return save_rows(rows)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', action='store_true', help='full refresh')
    args = parser.parse_args()
    count = run_full_refresh() if args.full else run_daily()
    print(f'saved {count} rows')
