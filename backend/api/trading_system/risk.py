"""GET /api/trading-system/risk/status — 当前风控状态"""
import json
import logging
from datetime import datetime
from fastapi import APIRouter
from db.session import get_db_session
from db.models import TradingSignalDaily, AutoTradeConfig
from services.trading_system.risk_engine import SENTIMENT_TOTAL_CAP

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/trading-system/risk/status")
def get_risk_status():
    """当前风控状态：总仓位/上限/高位股/警告"""
    today = datetime.now().date()

    with get_db_session() as db:
        # 风控配置
        config_row = db.query(AutoTradeConfig).filter_by(id=1).first()
        config = {}
        if config_row:
            config = {
                'enabled': config_row.enabled,
                'single_position_pct': float(config_row.single_position_pct or 10),
                'max_positions': config_row.max_positions or 10,
                'stop_loss_pct': float(config_row.stop_loss_pct or -5),
                'take_profit_pct': float(config_row.take_profit_pct or 15),
            }

        # 当日信号
        rows = db.query(TradingSignalDaily).filter(
            TradingSignalDaily.trade_date == today
        ).all()

        if not rows:
            return {
                'total_position_pct': 0,
                'total_cap_pct': 40,
                'sentiment': '中性',
                'single_risk_pct': 2.0,
                'high_position_stocks': [],
                'warnings': ['暂无当日信号数据'],
                'config': config,
            }

        # 情绪 → 总仓位上限
        sentiments = [r.sentiment_stage for r in rows if r.sentiment_stage]
        dominant_sentiment = max(set(sentiments), key=sentiments.count) if sentiments else '中性'
        total_cap = SENTIMENT_TOTAL_CAP.get(dominant_sentiment, 40.0)

        # 当前总仓位
        buyable = [r for r in rows if r.signal_4 in ('STRONG_BUY', 'WATCH_BUY')]
        total_position = sum(float(r.position_pct or 0) for r in buyable)

        # 高位股
        high_pos = []
        for r in rows:
            if r.is_high_position:
                high_pos.append({
                    'code': r.ts_code,
                    'name': r.name,
                    'position_pct': float(r.position_pct or 0),
                })

        # 警告
        warnings = []
        if total_position >= total_cap:
            warnings.append(f'总仓位已达 {total_cap}% 上限')
        if high_pos:
            warnings.append(f'{len(high_pos)} 只高位股仓位受限')
        if dominant_sentiment in ('恐慌', '谨慎', '狂热'):
            warnings.append(f'情绪{dominant_sentiment}，总仓位上限降至 {total_cap}%')

        return {
            'total_position_pct': round(total_position, 2),
            'total_cap_pct': total_cap,
            'sentiment': dominant_sentiment,
            'single_risk_pct': 2.0,
            'high_position_stocks': high_pos,
            'warnings': warnings,
            'config': config,
        }
