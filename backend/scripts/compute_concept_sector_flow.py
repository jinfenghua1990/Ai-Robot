"""
根据 concept_sectors 成分股和 stock_flow 表，计算概念板块日度资金流向。
"""
import os
import sys
from datetime import datetime, date
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_db, engine, Base
from db.session import get_db_session
from db.models import ConceptSector, ConceptSectorFlow, StockFlow
from sqlalchemy import func


def _resolve_trade_date(db, target_date):
    """若 target_date 无数据，向前查找最近交易日"""
    latest = db.query(func.max(StockFlow.trade_date)).filter(
        StockFlow.trade_date <= target_date
    ).scalar()
    return latest


def compute_for_date(target_date=None):
    with get_db_session() as db:
        Base.metadata.create_all(bind=engine, tables=[ConceptSectorFlow.__table__])

        if target_date is None:
            target_date = date.today()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

        trade_date = _resolve_trade_date(db, target_date)
        if not trade_date:
            print(f'[compute_concept_sector_flow] no stock_flow data for {target_date}')
            return

        concepts = db.query(ConceptSector).all()
        if not concepts:
            print('[compute_concept_sector_flow] no concept sectors found')
            return

        # 获取所有相关股票的 stock_flow 数据
        all_codes = set()
        concept_map = {}
        for c in concepts:
            codes = [s.strip() for s in (c.stocks or '').split(',') if s.strip()]
            concept_map[c.id] = {'id': c.id, 'name': c.name, 'codes': codes}
            all_codes.update(codes)

        stocks = db.query(StockFlow).filter(
            StockFlow.trade_date == trade_date,
            StockFlow.ts_code.in_(all_codes)
        ).all()

        # 按 ts_code 聚合（同一股票不应重复，但保险起见取第一条）
        stock_data = {}
        for s in stocks:
            if s.ts_code not in stock_data:
                stock_data[s.ts_code] = s

        # 计算每个概念板块
        for c in concept_map.values():
            money_inflow = 0.0
            money_outflow = 0.0
            net_flow = 0.0
            total_chg = 0.0
            count = 0
            limit_up = 0
            valid_stocks = []

            for code in c['codes']:
                s = stock_data.get(code)
                if not s:
                    continue
                mi = float(s.net_inflow or 0) if s.net_inflow is not None else 0.0
                # stock_flow 只有 net_inflow，没有单独的流入流出；用 net_inflow 近似
                # 这里用 net_inflow 作为净流入，流入流出需要额外计算，暂用 net_inflow 正负拆分
                money_inflow += max(mi, 0)
                money_outflow += max(-mi, 0)
                net_flow += mi
                chg = float(s.price_chg or 0)
                total_chg += chg
                count += 1
                if chg >= 9.5:
                    limit_up += 1
                valid_stocks.append(chg)

            if count == 0:
                # 即使没有成分股数据，也写入0值记录，保证板块覆盖与实时一致
                existing = db.query(ConceptSectorFlow).filter_by(
                    trade_date=trade_date, concept_sector_id=c['id']
                ).first()
                if existing:
                    existing.money_inflow = 0
                    existing.money_outflow = 0
                    existing.net_flow = 0
                    existing.rise_ratio = 0
                    existing.avg_chg = 0
                    existing.limit_up_count = 0
                    existing.heat_score = 0
                else:
                    db.add(ConceptSectorFlow(
                        trade_date=trade_date,
                        concept_sector_id=c['id'],
                        concept_name=c['name'],
                        money_inflow=0,
                        money_outflow=0,
                        net_flow=0,
                        rise_ratio=0,
                        avg_chg=0,
                        limit_up_count=0,
                        heat_score=0,
                    ))
                continue

            avg_chg = total_chg / count
            rise_ratio = avg_chg
            # 热度分：综合涨幅、涨停数、净流入（简化版）
            heat_score = min(100, max(0, 50 + rise_ratio * 2 + limit_up * 3 + (net_flow / 100000)))

            existing = db.query(ConceptSectorFlow).filter_by(
                trade_date=trade_date, concept_sector_id=c['id']
            ).first()
            if existing:
                existing.money_inflow = money_inflow
                existing.money_outflow = money_outflow
                existing.net_flow = net_flow
                existing.rise_ratio = rise_ratio
                existing.avg_chg = avg_chg
                existing.limit_up_count = limit_up
                existing.heat_score = heat_score
            else:
                db.add(ConceptSectorFlow(
                    trade_date=trade_date,
                    concept_sector_id=c['id'],
                    concept_name=c['name'],
                    money_inflow=money_inflow,
                    money_outflow=money_outflow,
                    net_flow=net_flow,
                    rise_ratio=rise_ratio,
                    avg_chg=avg_chg,
                    limit_up_count=limit_up,
                    heat_score=heat_score,
                ))
        db.commit()
        print(f'[compute_concept_sector_flow] computed {len(concept_map)} concepts for {trade_date}')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=None, help='YYYY-MM-DD，默认今天')
    args = parser.parse_args()
    compute_for_date(args.date)
