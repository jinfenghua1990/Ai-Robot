"""
资金流路径分析器
生成: 散户/机构/游资 → 板块 → 龙头股 的流向图数据
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
from db.connection import get_db
from db.session import get_db_session
from db.models import StockFlow, LeaderLifecycle

logger = logging.getLogger(__name__)


def calculate_money_flow_path(trade_date):
    """
    计算资金流路径
    返回Graph格式: { nodes: [...], links: [...], top10: [...] }
    """
    try:
        with get_db_session() as db:
            # 获取个股资金流向
            stocks = db.query(StockFlow).filter_by(trade_date=trade_date).all()
            if not stocks:
                return {'nodes': [], 'links': [], 'top10': []}
        
            # 按板块汇总，同时收集每板块个股（用于取 Top 10）
            sector_data = {}
            sector_stocks = {}  # {sector: [{'ts_code','name','main_force_inflow'}, ...]}
            for stock in stocks:
                sector = stock.sector or '未知'
                if sector not in sector_data:
                    sector_data[sector] = {
                        'main_force': 0,
                        'retail': 0,
                        'net': 0,
                        'leaders': [],
                    }
                    sector_stocks[sector] = []
                sector_data[sector]['main_force'] += float(stock.main_force_inflow or 0)
                sector_data[sector]['retail'] += float(stock.retail_flow or 0)
                sector_data[sector]['net'] += float(stock.net_inflow or 0)
                sector_stocks[sector].append({
                    'ts_code': stock.ts_code,
                    'name': stock.name or '',
                    'main_force_inflow': float(stock.main_force_inflow or 0),
                    'price': float(stock.price or 0),
                    'price_chg': float(stock.price_chg or 0),
                })

            # 构建个股主力净流入映射（用于板块→龙头股链接的实际资金量）
            stock_main_flow = {s.ts_code: float(s.main_force_inflow or 0) for s in stocks}
            # 构建个股价格/涨跌幅映射
            stock_price = {s.ts_code: float(s.price or 0) for s in stocks}
            stock_chg = {s.ts_code: float(s.price_chg or 0) for s in stocks}

            # 构建生命周期阶段映射（ts_code → stage）
            leaders = db.query(LeaderLifecycle).filter_by(trade_date=trade_date).all()
            leader_stage = {l.ts_code: l.stage for l in leaders}
        
            # 构建图数据
            nodes = []
            links = []
        
            # 资金来源节点
            sources = ['主力', '散户']
            for s in sources:
                nodes.append({'name': s, 'category': 'source'})
        
            # 板块节点：流入Top10 + 流出Top10
            all_sectors_sorted = sorted(sector_data.items(), key=lambda x: x[1]['main_force'], reverse=True)
            # 取主力净流入前10（流入最多）和后10（流出最多）
            inflow_top = [s for s in all_sectors_sorted if s[1]['main_force'] > 0][:10]
            outflow_top = [s for s in all_sectors_sorted if s[1]['main_force'] < 0][-10:][::-1]  # 流出最多的排前面
            top_sectors = inflow_top + outflow_top

            for sector, data in top_sectors:
                # sector 节点带上主力/散户净流入值（正负），前端直接用
                nodes.append({
                    'name': sector,
                    'category': 'sector',
                    'main_force': round(data['main_force'], 2),
                    'retail': round(data['retail'], 2),
                })

                # 资金来源 → 板块（流入用主力→板块，流出用板块→主力）
                if data['main_force'] > 0:
                    links.append({
                        'source': '主力',
                        'target': sector,
                        'value': round(abs(data['main_force']), 2),
                    })
                if data['retail'] > 0:
                    links.append({
                        'source': '散户',
                        'target': sector,
                        'value': round(abs(data['retail']), 2),
                    })
            
                # 板块 → 龙头股（按主力净流入排序取 Top 10）
                top_stocks = sorted(sector_stocks.get(sector, []),
                                    key=lambda x: x['main_force_inflow'], reverse=True)[:10]
                for stock_info in top_stocks:
                    ts_code = stock_info['ts_code']
                    display_name = stock_info['name'] or ts_code
                    leader_flow = stock_info['main_force_inflow']
                    stage = leader_stage.get(ts_code)  # 生命周期阶段：启动/发酵/主升/退潮
                    nodes.append({
                        'name': ts_code,
                        'label': display_name,
                        'category': 'leader',
                        'stage': stage,
                        'price': stock_info.get('price', 0),
                        'price_chg': stock_info.get('price_chg', 0),
                    })
                    links.append({
                        'source': sector,
                        'target': ts_code,
                        'value': round(abs(leader_flow), 2),
                    })
        
            # 主力净流入Top10
            top10 = sorted(stocks, key=lambda x: float(x.main_force_inflow or 0), reverse=True)[:10]
            top10_data = [{
                'ts_code': s.ts_code,
                'name': s.name or '',
                'sector': s.sector,
                'main_force_inflow': float(s.main_force_inflow or 0),
                'price_chg': float(s.price_chg or 0),
                'stage': leader_stage.get(s.ts_code),
            } for s in top10]
        
            return {
                'nodes': nodes,
                'links': links,
                'top10': top10_data,
                'date': trade_date,
        }
    except Exception as e:
        logger.exception(f'[money_flow] Error')
        return {'nodes': [], 'links': [], 'top10': [], 'error': str(e)}


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    result = calculate_money_flow_path(today)
    print(result)
