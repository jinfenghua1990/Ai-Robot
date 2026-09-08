"""
等待 7-06 Tushare 龙虎榜数据 + 拉取 + 全面数据检查
- 18:02 开始第一次尝试
- 每 3 分钟试一次,直到拉到数据或 21:00
- 拉到后自动做全面数据体检
"""
import sys, os, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LOG_FILE = '/tmp/pull_0706_full.log'

def log(msg):
    line = f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def wait_until(hour, minute):
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < target:
        secs = (target - now).total_seconds()
        log(f'waiting {secs:.0f}s until {hour:02d}:{minute:02d}...')
        time.sleep(secs)

def try_pull():
    from collectors.dragon_tiger_collector import run_today
    r = run_today('20260706')
    return r

def full_check():
    """拉到数据后做全面体检"""
    from db.session import get_db_session
    from db.models import YuziDict, YuziSeatDaily, YuziQuantSignal
    from sqlalchemy import func, distinct

    log('=' * 70)
    log('【7-06 数据入库后全面体检】')
    log('=' * 70)

    with get_db_session() as db:
        # 7-06 当日数据
        seat_n = db.query(YuziSeatDaily).filter(YuziSeatDaily.trade_date == '20260706').count()
        sig_n = db.query(YuziQuantSignal).filter(YuziQuantSignal.trade_date == '20260706').count()
        alias_n = db.query(distinct(YuziSeatDaily.yuzi_alias)).filter(
            YuziSeatDaily.trade_date == '20260706'
        ).count()
        stock_n = db.query(distinct(YuziSeatDaily.ts_code)).filter(
            YuziSeatDaily.trade_date == '20260706'
        ).count()
        log(f'7-06 yuzi_seat_daily: {seat_n} 行')
        log(f'7-06 yuzi_quant_signals: {sig_n} 行')
        log(f'7-06 上榜游资: {alias_n} 位')
        log(f'7-06 上榜股票: {stock_n} 只')

        # 7-06 top 10 大佬
        rows = db.query(
            YuziSeatDaily.yuzi_alias,
            YuziDict.style,
            func.sum(YuziSeatDaily.net_amount).label('net'),
        ).outerjoin(
            YuziDict, YuziSeatDaily.seat_name == YuziDict.seat_name
        ).filter(
            YuziSeatDaily.trade_date == '20260706'
        ).group_by(
            YuziSeatDaily.yuzi_alias, YuziDict.style
        ).order_by(func.sum(YuziSeatDaily.net_amount).desc()).limit(10).all()

        log('')
        log('7-06 top 10 大佬(含风格):')
        for r in rows:
            sign = '+' if r.net >= 0 else ''
            log(f'  {r.yuzi_alias:20s} style={r.style or "(未分类)":8s} net={sign}{r.net:.0f}万')

        # 近 7 天数据对比
        log('')
        log('近 7 天数据对比:')
        rows = db.query(
            YuziSeatDaily.trade_date,
            func.count(distinct(YuziSeatDaily.yuzi_alias)).label('n'),
        ).filter(
            YuziSeatDaily.trade_date >= '20260629'
        ).group_by(YuziSeatDaily.trade_date).order_by(YuziSeatDaily.trade_date.desc()).all()
        for r in rows:
            log(f'  {r.trade_date}: {r.n} 位游资')

        # 字典总览
        log('')
        log(f'字典总览: {db.query(YuziDict).count()} 席位, '
            f'{db.query(distinct(YuziDict.yuzi_alias)).count()} 位独立游资')

    log('=' * 70)
    log('【体检完成】刷新 http://localhost:9000/yuzi-billboard 可看到 7-06 数据')
    log('=' * 70)

def main():
    # 清空日志
    with open(LOG_FILE, 'w') as f:
        f.write('')

    log('start: 等待 Tushare 7-06 龙虎榜数据')
    log(f'now: {datetime.now().strftime("%H:%M:%S")}')

    # 等到 18:02
    wait_until(18, 2)

    attempt = 0
    while True:
        now = datetime.now()
        if now.hour >= 21:
            log('gave up at 21:00, Tushare never published 7-06 data')
            return

        attempt += 1
        log(f'attempt {attempt}...')
        try:
            r = try_pull()
            log(f'  result: {r}')
            if r.get('matched', 0) > 0 or r.get('top_list', 0) > 0:
                log(f'SUCCESS! pulled {r.get("matched")} seats, {r.get("signals")} signals')
                # 拉到数据后做全面体检
                full_check()
                return
        except Exception as e:
            log(f'  error: {e}')

        # 等 3 分钟
        time.sleep(180)

if __name__ == '__main__':
    main()
