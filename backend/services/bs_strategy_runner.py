"""
BS策略每日预计算服务
- 盘后定时跑最近 N 条 BSBacktestResult 策略，结果落 bs_daily_scan 表
- 前端 /api/bs-screener/today 读取预计算结果，消除现场全市场扫描
- 防重复跑：同 trade_date × backtest_id 只跑一次（唯一约束）
"""
import sys
import os
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func
from db.connection import get_db
from db.session import get_db_session
from db.models import BSBacktestResult, BSDailyScan

logger = logging.getLogger(__name__)

# 每天预计算的最近回测策略数量（与前端 StrategyCenterPage 的 limit=5 对齐，多取5个留余量）
PRECOMPUTE_TOP_N = 10


async def precompute_bs_strategies(target_date=None) -> dict:
    """跑最近 N 条 BSBacktestResult 策略，结果落 bs_daily_scan 表。

    Args:
        target_date: 指定日期（None=今天）

    Returns:
        {'success': int, 'failed': int, 'skipped': int, 'details': [...]}
    """
    from api.bs_screener import _execute_bs_scan_core

    if target_date is None:
        target_date = datetime.now().date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

    with get_db_session() as db:
        stats = {'success': 0, 'failed': 0, 'skipped': 0, 'details': []}
        try:
            backtests = db.query(BSBacktestResult).order_by(
                BSBacktestResult.run_at.desc()
            ).limit(PRECOMPUTE_TOP_N).all()

            if not backtests:
                logger.info('[bs-precompute] 无 BSBacktestResult 记录，跳过')
                return stats

            for bt in backtests:
                exists = db.query(BSDailyScan).filter(
                    BSDailyScan.trade_date == target_date,
                    BSDailyScan.backtest_id == bt.id,
                ).first()
                if exists:
                    stats['skipped'] += 1
                    stats['details'].append({
                        'backtest_id': bt.id, 'name': bt.name,
                        'status': 'skipped', 'hits': exists.hit_count,
                    })
                    continue

                start = datetime.now()
                try:
                    result = await _execute_bs_scan_core(
                        db,
                        atr_period=bt.atr_period or 10,
                        atr_multiplier=float(bt.atr_multiplier or 1.0),
                        scan_limit=9999,
                        sector='',
                        signal_type='B',
                        volume_filter=bool(bt.volume_filter),
                        ma20_filter=bool(bt.ma20_filter),
                        ma60_trend=bool(getattr(bt, 'ma60_trend', False) or False),
                        rsi_filter=bool(getattr(bt, 'rsi_filter', False) or False),
                        strong_volume=bool(getattr(bt, 'strong_volume', False) or False),
                        macd_filter=bool(getattr(bt, 'macd_filter', False) or False),
                        kdj_filter=bool(getattr(bt, 'kdj_filter', False) or False),
                        rsi_lower=int(getattr(bt, 'rsi_lower', 30) or 30),
                        rsi_upper=int(getattr(bt, 'rsi_upper', 70) or 70),
                        dimension=bt.dimension or '',
                    )
                    signals = result.get('signals', [])
                    summary = result.get('summary', {})
                    row = BSDailyScan(
                        trade_date=target_date,
                        backtest_id=bt.id,
                        strategy_name=bt.name or f'BS-{bt.id}',
                        dimension=bt.dimension or '',
                        signals_json=json.dumps(signals, ensure_ascii=False),
                        summary_json=json.dumps(summary, ensure_ascii=False),
                        scanned=result.get('scanned', 0),
                        hit_count=len(signals),
                    )
                    db.add(row)
                    db.commit()
                    dur = (datetime.now() - start).total_seconds()
                    stats['success'] += 1
                    stats['details'].append({
                        'backtest_id': bt.id, 'name': bt.name,
                        'status': 'success', 'hits': len(signals),
                        'scanned': result.get('scanned', 0), 'dur_s': round(dur, 1),
                    })
                    logger.info(
                        f'[bs-precompute] bt={bt.id}({bt.name}) dim={bt.dimension} '
                        f'hits={len(signals)} scanned={result.get("scanned", 0)} dur={dur:.1f}s'
                    )
                except Exception as e:
                    db.rollback()
                    stats['failed'] += 1
                    stats['details'].append({
                        'backtest_id': bt.id, 'name': bt.name,
                        'status': 'failed', 'error': str(e)[:200],
                    })
                    logger.exception(f'[bs-precompute] bt={bt.id}({bt.name}) failed: {e}')
        except Exception as e:
            logger.exception(f'[bs-precompute] outer error: {e}')

    logger.info(
        f'[bs-precompute] {target_date} done: '
        f"success={stats['success']} failed={stats['failed']} skipped={stats['skipped']}"
    )
    return stats


if __name__ == '__main__':
    import asyncio
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    result = asyncio.run(precompute_bs_strategies())
    logger.info(json.dumps(result, ensure_ascii=False, indent=2))
