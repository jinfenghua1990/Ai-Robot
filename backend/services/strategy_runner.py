"""
策略扫描服务
- 数据就绪检测（复用 scheduler._has_today_data 逻辑）
- 每日盘后跑 5 个策略，结果落 StrategyResult 表
- 每次运行写 StrategyRunLog，用于健康检查
- 防重复跑：同 trade_date × strategy_key 只跑一次（唯一约束）

已废弃（2026-07-15 合并审计）：
  baihu_v26 → 被 baihu_v30 完全覆盖
  volume_breakout → 被合并进 liangjia_report breakout 评分维度
  zhushenglang → 被合并进 liangjia_report trend 评分维度（主力连续流入）
  wave_band → buy 被 V4.0+V3 覆盖，sell 独立为 risk_exit 通用模块
"""
import sys
import os
import json
import time
from datetime import datetime, date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func
from db.session import get_db_session
from db.models import StrategyResult, StrategyRunLog, StockFlow, SectorFlow, StockDailyKline
from services.indicators import calc_supertrend
import logging
logger = logging.getLogger(__name__)


# ============================================================
# 策略注册表（8→5 合并后保留 5 个策略）
# ============================================================

STRATEGIES = [
    {
        'key': 'baihu_v30',
        'name': '白虎V3.0',
        'icon': '🐯',
        'module': 'strategies.baihu_v30',
        'func': 'run_baihu_v30_screen',
        'needs_db': False,
    },
    {
        'key': 'liangjia_report',
        'name': '朱雀V3.0',
        'icon': '🐯',
        'module': 'strategies.liangjia_report',
        'func': 'run_liangjia_report_screen',
        'needs_db': True,  # 需要查 StockFlow 获取主力资金数据
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
        'key': 'macd_golden_cross',
        'name': 'MACD金叉',
        'icon': '📊',
        'module': 'strategies.macd_golden_cross',
        'func': 'run_macd_golden_cross_screen',
        'needs_db': False,
    },
    {
        'key': 'risk_exit',
        'name': '风险退出',
        'icon': '🛡️',
        'module': 'strategies.risk_exit',
        'func': 'run_risk_exit_screen',
        'needs_db': False,
    },
    {
        'key': 'rsi_bounce',
        'name': 'RSI超卖反弹',
        'icon': '🔄',
        'module': 'strategies.rsi_bounce',
        'func': 'run_rsi_bounce_screen',
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


def is_market_healthy(db, target_date) -> bool:
    """市场宽度过滤：上涨股票占比 > 40% 才执行买入策略
    用 StockDailyKline.pct_chg 计算当日上涨比例，避免在普跌日做多。
    """
    try:
        total = db.query(StockDailyKline).filter(
            StockDailyKline.trade_date == target_date
        ).count()
        up = db.query(StockDailyKline).filter(
            StockDailyKline.trade_date == target_date,
            StockDailyKline.pct_chg > 0
        ).count()
        healthy = (up / total) > 0.4 if total > 0 else False
        if not healthy:
            logger.info(f'[strategy_runner] 市场宽度不足({up}/{total}={(up/total)*100:.0f}%)，跳过买入策略')
        return healthy
    except Exception as e:
        logger.error(f'[strategy_runner] is_market_healthy error: {e}')
        return True  # 兜底：数据异常时放行，避免漏掉信号


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
        # 市场宽度过滤：大盘弱势时只跑风险退出，跳过买入策略
        if s['key'] != 'risk_exit':
            with get_db_session() as db:
                if not is_market_healthy(db, trade_date):
                    results.append({'strategy_key': s['key'], 'strategy_name': s['name'],
                                    'status': 'skipped', 'message': '市场宽度不足(上涨<40%)，跳过'})
                    continue
        r = run_single_strategy(s['key'], trade_date)
        results.append(r)
        if r.get('status') == 'success':
            total_hits += r.get('hit_count', 0)

    logger.info(f'[strategy_runner] ===== 全量扫描完成，总命中 {total_hits} =====')

    # 自动将 ≥3 共振股加入跟踪列表（StockTracker）
    resonance_result = _auto_add_resonance_to_tracker(trade_date)

    return {
        'trade_date': str(trade_date),
        'status': 'completed',
        'results': results,
        'total_hits': total_hits,
        'resonance_added': resonance_result,
    }


def _extract_v4_pattern(row):
    """从量价报告（liangjia_report）的 detail/scores 中提取 pattern 字段"""
    try:
        if row.detail_json:
            detail = json.loads(row.detail_json) if isinstance(row.detail_json, str) else row.detail_json
            return detail.get('pattern')
    except Exception:
        pass
    try:
        if row.scores_json:
            scores = json.loads(row.scores_json) if isinstance(row.scores_json, str) else row.scores_json
            return scores.get('pattern')
    except Exception:
        pass
    return None


_V4_PATTERN_META = {
    'pullback': {'name': '朱雀V3.0回踩'},
    'breakout': {'name': '朱雀V3.0突破'},
    'trend': {'name': '朱雀V3.0趋势'},
    'repair': {'name': '朱雀V3.0修复'},
}


def _get_current_bs_signal(db, stock_code: str) -> int:
    """获取股票当前 SuperTrend BS 信号
    
    Returns:
        1 = B (多头/买入), -1 = S (空头/卖出), 0 = 数据不足
    """
    try:
        ts_code = f"{stock_code}.{'SH' if stock_code.startswith(('6','9','68')) else 'SZ' if not stock_code.startswith('8') else 'BJ'}"
        rows = db.query(StockDailyKline).filter(
            StockDailyKline.ts_code == ts_code
        ).order_by(StockDailyKline.trade_date.desc()).limit(150).all()
        if len(rows) < 30:
            return 0
        closes = [float(r.close) for r in reversed(rows)]
        highs = [float(r.high) for r in reversed(rows)]
        lows = [float(r.low) for r in reversed(rows)]
        _, _, trend, _ = calc_supertrend(highs, lows, closes, period=10, multiplier=1.0)
        return trend[-1] if trend else 0
    except Exception:
        return 0


def _auto_add_resonance_to_tracker(trade_date) -> dict:
    """策略扫描完成后，自动将 ≥3 共振股加入跟踪列表（StockTracker）

    逻辑：
    - 查当日 StrategyResult，按 ts_code 聚合共振数（与共振页面口径一致）
    - 风险退出策略不参与共振；朱雀 V3.0 按子形态拆分为独立维度
    - 共振 ≥3 的股票自动加入跟踪，note 标注「共振选股」+ 共振维度
    - 已在跟踪中的：更新 note 为最新共振信息
    - 不再 ≥3 共振的旧共振跟踪股：软删除（active=False），note 标注退出原因
    """
    from db.models import StrategyResult, StockTracker, StockDailyKline
    from collections import defaultdict

    trade_date_str = str(trade_date) if not isinstance(trade_date, str) else trade_date

    with get_db_session() as db:
        # 1. 聚合当日共振（与 /api/strategy-resonance 口径保持一致）
        rows = db.query(StrategyResult).filter(
            StrategyResult.trade_date == trade_date_str
        ).all()
        grouped = defaultdict(list)
        name_map = {}
        for r in rows:
            name_map[r.ts_code] = r.name or ''
            # 风险退出是卖出信号，不参与共振计数
            if r.strategy_key == 'risk_exit':
                continue
            # 朱雀 V3.0 子形态拆分
            if r.strategy_key == 'liangjia_report':
                pattern = _extract_v4_pattern(r)
                if pattern in (None, 'weak'):
                    continue
                pmeta = _V4_PATTERN_META.get(pattern)
                if not pmeta:
                    continue
                grouped[r.ts_code].append(pmeta['name'])
                continue
            grouped[r.ts_code].append(r.strategy_name or r.strategy_key)

        high_resonance = {}  # {code: {name, resonance_count, strategies, note}}
        for ts_code, strategy_names in grouped.items():
            if len(strategy_names) >= 3:
                code = ts_code.split('.')[0]
                name = name_map.get(ts_code, '')
                note = f'共振选股 共振{len(strategy_names)}: {"+".join(strategy_names)}'
                high_resonance[code] = {
                    'name': name,
                    'resonance_count': len(strategy_names),
                    'strategies': strategy_names,
                    'note': note,
                }

        # 2. 加入跟踪列表（BS 信号为 S 的股票不加入）
        added = []
        updated = []
        bs_filtered = []
        for code, info in high_resonance.items():
            bs = _get_current_bs_signal(db, code)
            if bs == -1:
                bs_filtered.append(f"{info['name']}({code}) BS=S")
                continue

            existing = db.query(StockTracker).filter_by(stock_code=code, active=True).first()
            if existing:
                existing.note = info['note']
                updated.append(f"{info['name']}({code})")
            else:
                old = db.query(StockTracker).filter_by(stock_code=code, active=False).first()
                latest = db.query(StockDailyKline)\
                    .filter(StockDailyKline.ts_code.like(f"{code}%"))\
                    .order_by(StockDailyKline.trade_date.desc())\
                    .first()
                entry_date = latest.trade_date if latest else trade_date
                entry_price = latest.close if latest else 0
                if old:
                    old.active = True
                    old.entry_date = entry_date
                    old.entry_price = entry_price
                    old.stock_name = info['name']
                    old.note = info['note']
                    updated.append(f"{info['name']}({code}) 恢复跟踪")
                else:
                    db.add(StockTracker(
                        stock_code=code,
                        stock_name=info['name'],
                        entry_date=entry_date,
                        entry_price=entry_price,
                        note=info['note'],
                    ))
                    added.append(f"{info['name']}({code})")

        # 3. 清理：BS 信号已转为 S 的旧共振跟踪股 → 软删除
        # 注意：不再按「今日是否 ≥3 共振」清理，因为一旦入选就持续跟踪，直到 BS 转 S
        removed = []
        bs_removed = []
        old_resonance = db.query(StockTracker).filter(
            StockTracker.active == True,
            StockTracker.note.like('%共振选股%'),
        ).all()
        for t in old_resonance:
            bs = _get_current_bs_signal(db, t.stock_code)
            if bs == -1:
                t.active = False
                old_note = t.note or ''
                t.note = f'[BS转S] {old_note}'
                bs_removed.append(f"{t.stock_name}({t.stock_code})")

        db.commit()

    result = {
        'added': len(added),
        'updated': len(updated),
        'removed': len(removed),
        'bs_filtered': len(bs_filtered),
        'bs_removed': len(bs_removed),
        'details': {
            'added': added,
            'updated': updated,
            'removed': removed,
            'bs_filtered': bs_filtered,
            'bs_removed': bs_removed,
        }
    }
    if added or updated or removed or bs_filtered or bs_removed:
        logger.info(f'[strategy_runner] 共振跟踪自动同步: +{len(added)} ~{len(updated)} -{len(removed)} BS过滤:{len(bs_filtered)} BS转S:{len(bs_removed)}')
    return result


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
