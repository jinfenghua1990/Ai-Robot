"""策略扫描 API —— 18 个内置策略（移植自 tickflow-stock-panel）对 A股/美股候选池扫描。"""
from __future__ import annotations

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Query  # noqa: E402
from sqlalchemy import func as sql_func  # noqa: E402

from api.strategy_lib import list_strategies, enrich_features, run_strategy  # noqa: E402

router = APIRouter()

# 扫描结果缓存（strategy_key -> {data, ts}，TTL 300s）
_scan_cache: dict = {}
_SCAN_TTL = 300
_MAX_CACHE = 50


def _cache_get(key):
    c = _scan_cache.get(key)
    if c and time.time() - c["ts"] < _SCAN_TTL:
        return c["data"]
    return None


def _cache_set(key, data):
    if len(_scan_cache) >= _MAX_CACHE:
        oldest = min(_scan_cache.items(), key=lambda x: x[1]["ts"])
        _scan_cache.pop(oldest[0], None)
    _scan_cache[key] = {"data": data, "ts": time.time()}


@router.get("/api/strategy-scan/strategies")
def strategies_list(market: str = Query("a", description="a= A股, us= 美股")):
    """策略列表（含参数定义）。"""
    try:
        return {"ok": True, "data": list_strategies(market), "error": None}
    except Exception as e:
        return {"ok": False, "data": [], "error": str(e)}


async def _a_pool(db, limit: int):
    """A股候选池：主力净流入 > 0 的前 N 只。"""
    from db.models import StockFlow
    latest_subq = db.query(sql_func.max(StockFlow.id).label("max_id")).group_by(StockFlow.ts_code).subquery()
    q = db.query(StockFlow).join(
        latest_subq, StockFlow.id == latest_subq.c.max_id
    ).filter(StockFlow.main_force_inflow > 0)
    rows = q.order_by(StockFlow.main_force_inflow.desc()).limit(limit).all()
    return [{"code": r.ts_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", ""),
             "name": r.name, "sector": r.sector or ""} for r in rows]


async def _scan_a(db, strategy_id: str, params: dict, pool_limit: int):
    """A股扫描：逐股取K线（本地库优先）+ 策略判定。"""
    from api.bs_screener.core import _fetch_kline_cached
    pool = await _a_pool(db, pool_limit)
    if not pool:
        return {"total": 0, "hits": [], "pool": [], "message": "候选池为空（无主力流入数据）"}

    semaphore = asyncio.Semaphore(12)

    async def one(item):
        async with semaphore:
            try:
                klines = await _fetch_kline_cached(item["code"], 260)
                if not klines or len(klines) < 30:
                    return None
                feats = enrich_features(klines, item["code"])
                res = run_strategy(strategy_id, feats, params)
                if not res or not res["hit"]:
                    return None
                return {
                    "code": item["code"], "name": item["name"], "sector": item["sector"],
                    "price": round(feats.get("close") or 0, 2),
                    "change_pct": round((feats.get("change_pct") or 0) * 100, 2),
                    "reason": res["reason"],
                    "ma20": round(feats["ma20"], 2) if feats.get("ma20") else None,
                    "rsi": round(feats["rsi_14"], 1) if feats.get("rsi_14") else None,
                    "vol_ratio": round(feats["vol_ratio_5d"], 2) if feats.get("vol_ratio_5d") else None,
                    "boards": feats.get("consecutive_limit_ups", 0),
                }
            except Exception:
                return None

    results = await asyncio.gather(*[one(i) for i in pool], return_exceptions=True)
    hits = [r for r in results if r and not isinstance(r, Exception)]
    hits.sort(key=lambda x: x["change_pct"], reverse=True)
    return {"total": len(hits), "hits": hits, "pool": [i["code"] for i in pool], "message": ""}


async def _us_pool(limit: int):
    """美股候选池：US_WATCHLIST 自选 + CORE_A/CORE_B 合并前 N 只。"""
    try:
        from us_quant.universe import get_universe_members
        a = list(get_universe_members("US_WATCHLIST"))[:limit]
        b = list(get_universe_members("CORE_A"))[:limit]
        c = list(get_universe_members("CORE_B"))[:limit]
        return list(dict.fromkeys(a + b + c))[:limit]
    except Exception:
        # 回退：美股自选池
        try:
            from us_quant.universe import get_universe_members as g2
            return list(g2("US_WATCHLIST"))[:limit]
        except Exception:
            return []


async def _scan_us(strategy_id: str, params: dict, pool_limit: int):
    """美股扫描：批量拉K线（数据库→多源采集）+ 策略判定。"""
    from us_quant.data_provider import get_klines_batch
    codes = await _us_pool(pool_limit)
    if not codes:
        return {"total": 0, "hits": [], "pool": [], "message": "候选池为空"}

    batch = codes[:min(len(codes), 40)]
    kl_map = await asyncio.to_thread(get_klines_batch, batch, "1y", 8)

    hits = []
    for sym in batch:
        klines = kl_map.get(sym)
        if not klines or len(klines) < 30:
            continue
        try:
            feats = enrich_features(klines, sym)
            res = run_strategy(strategy_id, feats, params)
            if not res or not res["hit"]:
                continue
            hits.append({
                "code": sym, "name": sym, "sector": "",
                "price": round(feats.get("close") or 0, 2),
                "change_pct": round((feats.get("change_pct") or 0) * 100, 2),
                "reason": res["reason"],
                "ma20": round(feats["ma20"], 2) if feats.get("ma20") else None,
                "rsi": round(feats["rsi_14"], 1) if feats.get("rsi_14") else None,
                "vol_ratio": round(feats["vol_ratio_5d"], 2) if feats.get("vol_ratio_5d") else None,
                "boards": 0,
            })
        except Exception:
            continue
    hits.sort(key=lambda x: x["change_pct"], reverse=True)
    return {"total": len(hits), "hits": hits, "pool": batch, "message": ""}


@router.get("/api/strategy-scan/run")
async def strategy_scan(
    market: str = Query("a", description="a= A股, us= 美股"),
    strategy_id: str = Query(..., description="策略 id，见 /strategies"),
    limit: int = Query(30, ge=1, le=100),
    params_json: str = Query("{}", description="策略参数 JSON"),
    refresh: bool = Query(False, description="强制刷新缓存"),
):
    """运行策略扫描。"""
    import json
    try:
        params = json.loads(params_json) if isinstance(params_json, str) else (params_json or {})
        if not isinstance(params, dict):
            return {"ok": False, "data": None, "error": "params_json 必须是 JSON 对象"}
    except Exception as e:
        return {"ok": False, "data": None, "error": f"params_json 解析失败: {e}"}

    # 校验策略存在且市场适用
    meta = next((m for m in list_strategies(market) if m["id"] == strategy_id), None)
    if meta is None:
        return {"ok": False, "data": None, "error": f"策略 {strategy_id} 不存在或不适配 {market} 市场"}

    key = f"{market}:{strategy_id}:{json.dumps(params, sort_keys=True)}:{limit}"
    if not refresh:
        cached = _cache_get(key)
        if cached is not None:
            return {"ok": True, "data": cached, "error": None}

    try:
        t0 = time.time()
        if market == "us":
            result = await _scan_us(strategy_id, params, pool_limit=min(limit * 4, 60))
        else:
            from db.session import get_db_session
            with get_db_session() as db:
                result = await _scan_a(db, strategy_id, params, pool_limit=min(limit * 5, 150))
        result["scanned"] = len(result.get("pool", []))
        result["hits"] = result["hits"][:limit]
        result["total"] = len(result["hits"])
        result["elapsed_ms"] = round((time.time() - t0) * 1000, 0)
        result["strategy"] = {"id": meta["id"], "name": meta["name"], "description": meta["description"]}
        _cache_set(key, result)
        return {"ok": True, "data": result, "error": None}
    except Exception as e:
        return {"ok": False, "data": None, "error": str(e)}
