"""数据库只读的中线趋势候选策略（纸面决策）。"""
from collections import defaultdict
from datetime import date, datetime
import json
import logging

from sqlalchemy import func

from db.models import SectorFlow, StockDailyKline, StockFlow, StrategyResult, StrategyRunLog
from db.session import get_db_session

logger = logging.getLogger(__name__)

STRATEGY_KEY = 'medium_trend_v1'
STRATEGY_NAME = '中线趋势V1'
RULE_VERSION = '2026-08-24'
MIN_HISTORY_BARS = 80
MAX_POSITIONS = 5
TARGET_POSITION_PCT = 20.0


def _mean(values):
    return sum(values) / len(values) if values else None


def _evaluate_bars(bars: list[dict], sector_change_pct: float | None = None) -> dict | None:
    """仅从已完成日K计算中线趋势资格；不足历史直接返回 None。"""
    if len(bars) < MIN_HISTORY_BARS:
        return None
    closes = [float(bar['close']) for bar in bars if bar.get('close') is not None]
    if len(closes) != len(bars) or min(closes) <= 0:
        return None

    close = closes[-1]
    ma20 = _mean(closes[-20:])
    ma60 = _mean(closes[-60:])
    ma60_10d_ago = _mean(closes[-70:-10])
    ret20 = (close / closes[-21] - 1) * 100
    ma60_slope = (ma60 / ma60_10d_ago - 1) * 100 if ma60_10d_ago else None
    peak20 = max(closes[-20:])
    drawdown20 = (close / peak20 - 1) * 100

    structure_ok = close > ma20 > ma60
    slope_ok = ma60_slope is not None and ma60_slope > 0
    momentum_ok = 0 < ret20 <= 25
    drawdown_ok = drawdown20 >= -8
    eligible = structure_ok and slope_ok and momentum_ok and drawdown_ok

    score = 0.0
    score += 35 if structure_ok else 0
    score += min(max(ma60_slope or 0, 0), 5) / 5 * 20
    score += 20 if 2 <= ret20 <= 15 else 12 if 0 < ret20 <= 25 else 0
    score += min(max(drawdown20 + 8, 0), 8) / 8 * 15
    score += 10 if sector_change_pct is not None and sector_change_pct > 0 else 5 if sector_change_pct is not None else 0

    reasons = []
    if structure_ok:
        reasons.append('收盘价>MA20>MA60')
    if slope_ok:
        reasons.append(f'MA60十日斜率 {ma60_slope:+.2f}%')
    if momentum_ok:
        reasons.append(f'20日动量 {ret20:+.2f}%')
    if drawdown_ok:
        reasons.append(f'距20日高点 {drawdown20:+.2f}%')
    if sector_change_pct is not None and sector_change_pct > 0:
        reasons.append(f'板块当日涨幅 {sector_change_pct:+.2f}%')

    return {
        'eligible': eligible,
        'score': round(score, 2),
        'close': round(close, 2),
        'ma20': round(ma20, 2),
        'ma60': round(ma60, 2),
        'ma60_slope_10d_pct': round(ma60_slope, 2) if ma60_slope is not None else None,
        'return_20d_pct': round(ret20, 2),
        'drawdown_20d_pct': round(drawdown20, 2),
        'reasons': reasons,
        'gates': {
            'structure': structure_ok,
            'ma60_slope': slope_ok,
            'momentum_20d': momentum_ok,
            'drawdown_20d': drawdown_ok,
        },
    }


def run_medium_term_snapshot(target_date: date | str | None = None) -> dict:
    """基于本地已完成交易日生成并持久化中线候选；不读取网络、不发送订单。"""
    started = datetime.now()
    with get_db_session() as db:
        if target_date is None:
            target_date = db.query(func.max(StockFlow.trade_date)).scalar()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
        if target_date is None:
            return {'status': 'MISSING', 'source': 'database', 'message': '没有已完成的个股资金流交易日'}

        run = db.query(StrategyRunLog).filter_by(
            trade_date=target_date, strategy_key=STRATEGY_KEY,
        ).first()
        if run is None:
            run = StrategyRunLog(
                trade_date=target_date, strategy_key=STRATEGY_KEY,
                strategy_name=STRATEGY_NAME, started_at=started,
            )
            db.add(run)
        else:
            run.started_at = started
            run.finished_at = None
            run.status = 'running'
            run.error_msg = None

        stocks = db.query(
            StockFlow.ts_code, StockFlow.name, StockFlow.sector,
        ).filter(
            StockFlow.trade_date == target_date,
            StockFlow.ts_code.isnot(None),
        ).all()
        codes = [row.ts_code for row in stocks]
        sector_changes = {
            row.sector: float(row.avg_chg)
            for row in db.query(SectorFlow.sector, SectorFlow.avg_chg).filter(
                SectorFlow.trade_date == target_date,
                SectorFlow.sector.isnot(None),
                SectorFlow.avg_chg.isnot(None),
            ).all()
        }
        if not codes:
            run.status = 'failed'
            run.error_msg = 'target trade date has no StockFlow rows'
            run.finished_at = datetime.now()
            db.commit()
            return {'status': 'MISSING', 'source': 'database', 'message': '目标交易日没有个股资金流'}

        ranked = db.query(
            StockDailyKline.ts_code.label('ts_code'),
            StockDailyKline.trade_date.label('trade_date'),
            StockDailyKline.close.label('close'),
            func.row_number().over(
                partition_by=StockDailyKline.ts_code,
                order_by=StockDailyKline.trade_date.desc(),
            ).label('rn'),
        ).filter(
            StockDailyKline.ts_code.in_(codes),
            StockDailyKline.trade_date <= target_date,
            StockDailyKline.close.isnot(None),
        ).subquery()
        rows = db.query(ranked).filter(ranked.c.rn <= MIN_HISTORY_BARS).all()
        bars_by_code = defaultdict(list)
        for row in rows:
            bars_by_code[str(row.ts_code)].append({
                'date': row.trade_date,
                'close': float(row.close),
            })
        for bars in bars_by_code.values():
            bars.sort(key=lambda row: row['date'])

        all_candidates = []
        for row in stocks:
            metrics = _evaluate_bars(
                bars_by_code.get(str(row.ts_code), []),
                sector_changes.get(row.sector or ''),
            )
            if not metrics or not metrics['eligible']:
                continue
            all_candidates.append({
                'ts_code': str(row.ts_code),
                'name': row.name or str(row.ts_code).split('.')[0],
                'sector': row.sector or '',
                **metrics,
            })

        all_candidates.sort(key=lambda item: (-item['score'], item['ts_code']))
        selected, seen_sectors = [], set()
        for candidate in all_candidates:
            sector = candidate['sector']
            if sector and sector in seen_sectors:
                continue
            selected.append(candidate)
            if sector:
                seen_sectors.add(sector)
            if len(selected) == MAX_POSITIONS:
                break

        existing = {
            row.ts_code: row for row in db.query(StrategyResult).filter_by(
                trade_date=target_date, strategy_key=STRATEGY_KEY,
            ).all()
        }
        selected_codes = {row['ts_code'] for row in selected}
        for stale in (row for code, row in existing.items() if code not in selected_codes):
            db.delete(stale)
        for rank, candidate in enumerate(selected, start=1):
            detail = {
                'rank': rank,
                'rule_version': RULE_VERSION,
                'holding_horizon_sessions': [20, 60],
                'target_position_pct': TARGET_POSITION_PCT,
                'source': 'database',
                **candidate,
            }
            result = existing.get(candidate['ts_code'])
            if result is None:
                result = StrategyResult(
                    trade_date=target_date, ts_code=candidate['ts_code'],
                    strategy_key=STRATEGY_KEY, strategy_name=STRATEGY_NAME,
                )
                db.add(result)
            result.name = candidate['name']
            result.sector = candidate['sector']
            result.score = candidate['score']
            result.scores_json = json.dumps(candidate['gates'], ensure_ascii=False)
            result.detail_json = json.dumps(detail, ensure_ascii=False, default=str)
            result.exit_signal = 'MA60收盘跌破或20日回撤超过8%'

        run.finished_at = datetime.now()
        run.duration_seconds = (run.finished_at - started).total_seconds()
        run.candidate_count = len(stocks)
        run.hit_count = len(selected)
        run.status = 'success'
        run.error_msg = None
        db.commit()

    return {
        'status': 'READY',
        'source': 'database',
        'trade_date': target_date.isoformat(),
        'data_as_of': target_date.isoformat(),
        'rule_version': RULE_VERSION,
        'coverage': {'universe': len(stocks), 'eligible': len(all_candidates), 'selected': len(selected)},
        'target_positions': selected,
        'cash_target_pct': max(0.0, 100 - len(selected) * TARGET_POSITION_PCT),
        'message': '纸面中线候选；不连接自动下单。',
    }
