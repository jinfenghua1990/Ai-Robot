"""
投资组合风格分析器
综合资金流向、板块轮动、龙头生命周期数据，生成投资风格转换建议
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
from datetime import datetime
from db.connection import get_db
from db.session import get_db_session
from db.models import StockFlow, SectorFlow, LeaderLifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path

logger = logging.getLogger(__name__)


def analyze_portfolio_style(trade_date, lookback_days=5):
    """
    分析当前市场风格并生成投资组合转换建议
    返回: {
        market_style: 当前市场风格特征,
        inflow_sectors: 资金流入板块,
        outflow_sectors: 资金流出板块,
        top_stocks: 主力净流入个股,
        leaders: 龙头股分布,
        recommendations: 风格转换建议,
        allocation: 推荐配置比例,
        risk_control: 风控建议,
    }
    """
    try:
        with get_db_session() as db:
            # 1. 获取板块轮动数据
            rotation = calculate_rotation(trade_date, lookback_days)
            in_totals, out_totals = {}, {}
            for l in rotation.get('links', []):
                out_totals[l['source']] = out_totals.get(l['source'], 0) + l['value']
                in_totals[l['target']] = in_totals.get(l['target'], 0) + l['value']

            inflow_sorted = sorted(in_totals.items(), key=lambda x: -x[1])[:5]
            outflow_sorted = sorted(out_totals.items(), key=lambda x: -x[1])[:10]
            total_inflow = sum(in_totals.values())
            total_outflow = sum(out_totals.values())

            # 2. 获取个股资金流数据
            money_flow = calculate_money_flow_path(trade_date)
            top10 = money_flow.get('top10', [])

            # 个股板块分布
            stock_sectors = {}
            for s in top10:
                sec = s.get('sector', '未知')
                if sec not in stock_sectors:
                    stock_sectors[sec] = {'count': 0, 'total': 0.0, 'avg_chg': [], 'stocks': []}
                stock_sectors[sec]['count'] += 1
                stock_sectors[sec]['total'] += s['main_force_inflow']
                stock_sectors[sec]['avg_chg'].append(s['price_chg'])
                stock_sectors[sec]['stocks'].append({
                    'name': s['name'],
                    'ts_code': s['ts_code'],
                    'main_force_inflow': round(s['main_force_inflow'], 1),
                    'price_chg': round(s['price_chg'], 2),
                })

            for sec in stock_sectors:
                chgs = stock_sectors[sec]['avg_chg']
                stock_sectors[sec]['avg_chg'] = round(sum(chgs) / len(chgs), 2) if chgs else 0

            # 3. 获取龙头股分布
            leaders = db.query(LeaderLifecycle).filter_by(trade_date=trade_date).all()
            leader_by_sector = {}
            stage_counts = {}
            for l in leaders:
                sec = l.sector or '未知'
                if sec not in leader_by_sector:
                    leader_by_sector[sec] = []
                leader_by_sector[sec].append({
                    'name': l.name or l.ts_code,
                    'ts_code': l.ts_code,
                    'stage': l.stage,
                    'consecutive_days': l.consecutive_days or 1,
                })
                stage = l.stage or '未知'
                stage_counts[stage] = stage_counts.get(stage, 0) + 1

            # 龙头股最多的板块 Top10
            leader_top_sectors = sorted(leader_by_sector.items(), key=lambda x: -len(x[1]))[:10]

            # 4. 判断市场风格
            inflow_names = [s[0] for s in inflow_sorted]
            outflow_names = [s[0] for s in outflow_sorted]

            # 风格分类
            tech_sectors = {'半导体', '通信设备', '元器件', '计算机', '软件', '电子'}
            finance_sectors = {'银行', '证券', '保险', '多元金融'}
            energy_sectors = {'火力发电', '水力发电', '石油', '煤炭', '电力'}
            manufacturing_sectors = {'机械基件', '专用机械', '工程机械', '汽车配件', '运输设备'}
            cyclical_sectors = {'化工原料', '小金属', '铝', '铜', '钢铁', '建筑工程', '电气设备'}
            defensive_sectors = {'医药', '中成药', '医疗保健', '食品饮料', '旅游服务', '环境保护'}

            inflow_tech = sum(v for s, v in inflow_sorted if s in tech_sectors)
            inflow_finance = sum(v for s, v in inflow_sorted if s in finance_sectors)
            inflow_manufacturing = sum(v for s, v in inflow_sorted if s in manufacturing_sectors)
            inflow_cyclical = sum(v for s, v in inflow_sorted if s in cyclical_sectors)
            inflow_defensive = sum(v for s, v in inflow_sorted if s in defensive_sectors)
            outflow_finance = sum(v for s, v in outflow_sorted if s in finance_sectors)
            outflow_energy = sum(v for s, v in outflow_sorted if s in energy_sectors)

            # 风格判断
            style_scores = {
                '成长': inflow_tech,
                '价值': inflow_finance,
                '制造': inflow_manufacturing,
            }
            dominant_style = max(style_scores, key=style_scores.get) if any(style_scores.values()) else '均衡'

            market_style = {
                'dominant': dominant_style,
                'growth_vs_value': '成长 > 价值' if inflow_tech > inflow_finance else '价值 > 成长',
                'tech_vs_finance': '科技 > 金融' if inflow_tech > inflow_finance else '金融 > 科技',
                'manufacturing_vs_cyclical': '制造 > 周期' if inflow_manufacturing > outflow_energy else '周期 > 制造',
                'inflow_tech': round(inflow_tech, 1),
                'inflow_finance': round(inflow_finance, 1),
                'inflow_manufacturing': round(inflow_manufacturing, 1),
                'inflow_cyclical': round(inflow_cyclical, 1),
                'inflow_defensive': round(inflow_defensive, 1),
                'outflow_finance': round(outflow_finance, 1),
                'outflow_energy': round(outflow_energy, 1),
            }

            # 5. 生成配置建议
            # 基于流入板块计算配置权重
            total_inflow_val = sum(v for _, v in inflow_sorted) or 1
            allocation = []

            # 科技硬件
            tech_inflow = sum(v for s, v in inflow_sorted if s in tech_sectors)
            tech_pct = round(tech_inflow / total_inflow_val * 100) if total_inflow_val > 0 else 0
            tech_pct = min(max(tech_pct, 30), 45)  # 限制在30-45%
            allocation.append({
                'category': '科技硬件',
                'sectors': [s for s, _ in inflow_sorted if s in tech_sectors] or ['半导体', '通信设备'],
                'percentage': tech_pct,
                'reason': 'AI算力需求爆发，国产替代加速，主力资金持续流入',
                'stocks': [s for sec in stock_sectors if sec in tech_sectors for s in stock_sectors[sec]['stocks'][:3]],
            })

            # 高端制造
            mfg_inflow = sum(v for s, v in inflow_sorted if s in manufacturing_sectors)
            mfg_pct = round(mfg_inflow / total_inflow_val * 100) if total_inflow_val > 0 else 0
            mfg_pct = min(max(mfg_pct, 15), 30)
            allocation.append({
                'category': '高端制造',
                'sectors': [s for s, _ in inflow_sorted if s in manufacturing_sectors] or ['机械基件', '专用机械'],
                'percentage': mfg_pct,
                'reason': '高端制造国产化，设备更新政策催化，订单饱满',
                'stocks': [],
            })

            # 防御消费
            allocation.append({
                'category': '防御消费',
                'sectors': ['医药', '食品饮料', '旅游'],
                'percentage': 20,
                'reason': '对冲科技波动风险，防御属性突出',
                'stocks': [],
            })

            # 现金
            cash_pct = 100 - tech_pct - mfg_pct - 20
            allocation.append({
                'category': '现金/短债',
                'sectors': [],
                'percentage': max(cash_pct, 10),
                'reason': '等待回调加仓科技股的机会',
                'stocks': [],
            })

            # 6. 减持建议
            reduce_list = []
            for sec, val in outflow_sorted:
                reason_map = {
                    '银行': '低估值陷阱，资金持续外流，缺乏催化剂',
                    '证券': '市场量能不足，券商beta属性弱化',
                    '保险': '利率下行周期，负债端承压',
                    '火力发电': '能源转型趋势下长期承压',
                    '水力发电': '来水不确定性，防御价值降低',
                    '化工原料': '周期下行，需求疲软',
                    '电气设备': '新能源链产能过剩，竞争加剧',
                }
                reduce_list.append({
                    'sector': sec,
                    'outflow': round(val, 1),
                    'reason': reason_map.get(sec, '资金持续流出，趋势走弱'),
                })

            # 7. 增持建议
            increase_list = []
            for sec, val in inflow_sorted:
                stock_list = stock_sectors.get(sec, {}).get('stocks', [])
                leader_list = leader_by_sector.get(sec, [])
                increase_list.append({
                    'sector': sec,
                    'inflow': round(val, 1),
                    'stocks': stock_list[:3],
                    'leader_count': len(leader_list),
                    'leaders': [l['name'] for l in leader_list[:3]],
                })

            # 8. 风控建议
            risk_control = {
                'stop_loss': '个股跌幅超8%减半仓，超12%清仓',
                'stop_profit': '板块轮动信号反转（科技板块出现在流出Top10时）全面减仓',
                'monitor': '每日关注资金流向Sankey图，若半导体/通信设备从流入端消失则立即调整',
                'position_limit': '单一个股不超过15%，单一板块不超过30%',
            }

            return {
                'date': trade_date,
                'lookback_days': lookback_days,
                'market_style': market_style,
                'inflow_sectors': [{'sector': s, 'inflow': round(v, 1)} for s, v in inflow_sorted],
                'outflow_sectors': reduce_list,
                'top_stocks': top10,
                'stock_sectors': stock_sectors,
                'leaders': {
                    'total': len(leaders),
                    'stage_counts': stage_counts,
                    'top_sectors': [{'sector': sec, 'count': len(lst), 'leaders': lst[:3]} for sec, lst in leader_top_sectors],
                },
                'recommendations': {
                    'reduce': reduce_list,
                    'increase': increase_list,
                },
                'allocation': allocation,
                'risk_control': risk_control,
                'summary': {
                    'total_inflow': round(total_inflow, 0),
                    'total_outflow': round(total_outflow, 0),
                    'net_flow': round(total_inflow - total_outflow, 0),
                    'dominant_style': dominant_style,
                    'leader_total': len(leaders),
                },
        }
    except Exception as e:
        logger.exception(f'[portfolio] Error')
        return {'error': str(e)}


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    result = analyze_portfolio_style(today)
    print(result)
