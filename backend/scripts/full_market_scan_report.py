#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场策略扫描报告（只读，不动 StrategyResult 表）
用法：python3 scripts/full_market_scan_report.py [--date YYYY-MM-DD]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from datetime import datetime
from collections import Counter, defaultdict

from db.connection import get_db
from db.session import get_db_session
from db.models import (
    StrategyResult, StrategyRunLog, StockFlow,
    AutoTradeConfig, AutoTradeLog,
)
from services.strategy_runner import STRATEGIES, get_candidate_stocks, get_strategy_meta
import importlib


def get_all_stocks_today(db, trade_date):
    """获取当日全市场股票（不限主力净流入），按成交额降序前 1500 只"""
    rows = db.query(
        StockFlow.ts_code,
        StockFlow.name,
        StockFlow.sector,
        StockFlow.main_force_inflow,
    ).filter(
        StockFlow.trade_date == trade_date,
    ).order_by(
        StockFlow.main_force_inflow.desc()
    ).limit(1500).all()
    return [{
        'ts_code': r.ts_code,
        'name': r.name or '',
        'sector': r.sector or '',
        'main_force_inflow': float(r.main_force_inflow or 0),
    } for r in rows]


def run_strategy_safely(strategy_key, stock_list, trade_date_str, db):
    """跑单个策略（不落库，仅收集结果）。返回 (hits, dur, error_str)"""
    meta = get_strategy_meta(strategy_key)
    if not meta:
        return [], 0, 'unknown strategy'
    try:
        mod = importlib.import_module(meta['module'])
        screen_func = getattr(mod, meta['func'])
        t0 = time.time()
        if meta['needs_db']:
            hits = screen_func(stock_list, trade_date_str, db=db)
        else:
            hits = screen_func(stock_list, trade_date_str)
        dur = time.time() - t0
        return hits, dur, None
    except Exception as e:
        return [], 0, str(e)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'))
    args = parser.parse_args()

    trade_date = args.date
    with get_db_session() as db:
        print('=' * 80)
        print(f'📊 全市场策略扫描报告 - {trade_date}')
        print('=' * 80)

        # 1. 候选池
        all_stocks = get_all_stocks_today(db, trade_date)
        print(f'\n【候选池】全市场 {len(all_stocks)} 只（按主力净流入降序前 1500）')
        print(f'  来自: stock_flow 表 trade_date = {trade_date}')

        # 对比现有 strategy_runner 的候选池（前 300）
        runner_candidates = get_candidate_stocks(db, trade_date, limit=300)
        print(f'  现 runner 实际用: {len(runner_candidates)} 只 (main_force_inflow > 0)')

        stock_list = [c['ts_code'] for c in all_stocks]
        name_map = {c['ts_code']: c['name'] for c in all_stocks}
        sector_map = {c['ts_code']: c['sector'] for c in all_stocks}

        # 2. 跑 4 个策略
        all_hits = {}  # ts_code -> {strategy: [...]}
        strategy_stats = {}

        for s in STRATEGIES:
            key = s['key']
            name = s['name']
            print(f'\n--- 跑 {s["icon"]}{name} ({key}) ---')
            hits, dur, err = run_strategy_safely(key, stock_list, trade_date, db)
            if err is not None:
                print(f'  ❌ 失败: {err}')
                strategy_stats[key] = {'error': err, 'hits': 0, 'duration': 0}
                continue
            print(f'  ✅ 命中 {len(hits)} / {len(stock_list)} 只 (耗时 {dur:.1f}s)')
            strategy_stats[key] = {'hits': len(hits), 'duration': dur}
            for h in hits:
                ts_code = h.get('ts_code', '')
                if ts_code not in all_hits:
                    all_hits[ts_code] = {'name': name_map.get(ts_code, ''), 'sector': sector_map.get(ts_code, ''), 'strategies': []}
                all_hits[ts_code]['strategies'].append({
                    'key': key,
                    'name': name,
                    'score': float(h.get('score', 0)),
                })

        # 3. 多策略共振排名
        print(f'\n{"=" * 80}')
        print('【多策略共振排名】vote_score >= 2')
        print('=' * 80)
        multi = [(t, d) for t, d in all_hits.items() if len(d['strategies']) >= 2]
        multi.sort(key=lambda x: (-len(x[1]['strategies']), -sum(s['score'] for s in x[1]['strategies'])))
        print(f'共 {len(multi)} 只票被 2+ 策略同时命中')
        for i, (ts, d) in enumerate(multi[:30], 1):
            names = '+'.join(s['name'] for s in d['strategies'])
            avg_s = sum(s['score'] for s in d['strategies']) / len(d['strategies'])
            print(f'  {i:2d}. {ts} {d["name"]:<8s} [{d["sector"]:<10s}] {len(d["strategies"])}策略 平均{avg_s:.1f}分 | {names}')

        # 4. 单策略高强度
        print(f'\n{"=" * 80}')
        print('【单策略高强度 Top 20】vote_score=1 但策略评分 >= 7')
        print('=' * 80)
        single_strong = []
        for ts, d in all_hits.items():
            if len(d['strategies']) == 1:
                s = d['strategies'][0]
                if s['score'] >= 7:
                    single_strong.append((ts, d, s))
        single_strong.sort(key=lambda x: -x[2]['score'])
        for i, (ts, d, s) in enumerate(single_strong[:20], 1):
            print(f'  {i:2d}. {ts} {d["name"]:<8s} [{d["sector"]:<10s}] {s["name"]} {s["score"]}分')

        # 5. 与现 strategy_result 表对比
        print(f'\n{"=" * 80}')
        print('【对比】现有 strategy_result 当日命中 vs 全市场扫描结果')
        print('=' * 80)
        existing = db.query(StrategyResult).filter(StrategyResult.trade_date == trade_date).all()
        existing_set = {(r.ts_code, r.strategy_key) for r in existing}
        print(f'strategy_result 当日: {len(existing)} 条 ({len(set(r.ts_code for r in existing))} 只票 × {len(set(r.strategy_key for r in existing))} 策略)')
        print()
        # 全市场扫描多出来的新命中
        new_hits = set()
        for ts, d in all_hits.items():
            for s in d['strategies']:
                key = (ts, s['key'])
                if key not in existing_set:
                    new_hits.add(key)
        print(f'全市场扫描新增命中: {len(new_hits)} (只跑候选池 300 时漏掉的)')

        # 6. 策略统计汇总
        print(f'\n{"=" * 80}')
        print('【策略统计汇总】')
        print('=' * 80)
        print(f'{"策略":<12s} {"命中数":>6s} {"占比":>8s} {"耗时(秒)":>10s}')
        for s in STRATEGIES:
            st = strategy_stats.get(s['key'], {})
            hits = st.get('hits', 0)
            dur = st.get('duration', 0)
            pct = hits / len(stock_list) * 100 if stock_list else 0
            print(f'{s["name"]:<12s} {hits:>6d} {pct:>7.2f}% {dur:>9.1f}')

        # 7. 写入临时结果到 memory
        summary = {
            'date': trade_date,
            'total_candidates': len(stock_list),
            'total_hits': len(all_hits),
            'multi_strategy': len(multi),
            'single_strong': len(single_strong),
            'by_strategy': strategy_stats,
        }
        out = '/tmp/full_market_scan_result.json'
        with open(out, 'w') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        print(f'\n汇总已保存: {out}')



if __name__ == '__main__':
    main()
