"""GET /api/trading-system/daily-report — 当日 4.0 交易信号日报"""
import json
import logging
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Query
from db.session import get_db_session
from db.models import TradingSignalDaily
from services.trading_system.runner import compute_for_date, has_run_today

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/trading-system/daily-report")
def get_daily_report(date: Optional[str] = Query(None, description="日期 YYYY-MM-DD，默认今天")):
    """当日 4.0 交易信号日报
    返回：市场总览 + 信号汇总 + 信号列表 + 风控警告
    """
    target_date_str = date or datetime.now().strftime('%Y-%m-%d')
    target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()

    with get_db_session() as db:
        rows = db.query(TradingSignalDaily).filter(
            TradingSignalDaily.trade_date == target_date
        ).order_by(
            TradingSignalDaily.signal_4 == 'STRONG_BUY',
            TradingSignalDaily.final_score.desc(),
        ).all()

        # 无数据时尝试现场计算
        if not rows:
            logger.info(f'[daily-report] 无 {target_date_str} 数据，尝试现场计算')
            try:
                result = compute_for_date(target_date)
                if result.get('count', 0) > 0:
                    rows = db.query(TradingSignalDaily).filter(
                        TradingSignalDaily.trade_date == target_date
                    ).order_by(
                        TradingSignalDaily.signal_4 == 'STRONG_BUY',
                        TradingSignalDaily.final_score.desc(),
                    ).all()
            except Exception as e:
                logger.error(f'[daily-report] compute failed: {e}')

        if not rows:
            return {
                'date': target_date_str,
                'market_overview': None,
                'summary': {'strong_buy': 0, 'watch_buy': 0, 'forbid': 0, 'total': 0},
                'signals': [],
                'risk_warnings': [],
                'message': '暂无数据，请等待盘后预计算',
            }

        # 构建信号列表
        signals = []
        for row in rows:
            signals.append({
                'ts_code': row.ts_code,
                'name': row.name,
                'sector': row.sector,
                'signal_4': row.signal_4,
                'signal_label': row.signal_label,
                'signal_color': row.signal_color,
                'final_score': float(row.final_score) if row.final_score else 0,
                'score_detail': json.loads(row.score_detail_json or '{}'),
                'position_pct': float(row.position_pct) if row.position_pct else 0,
                'position_amount': float(row.position_amount) if row.position_amount else 0,
                'stop_loss_pct': float(row.stop_loss_pct) if row.stop_loss_pct else 0,
                'take_profit_pct': float(row.take_profit_pct) if row.take_profit_pct else 0,
                'atr_14': float(row.atr_14) if row.atr_14 else 0,
                'risk_status': row.risk_status,
                'risk_reasons': json.loads(row.risk_reasons_json or '[]'),
                'market_state': row.market_state,
                'sentiment_stage': row.sentiment_stage,
                'is_high_position': row.is_high_position,
                'reasons': json.loads(row.reasons_json or '[]'),
            })

        # 市场总览（取多数票）
        market_states = [s['market_state'] for s in signals if s['market_state']]
        sentiments = [s['sentiment_stage'] for s in signals if s['sentiment_stage']]
        dominant_market = max(set(market_states), key=market_states.count) if market_states else 'PENDING'
        dominant_sentiment = max(set(sentiments), key=sentiments.count) if sentiments else '中性'

        # 总仓位建议
        from services.trading_system.risk_engine import SENTIMENT_TOTAL_CAP
        total_cap = SENTIMENT_TOTAL_CAP.get(dominant_sentiment, 40.0)
        total_position = sum(s['position_pct'] for s in signals if s['signal_4'] in ('STRONG_BUY', 'WATCH_BUY'))

        # 汇总
        summary = {
            'strong_buy': sum(1 for s in signals if s['signal_4'] == 'STRONG_BUY'),
            'watch_buy': sum(1 for s in signals if s['signal_4'] == 'WATCH_BUY'),
            'forbid': sum(1 for s in signals if s['signal_4'] == 'FORBID'),
            'total': len(signals),
        }

        # 风控警告
        warnings = []
        if total_position >= total_cap:
            warnings.append(f'总仓位已达 {total_cap}% 上限')
        high_pos = [s for s in signals if s['is_high_position']]
        if high_pos:
            warnings.append(f'{len(high_pos)} 只高位股仓位受限')

        return {
            'date': target_date_str,
            'market_overview': {
                'market_state': dominant_market,
                'sentiment': dominant_sentiment,
                'total_position_suggestion': round(total_position, 2),
                'total_cap_pct': total_cap,
            },
            'summary': summary,
            'signals': signals,
            'risk_warnings': warnings,
        }
