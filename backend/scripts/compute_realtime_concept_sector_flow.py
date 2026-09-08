"""
根据 concept_sectors 成分股和 realtime_stock_flow 表，计算概念板块实时资金流向快照。
"""
import os
import sys
from datetime import datetime, date
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_db, engine, Base
from db.session import get_db_session
from db.models import ConceptSector, RealtimeConceptSectorFlow, RealtimeStockFlow
from sqlalchemy import func


def compute_for_snapshot(snapshot_time=None, trade_date=None):
    with get_db_session() as db:
        Base.metadata.create_all(bind=engine, tables=[RealtimeConceptSectorFlow.__table__])

        if snapshot_time is None:
            # 取最新一次快照时间
            snapshot_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).scalar()
        if not snapshot_time:
            print('[compute_realtime_concept_sector_flow] no realtime stock snapshot found')
            return

        if trade_date is None:
            trade_date = snapshot_time.date()

        concepts = db.query(ConceptSector).all()
        if not concepts:
            print('[compute_realtime_concept_sector_flow] no concept sectors found')
            return

        all_codes = set()
        concept_map = {}
        for c in concepts:
            codes = [s.strip() for s in (c.stocks or '').split(',') if s.strip()]
            concept_map[c.id] = {'id': c.id, 'name': c.name, 'codes': codes}
            all_codes.update(codes)

        stocks = db.query(RealtimeStockFlow).filter(
            RealtimeStockFlow.snapshot_time == snapshot_time,
            RealtimeStockFlow.ts_code.in_(all_codes)
        ).all()

        stock_data = {}
        for s in stocks:
            if s.ts_code not in stock_data:
                stock_data[s.ts_code] = s

        for c in concept_map.values():
            money_inflow = 0.0
            money_outflow = 0.0
            net_flow = 0.0
            total_chg = 0.0
            count = 0

            for code in c['codes']:
                s = stock_data.get(code)
                if not s:
                    continue
                mi = float(s.main_force_inflow or 0) if s.main_force_inflow is not None else 0.0
                money_inflow += max(mi, 0)
                money_outflow += max(-mi, 0)
                net_flow += mi
                chg = float(s.price_chg or 0)
                total_chg += chg
                count += 1

            if count == 0:
                continue

            rise_ratio = total_chg / count

            existing = db.query(RealtimeConceptSectorFlow).filter_by(
                snapshot_time=snapshot_time, concept_sector_id=c['id']
            ).first()
            if existing:
                existing.money_inflow = money_inflow
                existing.money_outflow = money_outflow
                existing.net_flow = net_flow
                existing.rise_ratio = rise_ratio
                existing.trade_date = trade_date
            else:
                db.add(RealtimeConceptSectorFlow(
                    snapshot_time=snapshot_time,
                    trade_date=trade_date,
                    concept_sector_id=c['id'],
                    concept_name=c['name'],
                    money_inflow=money_inflow,
                    money_outflow=money_outflow,
                    net_flow=net_flow,
                    rise_ratio=rise_ratio,
                ))
        db.commit()
        print(f'[compute_realtime_concept_sector_flow] computed {len(concept_map)} concepts for {snapshot_time}')


if __name__ == '__main__':
    compute_for_snapshot()
