"""
模拟盘交易API（trading）
现作为东财模拟盘 146w 账户的展示/手动交易入口，通过 MX_APIKEY 代理到东方财富妙想接口
与东财自动化模拟盘（/api/mx-trading，MX_TRADING_APIKEY）完全独立
"""
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from config import MX_APIKEY
from utils import stock_code_to_sina as _stock_code_to_sina
from api.watchlist._shared import _get_http_client
from utils.http_constants import SINA_HEADERS_SHORT

router = APIRouter()


async def _get_realtime_price(code: str) -> dict:
    """获取新浪实时行情，返回 {name, price, yesterday_close, change_pct}"""
    sina_code = _stock_code_to_sina(code)
    if not sina_code:
        raise HTTPException(status_code=400, detail="无效的股票代码")

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
        current_price = float(parts[3])
        change_pct = ((current_price - yesterday_close) / yesterday_close * 100) if yesterday_close else 0
        return {
            'name': name,
            'price': current_price,
            'yesterday_close': yesterday_close,
            'change_pct': change_pct,
        }
    except (IndexError, ValueError) as e:
        raise HTTPException(status_code=500, detail=f"行情解析失败: {str(e)}")


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


# ========== 账户/交易接口：代理到东财 146w 账户（MX_APIKEY） ==========

async def get_balance(force: bool = False) -> dict:
    """查询模拟盘账户资金（146w 东财账户）"""
    from api.mx_trading import fetch_balance
    return await fetch_balance(api_key=MX_APIKEY, force=force)


async def get_positions(force: bool = False) -> dict:
    """查询模拟盘持仓明细（146w 东财账户）"""
    from api.mx_trading import fetch_positions
    return await fetch_positions(api_key=MX_APIKEY, force=force)


@router.get("/api/trading/balance")
async def get_balance_endpoint(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """查询模拟盘账户资金（146w 东财账户）"""
    return await get_balance(force=bool(force))


@router.get("/api/trading/positions")
async def get_positions_endpoint(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """查询模拟盘持仓明细（146w 东财账户）"""
    return await get_positions(force=bool(force))


@router.get("/api/trading/orders")
async def get_orders(
    drt: int = Query(0, description="0=全部, 1=买入, 2=卖出"),
    status: int = Query(0, description="0=全部, 4=已成"),
):
    """查询模拟盘委托记录（146w 东财账户）"""
    from api.mx_trading import fetch_orders
    # 状态码映射保持与旧接口一致：前端传 4=已成，东财接口也使用 4
    return await fetch_orders(api_key=MX_APIKEY, drt=drt, status=status)


@router.post("/api/trading/trade")
async def trade(req: TradeRequest):
    """模拟盘买入/卖出（146w 东财账户）"""
    from api.mx_trading import place_trade
    return await place_trade(
        api_key=MX_APIKEY,
        type=req.type,
        stock_code=req.stockCode,
        quantity=req.quantity,
        use_market_price=req.useMarketPrice,
        price=req.price,
    )


@router.post("/api/trading/cancel")
async def cancel(req: CancelRequest):
    """模拟盘撤单（146w 东财账户）"""
    from api.mx_trading import place_cancel
    return await place_cancel(
        api_key=MX_APIKEY,
        type=req.type,
        order_id=req.orderId,
        stock_code=req.stockCode,
    )


@router.get("/api/trading/quote")
async def get_realtime_quote(code: str = Query(..., description="6位股票代码")):
    """获取新浪实时行情"""
    quote = await _get_realtime_price(code)
    return {
        'code': code,
        'name': quote['name'],
        'price': quote['price'],
        'yesterdayClose': quote['yesterday_close'],
        'changePct': quote['change_pct'],
    }


@router.get("/api/trading/search")
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
