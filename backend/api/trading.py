"""
模拟盘交易API（trading）
现作为东财模拟盘 146w 账户的展示/手动交易入口，通过 MX_APIKEY 代理到东方财富妙想接口
与东财自动化模拟盘（/api/mx-trading，MX_TRADING_APIKEY）完全独立
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from api.auth import verify_api_key
from pydantic import BaseModel
from config import MX_APIKEY

router = APIRouter()

async def _get_realtime_price(code: str) -> dict:
    """只从数据库读取最新行情，供报价展示和交易限价回退复用。"""
    import re
    from db.session import get_db_session
    from db.models import StockDailyKline, StockFlow, StockRealtimeTick, Watchlist
    from utils import should_use_intraday_snapshot

    match = re.search(r"\d{6}", str(code or ""))
    if not match:
        raise HTTPException(status_code=400, detail="无效的股票代码")
    bare = match.group(0)
    ts_codes = [f"{bare}.SH", f"{bare}.SZ", f"{bare}.BJ"]
    with get_db_session() as db:
        daily = db.query(StockDailyKline).filter(
            StockDailyKline.ts_code.in_(ts_codes),
            StockDailyKline.close.isnot(None),
        ).order_by(StockDailyKline.trade_date.desc()).limit(2).all()
        # 先由已落库日线确定市场，再按精确 ts_code 查询实时表。不能用
        # "三市场 IN + 全表时间倒序"：没有 tick 的代码会反向扫描千万级历史表。
        resolved_ts_code = daily[0].ts_code if daily else None
        tick = None
        if resolved_ts_code:
            tick = db.query(StockRealtimeTick).filter(
                StockRealtimeTick.ts_code == resolved_ts_code,
                StockRealtimeTick.price.isnot(None),
            ).order_by(StockRealtimeTick.snapshot_time.desc()).first()
        else:
            # 极少数“已有实时、尚无日线”的新标的仍可展示；逐市场精确查，
            # 结果在 Python 中按时间取最新，避免数据库按全表时间排序。
            for ts_code in ts_codes:
                candidate = db.query(StockRealtimeTick).filter(
                    StockRealtimeTick.ts_code == ts_code,
                    StockRealtimeTick.price.isnot(None),
                ).order_by(StockRealtimeTick.snapshot_time.desc()).first()
                if candidate and (tick is None or candidate.snapshot_time > tick.snapshot_time):
                    tick = candidate
            resolved_ts_code = tick.ts_code if tick else None
        name_row = db.query(StockFlow.name).filter(
            StockFlow.ts_code == resolved_ts_code if resolved_ts_code else StockFlow.ts_code.in_(ts_codes),
            StockFlow.name.isnot(None),
        ).first()
        watchlist_name = db.query(Watchlist.stock_name).filter(
            Watchlist.stock_code == bare,
            Watchlist.stock_name.isnot(None),
        ).scalar()

    if tick is None and not daily:
        raise HTTPException(status_code=404, detail=f"数据库暂无 {bare} 行情，请等待自动采集")

    latest_daily = daily[0] if daily else None
    previous_daily = daily[1] if len(daily) > 1 else None
    use_tick = tick is not None and should_use_intraday_snapshot(
        tick.trade_date,
        latest_daily.trade_date if latest_daily else None,
    )
    if use_tick:
        price = float(tick.price)
        if latest_daily and latest_daily.trade_date < tick.trade_date:
            previous_close = float(latest_daily.close) if latest_daily.close is not None else None
        elif previous_daily and previous_daily.close is not None:
            previous_close = float(previous_daily.close)
        else:
            previous_close = None
        # Tick 表没有完整 OHLC，不能混入上一日日线字段伪装成实时值。
        open_price = high = low = None
        volume = int(tick.volume) if tick.volume is not None else None
        amount = float(tick.amount) if tick.amount is not None else None
        data_as_of = tick.snapshot_time.isoformat() if tick.snapshot_time else None
        upstream_source = 'stock_realtime_tick'
    else:
        price = float(latest_daily.close)
        previous_close = float(previous_daily.close) if previous_daily and previous_daily.close is not None else None
        open_price = float(latest_daily.open) if latest_daily.open is not None else None
        high = float(latest_daily.high) if latest_daily.high is not None else None
        low = float(latest_daily.low) if latest_daily.low is not None else None
        volume = int(latest_daily.volume) if latest_daily.volume is not None else None
        amount = float(latest_daily.amount) if latest_daily.amount is not None else None
        data_as_of = latest_daily.trade_date.isoformat()
        upstream_source = 'daily_kline'
    change = price - previous_close if previous_close is not None else None
    return {
        'name': (name_row[0] if name_row else None) or watchlist_name or bare,
        'price': price,
        'yesterday_close': previous_close,
        'open': open_price,
        'high': high,
        'low': low,
        'volume': volume,
        'amount': amount,
        'change': change,
        'change_pct': change / previous_close * 100 if previous_close else None,
        'source': 'database',
        'upstream_source': upstream_source,
        'data_as_of': data_as_of,
    }


# ========== 数据模型 ==========

class TradeRequest(BaseModel):
    type: str  # buy | sell
    stockCode: str
    price: Optional[float] = None
    quantity: int
    useMarketPrice: bool = True


class CancelRequest(BaseModel):
    type: str = "order"
    orderId: Optional[str] = None
    stockCode: Optional[str] = None


# ========== 账户/持仓快照：采集任务写库，查询接口只读数据库 ==========

def _num(value, default=0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return float(default)


def _order_time(value) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    if text.isdigit() and len(text) <= 6:
        try:
            return datetime.combine(datetime.now().date(), datetime.strptime(text.zfill(6), "%H%M%S").time())
        except ValueError:
            pass
    return datetime.now()


def read_balance_from_db() -> dict:
    from db.session import get_db_session
    from db.models import SimAccount

    with get_db_session() as db:
        row = db.get(SimAccount, 1)
        if row is None:
            return {
                "accName": "", "accID": "", "initMoney": 0, "totalAssets": 0,
                "availBalance": 0, "frozenMoney": 0, "totalPosValue": 0,
                "totalPosPct": 0, "nav": 0, "oprDays": 0,
                "source": "database", "status": "MISSING", "data_as_of": None,
            }
        return {
            "accName": row.acc_name or "",
            "accID": "",
            "initMoney": _num(row.init_money),
            "totalAssets": _num(row.total_assets),
            "availBalance": _num(row.avail_balance),
            "frozenMoney": _num(row.frozen_money),
            "totalPosValue": _num(row.total_pos_value),
            "totalPosPct": _num(row.total_pos_pct),
            "nav": _num(row.nav),
            "oprDays": int(row.opr_days or 0),
            "source": "database",
            "upstream_source": row.source or "miaoxiang",
            "status": "READY",
            "data_as_of": row.updated_at.isoformat() if row.updated_at else None,
        }


def read_positions_from_db() -> dict:
    from db.session import get_db_session
    from db.models import SimAccount, SimPosition, StockFlow

    with get_db_session() as db:
        rows = db.query(SimPosition).order_by(SimPosition.sec_code).all()
        account = db.get(SimAccount, 1)
        codes = [str(row.sec_code or "").zfill(6) for row in rows]
        sector_map = {}
        if codes:
            ts_codes = [f"{code}.{suffix}" for code in codes for suffix in ("SH", "SZ", "BJ")]
            for ts_code, sector in db.query(StockFlow.ts_code, StockFlow.sector).filter(
                StockFlow.ts_code.in_(ts_codes),
            ).all():
                sector_map[str(ts_code).split(".")[0]] = sector or ""

        positions = [{
            "secCode": str(row.sec_code or "").zfill(6),
            "secName": row.sec_name or "",
            "secMkt": int(row.sec_mkt or 0),
            "count": int(row.count or 0),
            "availCount": int(row.avail_count or 0),
            "price": _num(row.price),
            "costPrice": _num(row.cost_price),
            "value": _num(row.value),
            "dayProfit": _num(row.day_profit),
            "dayProfitPct": _num(row.day_profit_pct),
            "profit": _num(row.profit),
            "profitPct": _num(row.profit_pct),
            "posPct": _num(row.pos_pct),
            "sector": sector_map.get(str(row.sec_code or "").zfill(6), ""),
            "source": "database",
            "data_as_of": row.updated_at.isoformat() if row.updated_at else None,
        } for row in rows]

    return {
        "totalAssets": _num(account.total_assets) if account else 0,
        "availBalance": _num(account.avail_balance) if account else 0,
        "totalPosValue": _num(account.total_pos_value) if account else sum(p["value"] for p in positions),
        "posCount": len(positions),
        "totalProfit": sum(p["profit"] for p in positions),
        "positions": positions,
        "source": "database",
        "upstream_source": (account.source or "miaoxiang") if account else "miaoxiang",
        "status": "READY" if account else "MISSING",
        "data_as_of": account.updated_at.isoformat() if account and account.updated_at else None,
    }


def read_orders_from_db(drt: int = 0, status: int = 0) -> dict:
    from db.session import get_db_session
    from db.models import SimAccount, SimOrder

    with get_db_session() as db:
        account = db.get(SimAccount, 1)
        query = db.query(SimOrder)
        if drt:
            query = query.filter(SimOrder.drt == drt)
        if status:
            query = query.filter(SimOrder.status == status)
        rows = query.order_by(SimOrder.time.desc(), SimOrder.id.desc()).limit(500).all()
        orders = [{
            "id": row.external_order_id or str(row.id),
            "secCode": str(row.sec_code or "").zfill(6),
            "secName": row.sec_name or "",
            "secMkt": int(row.sec_mkt or 0),
            "drt": int(row.drt or 0),
            "price": _num(row.price),
            "count": int(row.count or 0),
            "tradeCount": int(row.trade_count or 0),
            "tradePrice": _num(row.trade_price) if row.trade_price is not None else None,
            "status": int(row.status or 0),
            "time": row.time.isoformat() if row.time else None,
            "source": "database",
        } for row in rows]
    return {
        "totalNum": len(orders), "orders": orders,
        "source": "database",
        "upstream_source": (account.source or "miaoxiang") if account else "miaoxiang",
        "status": "READY" if account else "MISSING",
        "data_as_of": account.updated_at.isoformat() if account and account.updated_at else None,
    }


def persist_trading_snapshot(balance: dict, positions_data: dict, orders_data: dict | None = None) -> dict:
    """原子替换妙想当前账户快照；仅供采集任务和交易写操作调用。"""
    from db.session import get_db_session
    from db.models import SimAccount, SimOrder, SimPosition

    positions = positions_data.get("positions") or []
    now = datetime.now()
    with get_db_session() as db:
        account = db.get(SimAccount, 1) or SimAccount(id=1)
        account.acc_name = balance.get("accName") or account.acc_name or "妙想模拟盘"
        account.init_money = _num(balance.get("initMoney"), account.init_money or 0)
        account.total_assets = _num(balance.get("totalAssets"), positions_data.get("totalAssets", 0))
        account.avail_balance = _num(balance.get("availBalance"), positions_data.get("availBalance", 0))
        account.frozen_money = _num(balance.get("frozenMoney"))
        account.total_pos_value = _num(balance.get("totalPosValue"), positions_data.get("totalPosValue", 0))
        account.total_pos_pct = _num(balance.get("totalPosPct"))
        account.nav = _num(balance.get("nav"), 1)
        account.opr_days = int(balance.get("oprDays") or 0)
        account.source = "miaoxiang"
        account.updated_at = now
        db.add(account)

        db.query(SimPosition).delete(synchronize_session=False)
        for item in positions:
            if int(item.get("count") or 0) <= 0:
                continue
            db.add(SimPosition(
                sec_code=str(item.get("secCode") or "").zfill(6),
                sec_name=item.get("secName") or "",
                sec_mkt=int(item.get("secMkt") or 0),
                count=int(item.get("count") or 0),
                avail_count=int(item.get("availCount") or 0),
                cost_price=_num(item.get("costPrice")),
                price=_num(item.get("price")),
                value=_num(item.get("value")),
                day_profit=_num(item.get("dayProfit")),
                day_profit_pct=_num(item.get("dayProfitPct")),
                profit=_num(item.get("profit")),
                profit_pct=_num(item.get("profitPct")),
                pos_pct=_num(item.get("posPct")),
                source="miaoxiang",
                updated_at=now,
            ))

        if orders_data is not None:
            db.query(SimOrder).delete(synchronize_session=False)
            for item in orders_data.get("orders") or []:
                db.add(SimOrder(
                    external_order_id=str(item.get("id") or ""),
                    sec_code=str(item.get("secCode") or "").zfill(6),
                    sec_name=item.get("secName") or "",
                    sec_mkt=int(item.get("secMkt") or 0),
                    drt=int(item.get("drt") or 0),
                    price=_num(item.get("price")),
                    count=int(item.get("count") or 0),
                    trade_count=int(item.get("tradeCount") or 0),
                    trade_price=_num(item.get("tradePrice")) if item.get("tradePrice") is not None else None,
                    status=int(item.get("status") or 0),
                    source="miaoxiang",
                    time=_order_time(item.get("time")),
                ))
        db.commit()
    return {"positions": len(positions), "orders": len((orders_data or {}).get("orders") or []), "data_as_of": now.isoformat()}


async def collect_trading_snapshot(force: bool = False) -> dict:
    """妙想自动采集入口：远端读取后先落库，页面不直接调用。"""
    from api.mx_trading import fetch_balance, fetch_orders, fetch_positions

    positions = await fetch_positions(api_key=MX_APIKEY, force=force)
    try:
        balance = await fetch_balance(api_key=MX_APIKEY, force=force)
    except Exception as exc:
        logging.getLogger("trading").warning("妙想资金采集失败，使用持仓接口账户字段: %s", exc)
        balance = positions
    try:
        orders = await fetch_orders(api_key=MX_APIKEY)
    except Exception as exc:
        logging.getLogger("trading").warning("妙想委托采集失败，本次保留原委托快照: %s", exc)
        orders = None
    persisted = persist_trading_snapshot(balance, positions, orders)
    return {"balance": balance, "positions": positions, "orders": orders, "persisted": persisted}


async def get_balance(force: bool = False) -> dict:
    """只读取数据库中的妙想账户快照；force 参数仅为旧接口兼容。"""
    return await asyncio.to_thread(read_balance_from_db)


async def get_positions(force: bool = False) -> dict:
    """只读取数据库中的妙想持仓快照；force 参数仅为旧接口兼容。"""
    return await asyncio.to_thread(read_positions_from_db)


@router.get("/api/trading/balance")
async def get_balance_endpoint(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """读取数据库中的模拟盘账户资金。"""
    return await get_balance(force=bool(force))


@router.get("/api/trading/positions")
async def get_positions_endpoint(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """读取数据库中的模拟盘持仓明细。"""
    return await get_positions(force=bool(force))


from datetime import date as _date

@router.get("/api/trading/portfolio-snapshot")
async def portfolio_snapshot_endpoint():
    """从数据库返回 DSA-compatible 持仓快照。"""
    pos_data = await get_positions(force=False)
    pos_list = pos_data.get("positions", [])
    
    items = []
    for p in pos_list:
        items.append({
            "symbol": p.get("secCode", ""),
            "market": "cn", "currency": "CNY",
            "quantity": p.get("count", 0) or 0,
            "avg_cost": float(p.get("costPrice", 0) or 0),
            "total_cost": float((p.get("costPrice", 0) or 0) * (p.get("count", 0) or 0)),
            "last_price": float(p.get("price", 0) or 0),
            "market_value_base": float(p.get("value", 0) or 0),
            "unrealized_pnl_base": float(p.get("profit", 0) or 0),
            "price_source": "database", "price_available": True,
        })
    total_mv = sum(it["market_value_base"] for it in items)
    total_upnl = sum(it["unrealized_pnl_base"] for it in items)
    # 资产口径必须来自同一个妙想账户快照，不能把“持仓市值”冒充“总资产”。
    # positions 接口在部分情况下不返回完整账户字段，因此保留明确的质量标记。
    api_cash = pos_data.get("availBalance")
    api_market_value = pos_data.get("totalPosValue")
    api_equity = pos_data.get("totalAssets")
    total_cash = float(api_cash or 0)
    if api_market_value not in (None, ""):
        total_mv = float(api_market_value or 0)
    total_equity = float(api_equity or 0) if api_equity not in (None, "") else total_cash + total_mv
    limitations = []
    if api_cash in (None, ""):
        limitations.append("现金余额未从妙想账户返回")
    if api_market_value in (None, ""):
        limitations.append("持仓市值使用持仓明细求和")
    if api_equity in (None, ""):
        limitations.append("总资产使用现金加持仓市值估算")
    limitations.extend(["已实现盈亏未由当前接口提供", "手续费与印花税未由当前接口提供"])
    data_quality = "ok" if not any(
        item in limitations for item in (
            "现金余额未从妙想账户返回",
            "持仓市值使用持仓明细求和",
            "总资产使用现金加持仓市值估算",
        )
    ) else "partial"
    snapshot_as_of = pos_data.get("data_as_of") or _date.today().isoformat()
    return {
        "as_of": snapshot_as_of,
        "source": "database",
        "cost_method": "avg", "currency": "CNY",
        "account_count": 1 if items else 0,
        "total_cash": total_cash, "total_market_value": total_mv, "total_equity": total_equity,
        "realized_pnl": 0.0, "unrealized_pnl": total_upnl,
        "fee_total": 0.0, "tax_total": 0.0,
        "fx_stale": False, "data_quality": data_quality, "limitations": limitations,
        "accounts": [{
            "account_id": 1, "account_name": "模拟交易", "market": "cn",
            "base_currency": "CNY", "as_of": snapshot_as_of,
            "cost_method": "avg", "total_cash": total_cash,
            "total_market_value": total_mv, "total_equity": total_equity,
            "realized_pnl": 0.0, "unrealized_pnl": total_upnl,
            "fee_total": 0.0, "tax_total": 0.0,
            "fx_stale": False, "data_quality": data_quality, "limitations": limitations, "positions": items,
        }],
    }


@router.get("/api/trading/orders")
async def get_orders(
    drt: int = Query(0, description="0=全部, 1=买入, 2=卖出"),
    status: int = Query(0, description="0=全部, 4=已成"),
):
    """读取数据库中的妙想委托快照。"""
    return await asyncio.to_thread(read_orders_from_db, drt, status)


@router.post("/api/trading/trade", dependencies=[Depends(verify_api_key)])
async def trade(req: TradeRequest):
    """模拟盘买入/卖出（146w 东财账户）"""
    from api.mx_trading import place_trade
    result = await place_trade(
        api_key=MX_APIKEY,
        type=req.type,
        stock_code=req.stockCode,
        quantity=req.quantity,
        use_market_price=req.useMarketPrice,
        price=req.price,
    )
    try:
        await collect_trading_snapshot(force=True)
    except Exception as exc:
        logging.getLogger("trading").warning("交易成功后账户快照刷新失败: %s", exc)
    return result


@router.post("/api/trading/cancel", dependencies=[Depends(verify_api_key)])
async def cancel(req: CancelRequest):
    """模拟盘撤单（146w 东财账户）"""
    from api.mx_trading import place_cancel
    result = await place_cancel(
        api_key=MX_APIKEY,
        type=req.type,
        order_id=req.orderId,
        stock_code=req.stockCode,
    )
    try:
        await collect_trading_snapshot(force=True)
    except Exception as exc:
        logging.getLogger("trading").warning("撤单成功后账户快照刷新失败: %s", exc)
    return result


@router.get("/api/trading/quote")
async def get_realtime_quote(code: str = Query(..., description="6位股票代码")):
    """从数据库读取行情（完整字段：price/yesterdayClose/open/high/low/change/changePct）。"""
    quote = await _get_realtime_price(code)
    return {
        'code': code,
        'name': quote['name'],
        'price': quote['price'],
        'yesterdayClose': quote['yesterday_close'],
        'open': quote['open'],
        'high': quote['high'],
        'low': quote['low'],
        'change': quote['change'],
        'changePct': quote['change_pct'],
        'volume': quote['volume'],
        'amount': quote['amount'],
        'source': 'database',
        'upstreamSource': quote.get('upstream_source'),
        'dataAsOf': quote.get('data_as_of'),
    }


@router.get("/api/trading/search")
def search_stock(q: str = Query(..., min_length=1, description="股票代码或名称")):
    """搜索股票（代码或名称模糊匹配）"""
    from db.session import get_db_session
    from db.models import StockFlow
    with get_db_session() as db:
        query = db.query(
            StockFlow.ts_code,
            StockFlow.name,
            StockFlow.sector,
        ).filter(
            StockFlow.ts_code.ilike(f'%{q}%') | StockFlow.name.ilike(f'%{q}%')
        ).distinct().limit(15)

        results = []
        seen = set()
        for row in query:
            if row.ts_code in seen:
                continue
            seen.add(row.ts_code)
            code6 = row.ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
            results.append({
                'ts_code': row.ts_code,
                'code': code6,
                'name': row.name,
                'sector': row.sector,
            })
        return {'results': results}
