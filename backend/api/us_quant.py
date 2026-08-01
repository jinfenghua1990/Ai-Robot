"""US Quant System V2.1.1 — FastAPI 路由

所有 API 前缀: /api/us-quant
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.encoders import jsonable_encoder

from db.session import get_db_session

from us_quant.contracts import IndexQuote, MarketRegime, Signal
from us_quant.market_regime import assess_market_regime
from us_quant.sector_rotation import SECTOR_ETFS, score_sector, rank_sectors
from us_quant.strategies import score_breakout, score_pullback, score_earnings_gap
from us_quant.filters import check_hard_filters
from us_quant.states import determine_stock_state
from us_quant.risk import check_risk_veto, calculate_position_size
from us_quant.scanner import scan_premarket, check_intraday_trigger, create_signal
from sqlalchemy import func

from us_quant.repository import ensure_schema
from us_quant.indicators import ema, sma, rsi as calc_rsi, macd as calc_macd, kdj as calc_kdj, ma_bias
from us_quant.repository import USStrategyScore, USSignal, USBacktestResult, USBacktestTrade
from us_quant.backtest import run_backtest_batch, resolve_backtest_pool
from us_quant.rebalance import run_rebalance, get_universe_definitions
from us_quant.universe import (
    list_universes, get_universe, get_universe_members,
    uniques_for_scanner, pool_stats, get_scanner_limit,
    UNIVERSE_DEFINITIONS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/us-quant", tags=["us-quant"])

# ─── 数据源（可插拔：Nasdaq 主源 + CBOE VIX + Yahoo 兜底 → 离线模拟最后兜底）──
# 后端会先自动识别本机出网代理（macOS 系统代理 / HTTP(S)_PROXY），让请求能
# 像浏览器一样走代理；详见 us_quant/data_provider.py


def _fetch_yahoo(symbol: str, range_str: str = "1mo") -> list[dict] | None:
    """委托给可插拔数据源（Nasdaq 实时主源 → Yahoo 兜底 → 离线模拟）。"""
    from us_quant.data_provider import get_klines
    return get_klines(symbol, range_str)


def _fetch_quote(symbol: str) -> Optional[dict]:
    """委托给可插拔数据源（Nasdaq 实时主源 → Yahoo 兜底 → 离线模拟）。"""
    from us_quant.data_provider import get_quote
    return get_quote(symbol)


# ─── API 端点 ─────────────────────────────────────────────────────────────────

@router.get("/regime")
async def get_regime():
    """获取当前市场环境状态"""
    from us_quant.data_provider import get_klines_batch
    _batch = get_klines_batch(["SPY", "QQQ", "IWM", "RSP"], "2mo")
    indices = {
        "SPY": _batch.get("SPY"),
        "QQQ": _batch.get("QQQ"),
        "IWM": _batch.get("IWM"),
        "RSP": _batch.get("RSP"),
        "^VIX": _fetch_yahoo("^VIX", "1mo"),
    }

    def _make_quote(symbol, klines, name) -> IndexQuote:
        if not klines or len(klines) < 2:
            return IndexQuote(symbol=symbol, name=name, price=0, change_pct=0)
        closes = [k["close"] for k in klines if k.get("close")]
        prices = [k["close"] for k in klines if k.get("close")]
        price = prices[-1] if prices else 0
        change_pct = (prices[-1] - prices[-2]) / prices[-2] * 100 if len(prices) >= 2 else 0
        ma20 = sum(closes[-20:]) / min(20, len(closes)) if len(closes) >= 20 else None
        ma50 = sum(closes[-50:]) / min(50, len(closes)) if len(closes) >= 50 else None
        return IndexQuote(
            symbol=symbol, name=name, price=price,
            change_pct=round(change_pct, 2),
            ma20=round(ma20, 2) if ma20 else None,
            ma50=round(ma50, 2) if ma50 else None,
        )

    spy_quote = _make_quote("SPY", indices["SPY"], "SPY")
    qqq_quote = _make_quote("QQQ", indices["QQQ"], "QQQ")
    iwm_quote = _make_quote("IWM", indices["IWM"], "IWM")
    rsp_quote = _make_quote("RSP", indices["RSP"], "RSP")

    # VIX
    vix = None
    if indices["^VIX"]:
        closes = [k["close"] for k in indices["^VIX"] if k.get("close")]
        if closes:
            vix = closes[-1]

    regime = assess_market_regime(
        spy=spy_quote, qqq=qqq_quote, iwm=iwm_quote, rsp=rsp_quote, vix=vix,
    )

    return jsonable_encoder({
        "regime": regime.regime,
        "score": regime.score,
        "label": regime.label,
        "allow_new_positions": regime.allow_new_positions,
        "reason": regime.reason,
        "multipliers": {
            "breakout": regime.breakout_mult,
            "pullback": regime.pullback_mult,
            "earnings_gap": regime.earnings_gap_mult,
        },
        "indices": {
            "SPY": {"price": spy_quote.price, "change_pct": spy_quote.change_pct, "ma20": spy_quote.ma20, "ma50": spy_quote.ma50},
            "QQQ": {"price": qqq_quote.price, "change_pct": qqq_quote.change_pct, "ma20": qqq_quote.ma20, "ma50": qqq_quote.ma50},
            "IWM": {"price": iwm_quote.price, "change_pct": iwm_quote.change_pct, "ma20": iwm_quote.ma20, "ma50": iwm_quote.ma50},
            "RSP": {"price": rsp_quote.price, "change_pct": rsp_quote.change_pct, "ma20": rsp_quote.ma20, "ma50": rsp_quote.ma50},
        },
        "vix": vix,
        "updated_at": datetime.utcnow().isoformat(),
    })


@router.get("/sectors")
async def get_sectors():
    """获取行业轮动评分"""
    results = []
    today = date.today()

    # 一次性并行拉取所有行业 ETF + SPY（避免串行 13+ 次请求，首屏从数十秒降到数秒）
    from us_quant.data_provider import get_klines_batch
    _etf_symbols = [e[0] for e in SECTOR_ETFS]
    _klines_map = get_klines_batch(_etf_symbols + ["SPY"], "3mo")
    spy_klines = _klines_map.get("SPY")
    spy_closes = [k["close"] for k in spy_klines if k.get("close")] if spy_klines else []
    spy_closes_20d = spy_closes[-20:] if len(spy_closes) >= 20 else spy_closes
    spy_closes_60d = spy_closes[-60:] if len(spy_closes) >= 60 else spy_closes

    for etf_symbol, etf_name, industry in SECTOR_ETFS:
        klines = _klines_map.get(etf_symbol)
        if not klines:
            results.append(score_sector(etf_symbol, etf_name, industry, rank=0))
            continue

        closes = [k["close"] for k in klines if k.get("close")]
        volumes = [k["volume"] for k in klines if k.get("volume")]

        closes_5d = closes[-5:] if len(closes) >= 5 else closes
        closes_20d = closes[-20:] if len(closes) >= 20 else closes
        closes_60d = closes[-60:] if len(closes) >= 60 else closes

        # 均线
        ma20_vals = sma(closes, 20) if len(closes) >= 20 else []
        ma50_vals = sma(closes, 50) if len(closes) >= 50 else []
        current_price = closes[-1] if closes else None

        # 平均成交量
        avg_vol = sum(volumes) / len(volumes) if volumes else None

        sector = score_sector(
            etf_symbol=etf_symbol, etf_name=etf_name, industry=industry,
            closes_5d=closes_5d, closes_20d=closes_20d, closes_60d=closes_60d,
            spy_closes_20d=spy_closes_20d, spy_closes_60d=spy_closes_60d,
            volumes_20d=volumes[-20:] if len(volumes) >= 20 else volumes,
            avg_volume_20d=avg_vol,
            ma20=ma20_vals[-1] if ma20_vals else None,
            ma50=ma50_vals[-1] if ma50_vals else None,
            current_price=current_price,
        )
        results.append(sector)

    ranked = rank_sectors(results)
    return jsonable_encoder({
        "sectors": [
            {
                "etf_symbol": s.etf_symbol,
                "etf_name": s.etf_name,
                "industry": s.industry,
                "total_score": s.total_score,
                "ret_5d": s.ret_5d,
                "ret_20d": s.ret_20d,
                "ret_60d": s.ret_60d,
                "rel_strength_20d": s.rel_strength_20d,
                "rel_strength_60d": s.rel_strength_60d,
                "ma_trend": s.ma_trend,
                "volume_activity": s.volume_activity,
                "rank": s.rank,
                "grade": s.grade,
            }
            for s in ranked
        ],
        "updated_at": datetime.utcnow().isoformat(),
    })


@router.get("/scanner")
async def get_scanner(
    symbols: str = Query("", description="逗号分隔的股票代码（与 universe 互斥；留空则从池取）"),
    universe: str = Query("", description="股票池：CORE_A / CORE_B / ALL / RESEARCH_DYNAMIC"),
    market_mult: float = 1.0,
    sector_mult: float = 1.0,
):
    """扫描并评分股票。symbols 手动模式与 universe 池模式兼容。"""
    # 防御：/overview 等内部直接函数调用时，FastAPI 不会解析 Query 默认值
    def _to_float(v: object, default: float = 1.0) -> float:
        if isinstance(v, (int, float)):
            return float(v)
        inner = getattr(v, "default", None)
        if isinstance(inner, (int, float)):
            return float(inner)
        return default

    market_mult = _to_float(market_mult)
    sector_mult = _to_float(sector_mult)

    # ── 解析候选 ──
    if symbols.strip():
        code_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        pool_source = None
    elif universe.strip():
        uni = universe.strip().upper()
        if uni == "ALL":
            code_list = uniques_for_scanner(["CORE_A", "CORE_B"])
        else:
            code_list = get_universe_members(uni)
        limit = get_scanner_limit(uni) if uni != "ALL" else 120
        code_list = code_list[:limit]
        pool_source = uni
    else:
        return jsonable_encoder({"candidates": [], "count": 0, "message": "请提供股票代码或选择股票池", "pool": None})

    if not code_list:
        return jsonable_encoder({"candidates": [], "count": 0, "message": "股票池候选为空", "pool": pool_source})
    # 并行批量拉取 K 线（单次最多 30 只，避免 Nasdaq 限流）
    from us_quant.data_provider import get_klines_batch
    max_scan = min(len(code_list), 30)
    _klines_map = get_klines_batch(code_list[:max_scan], "3mo")
    candidates = []

    for symbol in code_list[:max_scan]:
        try:
            klines = _klines_map.get(symbol)
            if not klines:
                continue

            closes = [k["close"] for k in klines if k.get("close")]
            highs = [k["high"] for k in klines if k.get("high")]
            lows = [k["low"] for k in klines if k.get("low")]
            volumes = [k["volume"] for k in klines if k.get("volume")]
            price = closes[-1] if closes else None

            if not price:
                continue

            # 技术指标
            ema10_vals = ema(closes, 10)
            ema20_vals = ema(closes, 20)
            ma50_vals = sma(closes, 50)
            rsi_val = calc_rsi(closes, 14)
            macd_val = calc_macd(closes)
            kdj_val = calc_kdj(closes)

            ema10 = ema10_vals[-1] if ema10_vals else None
            ema20 = ema20_vals[-1] if ema20_vals else None
            ma50 = ma50_vals[-1] if ma50_vals else None

            # 硬过滤
            hf = check_hard_filters(price=price)

            # 平台突破评分
            high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
            base_high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
            base_low = min(closes[-20:]) if len(closes) >= 20 else min(closes)
            base_days = 20
            rel_vol = (volumes[-1] / (sum(volumes[-5:]) / 5)) if len(volumes) >= 5 else 1.0
            change_today = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

            bs = score_breakout(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                high_52w=high_52w, base_high=base_high, base_low=base_low,
                base_days=base_days, rel_volume=rel_vol,
                change_pct_today=change_today,
                market_mult=market_mult,
            )

            # 趋势回踩评分
            prior_uptrend = bool(ema10 and ema20 and ma50 and ema10 > ema20 > ma50)
            pullback_pct = None
            if len(closes) >= 10:
                peak = max(closes[-10:])
                pullback_pct = (peak - price) / peak * 100

            ps = score_pullback(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                prior_uptrend=prior_uptrend, first_pullback=True,
                pullback_pct=pullback_pct, volume_contracted=True,
                no_consecutive_bearish=True,
                market_mult=market_mult,
            )

            # 7状态
            state = determine_stock_state(
                price=price, ma20=ema20, ma50=ma50,
                rsi=rsi_val,
            )

            # 计算关键位
            stop_loss = None
            if ma50 and price:
                stop_loss = round(ma50 * 0.97, 2)
            elif price:
                stop_loss = round(price * 0.95, 2)

            candidates.append({
                "symbol": symbol,
                "price": round(price, 2),
                "change_pct": round(change_today, 2),
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "macd": macd_val,
                "kdj": kdj_val,
                "ema10": round(ema10, 2) if ema10 else None,
                "ema20": round(ema20, 2) if ema20 else None,
                "ma50": round(ma50, 2) if ma50 else None,
                "hard_filter_pass": hf.passed,
                "hard_filter_reasons": hf.reasons,
                "breakout_score": bs.total if bs.hard_pass else None,
                "breakout_details": bs.details,
                "pullback_score": ps.total if ps.hard_pass else None,
                "pullback_details": ps.details,
                "state": state.state,
                "state_label": state.label,
                "state_signal": state.signal,
                "stop_loss": stop_loss,
                "ma_bias": round(ma_bias(price, ma50), 2) if ma50 else None,
            })
        except Exception as exc:
            logger.warning(f"Scanner error for {symbol}: {exc}")
            continue

    candidates.sort(key=lambda x: max(
        x.get("breakout_score") or 0,
        x.get("pullback_score") or 0,
    ), reverse=True)

    # 计算排名
    for i, c in enumerate(candidates):
        c["rank"] = i + 1

    return jsonable_encoder({
        "candidates": candidates,
        "count": len(candidates),
        "pool": pool_source,
        "pool_total": len(code_list),
        "scanned": max_scan,
        "updated_at": datetime.utcnow().isoformat(),
    })


@router.get("/overview")
async def get_overview():
    """获取综合仪表盘数据"""
    from us_quant.data_provider import is_live_available, _get_proxies
    regime_data = await get_regime()
    sectors_data = await get_sectors()

    # 默认关注股票（scanner 缓存由启动预热填充；冷启动若偶发丢数据则错峰重试补齐）
    watchlist = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "TSM"]
    scanner_data = await get_scanner(symbols=",".join(watchlist))

    return jsonable_encoder({
        "regime": regime_data,
        "sectors": sectors_data["sectors"],
        "scanner": scanner_data["candidates"],
        "scanner_count": scanner_data["count"],
        "updated_at": datetime.utcnow().isoformat(),
        "system": {
            "status": "running",
            "mode": "SHADOW",
            "allow_live": False,
            "version": "2.1.1",
            "data_provider": "nasdaq" if is_live_available() else "offline-sim",
            "live": is_live_available(),
            "proxy": (_get_proxies() or {}).get("https"),
            "broker": "paper",
        },
    })


@router.get("/system/status")
async def get_system_status():
    """获取系统状态"""
    from us_quant.data_provider import is_live_available, _get_proxies
    live = is_live_available()
    proxies = _get_proxies()
    return jsonable_encoder({
        "status": "running",
        "mode": "SHADOW",
        "allow_live": False,
        "version": "2.1.1",
        "data_provider": "nasdaq" if live else "offline-sim",
        "live": live,
        "proxy": proxies["https"] if proxies else None,
        "broker": "paper",
        "last_scan": None,
        "uptime": datetime.utcnow().isoformat(),
    })


@router.get("/positions")
async def get_positions():
    """获取当前持仓"""
    try:
        with get_db_session() as db:
            from us_quant.repository import USPosition
            rows = db.query(USPosition).filter(
                USPosition.status == "ACTIVE"
            ).all()
            return jsonable_encoder({
                "positions": [
                    {
                        "symbol": r.symbol,
                        "name": r.name,
                        "strategy": r.strategy,
                        "entry_price": float(r.entry_price) if r.entry_price else None,
                        "current_price": float(r.current_price) if r.current_price else None,
                        "quantity": r.quantity,
                        "unrealized_pl": float(r.unrealized_pl) if r.unrealized_pl else None,
                        "unrealized_pl_pct": float(r.unrealized_pl_pct) if r.unrealized_pl_pct else None,
                        "stop_price": float(r.stop_price) if r.stop_price else None,
                        "holding_days": r.holding_days,
                        "sector": r.sector,
                        "status": r.status,
                    }
                    for r in rows
                ],
                "count": len(rows),
            })
    except Exception as exc:
        return jsonable_encoder({"positions": [], "count": 0, "error": str(exc)})


@router.get("/signals")
async def get_signals(status: str = "ACTIVE"):
    """获取交易信号"""
    # 防御：refresh_signal_cache 等内部直调时 status 可能是 Query 对象
    if not isinstance(status, str):
        status = getattr(status, "default", "ACTIVE")
    try:
        with get_db_session() as db:
            from us_quant.repository import USSignal
            query = db.query(USSignal)
            if status != "ALL":
                query = query.filter(USSignal.lifecycle_status == status)
            rows = query.order_by(USSignal.created_at.desc()).limit(50).all()
            return jsonable_encoder({
                "signals": [
                    {
                        "id": r.id,
                        "symbol": r.symbol,
                        "name": r.name,
                        "strategy": r.strategy,
                        "signal_type": r.signal_type,
                        "lifecycle_status": r.lifecycle_status,
                        "score": float(r.score) if r.score else None,
                        "planned_entry": float(r.planned_entry) if r.planned_entry else None,
                        "planned_stop": float(r.planned_stop) if r.planned_stop else None,
                        "expected_rr": float(r.expected_rr) if r.expected_rr else None,
                        "risk_veto": r.risk_veto,
                        "market_regime": r.market_regime,
                        "signal_time": r.signal_time.isoformat() if r.signal_time else None,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ],
                "count": len(rows),
            })
    except Exception as exc:
        return jsonable_encoder({"signals": [], "count": 0, "error": str(exc)})


# ─── 预设美股扫描池 ──────────────────────────────────────────────────────────

US_SCAN_POOL = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "TSM",
    "AVGO", "AMD", "JPM", "V", "MA", "UNH", "HD", "DIS", "NFLX",
    "ADBE", "CRM", "ORCL", "IBM", "QCOM", "TXN",
    "XOM", "CVX", "JNJ", "PFE", "MRK", "ABBV", "LLY",
    "PG", "KO", "PEP", "WMT", "COST", "MCD", "SBUX", "NKE",
    "BAC", "WFC", "GS", "MS", "BLK",
    "CAT", "BA", "GE", "LMT",
]


# ─── 自动扫描（预设池+落库）───────────────────────────────────────────────────

def run_us_quant_scan(trade_date: Optional[str] = None) -> dict:
    """对预设美股池运行全策略扫描，结果落库到 USStrategyScore，高分自动生成信号"""
    from us_quant.data_provider import get_klines_batch, get_quote
    from datetime import date as dt_date

    scan_date = trade_date or datetime.utcnow().strftime("%Y-%m-%d")
    symbols = US_SCAN_POOL
    klines_map = get_klines_batch(symbols, "3mo")
    candidates = []
    scored = 0

    for symbol in symbols:
        try:
            klines = klines_map.get(symbol)
            if not klines or len(klines) < 30:
                continue

            closes = [k["close"] for k in klines if k.get("close")]
            highs = [k["high"] for k in klines if k.get("high")]
            lows = [k["low"] for k in klines if k.get("low")]
            volumes = [k["volume"] for k in klines if k.get("volume")]
            price = closes[-1] if closes else None
            if not price:
                continue

            ema10_vals = ema(closes, 10)
            ema20_vals = ema(closes, 20)
            ma50_vals = sma(closes, 50)
            rsi_val = calc_rsi(closes, 14)

            ema10 = ema10_vals[-1] if ema10_vals else None
            ema20 = ema20_vals[-1] if ema20_vals else None
            ma50 = ma50_vals[-1] if ma50_vals else None

            # 突破评分
            high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
            base_high = max(closes[-20:]) if len(closes) >= 20 else max(closes)
            base_low = min(closes[-20:]) if len(closes) >= 20 else min(closes)
            rel_vol = (volumes[-1] / (sum(volumes[-5:]) / 5)) if len(volumes) >= 5 else 1.0
            change_today = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) >= 2 else 0

            bs = score_breakout(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                high_52w=high_52w, base_high=base_high, base_low=base_low,
                base_days=20, rel_volume=rel_vol, change_pct_today=change_today,
            )

            # 回踩评分
            prior_uptrend = bool(ema10 and ema20 and ma50 and ema10 > ema20 > ma50)
            pullback_pct = None
            if len(closes) >= 10:
                peak = max(closes[-10:])
                pullback_pct = (peak - price) / peak * 100

            ps = score_pullback(
                price=price, ema10=ema10, ema20=ema20, ma50=ma50,
                prior_uptrend=prior_uptrend, first_pullback=True,
                pullback_pct=pullback_pct, volume_contracted=True,
                no_consecutive_bearish=True,
            )

            # 状态
            state = determine_stock_state(price=price, ma20=ema20, ma50=ma50, rsi=rsi_val)

            # 确定主策略
            primary = None
            max_score = 0
            if bs.hard_pass and bs.total > max_score:
                primary = "breakout"
                max_score = bs.total
            if ps.hard_pass and ps.total > max_score:
                primary = "pullback"
                max_score = ps.total

            if not primary:
                continue

            scored += 1
            entry = {
                "symbol": symbol,
                "price": round(price, 2),
                "change_pct": round(change_today, 2),
                "rsi": round(rsi_val, 1) if rsi_val else None,
                "ema10": round(ema10, 2) if ema10 else None,
                "ema20": round(ema20, 2) if ema20 else None,
                "ma50": round(ma50, 2) if ma50 else None,
                "breakout_score": round(bs.total, 1) if bs.hard_pass else None,
                "pullback_score": round(ps.total, 1) if ps.hard_pass else None,
                "primary_strategy": primary,
                "state": state.state,
                "state_label": state.label,
                "stop_loss": round(ma50 * 0.97, 2) if ma50 else round(price * 0.95, 2),
            }
            candidates.append(entry)

            # 落库到 USStrategyScore
            try:
                with get_db_session() as db:
                    # 先删旧记录
                    db.query(USStrategyScore).filter(
                        USStrategyScore.trade_date == scan_date,
                        USStrategyScore.symbol == symbol,
                    ).delete()
                    row = USStrategyScore(
                        trade_date=scan_date,
                        symbol=symbol,
                        breakout_score=round(bs.total, 1) if bs.hard_pass else None,
                        pullback_score=round(ps.total, 1) if ps.hard_pass else None,
                        primary_strategy=primary,
                        hard_filter_pass=bs.hard_pass or ps.hard_pass,
                        state=state.state,
                        state_label=state.label,
                        strategy_version="1.0.0",
                    )
                    db.add(row)
                    db.commit()
            except Exception as db_err:
                logger.warning(f"[us-quant] save strategy score failed {symbol}: {db_err}")

            # 高分（>=70）自动生成信号
            if max_score >= 70:
                try:
                    with get_db_session() as db:
                        stop_loss = round(ma50 * 0.97, 2) if ma50 else round(price * 0.95, 2)
                        target = round(price * 1.15, 2)
                        rr = round((target - price) / (price - stop_loss), 2) if (price - stop_loss) > 0 else 0

                        signal = USSignal(
                            symbol=symbol,
                            strategy=primary,
                            strategy_version="1.0.0",
                            signal_type="ENTRY",
                            lifecycle_status="DISCOVERED",
                            score=max_score,
                            signal_time=datetime.utcnow(),
                            expires_at=datetime.utcnow() + timedelta(days=3),
                            planned_entry=price,
                            planned_stop=stop_loss,
                            planned_target=target,
                            expected_rr=rr,
                        )
                        db.add(signal)
                        db.commit()
                except Exception as sig_err:
                    logger.warning(f"[us-quant] create signal failed {symbol}: {sig_err}")

        except Exception as exc:
            logger.warning(f"[us-quant] scan error {symbol}: {exc}")
            continue

    candidates.sort(key=lambda x: max(
        x.get("breakout_score") or 0,
        x.get("pullback_score") or 0,
    ), reverse=True)
    for i, c in enumerate(candidates):
        c["rank"] = i + 1

    return {
        "candidates": candidates,
        "count": len(candidates),
        "scored": scored,
        "total": len(symbols),
        "updated_at": datetime.utcnow().isoformat(),
    }


# ─── API: 触发自动扫描 ────────────────────────────────────────────────────────

@router.get("/scan")
async def api_scan():
    """触发预设池自动扫描并落库"""
    try:
        result = run_us_quant_scan()
        return jsonable_encoder({
            "status": "ok",
            "result": result,
        })
    except Exception as exc:
        return jsonable_encoder({"status": "error", "error": str(exc)})


# ─── API: 获取策略扫描结果 ────────────────────────────────────────────────────

@router.get("/scan-results")
async def get_scan_results(trade_date: str = ""):
    """获取指定日期的策略扫描结果"""
    if not trade_date:
        trade_date = datetime.utcnow().strftime("%Y-%m-%d")
    try:
        with get_db_session() as db:
            rows = db.query(USStrategyScore).filter(
                USStrategyScore.trade_date == trade_date,
                USStrategyScore.hard_filter_pass == True,
            ).order_by(
                (func.coalesce(USStrategyScore.breakout_score, 0) +
                 func.coalesce(USStrategyScore.pullback_score, 0)).desc()
            ).limit(50).all()
            return jsonable_encoder({
                "results": [
                    {
                        "symbol": r.symbol,
                        "breakout_score": float(r.breakout_score) if r.breakout_score else None,
                        "pullback_score": float(r.pullback_score) if r.pullback_score else None,
                        "primary_strategy": r.primary_strategy,
                        "state": r.state,
                        "state_label": r.state_label,
                    }
                    for r in rows
                ],
                "count": len(rows),
                "trade_date": trade_date,
            })
    except Exception as exc:
        return jsonable_encoder({"results": [], "count": 0, "error": str(exc)})


# ─── API: 触发回测 ────────────────────────────────────────────────────────────

@router.get("/backtest")
async def api_backtest(
    symbols: str = "",
    strategy: str = "ALL",
    start_date: str = "",
    end_date: str = "",
    pool_source: str = "",
):
    """触发回测（V2.2: 支持 pool_source 参数，从 universe_memberships 读取池）"""
    try:
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else None
        results = run_backtest_batch(
            symbols=sym_list,
            strategy=strategy,
            start_date=start_date or None,
            end_date=end_date or None,
            save_to_db=True,
            pool_source=pool_source or None,
        )
        return jsonable_encoder({
            "status": "ok",
            "results": [
                {
                    "symbol": r.symbol,
                    "strategy": r.strategy,
                    "total_trades": r.total_trades,
                    "winning_trades": r.winning_trades,
                    "losing_trades": r.losing_trades,
                    "win_rate": r.win_rate,
                    "total_pnl": r.total_pnl,
                    "total_pnl_pct": r.total_pnl_pct,
                    "profit_factor": r.profit_factor,
                    "max_drawdown_pct": r.max_drawdown_pct,
                    "sharpe_ratio": r.sharpe_ratio,
                    "avg_bars_held": r.avg_bars_held,
                }
                for r in results
            ],
            "count": len(results),
        })
    except Exception as exc:
        return jsonable_encoder({"status": "error", "error": str(exc)})


# ─── API: 查看回测结果 ────────────────────────────────────────────────────────

@router.get("/backtest/results")
async def get_backtest_results(limit: int = 20):
    """获取最近的回测结果"""
    try:
        with get_db_session() as db:
            rows = db.query(USBacktestResult).order_by(
                USBacktestResult.run_at.desc()
            ).limit(limit).all()
            return jsonable_encoder({
                "results": [
                    {
                        "run_id": r.run_id,
                        "symbol": r.symbol,
                        "strategy": r.strategy,
                        "total_trades": r.total_trades,
                        "win_rate": float(r.win_rate) if r.win_rate else None,
                        "total_pnl_pct": float(r.total_pnl_pct) if r.total_pnl_pct else None,
                        "profit_factor": float(r.profit_factor) if r.profit_factor else None,
                        "max_drawdown_pct": float(r.max_drawdown_pct) if r.max_drawdown_pct else None,
                        "sharpe_ratio": float(r.sharpe_ratio) if r.sharpe_ratio else None,
                        "run_at": r.run_at.isoformat() if r.run_at else None,
                    }
                    for r in rows
                ],
                "count": len(rows),
            })
    except Exception as exc:
        return jsonable_encoder({"results": [], "count": 0, "error": str(exc)})


# ─── API: 查看回测交易详情 ────────────────────────────────────────────────────

@router.get("/backtest/trades")
async def get_backtest_trades(run_id: str = ""):
    """获取指定 run_id 的回测交易明细"""
    if not run_id:
        return jsonable_encoder({"trades": [], "error": "请提供 run_id"})
    try:
        with get_db_session() as db:
            rows = db.query(USBacktestTrade).filter(
                USBacktestTrade.run_id == run_id
            ).order_by(USBacktestTrade.entry_date).all()
            return jsonable_encoder({
                "trades": [
                    {
                        "symbol": r.symbol,
                        "strategy": r.strategy,
                        "entry_date": r.entry_date,
                        "entry_price": float(r.entry_price) if r.entry_price else None,
                        "exit_date": r.exit_date,
                        "exit_price": float(r.exit_price) if r.exit_price else None,
                        "direction": r.direction,
                        "shares": r.shares,
                        "pnl": float(r.pnl) if r.pnl else None,
                        "pnl_pct": float(r.pnl_pct) if r.pnl_pct else None,
                        "bars_held": r.bars_held,
                        "exit_reason": r.exit_reason,
                    }
                    for r in rows
                ],
                "count": len(rows),
            })
    except Exception as exc:
        return jsonable_encoder({"trades": [], "count": 0, "error": str(exc)})


# ═══════════════════════════════════════════════════════════════════════════
# 股票池 API（US_Quant_Stock_Universe_V2.0）
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/universes")
async def get_universes():
    """列出所有股票池（含当前成员数量与目标数量）。"""
    return jsonable_encoder({
        "universes": list_universes(),
        "stats": pool_stats(),
    })


@router.get("/universe/{code}")
async def get_universe_detail(code: str):
    """获取单个股票池的完整信息（定义 + 成员列表）。"""
    entry = get_universe(code)
    if not entry:
        return jsonable_encoder({"error": f"未知股票池: {code}"})
    return jsonable_encoder(entry)


@router.get("/universe/{code}/members")
async def get_universe_members_api(code: str):
    """获取单个股票池的成员符号列表。"""
    members = get_universe_members(code)
    defn = UNIVERSE_DEFINITIONS.get(code.upper(), {})
    return jsonable_encoder({
        "universe": code.upper(),
        "name": defn.get("name", ""),
        "members": members,
        "count": len(members),
        "target": defn.get("target_count"),
    })


# ─── API: 股票池再平衡（V2.2）─────────────────────────────────────────────────

@router.get("/rebalance")
async def api_rebalance(dry_run: bool = True):
    """触发股票池再平衡（V2.2: 按配置自动填充 300/500/1500 目标）

    Args:
        dry_run: True=预览, False=执行写入
    """
    report = run_rebalance(dry_run=dry_run)
    return jsonable_encoder(report)
