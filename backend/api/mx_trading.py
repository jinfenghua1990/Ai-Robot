"""
东财模拟盘交易代理API（mx-trading）
代理东方财富妙想模拟组合管理接口，API Key保存在后端
与原模拟盘（/api/trading）完全独立
"""
import time
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from config import MX_TRADING_APIKEY, MX_API_URL
from utils import stock_code_to_sina as _stock_code_to_sina
from api.watchlist._shared import _get_http_client
from utils.http_constants import SINA_HEADERS_SHORT

logger = logging.getLogger(__name__)

router = APIRouter()

# 内存缓存（仅缓存查询类接口）
_cache = {}
_CACHE_TTL = 300  # 5分钟，减少妙想API调用次数


def _cache_ns(api_key: str = None) -> str:
    """根据 api_key 生成缓存命名空间，避免不同 key 的数据互相覆盖"""
    key = api_key or MX_TRADING_APIKEY
    return 'default' if not api_key else f"ns{hash(key) & 0xFFFFFFFF}"


def _clear_cache(api_key: str = None):
    """交易操作后清除缓存"""
    ns = _cache_ns(api_key)
    _cache.pop(ns, None)


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
        client = _get_http_client()
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
        # 特殊错误码处理
        if code == '113':
            raise HTTPException(status_code=429, detail="今日调用次数已达上限")
        if code in ('114', '115', '116'):
            raise HTTPException(status_code=401, detail="API密钥无效，请检查MX_APIKEY配置")
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
    """东财模拟盘买入/卖出（可指定 api_key）"""
    if type not in ('buy', 'sell'):
        raise HTTPException(status_code=400, detail="type必须为buy或sell")
    if not stock_code or len(stock_code) != 6:
        raise HTTPException(status_code=400, detail="stockCode必须为6位数字")
    if quantity % 100 != 0:
        raise HTTPException(status_code=400, detail="数量必须为100的整数倍")
    if not use_market_price and price is None:
        raise HTTPException(status_code=400, detail="限价委托必须提供price")

    payload = {
        'type': type,
        'stockCode': stock_code,
        'quantity': quantity,
        'useMarketPrice': use_market_price,
    }
    if not use_market_price and price is not None:
        decimal_places = 2 if stock_code[0] in ('6', '9') else 3
        payload['price'] = int(round(price * (10 ** decimal_places)))

    result = await _proxy('/api/claw/mockTrading/trade', payload, api_key=api_key)
    _clear_cache(api_key)
    return result


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
    """查询东财模拟盘账户资金"""
    return await fetch_balance(force=force)


@router.get("/api/mx-trading/positions")
async def get_positions(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """查询东财模拟盘持仓明细"""
    return await fetch_positions(force=force)


@router.get("/api/mx-trading/orders")
async def get_orders(
    drt: int = Query(0, description="0=全部, 1=买入, 2=卖出"),
    status: int = Query(0, description="0=全部, 2=已报, 4=已成"),
):
    """查询东财模拟盘委托记录"""
    return await fetch_orders(drt=drt, status=status)


@router.post("/api/mx-trading/trade")
async def trade(req: TradeRequest):
    """东财模拟盘买入/卖出"""
    return await place_trade(
        type=req.type,
        stock_code=req.stockCode,
        quantity=req.quantity,
        use_market_price=req.useMarketPrice,
        price=req.price,
    )


@router.post("/api/mx-trading/cancel")
async def cancel(req: CancelRequest):
    """东财模拟盘撤单/一键撤单"""
    return await place_cancel(
        type=req.type,
        order_id=req.orderId,
        stock_code=req.stockCode,
    )


@router.get("/api/mx-trading/quote")
async def get_realtime_quote(code: str = Query(..., description="6位股票代码")):
    """获取新浪实时行情"""
    sina_code = _stock_code_to_sina(code)
    if not sina_code:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    cache_key = f'mx_quote_{code}'
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[1] < 3:
        return cached[0]

    url = f"https://hq.sinajs.cn/list={sina_code}"
    try:
        client = _get_http_client()
        resp = await client.get(url, headers=SINA_HEADERS_SHORT)
        resp.encoding = 'gbk'
        text = resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取行情失败: {str(e)}")

    try:
        parts = text.split('"')[1].split(',')
        if len(parts) < 10:
            raise HTTPException(status_code=500, detail="行情数据格式异常")

        name = parts[0]
        yesterday_close = float(parts[1])
        open_price = float(parts[2])
        current_price = float(parts[3])
        high = float(parts[4])
        low = float(parts[5])
        volume = int(float(parts[8]))
        amount = float(parts[9])

        change = current_price - yesterday_close
        change_pct = (change / yesterday_close * 100) if yesterday_close else 0

        result = {
            'code': code,
            'name': name,
            'price': current_price,
            'yesterdayClose': yesterday_close,
            'open': open_price,
            'high': high,
            'low': low,
            'volume': volume,
            'amount': amount,
            'change': round(change, 3),
            'changePct': round(change_pct, 2),
        }
        _cache[cache_key] = (result, time.time())
        return result
    except (IndexError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"行情解析失败: {str(e)}")


@router.get("/api/mx-trading/search")
async def search_stock(q: str = Query(..., min_length=1, description="股票代码或名称")):
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
