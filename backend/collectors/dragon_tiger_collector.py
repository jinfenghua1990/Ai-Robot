"""
游资龙虎榜采集器（Tushare top_list / top_inst）

核心流程（Day 1 盘后清洗 → Day 2 观察池）:
1) top_list(trade_date)        当日龙虎榜上榜股（含 reason / net_amount / turnover_rate）
2) top_inst(trade_date)        上榜股的营业部明细（含 ex_name / side / buy / sell）
3) 用 yuzi_dict 做 ex_name → yuzi_alias 匹配
4) 按 ts_code 聚合：总净买 / 共振大佬数 / boss_list / seat_detail
5) 量化评分（基础 60 + 共振加成 + 资金规模加成 + 涨停/换手修正）
6) 写 yuzi_seat_daily（明细）+ yuzi_quant_signals（汇总）
7) 前端 /yuzi-billboard 直接读

历史回填：backfill_yuzi(start_date, end_date) 逐日跑
盘后调度：run_today() 跑最新一日（无新数据则跳过）
"""
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

from sqlalchemy import func
from db.connection import engine
from db.session import get_db_session
from db.models import YuziDict, YuziQuantSignal, YuziSeatDaily

logger = logging.getLogger(__name__)

# === 评分参数（保持与 quant_engine.py 风格一致，可后续调）===
SCORE_BASE = 60.0
SCORE_PER_RESONANCE = 8.0          # 每多 1 家大佬共振 +8 分
SCORE_PER_1000W_NETBUY = 1.5       # 每 1000 万净买入 +1.5 分
SCORE_NETBUY_CAP = 25.0            # 资金规模加成上限 25 分
SCORE_LIMIT_UP_BONUS = 5.0         # 涨停额外 +5 分
SCORE_HIGH_TURN_PENALTY = -3.0     # 换手 > 30% 减 3 分（防短线出货）
SCORE_TURNOVER_THRESHOLD = 30.0


def _tushare_top_list(trade_date: str) -> List[dict]:
    """调 Tushare HTTP API 拉 top_list"""
    from collectors.tdx_collector import call_tushare_mcp
    rows = call_tushare_mcp(
        api_name='top_list',
        params={'trade_date': trade_date},
        fields=['ts_code', 'name', 'trade_date', 'close', 'pct_change',
                'turnover_rate', 'amount', 'l_sell', 'l_buy', 'l_amount',
                'net_amount', 'net_rate', 'amount_rate', 'float_values',
                'reason', 'reason_type'],
    )
    if not rows:
        return []
    # 字段名兼容
    for r in rows:
        r['pct_change'] = r.get('pct_change') or r.get('pct_chg') or 0
        r['turnover_rate'] = r.get('turnover_rate') or 0
        r['amount'] = r.get('amount') or 0
        r['net_amount'] = r.get('net_amount') or 0
        r['l_buy'] = r.get('l_buy') or 0
        r['l_sell'] = r.get('l_sell') or 0
    return rows


def _tushare_top_inst(trade_date: str) -> List[dict]:
    """调 Tushare HTTP API 拉 top_inst（营业部明细）"""
    from collectors.tdx_collector import call_tushare_mcp
    rows = call_tushare_mcp(
        api_name='top_inst',
        params={'trade_date': trade_date},
        fields=['ts_code', 'exalter', 'side', 'buy', 'sell', 'net_buy',
                'reason', 'net_rate', 'amount', 'branch', 'net_amount'],
    )
    if not rows:
        return []
    # 字段名兼容
    for r in rows:
        r['buy'] = r.get('buy') or 0
        r['sell'] = r.get('sell') or 0
        r['net_buy'] = r.get('net_buy') or 0
        r['ex_name'] = r.get('exalter') or r.get('branch') or ''
    return rows


def _get_yuzi_mapping(db) -> Dict[str, YuziDict]:
    """从 yuzi_dict 读 seat_name → YuziDict 字典"""
    rows = db.query(YuziDict).filter(YuziDict.is_active == True).all()  # noqa
    return {r.seat_name: r for r in rows}


def _score_signal(resonance_count: int, total_net_buy: float,
                  limit_up: bool, turnover_rate: float) -> Tuple[float, dict]:
    """量化评分（0-100）"""
    score = SCORE_BASE
    factors = {'base': SCORE_BASE}

    # 共振加成
    if resonance_count > 1:
        s = (resonance_count - 1) * SCORE_PER_RESONANCE
        score += s
        factors['resonance'] = s

    # 资金规模加成（每 1000 万 +1.5，封顶 25）
    if total_net_buy > 0:
        s = min(int(total_net_buy / 1000) * SCORE_PER_1000W_NETBUY, SCORE_NETBUY_CAP)
        score += s
        factors['capital'] = round(s, 2)

    # 涨停加成
    if limit_up:
        score += SCORE_LIMIT_UP_BONUS
        factors['limit_up'] = SCORE_LIMIT_UP_BONUS

    # 高换手惩罚
    if turnover_rate and turnover_rate > SCORE_TURNOVER_THRESHOLD:
        score += SCORE_HIGH_TURN_PENALTY
        factors['turnover_penalty'] = SCORE_HIGH_TURN_PENALTY

    score = max(0, min(100, score))
    return round(score, 2), factors


def _process_one_day(trade_date: str) -> Dict:
    """
    处理单日：拉 Tushare → 匹配 → 评分 → 写库
    返回 {'date','top_list_count','top_inst_count','seat_matched','signals_written'}
    """
    logger.info(f'[{trade_date}] start processing yuzi dragon-tiger...')

    # 1) 拉原始数据
    top_list = _tushare_top_list(trade_date)
    if not top_list:
        logger.info(f'[{trade_date}] no top_list, skip')
        return {'date': trade_date, 'top_list': 0, 'top_inst': 0,
                'matched': 0, 'signals': 0, 'seats': 0}

    top_inst = _tushare_top_inst(trade_date)
    if not top_inst:
        logger.info(f'[{trade_date}] no top_inst, skip')
        return {'date': trade_date, 'top_list': len(top_list), 'top_inst': 0,
                'matched': 0, 'signals': 0, 'seats': 0}

    # 2) 整理 top_list 上下文
    tl_map = {r['ts_code']: r for r in top_list if r.get('ts_code')}

    with get_db_session() as db:
        yuzi_map = _get_yuzi_mapping(db)
        if not yuzi_map:
            logger.warning(f'[{trade_date}] yuzi_dict empty, run seed first')
            return {'date': trade_date, 'top_list': len(top_list), 'top_inst': len(top_inst),
                    'matched': 0, 'signals': 0, 'seats': 0}

        # 3) 匹配游资席位 → 按 ts_code 聚合
        matched_rows: List[dict] = []
        unmatched_seats = set()
        for inst in top_inst:
            ex_name = inst.get('ex_name', '') or ''
            yd = yuzi_map.get(ex_name)
            if not yd:
                unmatched_seats.add(ex_name)
                continue
            inst['yuzi_alias'] = yd.yuzi_alias
            inst['yuzi_group'] = yd.yuzi_group
            inst['yuzi_hot_score'] = yd.hot_score
            matched_rows.append(inst)

        logger.info(f'[{trade_date}] matched {len(matched_rows)}/{len(top_inst)} seats, '
                    f'{len(unmatched_seats)} unmatched')

        if not matched_rows:
            return {'date': trade_date, 'top_list': len(top_list), 'top_inst': len(top_inst),
                    'matched': 0, 'signals': 0, 'seats': 0}

        # 4) 写 yuzi_seat_daily（先清后写，幂等）
        db.query(YuziSeatDaily).filter(YuziSeatDaily.trade_date == trade_date).delete()
        # 同 (date, seat, code) 可能有多笔成交（买入+卖出/分多次），合并成一条
        seat_merge = {}
        for inst in matched_rows:
            key = (inst.get('ex_name', ''), inst.get('ts_code', ''))
            if key not in seat_merge:
                seat_merge[key] = {
                    'seat_name': inst.get('ex_name', ''),
                    'yuzi_alias': inst.get('yuzi_alias', ''),
                    'ts_code': inst.get('ts_code', ''),
                    'stock_name': (tl_map.get(inst.get('ts_code', ''), {}) or {}).get('name', ''),
                    'buy': 0.0, 'sell': 0.0, 'net': 0.0,
                    'net_ratio': float(inst.get('net_rate', 0)) or 0,
                    'turnover_rate': float((tl_map.get(inst.get('ts_code', ''), {}) or {}).get('turnover_rate', 0)) or 0,
                    'amount': float((tl_map.get(inst.get('ts_code', ''), {}) or {}).get('amount', 0)) or 0,
                    'reason': (tl_map.get(inst.get('ts_code', ''), {}) or {}).get('reason', ''),
                }
            m = seat_merge[key]
            m['buy'] += float(inst.get('buy', 0)) / 10000.0
            m['sell'] += float(inst.get('sell', 0)) / 10000.0
            m['net'] += float(inst.get('net_buy', 0)) / 10000.0
        for m in seat_merge.values():
            db.add(YuziSeatDaily(
                trade_date=trade_date,
                seat_name=m['seat_name'],
                yuzi_alias=m['yuzi_alias'],
                ts_code=m['ts_code'],
                stock_name=m['stock_name'],
                side='BUY' if m['net'] > 0 else ('SELL' if m['net'] < 0 else 'FLAT'),
                buy_amount=round(m['buy'], 2),
                sell_amount=round(m['sell'], 2),
                net_amount=round(m['net'], 2),
                net_ratio=m['net_ratio'],
                turnover_rate=m['turnover_rate'],
                amount=m['amount'],
                list_reason=m['reason'],
            ))

        # 5) 按 ts_code 聚合 → 写 yuzi_quant_signals
        from collections import defaultdict
        agg: Dict[str, dict] = defaultdict(lambda: {
            'total_buy': 0.0, 'total_sell': 0.0, 'total_net': 0.0,
            'bosses': [], 'seat_detail': [],
        })

        for inst in matched_rows:
            code = inst.get('ts_code', '')
            if not code:
                continue
            alias = inst.get('yuzi_alias', '')
            if alias not in agg[code]['bosses']:
                agg[code]['bosses'].append(alias)
            agg[code]['total_buy'] += float(inst.get('buy', 0)) / 10000.0
            agg[code]['total_sell'] += float(inst.get('sell', 0)) / 10000.0
            agg[code]['total_net'] += float(inst.get('net_buy', 0)) / 10000.0
            agg[code]['seat_detail'].append({
                'alias': alias,
                'side': 'BUY' if inst.get('net_buy', 0) > 0 else 'SELL',
                'net_buy': round(float(inst.get('net_buy', 0)) / 10000.0, 2),
                'buy': round(float(inst.get('buy', 0)) / 10000.0, 2),
                'sell': round(float(inst.get('sell', 0)) / 10000.0, 2),
            })

        # 清空当天旧信号
        db.query(YuziQuantSignal).filter(YuziQuantSignal.trade_date == trade_date).delete()
        signals_written = 0
        for ts_code, item in agg.items():
            tl = tl_map.get(ts_code, {}) or {}
            net_buy = item['total_net']
            # 只写净买入的（净卖出跳过，量化池只关注"买"）
            if net_buy <= 0:
                continue

            resonance = len(item['bosses'])
            limit_up = (float(tl.get('pct_change', 0) or 0) >= 9.5)
            turnover = float(tl.get('turnover_rate', 0) or 0)
            score, factors = _score_signal(resonance, net_buy, limit_up, turnover)

            sig = YuziQuantSignal(
                trade_date=trade_date,
                ts_code=ts_code,
                stock_name=tl.get('name', ''),
                sector=tl.get('industry', ''),  # top_list 没 industry，运行时留空
                total_net_buy=round(net_buy, 2),
                total_buy=round(item['total_buy'], 2),
                total_sell=round(item['total_sell'], 2),
                resonance_count=resonance,
                boss_list=','.join(item['bosses']),
                seat_detail=json.dumps(item['seat_detail'], ensure_ascii=False),
                quant_score=score,
                score_factors=json.dumps(factors, ensure_ascii=False),
                change_pct=float(tl.get('pct_change', 0) or 0),
                close_price=float(tl.get('close', 0) or 0),
                turnover_rate=turnover,
                limit_up_flag=limit_up,
                amount=float(tl.get('amount', 0) or 0),
                list_reason=tl.get('reason', ''),
                list_tag=tl.get('reason_type', ''),
            )
            db.add(sig)
            signals_written += 1

        db.commit()
        logger.info(f'[{trade_date}] done. {signals_written} signals, '
                    f'{len(matched_rows)} seat rows, {len(unmatched_seats)} unmatched seats')

    return {
        'date': trade_date,
        'top_list': len(top_list),
        'top_inst': len(top_inst),
        'matched': len(matched_rows),
        'signals': signals_written,
        'seats': len(matched_rows),
        'unmatched_count': len(unmatched_seats),
        'unmatched_sample': list(unmatched_seats)[:30],
    }


def run_today(force_date: Optional[str] = None) -> Dict:
    """
    跑最新一日的龙虎榜清洗
    force_date: 强制跑指定日期（YYYYMMDD）
    """
    target = force_date
    if not target:
        # 默认取最近一个交易日（Tushare 通常 18:00 后才出当日数据）
        from collectors.tdx_collector import call_tushare_mcp
        rows = call_tushare_mcp(
            api_name='top_list',
            params={},
            fields=['trade_date'],
        )
        if rows:
            target = max(r.get('trade_date', '') for r in rows if r.get('trade_date'))
        else:
            # 退到上一个工作日
            target = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

    return _process_one_day(target)


def backfill_yuzi(start_date: str, end_date: str) -> List[Dict]:
    """
    历史回填：start_date/end_date 均为 YYYYMMDD 字符串
    逐日跑，跳过已成功的日期
    """
    from datetime import datetime as _dt
    sd = _dt.strptime(start_date, '%Y%m%d')
    ed = _dt.strptime(end_date, '%Y%m%d')
    if sd > ed:
        sd, ed = ed, sd

    results = []
    cur = sd
    while cur <= ed:
        d = cur.strftime('%Y%m%d')
        try:
            r = _process_one_day(d)
            results.append(r)
            time.sleep(0.6)  # 避免 Tushare 限流
        except Exception as e:
            logger.error(f'[{d}] backfill error: {e}', exc_info=True)
            results.append({'date': d, 'error': str(e)})
        cur += timedelta(days=1)
    return results


def latest_yuzi_date() -> Optional[str]:
    """返回 DB 里最新的 yuzi_quant_signals.trade_date"""
    with get_db_session() as db:
        row = db.query(YuziQuantSignal.trade_date, func.max(YuziQuantSignal.trade_date)).first()
        if row and row[0]:
            return row[0]
        return None
