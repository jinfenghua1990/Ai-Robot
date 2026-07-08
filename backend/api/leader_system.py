"""
双引擎决策系统 API
GET /api/leader/system - 板块+龙头双层决策结果
"""
import logging
from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool
from datetime import date, datetime
from sqlalchemy import func
from analyzers.leader_engine import run_leader_engine, should_switch
from analyzers.sector_engine import get_sector_ranking
from db.connection import get_db
from db.session import get_db_session
from db.models import WatchlistSignalDaily, StockFeaturesDaily, StockFlow
from services.leader_history_service import save_daily_leader
from services.signal_builder import build_signal_for_stock, build_signal_from_precomputed

router = APIRouter()
logger = logging.getLogger(__name__)


def _infer_market_suffix(code: str) -> str:
    """根据 6 位代码推断市场后缀"""
    if not code:
        return '.SH'
    c = str(code).strip()
    if '.' in c:
        return c.split('.', 1)[1].upper() or '.SH'
    if c.startswith(('6', '9', '5')):
        return '.SH'
    if c.startswith(('0', '3', '1')):
        return '.SZ'
    if c.startswith(('8', '4')):
        return '.BJ'
    return '.SH'


def _load_inflow_map(db, ts_codes: list, trade_date_str: str) -> dict:
    """批量查 StockFlow 主力净流入（游资详情页用）
    StockFlow 数据覆盖度远高于 StockFeaturesDaily，是主力净流入的权威源。
    1日 = 当日 main_force_inflow；3日/5日 = 累计；连续天数 = 连续 > 0 交易日数
    """
    inflow_map = {}
    if not ts_codes:
        return inflow_map
    # 归一化 ts_code + 纯 6 位 code
    pure_codes = []
    code_to_ts = {}
    for tc in ts_codes:
        if not tc:
            continue
        pure = tc.split('.')[0] if '.' in tc else tc
        suffix = _infer_market_suffix(pure)
        full_ts = f"{pure}{suffix}"
        if pure not in pure_codes:
            pure_codes.append(pure)
        code_to_ts[pure] = full_ts
    if not pure_codes:
        return inflow_map
    full_ts_list = [f"{c}.SH" if c.startswith(('6', '9', '5')) else f"{c}.SZ" if c.startswith(('0', '3', '1')) else f"{c}.BJ" for c in pure_codes]

    # 取最近 10 个交易日（含当日），用于计算 1日/3日/5日/连续
    rows = db.query(StockFlow).filter(
        StockFlow.ts_code.in_(full_ts_list)
    ).order_by(StockFlow.trade_date.desc()).limit(len(full_ts_list) * 10).all()

    # 按 ts_code 分组
    by_code = {}
    for r in rows:
        by_code.setdefault(r.ts_code, []).append(r)

    for full_ts in full_ts_list:
        records = by_code.get(full_ts, [])
        if not records:
            inflow_map[full_ts] = {
                'inflow_1d': 0, 'inflow_3d': 0, 'inflow_5d': 0,
                'flow_continuity': 0,
            }
            continue
        # StockFlow.main_force_inflow 单位是万元（之前其他查询是元，注意统一）
        # 这里按万元处理，前端展示"万"
        # 找到当前 trade_date 当日（若无则取最新）
        if trade_date_str:
            target_date = trade_date_str
            if hasattr(target_date, 'isoformat'):
                target_date = target_date.isoformat()
        else:
            target_date = None

        # 取当日的 main_force_inflow（按 trade_date 匹配）
        day1 = next((r for r in records if str(r.trade_date) == str(target_date)), None)
        inflow_1d = float(day1.main_force_inflow or 0) if day1 else 0

        # 3日累计：取 trade_date <= target_date 的 3 条，按 DESC 取前 3 条再求和
        sorted_recs = records  # 已经 desc
        inflow_3d = sum(float(r.main_force_inflow or 0) for r in sorted_recs[:3])
        inflow_5d = sum(float(r.main_force_inflow or 0) for r in sorted_recs[:5])

        # 连续净流入天数（从最近一天往前数 main_force_inflow > 0）
        continuity = 0
        for r in sorted_recs:
            if float(r.main_force_inflow or 0) > 0:
                continuity += 1
            else:
                break

        inflow_map[full_ts] = {
            'inflow_1d': inflow_1d * 10000,  # 万元 → 元（前端除以 10000 变万元显示）
            'inflow_3d': inflow_3d * 10000,
            'inflow_5d': inflow_5d * 10000,
            'flow_continuity': continuity,
        }
    return inflow_map


def _enrich_with_inflow(stocks: list, inflow_map: dict) -> None:
    """把 inflow 数据注入到每只股票的 mainForce 字段（inplace）"""
    if not stocks:
        return
    for s in stocks:
        if not s:
            continue
        ts = s.get('ts_code') or ''
        if not ts and s.get('secCode'):
            ts = f"{s.get('secCode')}{_infer_market_suffix(s.get('secCode', ''))}"
        inflow = inflow_map.get(ts, {}) if ts else {}
        mf = s.get('mainForce') or {'stage': '平衡', 'score': 50}
        if not isinstance(mf, dict):
            mf = {'stage': '平衡', 'score': 50}
        mf['inflow_1d'] = inflow.get('inflow_1d', 0)
        mf['inflow_3d'] = inflow.get('inflow_3d', 0)
        mf['inflow_5d'] = inflow.get('inflow_5d', 0)
        mf['flow_continuity'] = inflow.get('flow_continuity', 0)
        s['mainForce'] = mf


def _enrich_with_leader_meta(stocks: list, original_map: dict) -> None:
    """从 leader_engine 原始数据补回 stage/strength/consecutive_days/change_rate
    （_enrich_stock 转换时丢失的原始龙头字段）"""
    if not stocks:
        return
    for s in stocks:
        if not s:
            continue
        ts = s.get('ts_code') or ''
        if not ts and s.get('secCode'):
            ts = f"{s.get('secCode')}{_infer_market_suffix(s.get('secCode', ''))}"
        orig = original_map.get(ts, {}) if ts else {}
        if orig:
            s['stage'] = orig.get('stage') or s.get('stage') or s.get('lifecycleStage')
            s['strength'] = orig.get('strength') if orig.get('strength') is not None else s.get('strength')
            s['consecutive_days'] = orig.get('consecutive_days') if orig.get('consecutive_days') is not None else s.get('consecutive_days')
            s['change_rate'] = orig.get('change_rate') if orig.get('change_rate') is not None else s.get('change_rate')


async def _enrich_stock(stock: dict, db, precomputed_map: dict = None) -> dict:
    """将 leader_engine 输出的股票数据增强为完整 18 字段 signal
    优先读预计算表，未命中才 fallback 到 build_signal_for_stock
    """
    if not stock or not stock.get('ts_code'):
        return stock
    ts_code = stock['ts_code']
    code = ts_code.split('.')[0] if '.' in ts_code else ts_code
    name = stock.get('name', '')
    sector = stock.get('sector', '')
    try:
        precomputed = (precomputed_map or {}).get(ts_code)
        if precomputed:
            signal = await build_signal_from_precomputed(
                code, name, precomputed,
                stage=stock.get('stage'),
                strength=stock.get('strength'),
                consecutive_days=stock.get('consecutive_days'),
                lifecycle_stage=stock.get('stage'),
                db=db,
            )
        else:
            signal = await build_signal_for_stock(
                code, name, sector, db,
                stage=stock.get('stage'),
                strength=stock.get('strength'),
                change_rate=stock.get('change_rate'),
                consecutive_days=stock.get('consecutive_days'),
            )
        signal['leaderScore'] = stock.get('score', 0)
        signal['sectorScore'] = stock.get('sector_score')
        signal['sectorStateLabel'] = stock.get('sector_state_label')
        signal['details'] = stock.get('details')
        return signal
    except Exception as e:
        logger.warning(f' enrich {ts_code} failed: {e}')
        return stock


def _load_precomputed_map(db, ts_codes: list) -> dict:
    """同步查预计算表（最近交易日），返回 {ts_code: row}"""
    precomputed_map = {}
    if not ts_codes:
        return precomputed_map
    latest_date = db.query(func.max(WatchlistSignalDaily.trade_date)).scalar()
    if latest_date:
        rows = db.query(WatchlistSignalDaily).filter(
            WatchlistSignalDaily.trade_date == latest_date,
            WatchlistSignalDaily.ts_code.in_(ts_codes),
        ).all()
        for row in rows:
            precomputed_map[row.ts_code] = row
    return precomputed_map


_leader_cache = {'data': None, 'ts': 0, 'date': None}
_LEADER_CACHE_TTL = 5  # 5 秒结果缓存，避免短时间内重复计算

@router.get("/api/leader/system")
async def leader_system(target_date: str = Query(None, description="目标日期 YYYY-MM-DD")):
    """双引擎决策系统

    返回：
    - sector_filter: 板块引擎输出（strong/rotation/down）
    - leader: 主龙（唯一，含完整 signal 数据）
    - candidates: 候选龙（≤3只，含完整 signal 数据）
    - all_stocks: 热度池（前20，含完整 signal 数据）
    - switch_warning: 主龙切换预警
    """
    d = date.fromisoformat(target_date) if target_date else None
    today_str = target_date or datetime.now().strftime('%Y-%m-%d')

    # 5 秒结果缓存（同日内重复请求直接返回）
    import time as _time
    if (not target_date and _leader_cache['data']
            and _leader_cache['date'] == today_str
            and _time.time() - _leader_cache['ts'] < _LEADER_CACHE_TTL):
        return _leader_cache['data']

    result = await run_in_threadpool(run_leader_engine, d)

    # 切换预警：如果有候选且候选评分接近主龙
    switch_warning = None
    if result.get('leader') and result.get('candidates'):
        leader = result['leader']
        for c in result['candidates']:
            diff = leader['score'] - c['score']
            if diff <= 1.5 and c['change_rate'] > leader['change_rate']:
                should, reason = should_switch(leader, c)
                if should:
                    switch_warning = {
                        'new_candidate': c['name'],
                        'reason': reason,
                        'score_diff': round(diff, 1),
                    }
                    break

    # 自动写入龙头历史（主龙选出后记录）
    leader_raw = result.get('leader')
    trade_date = result.get('date')
    if leader_raw and trade_date:
        try:
            with get_db_session() as db:
                save_daily_leader(db, trade_date, leader_raw['sector'], leader_raw)
        except Exception as e:
            logger.warning(f'龙头历史写入失败: {e}')

    # 构造完整 signal 数据
    import asyncio
    with get_db_session() as db:
        # 批量查预计算表（最近交易日），命中则跳过现场计算（丢线程池避免阻塞事件循环）
        all_raw = ([leader_raw] if leader_raw else []) + result.get('candidates', []) + result.get('all_stocks', [])
        ts_codes = [s.get('ts_code') for s in all_raw if s and s.get('ts_code')]
        precomputed_map = await run_in_threadpool(_load_precomputed_map, db, ts_codes)

        tasks = []
        if leader_raw:
            tasks.append(_enrich_stock(leader_raw, db, precomputed_map))
        candidates_raw = result.get('candidates', [])
        for c in candidates_raw:
            tasks.append(_enrich_stock(c, db, precomputed_map))
        all_stocks_raw = result.get('all_stocks', [])
        for s in all_stocks_raw:
            tasks.append(_enrich_stock(s, db, precomputed_map))

        enriched = await asyncio.gather(*tasks, return_exceptions=True)

        idx = 0
        enriched_leader = None
        if leader_raw:
            r = enriched[idx]
            enriched_leader = r if not isinstance(r, Exception) else leader_raw
            idx += 1
        enriched_candidates = []
        for c in candidates_raw:
            r = enriched[idx]
            enriched_candidates.append(r if not isinstance(r, Exception) else c)
            idx += 1
        enriched_all = []
        for s in all_stocks_raw:
            r = enriched[idx]
            enriched_all.append(r if not isinstance(r, Exception) else s)
            idx += 1

    # 注入主力净流入（inflow 1日/3日/5日 + 连续天数）— 游资详情页用
    try:
        # 从 leader_engine 原始数据取 ts_code（enriched 后的 stock 只有 secCode）
        all_ts = []
        for src in (result.get('leader'),) + tuple(result.get('candidates') or []) + tuple(result.get('all_stocks') or []):
            if src and src.get('ts_code') and src['ts_code'] not in all_ts:
                all_ts.append(src['ts_code'])
        inflow_map = await run_in_threadpool(_load_inflow_map, db, all_ts, result.get('date'))
        _enrich_with_inflow([enriched_leader] if enriched_leader else [], inflow_map)
        _enrich_with_inflow(enriched_candidates, inflow_map)
        _enrich_with_inflow(enriched_all, inflow_map)
    except Exception as e:
        logger.warning(f'inflow enrichment failed: {e}')

    # 补回 leader_engine 原始字段（strength/连板/涨幅/stage）— 游资详情页用
    try:
        original_map = {}
        for src in (result.get('leader'),) + tuple(result.get('candidates') or []) + tuple(result.get('all_stocks') or []):
            if src and src.get('ts_code'):
                original_map[src['ts_code']] = src
        _enrich_with_leader_meta([enriched_leader] if enriched_leader else [], original_map)
        _enrich_with_leader_meta(enriched_candidates, original_map)
        _enrich_with_leader_meta(enriched_all, original_map)
    except Exception as e:
        logger.warning(f'leader_meta enrichment failed: {e}')

    response = {
        'leader': enriched_leader,
        'candidates': enriched_candidates,
        'all_stocks': enriched_all,
        'all_count': result.get('all_count', 0),
        'sector_filter': result.get('sector_filter'),
        'switch_warning': switch_warning,
        'date': result.get('date'),
        'message': result.get('message', 'ok'),
    }

    # 写入 5 秒缓存
    if not target_date:
        _leader_cache['data'] = response
        _leader_cache['ts'] = _time.time()
        _leader_cache['date'] = today_str

    return response


@router.get("/api/leader/sector-status")
def sector_status(target_date: str = Query(None)):
    """板块状态总览（单独接口，轻量版）"""
    d = date.fromisoformat(target_date) if target_date else None
    return get_sector_ranking(d)
