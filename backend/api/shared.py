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
    """从数据库返回统一自选股；JSON 不参与读取。"""
    from db.session import get_db_session
    from db.models import Watchlist
    with get_db_session() as db:
        rows = db.query(Watchlist).order_by(
            Watchlist.sort_order, Watchlist.created_at
        ).all()
        return {
            "stocks": [{
                "code": row.stock_code,
                "name": row.stock_name or "",
                "note": row.note or "",
                "group": row.group_name or "默认",
                "sort_order": int(row.sort_order or 0),
                "quality_status": row.quality_status or "普通",
            } for row in rows],
            "source": "database",
            "status": "READY",
        }


def save_watchlist(data):
    """兼容旧调用：数据库已写入后导出 JSON，不把 JSON 反写数据库。"""
    from api.watchlist.watchlist_local import export_db_to_local
    return export_db_to_local()


@router.get("/api/shared/watchlist")
def shared_watchlist():
    """返回统一自选股列表"""
    return get_watchlist()


@router.get("/api/shared/watchlist/codes")
def shared_watchlist_codes():
    """返回自选股代码列表（简洁模式，供研究与交易页面使用）"""
    wl = get_watchlist()
    return {"codes": [s["code"] for s in wl.get("stocks", [])]}


class AddCodesRequest(BaseModel):
    codes: list[str]
    note: str = "研究工作区同步"
    group: str = "研究工作区同步"


@router.post("/api/shared/watchlist/add")
def shared_watchlist_add(req: AddCodesRequest):
    """批量写数据库，再导出兼容 JSON 并触发云同步。"""
    from db.session import get_db_session
    from db.models import Watchlist
    from api.watchlist._shared import reset_watchlist_cache

    codes = [c.strip() for c in req.codes if c and c.strip()]
    if not codes:
        return {"status": "ok", "added": 0}

    with get_db_session() as db:
        existing_map = {item.stock_code: item for item in db.query(Watchlist).all()}
        for code in codes:
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

    save_watchlist(None)

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
def shared_watchlist_remove(req: RemoveCodeRequest):
    """从数据库删除自选股，再导出兼容 JSON。"""
    from db.session import get_db_session
    from db.models import Watchlist
    from api.watchlist._shared import reset_watchlist_cache

    code = req.code

    stock_name = code
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if item:
            stock_name = item.stock_name or code
            db.delete(item)
            db.commit()

    save_watchlist(None)

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
    """只从数据库读取当前妙想账户快照。"""
    try:
        from api.trading import read_balance_from_db, read_positions_from_db
        balance = read_balance_from_db()
        positions_data = read_positions_from_db()
    except Exception as exc:
        logger.warning("数据库持仓快照读取失败: %s", exc)
        return {
            "positions": [], "count": 0, "total_market_value": 0,
            "total_unrealized_pnl": 0, "total_assets": 0, "available_cash": 0,
            "source": "database", "status": "MISSING", "data_as_of": None,
            "data_quality": "数据库持仓快照读取失败",
        }

    items = [{
        "symbol": p.get("secCode", ""),
        "name": p.get("secName", ""),
        "market": "cn",
        "quantity": float(p.get("count", 0) or 0),
        "avg_cost": float(p.get("costPrice", 0) or 0),
        "last_price": float(p.get("price", 0) or 0),
        "market_value": float(p.get("value", 0) or 0),
        "unrealized_pnl": float(p.get("profit", 0) or 0),
        "profit_ratio": round(float(p.get("profitPct", 0) or 0), 2),
        "day_pnl": float(p.get("dayProfit", 0) or 0),
        "day_pnl_pct": round(float(p.get("dayProfitPct", 0) or 0), 2),
        "pos_pct": round(float(p.get("posPct", 0) or 0), 2),
        "sector": p.get("sector", ""),
        "source": "database",
    } for p in positions_data.get("positions", []) if float(p.get("count", 0) or 0) > 0]
    total_mv = sum(item["market_value"] for item in items)
    total_upnl = sum(item["unrealized_pnl"] for item in items)
    total_cost = sum(item["avg_cost"] * item["quantity"] for item in items)
    total_day_pnl = sum(item["day_pnl"] for item in items)
    status = positions_data.get("status") or balance.get("status") or "MISSING"
    return {
        "as_of": positions_data.get("data_as_of") or balance.get("data_as_of"),
        "data_as_of": positions_data.get("data_as_of") or balance.get("data_as_of"),
        "source": "database",
        "upstream_source": positions_data.get("upstream_source", "miaoxiang"),
        "status": status,
        "total_market_value": round(float(positions_data.get("totalPosValue") or total_mv), 2),
        "total_unrealized_pnl": round(total_upnl, 2),
        "total_assets": round(float(balance.get("totalAssets") or positions_data.get("totalAssets") or 0), 2),
        "available_cash": round(float(balance.get("availBalance") or positions_data.get("availBalance") or 0), 2),
        "total_cost": round(total_cost, 2),
        "total_day_pnl": round(total_day_pnl, 2),
        "positions": items,
        "count": len(items),
        "data_sources": {"database": len(items), "miaoxiang": len(items)},
        "data_quality": None if status == "READY" else "数据库暂无妙想持仓快照，请等待自动同步",
    }


# ─── 持仓自动同步到自选 ─────────────────────────────────

def _sync_portfolio_to_watchlist(items: list[dict]) -> dict:
    """持仓 → 自选 自动同步：只加不减、去重；仅在真正新增时写盘。
    返回 {"added": n, "skipped": m}
    """
    codes = sorted({str(it.get("symbol", "")).strip() for it in items if it.get("symbol")})
    if not codes:
        return {"added": 0, "skipped": 0}

    name_map = {str(it.get("symbol", "")).strip(): (it.get("name") or "") for it in items}
    missing = []
    try:
        from db.session import get_db_session
        from db.models import Watchlist
        from api.watchlist._shared import reset_watchlist_cache
        with get_db_session() as db:
            existing_map = {item.stock_code: item for item in db.query(Watchlist).all()}
            missing = [code for code in codes if code not in existing_map]
            for code in missing:
                db.add(Watchlist(
                    stock_code=code,
                    stock_name=name_map.get(code, ""),
                    note="持仓自动同步",
                    group_name="持仓同步",
                ))
            db.commit()
        save_watchlist(None)
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
    """自动采集妙想账户并先落库；JSON 仅保留为兼容导出，不再供接口读取。"""
    from api.trading import collect_trading_snapshot

    try:
        await collect_trading_snapshot(force=force)
    except Exception as exc:
        logger.warning("妙想账户自动采集失败，保留数据库上次成功快照: %s", exc)
        previous = get_portfolio()
        previous["data_quality"] = "妙想源暂时不可用，保留数据库上次成功快照"
        return previous

    cache = get_portfolio()
    items = cache.get("positions", [])

    # 持仓自动同步到自选（只加不减、去重；仅在真正新增时写盘）
    try:
        sync_info = _sync_portfolio_to_watchlist(items)
    except Exception as e:
        logger.warning("持仓自动同步到自选失败: %s", e)
        sync_info = {"added": 0, "skipped": 0}

    cache["watchlist_sync"] = sync_info
    _write_json(PORTFOLIO_PATH, cache)
    return cache


@router.get("/api/shared/portfolio")
async def shared_portfolio(force: int = Query(0, description="1=强制刷新缓存")):
    """只返回数据库中的统一持仓；force 参数保留兼容但不触发外采。"""
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
def shared_stock_notes():
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
def shared_focus_stocks():
    """返回统一重点关注数据"""
    return get_focus_stocks()


@router.post("/api/shared/focus-stocks/refresh")
def shared_focus_stocks_refresh():
    """强制刷新重点关注缓存"""
    _export_focus_stocks()
    return {"status": "ok", "message": "重点关注已刷新"}
