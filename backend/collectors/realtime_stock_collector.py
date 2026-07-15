"""
实时个股资金流向采集器（多源+交叉验证）
额度优化策略：
- 东方财富datacenter：全市场批量（1次API，有额度限制但批量高效）
- 东财push2 + 新浪财经：Top20资金流向验证（无额度限制）
- 国信证券：Top10资金流向验证（有额度限制，减少使用）
- 腾讯财经：Top50价格验证（无额度限制）
- 通达信：Top20价格验证（TCP协议，无额度限制）
"""
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date
from db.session import get_db_session
from db.models import RealtimeStockFlow
from collectors.realtime_sector_collector import _now_truncated
from collectors.tdx_collector import get_stock_money_flow
from collectors.guosen_collector import GUOSEN_AVAILABLE, guosen_single_fund_flow
from collectors.astock_collector import (
    batch_realtime_quotes, eastmoney_fund_flow_daily,
    sina_stock_fund_flow, tdx_realtime_price,
)
from collectors.akshare_collector import akshare_batch_prices
from analyzers.cross_validator import cross_validate

logger = logging.getLogger(__name__)


def _build_fallback_stock_flows(trade_date):
    """主源失败时，从本地关键股票池构建 stock_flows（腾讯/通达信价格 + 东财push2/新浪资金流向）"""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    codes = set()
    names = {}

    def _add_code(c, name=""):
        c = str(c or "").strip()
        if not c or not c.isdigit() or len(c) != 6:
            return
        codes.add(c)
        if name:
            names.setdefault(c, name)

    # 1. 读取 watchlist
    try:
        with open(root / "watchlist.json", "r", encoding="utf-8") as f:
            for s in json.load(f).get("stocks", []):
                _add_code(s.get("code"), s.get("name"))
    except Exception as e:
        logger.warning("[fallback] read watchlist.json failed: %s", e)

    # 2. 读取 portfolio
    try:
        with open(root / "portfolio.json", "r", encoding="utf-8") as f:
            for p in json.load(f).get("positions", []):
                _add_code(p.get("symbol") or p.get("code"), p.get("name"))
    except Exception as e:
        logger.warning("[fallback] read portfolio.json failed: %s", e)

    # 3. 读取 focus
    try:
        with open(root / "focus.json", "r", encoding="utf-8") as f:
            for sec in json.load(f).get("sectors", []):
                for st in sec.get("stocks", []):
                    _add_code(st.get("code"), st.get("name"))
    except Exception as e:
        logger.warning("[fallback] read focus.json failed: %s", e)

    if not codes:
        logger.warning("[fallback] no local stock codes available")
        return []

    # 转换为 ts_code
    code_to_ts = {}
    ts_codes = []
    for c in codes:
        if c.startswith(("6", "7", "9")):
            ts = f"{c}.SH"
        elif c.startswith("8"):
            ts = f"{c}.BJ"
        else:
            ts = f"{c}.SZ"
        code_to_ts[c] = ts
        ts_codes.append(ts)

    # 4. 腾讯批量价格（无额度限制）
    prices = {}
    try:
        prices = batch_realtime_quotes(ts_codes) or {}
    except Exception as e:
        logger.warning("[fallback] tencent price failed: %s", e)

    # 5. 东财push2 + 新浪资金流向（并发，无额度限制）
    flows = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {}
        for c in codes:
            futures[executor.submit(eastmoney_fund_flow_daily, c)] = ("em_push2", c)
            futures[executor.submit(sina_stock_fund_flow, c)] = ("sina", c)

        for future in as_completed(futures):
            source, c = futures[future]
            try:
                r = future.result()
                if r:
                    ts = code_to_ts[c]
                    flows.setdefault(ts, {})[source] = r
            except Exception:
                logger.debug("realtime flow mapping skip", exc_info=False)

    # 6. 组合结果
    results = []
    for c in codes:
        ts = code_to_ts[c]
        price_data = prices.get(ts, {})
        price = price_data.get("price") or 0
        change_pct = price_data.get("change_pct") or 0
        name = price_data.get("name") or names.get(c) or ""
        flow_data = flows.get(ts, {})

        em = flow_data.get("em_push2", {})
        sina = flow_data.get("sina", {})
        main_net = em.get("main_net")
        if main_net is None:
            main_net = sina.get("main_net")
        small_net = em.get("small_net") if em else sina.get("small_net")

        if main_net is None and price <= 0:
            continue

        main_flow = main_net / 10000 if main_net else 0
        sm_flow = small_net / 10000 if small_net else 0

        results.append({
            "ts_code": ts,
            "name": name,
            "sector": "",
            "net_inflow": main_flow,
            "main_force_inflow": main_flow,
            "retail_flow": sm_flow,
            "price_chg": change_pct,
            "price": price,
            "_is_fallback": True,
        })

    logger.info("[fallback] Built %d stock flows from local pools", len(results))
    return results


def collect_realtime_stock_flow(trade_date):
    """
    采集个股实时资金流向快照（多源+交叉验证）
    """
    start_time = time.time()
    snapshot_time = _now_truncated()
    trade_date_obj = trade_date if isinstance(trade_date, date) else datetime.strptime(trade_date, '%Y-%m-%d').date()
    print(f'[realtime] Collecting stock flow snapshot at {snapshot_time}')

    # 东方财富全市场个股资金流向（主源，1次批量API）
    stock_flows = get_stock_money_flow(trade_date)
    if not stock_flows:
        print('[realtime] Primary stock flow source empty, trying fallback from local pools')
        stock_flows = _build_fallback_stock_flows(trade_date)
        if not stock_flows:
            print('[realtime] No stock flow data')
            return 0

    # 东方财富对停牌/退市/未成交股票可能返回 price=0，用腾讯批量接口补充价格
    # 腾讯 URL 长度限制，每批约 300 只
    zero_price_flows = [s for s in stock_flows if (s.get('price') or 0) <= 0]
    if zero_price_flows:
        batch_size = 300
        filled = 0
        for i in range(0, len(zero_price_flows), batch_size):
            batch = zero_price_flows[i:i + batch_size]
            ts_codes = [s['ts_code'] for s in batch]
            try:
                tencent_quotes = batch_realtime_quotes(ts_codes)
                for s in batch:
                    q = tencent_quotes.get(s['ts_code'])
                    if q and (q.get('price') or 0) > 0:
                        s['price'] = q['price']
                        if (q.get('change_pct') or 0) != 0:
                            s['price_chg'] = q['change_pct']
                        filled += 1
            except Exception as e:
                logger.warning(f'[realtime] tencent price fallback batch {i//batch_size} error: {e}', exc_info=True)
        print(f'[realtime] Filled {filled}/{len(zero_price_flows)} zero prices from tencent')

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
            logger.warning(f'[realtime] {name} price error: {e}', exc_info=True)
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

    # 3. 东财push2资金流向（Top20，无额度限制）——并发请求避免串行阻塞
    def _fetch_em_push2(s):
        code = s['ts_code'].replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        try:
            r = eastmoney_fund_flow_daily(code)
            return s['ts_code'], r
        except Exception:
            return s['ts_code'], None

    em_push2_flows = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_em_push2, s) for s in top20_for_flow]
        for future in as_completed(futures):
            ts_code, r = future.result()
            if r:
                em_push2_flows[ts_code] = r
    print(f'[realtime] EM push2 flows: {len(em_push2_flows)} stocks')

    # 4. 新浪财经资金流向（Top20，无额度限制）——并发请求避免串行阻塞
    def _fetch_sina(s):
        code = s['ts_code'].replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        try:
            r = sina_stock_fund_flow(code)
            return s['ts_code'], r
        except Exception:
            return s['ts_code'], None

    sina_flows = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_fetch_sina, s) for s in top20_for_flow]
        for future in as_completed(futures):
            ts_code, r = future.result()
            if r:
                sina_flows[ts_code] = r
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
        logger.warning(f'[realtime] THS flow error: {e}', exc_info=True)

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

                is_fallback = sf.get('_is_fallback', False)
                base_source = 'fallback' if is_fallback else 'eastmoney'

                # === 交叉验证：主力净流入 ===
                flow_sources = {base_source: {'value': main_flow}}
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
                    # 聚宽 net_amount_main 单位为"元"，统一转为万元后再交叉验证
                    jq_main = jqdata_flows[ts_code].get('main_force_inflow', 0)
                    flow_sources['jqdata'] = {'value': jq_main / 10000 if jq_main else None}

                flow_result = cross_validate(
                    ts_code=ts_code, name=name, indicator='main_force_inflow',
                    sources_data=flow_sources, snapshot_time=snapshot_time,
                    trade_date=datetime.strptime(trade_date, '%Y-%m-%d').date() if isinstance(trade_date, str) else trade_date,
                )
                authority_flow = flow_result['authority_value'] if flow_result['authority_value'] is not None else main_flow

                # === 交叉验证：价格 ===
                price_sources = {base_source: {'value': price}}
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
                    source=','.join(all_sources) if all_sources else base_source,
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
            from services.alert_service import record_alert
            record_alert(
                level='error',
                category='source_failure',
                message=f'[{trade_date_obj}] 实时个股快照数据库写入失败: {str(e)[:120]}',
                trade_date=trade_date_obj,
            )
            return 0

    # 采集结果异常检测（数量/耗时）
    try:
        duration = time.time() - start_time
        from services.alert_service import check_collection_result
        check_collection_result(
            trade_date=trade_date_obj,
            saved_count=saved,
            expected_count=5000,
            duration_seconds=duration,
        )
    except Exception as e:
        logger.error(f'[realtime] check_collection_result error: {e}', exc_info=True)

    return saved
