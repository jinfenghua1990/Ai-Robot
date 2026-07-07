#!/usr/bin/env python3
"""查看数据库中的最新数据状态"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.connection import get_db
from db.models import LeaderLifecycle, SectorFlow, StockFlow

db = next(get_db())
try:
    # 最新数据日期
    latest = db.query(SectorFlow.trade_date).order_by(SectorFlow.trade_date.desc()).first()
    print(f'最新数据日期: {latest[0] if latest else None}')
    print()

    # 龙头生命周期统计
    if latest:
        leaders = db.query(LeaderLifecycle).filter_by(trade_date=latest[0]).all()
        print(f'龙头数量: {len(leaders)}')
        if leaders:
            print('示例龙头 (Top 5):')
            for l in leaders[:5]:
                print(f'  {l.ts_code} | {l.name} | {l.sector} | {l.stage} | 强度:{l.strength} | 连板:{l.consecutive_days}')
        print()

        # 板块统计
        sectors = db.query(SectorFlow).filter_by(trade_date=latest[0]).order_by(SectorFlow.heat_score.desc()).all()
        print(f'板块数量: {len(sectors)}')
        if sectors:
            print('Top 5 热门板块:')
            for s in sectors[:5]:
                print(f'  {s.sector} | 热度:{s.heat_score} | 净流入:{s.net_flow} | 涨停:{s.limit_up_count}')

        # 各阶段统计
        print()
        print('龙头阶段分布:')
        stages = {}
        for l in leaders:
            stages[l.stage] = stages.get(l.stage, 0) + 1
        for stage, count in sorted(stages.items(), key=lambda x: -x[1]):
            print(f'  {stage}: {count}只')

finally:
    db.close()
