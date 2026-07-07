"""
板块轮动分析器
对比当前与N日前各板块net_flow变化，生成桑基图数据
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
from datetime import datetime, timedelta
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow
from sqlalchemy import func

logger = logging.getLogger(__name__)


def calculate_rotation(trade_date, lookback_days=5):
    """
    计算板块轮动数据
    返回桑基图格式: { nodes: [...], links: [...], signals: [...], streaks: {...} }
    """
    try:
        with get_db_session() as db:
            # 获取当前日期和N天前的板块数据
            current_sectors = db.query(SectorFlow).filter_by(trade_date=trade_date).all()
        
            # 获取N天前的数据：查找数据库中实际存在的最近交易日
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d') if isinstance(trade_date, str) else trade_date
            past_date_obj = trade_date_obj - timedelta(days=lookback_days)
            # 查询该日期之前（含）最近的交易日
            past_date_row = db.query(func.max(SectorFlow.trade_date)).filter(
                SectorFlow.trade_date <= past_date_obj.date(),
                SectorFlow.trade_date < trade_date_obj.date()
            ).scalar()
            past_sectors = []
            if past_date_row:
                past_date = past_date_row.strftime('%Y-%m-%d')
                past_sectors = db.query(SectorFlow).filter_by(trade_date=past_date_row).all()
                logger.debug(f'[rotation] Comparing {trade_date} vs {past_date} (lookback {lookback_days}d)')
            else:
                logger.debug(f'[rotation] No past trading day found for lookback {lookback_days}d')
        
            if not current_sectors:
                return {'nodes': [], 'links': [], 'signals': [], 'streaks': {}}
        
            # 构建板块净流入映射
            current_map = {s.sector: float(s.net_flow or 0) for s in current_sectors}
            past_map = {s.sector: float(s.net_flow or 0) for s in past_sectors} if past_sectors else {}
        
            # 计算变化
            changes = []
            for sector, current_flow in current_map.items():
                past_flow = past_map.get(sector, 0)
                change = current_flow - past_flow
                changes.append({
                    'sector': sector,
                    'current': current_flow,
                    'past': past_flow,
                    'change': change,
                })
        
            # 按变化排序：正变化=流入，负变化=流出
            inflows = sorted([c for c in changes if c['change'] > 0], key=lambda x: x['change'], reverse=True)
            outflows = sorted([c for c in changes if c['change'] < 0], key=lambda x: x['change'])
        
            # 生成桑基图节点和链接
            nodes = []
            links = []

            # 全量流出/流入列表（按变化值排序）
            all_outflows = outflows  # 全部流出板块
            all_inflows = inflows    # 全部流入板块

            # 实际总额（全量）
            total_outflow_all = sum(abs(c['change']) for c in all_outflows)
            total_inflow_all = sum(c['change'] for c in all_inflows)

            # 桑基图用 Top 15 流出 + Top 10 流入（避免节点过多）
            top_outflows = outflows[:15]
            top_inflows = inflows[:10]

            # 流出板块节点
            for c in top_outflows:
                nodes.append({'name': c['sector'], 'category': 'outflow'})

            # 流入板块节点
            for c in top_inflows:
                nodes.append({'name': c['sector'], 'category': 'inflow'})

            # 按比例分配链接：每个流出板块按各流入板块占比分配资金
            total_outflow = sum(abs(c['change']) for c in top_outflows)
            total_inflow = sum(c['change'] for c in top_inflows)

            for out_c in top_outflows:
                out_val = abs(out_c['change'])
                for in_c in top_inflows:
                    if total_outflow > 0:
                        flow_value = out_val * (in_c['change'] / total_outflow)
                    else:
                        flow_value = 0
                    if flow_value > 0.01:
                        links.append({
                            'source': out_c['sector'],
                            'target': in_c['sector'],
                            'value': round(flow_value, 2),
                        })
        
            # === 计算连续流入天数 ===
            # 查询最近30天的交易日，计算每个板块的连续净流入天数
            recent_dates = db.query(SectorFlow.trade_date).filter(
                SectorFlow.trade_date <= trade_date_obj.date()
            ).distinct().order_by(SectorFlow.trade_date.desc()).limit(30).all()
            recent_dates = [d[0] for d in recent_dates]
            recent_dates.reverse()  # 旧→新
        
            streaks = {}
            if recent_dates:
                recent_data = db.query(SectorFlow).filter(
                    SectorFlow.trade_date.in_(recent_dates)
                ).all()
            
                # 按板块分组，按日期排序
                sector_daily = {}
                for s in recent_data:
                    if s.sector not in sector_daily:
                        sector_daily[s.sector] = []
                    sector_daily[s.sector].append({
                        'date': s.trade_date,
                        'net_flow': float(s.net_flow or 0)
                    })
            
                # 计算每个板块的连续流入天数
                for sector, daily_list in sector_daily.items():
                    daily_list.sort(key=lambda x: x['date'], reverse=True)  # 最新在前
                    streak = 0
                    for d in daily_list:
                        if d['net_flow'] > 0:
                            streak += 1
                        else:
                            break
                    streaks[sector] = streak
        
            # 生成轮动信号
            signals = []
            if inflows:
                # 在信号中加入连续流入天数信息
                inflow_names = [c['sector'] for c in inflows[:5]]
                inflow_detail = []
                for c in inflows[:5]:
                    streak = streaks.get(c['sector'], 0)
                    if streak >= 2:
                        inflow_detail.append(f"{c['sector']}(连续{streak}天流入)")
                    else:
                        inflow_detail.append(c['sector'])
                signals.append(f"资金流入：{'、'.join(inflow_detail)}")
            if outflows:
                signals.append(f"资金流出：{'、'.join([c['sector'] for c in outflows[:5]])}")
        
            return {
                'nodes': nodes,
                'links': links,
                'signals': signals,
                'streaks': streaks,
                'date': trade_date,
                'lookback_days': lookback_days,
                # 全量数据（供前端展示完整列表）
                'all_inflows': [{'sector': c['sector'], 'change': round(c['change'], 2),
                                 'current': round(c['current'], 2), 'past': round(c['past'], 2)}
                                for c in all_inflows],
                'all_outflows': [{'sector': c['sector'], 'change': round(c['change'], 2),
                                  'current': round(c['current'], 2), 'past': round(c['past'], 2)}
                                 for c in all_outflows],
                # 实际总额（全量）
                'total_inflow': round(total_inflow_all, 2),
                'total_outflow': round(total_outflow_all, 2),
                'net_flow': round(total_inflow_all - total_outflow_all, 2),
        }
    except Exception as e:
        logger.exception(f'[rotation] Error')
        return {'nodes': [], 'links': [], 'signals': [], 'streaks': {}, 'error': str(e)}


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    result = calculate_rotation(today)
    print(result)
