"""
游资 7 天生命周期跟踪中转调度器 (main_tracker.py)

数据流：
1) trigger_d1() - 找出 yuzi_quant_signals 当日共振数≥2 且 净买>0 的信号,
                   INSERT 到 yuzi_lifecycle_tracker (D1 触发记录)
2) update_lifecycle(target_date) - 对所有 trigger_date >= today-30 的股票,
                    拉 Tushare daily 算 day_diff (1-20),
                    组装 7 维度状态 → UPDATE lifecycle_data JSONB
3) finalize_outcome() - 对已填到 Day 20+ 的,计算 final_outcome + net_return_20d

CLI:
    python lifecycle_tracker.py d1 --date 20260703   # 手动补 D1
    python lifecycle_tracker.py update --date 20260704  # 补某日 D2-D20
    python lifecycle_tracker.py run --date 20260704     # d1 + update 一条龙
"""
import json
import logging
import time
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from sqlalchemy import desc

from db.connection import engine
from db.session import get_db_session
from db.models import (
    YuziQuantSignal, YuziLifecycleTracker, YuziSeatDaily,
    StockDailyKline, StockFlow,
)

logger = logging.getLogger(__name__)


# ============================================================
# D1 触发器
# ============================================================
def trigger_d1(trade_date: str) -> int:
    """
    把 trade_date 当日触发 D1 条件的共振股写入 tracker 表
    D1 触发条件（与 yuzi_quant_signals 一致）：
        - resonance_count >= 1   (放宽:至少1位游资共振)
        - total_net_buy > 0
        - quant_score >= 60      (放宽:中等置信度起步)

    Returns: 新增行数
    """
    inserted = 0
    with get_db_session() as db:
        # 1) 找当日触发股 (排除 ST/*ST 股票)
        rows = db.query(YuziQuantSignal).filter(
            YuziQuantSignal.trade_date == trade_date,
            YuziQuantSignal.resonance_count >= 1,
            YuziQuantSignal.total_net_buy > 0,
            YuziQuantSignal.quant_score >= 60,
            ~YuziQuantSignal.stock_name.like('%ST%'),
        ).all()

        for r in rows:
            # 2) 跳过已存在
            exists = db.query(YuziLifecycleTracker).filter(
                YuziLifecycleTracker.trigger_date == trade_date,
                YuziLifecycleTracker.ts_code == r.ts_code,
            ).first()
            if exists:
                continue
            # 3) INSERT
            db.add(YuziLifecycleTracker(
                trigger_date=trade_date,
                ts_code=r.ts_code,
                stock_name=r.stock_name or '',
                quant_score_d1=r.quant_score,
                boss_list_d1=r.boss_list or '',
                resonance_count_d1=r.resonance_count,
                lifecycle_data=json.dumps({}, ensure_ascii=False),
                day_filled=1,
                final_outcome='未结束',
            ))
            inserted += 1
        db.commit()
    logger.info(f'[trigger_d1] {trade_date} inserted={inserted}')
    return inserted


# ============================================================
# D2-D7 增量更新
# ============================================================
def _tushare_daily(ts_code: str, trade_date: str) -> Optional[dict]:
    """调 Tushare 拉日线"""
    from collectors.tdx_collector import call_tushare_mcp
    rows = call_tushare_mcp(
        api_name='daily',
        params={'ts_code': ts_code, 'trade_date': trade_date},
        fields=['ts_code', 'trade_date', 'open', 'high', 'low', 'close',
                'pre_close', 'change', 'pct_chg', 'vol', 'amount', 'turnover_rate'],
    )
    if rows:
        return rows[0]
    return None


def _tushare_top_list_for_stock(ts_code: str, trade_date: str) -> Optional[dict]:
    """看某股某日是否上龙虎榜(用于 capital_retention 判断)"""
    from collectors.tdx_collector import call_tushare_mcp
    rows = call_tushare_mcp(
        api_name='top_list',
        params={'ts_code': ts_code, 'trade_date': trade_date},
        fields=['ts_code', 'net_amount', 'net_rate', 'reason'],
    )
    if rows:
        return rows[0]
    return None


def _read_daily_kline(ts_code: str, trade_date: str) -> Optional[dict]:
    """从中转层 stock_daily_kline 读日线数据（不再实时调 Tushare）"""
    with get_db_session() as db:
        d_str = f'{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}'
        row = db.query(StockDailyKline).filter(
            StockDailyKline.ts_code == ts_code,
            StockDailyKline.trade_date == d_str,
        ).first()
        if not row:
            return None
        close = float(row.close or 0)
        pct_chg = float(row.pct_chg or 0)
        # pre_close 反推: close = pre_close * (1 + pct_chg/100)
        pre_close = close / (1 + pct_chg / 100) if pct_chg != 0 else close
        return {
            'open': float(row.open or 0),
            'high': float(row.high or 0),
            'low': float(row.low or 0),
            'close': close,
            'pre_close': pre_close,
            'pct_chg': pct_chg,
        }


def _read_top_list(ts_code: str, trade_date: str) -> Optional[dict]:
    """从中转层 yuzi_seat_daily 读当日席位净额(替代 Tushare top_list)"""
    with get_db_session() as db:
        rows = db.query(YuziSeatDaily).filter(
            YuziSeatDaily.ts_code == ts_code,
            YuziSeatDaily.trade_date == trade_date,
        ).all()
        if not rows:
            return None
        return {
            'net_amount': sum(float(r.net_amount or 0) for r in rows) * 10000.0,  # 万→元
        }


def _trading_day_diff(trigger_dt: datetime, target_dt: datetime) -> int:
    """
    算两个日期之间的"交易日序号"差(跳过周末)
    - d1 = trigger_dt 本身
    - 例: 6-25(四)→6-29(一) = 3 个交易日 (跳过 6-27/28 周末)
    """
    if target_dt < trigger_dt:
        return 0
    cur = trigger_dt
    count = 0
    while cur <= target_dt:
        if cur.weekday() < 5:  # 周一到周五
            count += 1
        cur += timedelta(days=1)
    return count


def _classify_price_stage(pct_chg: float, open_premium: float) -> str:
    """价格状态分类"""
    if pct_chg >= 9.8:
        return '连板'
    if pct_chg <= -9.8:
        return '跌停A杀'
    if open_premium >= 3.0 and pct_chg >= 5.0:
        return '晋级'   # 竞价强 + 大涨
    if open_premium <= -3.0 and pct_chg <= -3.0:
        return '分歧'   # 竞价弱 + 收跌
    if abs(pct_chg) < 1.5:
        return '震荡'
    if pct_chg > 0:
        return '偏多'
    return '偏空'


def _classify_capital_retention(yesterday_seat_net: float, today_seat_net: float) -> str:
    """资金留存判断(简化版,基于龙虎榜席位净买变化)"""
    if yesterday_seat_net is None or today_seat_net is None:
        return '无数据'
    if today_seat_net > 0 and today_seat_net >= yesterday_seat_net * 0.7:
        return '锁仓'
    if today_seat_net > 0 and today_seat_net < yesterday_seat_net * 0.7:
        return '减仓'
    if today_seat_net < 0:
        return '出货'
    return '无数据'


def _classify_support(open_premium: float, intra_amp: float, pct_chg: float) -> str:
    """承接力度(竞价+振幅+收涨)"""
    if open_premium >= 2.0 and pct_chg > 0:
        return '强'
    if open_premium <= -2.0 and pct_chg < 0:
        return '弱'
    if intra_amp > 12:
        return '弱'  # 振幅大+没方向 = 承接混乱
    return '中'


def _compute_day_metrics(ts_code: str, trade_date: str, yesterday_seat_net: Optional[float]) -> Optional[dict]:
    """组装 7 维度:全部从 DB 中转层读"""
    daily = _read_daily_kline(ts_code, trade_date)
    if not daily:
        return None

    open_p = daily['open']
    high_p = daily['high']
    low_p = daily['low']
    pre_close = daily['pre_close']
    pct_chg = daily['pct_chg']

    # 从 stock_flow 读资金数据
    with get_db_session() as db:
        sf = db.query(StockFlow).filter(
            StockFlow.ts_code == ts_code,
            StockFlow.trade_date == trade_date,
        ).first()
        main_force = float(sf.main_force_inflow or 0) if sf else 0  # 主力净流入(万)
        net_inflow = float(sf.net_inflow or 0) if sf else 0  # 总净流入(万)
        retail_flow = float(sf.retail_flow or 0) if sf else 0  # 散户净流入(万)

    open_premium = (open_p / pre_close - 1) * 100 if pre_close > 0 else 0
    intra_amp = (high_p - low_p) / pre_close * 100 if pre_close > 0 else 0
    price_stage = _classify_price_stage(pct_chg, open_premium)

    # 资金留存:从 yuzi_seat_daily 读当日席位净额
    top = _read_top_list(ts_code, trade_date)
    today_seat_net = top['net_amount'] / 10000.0 if top else None  # 元→万
    capital_retention = _classify_capital_retention(yesterday_seat_net, today_seat_net or 0)

    support = _classify_support(open_premium, intra_amp, pct_chg)

    # 主力主导度 = |主力| / (|主力| + |散户|), 0-100 之间
    total_abs = abs(main_force) + abs(retail_flow)
    main_force_ratio = round(abs(main_force) / total_abs * 100, 0) if total_abs > 0 else 0

    return {
        'price_stage': price_stage,
        'open_premium': round(open_premium, 2),
        'intra_amplitude': round(intra_amp, 2),
        'pct_chg': round(pct_chg, 2),
        'main_force_inflow': round(main_force, 0),
        'net_inflow': round(net_inflow, 0),
        'retail_flow': round(retail_flow, 0),
        'main_force_ratio': main_force_ratio,
        'capital_retention': capital_retention,
        'support_level': support,
        'win_rate_impact': round(pct_chg, 2),
    }


def update_lifecycle(target_date: str) -> Dict:
    """
    增量更新 target_date 当天所有 tracker 记录的 Day X
    Returns: {date, updated, skipped, finalized}
    """
    target_dt = datetime.strptime(target_date, '%Y%m%d')
    # 拉 30 天内的 active tracker, 覆盖 20 个交易日
    cutoff = (target_dt - timedelta(days=30)).strftime('%Y%m%d')

    updated, skipped, finalized = 0, 0, 0
    with get_db_session() as db:
        active = db.query(YuziLifecycleTracker).filter(
            YuziLifecycleTracker.trigger_date >= cutoff,
            YuziLifecycleTracker.trigger_date <= target_date,
        ).all()

        for tracker in active:
            trigger_dt = datetime.strptime(tracker.trigger_date, '%Y%m%d')
            # 按交易日算 day_diff: 跳过 trigger_dt..target_dt 之间的周末
            # 例: 6-25(周四)→6-29(周一), 日历差=5, 交易日差=3 (d3)
            day_diff = _trading_day_diff(trigger_dt, target_dt)
            if day_diff < 1 or day_diff > 20:
                skipped += 1
                continue

            day_key = f'd{day_diff}'

            # 解析已有 lifecycle_data
            try:
                lifecycle = json.loads(tracker.lifecycle_data or '{}')
            except (ValueError, TypeError):
                lifecycle = {}

            # 以实际数据是否存在为准，防御 day_filled 与实际数据不一致（如 trigger_d1 时 day_filled=1 但 lifecycle_data 为空）
            if day_key in lifecycle:
                skipped += 1
                continue

            # 算 D-1 的大佬净买(用于 capital_retention)
            d_prev = f'd{day_diff - 1}'
            yesterday_seat_net = None
            if d_prev in lifecycle and 'capital_retention' in lifecycle[d_prev]:
                # 上一日的席位净买我们没存,简化:从 yuzi_seat_daily 取
                prev_date = (target_dt - timedelta(days=1)).strftime('%Y%m%d')
                prev_seat = db.query(YuziSeatDaily).filter(
                    YuziSeatDaily.ts_code == tracker.ts_code,
                    YuziSeatDaily.trade_date == prev_date,
                ).all()
                if prev_seat:
                    yesterday_seat_net = sum(float(s.net_amount or 0) for s in prev_seat)

            metrics = _compute_day_metrics(tracker.ts_code, target_date, yesterday_seat_net)
            if not metrics:
                skipped += 1
                continue

            metrics['date'] = target_date  # YYYYMMDD, 前端表头展示用
            lifecycle[day_key] = metrics
            tracker.lifecycle_data = json.dumps(lifecycle, ensure_ascii=False)
            tracker.day_filled = max(tracker.day_filled or 1, day_diff)

            # Day 20 当天:算 final_outcome
            if day_diff >= 20:
                # 算 20d 最大可实现收益
                # = (Day 1 开盘 → Day 20 最高价) / Day 1 开盘
                # 取 20 天内的累计 pct_chg + 单日最大涨幅
                total_pct = 0.0
                for k in [f'd{i}' for i in range(1, 21)]:
                    if k in lifecycle:
                        total_pct += float(lifecycle[k].get('win_rate_impact', 0) or 0)
                # 取 20 天内的单日最大涨幅 + 累计(更接近实际可实现)
                max_single = max((float(lifecycle[k].get('win_rate_impact', 0) or 0) for k in lifecycle), default=0)
                net_return = round(max(max_single, total_pct), 2)

                # 结局分类(20d 阈值与 7d 不同:大妖/A 杀门槛放宽)
                if net_return >= 30:
                    outcome = '大妖股'
                elif net_return <= -20:
                    outcome = 'A杀退潮'
                elif 8 <= net_return < 30:
                    outcome = '高位震荡'
                elif -8 <= net_return < 8:
                    outcome = '横盘'
                else:  # -20 ~ -8
                    outcome = '弱势回调'
                tracker.final_outcome = outcome
                tracker.net_return_20d = net_return
                finalized += 1

            updated += 1
            time.sleep(0.15)  # Tushare 限流

        db.commit()

    logger.info(f'[update_lifecycle] {target_date} updated={updated} skipped={skipped} finalized={finalized}')
    return {'date': target_date, 'updated': updated, 'skipped': skipped, 'finalized': finalized}


def run_all(target_date: str) -> Dict:
    """一站式: D1 触发 + D2-D7 更新"""
    d1_n = trigger_d1(target_date)
    upd = update_lifecycle(target_date)
    return {'date': target_date, 'd1_inserted': d1_n, **upd}


def list_active_tasks(days_back: int = 30) -> List[dict]:
    """列出所有正在跟踪周期的任务(30 天窗口, 覆盖 20 个交易日)"""
    with get_db_session() as db:
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
        rows = db.query(YuziLifecycleTracker).filter(
            YuziLifecycleTracker.trigger_date >= cutoff,
        ).order_by(desc(YuziLifecycleTracker.trigger_date)).all()
        return [{
            'id': r.id,
            'trigger_date': r.trigger_date,
            'ts_code': r.ts_code,
            'stock_name': r.stock_name,
            'quant_score_d1': float(r.quant_score_d1 or 0),
            'day_filled': r.day_filled,
            'final_outcome': r.final_outcome,
            'net_return_20d': float(r.net_return_20d or 0),
        } for r in rows]


def backfill_history(start_date: str, end_date: str) -> List[dict]:
    """
    历史回填 D1（用于冷启动）：
    对区间内每一天,跑 trigger_d1 + update_lifecycle

    关键:每个 trigger_date 需要 20 个交易日的 update_lifecycle 跟进,
    才能把 D1-D20 全部填满.因此实际跑的范围需要扩展到 end_date + 25.
    """
    sd = datetime.strptime(start_date, '%Y%m%d')
    ed = datetime.strptime(end_date, '%Y%m%d')
    if sd > ed:
        sd, ed = ed, sd
    # 扩展到 end + 25 天,确保 end_date 当天触发的股也能填到 D20
    end_extended = ed + timedelta(days=25)

    # 先清空旧数据,避免重复
    with get_db_session() as db:
        deleted = db.query(YuziLifecycleTracker).filter(
            YuziLifecycleTracker.trigger_date >= start_date,
            YuziLifecycleTracker.trigger_date <= end_date,
        ).delete(synchronize_session=False)
        db.commit()
        logger.info(f'[backfill] 清空旧数据 {deleted} 条')

    results = []
    cur = sd
    while cur <= end_extended:
        d = cur.strftime('%Y%m%d')
        try:
            r = run_all(d)
            results.append(r)
        except Exception as e:
            logger.error(f'[{d}] backfill error: {e}', exc_info=True)
            results.append({'date': d, 'error': str(e)})
        cur += timedelta(days=1)
    return results


# ============================================================
# CLI
# ============================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='游资 7 天生命周期跟踪调度器')
    sub = parser.add_subparsers(dest='cmd')
    p1 = sub.add_parser('d1', help='触发 D1 记录')
    p1.add_argument('--date', required=True)
    p2 = sub.add_parser('update', help='更新 D2-D7 状态')
    p2.add_argument('--date', required=True)
    p3 = sub.add_parser('run', help='D1+Update 一条龙')
    p3.add_argument('--date', required=True)
    p4 = sub.add_parser('backfill', help='历史回填')
    p4.add_argument('--start', required=True)
    p4.add_argument('--end', required=True)
    p5 = sub.add_parser('list', help='列出活跃任务')
    p5.add_argument('--days', type=int, default=10)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    if args.cmd == 'd1':
        n = trigger_d1(args.date)
        print(f'插入 D1 触发: {n} 条')
    elif args.cmd == 'update':
        r = update_lifecycle(args.date)
        print(r)
    elif args.cmd == 'run':
        r = run_all(args.date)
        print(r)
    elif args.cmd == 'backfill':
        rs = backfill_history(args.start, args.end)
        for r in rs:
            print(r)
    elif args.cmd == 'list':
        tasks = list_active_tasks(args.days)
        for t in tasks:
            print(t)
    else:
        parser.print_help()
