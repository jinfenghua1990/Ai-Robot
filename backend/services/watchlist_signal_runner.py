"""
个股信号预计算服务
- 盘后批量计算候选股票的 signal，落库到 WatchlistSignalDaily 表
- 消除 /api/watchlist、/api/panorama/stocks、/api/leader/system 的现场计算/HTTP拉取
- 防重复跑：同 trade_date 只跑一次（has_run_today 检查）
"""
import sys
import os
import json
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_db
from db.session import get_db_session
from db.models import WatchlistSignalDaily, StockFlow, SectorFlow, Watchlist
import logging
logger = logging.getLogger(__name__)


def check_data_ready(target_date=None) -> bool:
    """检测当日盘后数据是否完整（SectorFlow + StockFlow 都有当日数据）"""
    if target_date is None:
        target_date = datetime.now().date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

    try:
        with get_db_session() as db:
            sector_count = db.query(SectorFlow).filter(SectorFlow.trade_date == target_date).count()
            stock_count = db.query(StockFlow).filter(StockFlow.trade_date == target_date).count()
            return sector_count > 30 and stock_count > 500
    except Exception as e:
        logger.error(f'[watchlist_signal_runner] check_data_ready error: {e}')
        return False


def has_run_today(target_date=None) -> bool:
    """检查当日是否已预计算"""
    if target_date is None:
        target_date = datetime.now().date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

    with get_db_session() as db:
        count = db.query(WatchlistSignalDaily).filter(
            WatchlistSignalDaily.trade_date == target_date
        ).count()
        return count > 0


def _get_candidate_stocks(db, trade_date, limit=300):
    """候选股票池：StockFlow主力净流入前N只 + Watchlist自选股（去重）
    返回: [{'code', 'ts_code', 'name', 'sector', 'change_rate', 'main_force_inflow'}, ...]
    """
    candidates = {}

    # 1. StockFlow main_force_inflow > 0 前 N 只（覆盖 panorama 前端展示）
    rows = db.query(
        StockFlow.ts_code, StockFlow.name, StockFlow.sector,
        StockFlow.main_force_inflow, StockFlow.price_chg,
    ).filter(
        StockFlow.trade_date == trade_date, StockFlow.main_force_inflow > 0,
    ).order_by(StockFlow.main_force_inflow.desc()).limit(limit).all()

    for r in rows:
        code = r.ts_code.split('.')[0] if '.' in r.ts_code else r.ts_code
        candidates[code] = {
            'code': code, 'ts_code': r.ts_code, 'name': r.name or '',
            'sector': r.sector or '', 'change_rate': float(r.price_chg or 0),
            'main_force_inflow': float(r.main_force_inflow or 0),
        }

    # 2. Watchlist 自选股（补充不在前N的自选股，确保 watchlist 页面有数据）
    wl_rows = db.query(Watchlist.stock_code, Watchlist.stock_name).all()
    for r in wl_rows:
        code = r.stock_code
        if code in candidates:
            continue
        ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        sf = db.query(StockFlow).filter(
            StockFlow.trade_date == trade_date, StockFlow.ts_code == ts_code
        ).first()
        candidates[code] = {
            'code': code, 'ts_code': ts_code, 'name': r.stock_name or code,
            'sector': sf.sector if sf else '', 'change_rate': float(sf.price_chg or 0) if sf else 0,
            'main_force_inflow': float(sf.main_force_inflow or 0) if sf else 0,
        }

    return list(candidates.values())


def compute_for_date(target_date=None):
    """盘后批量计算个股信号并落库 WatchlistSignalDaily"""
    if target_date is None:
        target_date = datetime.now().date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

    if not check_data_ready(target_date):
        logger.info(f'[watchlist_signal_runner] data not ready for {target_date}')
        return False

    if has_run_today(target_date):
        logger.info(f'[watchlist_signal_runner] already computed for {target_date}')
        return True

    started = datetime.now()
    logger.info(f'[watchlist_signal_runner] computing for {target_date}')

    try:
        with get_db_session() as db:
            candidates = _get_candidate_stocks(db, target_date)
            logger.info(f'[watchlist_signal_runner] {len(candidates)} candidates')

            # 批量计算 signal（async，用 asyncio.run 包装）
            from services.signal_builder import build_signals_batch
            signals = asyncio.run(build_signals_batch(
                candidates, db,
                code_key='code', name_key='name', sector_key='sector',
                change_key='change_rate',
                batch_size=20,
            ))
            logger.info(f'[watchlist_signal_runner] {len(signals)} signals computed')

            # 构建 code → main_force_inflow 映射
            inflow_map = {c['code']: c['main_force_inflow'] for c in candidates}

            # 落库（upsert：query-by-(trade_date,ts_code) → setattr or db.add）
            upserted = 0
            for sig in signals:
                code = sig.get('secCode', '')
                if not code or len(code) != 6:
                    continue
                ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
                quote = sig.get('quote') or {}

                row = db.query(WatchlistSignalDaily).filter_by(
                    trade_date=target_date, ts_code=ts_code
                ).first()

                data = {
                    'name': sig.get('secName', ''),
                    'sector': sig.get('sector', ''),
                    'sector_trend_json': json.dumps(sig.get('sectorTrend') or {}, ensure_ascii=False),
                    'market_state_json': json.dumps(sig.get('marketState') or {}, ensure_ascii=False),
                    'bs_signal': sig.get('bsSignal'),
                    'bs_reasons_json': json.dumps(sig.get('reasons') or [], ensure_ascii=False),
                    'quality_status': sig.get('qualityStatus'),
                    'buy_power_base': json.dumps(sig.get('buyPower'), ensure_ascii=False) if sig.get('buyPower') else None,
                    'change_rate': quote.get('changePct') if quote else 0,
                    'main_force_inflow': inflow_map.get(code, 0),
                }

                if row:
                    for k, v in data.items():
                        setattr(row, k, v)
                else:
                    row = WatchlistSignalDaily(trade_date=target_date, ts_code=ts_code, **data)
                    db.add(row)
                upserted += 1

                if upserted % 100 == 0:
                    db.commit()

            db.commit()
            elapsed = (datetime.now() - started).total_seconds()
            logger.info(f'[watchlist_signal_runner] done: {upserted} rows in {elapsed:.1f}s')
        return True
    except Exception as e:
        db.rollback()
        logger.error(f'[watchlist_signal_runner] error: {e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=None, help='target date YYYY-MM-DD')
    args = parser.parse_args()
    ok = compute_for_date(args.date)
    logger.error(f'Result: {"success" if ok else "failed"}')
