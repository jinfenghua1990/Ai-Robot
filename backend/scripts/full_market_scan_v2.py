#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全市场高效扫描 - 单次 tdx 连接内跑完 4 个策略
避免每只股票都 reconnect，节省时间
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from datetime import datetime
from collections import defaultdict

from db.connection import get_db
from db.session import get_db_session
from db.models import StockFlow, StrategyResult
from collectors.tdx_collector import connect_with_retry

from strategies.baihu_v26 import baihu_strategy_v26
from strategies.baihu_v30 import baihu_strategy_v30
from strategies.qinglong import qinglong_strategy
from strategies.zhushenglang import zhushenglang_strategy, calc_ma_series
from strategies.volume_breakout import volume_breakout_strategy
from strategies.macd_golden_cross import macd_golden_cross_strategy
from sqlalchemy import desc
import logging
logger = logging.getLogger(__name__)


def _parse_ts_code(ts_code):
    """从 tushare 格式 '000001.SZ' 解析为 (market, pure_code)"""
    code = str(ts_code).strip().lower()
    if '.' in code:
        pure_code, exchange = code.split('.')
        if exchange.startswith('sz'):
            return 0, pure_code
        elif exchange.startswith('sh'):
            return 1, pure_code
        return None, None
    if code.startswith('sz') or code.startswith('sh'):
        prefix = code[:2]
        pure_code = code[2:]
        market = 0 if prefix == 'sz' else 1
        return market, pure_code
    if code.isdigit():
        return (1, code) if code.startswith('6') else (0, code)
    return None, None


def fetch_kline_batch(api, stock_list, days=90):
    """单次连接内为多只股票拉 K 线"""
    out = {}
    ok = 0
    for ts_code in stock_list:
        market, pure_code = _parse_ts_code(ts_code)
        if market is None:
            continue
        try:
            bars = api.get_security_bars(4, market, pure_code, 0, days)
            if not bars or len(bars) < 30:
                continue
            kline = []
            closes_history = []
            ma20_sum = 0.0
            for b in bars:
                close = float(b['close'])
                open_p = float(b['open'])
                high = float(b['high'])
                low = float(b['low'])
                volume = float(b.get('vol', b.get('volume', 0)))
                day = b.get('datetime', '')
                if not day and b.get('year'):
                    day = f"{b['year']:04d}-{b['month']:02d}-{b['day']:02d}"
                closes_history.append(close)
                ma20_sum += close
                if len(closes_history) > 20:
                    ma20_sum -= closes_history[-21]
                ma20 = ma20_sum / 20.0 if len(closes_history) >= 20 else 0.0
                kline.append({
                    'close': close,
                    'open': open_p,
                    'high': high,
                    'low': low,
                    'volume': volume,
                    'ma_price20': ma20 if ma20 > 0 else None,
                    'day': day,
                })
            out[ts_code] = kline
            ok += 1
        except Exception:
            logger.debug(f"function item failed", exc_info=True)
            continue
    return out, ok


def get_main_force_history(db, ts_code, trade_date, days=5):
    """获取近 5 日主力净流入（主升浪用）"""
    from datetime import timedelta
    end = datetime.strptime(trade_date, '%Y-%m-%d').date() if isinstance(trade_date, str) else trade_date
    start = end - timedelta(days=10)
    rows = db.query(StockFlow).filter(
        StockFlow.ts_code == ts_code,
        StockFlow.trade_date >= start,
        StockFlow.trade_date <= end,
    ).order_by(StockFlow.trade_date.asc()).all()
    if len(rows) < 1:
        return None
    flows = [float(r.main_force_inflow or 0) for r in rows[-days:]]
    return flows


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--limit', type=int, default=800, help='候选股票数（按主力净流入降序）')
    args = parser.parse_args()

    trade_date = args.date
    with get_db_session() as db:
        print('=' * 80)
        print(f'📊 高效全市场扫描 - {trade_date} (单连接模式)')
        print('=' * 80)

        rows = db.query(StockFlow).filter(
            StockFlow.trade_date == trade_date,
            StockFlow.main_force_inflow > 0,
        ).order_by(desc(StockFlow.main_force_inflow)).limit(args.limit).all()
        stock_list = [r.ts_code for r in rows]
        name_map = {r.ts_code: (r.name or '') for r in rows}
        sector_map = {r.ts_code: (r.sector or '') for r in rows}
        print(f'\n候选池: {len(stock_list)} 只 (main_force_inflow > 0, 前 {args.limit})')

        # 单连接
        print('\n[1/3] 单次连接获取 K 线...')
        api, server = connect_with_retry()
        if not api:
            print('  ❌ tdx 连接失败')
            return
        print(f'  连接到: {server}')

        t0 = time.time()
        klines, ok = fetch_kline_batch(api, stock_list)
        api.disconnect()
        print(f'  ✅ 成功 {ok}/{len(stock_list)} 只 (耗时 {time.time()-t0:.1f}s)')

        # 跑 4 个策略
        print(f'\n[2/3] 跑 6 个策略...')
        all_hits = defaultdict(lambda: {'name': '', 'sector': '', 'strategies': []})
        strategy_stats = {}

        for key, name, func in [
            ('baihu_v26', '白虎', baihu_strategy_v26),
            ('baihu_v30', '白虎V3', baihu_strategy_v30),
            ('qinglong', '青龙', qinglong_strategy),
            ('volume_breakout', '放量突破', volume_breakout_strategy),
            ('macd_golden_cross', 'MACD金叉', macd_golden_cross_strategy),
        ]:
            t0 = time.time()
            hits = []
            for ts_code, kline in klines.items():
                try:
                    r = func(kline)
                    if r:
                        r['ts_code'] = ts_code
                        hits.append(r)
                except Exception:
                    logger.debug(f"function item failed", exc_info=True)
                    continue
            dur = time.time() - t0
            strategy_stats[key] = {'hits': len(hits), 'duration': dur}
            print(f'  {name}: 命中 {len(hits)} 只 (耗时 {dur:.1f}s)')
            for h in hits:
                ts = h['ts_code']
                all_hits[ts]['name'] = name_map.get(ts, '')
                all_hits[ts]['sector'] = sector_map.get(ts, '')
                all_hits[ts]['strategies'].append({'key': key, 'name': name, 'score': float(h.get('score', 0))})

        # 主升浪（需要 db）
        t0 = time.time()
        hits = []
        for ts_code, kline in klines.items():
            try:
                mf_hist = get_main_force_history(db, ts_code, trade_date)
                r = zhushenglang_strategy(kline, main_force_history=mf_hist)
                if r:
                    r['ts_code'] = ts_code
                    hits.append(r)
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
        dur = time.time() - t0
        strategy_stats['zhushenglang'] = {'hits': len(hits), 'duration': dur}
        print(f'  主升浪: 命中 {len(hits)} 只 (耗时 {dur:.1f}s)')
        for h in hits:
            ts = h['ts_code']
            all_hits[ts]['name'] = name_map.get(ts, '')
            all_hits[ts]['sector'] = sector_map.get(ts, '')
            all_hits[ts]['strategies'].append({'key': 'zhushenglang', 'name': '主升浪', 'score': float(h.get('score', 0))})

        # 排名
        print(f'\n[3/3] 排名与对比')
        print(f'\n{"=" * 80}')
        print('【多策略共振排名】vote_score >= 2')
        print('=' * 80)
        multi = [(t, d) for t, d in all_hits.items() if len(d['strategies']) >= 2]
        multi.sort(key=lambda x: (-len(x[1]['strategies']), -sum(s['score'] for s in x[1]['strategies'])))
        print(f'共 {len(multi)} 只被 2+ 策略同时命中')
        for i, (ts, d) in enumerate(multi[:30], 1):
            names = '+'.join(s['name'] for s in d['strategies'])
            avg_s = sum(s['score'] for s in d['strategies']) / len(d['strategies'])
            print(f'  {i:2d}. {ts} {d["name"]:<8s} [{d["sector"]:<10s}] {len(d["strategies"])}策略 平均{avg_s:.1f}分 | {names}')

        print(f'\n{"=" * 80}')
        print('【单策略 Top 30】按评分')
        print('=' * 80)
        single = [(t, d) for t, d in all_hits.items() if len(d['strategies']) == 1]
        single.sort(key=lambda x: -x[1]['strategies'][0]['score'])
        for i, (ts, d) in enumerate(single[:30], 1):
            s = d['strategies'][0]
            print(f'  {i:2d}. {ts} {d["name"]:<8s} [{d["sector"]:<10s}] {s["name"]} {s["score"]:.0f}分')

        # 策略统计
        print(f'\n{"=" * 80}')
        print('【策略统计】')
        print('=' * 80)
        print(f'{"策略":<12s} {"命中数":>6s} {"候选":>6s} {"占比":>8s} {"耗时(秒)":>10s}')
        for k, n in [('baihu_v26', '白虎'), ('baihu_v30', '白虎V3'), ('qinglong', '青龙'), ('zhushenglang', '主升浪'), ('volume_breakout', '放量突破'), ('macd_golden_cross', 'MACD金叉')]:
            st = strategy_stats.get(k, {})
            hits = st.get('hits', 0)
            dur = st.get('duration', 0)
            pct = hits / ok * 100 if ok else 0
            print(f'{n:<12s} {hits:>6d} {ok:>6d} {pct:>7.2f}% {dur:>9.1f}')

        # 与 strategy_result 当日对比
        print(f'\n{"=" * 80}')
        print('【对比】')
        print('=' * 80)
        existing = db.query(StrategyResult).filter(StrategyResult.trade_date == trade_date).all()
        existing_set = {(r.ts_code, r.strategy_key) for r in existing}
        print(f'  strategy_result 当日: {len(existing)} 条 ({len(set(r.ts_code for r in existing))} 只票 × {len(set(r.strategy_key for r in existing))} 策略)')
        new_hits = set()
        for ts, d in all_hits.items():
            for s in d['strategies']:
                key = (ts, s['key'])
                if key not in existing_set:
                    new_hits.add(key)
        print(f'  全市场扫描新增命中: {len(new_hits)} (现 runner 用 300 池时漏掉的)')

        # 保存
        summary = {
            'date': trade_date,
            'candidates': len(stock_list),
            'kline_ok': ok,
            'total_hits': len(all_hits),
            'multi_strategy': len(multi),
            'by_strategy': strategy_stats,
            'multi_list': [{'ts': t, **d} for t, d in multi],
            'single_top': [{'ts': t, **d} for t, d in single[:50]],
        }
        out = '/tmp/full_market_scan_v2.json'
        with open(out, 'w') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        print(f'\n汇总: {out}')



if __name__ == '__main__':
    main()
