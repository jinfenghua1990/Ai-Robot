"""4.0 信号盘后预计算
WatchlistSignalDaily → 4.0 引擎（signal/position/risk）→ TradingSignalDaily
依赖：watchlist_signal_runner 先跑完（数据源）
"""
import sys
import os
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import get_db_session
from db.models import WatchlistSignalDaily, TradingSignalDaily
from analyzers.stock_scores import (
    calc_sentiment, calc_risk, calc_momentum, calc_main_force,
    calc_technical, calc_sector_resonance,
)
from services.signal_builder import build_signal_from_precomputed
from .signal_engine import calc_final_score, classify_signal_4
from .position_engine import calc_dynamic_position
from .risk_engine import assess_portfolio_risk, is_high_position_stock

logger = logging.getLogger(__name__)


def has_run_today(target_date=None) -> bool:
    """检查当日 4.0 信号是否已预计算"""
    if target_date is None:
        target_date = datetime.now().date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()
    with get_db_session() as db:
        count = db.query(TradingSignalDaily).filter(
            TradingSignalDaily.trade_date == target_date
        ).count()
        return count > 0


async def _process_one(row, db) -> dict:
    """处理单只股票：预计算行 → 4.0 信号"""
    code = row.ts_code.split('.')[0] if '.' in row.ts_code else row.ts_code
    name = row.name or ''

    # 1. 构建 base signal（含 quote/sectorTrend/marketState/bsSignal/qualityStatus/lifecycleStage）
    signal = await build_signal_from_precomputed(code, name, row, db=db)

    # 2. 补充 6 维评分（build_signal_from_precomputed 不含这些）
    quote = signal.get('quote')
    sector_trend = signal.get('sectorTrend') or {}
    ms_data = signal.get('marketState') or {}
    features = ms_data.get('features') or {}
    bp_data = signal.get('buyPower') or {}

    signal['sentiment'] = calc_sentiment(quote, sector_trend, features)
    signal['risk'] = calc_risk(features, bp_data, None)
    signal['momentum'] = calc_momentum(sector_trend, features)
    signal['mainForce'] = calc_main_force(quote, features, sector_trend)
    signal['technical'] = calc_technical(features)
    signal['sectorResonance'] = calc_sector_resonance(sector_trend, features)

    # 3. 4.0 信号分级
    final_score, score_detail = calc_final_score(signal)
    classification = classify_signal_4(signal, final_score)

    # 4. 动态仓位
    position = calc_dynamic_position(signal, classification['signal_4'], final_score)

    # 5. 高位股检测
    is_high, high_reason = is_high_position_stock(signal)

    return {
        'ts_code': row.ts_code,
        'name': name,
        'sector': row.sector or '',
        'signal_raw': signal,
        'signal_4': classification['signal_4'],
        'signal_label': classification['label'],
        'signal_color': classification['color'],
        'final_score': final_score,
        'score_detail': score_detail,
        'reasons': classification['reasons'],
        'position_pct': position['position_pct'],
        'position_amount': position['position_amount'],
        'stop_loss_pct': position['stop_loss_pct'],
        'take_profit_pct': position['take_profit_pct'],
        'atr_14': position['atr_14'],
        'risk_per_share': position['risk_per_share'],
        'market_state': ms_data.get('market_state', ''),
        'sentiment_stage': (signal.get('sentiment') or {}).get('stage', '中性'),
        'is_high_position': is_high,
        'high_reason': high_reason,
        'watchlist_signal_id': row.id,
    }


async def _compute_async(target_date_str: str) -> List[dict]:
    """异步计算当日所有候选股票的 4.0 信号"""
    with get_db_session() as db:
        rows = db.query(WatchlistSignalDaily).filter(
            WatchlistSignalDaily.trade_date == target_date_str
        ).all()

        if not rows:
            logger.info(f'[trading_system] 无 {target_date_str} 的 WatchlistSignalDaily 数据')
            return []

        logger.info(f'[trading_system] 处理 {len(rows)} 只股票')

        # 分批并发（每批 20 只，避免新浪限流）
        all_results = []
        batch_size = 20
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            tasks = [_process_one(row, db) for row in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if not isinstance(r, Exception) and r is not None:
                    all_results.append(r)
                elif isinstance(r, Exception):
                    logger.error(f'[trading_system] 处理失败: {r}')

        # 6. 组合风控
        market_sentiment = '中性'
        if all_results:
            # 取多数情绪
            sentiments = [r['sentiment_stage'] for r in all_results]
            market_sentiment = max(set(sentiments), key=sentiments.count) if sentiments else '中性'

        risk_result = assess_portfolio_risk(all_results, market_sentiment)

        # 7. 合并风控调整到结果
        adjusted_map = {s['ts_code']: s for s in risk_result['adjusted_signals']}
        for r in all_results:
            adj = adjusted_map.get(r['ts_code'])
            if adj:
                r['position_pct'] = adj.get('position_pct', r['position_pct'])
                r['position_amount'] = adj.get('position_amount', r['position_amount'])
                r['risk_status'] = adj.get('risk_status', 'ok')
                r['risk_reasons'] = adj.get('risk_reasons', [])
            else:
                r['risk_status'] = 'ok'
                r['risk_reasons'] = []

        # 存入 risk_summary 供日志
        logger.info(f'[trading_system] 总仓位 {risk_result["total_position_pct"]}% / '
                     f'上限 {risk_result["total_cap_pct"]}% / '
                     f'可买 {risk_result["buyable_count"]} 只 / '
                     f'警告 {len(risk_result["warnings"])} 条')

        return all_results


def compute_for_date(target_date=None) -> Dict:
    """盘后预计算入口（同步，供 scheduler 调用）
    返回: {'date': str, 'count': int, 'signals': list}
    """
    if target_date is None:
        target_date = datetime.now().date()
    elif isinstance(target_date, str):
        target_date = datetime.strptime(target_date, '%Y-%m-%d').date()

    target_date_str = target_date.strftime('%Y-%m-%d')

    # 检查依赖
    from services.watchlist_signal_runner import has_run_today as wl_done
    if not wl_done(target_date):
        logger.warning(f'[trading_system] WatchlistSignalDaily 未跑完，跳过 4.0 计算')
        return {'date': target_date_str, 'count': 0, 'error': 'watchlist_signal not ready'}

    # 检查是否已跑
    if has_run_today(target_date):
        logger.info(f'[trading_system] {target_date_str} 已预计算，跳过')
        return {'date': target_date_str, 'count': 0, 'error': 'already computed'}

    # 计算
    results = asyncio.run(_compute_async(target_date_str))

    # 落库
    with get_db_session() as db:
        for r in results:
            row = TradingSignalDaily(
                trade_date=target_date,
                ts_code=r['ts_code'],
                name=r['name'],
                sector=r['sector'],
                signal_4=r['signal_4'],
                signal_label=r['signal_label'],
                signal_color=r['signal_color'],
                final_score=r['final_score'],
                score_detail_json=json.dumps(r['score_detail'], ensure_ascii=False),
                position_pct=r['position_pct'],
                position_amount=r['position_amount'],
                stop_loss_pct=r['stop_loss_pct'],
                take_profit_pct=r['take_profit_pct'],
                atr_14=r['atr_14'],
                risk_per_share=r['risk_per_share'],
                risk_status=r['risk_status'],
                risk_reasons_json=json.dumps(r.get('risk_reasons', []), ensure_ascii=False),
                market_state=r['market_state'],
                sentiment_stage=r['sentiment_stage'],
                is_high_position=r['is_high_position'],
                watchlist_signal_id=r.get('watchlist_signal_id'),
                reasons_json=json.dumps(r['reasons'], ensure_ascii=False),
            )
            db.merge(row)
        db.commit()

    # 统计
    summary = {
        'strong_buy': sum(1 for r in results if r['signal_4'] == 'STRONG_BUY'),
        'watch_buy': sum(1 for r in results if r['signal_4'] == 'WATCH_BUY'),
        'forbid': sum(1 for r in results if r['signal_4'] == 'FORBID'),
    }
    logger.info(f'[trading_system] {target_date_str} 完成: '
                f'强买{summary["strong_buy"]} 观察买{summary["watch_buy"]} 禁止{summary["forbid"]}')

    return {'date': target_date_str, 'count': len(results), 'summary': summary, 'signals': results}
