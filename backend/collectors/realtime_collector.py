"""
实时数据采集器
盘中每15分钟采集一次，写入 realtime_sector_flow / realtime_stock_flow 表
多源采集 + 交叉验证 + 质量评分
数据源优先级（额度优化版）：
  - 板块资金流向：新浪(主) → 东方财富(降级)
  - 个股资金流向：东方财富datacenter(全市场批量,1次API) → 东财push2+新浪(Top20验证) → 国信证券(Top10验证)
  - 实时价格：腾讯财经(主,Top50) → 通达信(验证,Top20) → 东方财富(已含)
  ※ 东方财富datacenter和国信证券有额度限制，尽量少用
  ※ 通达信(TCP)和新浪(无限制)可多用
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
from datetime import datetime
from db.connection import get_db
from db.session import get_db_session
from db.models import RealtimeSectorFlow, RealtimeStockFlow, StockFlow
from collectors.tdx_collector import get_sector_money_flow, get_stock_money_flow
from collectors.concept_sector_collector import get_concept_sector_money_flow_realtime
from collectors.guosen_collector import (
    GUOSEN_AVAILABLE, guosen_batch_realtime_quotes, guosen_single_fund_flow
)
from collectors.astock_collector import (
    batch_realtime_quotes, eastmoney_fund_flow_daily,
    sina_stock_fund_flow, tdx_realtime_price
)
from collectors.akshare_collector import akshare_batch_prices, akshare_single_fund_flow
from analyzers.cross_validator import cross_validate, detect_anomalies

logger = logging.getLogger(__name__)


def _now_truncated():
    """当前时间截断到分钟（秒数归零）"""
    return datetime.now().replace(second=0, microsecond=0)


def collect_realtime_sector_flow(trade_date):
    """
    采集板块实时资金流向快照
    数据源：新浪(主) → 东方财富(降级)
    """
    snapshot_time = _now_truncated()
    print(f'[realtime] Collecting sector flow snapshot at {snapshot_time}')

    # 复用现有采集函数（新浪→东方财富→Tushare）
    sector_flows = get_sector_money_flow(trade_date)
    if not sector_flows:
        print('[realtime] No sector flow data')
        return 0

    # 判断数据源
    source = 'sina'  # get_sector_money_flow 优先用新浪
    # 简单判断：如果板块数<40 可能是东方财富或Tushare
    if len(sector_flows) < 40:
        source = 'em'

    with get_db_session() as db:
        saved = 0
        try:
            for sf in sector_flows:
                record = RealtimeSectorFlow(
                    snapshot_time=snapshot_time,
                    trade_date=trade_date,
                    sector=sf['sector'],
                    money_inflow=sf.get('money_inflow'),
                    money_outflow=sf.get('money_outflow'),
                    net_flow=sf.get('net_flow'),
                    rise_ratio=sf.get('rise_ratio'),
                    source=source,
                )
                db.add(record)
                saved += 1
            db.commit()
            logger.info(f'[realtime] Saved {saved} sector snapshots (source={source})')
        except Exception as e:
            db.rollback()
            logger.warning(f'[realtime] Sector save error: {e}')
    return saved


def collect_realtime_stock_flow(trade_date):
    """
    采集个股实时资金流向快照（多源+交叉验证）
    额度优化策略：
    - 东方财富datacenter：全市场批量（1次API，有额度限制但批量高效）
    - 东财push2 + 新浪财经：Top20资金流向验证（无额度限制）
    - 国信证券：Top10资金流向验证（有额度限制，减少使用）
    - 腾讯财经：Top50价格验证（无额度限制）
    - 通达信：Top20价格验证（TCP协议，无额度限制）
    """
    snapshot_time = _now_truncated()
    print(f'[realtime] Collecting stock flow snapshot at {snapshot_time}')

    # 东方财富全市场个股资金流向（主源，1次批量API）
    stock_flows = get_stock_money_flow(trade_date)
    if not stock_flows:
        print('[realtime] No stock flow data')
        return 0

    # 按主力净流入绝对值排序，取Top进行多源验证
    sorted_flows = sorted(stock_flows, key=lambda x: abs(x.get('main_force_inflow', 0) or 0), reverse=True)
    top50_for_price = sorted_flows[:50]  # 价格验证Top50
    top20_for_flow = sorted_flows[:20]   # 资金流向验证Top20
    top10_for_guosen = sorted_flows[:10] # 国信证券验证Top10（减少额度消耗）

    # === 多源采集验证数据（数据源配置 + 统一循环，代替 12 组重复 try/except） ===
    import importlib
    _PRICE_COLLECTORS = [
        ('tencent',       top50_for_price, 'collectors.astock_collector',    'batch_realtime_quotes'),
        ('tdx',           top20_for_flow,  'collectors.astock_collector',    'tdx_realtime_price'),
        ('akshare',       top50_for_price, 'collectors.akshare_collector',   'akshare_batch_prices'),
        ('efinance',      top20_for_flow,  'collectors.extended_collectors', 'efinance_batch_quotes'),
        ('adata',         top20_for_flow,  'collectors.extended_collectors', 'adata_batch_quotes'),
        ('sina_quote',    top50_for_price, 'collectors.extended_collectors', 'sina_quote_batch'),
        ('tencent_kline', top20_for_flow,  'collectors.extended_collectors', 'tencent_kline_batch'),
        ('baostock',      top20_for_flow,  'collectors.extended_collectors', 'baostock_batch_quotes'),
        ('itick',         top20_for_flow,  'collectors.extended_collectors', 'itick_batch_quotes'),
        ('jqdata',        top20_for_flow,  'collectors.extended_collectors', 'jqdata_batch_quotes'),
        ('mootdx',        top20_for_flow,  'collectors.extended_collectors', 'mootdx_batch_quotes'),
        ('qstock',        top20_for_flow,  'collectors.extended_collectors', 'qstock_batch_quotes'),
    ]

    price_results = {}
    for name, codes_list, mod_path, func_name in _PRICE_COLLECTORS:
        result = {}
        ts_codes = [s['ts_code'] for s in codes_list]
        try:
            mod = importlib.import_module(mod_path)
            func = getattr(mod, func_name)
            result = func(ts_codes)
            print(f'[realtime] {name} prices: {len(result)} stocks')
        except Exception as e:
            print(f'[realtime] {name} price error: {e}')
        price_results[name] = result

    tencent_prices       = price_results['tencent']
    tdx_prices           = price_results['tdx']
    akshare_prices       = price_results['akshare']
    efinance_prices      = price_results['efinance']
    adata_prices         = price_results['adata']
    sina_quote_prices    = price_results['sina_quote']
    tencent_kline_prices = price_results['tencent_kline']
    baostock_prices      = price_results['baostock']
    itick_prices         = price_results['itick']
    jqdata_prices        = price_results['jqdata']
    mootdx_prices        = price_results['mootdx']
    qstock_prices        = price_results['qstock']

    # 3. 东财push2资金流向（Top20，无额度限制）
    em_push2_flows = {}
    for s in top20_for_flow:
        code = s['ts_code'].replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        try:
            r = eastmoney_fund_flow_daily(code)
            if r:
                em_push2_flows[s['ts_code']] = r
        except Exception:
            logger.debug('handled exception', exc_info=True)
    print(f'[realtime] EM push2 flows: {len(em_push2_flows)} stocks')

    # 4. 新浪财经资金流向（Top20，无额度限制）
    sina_flows = {}
    for s in top20_for_flow:
        code = s['ts_code'].replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        try:
            r = sina_stock_fund_flow(code)
            if r:
                sina_flows[s['ts_code']] = r
        except Exception:
            logger.debug('handled exception', exc_info=True)
    print(f'[realtime] Sina flows: {len(sina_flows)} stocks')

    # 5. 国信证券资金流向（Top10，有额度限制，减少使用）
    guosen_flows = {}
    if GUOSEN_AVAILABLE and top10_for_guosen:
        for s in top10_for_guosen:
            try:
                r = guosen_single_fund_flow(s['ts_code'], period=1)
                if r:
                    guosen_flows[s['ts_code']] = r
            except Exception:
                logger.debug('handled exception', exc_info=True)
        print(f'[realtime] Guosen flows: {len(guosen_flows)} stocks (Top10 only)')

    # 6. 同花顺资金流向排名（Top20，批量，降级容错）
    ths_flows = {}
    try:
        from collectors.extended_collectors import ths_fund_flow_rank
        ths_all = ths_fund_flow_rank()
        if ths_all:
            for s in top20_for_flow:
                if s['ts_code'] in ths_all:
                    ths_flows[s['ts_code']] = ths_all[s['ts_code']]
        print(f'[realtime] THS flows: {len(ths_flows)} stocks')
    except Exception as e:
        print(f'[realtime] THS flow error: {e}')

    # 7. 聚宽资金流向（Top20，高质量大单统计）
    jqdata_flows = {}
    if top20_for_flow:
        for s in top20_for_flow:
            try:
                from collectors.extended_collectors import jqdata_fund_flow
                r = jqdata_fund_flow(s['ts_code'])
                if r:
                    jqdata_flows[s['ts_code']] = r
            except Exception:
                logger.debug('handled exception', exc_info=True)
        print(f'[realtime] jqdata flows: {len(jqdata_flows)} stocks')

    # === 写入数据库（带交叉验证） ===
    with get_db_session() as db:
        saved = 0
        validated = 0
        try:
            for sf in stock_flows:
                ts_code = sf['ts_code']
                name = sf.get('name')
                main_flow = sf.get('main_force_inflow')
                price = sf.get('price')
                price_chg = sf.get('price_chg')

                # === 交叉验证：主力净流入 ===
                flow_sources = {'eastmoney': {'value': main_flow}}
                if ts_code in em_push2_flows:
                    push2_main = em_push2_flows[ts_code].get('main_net', 0)
                    flow_sources['em_push2'] = {'value': push2_main / 10000 if push2_main else None}
                if ts_code in sina_flows:
                    sina_main = sina_flows[ts_code].get('main_net', 0)
                    flow_sources['sina'] = {'value': sina_main / 10000 if sina_main else None}
                if ts_code in guosen_flows:
                    flow_sources['guosen'] = {'value': guosen_flows[ts_code].get('main_force_inflow')}
                if ts_code in ths_flows:
                    flow_sources['ths'] = {'value': ths_flows[ts_code].get('main_force_inflow')}
                if ts_code in jqdata_flows:
                    flow_sources['jqdata'] = {'value': jqdata_flows[ts_code].get('main_force_inflow')}

                flow_result = cross_validate(
                    ts_code=ts_code, name=name, indicator='main_force_inflow',
                    sources_data=flow_sources, snapshot_time=snapshot_time,
                    trade_date=datetime.strptime(trade_date, '%Y-%m-%d').date() if isinstance(trade_date, str) else trade_date,
                )
                authority_flow = flow_result['authority_value'] if flow_result['authority_value'] is not None else main_flow

                # === 交叉验证：价格 ===
                price_sources = {'eastmoney': {'value': price}}
                if ts_code in tencent_prices:
                    price_sources['tencent'] = {'value': tencent_prices[ts_code].get('price')}
                if ts_code in tdx_prices:
                    price_sources['tdx'] = {'value': tdx_prices[ts_code].get('price')}
                if ts_code in akshare_prices:
                    price_sources['akshare'] = {'value': akshare_prices[ts_code].get('price')}
                if ts_code in efinance_prices:
                    price_sources['efinance'] = {'value': efinance_prices[ts_code].get('price')}
                if ts_code in adata_prices:
                    price_sources['adata'] = {'value': adata_prices[ts_code].get('price')}
                if ts_code in sina_quote_prices:
                    price_sources['sina_quote'] = {'value': sina_quote_prices[ts_code].get('price')}
                if ts_code in tencent_kline_prices:
                    price_sources['tencent_kline'] = {'value': tencent_kline_prices[ts_code].get('price')}
                if ts_code in baostock_prices:
                    price_sources['baostock'] = {'value': baostock_prices[ts_code].get('price')}
                if ts_code in itick_prices:
                    price_sources['itick'] = {'value': itick_prices[ts_code].get('price')}
                if ts_code in jqdata_prices:
                    price_sources['jqdata'] = {'value': jqdata_prices[ts_code].get('price')}
                if ts_code in mootdx_prices:
                    price_sources['mootdx'] = {'value': mootdx_prices[ts_code].get('price')}
                if ts_code in qstock_prices:
                    price_sources['qstock'] = {'value': qstock_prices[ts_code].get('price')}

                price_result = cross_validate(
                    ts_code=ts_code, name=name, indicator='price',
                    sources_data=price_sources, snapshot_time=snapshot_time,
                    trade_date=datetime.strptime(trade_date, '%Y-%m-%d').date() if isinstance(trade_date, str) else trade_date,
                )
                authority_price = price_result['authority_value'] if price_result['authority_value'] is not None else price

                # 综合置信度（取较低的）
                confidence_map = {'high': 3, 'medium': 2, 'low': 1, 'disputed': 0, 'no_data': 0}
                overall_confidence = flow_result['confidence']
                if confidence_map.get(price_result['confidence'], 0) < confidence_map.get(overall_confidence, 0):
                    overall_confidence = price_result['confidence']

                # 综合质量评分
                overall_score = (flow_result['quality_score'] + price_result['quality_score']) / 2
                all_sources = list(set(flow_result['sources_used'] + price_result['sources_used']))
                all_outliers = list(set(flow_result['outliers'] + price_result['outliers']))

                record = RealtimeStockFlow(
                    snapshot_time=snapshot_time,
                    trade_date=trade_date,
                    ts_code=ts_code,
                    name=name,
                    sector=sf.get('sector'),
                    net_inflow=sf.get('net_inflow'),
                    main_force_inflow=authority_flow,
                    retail_flow=sf.get('retail_flow'),
                    price_chg=price_chg,
                    price=authority_price,
                    source=','.join(all_sources) if all_sources else 'eastmoney',
                    confidence=overall_confidence,
                    sources_count=len(all_sources),
                    sources_used=','.join(all_sources),
                    deviation_pct=flow_result['deviation_pct'],
                    is_corrected=flow_result['is_corrected'] or price_result['is_corrected'],
                    correction_note=f"outliers:{','.join(all_outliers)}" if all_outliers else None,
                )
                db.add(record)
                saved += 1
                if len(all_sources) > 1:
                    validated += 1

            db.commit()
            logger.info(f'[realtime] Saved {saved} stock snapshots ({validated} multi-source validated)')
        except Exception as e:
            db.rollback()
            logger.exception(f'[realtime] Stock save error')
    return saved


def _compute_concept_flows_from_stocks(db, snapshot_time, trade_date, concept_map):
    """
    基于 RealtimeStockFlow 计算 concept_sectors 表中所有有成分股的概念板块资金流向。
    用于多源聚合：所有概念（含新浪的）都从成分股多源个股数据聚合，再与新浪板块维度数值交叉验证。
    返回: {concept_name: {'net_flow': ..., 'money_inflow': ..., 'money_outflow': ..., 'rise_ratio': ..., 'covered': N}, ...}
    """
    from db.models import RealtimeConceptSectorFlow, ConceptSector
    from sqlalchemy import func

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
    from db.models import RealtimeConceptSectorFlow, ConceptSector
    from sqlalchemy import func

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


def collect_realtime_snapshot(trade_date):
    """采集一次完整的实时快照（板块+个股+概念板块）"""
    print(f'[realtime] === Snapshot for {trade_date} ===')
    sector_count = collect_realtime_sector_flow(trade_date)
    stock_count = collect_realtime_stock_flow(trade_date)
    # 概念板块放在个股之后，便于用成分股计算补充新浪没有的热门概念
    concept_count = collect_realtime_concept_sector_flow(trade_date)
    print(f'[realtime] Snapshot done: {sector_count} sectors, {concept_count} concepts, {stock_count} stocks')
    return {'sector_count': sector_count, 'concept_count': concept_count, 'stock_count': stock_count}


def archive_today_snapshot_to_history(trade_date):
    """
    收盘后归档：多源交叉验证后写入历史表
    1. 先触发一次多源采集+交叉验证（确保权威值是最新的）
    2. 把权威值写入历史表（每天一条）
    3. 对于盘中未采集的股票，盘后补齐
    """
    from db.models import SectorFlow, StockFlow
    from sqlalchemy import func

    print(f'[archive] === 盘后归档开始 {trade_date} ===')

    # 步骤1：盘后再采集一次多源数据+交叉验证
    print('[archive] 步骤1: 盘后多源采集+交叉验证...')
    collect_realtime_snapshot(trade_date)

    try:
        with get_db_session() as db:
            # 步骤2：取最后一次快照的权威值写入历史表
            # 板块归档
            last_sector_time = db.query(func.max(RealtimeSectorFlow.snapshot_time)).filter_by(
                trade_date=trade_date
            ).scalar()
            last_stock_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter_by(
                trade_date=trade_date
            ).scalar()

            if last_sector_time:
                sectors = db.query(RealtimeSectorFlow).filter_by(
                    trade_date=trade_date, snapshot_time=last_sector_time
                ).all()
                existing = {s.sector: s for s in db.query(SectorFlow).filter_by(trade_date=trade_date).all()}
                for rt in sectors:
                    hist = existing.get(rt.sector)
                    if hist:
                        hist.money_inflow = rt.money_inflow
                        hist.money_outflow = rt.money_outflow
                        hist.net_flow = rt.net_flow
                        hist.rise_ratio = rt.rise_ratio
                    else:
                        db.add(SectorFlow(
                            trade_date=trade_date, sector=rt.sector,
                            money_inflow=rt.money_inflow, money_outflow=rt.money_outflow,
                            net_flow=rt.net_flow, rise_ratio=rt.rise_ratio,
                        ))
                print(f'[archive] 步骤2: 板块归档 {len(sectors)} 个')

            # 个股归档：使用交叉验证后的权威值
            if last_stock_time:
                stocks = db.query(RealtimeStockFlow).filter_by(
                    trade_date=trade_date, snapshot_time=last_stock_time
                ).all()
                existing = {s.ts_code: s for s in db.query(StockFlow).filter_by(trade_date=trade_date).all()}
                archived_count = 0
                high_confidence_count = 0
                for rt in stocks:
                    hist = existing.get(rt.ts_code)
                    # 使用交叉验证后的权威值（rt.main_force_inflow 已经是权威值）
                    if hist:
                        hist.net_inflow = rt.net_inflow
                        hist.main_force_inflow = rt.main_force_inflow
                        hist.retail_flow = rt.retail_flow
                        hist.price_chg = rt.price_chg
                        hist.price = rt.price
                        hist.sector = rt.sector
                        hist.name = rt.name
                    else:
                        db.add(StockFlow(
                            trade_date=trade_date, ts_code=rt.ts_code, name=rt.name,
                            sector=rt.sector, net_inflow=rt.net_inflow,
                            main_force_inflow=rt.main_force_inflow, retail_flow=rt.retail_flow,
                            price_chg=rt.price_chg, price=rt.price,
                        ))
                    archived_count += 1
                    if rt.confidence == 'high':
                        high_confidence_count += 1
                print(f'[archive] 步骤2: 个股归档 {archived_count} 只 (高置信度: {high_confidence_count}只)')

            # 步骤3：盘后补齐 - 对盘中未采集的股票用多源验证补采
            print('[archive] 步骤3: 盘后补齐日线...')
            _backfill_missing_stocks(trade_date, db)

            # 步骤4：复验pending审核记录（盘后重新采集多源数据验证）
            print('[archive] 步骤4: 复验pending审核记录...')
            _reverify_pending_reviews(trade_date, db)

            db.commit()
        print(f'[archive] === 盘后归档完成 {trade_date} ===')
    except Exception as e:
        db.rollback()
        logger.exception(f'[archive] Error')


def _backfill_missing_stocks(trade_date, db):
    """盘后补齐：对盘中未采集的股票用多源验证补采日线数据"""
    from db.models import StockFlow
    from collectors.tdx_collector import get_stock_money_flow
    from collectors.astock_collector import batch_realtime_quotes
    from analyzers.cross_validator import cross_validate
    from datetime import datetime

    # 获取已归档的股票代码
    existing_codes = {s.ts_code for s in db.query(StockFlow).filter_by(trade_date=trade_date).all()}

    # 获取全市场个股资金流向（东方财富批量）
    all_stocks = get_stock_money_flow(trade_date)
    if not all_stocks:
        print('[backfill] No stock data from eastmoney')
        return

    missing = [s for s in all_stocks if s['ts_code'] not in existing_codes]
    if not missing:
        print('[backfill] All stocks already archived')
        return

    print(f'[backfill] 补齐 {len(missing)} 只未归档股票')

    # 用腾讯财经批量验证价格
    ts_codes = [s['ts_code'] for s in missing[:200]]  # 限制200只
    tencent_prices = batch_realtime_quotes(ts_codes) if ts_codes else {}

    snapshot_time = datetime.now().replace(second=0, microsecond=0)
    backfilled = 0
    for s in missing[:200]:
        ts_code = s['ts_code']
        name = s.get('name', '')
        main_flow = float(s.get('main_force_inflow', 0) or 0)
        price = float(s.get('price', 0) or 0)
        price_chg = float(s.get('price_chg', 0) or 0)

        # 交叉验证价格
        price_sources = {'eastmoney': {'value': price}}
        if ts_code in tencent_prices:
            price_sources['tencent'] = {'value': tencent_prices[ts_code].get('price')}

        price_result = cross_validate(
            ts_code=ts_code, name=name, indicator='price',
            sources_data=price_sources, snapshot_time=snapshot_time,
            trade_date=trade_date,
        )
        authority_price = price_result['authority_value'] if price_result['authority_value'] is not None else price

        # 写入历史表
        db.add(StockFlow(
            trade_date=trade_date, ts_code=ts_code, name=name,
            sector=s.get('sector', ''), net_inflow=main_flow,
            main_force_inflow=main_flow, retail_flow=float(s.get('retail_flow', 0) or 0),
            price_chg=price_chg, price=authority_price,
        ))
        backfilled += 1

    print(f'[backfill] 补齐完成: {backfilled} 只')


def _reverify_pending_reviews(trade_date, db):
    """
    盘后复验pending审核记录：
    1. 重新采集多源数据验证
    2. CV≤15% → 自动通过
    3. CV>15% → 取中位数作为最终值（低置信度），标注"盘后复验仍分歧"
    4. 确保所有pending记录都有最终值，不再遗留
    """
    import json, statistics
    from datetime import datetime
    from db.models import ManualReviewQueue, StockFlow
    from collectors.astock_collector import batch_realtime_quotes

    pending = db.query(ManualReviewQueue).filter_by(status='pending').all()
    if not pending:
        print('[reverify] 无pending审核记录')
        return

    print(f'[reverify] 复验 {len(pending)} 条pending记录')

    # 批量获取腾讯财经价格（用于价格指标复验）
    ts_codes = list({r.ts_code for r in pending})
    tencent_data = batch_realtime_quotes(ts_codes) if ts_codes else {}

    # 批量获取国信证券数据（用于资金流向复验）
    guosen_data = {}
    try:
        from collectors.guosen_collector import guosen_single_fund_flow
        for code in ts_codes[:20]:  # 限制20只避免额度问题
            data = guosen_single_fund_flow(code)
            if data:
                guosen_data[code] = data
    except Exception as e:
        print(f'[reverify] 国信证券采集失败: {e}')

    auto_passed = 0
    forced_pass = 0

    for r in pending:
        # 重新采集多源数据
        new_sources = {}

        # 东方财富：从最新快照获取
        latest_rt = db.query(RealtimeStockFlow).filter_by(
            trade_date=trade_date, ts_code=r.ts_code
        ).order_by(RealtimeStockFlow.snapshot_time.desc()).first()

        if latest_rt:
            if r.indicator == 'main_force_inflow':
                new_sources['eastmoney'] = float(latest_rt.main_force_inflow or 0)
            elif r.indicator == 'price':
                new_sources['eastmoney'] = float(latest_rt.price or 0)
            elif r.indicator == 'price_chg':
                new_sources['eastmoney'] = float(latest_rt.price_chg or 0)

        # 腾讯财经：价格
        if r.ts_code in tencent_data and r.indicator == 'price':
            new_sources['tencent'] = float(tencent_data[r.ts_code].get('price', 0) or 0)

        # 国信证券：资金流向+价格
        if r.ts_code in guosen_data:
            gd = guosen_data[r.ts_code]
            if r.indicator == 'main_force_inflow' and gd.get('main_force_inflow') is not None:
                new_sources['guosen'] = float(gd['main_force_inflow'])

        # 合并原始数据
        try:
            old_raw = json.loads(r.sources_data) if r.sources_data else {}
            for k, v in old_raw.items():
                val = v.get('value') if isinstance(v, dict) else v
                if val is not None and k not in new_sources:
                    new_sources[k] = float(val)
        except Exception:
            logger.debug('handled exception', exc_info=True)

        vals = list(new_sources.values())
        if not vals:
            # 无数据，强制拒绝
            r.status = 'rejected'
            r.reviewed_by = 'auto_reverify'
            r.reviewed_at = datetime.now()
            r.reason = f'[盘后复验] 无有效数据，拒绝'
            forced_pass += 1
            continue

        median = statistics.median(vals)
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0
        cv = (std / abs(mean) * 100) if mean else 0

        if cv <= 15.0:
            # CV≤15%：自动通过
            if cv <= 5.0:
                final_value = statistics.mean(vals)
                confidence = '高'
                reason = f'盘后复验CV={cv:.1f}%≤5%，取平均值'
            else:
                final_value = median
                confidence = '中'
                reason = f'盘后复验CV={cv:.1f}%≤15%，取中位数'
            r.status = 'approved'
            r.final_value = final_value
            r.reviewed_by = 'auto_reverify'
            r.reviewed_at = datetime.now()
            r.reason = f'[盘后复验·{confidence}置信度] {reason}'
            r.sources_data = json.dumps(new_sources, ensure_ascii=False, default=str)
            auto_passed += 1
            print(f'  {r.ts_code} {r.indicator}: ✅ 复验通过({confidence}) CV={cv:.1f}% 值={final_value:.2f}')
        else:
            # CV>15%：盘后仍分歧，取中位数作为最终值（低置信度）
            final_value = median
            r.status = 'approved'
            r.final_value = final_value
            r.reviewed_by = 'auto_reverify'
            r.reviewed_at = datetime.now()
            r.reason = f'[盘后复验·低置信度] CV={cv:.1f}%>15%，盘后仍分歧，取中位数。建议次日关注'
            r.sources_data = json.dumps(new_sources, ensure_ascii=False, default=str)
            forced_pass += 1
            print(f'  {r.ts_code} {r.indicator}: ⚠️ 盘后仍分歧 CV={cv:.1f}%，取中位数={final_value:.2f}')

        # 同步更新历史表的权威值
        hist = db.query(StockFlow).filter_by(
            trade_date=trade_date, ts_code=r.ts_code
        ).first()
        if hist and r.final_value is not None:
            if r.indicator == 'main_force_inflow':
                hist.main_force_inflow = r.final_value
            elif r.indicator == 'price':
                hist.price = r.final_value
            elif r.indicator == 'price_chg':
                hist.price_chg = r.final_value

    print(f'[reverify] 完成: 自动通过{auto_passed}条，强制取中位数{forced_pass}条')


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    # 测试采集
    result = collect_realtime_snapshot(today)
    print(result)