"""
实时概念板块资金流向采集器
数据源：新浪财经(板块维度) + 个股多源聚合(交叉验证)
"""
import logging
from db.session import get_db_session
from db.models import RealtimeConceptSectorFlow, RealtimeStockFlow, ConceptSector
from collectors.realtime_sector_collector import _now_truncated
from collectors.concept_sector_collector import get_concept_sector_money_flow_realtime
from sqlalchemy import func

logger = logging.getLogger(__name__)


def _compute_concept_flows_from_stocks(db, snapshot_time, trade_date, concept_map):
    """
    基于 RealtimeStockFlow 计算 concept_sectors 表中所有有成分股的概念板块资金流向。
    用于多源聚合：所有概念（含新浪的）都从成分股多源个股数据聚合，再与新浪板块维度数值交叉验证。
    返回: {concept_name: {'net_flow': ..., 'money_inflow': ..., 'money_outflow': ..., 'rise_ratio': ..., 'covered': N}, ...}
    """
    # 对所有有成分股的概念计算（含 sina 来源）
    concepts = db.query(ConceptSector).all()
    if not concepts:
        return {}

    all_codes = set()
    concept_codes = {}
    for c in concepts:
        codes = [s.strip() for s in (c.stocks or '').split(',') if s.strip()]
        if codes:
            concept_codes[c.name] = codes
            all_codes.update(codes)

    if not all_codes:
        return {}

    # 取同一快照时间点的个股数据；若当前时间点无个股快照，回退到当日最新一次
    stocks = db.query(RealtimeStockFlow).filter(
        RealtimeStockFlow.snapshot_time == snapshot_time,
        RealtimeStockFlow.ts_code.in_(all_codes)
    ).all()
    if not stocks:
        latest_stock_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter(
            RealtimeStockFlow.trade_date == trade_date
        ).scalar()
        if latest_stock_time:
            stocks = db.query(RealtimeStockFlow).filter(
                RealtimeStockFlow.snapshot_time == latest_stock_time,
                RealtimeStockFlow.ts_code.in_(all_codes)
            ).all()
            if stocks:
                print(f'[realtime] fallback to latest stock snapshot {latest_stock_time} for computed concepts')
    stock_data = {s.ts_code: s for s in stocks}

    results = {}
    for name, codes in concept_codes.items():
        money_inflow = 0.0
        money_outflow = 0.0
        net_flow = 0.0
        total_chg = 0.0
        count = 0
        for code in codes:
            s = stock_data.get(code)
            if not s:
                continue
            mi = float(s.main_force_inflow or 0) if s.main_force_inflow is not None else 0.0
            # 异常值剔除：主力净流入为 None 或异常巨大时跳过
            if mi is None or abs(mi) > 1e10:
                continue
            money_inflow += max(mi, 0)
            money_outflow += max(-mi, 0)
            net_flow += mi
            total_chg += float(s.price_chg or 0)
            count += 1

        if count == 0:
            continue

        results[name] = {
            'net_flow': net_flow,
            'money_inflow': money_inflow,
            'money_outflow': money_outflow,
            'rise_ratio': total_chg / count,
            'covered': count,
            'total': len(codes),
        }

    if results:
        print(f'[realtime] Computed {len(results)} concept sectors from stocks (multi-source aggregated)')
    return results


def collect_realtime_concept_sector_flow(trade_date):
    """采集概念板块实时资金流向快照（新浪财经，板块维度）"""
    snapshot_time = _now_truncated()
    print(f'[realtime] Collecting concept sector flow snapshot at {snapshot_time}')

    flows = get_concept_sector_money_flow_realtime(pages=10, per_page=100)
    if not flows:
        print('[realtime] No concept sector flow data')
        return 0

    with get_db_session() as db:
        saved = 0
        try:
            concept_map = {c.name: c.id for c in db.query(ConceptSector).all()}
            new_concepts = []

            sina_values = {}
            for f in flows:
                name = f['sector']
                if f.get('net_flow') is not None:
                    sina_values[name] = {
                        'net_flow': f['net_flow'],
                        'money_inflow': f.get('money_inflow'),
                        'money_outflow': f.get('money_outflow'),
                        'rise_ratio': f.get('rise_ratio'),
                    }

            computed = _compute_concept_flows_from_stocks(db, snapshot_time, trade_date, concept_map)

            all_names = set(sina_values.keys()) | set(computed.keys())
            merged_count = 0
            for name in all_names:
                sina_val = sina_values.get(name)
                calc_val = computed.get(name)

                if sina_val and calc_val:
                    coverage = calc_val.get('covered', 0) / max(calc_val.get('total', 1), 1)
                    sina_net = abs(sina_val['net_flow'] or 0)
                    calc_net = abs(calc_val['net_flow'])
                    if coverage >= 0.3 and sina_net > 0 and abs(sina_net - calc_net) / max(sina_net, calc_net, 1) < 0.5:
                        final_net = (sina_val['net_flow'] + calc_val['net_flow']) / 2
                        source = 'merged'
                        merged_count += 1
                    else:
                        final_net = sina_val['net_flow']
                        source = 'sina'
                    final_rise = sina_val.get('rise_ratio') or calc_val['rise_ratio']
                elif sina_val:
                    final_net = sina_val['net_flow']
                    final_rise = sina_val['rise_ratio']
                    source = 'sina'
                else:
                    final_net = calc_val['net_flow']
                    final_rise = calc_val['rise_ratio']
                    source = 'computed'

                # 统一从 final_net 反推 inflow/outflow，保证 inflow-outflow=net_flow 恒等
                final_inflow = max(float(final_net or 0), 0)
                final_outflow = max(-float(final_net or 0), 0)

                cid = concept_map.get(name)
                if cid is None:
                    new_c = ConceptSector(name=name, source=source, stocks='')
                    db.add(new_c)
                    db.flush()
                    cid = new_c.id
                    concept_map[name] = cid
                    new_concepts.append(name)

                existing = db.query(RealtimeConceptSectorFlow).filter_by(
                    snapshot_time=snapshot_time, concept_name=name
                ).first()
                if existing:
                    existing.net_flow = final_net
                    existing.money_inflow = final_inflow
                    existing.money_outflow = final_outflow
                    existing.rise_ratio = final_rise
                    existing.source = source
                    existing.concept_sector_id = cid
                else:
                    db.add(RealtimeConceptSectorFlow(
                        snapshot_time=snapshot_time,
                        trade_date=trade_date,
                        concept_sector_id=cid,
                        concept_name=name,
                        net_flow=final_net,
                        money_inflow=final_inflow,
                        money_outflow=final_outflow,
                        rise_ratio=final_rise,
                        source=source,
                    ))
                saved += 1

            if merged_count:
                logger.info(f'[realtime] Multi-source merged: {merged_count} concepts (sina + computed avg)')
            db.commit()
            if new_concepts:
                logger.info(f'[realtime] Auto-created {len(new_concepts)} new concept sectors: {new_concepts[:10]}{"..." if len(new_concepts) > 10 else ""}')
            logger.info(f'[realtime] Saved {saved} concept sector snapshots')
        except Exception as e:
            db.rollback()
            logger.exception(f'[realtime] Concept sector save error')
    return saved
