"""
龙头生命周期 V3 分析器
新增功能:
1. 二波检测 - 识别退潮后重新走强的股票
2. 板块聚合 - 按板块分组统计
"""
from datetime import datetime, timedelta
from db.connection import get_db
from db.session import get_db_session
from db.models import LeaderLifecycle, StockFlow


def is_second_wave(ts_code, trade_date, db):
    """
    检测股票是否处于二波行情
    条件:
    1. 近15天内有过退潮记录（确认第一波结束）
    2. 当前重新走强（涨幅>5% 或 连板天数>=1）
    3. 之前有过强势记录（连板>=2）
    """
    trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d') if isinstance(trade_date, str) else trade_date
    start_date = trade_date_obj - timedelta(days=15)
    
    # 检查近15天内是否有衰退记录（兼容新旧命名）
    has_retreat = db.query(LeaderLifecycle).filter(
        LeaderLifecycle.ts_code == ts_code,
        LeaderLifecycle.trade_date >= start_date.date(),
        LeaderLifecycle.trade_date < trade_date_obj.date(),
        LeaderLifecycle.stage.in_(['衰退', '退潮'])
    ).first()
    
    if not has_retreat:
        return False
    
    # 检查之前是否有过强势记录（连板>=2）
    has_strong = db.query(LeaderLifecycle).filter(
        LeaderLifecycle.ts_code == ts_code,
        LeaderLifecycle.trade_date >= start_date.date(),
        LeaderLifecycle.trade_date < trade_date_obj.date(),
        LeaderLifecycle.consecutive_days >= 2
    ).first()
    
    if not has_strong:
        return False
    
    # 检查当前是否重新走强
    current = db.query(LeaderLifecycle).filter(
        LeaderLifecycle.ts_code == ts_code,
        LeaderLifecycle.trade_date == trade_date_obj.date()
    ).first()
    
    if not current:
        return False
    
    # 当前连板>=1 或涨幅>5% 视为重新走强
    if current.consecutive_days >= 1 or (current.change_rate or 0) > 5:
        return True
    
    return False


def get_lifecycle_v3(trade_date):
    """
    返回龙头生命周期 V3 数据
    包含: 板块聚合统计 + 二波股票 + 完整龙头列表
    """
    trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d') if isinstance(trade_date, str) else trade_date
    with get_db_session() as db:
        leaders = db.query(LeaderLifecycle).filter_by(trade_date=trade_date_obj.date()).all()
        
        sector_stats = {}
        for leader in leaders:
            sector = leader.sector or '未知'
            if sector not in sector_stats:
                sector_stats[sector] = {
                    'count': 0,
                    'avg_strength': 0,
                    'avg_change': 0,
                    'total_inflow': 0,
                    'leaders': [],
                }
            
            stock = db.query(StockFlow).filter_by(
                trade_date=trade_date_obj.date(),
                ts_code=leader.ts_code
            ).first()
            inflow = float(stock.main_force_inflow or 0) if stock else 0
            
            sector_stats[sector]['count'] += 1
            sector_stats[sector]['avg_strength'] += float(leader.strength or 0)
            sector_stats[sector]['avg_change'] += float(leader.change_rate or 0)
            sector_stats[sector]['total_inflow'] += inflow
            sector_stats[sector]['leaders'].append({
                'ts_code': leader.ts_code,
                'name': leader.name or '',
                'stage': leader.stage,
                'strength': float(leader.strength or 0),
                'change_rate': float(leader.change_rate or 0),
                'consecutive_days': leader.consecutive_days,
                'main_force_inflow': inflow,
                'is_second_wave': is_second_wave(leader.ts_code, trade_date, db),
            })
        
        for sector, stats in sector_stats.items():
            if stats['count'] > 0:
                stats['avg_strength'] = round(stats['avg_strength'] / stats['count'], 1)
                stats['avg_change'] = round(stats['avg_change'] / stats['count'], 2)
        
        sector_list = sorted(sector_stats.items(), key=lambda x: -x[1]['count'])
        
        second_wave_stocks = []
        for sector, stats in sector_stats.items():
            for leader in stats['leaders']:
                if leader['is_second_wave']:
                    leader['sector'] = sector
                    second_wave_stocks.append(leader)
        
        second_wave_stocks.sort(key=lambda x: -x['strength'])
        
        return {
            'date': trade_date,
            'total_leaders': len(leaders),
            'total_sectors': len(sector_stats),
            'sector_list': [
                {
                    'name': sector,
                    'count': stats['count'],
                    'avg_strength': stats['avg_strength'],
                    'avg_change': stats['avg_change'],
                    'total_inflow': round(stats['total_inflow'], 2),
                }
                for sector, stats in sector_list
            ],
            'sector_detail': sector_stats,
            'second_wave': second_wave_stocks,
            'leaders': [
                {
                    'ts_code': l.ts_code,
                    'name': l.name or '',
                    'sector': l.sector,
                    'stage': l.stage,
                    'strength': float(l.strength or 0),
                    'change_rate': float(l.change_rate or 0),
                    'consecutive_days': l.consecutive_days,
                    'is_second_wave': is_second_wave(l.ts_code, trade_date, db),
                }
                for l in leaders
            ],
        }


if __name__ == '__main__':
    today = datetime.now().strftime('%Y-%m-%d')
    result = get_lifecycle_v3(today)
    print(f"Total leaders: {result['total_leaders']}")
    print(f"Total sectors: {result['total_sectors']}")
    print(f"Second wave: {len(result['second_wave'])}")