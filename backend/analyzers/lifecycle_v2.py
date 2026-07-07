"""
龙头生命周期 V2 — 多维度强度评分
保留原 identify_stage 阶段判断逻辑，强度改为连续值计算
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
from datetime import datetime
from db.connection import get_db
from db.session import get_db_session
from db.models import LeaderLifecycle, StockFlow
from sqlalchemy import func

logger = logging.getLogger(__name__)


# 阶段判断（新命名）
def identify_stage(consecutive_days, change_rate, main_force_inflow):
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


# 阶段加成（加速最优，主升降分因高位风险）
STAGE_BONUS = {
    '突破': 15,
    '加速': 20,
    '主升': 10,
    '分歧': 5,
    '衰退': 0,
}

STAGE_COLORS = {
    '突破': '#facc15',
    '加速': '#fb923c',
    '主升': '#ef4444',
    '分歧': '#f97316',
    '衰退': '#94a3b8',
}


# 连板分映射表（非单调：2-3板最优，4板+递减因高位风险）
CONN_SCORE_MAP = {0: 5, 1: 15, 2: 30, 3: 30, 4: 20, 5: 10}
def get_conn_score(consecutive_days):
    if consecutive_days >= 6:
        return 5  # 6板+ 高位风险极大
    return CONN_SCORE_MAP.get(consecutive_days, 5)


def calculate_strength(consecutive_days, change_rate, main_force_inflow, stage):
    """
    多维度强度评分 V2（0-100 连续值）

    回测优化后公式（V2.1）：
      连板分 (30分): 非单调，2-3板满分，4板+递减（高位风险）
      涨幅分 (10分): |涨幅| × 1，10%满分（涨停无区分度，降权）
      资金分 (40分): sqrt(流入/50万) × 40，平方根曲线提升低端区分度
      阶段加成 (20分): 加速20 / 突破15 / 主升10 / 分歧5 / 衰退0
    """
    # 连板分（0-30，非单调）
    conn_score = get_conn_score(consecutive_days)

    # 涨幅分（0-10，涨停股无区分度故降权）
    change_score = min(abs(change_rate) * 1, 10)

    # 资金分（0-40，平方根曲线：低端区分度提升3-4倍）
    fund_score = min(math.sqrt(max(main_force_inflow, 0) / 50) * 40, 40) if main_force_inflow > 0 else 0

    # 阶段加成（0-20）
    stage_score = STAGE_BONUS.get(stage, 0)

    total = conn_score + change_score + fund_score + stage_score
    return round(min(total, 100), 1)


def get_lifecycle_v2(trade_date):
    """返回 V2 龙头生命周期数据（含多维度强度）"""
    try:
        with get_db_session() as db:
            leaders = db.query(LeaderLifecycle).filter_by(trade_date=trade_date).all()
            if not leaders:
                return {'date': trade_date, 'leaders': [], 'message': '无龙头数据'}

            # 获取前一交易日（计算连板天数）
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d') if isinstance(trade_date, str) else trade_date
            prev_date_row = db.query(func.max(LeaderLifecycle.trade_date)).filter(
                LeaderLifecycle.trade_date < trade_date_obj.date()
            ).scalar()
            prev_leaders = []
            if prev_date_row:
                prev_leaders = db.query(LeaderLifecycle).filter_by(trade_date=prev_date_row).all()
            prev_map = {l.ts_code: l for l in prev_leaders}

            # 批量获取个股资金数据
            ts_codes = [l.ts_code for l in leaders]
            stocks = db.query(StockFlow).filter(
                StockFlow.trade_date == trade_date,
                StockFlow.ts_code.in_(ts_codes)
            ).all()
            stock_map = {s.ts_code: s for s in stocks}

            result = []
            for leader in leaders:
                stock = stock_map.get(leader.ts_code)

                change_rate = float(stock.price_chg or 0) if stock else 0
                main_force = float(stock.main_force_inflow or 0) if stock else 0

                # 连板天数
                prev_leader = prev_map.get(leader.ts_code)
                consecutive_days = (prev_leader.consecutive_days or 0) + 1 if prev_leader else 1

                # 阶段判断（与 V1 一致）
                stage = identify_stage(consecutive_days, change_rate, main_force)

                # 多维度强度
                strength = calculate_strength(consecutive_days, change_rate, main_force, stage)

                # 各维度得分（用于前端展示）
                conn_score = get_conn_score(consecutive_days)
                change_score = min(abs(change_rate) * 1, 10)
                fund_score = min(math.sqrt(max(main_force, 0) / 50) * 40, 40) if main_force > 0 else 0
                stage_score = STAGE_BONUS.get(stage, 0)

                result.append({
                    'ts_code': leader.ts_code,
                    'name': leader.name or stock.name if stock else '',
                    'sector': leader.sector,
                    'stage': stage,
                    'strength': strength,
                    'consecutive_days': consecutive_days,
                    'change_rate': round(change_rate, 2),
                    'main_force_inflow': round(main_force, 2),
                    # 维度分解
                    'scores': {
                        'connection': round(conn_score, 1),
                        'change': round(change_score, 1),
                        'fund': round(fund_score, 1),
                        'stage_bonus': stage_score,
                    },
                })

            # 按强度降序
            result.sort(key=lambda x: -x['strength'])

            return {
                'date': trade_date,
                'leaders': result,
                'total': len(result),
                'formula': {
                    'name': '多维度强度评分 V2.1（回测优化版）',
                    'max_score': 100,
                    'dimensions': [
                        {'key': 'connection', 'name': '连板分', 'max': 30, 'desc': '非单调：2-3板满分，4板+递减（高位风险）'},
                        {'key': 'change', 'name': '涨幅分', 'max': 10, 'desc': '|涨幅| × 1，10%满分（涨停无区分度故降权）'},
                        {'key': 'fund', 'name': '资金分', 'max': 40, 'desc': 'sqrt(流入/50万) × 40，平方根曲线提升低端区分度'},
                        {'key': 'stage_bonus', 'name': '阶段加成', 'max': 20, 'desc': '发酵20 / 启动15 / 主升10 / 分歧5 / 退潮0'},
                    ],
                },
            }
    except Exception as e:
        logger.exception(f'[lifecycle_v2] Error')
        return {'error': str(e), 'leaders': []}
