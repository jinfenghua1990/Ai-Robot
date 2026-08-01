"""
共享数据层：统一管理自选股/持仓/重点关注，所有子系统共享同一个数据源
"""
import json, os, logging
from datetime import date
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

logger = logging.getLogger("airobot.shared")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WATCHLIST_PATH = os.path.join(ROOT, "watchlist.json")
PORTFOLIO_PATH = os.path.join(ROOT, "portfolio.json")
FOCUS_PATH = os.path.join(ROOT, "focus.json")
STOCK_NOTES_PATH = os.path.join(ROOT, "stock_notes.json")

router = APIRouter()


def _read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("读取 %s 失败: %s", path, e)
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 自选股 ───────────────────────────────────────────────

def get_watchlist():
    return _read_json(WATCHLIST_PATH, {"stocks": []})


def save_watchlist(data):
    _write_json(WATCHLIST_PATH, data)


@router.get("/api/shared/watchlist")
async def shared_watchlist():
    """返回统一自选股列表"""
    return get_watchlist()


@router.get("/api/shared/watchlist/codes")
async def shared_watchlist_codes():
    """返回自选股代码列表（简洁模式，供研究与交易页面使用）"""
    wl = get_watchlist()
    return {"codes": [s["code"] for s in wl.get("stocks", [])]}


class AddCodesRequest(BaseModel):
    codes: list[str]
    note: str = "研究工作区同步"
    group: str = "研究工作区同步"


@router.post("/api/shared/watchlist/add")
async def shared_watchlist_add(req: AddCodesRequest):
    """批量添加自选股代码：写 JSON → 写 DB → 重置缓存 → 触发云同步"""
    from db.session import get_db_session
    from db.models import Watchlist
    from api.watchlist._shared import reset_watchlist_cache

    codes = [c.strip() for c in req.codes if c and c.strip()]
    if not codes:
        return {"status": "ok", "added": 0}

    # 1. 写 JSON（唯一真相源）
    data = get_watchlist()
    stocks = data.setdefault("stocks", [])
    existing_codes = {s["code"] for s in stocks}

    # 2. 同步到 DB
    with get_db_session() as db:
        existing_map = {item.stock_code: item for item in db.query(Watchlist).all()}
        for code in codes:
            if code not in existing_codes:
                stocks.append({"code": code, "name": "", "note": req.note, "group": req.group})
                existing_codes.add(code)
            item = existing_map.get(code)
            if item:
                if req.note:
                    item.note = req.note
                if req.group:
                    item.group_name = req.group
            else:
                db.add(Watchlist(
                    stock_code=code,
                    stock_name="",
                    note=req.note,
                    group_name=req.group,
                ))
                existing_map[code] = None
        db.commit()

    save_watchlist(data)

    # 3. 重置缓存
    reset_watchlist_cache()

    # 4. 触发云同步（防抖 3 秒后推送所有云端）
    try:
        from api.sync_pkg import trigger_cloud_sync
        for code in codes:
            trigger_cloud_sync(f"add {code}")
    except Exception as e:
        logger.debug("cloud sync trigger failed: %s", e)

    return {"status": "ok", "added": len(codes)}


class RemoveCodeRequest(BaseModel):
    code: str


@router.post("/api/shared/watchlist/remove")
async def shared_watchlist_remove(req: RemoveCodeRequest):
    """删除自选股：写 JSON → 写 DB → 重置缓存 → 触发云删除"""
    from db.session import get_db_session
    from db.models import Watchlist
    from api.watchlist._shared import reset_watchlist_cache

    code = req.code

    # 1. 从 JSON 删除
    data = get_watchlist()
    data["stocks"] = [s for s in data.get("stocks", []) if s["code"] != code]
    save_watchlist(data)

    # 2. 从 DB 删除
    stock_name = code
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if item:
            stock_name = item.stock_name or code
            db.delete(item)
            db.commit()

    # 3. 重置缓存
    reset_watchlist_cache()

    # 4. 触发云删除
    try:
        from api.sync_pkg import trigger_cloud_delete
        trigger_cloud_delete(code, stock_name)
    except Exception as e:
        logger.debug("cloud delete trigger failed: %s", e)

    return {"status": "ok", "removed": code}


# ─── 持仓 ─────────────────────────────────────────────────

def get_portfolio():
    """从缓存文件读取持仓"""
    return _read_json(PORTFOLIO_PATH, {"positions": [], "count": 0, "total_market_value": 0})


# ─── 持仓自动同步到自选 ─────────────────────────────────

def _sync_portfolio_to_watchlist(items: list[dict]) -> dict:
    """持仓 → 自选 自动同步：只加不减、去重；仅在真正新增时写盘。
    返回 {"added": n, "skipped": m}
    """
    codes = sorted({str(it.get("symbol", "")).strip() for it in items if it.get("symbol")})
    if not codes:
        return {"added": 0, "skipped": 0}

    data = get_watchlist()
    stocks = data.setdefault("stocks", [])
    existing_codes = {s.get("code") for s in stocks}
    missing = [c for c in codes if c not in existing_codes]
    if not missing:
        return {"added": 0, "skipped": len(codes)}

    name_map = {str(it.get("symbol", "")).strip(): (it.get("name") or "") for it in items}

    # 1. 写 JSON（唯一真相源）
    for c in missing:
        stocks.append({"code": c, "name": name_map.get(c, ""), "note": "持仓自动同步", "group": "持仓同步"})
        existing_codes.add(c)
    save_watchlist(data)

    # 2. 同步到 DB + 重置缓存
    try:
        from db.session import get_db_session
        from db.models import Watchlist
        from api.watchlist._shared import reset_watchlist_cache
        with get_db_session() as db:
            existing_map = {item.stock_code: item for item in db.query(Watchlist).all()}
            for c in missing:
                if c not in existing_map:
                    db.add(Watchlist(
                        stock_code=c,
                        stock_name=name_map.get(c, ""),
                        note="持仓自动同步",
                        group_name="持仓同步",
                    ))
            db.commit()
        reset_watchlist_cache()
    except Exception as e:
        logger.warning("持仓同步到自选 DB 失败: %s", e)

    # 3. 触发云同步（防抖推送）
    try:
        from api.sync_pkg import trigger_cloud_sync
        for c in missing:
            trigger_cloud_sync(f"add {c} (portfolio auto-sync)")
    except Exception as e:
        logger.debug("cloud sync trigger failed: %s", e)

    logger.info("持仓自动同步到自选: 新增 %d 只 (跳过 %d)", len(missing), len(codes) - len(missing))
    return {"added": len(missing), "skipped": len(codes) - len(missing)}


async def _refresh_portfolio(force=False):
    """刷新本地妙想模拟盘持仓到统一缓存；不再依赖 DSA。
    
    数据源说明：
    - 妙想 (miaoxiang): 用户在模拟账户中交易的实时持仓，为唯一持仓来源
    - 获取失败时保留 portfolio.json 中上一次成功快照
    """
    from api.trading import get_positions, get_balance

    # 1. 拉妙想模拟交易持仓
    mx_items: list[dict] = []
    positions_ok = False
    try:
        pos_data = await get_positions(force=force)
        positions_ok = True
        for p in pos_data.get("positions", []):
            qty = p.get("count", 0) or 0
            if qty <= 0:
                continue
            mx_items.append({
                "symbol": p.get("secCode", ""),
                "name": p.get("secName", ""),
                "market": "cn",
                "quantity": float(qty),
                "avg_cost": float(p.get("costPrice", 0) or 0),
                "last_price": float(p.get("price", 0) or 0),
                "market_value": float(p.get("value", 0) or 0),
                "unrealized_pnl": float(p.get("profit", 0) or 0),
                "profit_ratio": round(float(p.get("profitPct", 0) or 0), 2),
                "day_pnl": float(p.get("dayProfit", 0) or 0),
                "day_pnl_pct": round(float(p.get("dayProfitPct", 0) or 0), 2),
                "pos_pct": round(float(p.get("posPct", 0) or 0), 2),
                "source": "miaoxiang",
            })
    except Exception as e:
        logger.warning("妙想模拟交易持仓拉取失败: %s", e)

    if not positions_ok:
        previous = get_portfolio()
        previous["data_quality"] = "持仓源暂时不可用，保留上次成功快照"
        return previous

    items = list(mx_items)
    total_mv = sum(it["market_value"] for it in items)
    total_upnl = sum(it["unrealized_pnl"] for it in items)
    total_cost = sum((it.get("avg_cost", 0) or 0) * (it.get("quantity", 0) or 0) for it in items)
    total_day_pnl = sum(it.get("day_pnl", 0) or 0 for it in items)

    # 妙想模拟盘可用资金（现金余额），API 失败时回退到上次缓存值
    available_cash = 0.0
    try:
        bal = await get_balance(force=force)
        available_cash = float(bal.get("availBalance", 0) or 0)
    except Exception as e:
        prev = _read_json(PORTFOLIO_PATH)
        prev_cash = float(prev.get("available_cash", 0) or 0) if prev else 0
        available_cash = prev_cash
        logger.warning("查询妙想账户资金失败，回退到上次缓存值 %.2f: %s", prev_cash, e)

    total_assets = round(total_mv + available_cash, 2)

    # 持仓自动同步到自选（只加不减、去重；仅在真正新增时写盘）
    try:
        sync_info = _sync_portfolio_to_watchlist(items)
    except Exception as e:
        logger.warning("持仓自动同步到自选失败: %s", e)
        sync_info = {"added": 0, "skipped": 0}

    cache = {
        "as_of": date.today().isoformat(),
        "watchlist_sync": sync_info,
        "total_market_value": round(total_mv, 2),
        "total_unrealized_pnl": round(total_upnl, 2),
        "total_assets": total_assets,
        "available_cash": round(available_cash, 2),
        "total_cost": round(total_cost, 2),
        "total_day_pnl": round(total_day_pnl, 2),
        "positions": items,
        "count": len(items),
        "data_sources": {
            "miaoxiang": len([p for p in items if p.get("source") == "miaoxiang"]),
            "dsa": 0,
        },
    }
    _write_json(PORTFOLIO_PATH, cache)
    return cache


@router.get("/api/shared/portfolio")
async def shared_portfolio(force: int = Query(0, description="1=强制刷新缓存")):
    """返回统一持仓数据"""
    if force:
        await _refresh_portfolio(force=True)
    return get_portfolio()


@router.post("/api/shared/portfolio/refresh")
async def shared_portfolio_refresh():
    """强制刷新持仓缓存"""
    await _refresh_portfolio(force=True)
    return {"status": "ok", "message": "持仓已刷新"}


# ─── 个股备注 ─────────────────────────────────────────────

def get_stock_notes():
    """从缓存文件读取个股备注"""
    return _read_json(STOCK_NOTES_PATH, {})


@router.get("/api/shared/stock-notes")
async def shared_stock_notes():
    """返回所有个股备注"""
    return get_stock_notes()


@router.post("/api/shared/stock-notes/{symbol}")
async def save_stock_note(symbol: str, request: Request):
    """保存单只股票的备注"""
    body = await request.json()
    notes = get_stock_notes()
    notes[symbol] = {
        "note": body.get("note", ""),
        "target_price": body.get("target_price"),
        "tags": body.get("tags", []),
        "updated_at": date.today().isoformat(),
    }
    _write_json(STOCK_NOTES_PATH, notes)
    return {"status": "ok", "symbol": symbol}


# ─── 重点关注 ─────────────────────────────────────────────

def get_focus_stocks():
    """从缓存文件读取重点关注，若不存在则从 focus_stocks.py 导出"""
    data = _read_json(FOCUS_PATH)
    if data is None:
        data = _export_focus_stocks()
    return data


def _export_focus_stocks():
    """从 focus_stocks.py 的 FOCUS_STOCKS 导出为 JSON"""
    try:
        from api.focus_stocks import FOCUS_STOCKS
        sectors = []
        for s in FOCUS_STOCKS:
            sectors.append({
                "sector": s.get("sector", ""),
                "icon": s.get("icon", ""),
                "color": s.get("color", ""),
                "stocks": [{"code": st["code"], "name": st["name"]} for st in s.get("stocks", [])],
            })
        data = {"sectors": sectors, "count": sum(len(s["stocks"]) for s in sectors)}
        _write_json(FOCUS_PATH, data)
        return data
    except Exception as e:
        logger.warning("导出重点关注失败: %s", e)
        return {"sectors": [], "count": 0}


@router.get("/api/shared/focus-stocks")
async def shared_focus_stocks():
    """返回统一重点关注数据"""
    return get_focus_stocks()


@router.post("/api/shared/focus-stocks/refresh")
async def shared_focus_stocks_refresh():
    """强制刷新重点关注缓存"""
    _export_focus_stocks()
    return {"status": "ok", "message": "重点关注已刷新"}
