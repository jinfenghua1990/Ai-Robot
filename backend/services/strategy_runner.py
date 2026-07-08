"""
策略扫描服务
- 数据就绪检测（复用 scheduler._has_today_data 逻辑）
- 每日盘后跑 4 个策略（白虎V2.6/V3.0、青龙、主升浪），结果落 StrategyResult 表
- 每次运行写 StrategyRunLog，用于健康检查
- 防重复跑：同 trade_date × strategy_key 只跑一次（唯一约束）
"""
import sys
import os
import json
import time
from datetime import datetime, date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func
from db.connection import get_db
from db.session import get_db_session
from db.models import StrategyResult, StrategyRunLog, StockFlow, SectorFlow
import logging
logger = logging.getLogger(__name__)


# ============================================================
# 策略注册表（统一管理 4 个策略的元数据）
# ============================================================

STRATEGIES = [
    {
        'key': 'baihu_v26',
        'name': '白虎',
        'icon': '🐯',
        'module': 'strategies.baihu_v26',
        'func': 'run_baihu_screen',
        'needs_db': False,
    },
    {
        'key': 'baihu_v30',
        'name': '白虎V3',
        'icon': '🐯',
        'module': 'strategies.baihu_v30',
        'func': 'run_baihu_v30_screen',
        'needs_db': False,
    },
    {
        'key': 'qinglong',
        'name': '青龙',
        'icon': '🐉',
        'module': 'strategies.qinglong',
        'func': 'run_qinglong_screen',
        'needs_db': False,
    },
    {
        'key': 'zhushenglang',
        'name': '主升浪',
        'icon': '🚀',
        'module': 'strategies.zhushenglang',
        'func': 'run_zhushenglang_screen',
        'needs_db': True,
    },
    {
        'key': 'volume_breakout',
        'name': '放量突破',
        'icon': '🔥',
        'module': 'strategies.volume_breakout',
        'func': 'run_volume_breakout_screen',
        'needs_db': False,
    },
    {
        'key': 'macd_golden_cross',
        'name': 'MACD金叉',
        'icon': '📊',
        'module': 'strategies.macd_golden_cross',
        'func': 'run_macd_golden_cross_screen',
        'needs_db': False,
    },
    {
        'key': 'liangjia_report',
        'name': '白虎V4.0',
        'icon': '🐯',
        'module': 'strategies.liangjia_report',
        'func': 'run_liangjia_report_screen',
        'needs_db': False,
    },
]


def get_strategy_meta(strategy_key: str) -> dict:
    """获取策略元数据"""
    for s in STRATEGIES:
        if s['key'] == strategy_key:
            return s
    return None


# ============================================================
# 数据就绪检测
# ============================================================

def check_data_ready(target_date=None) -> bool:
    """检测当日盘后数据是否完整（SectorFlow + StockFlow 都有当日数据）
    复用 scheduler._has_today_data 的逻辑，但支持指定日期。
    """
    if target_date is None:
        target_date = datetime.now().date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

    try:
        with get_db_session() as db:
            sector_count = db.query(SectorFlow).filter(SectorFlow.trade_date == target_date).count()
            stock_count = db.query(StockFlow).filter(StockFlow.trade_date == target_date).count()
            # 板块>30 且 个股>500 才算完整
            return sector_count > 30 and stock_count > 500
    except Exception as e:
        logger.error(f'[strategy_runner] check_data_ready error: {e}')
        return False


# ============================================================
# 候选股票池
# ============================================================

def get_candidate_stocks(db, trade_date, limit=300):
    """获取候选股票池：当日主力净流入 > 0 的股票，按主力净流入降序取前 N 只
    返回: [{'ts_code', 'name', 'sector', 'main_force_inflow'}, ...]
    """
    rows = db.query(
        StockFlow.ts_code,
        StockFlow.name,
        StockFlow.sector,
        StockFlow.main_force_inflow,
    ).filter(
        StockFlow.trade_date == trade_date,
        StockFlow.main_force_inflow > 0,
    ).order_by(
        StockFlow.main_force_inflow.desc()
    ).limit(limit).all()

    return [{
        'ts_code': r.ts_code,
        'name': r.name,
        'sector': r.sector,
        'main_force_inflow': float(r.main_force_inflow or 0),
    } for r in rows]


# ============================================================
# 防重复检查
# ============================================================

def has_run_today(strategy_key: str, target_date) -> bool:
    """检查今日该策略是否已成功跑过"""
    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
    with get_db_session() as db:
        log = db.query(StrategyRunLog).filter(
            StrategyRunLog.trade_date == target_date,
            StrategyRunLog.strategy_key == strategy_key,
            StrategyRunLog.status == 'success',
        ).first()
        return log is not None


# ============================================================
# 单策略运行
# ============================================================

def run_single_strategy(strategy_key: str, trade_date=None) -> dict:
    """运行单个策略扫描，结果落库，返回运行统计
    返回: {'strategy_key', 'strategy_name', 'status', 'hit_count', 'duration_seconds', 'error'}
    """
    meta = get_strategy_meta(strategy_key)
    if not meta:
        return {'strategy_key': strategy_key, 'status': 'failed', 'error': 'unknown strategy'}

    if trade_date is None:
        trade_date = datetime.now().date()
    elif isinstance(trade_date, str):
        trade_date = datetime.strptime(trade_date, '%Y-%m-%d').date()

    # 防重复
    if has_run_today(strategy_key, trade_date):
        return {
            'strategy_key': strategy_key,
            'strategy_name': meta['name'],
            'status': 'skipped',
            'message': f'{trade_date} 已跑过，跳过',
        }

    started_at = datetime.now()
    t0 = time.time()
    logger.info(f'[strategy_runner] === {meta["name"]}({strategy_key}) 开始 {started_at} ===')

    with get_db_session() as db:
        result = {
        'strategy_key': strategy_key,
        'strategy_name': meta['name'],
        'status': 'running',
        'started_at': started_at,
    }

    # 写入 running 状态的 log（占位，防并发）
    run_log = StrategyRunLog(
        trade_date=trade_date,
        strategy_key=strategy_key,
        strategy_name=meta['name'],
        started_at=started_at,
        status='running',
    )
    try:
        # 先删旧的（如果有 failed/running 的残留）
        db.query(StrategyRunLog).filter(
            StrategyRunLog.trade_date == trade_date,
            StrategyRunLog.strategy_key == strategy_key,
        ).delete()
        db.add(run_log)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f'[strategy_runner] write running log error: {e}')

    try:
        # 1. 获取候选池
        candidates = get_candidate_stocks(db, trade_date, limit=300)
        stock_list = [c['ts_code'] for c in candidates]
        name_map = {c['ts_code']: c['name'] for c in candidates}
        sector_map = {c['ts_code']: c['sector'] for c in candidates}
        logger.info(f'[strategy_runner] {meta["name"]}: {len(stock_list)} candidates')

        if not stock_list:
            raise Exception('无候选股票（StockFlow 无当日数据）')

        # 2. 动态导入并调用策略
        import importlib
        mod = importlib.import_module(meta['module'])
        screen_func = getattr(mod, meta['func'])

        if meta['needs_db']:
            hits = screen_func(stock_list, trade_date.strftime('%Y-%m-%d'), db=db)
        else:
            hits = screen_func(stock_list, trade_date.strftime('%Y-%m-%d'))

        # 3. 落库（先删当日该策略的旧结果，再插新结果）
        db.query(StrategyResult).filter(
            StrategyResult.trade_date == trade_date,
            StrategyResult.strategy_key == strategy_key,
        ).delete()

        for h in hits:
            ts_code = h.get('ts_code', '')
            # 构造 detail_json（保留所有指标字段）
            detail = {k: v for k, v in h.items() if k not in ('ts_code', 'strategy')}
            # Decimal 安全转换
            for k, v in detail.items():
                if isinstance(v, Decimal):
                    detail[k] = float(v)
            scores = h.get('scores', {})
            if not isinstance(scores, dict):
                scores = {}

            row = StrategyResult(
                trade_date=trade_date,
                ts_code=ts_code,
                strategy_key=strategy_key,
                strategy_name=meta['name'],
                name=name_map.get(ts_code, ''),
                sector=sector_map.get(ts_code, ''),
                score=float(h.get('score', 0)),
                scores_json=json.dumps(scores, ensure_ascii=False),
                detail_json=json.dumps(detail, ensure_ascii=False, default=str),
                exit_signal=h.get('exit_signal'),
            )
            db.add(row)

        # 4. 更新 run_log 为 success
        finished_at = datetime.now()
        duration = time.time() - t0
        run_log.finished_at = finished_at
        run_log.duration_seconds = round(duration, 2)
        run_log.candidate_count = len(stock_list)
        run_log.hit_count = len(hits)
        run_log.status = 'success'
        db.commit()

        result.update({
            'status': 'success',
            'hit_count': len(hits),
            'candidate_count': len(stock_list),
            'duration_seconds': round(duration, 2),
            'finished_at': finished_at,
        })
        logger.info(f'[strategy_runner] {meta["name"]}: {len(hits)} hits in {duration:.1f}s')

    except Exception as e:
        import traceback
        err = traceback.format_exc()
        logger.error(f'[strategy_runner] {meta["name"]} error: {e}')
        logger.error(err)
        db.rollback()
        finished_at = datetime.now()
        duration = time.time() - t0
        run_log.finished_at = finished_at
        run_log.duration_seconds = round(duration, 2)
        run_log.status = 'failed'
        run_log.error_msg = str(e)[:2000]
        try:
            db.commit()
        except Exception:
            logger.warning(f"function db error", exc_info=True)
            db.rollback()

        result.update({
            'status': 'failed',
            'error': str(e),
            'duration_seconds': round(duration, 2),
            'finished_at': finished_at,
        })
    finally:
        db.close()

    return result


# ============================================================
# 全量运行
# ============================================================

def run_all_strategies(trade_date=None) -> dict:
    """运行所有策略，返回每个策略的运行统计
    返回: {'trade_date', 'results': [{strategy_key, status, ...}], 'total_hits'}
    """
    if trade_date is None:
        trade_date = datetime.now().date()
    elif isinstance(trade_date, str):
        trade_date = datetime.strptime(trade_date, '%Y-%m-%d').date()

    logger.info(f'[strategy_runner] ===== 开始全量策略扫描 {trade_date} =====')

    # 数据就绪检查
    if not check_data_ready(trade_date):
        msg = f'{trade_date} 盘后数据未就绪，跳过策略扫描'
        logger.info(f'[strategy_runner] {msg}')
        return {
            'trade_date': str(trade_date),
            'status': 'data_not_ready',
            'message': msg,
            'results': [],
        }

    results = []
    total_hits = 0
    for s in STRATEGIES:
        r = run_single_strategy(s['key'], trade_date)
        results.append(r)
        if r.get('status') == 'success':
            total_hits += r.get('hit_count', 0)

    logger.info(f'[strategy_runner] ===== 全量扫描完成，总命中 {total_hits} =====')
    return {
        'trade_date': str(trade_date),
        'status': 'completed',
        'results': results,
        'total_hits': total_hits,
    }


# ============================================================
# 手动触发（命令行）
# ============================================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='策略扫描服务')
    parser.add_argument('--date', help='指定交易日期 YYYY-MM-DD（默认今天）')
    parser.add_argument('--strategy', help='只跑单个策略 key（默认全部）')
    args = parser.parse_args()

    if args.strategy:
        r = run_single_strategy(args.strategy, args.date)
        logger.info(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        r = run_all_strategies(args.date)
        logger.info(json.dumps(r, ensure_ascii=False, indent=2, default=str))
