"""
东财模拟盘交易代理API（mx-trading）
代理东方财富妙想模拟组合管理接口，API Key保存在后端
与原模拟盘（/api/trading）完全独立
"""
import time
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from api.auth import verify_api_key
from pydantic import BaseModel
from config import MX_TRADING_APIKEY, MX_API_URL
from utils.cache import BoundedDict
from sqlalchemy import select
from db.connection import SessionLocal
from db.models import SimPositionCost

logger = logging.getLogger(__name__)

router = APIRouter()

_MX_HTTP_TIMEOUT = 10
_MX_HTTP_LIMITS = httpx.Limits(max_connections=5, max_keepalive_connections=2)

# 内存缓存（仅缓存查询类接口）
_cache = BoundedDict(maxsize=50)
_CACHE_TTL = 300  # 5分钟，减少妙想API调用次数


def _cache_ns(api_key: str = None) -> str:
    """根据 api_key 生成缓存命名空间，避免不同 key 的数据互相覆盖"""
    key = api_key or MX_TRADING_APIKEY
    return 'default' if not api_key else f"ns{hash(key) & 0xFFFFFFFF}"


def _clear_cache(api_key: str = None):
    """交易操作后清除缓存"""
    ns = _cache_ns(api_key)
    _cache.pop(ns, None)


# ---------- PG 成本价持久化 ----------

def _cost_cache_get(api_key: str, sec_code: str) -> Optional[float]:
    """从 PG 读取缓存成本价"""
    try:
        with SessionLocal() as db:
            row = db.get(SimPositionCost, (api_key[:20], sec_code[:20]))
            if row and row.cost_price > 0:
                return float(row.cost_price)
    except Exception:
        logger.debug("mx_trading: PG op failed", exc_info=False)
    return None


def _cost_cache_set(api_key: str, sec_code: str, cost_price: float, quantity: int):
    """写入 PG 成本价缓存"""
    try:
        with SessionLocal() as db:
            obj = SimPositionCost(
                api_key=api_key[:20], sec_code=sec_code[:20],
                cost_price=cost_price, quantity=quantity,
            )
            db.merge(obj)
            db.commit()
    except Exception:
        logger.debug("mx_trading: PG op failed", exc_info=False)


async def _proxy(endpoint: str, payload: dict, cache_key: str = None, api_key: str = None):
    """统一代理东方财富API（可指定 api_key；默认用 MX_TRADING_APIKEY）"""
    key = api_key or MX_TRADING_APIKEY
    if not key:
        raise HTTPException(status_code=500, detail="MX_TRADING_APIKEY未配置")

    ns = _cache_ns(api_key)
    ns_cache = _cache.setdefault(ns, {})

    # 缓存检查
    if cache_key:
        cached = ns_cache.get(cache_key)
        if cached and time.time() - cached[1] < _CACHE_TTL:
            return cached[0]

    try:
        # 调度器会在不同线程中用 asyncio.run 创建独立事件循环；
        # AsyncClient 不能跨事件循环复用，因此每次外部采集/交易调用独立管理连接。
        async with httpx.AsyncClient(timeout=_MX_HTTP_TIMEOUT, limits=_MX_HTTP_LIMITS) as client:
            resp = await client.post(
                f"{MX_API_URL}{endpoint}",
                json=payload,
                headers={
                    "apikey": key,
                    "Content-Type": "application/json; charset=UTF-8",
                },
            )
            data = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="东方财富API请求超时")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"东方财富API请求失败: {str(e)}")

    code = str(data.get('code', ''))
    if code not in ('0', '200'):
        msg = data.get('message', '未知错误')
        logger.warning('[mx_trading] _proxy error: endpoint=%s code=%s message=%s data=%s', endpoint, code, msg, data)
        # 特殊错误码处理
        if code == '113':
            raise HTTPException(status_code=429, detail="妙想账户已休眠，调用次数降至10次/天。请前往东方财富APP搜索「妙想skill」激活账户后重试。")
        if code in ('114', '115', '116'):
            raise HTTPException(status_code=401, detail="妙想 API 密钥无效，请检查 MX_TRADING_APIKEY 配置")
        if code == '404':
            raise HTTPException(status_code=404, detail="未绑定模拟组合账户，请前往妙想Skills页面创建并绑定")
        raise HTTPException(status_code=400, detail=msg)

    result = data.get('data', {})

    # 写入缓存
    if cache_key:
        ns_cache[cache_key] = (result, time.time())

    return result


def _normalize_price(raw_price: int, price_dec: int) -> float:
    """将放大后的整数价格还原为浮点数"""
    return raw_price / (10 ** price_dec)


async def _recalc_cost_from_orders(sec_code: str, count: int, price: float, api_key: str = None) -> tuple:
    """从委托记录重算真实成本价（当妙想API返回负成本时使用）"""
    try:
        raw = await _proxy('/api/claw/mockTrading/orders', {
            'moneyUnit': 1,
            'beginDate': '',
            'endDate': '',
            'beginTime': 0,
            'endTime': 0,
            'count': 200,
            'offset': 0,
        }, cache_key='mx_orders', api_key=api_key)
        orders = raw.get('orders') or raw.get('orderList') or []
        buys = []
        sold_count = 0
        for o in orders:
            if o.get('secCode') != sec_code:
                continue
            if o.get('status') != 4:
                continue
            price_dec = o.get('priceDec', 2)
            raw_tp = o.get('tradePrice') or o.get('price') or 0
            tp = raw_tp / (10 ** price_dec)
            tc = o.get('tradeCount', 0)
            if o.get('drt') == 1:
                buys.append((tp, tc))
            elif o.get('drt') == 2:
                sold_count += tc
        remaining = count
        if remaining <= 0:
            return (price, 0, 0)
        total_cost = 0
        allocated_sold = sold_count
        for tp, tc in buys:
            if allocated_sold >= tc:
                allocated_sold -= tc
                continue
            avail = tc - allocated_sold
            allocated_sold = 0
            take = min(avail, remaining)
            total_cost += tp * take
            remaining -= take
            if remaining <= 0:
                break
        if total_cost <= 0:
            return (price, 0, 0)
        real_cost = total_cost / count
        profit = (price - real_cost) * count
        profit_pct = (price - real_cost) / real_cost * 100 if real_cost > 0 else 0
        return (real_cost, profit, profit_pct)
    except Exception as e:
        logger.debug(f'[mx_trading] 成本重算失败: {e}')
        return (price, 0, 0)


# ========== 数据模型 ==========

class TradeRequest(BaseModel):
    type: str  # buy | sell
    stockCode: str
    price: Optional[float] = None
    quantity: int
    useMarketPrice: bool = False


class CancelRequest(BaseModel):
    type: str = "order"  # order | all
    orderId: Optional[str] = None
    stockCode: Optional[str] = None


# ========== 可复用的业务函数（供 trading.py / analysis.py 调用） ==========

async def fetch_balance(api_key: str = None, force: bool = False) -> dict:
    """查询东财模拟盘账户资金（可指定 api_key）"""
    cache_key = 'mx_balance'
    ns = _cache_ns(api_key)
    if force:
        _cache.setdefault(ns, {}).pop(cache_key, None)
    raw = await _proxy('/api/claw/mockTrading/balance', {'moneyUnit': 1}, cache_key=cache_key, api_key=api_key)
    return {
        'accName': raw.get('accName', ''),
        'accID': raw.get('accID', ''),
        'initMoney': raw.get('initMoney', 0),
        'totalAssets': raw.get('totalAssets', 0),
        'availBalance': raw.get('availBalance', 0),
        'frozenMoney': raw.get('frozenMoney', 0),
        'totalPosValue': raw.get('totalPosValue', 0),
        'totalPosPct': raw.get('totalPosPct', 0),
        'nav': raw.get('nav', 0),
        'oprDays': raw.get('oprDays', 0),
    }


async def fetch_positions(api_key: str = None, force: bool = False) -> dict:
    """查询东财模拟盘持仓明细（可指定 api_key）"""
    cache_key = 'mx_positions'
    ns = _cache_ns(api_key)
    if force:
        _cache.setdefault(ns, {}).pop(cache_key, None)
    raw = await _proxy('/api/claw/mockTrading/positions', {'moneyUnit': 1}, cache_key=cache_key, api_key=api_key)

    pos_list = raw.get('posList') or []
    positions = []
    for pos in pos_list:
        price_dec = pos.get('priceDec', 2)
        cost_dec = pos.get('costPriceDec', 2)
        price = _normalize_price(pos.get('price', 0), price_dec)
        cost_price = _normalize_price(pos.get('costPrice', 0), cost_dec)
        count = pos.get('count', 0)
        profit = pos.get('profit', 0)
        profit_pct = pos.get('profitPct', 0)

        if cost_price <= 0 and count > 0:
            real_cost, real_profit, real_pct = await _recalc_cost_from_orders(
                pos.get('secCode', ''), count, price, api_key=api_key
            )
            cost_price = real_cost
            profit = real_profit
            profit_pct = real_pct

        positions.append({
            'secCode': pos.get('secCode', ''),
            'secName': pos.get('secName', ''),
            'secMkt': pos.get('secMkt', 0),
            'count': count,
            'availCount': pos.get('availCount', 0),
            'price': price,
            'costPrice': cost_price,
            'value': pos.get('value', 0),
            'dayProfit': pos.get('dayProfit', 0),
            'dayProfitPct': pos.get('dayProfitPct', 0),
            'profit': profit,
            'profitPct': profit_pct,
            'posPct': pos.get('posPct', 0),
        })

    return {
        'totalAssets': raw.get('totalAssets', 0),
        'availBalance': raw.get('availBalance', 0),
        'totalPosValue': raw.get('totalPosValue', 0),
        'posCount': raw.get('posCount', 0),
        'totalProfit': raw.get('totalProfit', 0),
        'positions': positions,
    }


async def fetch_orders(api_key: str = None, drt: int = 0, status: int = 0) -> dict:
    """查询东财模拟盘委托记录（可指定 api_key）"""
    raw = await _proxy('/api/claw/mockTrading/orders', {
        'fltOrderDrt': drt,
        'fltOrderStatus': status,
    }, api_key=api_key)

    orders = raw.get('orders') or []
    normalized = []
    for o in orders:
        price_dec = o.get('priceDec', 2)
        normalized.append({
            'id': o.get('id', ''),
            'secCode': o.get('secCode', ''),
            'secName': o.get('secName', ''),
            'secMkt': o.get('secMkt', 0),
            'drt': o.get('drt', 0),
            'price': _normalize_price(o.get('price', 0), price_dec),
            'count': o.get('count', 0),
            'tradeCount': o.get('tradeCount', 0),
            'tradePrice': _normalize_price(o.get('tradePrice', 0), price_dec) if o.get('tradePrice') else None,
            'status': o.get('status', 0),
            'time': o.get('time', 0),
        })

    return {
        'totalNum': raw.get('totalNum', 0),
        'orders': normalized,
    }


async def place_trade(api_key: str = None, type: str = None, stock_code: str = None,
                      quantity: int = 0, use_market_price: bool = False,
                      price: Optional[float] = None) -> dict:
    """东财模拟盘买入/卖出（可指定 api_key）

    市价委托在非交易时间会因妙想无法获取实时买一价而失败，
    此时自动回退为限价委托（用数据库最新收盘价）重试一次。
    """
    if type not in ('buy', 'sell'):
        raise HTTPException(status_code=400, detail="type必须为buy或sell")
    if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
        raise HTTPException(status_code=400, detail="stockCode必须为6位数字")
    if quantity <= 0 or quantity % 100 != 0:
        raise HTTPException(status_code=400, detail="数量必须为正数且是100的整数倍")
    if not use_market_price and price is None:
        raise HTTPException(status_code=400, detail="限价委托必须提供price")
    if not use_market_price and float(price) <= 0:
        raise HTTPException(status_code=400, detail="限价委托价格必须大于0")

    payload = {
        'type': type,
        'stockCode': stock_code,
        'quantity': quantity,
        'useMarketPrice': use_market_price,
    }
    if not use_market_price and price is not None:
        # 妙想 API 期望浮点数价格（如 53.87），不是放大后的整数
        payload['price'] = round(float(price), 4)

    logger.info('[mx_trading] place_trade request: type=%s stock_code=%s quantity=%s use_market_price=%s price=%s',
                type, stock_code, quantity, use_market_price, price)
    try:
        result = await _proxy('/api/claw/mockTrading/trade', payload, api_key=api_key)
        logger.info('[mx_trading] place_trade response: %s', result)
        _clear_cache(api_key)
        return result
    except HTTPException as e:
        # 市价委托在非交易时间会失败（妙想无法获取实时买一价），自动回退为限价委托
        fallback_msg = '获取行情买一价失败'
        if use_market_price and e.status_code == 400 and fallback_msg in str(e.detail):
            logger.warning('[mx_trading] 市价委托失败(%s)，回退为限价委托重试', e.detail)
            # 用数据库最新收盘价作为限价
            from api.trading import _get_realtime_price
            rt = await _get_realtime_price(stock_code)
            fb_price = rt.get('price')
            if not fb_price or fb_price <= 0:
                raise HTTPException(status_code=400, detail=f"市价委托失败且无法获取现价回退：{e.detail}")
            fb_payload = {
                'type': type,
                'stockCode': stock_code,
                'quantity': quantity,
                'useMarketPrice': False,
                'price': round(float(fb_price), 4),
            }
            logger.info('[mx_trading] 限价回退 request: price=%s (现价%.4f)', fb_payload['price'], fb_price)
            try:
                result = await _proxy('/api/claw/mockTrading/trade', fb_payload, api_key=api_key)
                logger.info('[mx_trading] 限价回退 response: %s', result)
                _clear_cache(api_key)
                if isinstance(result, dict):
                    result['_fallback'] = f'市价失败已自动回退限价({fb_price:.2f})'
                return result
            except HTTPException as e2:
                # 限价回退也失败：返回合并错误信息，提示可能是妙想账户休眠
                logger.warning('[mx_trading] 限价回退也失败: %s', e2.detail)
                raise HTTPException(
                    status_code=e2.status_code,
                    detail=f"市价委托失败({e.detail})，限价回退也失败({e2.detail})。妙想账户可能已休眠，请前往东方财富APP搜索「妙想skill」激活后重试。"
                )
        raise


async def place_cancel(api_key: str = None, type: str = "order",
                       order_id: str = None, stock_code: str = None) -> dict:
    """东财模拟盘撤单/一键撤单（可指定 api_key）"""
    if type == 'order':
        if not order_id or not stock_code:
            raise HTTPException(status_code=400, detail="撤单需提供orderId和stockCode")
        payload = {'type': 'order', 'orderId': order_id, 'stockCode': stock_code}
    else:
        payload = {'type': 'all'}

    result = await _proxy('/api/claw/mockTrading/cancel', payload, api_key=api_key)
    _clear_cache(api_key)
    return result


# ========== API 端点（默认走 MX_TRADING_APIKEY） ==========

@router.get("/api/mx-trading/balance")
async def get_balance(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """读取数据库中的东财模拟盘账户资金。"""
    from api.trading import get_balance as get_database_balance
    return await get_database_balance()


@router.get("/api/mx-trading/positions")
async def get_positions(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """读取数据库中的东财模拟盘持仓明细。"""
    from api.trading import get_positions as get_database_positions
    return await get_database_positions()


@router.get("/api/mx-trading/orders")
async def get_orders(
    drt: int = Query(0, description="0=全部, 1=买入, 2=卖出"),
    status: int = Query(0, description="0=全部, 2=已报, 4=已成"),
):
    """读取数据库中的东财模拟盘委托记录。"""
    from api.trading import read_orders_from_db
    import asyncio
    return await asyncio.to_thread(read_orders_from_db, drt, status)


@router.post("/api/mx-trading/trade", dependencies=[Depends(verify_api_key)])
async def trade(req: TradeRequest):
    """东财模拟盘买入/卖出"""
    result = await place_trade(
        type=req.type,
        stock_code=req.stockCode,
        quantity=req.quantity,
        use_market_price=req.useMarketPrice,
        price=req.price,
    )
    try:
        from api.trading import collect_trading_snapshot
        await collect_trading_snapshot(force=True)
    except Exception as exc:
        logger.warning("交易成功后账户快照刷新失败: %s", exc)
    return result


@router.post("/api/mx-trading/cancel", dependencies=[Depends(verify_api_key)])
async def cancel(req: CancelRequest):
    """东财模拟盘撤单/一键撤单"""
    result = await place_cancel(
        type=req.type,
        order_id=req.orderId,
        stock_code=req.stockCode,
    )
    try:
        from api.trading import collect_trading_snapshot
        await collect_trading_snapshot(force=True)
    except Exception as exc:
        logger.warning("撤单成功后账户快照刷新失败: %s", exc)
    return result


@router.get("/api/mx-trading/quote")
async def get_realtime_quote(code: str = Query(..., description="6位股票代码")):
    """从数据库读取行情。"""
    from api.trading import _get_realtime_price
    quote = await _get_realtime_price(code)
    return {
        'code': code,
        'name': quote['name'],
        'price': quote['price'],
        'yesterdayClose': quote['yesterday_close'],
        'open': quote['open'],
        'high': quote['high'],
        'low': quote['low'],
        'volume': quote['volume'],
        'amount': quote['amount'],
        'change': round(quote['change'], 3),
        'changePct': round(quote['change_pct'], 2),
        'source': 'database',
        'dataAsOf': quote.get('data_as_of'),
    }


@router.get("/api/mx-trading/search")
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
