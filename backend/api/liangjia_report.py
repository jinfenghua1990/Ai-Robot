"""
📋 量价报告策略 API
按 CodeBuddy 量价筛选报告逻辑，返回3层分层结果：
- priority: 优先买入（只做条件触发，不追高）
- wait:     等回踩确认（逻辑尚可，位置需优化）
- avoid:    暂不参与（高位、破位或性价比不足）

每只股票含：5种形态分类 + 关键指标 + 具体交易计划（买入价位+止损价位）
"""
import logging
import threading
import concurrent.futures
from fastapi import APIRouter, Query
from db.session import get_db_session
from db.models import StockFlow
from strategies.liangjia_report import get_kline_from_tdx, liangjia_report_strategy
from api.validators import validate_date
from services.signal_builder import build_signals_batch, build_signals_from_strategy_result, _enrich_signals_with_watchlist_extras

logger = logging.getLogger(__name__)

router = APIRouter()

_kline_cache = {}
_cache_lock = threading.Lock()


def _get_kline_cached(ts_code, days=60):
    with _cache_lock:
        if ts_code in _kline_cache:
            return _kline_cache[ts_code]
    kline = get_kline_from_tdx(ts_code, days)
    if kline:
        with _cache_lock:
            _kline_cache[ts_code] = kline
    return kline


def _screen_one(ts_code, trade_date):
    try:
        kline = _get_kline_cached(ts_code, 60)
        if kline and len(kline) >= 30:
            result = liangjia_report_strategy(kline)
            if result:
                result['ts_code'] = ts_code
                if trade_date:
                    result['trade_date'] = trade_date
                return result
    except Exception:
        logger.debug('liangjia _screen_one fallback', exc_info=True)
    return None


@router.get("/api/liangjia-report")
async def liangjia_report(date: str = Query(None)):
    """量价报告策略选股（3层分层 + 交易计划）"""
    trade_date = validate_date(date)
    try:
        with get_db_session() as db:
            # 优先读预计算表
            _precomputed = await build_signals_from_strategy_result(db, 'liangjia_report', trade_date)
            if _precomputed is not None:
                return _format_response(trade_date, _precomputed, len(_precomputed), 'ok(预计算)')

            # 1. 候选池：全市场当日主力净流入>0，按主力净流入降序取前80只
            candidates = db.query(StockFlow).filter(
                StockFlow.trade_date == trade_date,
                StockFlow.main_force_inflow > 0,
            ).order_by(StockFlow.main_force_inflow.desc()).limit(80).all()

            stock_list = [c.ts_code for c in candidates]
            stock_name_map = {c.ts_code: c.name for c in candidates}
            stock_sector_map = {c.ts_code: c.sector for c in candidates}

            if not stock_list:
                return _format_response(trade_date, [], 0, '无候选股票')

            # 2. 并发执行量价报告选股
            hits = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(_screen_one, code, trade_date): code for code in stock_list}
                for future in concurrent.futures.as_completed(futures, timeout=60):
                    try:
                        result = future.result(timeout=5)
                        if result:
                            hits.append(result)
                    except Exception:
                        logger.debug('liangjia future fallback', exc_info=True)

            # 3. 格式化结果
            results = []
            for h in hits:
                ts_code = h.get('ts_code', '')
                results.append({
                    'ts_code': ts_code,
                    'name': stock_name_map.get(ts_code, ''),
                    'sector': stock_sector_map.get(ts_code, ''),
                    'score': h.get('score', 0),
                    'pattern': h.get('pattern', ''),
                    'pattern_desc': h.get('pattern_desc', ''),
                    'tier': h.get('tier', ''),
                    'tier_label': h.get('tier_label', ''),
                    'close': float(h.get('close', 0)),
                    'change_pct': round(float(h.get('change_pct', 0)), 2),
                    'gain5d': round(float(h.get('gain5d', 0)), 2),
                    'gain20d': round(float(h.get('gain20d', 0)), 2),
                    'vol_ratio_20': round(float(h.get('vol_ratio_20', 0)), 2),
                    'distance_to_high_20': round(float(h.get('distance_to_high_20', 0)), 2),
                    'deviation_ma20': round(float(h.get('deviation_ma20', 0)), 2),
                    'rsi': round(float(h.get('rsi', 0)), 1),
                    'ma5': float(h.get('ma5', 0)),
                    'ma10': float(h.get('ma10', 0)),
                    'ma20': float(h.get('ma20', 0)),
                    'ma20_rising': bool(h.get('ma20_rising', False)),
                    'bull_alignment': bool(h.get('bull_alignment', False)),
                    'trade_plan': h.get('trade_plan', {}),
                })

            # 按 tier 分组排序：priority > wait > avoid，同层按评分降序
            tier_order = {'priority': 0, 'wait': 1, 'avoid': 2}
            results.sort(key=lambda x: (tier_order.get(x['tier'], 9), -x['score']))

            # 4. 构造完整 signal 数据
            enriched_stocks = await build_signals_batch(
                results, db,
                code_key='ts_code', name_key='name', sector_key='sector',
                stage_key=None, strength_key='score',
                change_key='change_pct',
            )
            # key 用6位纯代码匹配（build_signals_batch 会把 ts_code 转成 secCode 6位格式）
            stock_meta = {r['ts_code'].split('.')[0]: r for r in results}
            for s in enriched_stocks:
                meta = stock_meta.get(s['secCode'])
                if meta:
                    s['strategyScore'] = meta.get('score', 0)
                    s['pattern'] = meta.get('pattern', '')
                    s['patternDesc'] = meta.get('pattern_desc', '')
                    s['tier'] = meta.get('tier', '')
                    s['tierLabel'] = meta.get('tier_label', '')
                    s['gain5d'] = meta.get('gain5d', 0)
                    s['gain20d'] = meta.get('gain20d', 0)
                    s['volRatio20'] = meta.get('vol_ratio_20', 0)
                    s['distanceToHigh20'] = meta.get('distance_to_high_20', 0)
                    s['deviationMa20'] = meta.get('deviation_ma20', 0)
                    s['ma5'] = meta.get('ma5', 0)
                    s['ma10'] = meta.get('ma10', 0)
                    s['ma20'] = meta.get('ma20', 0)
                    s['tradePlan'] = meta.get('trade_plan', {})
                    s['strategyMode'] = meta.get('pattern', '')

            # 补充自选股个股模块字段
            await _enrich_signals_with_watchlist_extras(db, enriched_stocks)

            return _format_response(trade_date, enriched_stocks, len(stock_list), 'ok')
    except Exception as e:
        logger.exception('[liangjia] Error')
        return {'error': str(e), 'stocks': [], 'groups': {}}


def _format_response(trade_date, stocks, candidate_count, message):
    """按3层分层分组返回"""
    groups = {'priority': [], 'wait': [], 'avoid': []}
    for s in stocks:
        tier = s.get('tier', 'avoid')
        if tier in groups:
            groups[tier].append(s)
    return {
        'date': trade_date,
        'stocks': stocks,
        'groups': groups,
        'total': len(stocks),
        'priority_count': len(groups['priority']),
        'wait_count': len(groups['wait']),
        'avoid_count': len(groups['avoid']),
        'candidate_count': candidate_count,
        'formula': _formula_meta(),
        'message': message,
    }


def _formula_meta():
    """白虎V4.0策略公式元数据"""
    return {
        'name': '白虎V4.0（CodeBuddy）',
        'desc': '按量价筛选报告逻辑，5种形态分类 + 3层分层 + 交易计划',
        'patterns': [
            {'key': 'pullback', 'name': '缩量回踩', 'desc': '最低价≤MA20、缩量、收盘守MA20'},
            {'key': 'breakout', 'name': '放量突破', 'desc': '收盘>MA5/MA10、放量、接近20日高点'},
            {'key': 'trend', 'name': '趋势延续', 'desc': '多头排列、均线结构尚可'},
            {'key': 'repair', 'name': '缩量修复', 'desc': '缩量、跌破MA5/MA10、守MA20'},
            {'key': 'weak', 'name': '结构偏弱', 'desc': '跌破MA20或双线破位'},
        ],
        'tiers': [
            {'key': 'priority', 'name': '优先买入', 'color': '#ef4444', 'desc': '只做条件触发，不追高'},
            {'key': 'wait', 'name': '等回踩确认', 'color': '#f59e0b', 'desc': '逻辑尚可，位置需优化'},
            {'key': 'avoid', 'name': '暂不参与', 'color': '#6b7280', 'desc': '高位、破位或性价比不足'},
        ],
        'dimensions': [
            {'key': 'gain5d', 'name': '近5日涨跌', 'desc': '短期动能指标'},
            {'key': 'vol_ratio_20', 'name': '20日量比', 'desc': '当日成交量/过去20日均量'},
            {'key': 'distance_to_high_20', 'name': '距20日高点', 'desc': '位置高低'},
            {'key': 'deviation_ma20', 'name': 'MA20乖离', 'desc': '乖离率>15%降级'},
        ],
        'rules': [
            '开盘高开>3%不追，等第一次回踩不破分时均线',
            '优先看5日线和10日线附近缩量承接',
            '突破型必须放量站上前高或平台上沿',
            '放量跌破20日线，短线计划失效',
            '冲高回落且成交量放大，次日不接',
        ],
    }
