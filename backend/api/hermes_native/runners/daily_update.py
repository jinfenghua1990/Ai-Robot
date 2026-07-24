#!/usr/bin/env python3
"""
每日盘后数据更新脚本
使用 pytdx 获取最新数据，失败则从数据库读取
支持手动指定通达信服务器
"""
import sys, os, time
from datetime import datetime, timedelta

sys.path.insert(0, '/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database')
from api.hermes_native.runners.data_collector import daily_update, get_best_server, set_custom_server


def main():
    print(f'[daily] Starting daily update at {datetime.now()}', flush=True)
    
    # 如果有自定义服务器参数，设置它
    if len(sys.argv) >= 3:
        ip = sys.argv[1]
        port = int(sys.argv[2])
        set_custom_server(ip, port)
        print(f'[daily] Using custom server: {ip}:{port}', flush=True)
    
    # 先检测服务器
    server = get_best_server()
    if server:
        print(f'[daily] TDX server available: {server[0]}:{server[1]}', flush=True)
    else:
        print(f'[daily] Warning: No TDX server available, only using database', flush=True)
    
    # 更新最近5天数据（覆盖周末）
    result = daily_update(days=5, max_workers=20)
    
    print(f'\n[daily] Update complete:', flush=True)
    print(f'  Success: {result["success"]} stocks', flush=True)
    print(f'  Failed: {result["failed"]} stocks', flush=True)
    print(f'  Total rows updated: {result["total_rows"]}', flush=True)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())