"""
资金流路径分析器
生成: 散户/机构/游资 → 板块 → 龙头股 的流向图数据
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_db
from db.models import StockFlow, LeaderLifecycle, SectorFlow


def calculate_money_flow_path(trade_date):
    """
    计算资金流路径
    返回Graph格式: { nodes: [...], links: [...], top10: [...] }
    """
    db = next(get_db())
    try:
        # 获取个股资金流向
        stocks = db.query(StockFlow).filter_by(trade_date=trade_date).all()
        if not stocks:
            return {'nodes': [], 'links': [], 'top10': []}
        
        # 按板块汇总
        sector_data = {}
        for stock in stocks:
            sector = stock.sector or '未知'
            if sector not in sector_data:
                sector_data[sector] = {
                    'main_force': 0,
                    'retail': 0,
                    'net': 0,
                    'leaders': [],
                }
            sector_data[sector]['main_force'] += float(stock.main_force_inflow or 0)
            sector_data[sector]['retail'] += float(stock.retail_flow or 0)
            sector_data[sector]['net'] += float(stock.net_inflow or 0)
        
        # 获取龙头股
        leaders = db.query(LeaderLifecycle).filter_by(trade_date=trade_date).all()
        leader_sectors = {}
        for leader in leaders:
            if leader.sector:
                if leader.sector not in leader_sectors:
                    leader_sectors[leader.sector] = []
                leader_sectors[leader.sector].append(leader.ts_code)
        
        # 构建图数据
        nodes = []
        links = []
        
        # 资金来源节点
        sources = ['主力', '散户']
        for s in sources:
            nodes.append({'name': s, 'category': 'source'})
        
        # 板块节点
        top_sectors = sorted(sector_data.items(), key=lambda x: abs(x[1]['net']), reverse=True)[:10]
        for sector, data in top_sectors:
            nodes.append({'name': sector, 'category': 'sector'})
            
            # 资金来源 → 板块
            if data['main_force'] > 0:
                links.append({
                    'source': '主力',
                    'target': sector,
                    'value': round(abs(data['main_force']), 2),
                })
            if data['retail'] != 0:
                links.append({
                    'source': '散户',
                    'target': sector,
                    'value': round(abs(data['retail']), 2),
                })
            
            # 板块 → 龙头股
            if sector in leader_sectors:
                for ts_code in leader_sectors[sector][:3]:
                    nodes.append({'name': ts_code, 'category': 'leader'})
                    links.append({
                        'source': sector,
                        'target': ts_code,
                        'value': 100,  # 固定值或按资金量
                    })
        
        # 主力净流入Top10
        top10 = sorted(stocks, key=lambda x: float(x.main_force_inflow or 0), reverse=True)[:10]
        top10_data = [{
            'ts_code': s.ts_code,
            'sector': s.sector,
            'main_force_inflow': float(s.main_force_inflow or 0),
            'price_chg': float(s.price_chg or 0),
        } for s in top10]
        
        return {
            'nodes': nodes,
            'links': links,
            'top10': top10_data,
            'date': trade_date,
        }
    except Exception as e:
        print(f'[money_flow] Error: {e}')
        return {'nodes': [], 'links': [], 'top10': []}
    finally:
        db.close()


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    result = calculate_money_flow_path(today)
    print(result)
