"""
持仓策略引擎
基于多维度评分系统生成操作信号
每个维度独立计分（正分=看多，负分=看空），最终信号由总分决定
"""
import time
import asyncio
from datetime import datetime
from typing import List, Optional
import httpx
from db.connection import get_db
from db.models import SectorFlow, StockFlow
from analyzers.buy_power import calc_buy_power_for_signal
from analyzers.market_state import get_latest_state, compute_quality_from_features
import logging
from utils.http_constants import SINA_HEADERS_SHORT
logger = logging.getLogger(__name__)

# 默认策略参数
DEFAULT_CONFIG = {
    "stop_loss_pct": -5.0,        # 止损线：亏损超过此值扣分
    "take_profit_pct": 15.0,      # 止盈线：盈利超过此值扣分（减仓锁定）
    "add_position_pct": 5.0,      # 加仓条件：盈利超过此值且板块向上加分
    "sector_heat_threshold": 40,  # 板块热度预警线：低于此值扣分
    "sector_trend_days": 7,       # 板块趋势观察天数
    "max_position_pct": 20.0,     # 单只股票最大仓位比例
    "sector_decline_days": 3,     # 板块连续下跌天数触发预警
}

# 信号类型
SIGNAL_STRONG_SELL = "STRONG_SELL"  # 清仓
SIGNAL_SELL = "SELL"                # 减仓
SIGNAL_HOLD = "HOLD"                # 持仓维持
SIGNAL_ADD = "ADD"                  # 加仓

SIGNAL_META = {
    SIGNAL_STRONG_SELL: {"label": "清仓", "color": "#dc2626", "priority": 0},
    SIGNAL_SELL: {"label": "减仓", "color": "#f97316", "priority": 1},
    SIGNAL_HOLD: {"label": "持仓", "color": "#6b7280", "priority": 2},
    SIGNAL_ADD: {"label": "加仓", "color": "#22c55e", "priority": 3},
}

# 评分阈值
SCORE_STRONG_SELL = -5   # <= -5 清仓
SCORE_SELL = -2          # <= -2 减仓
SCORE_ADD = 3            # >= 3 加仓
# 中间区域: -2 < score < 3 → 持仓

# 运行时策略配置（可被API修改）
_runtime_config = DEFAULT_CONFIG.copy()


def get_config():
    return _runtime_config.copy()


def update_config(new_config: dict):
    _runtime_config.update({k: v for k, v in new_config.items() if k in DEFAULT_CONFIG})


def _find_sector_for_stock(db, ts_code: str) -> Optional[str]:
    """从 stock_flow 表查找股票所属板块（跳过空 sector 记录）"""
    row = db.query(StockFlow.sector).filter(
        StockFlow.ts_code.like(f"%{ts_code}%"),
        StockFlow.sector != None,
        StockFlow.sector != '',
    ).order_by(StockFlow.trade_date.desc()).first()
    return row[0] if row else None


def _get_sector_trend(db, sector: str, days: int) -> dict:
    """获取板块最近N天的趋势数据"""
    rows = db.query(SectorFlow).filter(
        SectorFlow.sector == sector
    ).order_by(SectorFlow.trade_date.desc()).limit(days).all()

    if not rows:
        return {"sector": sector, "available": False}

    heat_scores = [float(r.heat_score or 0) for r in rows]
    net_flows = [float(r.net_flow or 0) for r in rows]
    avg_chgs = [float(r.avg_chg or 0) for r in rows]

    # 趋势方向：比较最近一天与前面均值
    latest_heat = heat_scores[0]
    avg_heat = sum(heat_scores[1:]) / len(heat_scores[1:]) if len(heat_scores) > 1 else latest_heat
    heat_trend = "up" if latest_heat > avg_heat else "down" if latest_heat < avg_heat else "flat"

    # 连续下跌天数
    decline_days = 0
    for i in range(len(heat_scores) - 1):
        if heat_scores[i] < heat_scores[i + 1]:
            decline_days += 1
        else:
            break

    # 资金流向
    total_net_flow = sum(net_flows)
    flow_direction = "inflow" if total_net_flow > 0 else "outflow"

    return {
        "sector": sector,
        "available": True,
        "latest_heat": round(latest_heat, 1),
        "avg_heat": round(avg_heat, 1),
        "heat_series": [
            {"date": str(r.trade_date), "heat": round(float(r.heat_score or 0), 1), "flow": round(float(r.net_flow or 0), 1)}
            for r in rows
        ][::-1],  # 时间正序（旧→新）便于 K线叠加
        "heat_trend": heat_trend,
        "decline_days": decline_days,
        "total_net_flow": round(total_net_flow, 0),
        "flow_direction": flow_direction,
        "latest_avg_chg": round(avg_chgs[0], 2) if avg_chgs else 0,
        "latest_date": rows[0].trade_date.strftime('%Y-%m-%d') if rows[0].trade_date else None,
        "heat_history": heat_scores[::-1],  # 正序：旧→新
    }


def analyze_position(pos: dict, sector_trend: dict, config: dict, total_assets: float) -> dict:
    """
    多维度评分系统：每个维度独立计分，最终信号由总分决定
    正分 = 看多因素，负分 = 看空因素

    12 个评分维度统一为规则表（_RULES），新增/调整只需修改规则表，无需改主逻辑。
    """
    profit_pct = pos.get("profitPct", 0)
    pos_pct = pos.get("posPct", 0)
    day_profit = pos.get("dayProfit", 0)
    day_profit_pct = pos.get("dayProfitPct", 0)
    sector_ok = sector_trend.get("available", False)
    sector_name = sector_trend.get("sector", "未知")

    # ========== 规则表：12 个评分维度（看空 7 + 看多 5）==========
    # 每条规则 (condition, factor_name, weight, detail_fmt)：
    #   - condition: 命中条件（lambda 闭包）
    #   - factor_name: 因素中文名
    #   - weight: 权重（正=看多，负=看空）
    #   - detail_fmt: 详情格式化函数 (接收 self 绑定的 pos/st_dict/config) -> str
    _RULES = [
        # 看空维度
        (lambda: profit_pct <= config["stop_loss_pct"],
         "止损亏损", -3,
         lambda: f"亏损 {profit_pct:.1f}% 超过止损线 {config['stop_loss_pct']}%"),
        (lambda: sector_ok and sector_trend.get("decline_days", 0) >= config["sector_decline_days"],
         "板块下行", -2,
         lambda: f"板块「{sector_name}」热度连续 {sector_trend['decline_days']} 天下滑（当前 {sector_trend['latest_heat']}）"),
        (lambda: sector_ok and sector_trend.get("latest_heat", 100) < config["sector_heat_threshold"],
         "板块低温", -1,
         lambda: f"板块「{sector_name}」热度 {sector_trend['latest_heat']} 低于预警线 {config['sector_heat_threshold']}"),
        (lambda: profit_pct >= config["take_profit_pct"],
         "止盈区间", -1,
         lambda: f"盈利 {profit_pct:.1f}% 达到止盈线 {config['take_profit_pct']}%，可减仓锁定利润"),
        (lambda: pos_pct > config["max_position_pct"],
         "仓位过重", -1,
         lambda: f"仓位 {pos_pct:.1f}% 超过上限 {config['max_position_pct']}%"),
        (lambda: sector_ok and sector_trend.get("flow_direction") == "outflow",
         "资金流出", -1,
         lambda: f"板块「{sector_name}」资金净流出 {abs(sector_trend.get('total_net_flow', 0)):.0f} 万"),
        (lambda: day_profit_pct <= -3,
         "当日大跌", -1,
         lambda: f"当日跌幅 {day_profit_pct:.1f}%，短期承压"),

        # 看多维度
        (lambda: sector_ok and sector_trend.get("heat_trend") == "up",
         "板块上升", 2,
         lambda: f"板块「{sector_name}」热度上升（当前 {sector_trend['latest_heat']}，均值 {sector_trend['avg_heat']}）"),
        (lambda: sector_ok and sector_trend.get("flow_direction") == "inflow",
         "资金流入", 1,
         lambda: f"板块「{sector_name}」资金净流入 {sector_trend.get('total_net_flow', 0):.0f} 万"),
        (lambda: profit_pct >= config["add_position_pct"] and profit_pct < config["take_profit_pct"],
         "盈利良好", 1,
         lambda: f"盈利 {profit_pct:.1f}%，处于健康区间"),
        (lambda: sector_ok and sector_trend.get("latest_avg_chg", 0) > 0,
         "板块涨势", 1,
         lambda: f"板块当日平均涨幅 +{sector_trend['latest_avg_chg']:.2f}%"),
        (lambda: pos_pct < config["max_position_pct"] * 0.5,
         "仓位较低", 1,
         lambda: f"仓位 {pos_pct:.1f}% 远低于上限 {config['max_position_pct']}%，有加仓空间"),
    ]

    # ========== 规则评估：单循环计算 score + 分类 factors ==========
    score = 0
    positive_factors: list = []
    negative_factors: list = []
    for cond, factor, weight, detail_fn in _RULES:
        if not cond():
            continue
        score += weight
        factor_obj = {"factor": factor, "detail": detail_fn(), "weight": weight}
        (negative_factors if weight < 0 else positive_factors).append(factor_obj)

    # ========== 信号判定 ==========
    if score <= SCORE_STRONG_SELL:
        signal = SIGNAL_STRONG_SELL
    elif score <= SCORE_SELL:
        signal = SIGNAL_SELL
    elif score >= SCORE_ADD:
        signal = SIGNAL_ADD
    else:
        signal = SIGNAL_HOLD

    # 风险等级
    if score <= SCORE_STRONG_SELL:
        risk_level = "high"
    elif score <= SCORE_SELL:
        risk_level = "medium"
    else:
        risk_level = "low"

    # ========== 生成理由 ==========
    reasons = []
    # 看空因素
    for f in negative_factors:
        reasons.append(f"[-{abs(f['weight'])}] {f['factor']}：{f['detail']}")

    # 看多因素
    for f in positive_factors:
        reasons.append(f"[+{f['weight']}] {f['factor']}：{f['detail']}")

    # 综合结论
    if not reasons:
        if profit_pct >= 0:
            reasons.append(f"[0] 盈利 {profit_pct:.1f}%，各维度均衡，维持持仓")
        else:
            reasons.append(f"[0] 亏损 {profit_pct:.1f}% 但未触及止损线，各维度均衡，维持持仓观察")

    # 当日盈亏补充
    if day_profit != 0 and day_profit_pct > -3:
        reasons.append(f"当日{'盈利' if day_profit > 0 else '亏损'} {abs(day_profit):.0f} 元 ({day_profit_pct:+.1f}%)")

    reasons.append(f"综合评分: {score:+d} → {SIGNAL_META[signal]['label']}")

    return {
        "secCode": pos.get("secCode"),
        "secName": pos.get("secName"),
        "signal": signal,
        "signalLabel": SIGNAL_META[signal]["label"],
        "signalColor": SIGNAL_META[signal]["color"],
        "riskLevel": risk_level,
        "score": score,
        "reasons": reasons,
        "positiveFactors": positive_factors,
        "negativeFactors": negative_factors,
        "sector": sector_trend.get("sector"),
        "sectorTrend": sector_trend,
        "position": {
            "profitPct": round(profit_pct, 2),
            "posPct": round(pos_pct, 2),
            "dayProfit": round(day_profit, 0),
            "dayProfitPct": round(day_profit_pct, 2),
            "count": pos.get("count"),
            "price": pos.get("price"),
            "costPrice": pos.get("costPrice"),
            "value": pos.get("value"),
            "profit": pos.get("profit"),
        },
    }


def generate_signals(positions: List[dict], total_assets: float):
    """生成持仓分析信号（async，调用方需 await）
    数据维度与 /api/watchlist 完全对齐：marketState / buyPower / qualityStatus / quote / bsSignal
    """
    return _generate_signals_async(positions, total_assets)


# 新浪实时行情缓存（30秒，与 watchlist 口径一致）
_quote_cache = {}
_QUOTE_CACHE_TTL = 30

# 数据校验：确保每个 signal 包含与自选股一致的字段
_REQUIRED_SIGNAL_FIELDS = {
    'secCode', 'secName', 'signal', 'signalLabel', 'signalColor',
    'riskLevel', 'score', 'reasons', 'positiveFactors', 'negativeFactors',
    'sector', 'sectorTrend', 'position',
    'marketState', 'buyPower', 'qualityStatus',
    'quote', 'bsSignal',
}


def _validate_signal(sig: dict) -> list:
    """校验单个 signal 的字段完整性，返回缺失字段列表"""
    return [f for f in _REQUIRED_SIGNAL_FIELDS if f not in sig]


async def _get_quote(code: str):
    """获取新浪实时行情（缓存30秒，与 watchlist._get_quote 口径一致）"""
    cached = _quote_cache.get(code)
    if cached and time.time() - cached[1] < _QUOTE_CACHE_TTL:
        return cached[0]

    sina_code = f'sh{code}' if code[0] in ('6', '9') else f'sz{code}'
    url = f"https://hq.sinajs.cn/list={sina_code}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(url, headers=SINA_HEADERS_SHORT)
            resp.encoding = 'gbk'
            text = resp.text
        if '"' not in text or len(text.split('"')) < 3:
            _quote_cache[code] = (None, time.time())
            return None
        parts = text.split('"')[1].split(',')
        if len(parts) < 10:
            _quote_cache[code] = (None, time.time())
            return None
        yesterday_close = float(parts[1])
        current_price = float(parts[3])
        change = current_price - yesterday_close
        change_pct = (change / yesterday_close * 100) if yesterday_close else 0
        result = {
            'code': code,
            'name': parts[0],
            'price': current_price,
            'yesterdayClose': yesterday_close,
            'open': float(parts[2]),
            'high': float(parts[4]),
            'low': float(parts[5]),
            'volume': int(float(parts[8])),
            'change': round(change, 3),
            'changePct': round(change_pct, 2),
        }
        _quote_cache[code] = (result, time.time())
        return result
    except Exception:
        logger.debug(f"function fallback", exc_info=True)
        _quote_cache[code] = (None, time.time())
        return None


async def _fetch_quotes_batch(sec_codes: list) -> dict:
    """并发获取多只股票行情（分批20只，避免新浪限流）"""
    quotes = {}
    seen = set()
    unique_codes = [c for c in sec_codes if c and c not in seen and not seen.add(c)]
    BATCH = 20
    for i in range(0, len(unique_codes), BATCH):
        batch = unique_codes[i:i + BATCH]
        tasks = [_get_quote(code) for code in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for code, r in zip(batch, results):
            if isinstance(r, Exception) or r is None:
                continue
            quotes[code] = r
    return quotes


async def _generate_signals_async(positions: List[dict], total_assets: float) -> dict:
    """对所有持仓生成分析信号（async 实现）"""
    config = get_config()
    with get_db_session() as db:
        signals = []
        sector_cache = {}

        for pos in positions:
            sec_code = pos.get("secCode", "")

            # 查找板块（带缓存）
            if sec_code not in sector_cache:
                sector_cache[sec_code] = _find_sector_for_stock(db, sec_code)
            sector = sector_cache[sec_code]

            # 获取板块趋势
            if sector:
                if sector not in sector_cache:
                    sector_cache[sector] = _get_sector_trend(db, sector, config["sector_trend_days"])
                sector_trend = sector_cache[sector]
            else:
                sector_trend = {"sector": "未知", "available": False}

            # 生成信号
            signal = analyze_position(pos, sector_trend, config, total_assets)
            signals.append(signal)

        # 汇总统计
        signal_counts = {s: 0 for s in [SIGNAL_STRONG_SELL, SIGNAL_SELL, SIGNAL_HOLD, SIGNAL_ADD]}
        high_risk_count = 0
        for sig in signals:
            signal_counts[sig["signal"]] += 1
            if sig["riskLevel"] == "high":
                high_risk_count += 1

        # 并发拉取所有持仓的新浪实时行情（与自选股口径一致）
        sec_codes = [sig.get("secCode", "") for sig in signals]
        quotes_map = await _fetch_quotes_batch(sec_codes)

        # 补齐与自选股一致的数据维度
        validation_issues = []
        for sig in signals:
            sec_code = sig.get("secCode", "")
            sector_trend = sig.get("sectorTrend") or {}
            position = sig.get("position") or {}
            quote = quotes_map.get(sec_code)

            # 市场状态（CHOPPY/TREND/IMPULSE，从数据库预计算读取；缺则 PENDING 待算）
            market_state_data = get_latest_state(sec_code) or {"market_state": "PENDING", "reasons": ["待计算"]}
            sig["marketState"] = market_state_data

            # 透传 quote 和 bsSignal（与自选股字段对齐）
            sig["quote"] = quote
            sig["bsSignal"] = None  # 模拟盘未拉 K 线，无 BS 信号

            # 如有实时行情，用 quote.changePct 覆盖 position.dayProfitPct
            # 原因：妙想 API 的 dayProfitPct 是当日盈亏率（相对成本），
            # 自选股的 dayProfitPct 是当日涨跌幅（相对昨收），sim_watchlist 模式前端显示"涨跌"应用涨跌幅
            if quote:
                position["dayProfitPct"] = quote.get("changePct", position.get("dayProfitPct", 0))
                position["price"] = quote.get("price", position.get("price", 0))

            # 购买力评分（用真实 quote.changePct，与自选股 calc_buy_power_for_signal 口径一致）
            sig["buyPower"] = calc_buy_power_for_signal(quote, sector_trend, None)

            # 质量状态（用 compute_quality_from_features，与自选股 sync-quality 口径一致）
            ms = market_state_data.get("market_state", "PENDING")
            features = market_state_data.get("features") or {}
            stock_name = sig.get("secName", "") or ""
            is_junk = 'ST' in stock_name.upper() or '退' in stock_name
            sig["qualityStatus"] = compute_quality_from_features(ms, features, is_junk)

            # 数据校验
            missing = _validate_signal(sig)
            if missing:
                validation_issues.append({'secCode': sec_code, 'missing': missing})

        # 默认排序：持仓优先（仓位高的在前），同仓位按购买力降序
        # 同时保留信号优先级作为第三关键字，确保清仓/减仓信号仍优先展示
        priority_order = {SIGNAL_STRONG_SELL: 0, SIGNAL_SELL: 1, SIGNAL_HOLD: 2, SIGNAL_ADD: 3}
        signals.sort(key=lambda x: (
            -(x.get("position", {}).get("posPct") or 0),      # 1. 仓位降序（持仓优先）
            -(x.get("buyPower", {}).get("score") or 0),        # 2. 购买力降序
            priority_order.get(x["signal"], 9),                # 3. 信号优先级
        ))

        return {
            "signals": signals,
            "summary": {
                "total": len(signals),
                "strong_sell": signal_counts[SIGNAL_STRONG_SELL],
                "sell": signal_counts[SIGNAL_SELL],
                "hold": signal_counts[SIGNAL_HOLD],
                "add": signal_counts[SIGNAL_ADD],
                "high_risk": high_risk_count,
            },
            "config": config,
            "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "validation": {
                "issues": validation_issues,
                "field_count": len(_REQUIRED_SIGNAL_FIELDS),
            },
        }
