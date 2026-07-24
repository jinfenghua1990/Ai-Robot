"""
统一信号构造器：为任意股票代码构造与自选股完全一致的 18 字段 signal 数据结构

共享字段：secCode/secName/signal/signalLabel/signalColor/riskLevel/score/reasons/
         positiveFactors/negativeFactors/sector/sectorTrend/position/marketState/
         buyPower/qualityStatus/quote/bsSignal

被以下 API 共用：
- /api/focus-stocks        重点关注
- /api/screener            智能选股（热度/青龙）
- /api/baihu-screen        白虎V3.0
- /api/leader/system       双引擎决策
- /api/panorama/stocks     板块全景个股
"""
import logging
from utils.cache import BoundedDict
import time
import asyncio
import json
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)
from db.connection import get_db
from db.session import get_db_session
from api.watchlist._shared import get_quote, fetch_kline_cached
from analyzers.strategy_engine import _find_sector_for_stock, _get_sector_trend
from analyzers.buy_power import calc_buy_power_for_signal
from analyzers.market_state import get_latest_state, compute_quality_from_features
from analyzers.stock_scores import calc_sentiment, calc_risk, calc_momentum, calc_main_force, calc_technical, calc_sector_resonance


# ============================================================
# 生命周期阶段查询（统一入口，所有接口共用，避免重复代码）
# ============================================================
_lifecycle_cache: Dict[str, Optional[str]] = {}
_LIFECYCLE_CACHE_TTL = 300  # 5分钟缓存（LeaderLifecycle 每日更新一次）

def _get_lifecycle_stage(db, ts_code: str) -> Optional[str]:
    """查询单只股票的最新生命周期阶段（LeaderLifecycle 表），带缓存"""
    cached = _lifecycle_cache.get(ts_code)
    if cached and time.time() - cached[1] < _LIFECYCLE_CACHE_TTL:
        return cached[0]
    from db.models import LeaderLifecycle
    _ll = db.query(LeaderLifecycle).filter(
        LeaderLifecycle.ts_code == ts_code
    ).order_by(LeaderLifecycle.trade_date.desc()).first()
    stage = _ll.stage if _ll else None
    _lifecycle_cache[ts_code] = (stage, time.time())
    return stage

def _get_lifecycle_map(db, ts_codes: List[str], trade_date: str = None) -> Dict[str, str]:
    """批量查询多只股票的生命周期阶段（默认取最新交易日），用于批量场景"""
    if not ts_codes:
        return {}
    from db.models import LeaderLifecycle
    from sqlalchemy import func
    if trade_date:
        rows = db.query(LeaderLifecycle).filter(
            LeaderLifecycle.trade_date == trade_date,
            LeaderLifecycle.ts_code.in_(ts_codes),
        ).all()
    else:
        latest_date = db.query(func.max(LeaderLifecycle.trade_date)).scalar()
        if not latest_date:
            return {}
        rows = db.query(LeaderLifecycle).filter(
            LeaderLifecycle.trade_date == latest_date,
            LeaderLifecycle.ts_code.in_(ts_codes),
        ).all()
    return {r.ts_code: r.stage for r in rows}


# ============================================================
# BS 区间计算：SuperTrend 天然交替 B→S→B→S，每个 B-S 对构成一个持仓/空仓区间
# 区间信息暴露给前端：起止日期、起止价格、持有天数、区间盈亏%
# ============================================================
def _calc_bs_interval(bs_signals: list, current_price: float = 0.0) -> dict:
    """
    从 BS 信号序列中提取当前所在区间信息。

    返回结构：
    {
        'state': 'holding' | 'empty' | 'unknown',
        'start_date': str,      'start_price': float,
        'end_date': str,        # S 触发时为卖出日；当前持仓中为最近K线日期
        'end_price': float,
        'hold_days': int,
        'pnl_pct': float,      # 区间盈亏%（仅 holding 时有意义；空仓=区间跌幅）
    }
    """
    if not bs_signals:
        return {'state': 'unknown'}

    last = bs_signals[-1]
    last_type = last.get('type')
    last_date = last.get('date', '')
    last_price = last.get('price', 0.0) or 0.0

    # 找到上一个反向信号（S→B 时找前一个 B；B→S 时找前一个 S）
    prev_idx = None
    for i in range(len(bs_signals) - 2, -1, -1):
        if bs_signals[i].get('type') != last_type:
            prev_idx = i
            break

    # 区间盈亏%（基于当前价 / S 价）
    ref_price = current_price or last_price
    if last_type == 'B':
        # 当前持仓中：B 起点 → 今天（仍未卖出）
        start_date = last_date
        start_price = last_price
        end_date = ''  # 未结束
        end_price = ref_price
        state = 'holding'
        if prev_idx is not None:
            # 上一个 S 之后才有这个 B —— B 起点 = 当前 B 信号日
            pass
        pnl_pct = ((ref_price - start_price) / start_price * 100) if start_price else 0.0
    elif last_type == 'S':
        # 已平仓：前一个 B → 当前 S
        state = 'empty'
        end_date = last_date
        end_price = last_price
        if prev_idx is not None:
            b_sig = bs_signals[prev_idx]
            start_date = b_sig.get('date', '')
            start_price = b_sig.get('price', 0.0) or 0.0
        else:
            start_date = ''
            start_price = 0.0
        pnl_pct = ((end_price - start_price) / start_price * 100) if start_price else 0.0
    else:
        return {'state': 'unknown'}

    # 持有天数
    hold_days = 0
    if start_date:
        try:
            from datetime import datetime
            sd = datetime.strptime(str(start_date)[:10].replace('-', ''), '%Y%m%d')
            ed_str = str(end_date)[:10].replace('-', '') if end_date else datetime.now().strftime('%Y%m%d')
            ed = datetime.strptime(ed_str, '%Y%m%d')
            hold_days = max(0, (ed - sd).days)
        except Exception:
            hold_days = 0

    return {
        'state': state,
        'start_date': str(start_date)[:10] if start_date else '',
        'start_price': round(start_price, 3) if start_price else 0.0,
        'end_date': str(end_date)[:10] if end_date else '',
        'end_price': round(end_price, 3) if end_price else 0.0,
        'hold_days': hold_days,
        'pnl_pct': round(pnl_pct, 2),
    }


async def build_signal_for_stock(
    code: str,
    name: str,
    sector_name: str,
    db,
    *,
    stage: Optional[str] = None,
    strength: Optional[float] = None,
    change_rate: Optional[float] = None,
    consecutive_days: Optional[int] = None,
    extra_positive: Optional[List[dict]] = None,
    extra_negative: Optional[List[dict]] = None,
    lifecycle_stage: Optional[str] = None,
) -> dict:
    """为单只股票构造与自选股完全一致的 signal 数据结构

    可选参数用于在基础行情之上叠加策略维度信息（如龙头阶段、强度等）。
    """
    # 延迟导入避免与 api.screener 循环引用
    from api.bs_signals import _generate_bs_signals
    from services.indicators import calc_rsi as _calc_rsi

    # 并发获取行情和K线
    quote, klines = await asyncio.gather(
        get_quote(code),
        fetch_kline_cached(code, 60),
        return_exceptions=True,
    )
    if isinstance(quote, Exception):
        quote = None
    if isinstance(klines, Exception):
        klines = []

    # 查找板块 + 板块趋势
    ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
    sector = _find_sector_for_stock(db, ts_code) or sector_name
    sector_trend = _get_sector_trend(db, sector, 7) if sector else {"sector": "", "available": False}

    # 自动查 LeaderLifecycle 真实生命周期阶段（调用方未传时 fallback 查询）
    if lifecycle_stage is None:
        lifecycle_stage = _get_lifecycle_stage(db, ts_code)

    # 获取 BS 信号 + 技术指标（KDJ/MACD/支撑/阻力）
    bs_signal = None
    bs_reasons = []
    bs_interval = {'state': 'unknown'}
    indicators = {}
    try:
        if klines and len(klines) > 0:
            # _generate_bs_signals 返回 12 个值：signals, dif, dea, macd, ma5, ma20, k, d, j, support, resistance, trend
            bs_signals, dif, dea, macd, ma5, ma20, k_vals, d_vals, j_vals, support, resistance, _trend = _generate_bs_signals(klines)
            if bs_signals:
                last = bs_signals[-1]
                bs_signal = last.get('type')
                bs_reasons = last.get('reasons', [])
                bs_interval = _calc_bs_interval(bs_signals, quote.get('price') if quote else 0.0)
                # 提取最新 KDJ/MACD/支撑/阻力（最后一根 K 线对应的值）
                def _last(arr):
                    return arr[-1] if arr and arr[-1] is not None else None
                indicators = {
                    'macd': round(_last(macd), 4) if _last(macd) is not None else None,
                    'dif': round(_last(dif), 4) if _last(dif) is not None else None,
                    'dea': round(_last(dea), 4) if _last(dea) is not None else None,
                    'kdj_k': round(_last(k_vals), 2) if _last(k_vals) is not None else None,
                    'kdj_d': round(_last(d_vals), 2) if _last(d_vals) is not None else None,
                    'kdj_j': round(_last(j_vals), 2) if _last(j_vals) is not None else None,
                    'ma5': round(_last(ma5), 2) if _last(ma5) is not None else None,
                    'ma20': round(_last(ma20), 2) if _last(ma20) is not None else None,
                    'support': round(_last(support), 2) if _last(support) is not None else None,
                    'resistance': round(_last(resistance), 2) if _last(resistance) is not None else None,
                    'rsi': round(_last(_calc_rsi([k.get('close', 0.0) for k in klines], 14)), 1) if klines and len(klines) >= 15 else None,
                }
    except Exception as e:
        logger.debug(f'生成 BS 信号失败，跳过: {e}')

    price = quote['price'] if quote else 0
    change_pct = quote['changePct'] if quote else (change_rate or 0)

    # 信号标签（仅显示 BS 状态；区间详情在下方独立分组展示）
    bs_pnl = bs_interval.get('pnl_pct', 0.0) if bs_interval else 0.0
    if bs_signal == 'B':
        signal_label = 'B 持仓中'
        signal_color = '#ef4444'
        signal_type = 'ADD'
    elif bs_signal == 'S':
        signal_label = 'S 已平仓'
        signal_color = '#f97316'
        signal_type = 'SELL'
    else:
        signal_label, signal_color, signal_type = '关注', '#3b82f6', 'WATCH'

    # reasons / positiveFactors / negativeFactors
    reasons = []
    positive_factors = []
    negative_factors = []

    if bs_reasons:
        reasons.extend(bs_reasons)
    if quote:
        reasons.append(f'当日涨跌: {change_pct:+.2f}%')
    if stage:
        reasons.append(f'策略阶段: {stage}')
    if bs_pnl:
        reasons.append(f'BS区间盈亏: {bs_pnl:+.2f}%')

    if bs_signal == 'B':
        positive_factors.append({'factor': 'BS买入', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend突破', 'weight': 2})
    if change_pct > 0:
        positive_factors.append({'factor': '当日上涨', 'detail': f'涨幅 {change_pct:+.2f}%', 'weight': 1})
    if sector_trend.get('available') and sector_trend.get('heat_trend') == 'up':
        positive_factors.append({'factor': '板块升温', 'detail': f'板块热度上升至 {sector_trend["latest_heat"]:.1f}', 'weight': 1})
    if sector_trend.get('available') and sector_trend.get('flow_direction') == 'inflow':
        positive_factors.append({'factor': '资金流入', 'detail': f'净流入 {sector_trend["total_net_flow"]:.0f}万', 'weight': 1})

    if bs_signal == 'S':
        negative_factors.append({'factor': 'BS卖出', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend跌破', 'weight': -2})
    if change_pct < 0:
        negative_factors.append({'factor': '当日下跌', 'detail': f'跌幅 {change_pct:+.2f}%', 'weight': -1})
    if sector_trend.get('available') and sector_trend.get('heat_trend') == 'down':
        negative_factors.append({'factor': '板块降温', 'detail': f'板块热度下降至 {sector_trend["latest_heat"]:.1f}', 'weight': -1})
    if sector_trend.get('available') and sector_trend.get('flow_direction') == 'outflow':
        negative_factors.append({'factor': '资金流出', 'detail': f'净流出 {abs(sector_trend["total_net_flow"]):.0f}万', 'weight': -1})

    # 策略维度附加因素（兼容新旧命名）
    if stage:
        if stage in ('突破', '加速', '启动', '发酵'):
            positive_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段龙头', 'weight': 2})
        elif stage == '主升':
            positive_factors.append({'factor': '主升阶段', 'detail': f'{consecutive_days or 0}连板', 'weight': 1})
            negative_factors.append({'factor': '高位风险', 'detail': '连板高度较大，回调风险增加', 'weight': -1})
        elif stage in ('分歧', '衰退', '退潮'):
            negative_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段，谨慎参与', 'weight': -2})
    if strength and strength > 50:
        positive_factors.append({'factor': '强度领先', 'detail': f'强度评分 {strength:.0f}', 'weight': 1})
    if consecutive_days and consecutive_days >= 3:
        positive_factors.append({'factor': '连板强势', 'detail': f'{consecutive_days}连板', 'weight': 1})

    if extra_positive:
        positive_factors.extend(extra_positive)
    if extra_negative:
        negative_factors.extend(extra_negative)

    # === 停牌检查 ===
    is_suspended = False
    try:
        from sqlalchemy import text
        from datetime import date as d
        today_str = d.today().isoformat()
        _s_ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        sus = db.execute(text(
            "SELECT 1 FROM suspend_stock_daily WHERE ts_code=:code AND trade_date=:d"
        ), {'code': _s_ts_code, 'd': today_str}).scalar()
        is_suspended = bool(sus)
        if is_suspended:
            positive_factors = []
            negative_factors = [{'factor': '停牌', 'detail': '当日停牌，无交易', 'weight': -3}]
    except Exception:
        logger.debug("signal_builder: factor init fallback", exc_info=False)

    # === 融资融券因子 ===
    if not is_suspended:
        try:
            margin_rows = db.execute(text("""
                SELECT trade_date, rzye, rqye, rzmre
                FROM stock_margin_data
                WHERE ts_code=:code ORDER BY trade_date DESC LIMIT 3
            """), {'code': _s_ts_code}).fetchall()
            if len(margin_rows) >= 2:
                rzye_0 = float(margin_rows[0][1] or 0)
                rzye_1 = float(margin_rows[1][1] or 0)
                if rzye_0 > 0 and rzye_1 > 0:
                    margin_chg = (rzye_0 - rzye_1) / rzye_1
                    if margin_chg > 0.02:
                        positive_factors.append({'factor': '融资加仓', 'detail': f'融资余额日增 {margin_chg*100:.1f}%', 'weight': 2})
                    elif margin_chg > 0.005:
                        positive_factors.append({'factor': '融资微增', 'detail': f'融资余额日增 {margin_chg*100:.1f}%', 'weight': 1})
                    elif margin_chg < -0.02:
                        negative_factors.append({'factor': '融资减仓', 'detail': f'融资余额日降 {abs(margin_chg)*100:.1f}%', 'weight': -2})
                    elif margin_chg < -0.005:
                        negative_factors.append({'factor': '融资微降', 'detail': f'融资余额日降 {abs(margin_chg)*100:.1f}%', 'weight': -1})
        except Exception:
            logger.debug("signal_builder: margin factor failed", exc_info=False)

    # === 波浪信号交叉验证 ===
    if not is_suspended:
        try:
            pure_code = code.replace('.SH','').replace('.SZ','')
            wave = db.execute(text("""
                SELECT signal, confidence, reason FROM stock_wave_signals
                WHERE code=:c AND signal_date=:d ORDER BY id DESC LIMIT 1
            """), {'c': pure_code, 'd': d.today().isoformat()}).first()
            if wave:
                wsig, wconf, wreason = wave
                if wsig == 'buy' and float(wconf or 0) > 50:
                    positive_factors.append({'factor': '波浪买入', 'detail': f'波浪信号: {str(wreason)[:30]}', 'weight': 1})
                elif wsig == 'sell' and float(wconf or 0) > 50:
                    negative_factors.append({'factor': '波浪卖出', 'detail': f'波浪信号: {str(wreason)[:30]}', 'weight': -1})
        except Exception:
            logger.debug("signal_builder: margin factor failed", exc_info=False)

    score = len(positive_factors) - len(negative_factors)
    reasons.append(f'综合评分: {"看多" if score > 0 else "看空" if score < 0 else "中性"} → {signal_label}')

    # 市场状态 + 购买力 + 质量状态
    market_state_data = get_latest_state(code) or {'market_state': 'PENDING', 'reasons': ['待计算']}
    buy_power = calc_buy_power_for_signal(quote, sector_trend, bs_signal)

    ms = market_state_data.get('market_state', 'PENDING')
    features = market_state_data.get('features') or {}
    is_junk = 'ST' in (name or '').upper() or '退' in (name or '')
    quality_status = compute_quality_from_features(ms, features, is_junk)

    # 6 维状态评分
    pos_dict = None  # signal_builder 不涉及持仓
    sentiment = calc_sentiment(quote, sector_trend, features)
    risk = calc_risk(features, buy_power, pos_dict)
    momentum = calc_momentum(sector_trend, features)
    main_force = calc_main_force(quote, features, sector_trend)
    technical = calc_technical(features)
    sector_resonance = calc_sector_resonance(sector_trend, features)

    return {
        'secCode': code,
        'secName': name,
        'signal': signal_type,
        'signalLabel': signal_label,
        'signalColor': signal_color,
        'riskLevel': risk.get('stage', '低危') if isinstance(risk, dict) else '低危',
        'score': max(0, min(100, (score + 10) * 5)),  # 归一化 -4~4 → 0~100
        'reasons': reasons,
        'positiveFactors': positive_factors,
        'negativeFactors': negative_factors,
        'sector': sector or '',
        'sectorTrend': sector_trend,
        'quote': quote,
        'bsSignal': bs_signal,
        'bsInterval': bs_interval,
        'indicators': indicators,  # KDJ/MACD/MA 技术指标（最新一根 K 线）
        'position': {
            'profitPct': 0,
            'posPct': 0,
            'dayProfit': 0,
            'dayProfitPct': change_pct,
            'count': consecutive_days or 0,
            'price': price,
            'costPrice': 0,
            'value': 0,
            'profit': 0,
        },
        'qualityStatus': quality_status,
        'buyPower': buy_power,
        'marketState': market_state_data,
        'lifecycleStage': lifecycle_stage,
        'sentiment': sentiment,
        'risk': risk,
        'momentum': momentum,
        'mainForce': main_force,
        'technical': technical,
        'sectorResonance': sector_resonance,
    }


async def build_signals_batch(
    stocks: List[dict],
    db,
    *,
    code_key: str = 'code',
    name_key: str = 'name',
    sector_key: str = 'sector',
    stage_key: Optional[str] = None,
    strength_key: Optional[str] = None,
    change_key: Optional[str] = None,
    days_key: Optional[str] = None,
    batch_size: int = 20,
) -> List[dict]:
    """批量构造 signal 数据（分批并发，避免新浪限流）

    Args:
        stocks: 股票列表（dict）
        code_key/name_key/sector_key: 字段名映射
        stage_key/strength_key/change_key/days_key: 可选的策略维度字段名
        batch_size: 每批并发数
    """
    # 收集所有 ts_code，批量查 LeaderLifecycle 真实生命周期阶段
    _all_ts_codes = []
    for s in stocks:
        code = s.get(code_key) or s.get('ts_code') or s.get('secCode') or ''
        if '.' not in code and len(code) == 6:
            code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        if '.' in code:
            _all_ts_codes.append(code)
    lifecycle_map = _get_lifecycle_map(db, _all_ts_codes)

    all_signals = []
    for i in range(0, len(stocks), batch_size):
        batch = stocks[i:i + batch_size]
        tasks = []
        for s in batch:
            code = s.get(code_key) or s.get('ts_code') or s.get('secCode') or ''
            # ts_code 形如 "600000.SH"，提取6位数字
            if '.' in code:
                code = code.split('.')[0]
            if not code or len(code) != 6:
                continue
            ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
            name = s.get(name_key) or s.get('secName') or ''
            sector = s.get(sector_key) or ''
            kwargs = {}
            if stage_key and s.get(stage_key):
                kwargs['stage'] = s[stage_key]
            if strength_key and s.get(strength_key) is not None:
                kwargs['strength'] = float(s[strength_key])
            if change_key and s.get(change_key) is not None:
                kwargs['change_rate'] = float(s[change_key])
            if days_key and s.get(days_key) is not None:
                kwargs['consecutive_days'] = int(s[days_key])
            kwargs['lifecycle_stage'] = lifecycle_map.get(ts_code) or '未入选'
            tasks.append(build_signal_for_stock(code, name, sector, db, **kwargs))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if not isinstance(r, Exception) and r is not None:
                all_signals.append(r)
    return all_signals


async def build_signal_from_precomputed(
    code: str,
    name: str,
    precomputed_row,
    *,
    stage: Optional[str] = None,
    strength: Optional[float] = None,
    consecutive_days: Optional[int] = None,
    extra_positive: Optional[List[dict]] = None,
    extra_negative: Optional[List[dict]] = None,
    lifecycle_stage: Optional[str] = None,
    db=None,
) -> dict:
    """从预计算表行 + 实时行情组装 signal（消除 K线/BS/板块/市场状态的现场计算）

    与 build_signal_for_stock 返回结构完全一致，但跳过最慢的部分：
    - 不拉 K线（预计算已存 bs_signal）
    - 不查板块趋势（预计算已存 sector_trend_json）
    - 不查市场状态（预计算已存 market_state_json）
    - 仅拉实时 quote（30s缓存）
    """
    # 实时行情（30s缓存，盘后为收盘价）
    quote = await get_quote(code)

    # 自动查 LeaderLifecycle 真实生命周期阶段（调用方未传时 fallback 查询）
    if lifecycle_stage is None:
        _ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        if db is not None:
            lifecycle_stage = _get_lifecycle_stage(db, _ts_code)
        else:
            with get_db_session() as _db:
                lifecycle_stage = _get_lifecycle_stage(_db, _ts_code)

    # 从预计算行读数据
    sector = precomputed_row.sector or ''
    sector_trend = json.loads(precomputed_row.sector_trend_json or '{}')
    market_state_data = json.loads(precomputed_row.market_state_json or '{}')
    bs_signal = precomputed_row.bs_signal
    bs_reasons = json.loads(precomputed_row.bs_reasons_json or '[]')
    quality_status = precomputed_row.quality_status
    buy_power = json.loads(precomputed_row.buy_power_base) if precomputed_row.buy_power_base else {'score': 0, 'level': '弱', 'color': '#3b82f6', 'dimensions': {}}
    precomputed_change_rate = float(precomputed_row.change_rate or 0) if precomputed_row.change_rate else 0

    price = quote['price'] if quote else 0
    change_pct = quote['changePct'] if quote else precomputed_change_rate

    # 信号标签
    if bs_signal == 'B':
        signal_label, signal_color, signal_type = '买入', '#ef4444', 'ADD'
    elif bs_signal == 'S':
        signal_label, signal_color, signal_type = '减仓防守', '#f97316', 'SELL'
    else:
        signal_label, signal_color, signal_type = '关注', '#3b82f6', 'WATCH'

    # reasons / positiveFactors / negativeFactors（与 build_signal_for_stock 一致）
    reasons = []
    positive_factors = []
    negative_factors = []

    if bs_reasons:
        reasons.extend(bs_reasons)
    if quote:
        reasons.append(f'当日涨跌: {change_pct:+.2f}%')
    if stage:
        reasons.append(f'策略阶段: {stage}')

    if bs_signal == 'B':
        positive_factors.append({'factor': 'BS买入', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend突破', 'weight': 2})
    if change_pct > 0:
        positive_factors.append({'factor': '当日上涨', 'detail': f'涨幅 {change_pct:+.2f}%', 'weight': 1})
    if sector_trend.get('available') and sector_trend.get('heat_trend') == 'up':
        positive_factors.append({'factor': '板块升温', 'detail': f'板块热度上升至 {sector_trend["latest_heat"]:.1f}', 'weight': 1})
    if sector_trend.get('available') and sector_trend.get('flow_direction') == 'inflow':
        positive_factors.append({'factor': '资金流入', 'detail': f'净流入 {sector_trend["total_net_flow"]:.0f}万', 'weight': 1})

    if bs_signal == 'S':
        negative_factors.append({'factor': 'BS卖出', 'detail': bs_reasons[0] if bs_reasons else 'SuperTrend跌破', 'weight': -2})
    if change_pct < 0:
        negative_factors.append({'factor': '当日下跌', 'detail': f'跌幅 {change_pct:+.2f}%', 'weight': -1})
    if sector_trend.get('available') and sector_trend.get('heat_trend') == 'down':
        negative_factors.append({'factor': '板块降温', 'detail': f'板块热度下降至 {sector_trend["latest_heat"]:.1f}', 'weight': -1})
    if sector_trend.get('available') and sector_trend.get('flow_direction') == 'outflow':
        negative_factors.append({'factor': '资金流出', 'detail': f'净流出 {abs(sector_trend["total_net_flow"]):.0f}万', 'weight': -1})

    if stage:
        if stage in ('突破', '加速', '启动', '发酵'):
            positive_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段龙头', 'weight': 2})
        elif stage == '主升':
            positive_factors.append({'factor': '主升阶段', 'detail': f'{consecutive_days or 0}连板', 'weight': 1})
            negative_factors.append({'factor': '高位风险', 'detail': '连板高度较大，回调风险增加', 'weight': -1})
        elif stage in ('分歧', '衰退', '退潮'):
            negative_factors.append({'factor': f'{stage}阶段', 'detail': f'{stage}阶段，谨慎参与', 'weight': -2})
    if strength and strength > 50:
        positive_factors.append({'factor': '强度领先', 'detail': f'强度评分 {strength:.0f}', 'weight': 1})
    if consecutive_days and consecutive_days >= 3:
        positive_factors.append({'factor': '连板强势', 'detail': f'{consecutive_days}连板', 'weight': 1})

    if extra_positive:
        positive_factors.extend(extra_positive)
    if extra_negative:
        negative_factors.extend(extra_negative)

    # === 停牌检查 ===
    is_suspended = False
    try:
        from sqlalchemy import text
        from datetime import date as d
        today_str = d.today().isoformat()
        _s_ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        sus = db.execute(text(
            "SELECT 1 FROM suspend_stock_daily WHERE ts_code=:code AND trade_date=:d"
        ), {'code': _s_ts_code, 'd': today_str}).scalar()
        is_suspended = bool(sus)
        if is_suspended:
            positive_factors = []
            negative_factors = [{'factor': '停牌', 'detail': '当日停牌，无交易', 'weight': -3}]
    except Exception:
        logger.debug("signal_builder: factor init fallback", exc_info=False)

    # === 融资融券因子 ===
    if not is_suspended:
        try:
            margin_rows = db.execute(text("""
                SELECT trade_date, rzye, rqye, rzmre
                FROM stock_margin_data
                WHERE ts_code=:code ORDER BY trade_date DESC LIMIT 3
            """), {'code': _s_ts_code}).fetchall()
            if len(margin_rows) >= 2:
                rzye_0 = float(margin_rows[0][1] or 0)
                rzye_1 = float(margin_rows[1][1] or 0)
                if rzye_0 > 0 and rzye_1 > 0:
                    margin_chg = (rzye_0 - rzye_1) / rzye_1
                    if margin_chg > 0.02:
                        positive_factors.append({'factor': '融资加仓', 'detail': f'融资余额日增 {margin_chg*100:.1f}%', 'weight': 2})
                    elif margin_chg > 0.005:
                        positive_factors.append({'factor': '融资微增', 'detail': f'融资余额日增 {margin_chg*100:.1f}%', 'weight': 1})
                    elif margin_chg < -0.02:
                        negative_factors.append({'factor': '融资减仓', 'detail': f'融资余额日降 {abs(margin_chg)*100:.1f}%', 'weight': -2})
                    elif margin_chg < -0.005:
                        negative_factors.append({'factor': '融资微降', 'detail': f'融资余额日降 {abs(margin_chg)*100:.1f}%', 'weight': -1})
        except Exception:
            logger.debug("signal_builder: margin factor failed", exc_info=False)

    # === 波浪信号交叉验证 ===
    if not is_suspended:
        try:
            pure_code = code.replace('.SH','').replace('.SZ','')
            wave = db.execute(text("""
                SELECT signal, confidence, reason FROM stock_wave_signals
                WHERE code=:c AND signal_date=:d ORDER BY id DESC LIMIT 1
            """), {'c': pure_code, 'd': d.today().isoformat()}).first()
            if wave:
                wsig, wconf, wreason = wave
                if wsig == 'buy' and float(wconf or 0) > 50:
                    positive_factors.append({'factor': '波浪买入', 'detail': f'波浪信号: {str(wreason)[:30]}', 'weight': 1})
                elif wsig == 'sell' and float(wconf or 0) > 50:
                    negative_factors.append({'factor': '波浪卖出', 'detail': f'波浪信号: {str(wreason)[:30]}', 'weight': -1})
        except Exception:
            logger.debug("signal_builder: margin factor failed", exc_info=False)

    score = len(positive_factors) - len(negative_factors)
    reasons.append(f'综合评分: {"看多" if score > 0 else "看空" if score < 0 else "中性"} → {signal_label}')

    # 计算风险等级（预计算模式不涉及持仓）
    features = market_state_data.get('features') or {}
    risk = calc_risk(features, buy_power, None)

    return {
        'secCode': code,
        'secName': name,
        'signal': signal_type,
        'signalLabel': signal_label,
        'signalColor': signal_color,
        'riskLevel': risk.get('stage', '低危') if isinstance(risk, dict) else '低危',
        'score': max(0, min(100, (score + 10) * 5)),  # 归一化 -4~4 → 0~100
        'reasons': reasons,
        'positiveFactors': positive_factors,
        'negativeFactors': negative_factors,
        'sector': sector,
        'sectorTrend': sector_trend,
        'quote': quote,
        'bsSignal': bs_signal,
        'position': {
            'profitPct': 0,
            'posPct': 0,
            'dayProfit': 0,
            'dayProfitPct': change_pct,
            'count': consecutive_days or 0,
            'price': price,
            'costPrice': 0,
            'value': 0,
            'profit': 0,
        },
        'qualityStatus': quality_status,
        'buyPower': buy_power,
        'marketState': market_state_data,
        'lifecycleStage': lifecycle_stage,
    }


async def build_signals_from_strategy_result(
    db, strategy_key: str, trade_date: str, *,
    stage: str = '策略选股',
) -> Optional[List[dict]]:
    """从 strategy_result 预计算表读取策略命中，用 WatchlistSignalDaily 富化

    返回 enriched signals 列表；无预计算数据时返回 None（调用方 fallback 现场计算）。
    跳过 K线/BS/板块/市场状态的现场计算，仅拉实时 quote（30s缓存）。
    """
    from db.models import StrategyResult, WatchlistSignalDaily
    from sqlalchemy import func

    rows = db.query(StrategyResult).filter(
        StrategyResult.trade_date == trade_date,
        StrategyResult.strategy_key == strategy_key,
    ).order_by(StrategyResult.score.desc()).all()
    if not rows:
        return None

    ts_codes = [r.ts_code for r in rows]
    latest_date = db.query(func.max(WatchlistSignalDaily.trade_date)).scalar()
    precomputed_map = {}
    if latest_date:
        wl_rows = db.query(WatchlistSignalDaily).filter(
            WatchlistSignalDaily.trade_date == latest_date,
            WatchlistSignalDaily.ts_code.in_(ts_codes),
        ).all()
        for wl_row in wl_rows:
            precomputed_map[wl_row.ts_code] = wl_row

    # 批量查 LeaderLifecycle 真实生命周期阶段（非龙头股查不到则显示"未入选"）
    lifecycle_map = _get_lifecycle_map(db, ts_codes, trade_date)

    tasks = []
    for row in rows:
        code = row.ts_code.split('.')[0] if '.' in row.ts_code else row.ts_code
        precomputed = precomputed_map.get(row.ts_code)
        _lifecycle = lifecycle_map.get(row.ts_code) or '未入选'
        if precomputed:
            tasks.append(build_signal_from_precomputed(
                code, row.name, precomputed,
                stage=stage, strength=float(row.score or 0),
                lifecycle_stage=_lifecycle,
            ))
        else:
            tasks.append(build_signal_for_stock(
                code, row.name, row.sector, db,
                stage=stage, strength=float(row.score or 0),
                lifecycle_stage=_lifecycle,
            ))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched = []
    for i, r in enumerate(results):
        if isinstance(r, Exception) or r is None:
            continue
        row = rows[i]
        detail = json.loads(row.detail_json or '{}')
        r['strategyScore'] = float(row.score or 0)
        r['deviation'] = float(detail.get('deviation', 0))
        r['rsi'] = float(detail.get('rsi', 0))
        r['scores'] = json.loads(row.scores_json or '{}')
        r['lowerShadow'] = float(detail.get('lower_shadow', 0))
        if strategy_key in ('baihu_v30', 'liangjia_report'):
            r['ma20'] = float(detail.get('ma20', 0))
            r['volRatio'] = float(detail.get('vol_ratio', 0))
            r['20dayGain'] = float(detail.get('20day_gain', 0))
        if strategy_key == 'baihu_v30':
            r['strategyMode'] = detail.get('mode', '')
            r['ma5'] = float(detail.get('ma5', 0))
            r['ma10'] = float(detail.get('ma10', 0))
            r['distanceToHigh20'] = float(detail.get('distance_to_high_20', 0))
        if strategy_key == 'liangjia_report':
            # 量价报告策略：5种形态 + 3层分层 + 交易计划 + 合并维度
            r['pattern'] = detail.get('pattern', '')
            r['patternDesc'] = detail.get('pattern_desc', '')
            r['tier'] = detail.get('tier', '')
            r['tierLabel'] = detail.get('tier_label', '')
            r['gain5d'] = float(detail.get('gain5d', 0))
            r['gain20d'] = float(detail.get('gain20d', 0))
            r['volRatio20'] = float(detail.get('vol_ratio_20', 0))
            r['distanceToHigh20'] = float(detail.get('distance_to_high_20', 0))
            r['deviationMa20'] = float(detail.get('deviation_ma20', 0))
            r['deviationMa5'] = float(detail.get('deviation_ma5', 0))
            r['ma5'] = float(detail.get('ma5', 0))
            r['ma10'] = float(detail.get('ma10', 0))
            r['ma20'] = float(detail.get('ma20', 0))
            r['ma20Rising'] = bool(detail.get('ma20_rising', False))
            r['bullAlignment'] = bool(detail.get('bull_alignment', False))
            r['tradePlan'] = detail.get('trade_plan', {})
            r['strategyMode'] = detail.get('pattern', '')  # 复用 SignalCard 模式标签
            # 合并吸收的维度
            r['breakout10d'] = bool(detail.get('breakout_10d', False))
            r['breakoutPct'] = float(detail.get('breakout_pct', 0))
            r['mainForceDays'] = int(detail.get('main_force_days', 0))
            r['hasMainForce'] = bool(detail.get('has_main_force', False))
        if strategy_key == 'risk_exit':
            r['worstSeverity'] = detail.get('worst_severity', '')
            r['worstLabel'] = detail.get('worst_label', '')
            r['worstReason'] = detail.get('worst_reason', '')
            r['riskSignals'] = detail.get('signals', [])
        enriched.append(r)

    # 补充自选股个股模块字段（moneyFlow/hitTags/actionHint），让 SignalCard 显示完整信息
    await _enrich_signals_with_watchlist_extras(db, enriched)
    return enriched


# 缓存 _enrich_signals_with_watchlist_extras 的中间结果（moneyflow_map + hit_tags_map）
# 这些都是盘后数据，2 分钟内不会变化；避免 81 只股票的 11+ 次 DB 查询重复执行（首次 6-9s → 命中 <100ms）
_enrich_extras_cache = BoundedDict(maxsize=50)  # key: frozenset(codes) -> (timestamp, moneyflow_map, hit_tags_map)
_ENRICH_EXTRAS_CACHE_TTL = 120  # 2 分钟


async def _enrich_signals_with_watchlist_extras(db, signals: List[dict]) -> None:
    """为 signal 列表批量补充自选股个股模块的 3 个字段（原地修改）：
    - moneyFlow: 4 档资金流 + 1/2/3/4/5 日累计（盘后数据）
    - hitTags:   7 大命中标签（yuzi/strategy/trend/capital/popularity/support/accumulation）
    - actionHint: 根据命中标签组合生成的操作方向文案

    与自选股 build_watchlist 完全一致的口径，确保 SignalCard 中列资金流向模块和 HitTagBar 正常渲染。
    """
    if not signals:
        return
    # 复用 watchlist.core 的批量函数，保证口径一致
    from api.watchlist.core import _batch_moneyflow_map, _batch_hit_tags

    stock_codes = [s.get('secCode') for s in signals if s.get('secCode')]
    if not stock_codes:
        return

    # 检查缓存（盘后数据，2 分钟 TTL）
    cache_key = frozenset(stock_codes)
    now = time.time()
    cached = _enrich_extras_cache.get(cache_key)
    if cached and now - cached[0] < _ENRICH_EXTRAS_CACHE_TTL:
        moneyflow_map, hit_tags_map = cached[1], cached[2]
    else:
        # 批量拉资金流 + 命中标签（11+ 次 DB 查询，首次 6-9s）
        moneyflow_map = _batch_moneyflow_map(db, stock_codes)
        sectors_map = {s.get('secCode'): s.get('sector', '') for s in signals}
        hit_tags_map = _batch_hit_tags(db, stock_codes, sectors_map)
        _enrich_extras_cache[cache_key] = (now, moneyflow_map, hit_tags_map)

    for s in signals:
        code = s.get('secCode')
        if not code or len(code) != 6:
            continue
        ts_code = f"{code}.SH" if code[0] in ('6', '9') else f"{code}.SZ"
        # moneyFlow（缺失时给空壳，前端显示"暂无盘后数据"）；浅拷贝避免污染缓存
        if 'moneyFlow' not in s or not s.get('moneyFlow'):
            mf = moneyflow_map.get(ts_code)
            s['moneyFlow'] = dict(mf) if mf else {
                'available': False, 'main_net': 0, 'super_large': 0,
                'large': 0, 'small': 0, 'tiny': 0, 'turnover_rate': 0,
                'inflow_1d': 0, 'inflow_2d': 0, 'inflow_3d': 0,
                'inflow_4d': 0, 'inflow_5d': 0, 'flow_continuity': 0,
            }
        # hitTags + actionHint；浅拷贝 list 避免污染缓存
        hit_info = hit_tags_map.get(ts_code, {})
        s.setdefault('hitTags', list(hit_info.get('hit_tags', [])))
        s.setdefault('actionHint', hit_info.get('action_hint', ''))