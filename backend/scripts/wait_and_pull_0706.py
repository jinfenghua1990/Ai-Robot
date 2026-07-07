"""
等待 Tushare 7-06 龙虎榜数据并触发采集
每 5 分钟试一次,直到拉到数据或超过 21:00
"""
import sys, os, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.dragon_tiger_collector import run_today

TARGET_DATE = '20260706'
MAX_WAIT_UNTIL = 21  # 21:00 后放弃

def try_once():
    r = run_today(TARGET_DATE)
    return r

def main():
    print(f'[wait_and_pull] target={TARGET_DATE}, polling every 5 min until {MAX_WAIT_UNTIL}:00')
    attempt = 0
    while True:
        now = datetime.now()
        if now.hour >= MAX_WAIT_UNTIL:
            print(f'[wait_and_pull] gave up at {now.strftime("%H:%M")}, Tushare never published data')
            return

        attempt += 1
        print(f'[wait_and_pull] attempt {attempt} at {now.strftime("%H:%M:%S")}...')
        try:
            r = try_once()
            print(f'  result: {r}')
            if r.get('matched', 0) > 0 or r.get('top_list', 0) > 0:
                print(f'[wait_and_pull] SUCCESS! pulled {r.get("matched")} seats, {r.get("signals")} signals')
                return
        except Exception as e:
            print(f'  error: {e}')

        # 等 5 分钟
        time.sleep(300)

if __name__ == '__main__':
    main()
