"""
龙头趋势阶段识别器（原"生命周期"）
阶段: 观望 → 留意 → 蓄势 → 突破 → 加速 → 主升 → 分歧 → 衰退
- 涨停股：基于连板高度 + 涨幅 + 主力资金判断（突破/加速/主升/分歧/衰退）
- 非涨停股：基于主力净流入推断（观望/留意/蓄势）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
from datetime import datetime
from db.connection import get_db
from db.session import get_db_session
from db.models import LeaderLifecycle, StockFlow
from sqlalchemy import func

logger = logging.getLogger(__name__)

LIMIT_UP_THRESHOLD = 9.8  # 涨停判定阈值（%）

# 涨停股趋势阶段配置
LIMIT_UP_STAGE_CONFIG = {
    '突破': {'strength': 20, 'color': '#facc15'},
    '加速': {'strength': 40, 'color': '#fb923c'},
    '主升': {'strength': 80, 'color': '#ef4444'},
    '分歧': {'strength': 60, 'color': '#f97316'},
    '衰退': {'strength': 20, 'color': '#94a3b8'},
}

# 非涨停股趋势阶段配置（观望/留意/蓄势）
NON_LIMIT_STAGE_CONFIG = {
    '蓄势': {'strength': 60, 'color': '#38bdf8'},
    '留意': {'strength': 40, 'color': '#a78bfa'},
    '观望': {'strength': 20, 'color': '#64748b'},
}


def _to_float(value, default=0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def identify_limit_up_stage(consecutive_days, change_rate, main_force_inflow):
    """涨停股：根据连板天数、涨幅、主力资金判断趋势阶段"""
    if consecutive_days <= 1:
        return '突破'
    elif consecutive_days <= 3:
        if main_force_inflow > 0:
            return '加速'
        return '分歧'
    elif consecutive_days >= 4:
        if change_rate > 5:
            return '主升'
        elif change_rate > 0:
            return '分歧'
        else:
            return '衰退'
    return '突破'


def infer_non_limit_stage(main_force_inflow):
    """非涨停股：根据主力净流入推断趋势阶段"""
    if main_force_inflow >= 10000:
        return '蓄势'
    elif main_force_inflow >= 1000:
        return '留意'
    return '观望'


def update_lifecycle(trade_date):
    """更新指定日期所有股票的生命周期阶段"""
    try:
        with get_db_session() as db:
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d') if isinstance(trade_date, str) else trade_date

            # 获取前一交易日数据用于计算连板天数
            prev_date_row = db.query(func.max(LeaderLifecycle.trade_date)).filter(
                LeaderLifecycle.trade_date < trade_date_obj.date()
            ).scalar()
            prev_leaders = db.query(LeaderLifecycle).filter_by(trade_date=prev_date_row).all() if prev_date_row else []
            prev_map = {l.ts_code: l for l in prev_leaders}

            # 当天所有已存在的生命周期记录
            existing_leaders = {l.ts_code: l for l in db.query(LeaderLifecycle).filter_by(trade_date=trade_date).all()}

            # 当天所有个股资金流向（覆盖涨停+非涨停）
            stocks = db.query(StockFlow).filter_by(trade_date=trade_date).all()
            if not stocks:
                print(f'[lifecycle] No stock flow data for {trade_date}')
                return

            updated = 0
            created = 0
            for stock in stocks:
                ts_code = stock.ts_code
                name = stock.name
                sector = stock.sector
                change_rate = _to_float(stock.price_chg)
                main_force = _to_float(stock.main_force_inflow)
                is_limit_up = change_rate >= LIMIT_UP_THRESHOLD

                leader = existing_leaders.get(ts_code)
                if not leader:
                    leader = LeaderLifecycle(
                        trade_date=trade_date,
                        ts_code=ts_code,
                        name=name,
                        sector=sector,
                        stage='突破',
                        consecutive_days=1,
                    )
                    db.add(leader)
                    created += 1

                # 补充名称/板块（如果缺失）
                if not leader.name and name:
                    leader.name = name
                if not leader.sector and sector:
                    leader.sector = sector

                # 计算连板天数：仅涨停股累计，非涨停股重置为 1
                prev_leader = prev_map.get(ts_code)
                if is_limit_up:
                    if prev_leader and prev_leader.consecutive_days and prev_leader.consecutive_days >= 1:
                        leader.consecutive_days = prev_leader.consecutive_days + 1
                    else:
                        leader.consecutive_days = 1
                else:
                    leader.consecutive_days = 1

                # 识别阶段
                if is_limit_up:
                    stage = identify_limit_up_stage(leader.consecutive_days, change_rate, main_force)
                    leader.strength = LIMIT_UP_STAGE_CONFIG[stage]['strength']
                else:
                    stage = infer_non_limit_stage(main_force)
                    leader.strength = NON_LIMIT_STAGE_CONFIG[stage]['strength']

                leader.stage = stage
                leader.change_rate = change_rate
                updated += 1

            db.commit()
        print(f'[lifecycle] Updated {updated} stocks ({created} created) for {trade_date}')
    except Exception as e:
        db.rollback()
        logger.exception(f'[lifecycle] Error')
        return {'error': str(e)}


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    update_lifecycle(today)
