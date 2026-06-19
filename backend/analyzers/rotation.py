"""
板块轮动分析器
对比当前与N日前各板块net_flow变化，生成桑基图数据
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta
from db.connection import get_db
from db.models import SectorFlow
from sqlalchemy import func


def calculate_rotation(trade_date, lookback_days=5):
    """
    计算板块轮动数据
    返回桑基图格式: { nodes: [...], links: [...], signals: [...] }
    """
    db = next(get_db())
    try:
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
            print(f'[rotation] Comparing {trade_date} vs {past_date} (lookback {lookback_days}d)')
        else:
            print(f'[rotation] No past trading day found for lookback {lookback_days}d')
        
        if not current_sectors:
            return {'nodes': [], 'links': [], 'signals': []}
        
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
        
        # 流出板块节点（Top 10）
        for c in outflows[:10]:
            nodes.append({'name': c['sector'], 'category': 'outflow'})
        
        # 流入板块节点（Top 5，更聚焦）
        for c in inflows[:5]:
            nodes.append({'name': c['sector'], 'category': 'inflow'})
        
        # 生成链接：流出Top10 → 流入Top5
        for out_c in outflows[:10]:
            for in_c in inflows[:5]:
                flow_value = min(abs(out_c['change']), in_c['change'])
                if flow_value > 0:
                    links.append({
                        'source': out_c['sector'],
                        'target': in_c['sector'],
                        'value': round(flow_value, 2),
                    })
        
        # 生成轮动信号
        signals = []
        if inflows:
            signals.append(f"资金流入: {', '.join([c['sector'] for c in inflows[:5]])}")
        if outflows:
            signals.append(f"资金流出: {', '.join([c['sector'] for c in outflows[:5]])}")
        
        return {
            'nodes': nodes,
            'links': links,
            'signals': signals,
            'date': trade_date,
            'lookback_days': lookback_days,
        }
    except Exception as e:
        print(f'[rotation] Error: {e}')
        return {'nodes': [], 'links': [], 'signals': []}
    finally:
        db.close()


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    result = calculate_rotation(today)
    print(result)
