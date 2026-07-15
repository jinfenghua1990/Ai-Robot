"""
个股 4 档资金流(特/大/小/散单)采集器
- 数据源:Tushare moneyflow 接口(主力=特大+大,散户=小+散)
- Tushare moneyflow 字段:
  - buy_elg_amount: 特大单买入
  - sell_elg_amount: 特大单卖出
  - buy_lg_amount: 大单买入
  - sell_lg_amount: 大单卖出
  - buy_md_amount: 中单买入
  - sell_md_amount: 中单卖出
  - buy_sm_amount: 小单买入
  - sell_sm_amount: 小单卖出
- 散单(tiny) = 净流入 - 特大单 - 大单 - 中单 - 小单
- 表:stock_money_flow_detail
"""
import logging
from datetime import datetime
from typing import Optional

from db.session import get_db_session
from db.models import StockMoneyFlowDetail

logger = logging.getLogger(__name__)


def _to_yuan(val) -> float:
    """Tushare moneyflow 单位是万元,转元"""
    try:
        return float(val or 0) * 10000
    except (TypeError, ValueError):
        return 0.0


def _net(buy, sell) -> float:
    """净流入 = 买入 - 卖出"""
    return _to_yuan(buy) - _to_yuan(sell)


def _safe_pct(part, total) -> float:
    if not total:
        return 0.0
    try:
        return round(float(part) / float(total) * 100, 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def fetch_moneyflow_for_date(trade_date: str) -> dict:
    """拉 Tushare 某日的全市场 moneyflow 流水,标准化后写库

    trade_date: YYYYMMDD 字符串
    返回:{'fetched': 整数, 'written': 整数, 'skipped': 整数}
    """
    from collectors.tdx_collector import call_tushare_mcp

    # 拉全市场 moneyflow 流水
    rows = call_tushare_mcp(
        'moneyflow',
        params={'trade_date': trade_date},
        fields=[
            'ts_code', 'trade_date',
            'buy_elg_amount', 'sell_elg_amount',
            'buy_lg_amount', 'sell_lg_amount',
            'buy_md_amount', 'sell_md_amount',
            'buy_sm_amount', 'sell_sm_amount',
            'net_mf_amount',  # 主力净流入
        ],
    )
    if not rows:
        logger.info(f'[moneyflow_detail] tushare returned empty for {trade_date}')
        return {'fetched': 0, 'written': 0, 'skipped': 0}

    # 拉流通市值(万元) + 换手率(算占流通市值比例)
    daily_rows = call_tushare_mcp(
        'daily_basic',
        params={'trade_date': trade_date},
        fields=['ts_code', 'turnover_rate', 'circ_mv'],  # circ_mv: 流通市值(万元)
    )
    turnover_map = {r['ts_code']: r.get('turnover_rate') for r in (daily_rows or [])}
    circ_mv_map = {r['ts_code']: r.get('circ_mv') for r in (daily_rows or [])}  # 万元

    written = 0
    skipped = 0
    trade_date_obj = datetime.strptime(trade_date, '%Y%m%d').date()

    with get_db_session() as db:
        for r in rows:
            ts_code = r.get('ts_code')
            if not ts_code:
                skipped += 1
                continue

            # 4 档净流入(元)
            super_large_net = _net(r.get('buy_elg_amount'), r.get('sell_elg_amount'))
            large_net = _net(r.get('buy_lg_amount'), r.get('sell_lg_amount'))
            medium_net = _net(r.get('buy_md_amount'), r.get('sell_md_amount'))
            small_net = _net(r.get('buy_sm_amount'), r.get('sell_sm_amount'))

            # 主力=特大+大
            main_net = super_large_net + large_net
            main_buy = _to_yuan(r.get('buy_elg_amount')) + _to_yuan(r.get('buy_lg_amount'))
            main_sell = _to_yuan(r.get('sell_elg_amount')) + _to_yuan(r.get('sell_lg_amount'))

            # 散户=中单+小单+散单(tiny)
            retail_buy = _to_yuan(r.get('buy_sm_amount')) + _to_yuan(r.get('buy_md_amount'))
            retail_sell = _to_yuan(r.get('sell_sm_amount')) + _to_yuan(r.get('sell_md_amount'))

            # 散单=主力+中单+小单 之和的负值(总净流入=0)
            # 总净流入 = 主力 + 中单 + 小单 + 散单 = 0
            # 所以 散单 = -(主力 + 中单 + 小单)
            tiny_net = -(main_net + medium_net + small_net)
            retail_net = medium_net + small_net + tiny_net  # 散户=中单+小单+散单

            # 占流通市值比例(%) = 净流入(元) / 流通市值(元) * 100
            # 净流入(元)/10000 = 净流入(万元)
            # 流通市值(万元)
            # 占比% = 净流入(万元) / 流通市值(万元) * 100
            circ_mv = circ_mv_map.get(ts_code)  # 万元
            super_large_pct = round(super_large_net / 10000 / circ_mv * 100, 3) if circ_mv and circ_mv > 0 else 0
            large_pct = round(large_net / 10000 / circ_mv * 100, 3) if circ_mv and circ_mv > 0 else 0
            small_pct = round(small_net / 10000 / circ_mv * 100, 3) if circ_mv and circ_mv > 0 else 0
            tiny_pct = round(tiny_net / 10000 / circ_mv * 100, 3) if circ_mv and circ_mv > 0 else 0

            turnover = float(turnover_map.get(ts_code) or 0)

            # upsert
            existing = db.query(StockMoneyFlowDetail).filter(
                StockMoneyFlowDetail.trade_date == trade_date_obj,
                StockMoneyFlowDetail.ts_code == ts_code,
            ).first()
            if existing:
                existing.super_large_net = super_large_net
                existing.large_net = large_net
                existing.medium_net = medium_net
                existing.small_net = small_net
                existing.tiny_net = tiny_net
                existing.main_net = main_net
                existing.main_buy = main_buy
                existing.main_sell = main_sell
                existing.retail_net = retail_net
                existing.retail_buy = retail_buy
                existing.retail_sell = retail_sell
                existing.super_large_pct = super_large_pct
                existing.large_pct = large_pct
                existing.small_pct = small_pct
                existing.tiny_pct = tiny_pct
                existing.turnover_rate = turnover
                existing.source = 'tushare'
            else:
                db.add(StockMoneyFlowDetail(
                    trade_date=trade_date_obj,
                    ts_code=ts_code,
                    super_large_net=super_large_net,
                    large_net=large_net,
                    medium_net=medium_net,
                    small_net=small_net,
                    tiny_net=tiny_net,
                    main_net=main_net,
                    main_buy=main_buy,
                    main_sell=main_sell,
                    retail_net=retail_net,
                    retail_buy=retail_buy,
                    retail_sell=retail_sell,
                    super_large_pct=super_large_pct,
                    large_pct=large_pct,
                    small_pct=small_pct,
                    tiny_pct=tiny_pct,
                    turnover_rate=turnover,
                    source='tushare',
                ))
            written += 1
        db.commit()

    return {'fetched': len(rows), 'written': written, 'skipped': skipped}


def backfill_moneyflow_detail(start_date: str, end_date: str) -> list:
    """批量回填区间内的所有交易日"""
    from datetime import timedelta
    from sqlalchemy import func as sqlfunc
    from db.models import StockMoneyFlowDetail

    start = datetime.strptime(start_date, '%Y%m%d').date()
    end = datetime.strptime(end_date, '%Y%m%d').date()
    results = []

    cur = start
    while cur <= end:
        # 跳过周末
        if cur.weekday() < 5:
            trade_date_str = cur.strftime('%Y%m%d')
            try:
                r = fetch_moneyflow_for_date(trade_date_str)
                results.append({'date': trade_date_str, **r})
            except Exception as e:
                logger.error(f'[moneyflow_detail] backfill {trade_date_str} error: {e}')
                results.append({'date': trade_date_str, 'error': str(e)})
        cur += timedelta(days=1)

    return results


def get_stock_moneyflow_detail(ts_code: str, trade_date: Optional[str] = None) -> Optional[dict]:
    """查询某只股票某日的 4 档资金流(无 trade_date 时取最新一日)

    返回 dict 含:
      - super_large/large/small/tiny: 4 档净流入(元)
      - main_net/main_buy/main_sell: 主力净流入/买入/卖出
      - retail_net/retail_buy/retail_sell: 散户
      - super_large_pct/large_pct/small_pct/tiny_pct: 占流通盘比例
      - turnover_rate: 换手率
      - 同步返回近 5 日数据
    """
    from db.models import StockMoneyFlowDetail
    from sqlalchemy import func as sqlfunc

    with get_db_session() as db:
        if trade_date:
            td = datetime.strptime(trade_date, '%Y%m%d').date()
            row = db.query(StockMoneyFlowDetail).filter(
                StockMoneyFlowDetail.trade_date == td,
                StockMoneyFlowDetail.ts_code == ts_code,
            ).first()
        else:
            row = db.query(StockMoneyFlowDetail).filter(
                StockMoneyFlowDetail.ts_code == ts_code
            ).order_by(StockMoneyFlowDetail.trade_date.desc()).first()

        if not row:
            return None

        # 当前数据
        current = _row_to_dict(row)

        # 近 5 日同档
        recent = db.query(StockMoneyFlowDetail).filter(
            StockMoneyFlowDetail.ts_code == ts_code,
            StockMoneyFlowDetail.trade_date <= row.trade_date,
        ).order_by(StockMoneyFlowDetail.trade_date.desc()).limit(5).all()
        recent_list = [_row_to_dict(r) for r in recent]

        return {
            'current': current,
            'recent_5d': recent_list,
        }


def _row_to_dict(row) -> dict:
    """DB Row → dict(单位:万元,保留 2 位小数)"""
    def y2w(v) -> float:
        """元 → 万元"""
        try:
            return round(float(v or 0) / 10000, 2)
        except (TypeError, ValueError):
            return 0.0
    return {
        'trade_date': row.trade_date.strftime('%Y%m%d') if row.trade_date else None,
        'ts_code': row.ts_code,
        # 4 档净流入(万元)
        'super_large': y2w(row.super_large_net),
        'large': y2w(row.large_net),
        'medium': y2w(row.medium_net),
        'small': y2w(row.small_net),
        'tiny': y2w(row.tiny_net),
        # 主力/散户(万元)
        'main_net': y2w(row.main_net),
        'main_buy': y2w(row.main_buy),
        'main_sell': y2w(row.main_sell),
        'retail_net': y2w(row.retail_net),
        'retail_buy': y2w(row.retail_buy),
        'retail_sell': y2w(row.retail_sell),
        # 占比(% 占流通盘)
        'super_large_pct': float(row.super_large_pct or 0),
        'large_pct': float(row.large_pct or 0),
        'small_pct': float(row.small_pct or 0),
        'tiny_pct': float(row.tiny_pct or 0),
        'turnover_rate': float(row.turnover_rate or 0),
        'source': row.source,
    }
