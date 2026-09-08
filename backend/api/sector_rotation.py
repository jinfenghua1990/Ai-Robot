"""A-share sector rotation research pool built from completed daily bars.

Pool admission is deliberately strict and auditable: a stock must have shown
at least one 9% single-day move or one 16% compounded two-day move during the
latest 250 completed market sessions.  Technical indicators rank and explain
qualified stocks; they do not silently relax the admission gate.
"""
from datetime import date, datetime, time
import json
from math import sqrt
import threading
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, text

from db.models import (
    ConceptSector,
    ConceptSectorFlow,
    PingAnEtfScreen,
    SectorFlow,
    SectorRotationSnapshot,
    StockDailyKline,
    StockFlow,
    StockMoneyFlowDetail,
)
from db.session import get_db_session
from services.indicators import calc_kdj, calc_ma, calc_macd, calc_rsi, calc_supertrend
from industry_stage.registry import taxonomy_metadata

router = APIRouter(prefix="/api/sector-rotation", tags=["sector_rotation"])

LOOKBACK_DAYS = 250
WARMUP_DAYS = 20
MIN_HISTORY_BARS = 60
CORE_MAX_DAYS_SINCE_TRIGGER = 120
CORE_MIN_EVENT_COUNT = 2
SINGLE_DAY_THRESHOLD = 9.0
TWO_DAY_THRESHOLD = 16.0
MAX_ABS_DAILY_PCT = 30.5
SNAPSHOT_VERSION = 3

_CACHE = {"trade_date": None, "snapshot": None}
_THEME_CACHE = {"stock_date": None, "concept_date": None, "groups": None, "stocks": None}
_CACHE_LOCK = threading.Lock()

POOL_RULE = {
    "lookback_trade_days": LOOKBACK_DAYS,
    "single_day_pct_gte": SINGLE_DAY_THRESHOLD,
    "two_day_compound_pct_gte": TWO_DAY_THRESHOLD,
    "maximum_valid_abs_daily_pct": MAX_ABS_DAILY_PCT,
    "minimum_history_bars": MIN_HISTORY_BARS,
    "ignored_initial_trading_bars": WARMUP_DAYS,
    "requires_latest_completed_bar": True,
    "excludes_st": True,
    "core_requires_days_since_trigger_lte": CORE_MAX_DAYS_SINCE_TRIGGER,
    "core_requires_distinct_event_dates_gte": CORE_MIN_EVENT_COUNT,
    "core_requires_above_ma60": True,
    "ranking": "35%触发新近度 + 35%事件强度 + 20%当前20日动量 + 10%行业内成交额分位",
}

SECTOR_ETF_ALIASES = {
    "火力发电": ("绿色电力", "电力"),
    "水力发电": ("绿色电力", "电力"),
    "新型电力": ("绿色电力", "电力"),
    "供气供热": ("绿色电力", "公用事业"),
    "软件服务": ("软件", "信创", "云计算"),
    "生物制药": ("生物科技", "创新药", "医药"),
    "化学制药": ("创新药", "医药"),
    "中成药": ("中药", "医药"),
    "医药商业": ("医药", "医疗"),
    "电气设备": ("电池", "新能源", "光伏"),
    "元器件": ("消费电子", "信息技术", "物联网"),
    "IT设备": ("信息技术", "计算机"),
    "机床制造": ("高端装备", "工业母机", "机器人"),
    "专用机械": ("高端装备", "机器人", "机械"),
    "机械基件": ("高端装备", "机械"),
    "汽车整车": ("汽车", "新能源车"),
    "汽车配件": ("汽车", "新能源车"),
    "煤炭开采": ("煤炭", "能源"),
    "焦炭加工": ("煤炭", "能源"),
    "化工原料": ("化工",),
    "化工机械": ("化工",),
    "小金属": ("有色", "稀有金属"),
    "铅锌": ("有色",),
    "铜": ("有色",),
    "铝": ("有色",),
    "普钢": ("钢铁",),
    "特种钢": ("钢铁",),
    "钢加工": ("钢铁",),
    "全国地产": ("房地产",),
    "区域地产": ("房地产",),
    "房产服务": ("房地产",),
    "建筑工程": ("基建",),
    "水泥": ("基建", "建材"),
    "其他建材": ("建材",),
    "环境保护": ("环保", "碳中和"),
    "航空": ("航空航天", "军工"),
    "船舶": ("军工",),
    "运输设备": ("高端装备", "机械"),
    "白酒": ("酒", "食品饮料"),
    "啤酒": ("酒", "食品饮料"),
    "红黄酒": ("酒", "食品饮料"),
    "乳制品": ("食品饮料", "食品"),
    "农业综合": ("农业", "粮食"),
    "种植业": ("农业", "粮食"),
    "饲料": ("养殖", "农业"),
    "旅游景点": ("旅游",),
    "旅游服务": ("旅游",),
    "保险": ("保险",),
    "银行": ("银行",),
    "多元金融": ("金融",),
}

THEME_GROUPS = (
    {"name": "算力", "keywords": ("算力", "云计算", "数据中心", "东数西算", "边缘计算", "英伟达", "AI芯片", "CPO", "共封装光学", "液冷", "F5G", "宽带提速")},
    {"name": "人工智能", "keywords": ("人工智能", "AI应用", "AI智能体", "AIGC", "ChatGPT", "多模态AI", "智谱AI", "机器视觉")},
    {"name": "半导体", "keywords": ("AI芯片", "国产芯片", "存储芯片", "先进封装", "Chiplet", "光刻", "第三代半导体", "碳化硅", "氮化镓")},
    {"name": "机器人", "keywords": ("机器人", "减速器", "伺服", "工业母机", "机器视觉")},
    {"name": "新能源", "keywords": ("光伏", "风能", "储能", "锂电", "钠电", "固态电池", "充电桩", "高压快充")},
    {"name": "智能汽车", "keywords": ("新能源车", "无人驾驶", "车路云", "智能座舱", "汽车芯片", "汽车电子")},
    {"name": "低空与军工", "keywords": ("低空经济", "通用航空", "军工", "航天", "卫星", "大飞机", "无人机")},
    {"name": "医药医疗", "keywords": ("创新药", "CXO", "CRO", "减肥药", "AI制药", "医疗器械", "生物疫苗", "基因")},
    {"name": "资源周期", "keywords": ("稀土", "黄金", "小金属", "稀缺资源", "煤炭", "有色", "化工")},
    {"name": "大消费", "keywords": ("消费电子", "白酒", "食品", "家电", "旅游", "零售", "乳业")},
)


def _theme_names_for_concept(concept_name):
    name = str(concept_name or "").lower()
    return [config["name"] for config in THEME_GROUPS if any(keyword.lower() in name for keyword in config["keywords"])]


def _last(values):
    return values[-1] if values and values[-1] is not None else None


def _pct(last, old):
    return (last / old - 1) * 100 if last and old else None


def _two_day_return(previous_pct, current_pct):
    if previous_pct is None or current_pct is None:
        return None
    return ((1 + float(previous_pct) / 100) * (1 + float(current_pct) / 100) - 1) * 100


def _latest_completed_trade_date(db, now=None):
    """Use today's daily bar only after the A-share close; never score intraday snapshots."""
    latest = db.query(func.max(StockDailyKline.trade_date)).scalar()
    if not latest:
        return None
    current = now or datetime.now()
    if latest == current.date() and current.time() < time(15, 5):
        previous = db.query(func.max(StockDailyKline.trade_date)).filter(
            StockDailyKline.trade_date < latest
        ).scalar()
        return previous or latest
    return latest


def _event_rows(db, target):
    """Return only qualifying events; PostgreSQL does the 270-day scan."""
    sql = text("""
        WITH selected_dates AS (
            SELECT trade_date
            FROM stock_daily_kline
            WHERE trade_date <= :target
            GROUP BY trade_date
            ORDER BY trade_date DESC
            LIMIT :date_limit
        ),
        date_index AS (
            SELECT trade_date, ROW_NUMBER() OVER (ORDER BY trade_date) AS market_seq
            FROM selected_dates
        ),
        bars AS (
            SELECT
                k.ts_code,
                k.trade_date,
                d.market_seq,
                k.pct_chg,
                ROW_NUMBER() OVER (PARTITION BY k.ts_code ORDER BY k.trade_date) AS stock_seq,
                LAG(k.pct_chg) OVER (PARTITION BY k.ts_code ORDER BY k.trade_date) AS prev_pct,
                LAG(d.market_seq) OVER (PARTITION BY k.ts_code ORDER BY k.trade_date) AS prev_market_seq
            FROM stock_daily_kline k
            JOIN date_index d ON d.trade_date = k.trade_date
            WHERE k.close > 0
              AND k.volume > 0
              AND k.pct_chg IS NOT NULL
              AND ABS(k.pct_chg) <= :max_abs_daily_pct
        ),
        bounds AS (
            SELECT MAX(market_seq) AS max_seq,
                   GREATEST(MAX(market_seq) - :lookback_days + 1, 1) AS min_seq
            FROM date_index
        ),
        measured AS (
            SELECT b.*, bounds.max_seq, bounds.min_seq,
                   ((1 + b.prev_pct / 100.0) * (1 + b.pct_chg / 100.0) - 1) * 100.0 AS two_day_pct
            FROM bars b CROSS JOIN bounds
        )
        SELECT ts_code, trade_date, market_seq, max_seq, pct_chg, two_day_pct,
               (pct_chg >= :single_threshold) AS single_hit,
               (market_seq - prev_market_seq = 1 AND two_day_pct >= :two_day_threshold) AS two_day_hit
        FROM measured
        WHERE market_seq >= min_seq
          AND stock_seq > :warmup_days
          AND (
              pct_chg >= :single_threshold
              OR (market_seq - prev_market_seq = 1 AND two_day_pct >= :two_day_threshold)
          )
        ORDER BY ts_code, trade_date
    """)
    return db.execute(sql, {
        "target": target,
        "date_limit": LOOKBACK_DAYS + WARMUP_DAYS,
        "lookback_days": LOOKBACK_DAYS,
        "warmup_days": WARMUP_DAYS,
        "single_threshold": SINGLE_DAY_THRESHOLD,
        "two_day_threshold": TWO_DAY_THRESHOLD,
        "max_abs_daily_pct": MAX_ABS_DAILY_PCT,
    }).mappings().all()


def _summarize_events(rows):
    result = {}
    for row in rows:
        code = row["ts_code"]
        item = result.setdefault(code, {
            "single_day_count": 0,
            "two_day_count": 0,
            "max_single_day_pct": None,
            "max_two_day_pct": None,
            "latest_trigger_date": None,
            "latest_trigger_seq": None,
            "target_seq": int(row["max_seq"]),
            "latest_trigger_types": [],
            "trigger_dates": set(),
        })
        item["trigger_dates"].add(row["trade_date"])
        if row["single_hit"]:
            item["single_day_count"] += 1
            value = float(row["pct_chg"])
            item["max_single_day_pct"] = value if item["max_single_day_pct"] is None else max(item["max_single_day_pct"], value)
        if row["two_day_hit"]:
            item["two_day_count"] += 1
            value = float(row["two_day_pct"])
            item["max_two_day_pct"] = value if item["max_two_day_pct"] is None else max(item["max_two_day_pct"], value)
        seq = int(row["market_seq"])
        types = (["single_day"] if row["single_hit"] else []) + (["two_day"] if row["two_day_hit"] else [])
        if item["latest_trigger_seq"] is None or seq >= item["latest_trigger_seq"]:
            item["latest_trigger_seq"] = seq
            item["latest_trigger_date"] = row["trade_date"]
            item["latest_trigger_types"] = types
    for item in result.values():
        item["days_since_trigger"] = item["target_seq"] - item["latest_trigger_seq"]
        item["trigger_type"] = "both" if item["single_day_count"] and item["two_day_count"] else "single_day" if item["single_day_count"] else "two_day"
        single_ratio = (item["max_single_day_pct"] or 0) / SINGLE_DAY_THRESHOLD
        two_ratio = (item["max_two_day_pct"] or 0) / TWO_DAY_THRESHOLD
        item["strength_ratio"] = max(single_ratio, two_ratio)
        item["event_count"] = len(item["trigger_dates"])
        item["recent_trigger_dates"] = sorted(item["trigger_dates"], reverse=True)[:5]
        del item["trigger_dates"]
        del item["latest_trigger_seq"]
        del item["target_seq"]
    return result


def _metrics(rows, turnover=None, main_net=None):
    rows = sorted(rows, key=lambda row: row.trade_date)
    closes = [float(row.close) for row in rows]
    highs = [float(row.high or row.close) for row in rows]
    lows = [float(row.low or row.close) for row in rows]
    volumes = [float(row.volume or 0) for row in rows]
    amounts = [float(row.amount or 0) for row in rows]
    if len(closes) < MIN_HISTORY_BARS:
        return None

    ma5_values = calc_ma(closes, 5)
    ma20_values = calc_ma(closes, 20)
    ma60_values = calc_ma(closes, 60)
    rsi_values = calc_rsi(closes, 14)
    dif_values, dea_values, macd_values = calc_macd(closes)
    k_values, d_values, j_values = calc_kdj(highs, lows, closes)
    supports, resistances, _, atr_values = calc_supertrend(highs, lows, closes, period=10, multiplier=1.0)

    last_price = closes[-1]
    ma5, ma20, ma60 = _last(ma5_values), _last(ma20_values), _last(ma60_values)
    returns = [_pct(closes[i], closes[i - 1]) for i in range(1, len(closes))]
    mean_return = sum(returns) / len(returns)
    volatility = sqrt(sum((value - mean_return) ** 2 for value in returns) / len(returns))
    ma20_prior = ma20_values[-6] if len(ma20_values) >= 6 else None
    amount_values = [value for value in amounts[-20:] if value > 0]
    avg_volume = sum(volumes[-20:-1]) / max(1, len(volumes[-20:-1]))
    latest = rows[-1]

    def period_return(days):
        return _pct(last_price, closes[-1 - days]) if len(closes) > days else None

    return {
        "day_change_pct": float(latest.pct_chg) if latest.pct_chg is not None else None,
        "ret_5d": period_return(5),
        "ret_20d": period_return(20),
        "ret_60d": period_return(60),
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "ma20_slope": _pct(ma20, ma20_prior),
        "above_ma20": last_price >= ma20 if ma20 is not None else None,
        "above_ma60": last_price >= ma60 if ma60 is not None else None,
        "volatility": volatility,
        "drawdown": _pct(last_price, max(closes)),
        "amount_20d": sum(amount_values) / len(amount_values) if amount_values else None,
        "volume_ratio": volumes[-1] / avg_volume if avg_volume > 0 else None,
        "last_price": last_price,
        "rsi": _last(rsi_values),
        "dif": _last(dif_values),
        "dea": _last(dea_values),
        "macd": _last(macd_values),
        "kdj_k": _last(k_values),
        "kdj_d": _last(d_values),
        "kdj_j": _last(j_values),
        "support": _last(supports),
        "resistance": _last(resistances),
        "atr": _last(atr_values),
        "turnover": turnover,
        "main_net": main_net,
    }


def _liquidity_scores(stocks):
    ordered = sorted(stocks, key=lambda stock: stock["metrics"].get("amount_20d") or 0)
    denominator = max(1, len(ordered) - 1)
    return {stock["ts_code"]: index / denominator * 100 for index, stock in enumerate(ordered)}


def _rank_stocks(stocks):
    liquidity = _liquidity_scores(stocks)
    for stock in stocks:
        evidence = stock["qualification"]
        metrics = stock["metrics"]
        recency = max(0.0, 100 * (1 - evidence["days_since_trigger"] / max(1, LOOKBACK_DAYS - 1)))
        event_strength = min(100.0, evidence["strength_ratio"] / 2 * 100)
        momentum = max(0.0, min(100.0, ((metrics.get("ret_20d") or -20) + 20) / 60 * 100))
        liquidity_score = liquidity[stock["ts_code"]]
        components = {
            "trigger_recency": round(recency, 2),
            "event_strength": round(event_strength, 2),
            "momentum_20d": round(momentum, 2),
            "liquidity": round(liquidity_score, 2),
        }
        stock["score_components"] = components
        stock["score"] = round(recency * 0.35 + event_strength * 0.35 + momentum * 0.20 + liquidity_score * 0.10, 2)
        if metrics.get("above_ma20") is False:
            stock["action"] = "等待修复"
        elif (metrics.get("rsi") or 0) >= 75:
            stock["action"] = "强势·谨慎追高"
        elif metrics.get("ma5") and metrics.get("ma20") and metrics.get("ma60") and metrics["ma5"] >= metrics["ma20"] >= metrics["ma60"]:
            stock["action"] = "强势跟踪"
        else:
            stock["action"] = "观察"
    stocks.sort(key=lambda stock: (-stock["score"], stock["qualification"]["days_since_trigger"], stock["ts_code"]))
    for rank, stock in enumerate(stocks, 1):
        stock["rank"] = rank


def _is_core_stock(stock):
    evidence = stock["qualification"]
    metrics = stock["metrics"]
    event_count = evidence["event_count"]
    reasons = []
    if evidence["days_since_trigger"] > CORE_MAX_DAYS_SINCE_TRIGGER:
        reasons.append("strong_event_too_old")
    if event_count < CORE_MIN_EVENT_COUNT:
        reasons.append("insufficient_repeat_events")
    if metrics.get("above_ma60") is not True:
        reasons.append("below_ma60")
    stock["core_gate"] = {"valid": not reasons, "reasons": reasons}
    return not reasons


def _average_metrics(stocks):
    keys = ("ret_5d", "ret_20d", "ret_60d", "volatility", "drawdown")
    result = {}
    for key in keys:
        values = [stock["metrics"].get(key) for stock in stocks if stock["metrics"].get(key) is not None]
        result[key] = round(sum(values) / len(values), 2) if values else None
    result["breadth"] = round(
        sum((stock["metrics"].get("ret_20d") or 0) > 0 for stock in stocks) / len(stocks) * 100,
        2,
    ) if stocks else 0
    result["score"] = round(sum(stock["score"] for stock in stocks) / len(stocks), 2) if stocks else None
    result["is_strong"] = bool(result["ret_20d"] and result["ret_20d"] > 0 and result["breadth"] >= 50)
    return result


def _build_theme_groups(db, target, qualified_by_sector):
    """Aggregate granular concept membership into tradeable parent themes.

    Industry remains the stable classification.  Themes are a second, many-to-many
    view used to explain what the market is trading today.  A theme is only shown
    when it intersects the audited strong-stock qualification library.
    """
    qualified = {}
    for industry, stocks in qualified_by_sector.items():
        for stock in stocks:
            code = str(stock.get("ts_code") or "").split(".")[0]
            if code:
                qualified[code] = (industry, stock)

    concept_flow_date = db.query(func.max(ConceptSectorFlow.trade_date)).filter(
        ConceptSectorFlow.trade_date <= target
    ).scalar()
    flow_rows = db.query(ConceptSectorFlow).filter(
        ConceptSectorFlow.trade_date == concept_flow_date
    ).all() if concept_flow_date else []
    flows = {row.concept_name: row for row in flow_rows}
    concepts = []
    for row in db.query(ConceptSector).all():
        codes = {str(code).strip().split(".")[0] for code in (row.stocks or "").split(",") if str(code).strip()}
        if codes:
            concepts.append((row.name, codes, int(row.stock_count or len(codes))))

    groups = []
    stocks_by_theme = {}
    for config in THEME_GROUPS:
        matched = [item for item in concepts if config["name"] in _theme_names_for_concept(item[0])]
        concept_details = []
        stock_concepts = {}
        for concept_name, codes, universe_count in matched:
            active_codes = sorted(codes.intersection(qualified))
            if not active_codes:
                continue
            flow = flows.get(concept_name)
            detail = {
                "name": concept_name,
                "universe_stock_count": universe_count,
                "qualified_stock_count": len(active_codes),
                "heat_score": round(float(flow.heat_score or 0), 2) if flow else None,
                "avg_chg_pct": round(float(flow.avg_chg or 0), 2) if flow else None,
                "rise_ratio": round(float(flow.rise_ratio or 0), 2) if flow else None,
                "net_flow": float(flow.net_flow or 0) if flow else None,
                "limit_up_count": int(flow.limit_up_count or 0) if flow else 0,
            }
            concept_details.append(detail)
            for code in active_codes:
                stock_concepts.setdefault(code, []).append(detail)

        if not stock_concepts:
            continue
        concept_details.sort(key=lambda item: (
            -(item.get("heat_score") or 0),
            -(item.get("avg_chg_pct") or 0),
            -item.get("qualified_stock_count", 0),
            item["name"],
        ))
        theme_stocks = []
        for code, memberships in stock_concepts.items():
            industry, source = qualified[code]
            stock = dict(source)
            stock["industry_sector"] = industry
            stock["theme_concepts"] = [item["name"] for item in sorted(
                memberships,
                key=lambda item: (-(item.get("heat_score") or 0), item["name"]),
            )[:6]]
            theme_stocks.append(stock)
        _rank_stocks(theme_stocks)
        core_count = sum(stock.get("core_gate", {}).get("valid") is True for stock in theme_stocks)
        leading = concept_details[:3]
        heat_values = [item["heat_score"] for item in leading if item.get("heat_score") is not None]
        change_values = [item["avg_chg_pct"] for item in leading if item.get("avg_chg_pct") is not None]
        theme_heat = round(sum(heat_values) / len(heat_values), 2) if heat_values else None
        theme_change = round(sum(change_values) / len(change_values), 2) if change_values else None
        stock_metrics = _average_metrics(theme_stocks)
        recommended = bool(
            core_count > 0
            and theme_heat is not None and theme_heat >= 52
            and theme_change is not None and theme_change > 0
        )
        groups.append({
            "theme": config["name"],
            "recommended": recommended,
            "stock_count": len(theme_stocks),
            "core_stock_count": core_count,
            "candidate_stock_count": len(theme_stocks) - core_count,
            "subtheme_count": len(concept_details),
            "leading_concept": leading[0]["name"] if leading else None,
            "concepts": concept_details[:12],
            "metrics": {
                "score": theme_heat,
                "heat_score": theme_heat,
                "avg_chg_pct": theme_change,
                "ret_20d": stock_metrics.get("ret_20d"),
                "ret_60d": stock_metrics.get("ret_60d"),
                "breadth": stock_metrics.get("breadth"),
                "limit_up_count": max((item.get("limit_up_count", 0) for item in leading), default=0),
                "basis": "领涨前3个子方向平均热度与平均涨幅；涨停数取领涨子方向最大值，避免跨概念重复计数",
            },
        })
        stocks_by_theme[config["name"]] = theme_stocks

    groups.sort(key=lambda item: (
        not item["recommended"],
        -(item["metrics"].get("score") or 0),
        -(item["metrics"].get("avg_chg_pct") or -999),
        -item["core_stock_count"],
        item["theme"],
    ))
    for rank, item in enumerate(groups, 1):
        item["rank"] = rank
    return groups, stocks_by_theme, concept_flow_date


def _etf_match(sector_name, etfs):
    keywords = (sector_name,) + SECTOR_ETF_ALIASES.get(sector_name, ())
    best = None
    best_key = None
    for etf in etfs:
        blob = " ".join((etf.etf_name or "", etf.tracking_index or "", etf.etf_type or ""))
        match_index = next((index for index, keyword in enumerate(keywords) if keyword and keyword in blob), None)
        if match_index is None:
            continue
        key = (match_index, -(float(etf.amount_20d) if etf.amount_20d is not None else 0))
        if best_key is None or key < best_key:
            best, best_key = etf, key
    return best, keywords


def _build_snapshot(db, target):
    event_evidence = _summarize_events(_event_rows(db, target))
    qualified_codes = list(event_evidence)
    if not qualified_codes:
        return {
            "snapshot_version": SNAPSHOT_VERSION,
            "taxonomy": taxonomy_metadata(),
            "trade_date": target,
            "sectors": [],
            "stocks_by_sector": {},
            "qualification_by_sector": {},
            "theme_groups": [],
            "stocks_by_theme": {},
            "pool_rule": POOL_RULE,
        }

    metadata_rows = db.query(
        StockFlow.ts_code,
        StockFlow.name,
        StockFlow.sector,
        StockFlow.main_force_inflow,
    ).filter(StockFlow.trade_date == target).all()
    metadata = {row.ts_code: row for row in metadata_rows}
    total_sector_counts = {}
    for row in metadata_rows:
        sector_name = (row.sector or "").strip()
        if sector_name:
            total_sector_counts[sector_name] = total_sector_counts.get(sector_name, 0) + 1

    recent_dates = [row[0] for row in db.query(StockDailyKline.trade_date).distinct().filter(
        StockDailyKline.trade_date <= target
    ).order_by(StockDailyKline.trade_date.desc()).limit(80).all()]
    history_rows = db.query(
        StockDailyKline.ts_code,
        StockDailyKline.trade_date,
        StockDailyKline.high,
        StockDailyKline.low,
        StockDailyKline.close,
        StockDailyKline.volume,
        StockDailyKline.amount,
        StockDailyKline.pct_chg,
    ).filter(
        StockDailyKline.ts_code.in_(qualified_codes),
        StockDailyKline.trade_date.in_(recent_dates),
        StockDailyKline.close > 0,
    ).all()
    histories = {}
    for row in history_rows:
        histories.setdefault(row.ts_code, []).append(row)

    money_flow_date = db.query(func.max(StockMoneyFlowDetail.trade_date)).filter(
        StockMoneyFlowDetail.trade_date <= target
    ).scalar()
    turnover_rows = db.query(
        StockMoneyFlowDetail.ts_code,
        StockMoneyFlowDetail.turnover_rate,
        StockMoneyFlowDetail.main_net,
    ).filter(
        StockMoneyFlowDetail.trade_date == money_flow_date,
        StockMoneyFlowDetail.ts_code.in_(qualified_codes),
    ).all() if money_flow_date else []
    money_flow = {
        row.ts_code: {
            "turnover": float(row.turnover_rate) if row.turnover_rate is not None else None,
            "main_net": float(row.main_net) if row.main_net is not None else None,
        }
        for row in turnover_rows
    }

    sector_flow_date = db.query(func.max(SectorFlow.trade_date)).filter(SectorFlow.trade_date <= target).scalar()
    sector_flow_rows = db.query(SectorFlow).filter(SectorFlow.trade_date == sector_flow_date).all() if sector_flow_date else []
    sector_flows = {row.sector: row for row in sector_flow_rows}
    qualified_by_sector = {}
    for code in qualified_codes:
        meta = metadata.get(code)
        history = histories.get(code, [])
        if not meta or not history:
            continue
        name = meta.name or ""
        sector_name = (meta.sector or "").strip()
        if not sector_name or name.replace("*", "").replace(" ", "").upper().startswith("ST"):
            continue
        history.sort(key=lambda row: row.trade_date)
        if history[-1].trade_date != target or len(history) < MIN_HISTORY_BARS:
            continue
        metrics = _metrics(
            history,
            turnover=(money_flow.get(code) or {}).get("turnover"),
            main_net=(money_flow.get(code) or {}).get("main_net")
            if (money_flow.get(code) or {}).get("main_net") is not None
            else (float(meta.main_force_inflow) if meta.main_force_inflow is not None else None),
        )
        if not metrics:
            continue
        sector_flow = sector_flows.get(sector_name)
        stock = {
            "ts_code": code,
            "name": name,
            "sector": sector_name,
            "metrics": metrics,
            "qualification": event_evidence[code],
            "sector_context": {
                "net_flow": float(sector_flow.net_flow) if sector_flow and sector_flow.net_flow is not None else None,
                "heat_score": float(sector_flow.heat_score) if sector_flow and sector_flow.heat_score is not None else None,
                "rise_ratio": float(sector_flow.rise_ratio) if sector_flow and sector_flow.rise_ratio is not None else None,
                "as_of": sector_flow_date,
            },
        }
        qualified_by_sector.setdefault(sector_name, []).append(stock)

    etf_date = db.query(func.max(PingAnEtfScreen.trade_date)).filter(
        PingAnEtfScreen.trade_date <= target
    ).scalar()
    etfs = db.query(PingAnEtfScreen).filter(PingAnEtfScreen.trade_date == etf_date).all() if etf_date else []
    stocks_by_sector = {}
    sectors = []
    for sector_name, qualified_stocks in qualified_by_sector.items():
        _rank_stocks(qualified_stocks)
        stocks = [stock for stock in qualified_stocks if _is_core_stock(stock)]
        _rank_stocks(stocks)
        if not stocks:
            continue
        stocks_by_sector[sector_name] = stocks
        matched, etf_keywords = _etf_match(sector_name, etfs)
        sectors.append({
            "sector": sector_name,
            "stock_count": len(stocks),
            "qualified_stock_count": len(qualified_stocks),
            "universe_stock_count": total_sector_counts.get(sector_name, len(stocks)),
            "metrics": _average_metrics(stocks),
            "etf": ({
                "code": matched.etf_code,
                "name": matched.etf_name,
                "tracking_index": matched.tracking_index,
                "return_20d_pct": float(matched.return_20d_pct) if matched.return_20d_pct is not None else None,
                "return_1y_pct": float(matched.return_1y_pct) if matched.return_1y_pct is not None else None,
                "fund_size": float(matched.fund_size) if matched.fund_size is not None else None,
                "amount_20d": float(matched.amount_20d) if matched.amount_20d is not None else None,
                "as_of": etf_date,
            } if matched else None),
            "etf_note": f"ETF名称/指数匹配：{next((word for word in etf_keywords if word in ' '.join((matched.etf_name or '', matched.tracking_index or '', matched.etf_type or ''))), sector_name)}" if matched else "暂无可靠ETF映射，当前以强势资格股等权聚合参考",
        })
    sectors.sort(key=lambda item: (-(item["metrics"].get("score") or -999), item["sector"]))
    for rank, item in enumerate(sectors, 1):
        item["rank"] = rank
    theme_groups, stocks_by_theme, concept_flow_date = _build_theme_groups(db, target, qualified_by_sector)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "taxonomy": taxonomy_metadata(),
        "trade_date": target,
        "sectors": sectors,
        "stocks_by_sector": stocks_by_sector,
        "qualification_by_sector": qualified_by_sector,
        "theme_groups": theme_groups,
        "stocks_by_theme": stocks_by_theme,
        "pool_rule": POOL_RULE,
        "qualified_stock_count": sum(len(stocks) for stocks in stocks_by_sector.values()),
        "qualification_library_count": sum(len(stocks) for stocks in qualified_by_sector.values()),
        "data_mode": "completed_daily_cached",
        "data_as_of": {
            "daily_kline": target,
            "stock_money_flow": money_flow_date,
            "sector_flow": sector_flow_date,
            "sector_etf": etf_date,
            "concept_flow": concept_flow_date,
        },
    }


def _serialize_snapshot(snapshot):
    return json.dumps(jsonable_encoder(snapshot), ensure_ascii=False, separators=(",", ":"))


def _persist_snapshot(db, snapshot):
    target = snapshot.get("trade_date")
    if not target:
        return
    row = db.query(SectorRotationSnapshot).filter(
        SectorRotationSnapshot.trade_date == target
    ).first()
    payload = _serialize_snapshot(snapshot)
    if row:
        row.snapshot_json = payload
    else:
        db.add(SectorRotationSnapshot(trade_date=target, snapshot_json=payload))
    db.commit()


def _load_persisted_snapshot(db, target):
    row = db.query(SectorRotationSnapshot).filter(
        SectorRotationSnapshot.trade_date == target
    ).first()
    if not row:
        return None
    try:
        snapshot = json.loads(row.snapshot_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if snapshot.get("trade_date") != target.isoformat() or snapshot.get("snapshot_version") != SNAPSHOT_VERSION:
        return None
    return snapshot


def _snapshot_for_date(db, target, build_if_missing=False):
    persisted = _load_persisted_snapshot(db, target)
    if persisted is not None:
        return persisted
    if not build_if_missing:
        return None
    snapshot = _build_snapshot(db, target)
    _persist_snapshot(db, snapshot)
    return snapshot


def _response(snapshot, requested_sector):
    sectors = snapshot["sectors"]
    selected = next((item["sector"] for item in sectors if item["sector"] == requested_sector), sectors[0]["sector"] if sectors else None)
    stocks = snapshot["stocks_by_sector"].get(selected, []) if selected else []
    qualified = snapshot.get("qualification_by_sector", {}).get(selected, []) if selected else []
    candidates = [stock for stock in qualified if stock.get("core_gate", {}).get("valid") is not True]
    return jsonable_encoder({
        "source": "database",
        "status": "READY",
        "taxonomy": snapshot.get("taxonomy") or taxonomy_metadata(),
        "trade_date": snapshot["trade_date"],
        "sectors": sectors,
        "theme_groups": snapshot.get("theme_groups", []),
        "selected": selected,
        "stocks": stocks,
        "candidate_stocks": candidates,
        "stock_count": len(stocks),
        "candidate_count": len(candidates),
        "qualified_stock_count": snapshot.get("qualified_stock_count", 0),
        "qualification_library_count": snapshot.get("qualification_library_count", 0),
        "pool_rule": snapshot["pool_rule"],
        "data_mode": snapshot.get("data_mode"),
        "data_as_of": snapshot.get("data_as_of", {}),
    })


def _theme_response(snapshot, requested_theme, requested_concept=None):
    themes = snapshot.get("theme_groups", [])
    selected = next((item["theme"] for item in themes if item["theme"] == requested_theme), themes[0]["theme"] if themes else None)
    qualified = snapshot.get("stocks_by_theme", {}).get(selected, []) if selected else []
    if requested_concept:
        qualified = [stock for stock in qualified if requested_concept in (stock.get("theme_concepts") or [])]
    core = [stock for stock in qualified if stock.get("core_gate", {}).get("valid") is True]
    candidates = [stock for stock in qualified if stock.get("core_gate", {}).get("valid") is not True]
    return jsonable_encoder({
        "source": "database",
        "status": "READY",
        "taxonomy": snapshot.get("taxonomy") or taxonomy_metadata(),
        "trade_date": snapshot["trade_date"],
        "theme_groups": themes,
        "selected_theme": selected,
        "selected_concept": requested_concept,
        "stocks": core[:20],
        "candidate_stocks": candidates[:20],
        "stock_count": len(core),
        "candidate_count": len(candidates),
        "qualification_library_count": len(qualified),
        "pool_rule": snapshot["pool_rule"],
        "data_mode": snapshot.get("data_mode"),
        "data_as_of": snapshot.get("data_as_of", {}),
        "taxonomy_note": "一级行业用于稳定归类；交易主题由概念成分、概念热度与强势资格股交叉聚合，单只股票可属于多个主题。",
    })


def preheat_cache():
    """Build the latest completed-day snapshot before the page is opened."""
    with get_db_session() as db:
        target = _latest_completed_trade_date(db)
        if not target:
            return {"trade_date": None, "core_stock_count": 0}
        with _CACHE_LOCK:
            if _CACHE["trade_date"] != target or _CACHE["snapshot"] is None:
                _CACHE["snapshot"] = _snapshot_for_date(db, target, build_if_missing=True)
                _CACHE["trade_date"] = target
            snapshot = _CACHE["snapshot"]
        return {
            "trade_date": target,
            "core_stock_count": snapshot.get("qualified_stock_count", 0),
            "qualification_library_count": snapshot.get("qualification_library_count", 0),
        }


def invalidate_cache(trade_date=None, persisted=False):
    """Invalidate memory and, when reference data changed, the persisted daily snapshot."""
    with _CACHE_LOCK:
        _CACHE["trade_date"] = None
        _CACHE["snapshot"] = None
        _THEME_CACHE.update({"stock_date": None, "concept_date": None, "groups": None, "stocks": None})
    if persisted:
        with get_db_session() as db:
            query = db.query(SectorRotationSnapshot)
            if trade_date is not None:
                query = query.filter(SectorRotationSnapshot.trade_date == trade_date)
            query.delete(synchronize_session=False)
            db.commit()


@router.get("")
def get_sector_rotation(sector: Optional[str] = Query(None), trade_date: Optional[date] = Query(None)):
    requested_sector = sector if isinstance(sector, str) else None
    requested_date = trade_date if isinstance(trade_date, date) else None
    with get_db_session() as db:
        target = requested_date or _latest_completed_trade_date(db)
        if not target:
            return {
                "source": "database", "status": "MISSING",
                "trade_date": None, "sectors": [], "selected": None,
                "stocks": [], "pool_rule": POOL_RULE,
                "message": "数据库暂无已完成交易日的行业轮动数据",
            }
        with _CACHE_LOCK:
            if _CACHE["trade_date"] == target and _CACHE["snapshot"] is not None:
                snapshot = _CACHE["snapshot"]
            else:
                snapshot = _snapshot_for_date(db, target)
                if snapshot is None:
                    return {
                        "source": "database", "status": "MISSING",
                        "trade_date": target.isoformat(), "sectors": [],
                        "selected": None, "stocks": [], "pool_rule": POOL_RULE,
                        "message": "数据库暂无行业轮动快照，请等待定时任务生成",
                    }
                _CACHE["trade_date"] = target
                _CACHE["snapshot"] = snapshot
        return _response(snapshot, requested_sector)


@router.get("/themes")
def get_sector_rotation_themes(
    theme: Optional[str] = Query(None),
    concept: Optional[str] = Query(None),
    trade_date: Optional[date] = Query(None),
):
    requested_theme = theme if isinstance(theme, str) else None
    requested_concept = concept if isinstance(concept, str) else None
    requested_date = trade_date if isinstance(trade_date, date) else None
    with get_db_session() as db:
        target = requested_date or _latest_completed_trade_date(db)
        if not target:
            return {
                "source": "database", "status": "MISSING",
                "trade_date": None, "theme_groups": [], "selected_theme": None,
                "stocks": [], "pool_rule": POOL_RULE,
                "message": "数据库暂无已完成交易日的行业轮动主题数据",
            }
        with _CACHE_LOCK:
            if _CACHE["trade_date"] == target and _CACHE["snapshot"] is not None:
                snapshot = _CACHE["snapshot"]
            else:
                snapshot = _snapshot_for_date(db, target)
                if snapshot is None:
                    return {
                        "source": "database", "status": "MISSING",
                        "trade_date": target.isoformat(), "theme_groups": [],
                        "selected_theme": None, "stocks": [], "pool_rule": POOL_RULE,
                        "message": "数据库暂无行业轮动主题快照，请等待定时任务生成",
                    }
                _CACHE["trade_date"] = target
                _CACHE["snapshot"] = snapshot
        concept_target = requested_date or date.today()
        concept_date = db.query(func.max(ConceptSectorFlow.trade_date)).filter(
            ConceptSectorFlow.trade_date <= concept_target
        ).scalar()
        with _CACHE_LOCK:
            if (
                _THEME_CACHE["stock_date"] == target
                and _THEME_CACHE["concept_date"] == concept_date
                and _THEME_CACHE["groups"] is not None
            ):
                groups = _THEME_CACHE["groups"]
                stocks_by_theme = _THEME_CACHE["stocks"]
            else:
                groups, stocks_by_theme, concept_date = _build_theme_groups(
                    db,
                    concept_date or target,
                    snapshot.get("qualification_by_sector", {}),
                )
                _THEME_CACHE.update({
                    "stock_date": target,
                    "concept_date": concept_date,
                    "groups": groups,
                    "stocks": stocks_by_theme,
                })
        theme_snapshot = dict(snapshot)
        theme_snapshot["theme_groups"] = groups
        theme_snapshot["stocks_by_theme"] = stocks_by_theme
        theme_snapshot["data_as_of"] = dict(snapshot.get("data_as_of", {}), concept_flow=concept_date)
        return _theme_response(theme_snapshot, requested_theme, requested_concept)
