"""
龙头生命周期识别器
阶段: 启动 → 发酵 → 主升 → 分歧 → 退潮
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta
from db.connection import get_db
from db.models import LeaderLifecycle, StockFlow


STAGE_CONFIG = {
    '启动': {'strength': 20, 'color': '#3b82f6'},
    '发酵': {'strength': 40, 'color': '#eab308'},
    '主升': {'strength': 80, 'color': '#ef4444'},
    '分歧': {'strength': 60, 'color': '#f97316'},
    '退潮': {'strength': 20, 'color': '#64748b'},
}


def identify_stage(consecutive_days, change_rate, main_force_inflow):
    """
    根据连板天数、涨幅、主力资金判断生命周期阶段
    """
    if consecutive_days <= 1:
        return '启动'
    elif consecutive_days <= 3:
        if main_force_inflow > 0:
            return '发酵'
        return '分歧'
    elif consecutive_days >= 4:
        if change_rate > 5:
            return '主升'
        elif change_rate > 0:
            return '分歧'
        else:
            return '退潮'
    return '启动'


def update_lifecycle(trade_date):
    """更新指定日期所有龙头股的生命周期阶段"""
    db = next(get_db())
    try:
        leaders = db.query(LeaderLifecycle).filter_by(trade_date=trade_date).all()
        if not leaders:
            print(f'[lifecycle] No leader data for {trade_date}')
            return
        
        # 获取前一日数据用于计算连板天数
        trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d') if isinstance(trade_date, str) else trade_date
        prev_date = (trade_date_obj - timedelta(days=1)).strftime('%Y-%m-%d')
        prev_leaders = db.query(LeaderLifecycle).filter_by(trade_date=prev_date).all()
        prev_map = {l.ts_code: l for l in prev_leaders}
        
        updated = 0
        for leader in leaders:
            # 获取个股资金流向
            stock = db.query(StockFlow).filter_by(trade_date=trade_date, ts_code=leader.ts_code).first()
            
            change_rate = float(stock.price_chg or 0) if stock else 0
            main_force = float(stock.main_force_inflow or 0) if stock else 0
            
            # 计算连板天数
            prev_leader = prev_map.get(leader.ts_code)
            if prev_leader:
                leader.consecutive_days = (prev_leader.consecutive_days or 0) + 1
            else:
                leader.consecutive_days = 1
            
            # 识别阶段
            stage = identify_stage(leader.consecutive_days, change_rate, main_force)
            leader.stage = stage
            leader.strength = STAGE_CONFIG[stage]['strength']
            leader.change_rate = change_rate
            
            updated += 1
        
        db.commit()
        print(f'[lifecycle] Updated {updated} leaders')
    except Exception as e:
        db.rollback()
        print(f'[lifecycle] Error: {e}')
    finally:
        db.close()


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    update_lifecycle(today)
