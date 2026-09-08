"""
外部数据采集器：从 Tushare 直接拉取复权因子/融资融券/北向资金/停牌数据
不依赖 hermes 数据库，独立采集到 airobot 对应表。

数据源：Tushare（与 hermes 使用同一上游，token 通过 config.TUSHARE_TOKEN）
调用方式：复用 existing collectors.tdx_collector.call_tushare_mcp
"""
import logging
from datetime import datetime, timedelta, date
from db.session import get_db_session
from collectors.tdx_collector import call_tushare_mcp

logger = logging.getLogger(__name__)

def collect_stock_adj_factor(trade_date: str = None):
    """采集复权因子 adj_factor（Tushare API: adj_factor）
    按股票逐只拉取复权因子，写入 stock_adj_factor
    """
    if not trade_date:
        trade_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    logger.info(f'[external] 采集复权因子 {trade_date}...')
    rows = call_tushare_mcp('adj_factor', params={'trade_date': trade_date})
    if rows is None:
        logger.warning(f'[external] adj_factor 返回空')
        return 0
    
    from sqlalchemy import text
    saved = 0
    with get_db_session() as db:
        for row in rows:
            ts_code = row.get('ts_code')
            adj = row.get('adj_factor')
            if not ts_code or adj is None:
                continue
            try:
                db.execute(text("""
                    INSERT INTO stock_adj_factor (ts_code, trade_date, adj_factor, created_at)
                    VALUES (:code, :date, :adj, NOW())
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET adj_factor=:adj2
                """), {
                    'code': ts_code, 'date': trade_date,
                    'adj': float(adj), 'adj2': float(adj)
                })
                saved += 1
            except Exception as e:
                logger.error(f'[external] adj_factor save error {ts_code}: {e}')
        db.commit()
    logger.info(f'[external] 复权因子: 保存 {saved} 条')
    return saved


def collect_stock_margin_data(trade_date: str = None):
    """采集融资融券 margin_data（Tushare API: margin_detail）
    字段：trade_date, ts_code, rzye(融资余额), rzmre(融资买入额) 等
    """
    if not trade_date:
        trade_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    logger.info(f'[external] 采集融资融券 {trade_date}...')
    rows = call_tushare_mcp('margin_detail', params={'trade_date': trade_date})
    if rows is None:
        logger.warning(f'[external] margin_detail 返回空')
        return 0
    
    from sqlalchemy import text
    saved = 0
    with get_db_session() as db:
        for row in rows:
            ts_code = row.get('ts_code')
            if not ts_code or not ts_code.endswith(('.SH', '.SZ')):
                continue
            try:
                db.execute(text("""
                    INSERT INTO stock_margin_data (trade_date, ts_code, rzye, rqye, rzmre, rzche, rqyl, rqchl, rqmcl, rzrqye, created_at)
                    VALUES (:date,:code,:rzye,:rqye,:rzmre,:rzche,:rqyl,:rqchl,:rqmcl,:rzrqye,NOW())
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                        rzye=:rzye2, rqye=:rqye2, rzmre=:rzmre2, rzche=:rzche2,
                        rqyl=:rqyl2, rqchl=:rqchl2, rqmcl=:rqmcl2, rzrqye=:rzrqye2
                """), {
                    'date': trade_date, 'code': ts_code,
                    'rzye': float(row.get('rzye',0) or 0), 'rzye2': float(row.get('rzye',0) or 0),
                    'rqye': float(row.get('rqye',0) or 0), 'rqye2': float(row.get('rqye',0) or 0),
                    'rzmre': float(row.get('rzmre',0) or 0), 'rzmre2': float(row.get('rzmre',0) or 0),
                    'rzche': float(row.get('rzche',0) or 0), 'rzche2': float(row.get('rzche',0) or 0),
                    'rqyl': float(row.get('rqyl',0) or 0), 'rqyl2': float(row.get('rqyl',0) or 0),
                    'rqchl': float(row.get('rqchl',0) or 0), 'rqchl2': float(row.get('rqchl',0) or 0),
                    'rqmcl': float(row.get('rqmcl',0) or 0), 'rqmcl2': float(row.get('rqmcl',0) or 0),
                    'rzrqye': float(row.get('rzrqye',0) or 0), 'rzrqye2': float(row.get('rzrqye',0) or 0),
                })
                saved += 1
            except Exception as e:
                logger.error(f'[external] margin save error {ts_code}: {e}')
        db.commit()
    logger.info(f'[external] 融资融券: 保存 {saved} 条')
    return saved


def collect_north_money_flow(trade_date: str = None):
    """采集北向资金 north_money_flow（Tushare API: moneyflow_hsgt）"""
    if not trade_date:
        trade_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    logger.info(f'[external] 采集北向资金 {trade_date}...')
    rows = call_tushare_mcp('moneyflow_hsgt', params={'trade_date': trade_date})
    if not rows:
        logger.warning(f'[external] moneyflow_hsgt 返回空')
        return 0
    
    from sqlalchemy import text
    saved = 0
    with get_db_session() as db:
        for row in rows:
            try:
                db.execute(text("""
                    INSERT INTO north_money_flow (trade_date, hgt, sgt, north_money, south_money, ggt_ss, ggt_sz, created_at)
                    VALUES (:date,:hgt,:sgt,:nm,:sm,:gss,:gsz,NOW())
                    ON CONFLICT (trade_date) DO UPDATE SET
                        hgt=:hgt2, sgt=:sgt2, north_money=:nm2, south_money=:sm2,
                        ggt_ss=:gss2, ggt_sz=:gsz2
                """), {
                    'date': trade_date,
                    'hgt': float(row.get('hgt',0) or 0), 'hgt2': float(row.get('hgt',0) or 0),
                    'sgt': float(row.get('sgt',0) or 0), 'sgt2': float(row.get('sgt',0) or 0),
                    'nm': float(row.get('north_money',0) or 0), 'nm2': float(row.get('north_money',0) or 0),
                    'sm': float(row.get('south_money',0) or 0), 'sm2': float(row.get('south_money',0) or 0),
                    'gss': float(row.get('ggt_ss',0) or 0), 'gss2': float(row.get('ggt_ss',0) or 0),
                    'gsz': float(row.get('ggt_sz',0) or 0), 'gsz2': float(row.get('ggt_sz',0) or 0),
                })
                saved += 1
            except Exception as e:
                logger.error(f'[external] north_money save error: {e}')
        db.commit()
    logger.info(f'[external] 北向资金: 保存 {saved} 条')
    return saved


def collect_suspend_stock_daily(trade_date: str = None):
    """采集停牌股票 suspend_stock_daily（Tushare API: suspend_d）"""
    if not trade_date:
        trade_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    logger.info(f'[external] 采集停牌 {trade_date}...')
    rows = call_tushare_mcp('suspend_d', params={'trade_date': trade_date})
    if not rows:
        logger.info(f'[external] suspend_d 返回空（今日无新增停牌）')
        return 0
    
    from sqlalchemy import text
    saved = 0
    with get_db_session() as db:
        for row in rows:
            ts_code = row.get('ts_code')
            if not ts_code:
                continue
            try:
                db.execute(text("""
                    INSERT INTO suspend_stock_daily (trade_date, ts_code, suspend_timing, suspend_type, created_at)
                    VALUES (:date,:code,:timing,:type,NOW())
                    ON CONFLICT (ts_code, trade_date) DO NOTHING
                """), {
                    'date': trade_date, 'code': ts_code,
                    'timing': row.get('suspend_timing', ''),
                    'type': row.get('suspend_type', ''),
                })
                saved += 1
            except Exception as e:
                logger.error(f'[external] suspend save error {ts_code}: {e}')
        db.commit()
    logger.info(f'[external] 停牌: 保存 {saved} 条')
    return saved


def collect_hsgt_top10(trade_date: str = None):
    """采集沪深港通十大成交 hsgt_top10（Tushare API: hsgt_top10）"""
    if not trade_date:
        trade_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    
    logger.info(f'[external] 采集沪深港通十大成交 {trade_date}...')
    rows = call_tushare_mcp('hsgt_top10', params={'trade_date': trade_date})
    if not rows:
        logger.warning(f'[external] hsgt_top10 返回空')
        return 0
    
    from sqlalchemy import text
    saved = 0
    with get_db_session() as db:
        for row in rows:
            ts_code = row.get('ts_code')
            if not ts_code:
                continue
            try:
                db.execute(text("""
                    INSERT INTO hsgt_top10 (trade_date, ts_code, name, close, change_pct, rank, market_type, amount, net_amount, buy_amount, sell_amount, created_at)
                    VALUES (:date,:code,:name,:close,:chg,:rank,:mkt,:amt,:net,:buy,:sell,NOW())
                    ON CONFLICT (ts_code, trade_date) DO UPDATE SET
                        name=:name2, close=:close2, change_pct=:chg2, rank=:rank2,
                        amount=:amt2, net_amount=:net2, buy_amount=:buy2, sell_amount=:sell2
                """), {
                    'date': trade_date, 'code': ts_code,
                    'name': row.get('name',''), 'name2': row.get('name',''),
                    'close': float(row.get('close',0) or 0), 'close2': float(row.get('close',0) or 0),
                    'chg': float(row.get('pct_change',0) or 0), 'chg2': float(row.get('pct_change',0) or 0),
                    'rank': int(row.get('rank',0) or 0), 'rank2': int(row.get('rank',0) or 0),
                    'mkt': row.get('market_type',''),
                    'amt': float(row.get('amount',0) or 0), 'amt2': float(row.get('amount',0) or 0),
                    'net': float(row.get('net_amount',0) or 0), 'net2': float(row.get('net_amount',0) or 0),
                    'buy': float(row.get('buy',0) or 0), 'buy2': float(row.get('buy',0) or 0),
                    'sell': float(row.get('sell',0) or 0), 'sell2': float(row.get('sell',0) or 0),
                })
                saved += 1
            except Exception as e:
                logger.error(f'[external] hsgt_top10 save error {ts_code}: {e}')
        db.commit()
    logger.info(f'[external] 沪深港通十大成交: 保存 {saved} 条')
    return saved


def collect_all_external(trade_date: str = None):
    """批量采集所有外部数据（分两波）
    
    第一波（16:00，收盘后立即）：adj_factor(盘中可用) + suspend_d(盘中可用) + wave_signals(收盘后计算)
    第二波（次日09:30）：margin_data(T+1) + north_money_flow(T+1) + hsgt_top10(T+1)
    """
    if not trade_date:
        trade_date = datetime.now().strftime('%Y%m%d')
    
    results = {}
    results['adj_factor'] = collect_stock_adj_factor(trade_date)
    results['suspend'] = collect_suspend_stock_daily(trade_date)
    results['wave_signals'] = 0  # 波浪信号由 watchlist_signal_compute 在 16:00 生成
    results['margin_data'] = collect_stock_margin_data(trade_date)
    results['north_money'] = collect_north_money_flow(trade_date)
    results['hsgt_top10'] = collect_hsgt_top10(trade_date)
    
    logger.info(f'[external] 全部采集完成: {results}')
    return results


def collect_external_wave1(trade_date: str = None):
    """第一波（16:00）：adj_factor + suspend_d（当天盘中即可用）"""
    if not trade_date:
        trade_date = datetime.now().strftime('%Y%m%d')
    results = {}
    results['adj_factor'] = collect_stock_adj_factor(trade_date)
    results['suspend'] = collect_suspend_stock_daily(trade_date)
    logger.info(f'[external] 第一波采集完成: {results}')
    return results


def collect_external_wave2(trade_date: str = None):
    """第二波（次日09:30）：margin_data + north_money_flow + hsgt_top10（T+1数据）
    含重试逻辑：如果某数据为空，记录但继续（外部数据可能延迟）
    """
    # 第二波采集的目标日期是昨天（T+1）
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    if not trade_date:
        trade_date = yesterday
    results = {}
    results['margin_data'] = collect_stock_margin_data(trade_date)
    results['north_money'] = collect_north_money_flow(trade_date)
    results['hsgt_top10'] = collect_hsgt_top10(trade_date)
    logger.info(f'[external] 第二波采集完成({trade_date}): {results}')
    return results
