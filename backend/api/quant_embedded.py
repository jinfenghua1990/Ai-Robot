"""Quant Service 的内嵌接口。

这些接口直接运行在 AIROBOT 9000 进程内，不再通过独立端口转发。
Qlib / VectorBT 是可选依赖；未安装或数据未就绪时返回明确的 Phase0 状态。

二波接口不是“多因子总分器”。它按用户的实战流程做资格赛：
市场环境 -> 板块/主题二波 -> 龙头身份 -> 个股二波结构 -> 触发状态。
任何关键资格不满足都不会靠其他分数把股票“加回来”。
"""
import time
import importlib.util
from statistics import median
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

router = APIRouter(prefix="/api/quant", tags=["quant"])

QLIB_READY = False
VECTORBT_READY = False
QLIB_ERROR: Optional[str] = None
VECTORBT_ERROR: Optional[str] = None
try:
    QLIB_READY = importlib.util.find_spec("qlib") is not None
    if not QLIB_READY:
        QLIB_ERROR = "No module named 'qlib'"
except Exception as exc:  # pragma: no cover
    QLIB_ERROR = str(exc)
try:
    VECTORBT_READY = importlib.util.find_spec("vectorbt") is not None
    if not VECTORBT_READY:
        VECTORBT_ERROR = "No module named 'vectorbt'"
except Exception as exc:  # pragma: no cover
    VECTORBT_ERROR = str(exc)

DATA_READY = False
SERVICE_STARTED_AT = time.strftime("%Y/%m/%d %H:%M:%S")


def _n(value, default=None):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _mean(values):
    clean = [_n(v) for v in values]
    clean = [v for v in clean if v is not None]
    return sum(clean) / len(clean) if clean else None


def _ratio(stocks, predicate):
    if not stocks:
        return 0.0
    return sum(1 for stock in stocks if predicate(stock)) / len(stocks)


def _trade_levels(metrics):
    """给二波页提供可解释的位置参考，不把技术位包装成机械交易指令。

    突破参考使用已完成日线阶段最高收盘附近；结构防守使用当前价下方
    MA20 / Supertrend 支撑中更靠近现价的一档。盘中仍需要板块同步与承接确认。
    """
    price = _n(metrics.get("last_price"))
    drawdown = _n(metrics.get("drawdown"))
    ma20 = _n(metrics.get("ma20"))
    support = _n(metrics.get("support"))
    resistance = _n(metrics.get("resistance"))

    phase_high = None
    if price and drawdown is not None and drawdown > -99.9:
        denominator = 1 + drawdown / 100
        if denominator > 0:
            phase_high = price / denominator

    breakout_candidates = [v for v in (phase_high, resistance) if v and price and v >= price * 0.995]
    breakout_reference = min(breakout_candidates) if breakout_candidates else phase_high or resistance

    defense_candidates = []
    if price:
        if ma20 and 0 < ma20 < price:
            defense_candidates.append((ma20, "MA20"))
        if support and 0 < support < price:
            defense_candidates.append((support, "趋势支撑"))
    defense_reference = max(defense_candidates, key=lambda x: x[0]) if defense_candidates else (None, None)

    distance_to_breakout = None
    if price and breakout_reference:
        distance_to_breakout = (breakout_reference / price - 1) * 100

    return {
        "phase_high": round(phase_high, 3) if phase_high else None,
        "breakout_reference": round(breakout_reference, 3) if breakout_reference else None,
        "distance_to_breakout_pct": round(distance_to_breakout, 2) if distance_to_breakout is not None else None,
        "defense_reference": round(defense_reference[0], 3) if defense_reference[0] else None,
        "defense_basis": defense_reference[1],
        "ma20": round(ma20, 3) if ma20 else None,
        "support": round(support, 3) if support else None,
        "resistance": round(resistance, 3) if resistance else None,
    }


def _board_metrics(stocks):
    """用板块核心资格股聚合，避免把大量弱跟风股稀释主线。"""
    if not stocks:
        return {}
    metrics = [stock.get("metrics") or {} for stock in stocks]
    return {
        "ret_5d": _mean(m.get("ret_5d") for m in metrics),
        "ret_20d": _mean(m.get("ret_20d") for m in metrics),
        "ret_60d": _mean(m.get("ret_60d") for m in metrics),
        "day_change_pct": _mean(m.get("day_change_pct") for m in metrics),
        "breadth": _ratio(stocks, lambda s: _n((s.get("metrics") or {}).get("ret_20d"), -999) > 0) * 100,
        "trend_share": _ratio(stocks, lambda s: (
            (s.get("metrics") or {}).get("above_ma20") is True
            and _n((s.get("metrics") or {}).get("ma20_slope"), -999) > 0
        )) * 100,
        "reset_share": _ratio(stocks, lambda s: -18 <= _n((s.get("metrics") or {}).get("drawdown"), -999) <= -2) * 100,
        "near_high_share": _ratio(stocks, lambda s: _n((s.get("metrics") or {}).get("drawdown"), -999) >= -3) * 100,
        "contraction_share": _ratio(stocks, lambda s: (
            (s.get("metrics") or {}).get("volume_ratio") is None
            or _n((s.get("metrics") or {}).get("volume_ratio"), 99) <= 0.95
        )) * 100,
        "active_share": _ratio(stocks, lambda s: _n((s.get("metrics") or {}).get("day_change_pct"), -999) >= 1.5) * 100,
        "avg_stock_score": _mean(s.get("score") for s in stocks),
    }


def _board_stage(name, kind, stocks):
    m = _board_metrics(stocks)
    ages = [
        _n((stock.get("qualification") or {}).get("days_since_trigger"))
        for stock in stocks
        if _n((stock.get("qualification") or {}).get("days_since_trigger")) is not None
    ]
    age = median(ages) if ages else 999
    ret5 = _n(m.get("ret_5d"), -999)
    ret20 = _n(m.get("ret_20d"), -999)
    breadth = _n(m.get("breadth"), 0)
    trend = _n(m.get("trend_share"), 0)
    reset = _n(m.get("reset_share"), 0)
    near_high = _n(m.get("near_high_share"), 0)
    active = _n(m.get("active_share"), 0)
    avg_score = _n(m.get("avg_stock_score"), 0)

    first_wave = bool(stocks) and age <= 75 and all(
        _n((s.get("qualification") or {}).get("event_count"), 0) >= 2 for s in stocks[: min(3, len(stocks))]
    )
    reasons = []
    if first_wave:
        reasons.append("核心股第一波强势事件明确")
    if trend >= 60:
        reasons.append(f"{trend:.0f}%核心股维持MA20上升")
    if reset >= 30:
        reasons.append(f"{reset:.0f}%核心股完成健康回撤")
    if near_high >= 35:
        reasons.append(f"{near_high:.0f}%核心股已接近阶段高位")
    if breadth >= 55:
        reasons.append(f"板块20日正收益广度{breadth:.0f}%")
    if ret5 >= 1:
        reasons.append(f"近5日重新转强{ret5:+.1f}%")

    # 一票否决：趋势明显破坏/板块广度过弱，不允许综合分“救回来”。
    if not first_wave or trend < 35 or breadth < 35 or ret20 <= -5 or ret5 <= -6:
        stage = "退潮" if first_wave else "无二波资格"
        eligible = False
        grade = "C"
    elif ret5 >= 6 and trend >= 70 and breadth >= 65 and active >= 35:
        stage = "二波加速"
        eligible = True
        grade = "A"
    elif ret5 >= 1 and trend >= 60 and breadth >= 55 and avg_score >= 55 and (reset >= 20 or near_high >= 35):
        stage = "二波启动"
        eligible = True
        grade = "A"
    elif trend >= 50 and breadth >= 45 and ret20 > 0 and reset >= 30 and 3 <= age <= 75:
        stage = "二波蓄势"
        eligible = True
        grade = "B"
    else:
        stage = "观察"
        eligible = False
        grade = "B-"

    confidence = 0
    confidence += 20 if first_wave else 0
    confidence += min(20, max(0, trend / 5))
    confidence += min(15, max(0, breadth / 6))
    confidence += 15 if reset >= 30 or near_high >= 35 else 0
    confidence += 15 if ret20 > 0 else 0
    confidence += 15 if ret5 > 0 else 0

    return {
        "name": name,
        "kind": kind,
        "stage": stage,
        "eligible": eligible,
        "grade": grade,
        "confidence": round(min(100, confidence), 0),
        "core_count": len(stocks),
        "median_days_since_first_wave": round(age, 1) if age < 999 else None,
        "metrics": {k: round(v, 2) if isinstance(v, float) else v for k, v in m.items()},
        "reasons": reasons[:4],
    }


def _stock_candidate(stock, board):
    m = stock.get("metrics") or {}
    q = stock.get("qualification") or {}
    rank = int(stock.get("rank") or 999)
    leader = "核心龙头" if rank == 1 else "强次龙" if rank == 2 else "跟风"
    trend_ok = (
        m.get("above_ma20") is True
        and m.get("above_ma60") is True
        and _n(m.get("ma20_slope"), -999) > 0
    )
    drawdown = _n(m.get("drawdown"), -999)
    volume_ratio = _n(m.get("volume_ratio"))
    day_change = _n(m.get("day_change_pct"), 0)
    age = _n(q.get("days_since_trigger"), 999)
    reset_ok = -18 <= drawdown <= -2
    near_high = drawdown >= -3
    shrink_ok = volume_ratio is None or volume_ratio <= 0.95
    breakout = trend_ok and day_change >= 1.5 and (volume_ratio is None or volume_ratio >= 0.9)

    if not trend_ok or age > 90:
        structure = "结构破坏"
        action = "不做"
    elif board["stage"] == "二波加速" and breakout and near_high:
        structure = "二波主升"
        action = "持有优先·不追高"
    elif board["eligible"] and breakout and (reset_ok or near_high):
        structure = "二波触发"
        action = "买点触发"
    elif board["eligible"] and reset_ok and shrink_ok:
        structure = "缩量等待"
        action = "等转强"
    elif board["eligible"]:
        structure = "二波观察"
        action = "等待"
    else:
        structure = "板块未确认"
        action = "不做"

    reasons = []
    if leader == "核心龙头":
        reasons.append("板块核心排名第1")
    elif leader == "强次龙":
        reasons.append("板块核心排名第2")
    if trend_ok:
        reasons.append("MA20上行且站上MA20/MA60")
    if reset_ok:
        reasons.append(f"距阶段高点{drawdown:.1f}%")
    if shrink_ok:
        reasons.append("回调量能收缩")
    if breakout:
        reasons.append("当日重新转强")

    return {
        "code": stock.get("ts_code"),
        "name": stock.get("name"),
        "sector": stock.get("sector"),
        "board": board["name"],
        "board_kind": board["kind"],
        "board_stage": board["stage"],
        "board_grade": board["grade"],
        "leader": leader,
        "rank": rank,
        "structure": structure,
        "action": action,
        "price": m.get("last_price"),
        "day_change_pct": m.get("day_change_pct"),
        "ret_5d": m.get("ret_5d"),
        "ret_20d": m.get("ret_20d"),
        "drawdown": m.get("drawdown"),
        "ma20_slope": m.get("ma20_slope"),
        "volume_ratio": m.get("volume_ratio"),
        "main_net": m.get("main_net"),
        "days_since_first_wave": q.get("days_since_trigger"),
        "event_count": q.get("event_count"),
        "levels": _trade_levels(m),
        "reasons": reasons[:4],
    }


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "quant",
        "port": 9000,
        "embedded": True,
        "qlib_ready": QLIB_READY,
        "vectorbt_ready": VECTORBT_READY,
        "data_ready": DATA_READY,
        "qlib_error": QLIB_ERROR,
        "vectorbt_error": VECTORBT_ERROR,
        "started_at": SERVICE_STARTED_AT,
    }


@router.get("/second-wave")
def second_wave(limit: int = Query(12, ge=3, le=30)):
    """二波作战资格表：主题/行业 -> 龙头 -> 结构。

    只使用已完成交易日快照，避免盘中未收盘日线污染。盘口买点仍应在前端/实时模块二次确认。
    """
    from api import sector_rotation as sr
    from db.session import get_db_session

    with get_db_session() as db:
        target = sr._latest_completed_trade_date(db)
        if not target:
            return {"status": "MISSING", "trade_date": None, "market": {"state": "等待数据"}, "boards": [], "candidates": []}
        snapshot = sr._snapshot_for_date(db, target, build_if_missing=True)

    boards = []
    board_stocks = {}

    # 交易主题优先：更接近实战主线（算力/机器人/半导体等）。
    for item in snapshot.get("theme_groups", []):
        name = item.get("theme")
        stocks = list(snapshot.get("stocks_by_theme", {}).get(name, []))
        if not name or not stocks:
            continue
        stocks.sort(key=lambda s: int(s.get("rank") or 999))
        board = _board_stage(name, "主题", stocks)
        board["source_rank"] = item.get("rank")
        boards.append(board)
        board_stocks[("主题", name)] = stocks

    # 稳定行业作为确认层；与主题并列展示但主题排序优先。
    for item in snapshot.get("sectors", []):
        name = item.get("sector")
        stocks = list(snapshot.get("stocks_by_sector", {}).get(name, []))
        if not name or not stocks:
            continue
        stocks.sort(key=lambda s: int(s.get("rank") or 999))
        board = _board_stage(name, "行业", stocks)
        board["source_rank"] = item.get("rank")
        boards.append(board)
        board_stocks[("行业", name)] = stocks

    stage_order = {"二波启动": 0, "二波蓄势": 1, "二波加速": 2, "观察": 3, "退潮": 4, "无二波资格": 5}
    boards.sort(key=lambda b: (
        not b["eligible"],
        stage_order.get(b["stage"], 9),
        0 if b["kind"] == "主题" else 1,
        -_n(b.get("confidence"), 0),
        b["name"],
    ))

    candidates_by_code = {}
    for board in boards:
        if not board["eligible"]:
            continue
        stocks = board_stocks.get((board["kind"], board["name"]), [])
        for stock in stocks[:2]:  # 每个板块最多核心龙头+强次龙，不把跟风股塞回主界面。
            candidate = _stock_candidate(stock, board)
            if candidate["leader"] == "跟风" or candidate["action"] == "不做":
                continue
            old = candidates_by_code.get(candidate["code"])
            priority = (
                0 if candidate["leader"] == "核心龙头" else 1,
                0 if candidate["structure"] == "二波触发" else 1 if candidate["structure"] == "缩量等待" else 2,
                -_n(board.get("confidence"), 0),
            )
            if old is None or priority < old["_priority"]:
                candidate["_priority"] = priority
                candidates_by_code[candidate["code"]] = candidate

    candidates = list(candidates_by_code.values())
    candidates.sort(key=lambda c: c.pop("_priority"))
    candidates = candidates[:limit]

    eligible = [b for b in boards if b["eligible"]]
    startup = sum(1 for b in eligible if b["stage"] == "二波启动")
    accelerating = sum(1 for b in eligible if b["stage"] == "二波加速")
    if startup >= 2:
        market = {"state": "可做", "tone": "positive", "reason": f"{startup}个板块二波启动，优先等核心龙头触发"}
    elif startup == 1 or len(eligible) >= 2:
        market = {"state": "谨慎", "tone": "warning", "reason": "存在二波机会，但主线数量/同步性一般"}
    elif accelerating and not startup:
        market = {"state": "谨慎追高", "tone": "warning", "reason": "主要机会已进入加速段，等待回踩而非追高"}
    else:
        market = {"state": "等待", "tone": "neutral", "reason": "暂未形成可靠的板块二波启动"}
    market.update({
        "eligible_board_count": len(eligible),
        "startup_count": startup,
        "candidate_count": len(candidates),
    })

    return jsonable_encoder({
        "status": "READY",
        "trade_date": target,
        "data_mode": "completed_daily_second_wave_gate",
        "market": market,
        "boards": boards[:12],
        "candidates": candidates,
        "rules": {
            "flow": "市场 -> 板块二波 -> 龙头身份 -> 个股二波结构 -> 触发",
            "hard_veto": ["板块趋势破坏", "广度过弱", "个股跌破MA20趋势", "非板块前2核心股"],
            "note": "因子只用于解释证据，不再用综合加分覆盖硬门槛。关键价位来自已完成日线，仅作结构参考。",
        },
        "data_as_of": snapshot.get("data_as_of", {}),
    })


@router.post("/score")
async def score(payload: dict):
    market = payload.get("market", "US")
    codes = payload.get("codes") or []
    if not QLIB_READY or not DATA_READY:
        return {
            "ready": False,
            "phase": "Phase0",
            "reason": "Qlib 或数据仓尚未就绪",
            "qlib_ready": QLIB_READY,
            "data_ready": DATA_READY,
            "market": market,
            "requested": codes,
            "scores": {},
        }
    return {"ready": True, "market": market, "scores": {}}


@router.get("/scan")
async def scan(strategy: str = "longqing", market: str = "US", limit: int = 20):
    if not VECTORBT_READY or not DATA_READY:
        return {
            "ready": False,
            "phase": "Phase0",
            "reason": "VectorBT 或数据仓尚未就绪",
            "vectorbt_ready": VECTORBT_READY,
            "data_ready": DATA_READY,
            "strategy": strategy,
            "market": market,
            "limit": limit,
            "hits": [],
        }
    return {"ready": True, "strategy": strategy, "market": market, "hits": []}
