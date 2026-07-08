"""
白虎 V3.0 策略选股 API（全市场适配版）
独立于生命周期系统，返回5维度评分分解
"""
import threading
import concurrent.futures
import logging
from fastapi import APIRouter, Query
from db.connection import get_db
from db.session import get_db_session
from db.models import StockFlow
from strategies.baihu_v30 import get_kline_from_tdx, baihu_strategy_v30
from api.validators import validate_date
from services.signal_builder import build_signals_batch, build_signals_from_strategy_result, _enrich_signals_with_watchlist_extras

logger = logging.getLogger(__name__)

router = APIRouter()

# 线程本地K线缓存（避免重复请求通达信）
_kline_cache = {}
_cache_lock = threading.Lock()


def _get_kline_cached(ts_code, days=360):
    """带缓存的K线获取"""
    with _cache_lock:
        if ts_code in _kline_cache:
            return _kline_cache[ts_code]
    kline = get_kline_from_tdx(ts_code, days)
    if kline:
        with _cache_lock:
            _kline_cache[ts_code] = kline
    return kline


def _screen_one(ts_code, trade_date):
    """单只股票筛选（用于线程池）"""
    try:
        kline = _get_kline_cached(ts_code, 360)
        if kline and len(kline) >= 30:
            result = baihu_strategy_v30(kline)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                return result
    except Exception:
        logger.debug(f"_screen_one fallback", exc_info=True)
        logger.debug('handled exception', exc_info=True)
    return None


@router.get("/api/baihu-screen")
async def baihu_screen(date: str = Query(None)):
    """白虎V3.0强势回调选股（全市场适配）"""
    trade_date = validate_date(date)
    try:
        with get_db_session() as db:
            # 优先读预计算表（盘后定时扫描已落库 strategy_key='baihu_v30'），命中则跳过现场扫描
            _precomputed = await build_signals_from_strategy_result(db, 'baihu_v30', trade_date)
            if _precomputed is not None:
                return {
                    'date': trade_date,
                    'stocks': _precomputed,
                    'total': len(_precomputed),
                    'candidate_count': len(_precomputed),
                    'formula': _formula_meta(),
                    'message': 'ok(预计算)',
                }
            # 1. 获取全市场当日主力净流入>0的候选股票，按主力净流入降序取前50只
            candidates = db.query(StockFlow).filter(
                StockFlow.trade_date == trade_date,
                StockFlow.main_force_inflow > 0,
            ).order_by(StockFlow.main_force_inflow.desc()).limit(50).all()

            stock_list = [c.ts_code for c in candidates]
            stock_name_map = {c.ts_code: c.name for c in candidates}
            stock_sector_map = {c.ts_code: c.sector for c in candidates}

            if not stock_list:
                return {
                    'date': trade_date,
                    'stocks': [],
                    'total': 0,
                    'candidate_count': 0,
                    'formula': _formula_meta(),
                    'message': '无候选股票',
                }

            # 2. 并发执行白虎V3.0策略选股（最多20线程，30秒超时）
            hits = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(_screen_one, code, trade_date): code for code in stock_list}
                for future in concurrent.futures.as_completed(futures, timeout=30):
                    try:
                        result = future.result(timeout=5)
                        if result:
                            hits.append(result)
                    except Exception:
                        logger.debug(f"function fallback", exc_info=True)
                        logger.debug('handled exception', exc_info=True)

            # 3. 格式化结果（含5维度评分分解）
            results = []
            for h in hits:
                ts_code = h.get('ts_code', '')
                scores = h.get('scores', {})
                results.append({
                    'ts_code': ts_code,
                    'name': stock_name_map.get(ts_code, ''),
                    'sector': stock_sector_map.get(ts_code, ''),
                    'score': float(h.get('score', 0)),
                    'mode': h.get('mode', ''),
                    'close': float(h.get('close', 0)),
                    'ma5': float(h.get('ma5', 0)),
                    'ma10': float(h.get('ma10', 0)),
                    'ma20': float(h.get('ma20', 0)),
                    'change_pct': round(float(h.get('change_pct', 0)), 2),
                    'deviation': round(float(h.get('deviation', 0)), 2),
                    'rsi': round(float(h.get('rsi', 0)), 1),
                    'vol_ratio': round(float(h.get('vol_ratio', 0)), 1),
                    'lower_shadow': round(float(h.get('lower_shadow', 0)), 2),
                    '20day_gain': round(float(h.get('20day_gain', 0)), 2),
                    'distance_to_high_20': round(float(h.get('distance_to_high_20', 0)), 2),
                    'scores': scores,
                })

            # 按评分降序
            results.sort(key=lambda x: -x['score'])

            # 4. 构造完整 signal 数据（与自选股/重点关注口径一致）
            enriched_stocks = await build_signals_batch(
                results, db,
                code_key='ts_code', name_key='name', sector_key='sector',
                stage_key=None, strength_key='score',
                change_key='change_pct',
            )
            # 保留白虎原始字段
            stock_meta = {r['ts_code']: r for r in results}
            for s in enriched_stocks:
                meta = stock_meta.get(s['secCode'])
                if meta:
                    s['strategyScore'] = meta.get('score', 0)
                    s['strategyMode'] = meta.get('mode', '')
                    s['deviation'] = meta.get('deviation', 0)
                    s['rsi'] = meta.get('rsi', 0)
                    s['scores'] = meta.get('scores', {})
                    s['lowerShadow'] = meta.get('lower_shadow', 0)
                    s['ma20'] = meta.get('ma20', 0)
                    s['ma10'] = meta.get('ma10', 0)
                    s['ma5'] = meta.get('ma5', 0)
                    s['volRatio'] = meta.get('vol_ratio', 0)
                    s['20dayGain'] = meta.get('20day_gain', 0)
                    s['distanceToHigh20'] = meta.get('distance_to_high_20', 0)

            # 补充自选股个股模块字段（moneyFlow/hitTags/actionHint），让 SignalCard 显示完整信息
            await _enrich_signals_with_watchlist_extras(db, enriched_stocks)

            return {
                'date': trade_date,
                'stocks': enriched_stocks,
                'total': len(enriched_stocks),
                'candidate_count': len(stock_list),
                'formula': _formula_meta(),
        }
    except Exception as e:
        logger.exception(f'[baihu] Error')
        return {'error': str(e), 'stocks': []}


def _formula_meta():
    """白虎V3.0策略公式元数据（融合CodeBuddy量价筛选报告思路）"""
    return {
        'name': '白虎 V3.0 全市场适配版',
        'max_score': 10,
        'pass_threshold': 5,
        'modes': [
            {'key': 'pullback', 'name': '缩量回踩', 'desc': '最低价≤MA20且仍守20日线，缩量洗盘，下影线支撑'},
            {'key': 'breakout', 'name': '放量突破', 'desc': '收盘站上5/10日线，接近20日高点，放量转强'},
        ],
        'dimensions': [
            {'key': 'shadow', 'name': '下影线', 'max': 3, 'desc': '回踩模式：>2%金针探底(+3)，1-2%(+2)，0.5-1%(+1)'},
            {'key': 'change', 'name': '涨幅', 'max': 2, 'desc': '回踩模式-5%~10%最佳(+2)；突破模式0~9%最佳(+2)'},
            {'key': 'volume', 'name': '量能', 'max': 3, 'desc': '回踩缩量<80%(+2)、<110%(+1)；突破放量≥150%(+3)、≥120%(+2)'},
            {'key': 'breakout', 'name': '突破强度', 'max': 2, 'desc': '突破模式：距20日高点<1%(+2)、<3%(+1)'},
            {'key': 'upper_shadow', 'name': '上影线', 'max': 1, 'desc': '突破模式：上影线≤2%避免冲高回落(+1)'},
            {'key': 'rsi', 'name': 'RSI', 'max': 1, 'desc': '回踩30~55(+1)，可放宽到60；突破可放宽到70(+1)'},
            {'key': 'deviation', 'name': '偏离度', 'max': 2, 'desc': '回踩贴近MA20(+2)，允许到12%；突破允许到15%(+1)'},
        ],
        'hard_rules': [
            'MA20连续4天向上',
            '收盘价 > MA20（不破位）',
            '缩量回踩：最低价 ≤ MA20、偏离 < 12%、20日涨幅 > 15%',
            '放量突破：收盘 > MA5/MA10、距20日高点 < 5%、20日涨幅 > 10%',
        ],
        'v3_improvements': [
            '吸收CodeBuddy报告：既抓缩量回踩守20日线，也抓放量突破不破5/10日线',
            '双模式区分20日涨幅门槛，突破型放宽到10%，避免漏掉刚启动的右侧机会',
            '回踩模式涨幅放宽到-5%~10%、偏离放宽到12%，涨停回踩也能识别',
            '突破模式涨幅放宽到0%~12%，9%放量转强不再被错过',
            '候选池从科创创业板扩展到全市场，主板、创业板、科创板统一参与选股',
        ],
    }