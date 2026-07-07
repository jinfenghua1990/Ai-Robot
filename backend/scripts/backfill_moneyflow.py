"""
回补近1年个股主力资金数据到 StockFlow 表（科创+创业板）
数据源：tushare pro.moneyflow（按交易日遍历，单次返回全市场）
单位：tushare 原生万元，与 StockFlow 一致，无需转换

字段映射：
  main_force_inflow = net_mf_amount（主力净流入 = 超大单净额 + 大单净额）
  net_inflow        = net_mf_amount（保持一致）
  retail_flow       = buy_sm_amount - sell_sm_amount（小单/散户净额）
  name / sector     = 从 pro.stock_basic 补
"""
import os
import sys
import time
from datetime import datetime, date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_db, engine, Base
from db.session import get_db_session
from db.models import StockFlow
from config import TUSHARE_TOKEN
import tushare as ts

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


def is_target(ts_code):
    """科创(688.SH) + 创业(300/301.SZ)"""
    if ts_code.startswith('688') and ts_code.endswith('.SH'):
        return True
    if ts_code.startswith(('300', '301')) and ts_code.endswith('.SZ'):
        return True
    return False


def backfill(days=365):
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')

    # 1. 交易日历
    print(f'[backfill] 获取交易日历 {start_str} ~ {end_str}')
    cal = pro.trade_cal(exchange='SSE', start_date=start_str, end_date=end_str, is_open='1')
    trade_dates = sorted(cal['cal_date'].tolist())
    print(f'[backfill] 共 {len(trade_dates)} 个交易日')

    # 2. 股票基础信息（name, industry）
    print('[backfill] 获取股票基础信息...')
    basic = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,industry')
    basic_map = {r['ts_code']: {'name': r['name'], 'industry': r['industry']} for _, r in basic.iterrows()}
    print(f'[backfill] 股票基础信息 {len(basic_map)} 条')

    # 3. 检查已采集的交易日（跳过已完整的）
    with get_db_session() as db:
        existing_rows = db.query(StockFlow.trade_date).filter(
            StockFlow.trade_date >= start_date,
            StockFlow.main_force_inflow.isnot(None)
        ).distinct().all()
        existing_dates = set(str(r[0]) for r in existing_rows)

    todo = []
    for d in trade_dates:
        d_iso = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        if d_iso in existing_dates:
            continue
        todo.append(d)
    print(f'[backfill] 已采集 {len(trade_dates) - len(todo)} 天，待采集 {len(todo)} 天')

    # 4. 逐日采集
    total_rows = 0
    for i, d in enumerate(todo):
        d_iso = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        t0 = time.time()
        try:
            df = pro.moneyflow(trade_date=d)
        except Exception as e:
            print(f'[backfill] {d_iso} API错误: {e}, 等待5s重试')
            time.sleep(5)
            try:
                df = pro.moneyflow(trade_date=d)
            except Exception as e2:
                print(f'[backfill] {d_iso} 重试失败: {e2}, 跳过')
                continue

        if df is None or len(df) == 0:
            print(f'[{i+1}/{len(todo)}] {d_iso} 无数据')
            continue

        # 过滤科创+创业
        df = df[df['ts_code'].apply(is_target)]
        day_count = 0
        try:
            with get_db_session() as db:
                existing = {s.ts_code: s for s in db.query(StockFlow).filter_by(trade_date=d_iso).all()}
                for _, r in df.iterrows():
                    ts_code = r['ts_code']
                    net_mf = float(r.get('net_mf_amount') or 0)
                    retail = float(r.get('buy_sm_amount') or 0) - float(r.get('sell_sm_amount') or 0)
                    info = basic_map.get(ts_code, {})
                    rec = existing.get(ts_code)
                    if rec:
                        rec.main_force_inflow = net_mf
                        rec.net_inflow = net_mf
                        rec.retail_flow = retail
                        if not rec.name:
                            rec.name = info.get('name')
                        if not rec.sector:
                            rec.sector = info.get('industry')
                    else:
                        db.add(StockFlow(
                            trade_date=d_iso,
                            ts_code=ts_code,
                            name=info.get('name'),
                            sector=info.get('industry'),
                            net_inflow=net_mf,
                            main_force_inflow=net_mf,
                            retail_flow=retail,
                        ))
                    day_count += 1
                db.commit()
                total_rows += day_count
                elapsed = time.time() - t0
                print(f'[{i+1}/{len(todo)}] {d_iso} 写入 {day_count} 条 ({elapsed:.1f}s) 累计 {total_rows}')
        except Exception as e:
            db.rollback()
            print(f'[backfill] {d_iso} 写入失败: {e}')

        # 控制频率：tushare moneyflow 限制 500次/分钟，0.2s 间隔足够
        time.sleep(0.2)

    print(f'[backfill] 完成！共 {len(todo)} 天，{total_rows} 条记录')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=365, help='回补天数（默认365）')
    args = parser.parse_args()
    backfill(args.days)
