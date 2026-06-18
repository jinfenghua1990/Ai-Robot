from fastapi import APIRouter, Query
from db.connection import get_db
from db.models import SectorFlow, StockFlow, LeaderLifecycle
from collectors.tdx_collector import collect_daily_data
from analyzers.heat_score import calculate_heat_scores
from analyzers.lifecycle import update_lifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path
from datetime import datetime

router = APIRouter()

@router.get("/api/screener")
async def screen_stocks(strategy: str = Query("heat"), date: str = Query(None)):
    """智能选股：heat(热度综合) / baihu(白虎V2.6) / qinglong(青龙)"""
    db = next(get_db())
    try:
        trade_date = date or datetime.now().strftime('%Y-%m-%d')
        
        if strategy == "heat":
            # 基于热度的综合选股
            # 1. 获取热度Top5板块
            top_sectors = db.query(SectorFlow).filter_by(
                trade_date=trade_date
            ).order_by(SectorFlow.heat_score.desc()).limit(5).all()
            
            sector_names = [s.sector for s in top_sectors]
            
            # 2. 获取这些板块中的龙头股
            leaders = db.query(LeaderLifecycle).filter(
                LeaderLifecycle.trade_date == trade_date,
                LeaderLifecycle.sector.in_(sector_names),
                LeaderLifecycle.stage.in_(['启动', '发酵'])
            ).all()
            
            # 3. 获取这些股票的资金流向
            leader_codes = [l.ts_code for l in leaders]
            stocks = db.query(StockFlow).filter(
                StockFlow.trade_date == trade_date,
                StockFlow.ts_code.in_(leader_codes)
            ).all()
            
            stock_map = {s.ts_code: s for s in stocks}
            
            results = []
            for leader in leaders:
                stock = stock_map.get(leader.ts_code)
                results.append({
                    'ts_code': leader.ts_code,
                    'sector': leader.sector,
                    'stage': leader.stage,
                    'strength': float(leader.strength or 0),
                    'main_force_inflow': float(stock.main_force_inflow or 0) if stock else 0,
                    'price_chg': float(stock.price_chg or 0) if stock else 0,
                    'consecutive_days': leader.consecutive_days,
                })
            
            return {
                'strategy': 'heat',
                'date': trade_date,
                'stocks': sorted(results, key=lambda x: x['main_force_inflow'], reverse=True),
                'top_sectors': [{'name': s.sector, 'heat_score': float(s.heat_score or 0)} for s in top_sectors],
            }
        elif strategy == "baihu":
            # 白虎V2.6选股
            from strategies.baihu_v26 import run_baihu_screen
            # 获取热门板块的股票列表
            # 这里简化处理，实际需要获取股票列表后批量筛选
            return {'strategy': 'baihu', 'date': trade_date, 'stocks': [], 'message': 'Baihu strategy - need stock list'}
        elif strategy == "qinglong":
            return {'strategy': 'qinglong', 'date': trade_date, 'stocks': [], 'message': 'Qinglong strategy - need stock list'}
        else:
            return {'error': f'Unknown strategy: {strategy}'}
    finally:
        db.close()


@router.post("/api/backfill")
async def backfill(date: str = Query(...)):
    """手动补采集指定日期数据"""
    try:
        collect_daily_data(date)
        calculate_heat_scores(date)
        update_lifecycle(date)
        calculate_rotation(date)
        calculate_money_flow_path(date)
        return {'status': 'ok', 'date': date, 'message': 'Backfill complete'}
    except Exception as e:
        return {'status': 'error', 'date': date, 'message': str(e)}
