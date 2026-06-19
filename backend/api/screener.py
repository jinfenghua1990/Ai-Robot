from fastapi import APIRouter, Query
from db.connection import get_db
from db.models import SectorFlow, StockFlow, LeaderLifecycle
from collectors.tdx_collector import collect_daily_data
from analyzers.heat_score import calculate_heat_scores
from analyzers.lifecycle import update_lifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path
from datetime import datetime
import concurrent.futures

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
                    'name': leader.name or (stock.name if stock else '') or '',
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
        elif strategy in ("baihu", "qinglong"):
            # 白虎V2.6 / 青龙 选股
            # 1. 获取热门板块的股票作为候选池（Top10板块 + 主力净流入>0）
            top_sectors = db.query(SectorFlow).filter_by(
                trade_date=trade_date
            ).order_by(SectorFlow.heat_score.desc()).limit(10).all()
            sector_names = [s.sector for s in top_sectors]

            candidates = db.query(StockFlow).filter(
                StockFlow.trade_date == trade_date,
                StockFlow.sector.in_(sector_names),
                StockFlow.main_force_inflow > 0,
            ).order_by(StockFlow.main_force_inflow.desc()).limit(80).all()

            stock_list = [c.ts_code for c in candidates]
            stock_name_map = {c.ts_code: c.name for c in candidates}
            stock_sector_map = {c.ts_code: c.sector for c in candidates}

            if not stock_list:
                return {'strategy': strategy, 'date': trade_date, 'stocks': [], 'message': '无候选股票'}

            # 2. 执行策略选股（使用线程池避免阻塞）
            if strategy == "baihu":
                from strategies.baihu_v26 import run_baihu_screen
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    future = executor.submit(run_baihu_screen, stock_list, trade_date)
                    try:
                        hits = future.result(timeout=120)
                    except concurrent.futures.TimeoutError:
                        return {'strategy': strategy, 'date': trade_date, 'stocks': [], 'message': '选股超时，请减少候选数量'}
            else:
                from strategies.qinglong import run_qinglong_screen
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    future = executor.submit(run_qinglong_screen, stock_list, trade_date)
                    try:
                        hits = future.result(timeout=120)
                    except concurrent.futures.TimeoutError:
                        return {'strategy': strategy, 'date': trade_date, 'stocks': [], 'message': '选股超时，请减少候选数量'}

            # 3. 格式化结果
            results = []
            for h in hits:
                ts_code = h.get('ts_code', '')
                results.append({
                    'ts_code': ts_code,
                    'name': stock_name_map.get(ts_code, ''),
                    'sector': stock_sector_map.get(ts_code, ''),
                    'stage': '策略选股',
                    'strength': float(h.get('score', 0)),
                    'main_force_inflow': 0,
                    'price_chg': float(h.get('change_pct', 0)),
                    'consecutive_days': 0,
                    'score': float(h.get('score', 0)),
                    'deviation': float(h.get('deviation', 0)),
                    'rsi': float(h.get('rsi', 0)),
                    'vol_ratio': float(h.get('vol_ratio', 0)),
                    '20day_gain': float(h.get('20day_gain', 0)),
                    'close': float(h.get('close', 0)),
                })

            return {
                'strategy': strategy,
                'date': trade_date,
                'stocks': sorted(results, key=lambda x: x['score'], reverse=True),
                'top_sectors': [{'name': s.sector, 'heat_score': float(s.heat_score or 0)} for s in top_sectors[:5]],
                'candidate_count': len(stock_list),
            }
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
