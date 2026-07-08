from fastapi import APIRouter, Query
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow, StockFlow, LeaderLifecycle
from collectors.tdx_collector import collect_daily_data
from analyzers.heat_score import calculate_heat_scores
from analyzers.lifecycle import update_lifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path
from api.validators import validate_date
from services.signal_builder import build_signals_batch, build_signals_from_strategy_result
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/api/screener")
async def screen_stocks(strategy: str = Query("heat"), date: str = Query(None)):
    """智能选股：heat(热度综合) / baihu(白虎V2.6) / qinglong(青龙)"""
    trade_date = validate_date(date)
    with get_db_session() as db:
        # 通用：获取板块资金流和龙头生命周期数据
        sector_flows = db.query(SectorFlow).filter_by(trade_date=trade_date).order_by(SectorFlow.net_flow.desc()).all()
        leaders = db.query(LeaderLifecycle).filter_by(trade_date=trade_date).order_by(LeaderLifecycle.strength.desc()).all()

        sector_flow_data = [{
            'sector': s.sector,
            'net_flow': float(s.net_flow or 0),
            'money_inflow': float(s.money_inflow or 0),
            'money_outflow': float(s.money_outflow or 0),
            'limit_up_count': int(s.limit_up_count or 0),
            'heat_score': float(s.heat_score or 0),
            'leader_stock': s.leader_stock,
            'leader_strength': float(s.leader_strength or 0) if s.leader_strength else 0,
        } for s in sector_flows]

        leader_data = [{
            'ts_code': l.ts_code,
            'name': l.name,
            'sector': l.sector,
            'stage': l.stage,
            'strength': float(l.strength or 0),
            'change_rate': float(l.change_rate or 0),
            'consecutive_days': int(l.consecutive_days or 0),
        } for l in leaders]

        if strategy == "heat":
            # === 热度综合选股（V2：板块趋势过滤 + 多因子筛选 + 精选15只） ===

            # 1. 板块趋势分析：查询最近3个交易日，判断板块是否上升趋势
            date_obj = datetime.strptime(trade_date, '%Y-%m-%d')
            check_dates = []
            for i in range(1, 8):  # 往前找7天，取最近3个有数据的交易日
                d = (date_obj - timedelta(days=i)).strftime('%Y-%m-%d')
                check_dates.append(d)
            all_check_dates = [trade_date] + check_dates

            recent_sectors = db.query(SectorFlow).filter(
                SectorFlow.trade_date.in_(all_check_dates)
            ).all()

            # 按板块分组，计算趋势
            sector_history = {}  # {sector: [(date, net_flow, heat_score), ...]}
            for sf in recent_sectors:
                if sf.sector not in sector_history:
                    sector_history[sf.sector] = []
                sector_history[sf.sector].append((
                    sf.trade_date,
                    float(sf.net_flow or 0),
                    float(sf.heat_score or 0)
                ))

            # 判断板块趋势：最近3天中至少2天净流入为正 → 上升趋势
            up_trend_sectors = set()
            sector_trend_info = {}
            for sector, records in sector_history.items():
                records.sort(key=lambda x: x[0], reverse=True)
                recent = records[:3]  # 最近3天
                if len(recent) >= 2:
                    up_days = sum(1 for r in recent if r[1] > 0)
                    heat_now = recent[0][2]
                    heat_prev = recent[-1][2] if len(recent) > 1 else heat_now
                    is_up = up_days >= 2 and heat_now >= heat_prev
                    sector_trend_info[sector] = {
                        'trend': 'up' if is_up else ('flat' if up_days >= 1 else 'down'),
                        'up_days': up_days,
                        'heat_now': heat_now,
                        'heat_prev': heat_prev,
                    }
                    if is_up:
                        up_trend_sectors.add(sector)
                else:
                    # 数据不足，仅看当天
                    if records and records[0][1] > 0:
                        up_trend_sectors.add(sector)
                        sector_trend_info[sector] = {'trend': 'up', 'up_days': 1, 'heat_now': records[0][2], 'heat_prev': records[0][2]}

            # 2. 获取热度Top板块（用于展示）
            top_sectors_all = db.query(SectorFlow).filter_by(
                trade_date=trade_date
            ).order_by(SectorFlow.heat_score.desc()).limit(15).all()

            # 选股板块池：所有上升趋势板块 + 热度Top板块（取并集，避免板块名不一致漏选）
            sector_names = list(up_trend_sectors)
            for s in top_sectors_all:
                if s.sector not in sector_names and float(s.net_flow or 0) > 0:
                    sector_names.append(s.sector)

            # 用于展示的Top板块
            up_sectors = [s for s in top_sectors_all if s.sector in up_trend_sectors]
            if not up_sectors:
                up_sectors = [s for s in top_sectors_all if float(s.net_flow or 0) > 0][:5]

            # 3. 从上升趋势板块中选突破/加速阶段龙头（兼容新旧命名）
            leaders_query = db.query(LeaderLifecycle).filter(
                LeaderLifecycle.trade_date == trade_date,
                LeaderLifecycle.stage.in_(['突破', '加速', '启动', '发酵'])
            )
            if sector_names:
                leaders_query = leaders_query.filter(LeaderLifecycle.sector.in_(sector_names))
            leaders_stage = leaders_query.order_by(LeaderLifecycle.strength.desc()).limit(30).all()

            results = []
            use_leaders = len(leaders_stage) > 0

            if use_leaders:
                # 优先路径：有龙头生命周期数据
                leader_codes = [l.ts_code for l in leaders_stage]
                stocks = db.query(StockFlow).filter(
                    StockFlow.trade_date == trade_date,
                    StockFlow.ts_code.in_(leader_codes)
                ).all()
                stock_map = {s.ts_code: s for s in stocks}

                for leader in leaders_stage:
                    stock = stock_map.get(leader.ts_code)
                    main_force = float(stock.main_force_inflow or 0) if stock else 0
                    price_chg = float(stock.price_chg or 0) if stock else 0
                    strength = float(leader.strength or 0)

                    # 多因子过滤
                    if main_force <= 0: continue
                    if price_chg <= 0: continue
                    if strength < 30: continue

                    results.append({
                        'ts_code': leader.ts_code,
                        'name': leader.name or (stock.name if stock else '') or '',
                        'sector': leader.sector,
                        'stage': leader.stage,
                        'strength': strength,
                        'main_force_inflow': main_force,
                        'price_chg': price_chg,
                        'consecutive_days': leader.consecutive_days,
                    })
            else:
                # 降级路径：无龙头数据，直接从StockFlow选强势股
                stock_filter = [
                    StockFlow.trade_date == trade_date,
                    StockFlow.main_force_inflow > 0,
                ]
                if sector_names:
                    stock_filter.append(StockFlow.sector.in_(sector_names))
                candidates = db.query(StockFlow).filter(*stock_filter).order_by(
                    StockFlow.main_force_inflow.desc()
                ).limit(50).all()

                for stock in candidates:
                    main_force = float(stock.main_force_inflow or 0)
                    price_chg = float(stock.price_chg or 0)

                    if main_force <= 0: continue
                    if price_chg <= 0: continue

                    results.append({
                        'ts_code': stock.ts_code,
                        'name': stock.name or '',
                        'sector': stock.sector or '',
                        'stage': '热门',
                        'strength': main_force,  # 用主力净流入作为强度代理
                        'main_force_inflow': main_force,
                        'price_chg': price_chg,
                        'consecutive_days': 0,
                    })

            # 4. 综合评分排序：主力净流入(40%) + 强度(35%) + 涨幅(25%)
            if results:
                max_flow = max(r['main_force_inflow'] for r in results) or 1
                max_strength = max(r['strength'] for r in results) or 1
                max_chg = max(r['price_chg'] for r in results) or 1
                for r in results:
                    r['composite_score'] = round(
                        (r['main_force_inflow'] / max_flow) * 40 +
                        (r['strength'] / max_strength) * 35 +
                        (r['price_chg'] / max_chg) * 25, 2
                    )
                results = sorted(results, key=lambda x: x['composite_score'], reverse=True)

            # 5. 精选Top15
            results = results[:15]

            # 6. 构造完整 signal 数据（与自选股/重点关注口径一致）
            enriched_stocks = await build_signals_batch(
                results, db,
                code_key='ts_code', name_key='name', sector_key='sector',
                stage_key='stage', strength_key='strength',
                change_key='price_chg', days_key='consecutive_days',
            )
            # 保留原始字段（composite_score/main_force_inflow）合并到 enriched
            stock_meta = {r['ts_code']: r for r in results}
            for s in enriched_stocks:
                meta = stock_meta.get(s['secCode'])
                if meta:
                    s['compositeScore'] = meta.get('composite_score', 0)
                    s['mainForceInflow'] = meta.get('main_force_inflow', 0)

            # 同时为 leaders Top15 构造 signal
            top_leaders = leader_data[:15]
            enriched_leaders = await build_signals_batch(
                top_leaders, db,
                code_key='ts_code', name_key='name', sector_key='sector',
                stage_key='stage', strength_key='strength',
                change_key='change_rate', days_key='consecutive_days',
            )

            filters_used = [
                '板块上升趋势(近3天≥2天净流入)',
                '启动/发酵阶段' if use_leaders else '主力净流入Top50(降级)',
                '主力净流入>0',
                '涨幅>0',
                '强度>30' if use_leaders else '',
                '综合评分排序',
                '精选Top15',
            ]

            return {
                'strategy': 'heat',
                'date': trade_date,
                'stocks': enriched_stocks,
                'top_sectors': [{'name': s.sector, 'heat_score': float(s.heat_score or 0)} for s in up_sectors[:5]],
                'sector_flows': sector_flow_data,
                'leaders': enriched_leaders,
                'filter_info': {
                    'up_trend_sectors': len(up_trend_sectors),
                    'selected_sectors': len(up_sectors),
                    'total_candidates': len(leaders_stage) if use_leaders else len(candidates),
                    'filtered': len(results),
                    'mode': 'leader' if use_leaders else 'fallback',
                    'filters': [f for f in filters_used if f],
                },
            }
        elif strategy in ("baihu", "qinglong", "zhushenglang", "wave_band"):
            # 优先读预计算表（盘后定时扫描已落库），命中则跳过现场计算
            _sk_map = {'baihu': 'baihu_v26', 'qinglong': 'qinglong', 'zhushenglang': 'zhushenglang', 'wave_band': 'wave_band'}
            _sk = _sk_map.get(strategy)
            if _sk:
                _precomputed = await build_signals_from_strategy_result(db, _sk, trade_date)
                if _precomputed is not None:
                    return {
                        'strategy': strategy,
                        'date': trade_date,
                        'stocks': _precomputed,
                        'top_sectors': [],
                        'candidate_count': len(_precomputed),
                        'sector_flows': sector_flow_data,
                        'leaders': [],
                        'message': 'ok(预计算)',
                    }
            # 白虎V2.6 / 青龙 选股
            # 1. 获取热门板块的股票作为候选池（Top10板块 + 主力净流入>0）
            top_sectors = db.query(SectorFlow).filter_by(
                trade_date=trade_date
            ).order_by(SectorFlow.heat_score.desc()).limit(10).all()
            sector_names = [s.sector for s in top_sectors]

            # zhushenglang 需要更大的候选池（MA多头排列较稀有），放宽主力限制
            if strategy == "zhushenglang":
                top_sectors_q = db.query(SectorFlow).filter_by(
                    trade_date=trade_date
                ).order_by(SectorFlow.heat_score.desc()).limit(15)
                sector_names = [s.sector for s in top_sectors_q.all()]
                top_sectors = db.query(SectorFlow).filter_by(
                    trade_date=trade_date
                ).order_by(SectorFlow.heat_score.desc()).limit(15).all()

                candidates = db.query(StockFlow).filter(
                    StockFlow.trade_date == trade_date,
                    StockFlow.sector.in_(sector_names),
                ).order_by(StockFlow.main_force_inflow.desc()).limit(150).all()
            else:
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

            # 2. 执行策略选股
            if strategy == "baihu":
                from strategies.baihu_v26 import run_baihu_screen
                hits = run_baihu_screen(stock_list, trade_date)
            elif strategy == "qinglong":
                from strategies.qinglong import run_qinglong_screen
                hits = run_qinglong_screen(stock_list, trade_date)
            elif strategy == "wave_band":
                from strategies.wave_band import run_wave_band_screen
                hits = run_wave_band_screen(stock_list, trade_date)
            else:
                from strategies.zhushenglang import run_zhushenglang_screen
                hits = run_zhushenglang_screen(stock_list, trade_date, db=db)

            # 3. 格式化结果
            results = []
            for h in hits:
                ts_code = h.get('ts_code', '')
                r = {
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
                    'scores': h.get('scores', {}),
                    'lower_shadow': float(h.get('lower_shadow', 0)),
                    'ma20': float(h.get('ma20', 0)),
                }
                # 主升浪策略特有字段
                if strategy == "zhushenglang":
                    r['ma5'] = float(h.get('ma5', 0))
                    r['ma10'] = float(h.get('ma10', 0))
                    r['ma60'] = float(h.get('ma60', 0))
                    r['ma_spread'] = float(h.get('ma_spread', 0))
                    r['bias_20'] = float(h.get('bias_20', 0))
                    r['continuity_days'] = int(h.get('continuity_days', 0))
                    r['has_main_force'] = h.get('has_main_force', False)
                    r['exit_signal'] = h.get('exit_signal')
                # 波段信号策略特有字段
                if strategy == "wave_band":
                    r['ma5'] = float(h.get('ma5', 0))
                    r['ma10'] = float(h.get('ma10', 0))
                    r['rsi6'] = float(h.get('rsi6') or 0)
                    r['confidence'] = float(h.get('confidence', 0))
                    r['reason'] = h.get('reason', '')
                    r['signal'] = h.get('signal', 'buy')
                results.append(r)
            results = sorted(results, key=lambda x: x['score'], reverse=True)

            # 4. 构造完整 signal 数据
            enriched_stocks = await build_signals_batch(
                results, db,
                code_key='ts_code', name_key='name', sector_key='sector',
                stage_key='stage', strength_key='score',
                change_key='price_chg',
            )
            # 保留原始策略字段
            stock_meta = {r['ts_code']: r for r in results}
            for s in enriched_stocks:
                meta = stock_meta.get(s['secCode'])
                if meta:
                    s['strategyScore'] = meta.get('score', 0)
                    s['deviation'] = meta.get('deviation', 0)
                    s['rsi'] = meta.get('rsi', 0)
                    s['scores'] = meta.get('scores', {})
                    s['lowerShadow'] = meta.get('lower_shadow', 0)
                    # 主升浪策略特有字段
                    if strategy == "zhushenglang":
                        s['ma5'] = meta.get('ma5', 0)
                        s['ma10'] = meta.get('ma10', 0)
                        s['ma20'] = meta.get('ma20', 0)
                        s['ma60'] = meta.get('ma60', 0)
                        s['maSpread'] = meta.get('ma_spread', 0)
                        s['bias20'] = meta.get('bias_20', 0)
                        s['continuityDays'] = meta.get('continuity_days', 0)
                        s['hasMainForce'] = meta.get('has_main_force', False)
                        s['exitSignal'] = meta.get('exit_signal')
                    # 波段信号策略特有字段
                    if strategy == "wave_band":
                        s['ma5'] = meta.get('ma5', 0)
                        s['ma10'] = meta.get('ma10', 0)
                        s['rsi6'] = meta.get('rsi6', 0)
                        s['confidence'] = meta.get('confidence', 0)
                        s['waveReason'] = meta.get('reason', '')
                        s['waveSignal'] = meta.get('signal', 'buy')

            return {
                'strategy': strategy,
                'date': trade_date,
                'stocks': enriched_stocks,
                'top_sectors': [{'name': s.sector, 'heat_score': float(s.heat_score or 0)} for s in top_sectors[:5]],
                'candidate_count': len(stock_list),
                'sector_flows': sector_flow_data,
                'leaders': leader_data,
            }
        else:
            return {'error': f'Unknown strategy: {strategy}'}


@router.post("/api/backfill")
def backfill(date: str = Query(...), token: str = Query(None)):
    """手动补采集指定日期数据（需要 token 认证）"""
    import os
    expected_token = os.getenv("BACKFILL_TOKEN", "")
    if not expected_token or token != expected_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Unauthorized")
    try:
        collect_daily_data(date)
        calculate_heat_scores(date)
        update_lifecycle(date)
        calculate_rotation(date)
        calculate_money_flow_path(date)
        return {'status': 'ok', 'date': date, 'message': 'Backfill complete'}
    except Exception as e:
        from fastapi import HTTPException
        # 不暴露内部异常细节
        print(f'[backfill] Error for {date}: {e}')
        raise HTTPException(status_code=500, detail=f'Backfill failed for {date}')
