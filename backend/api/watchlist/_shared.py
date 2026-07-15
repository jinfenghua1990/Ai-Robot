"""watchlist 包内部共享状态与工具
包含：行情/K线缓存、watchlist 列表缓存、内部常量
所有子模块（core/groups/batch/quality/sync_mx）共用同一份缓存实例。
"""
import time
import asyncio
import logging
from typing import Optional
from utils.http_constants import SINA_HEADERS_SHORT as SINA_HEADERS

logger = logging.getLogger(__name__)

_quote_cache: dict = {}
_watchlist_cache = {"data": None, "ts": 0}
_watchlist_refreshing = False
_kline_cache: dict = {}

QUOTE_CACHE_TTL = 30
WATCHLIST_CACHE_TTL = 60
KLINE_CACHE_TTL = 3600

# 共享 httpx 客户端引用（由 main.py lifespan 设置）
_shared_http_client = None


def set_shared_http_client(client):
    """由 main.py lifespan 调用，设置共享 httpx 客户端"""
    global _shared_http_client
    _shared_http_client = client


def _get_http_client():
    """获取 httpx 客户端：优先共享实例，降级到临时创建"""
    if _shared_http_client and not _shared_http_client.is_closed:
        return _shared_http_client
    import httpx
    return httpx.AsyncClient(timeout=8, headers=SINA_HEADERS)


def reset_watchlist_cache():
    """清空 watchlist 列表缓存（外部模块删除/修改股票时调用）"""
    _watchlist_cache["data"] = None
    _watchlist_cache["ts"] = 0


QUOTE_FAIL_TTL = 5  # 失败短缓存：限流/故障时避免打爆新浪


async def get_quote(code: str) -> Optional[dict]:
    """获取新浪实时行情（缓存 30 秒，失败结果 5 秒）

    失败结果仅缓存 5 秒，避免新浪限流/临时故障时数据卡死。
    """
    cached = _quote_cache.get(code)
    if cached and time.time() - cached[1] < QUOTE_CACHE_TTL:
        return cached[0]
    # 失败短缓存：5s 内不再重试（避免打爆新浪）
    fail_ts = _quote_cache.get(code + '_fail_ts')
    if fail_ts and time.time() - fail_ts < QUOTE_FAIL_TTL:
        return None

    from utils import stock_code_to_sina
    sina_code = stock_code_to_sina(code)
    if not sina_code:
        return None
    url = f"https://hq.sinajs.cn/list={sina_code}"
    try:
        client = _get_http_client()
        resp = await client.get(url, headers=SINA_HEADERS, timeout=8)
        resp.encoding = 'gbk'
        text = resp.text
        if '"' not in text or len(text.split('"')) < 3:
            _quote_cache[code] = (None, time.time())
            _quote_cache[code + '_fail_ts'] = time.time()  # 失败短缓存标记
            return None
        parts = text.split('"')[1].split(',')
        if len(parts) < 10:
            _quote_cache[code] = (None, time.time())
            _quote_cache[code + '_fail_ts'] = time.time()
            return None
        yesterday_close = float(parts[1])
        current_price = float(parts[3])
        change = current_price - yesterday_close
        change_pct = (change / yesterday_close * 100) if yesterday_close else 0
        result = {
            'code': code,
            'name': parts[0],
            'price': current_price,
            'yesterdayClose': yesterday_close,
            'open': float(parts[2]),
            'high': float(parts[4]),
            'low': float(parts[5]),
            'volume': int(float(parts[8])),
            'change': round(change, 3),
            'changePct': round(change_pct, 2),
        }
        # 行情源校验：确保 low ≤ min(open, close), high ≥ max(open, close)
        min_price = min(result['open'], current_price)
        max_price = max(result['open'], current_price)
        if result['low'] > min_price:
            result['low'] = min_price
        if result['high'] < max_price:
            result['high'] = max_price
        _quote_cache[code] = (result, time.time())
        _quote_cache.pop(code + '_fail_ts', None)
        return result
    except Exception as e:
        logger.debug(f'[_shared] get_quote failed {code}: {e}')
        _quote_cache[code] = (None, time.time())
        _quote_cache[code + '_fail_ts'] = time.time()
        return None


async def fetch_kline_cached(code: str, datalen: int = 60) -> list:
    """日 K 线缓存（白天不变，缓存 1 小时，避免 164 只×HTTP=81 秒）"""
    from api.bs_signals import _fetch_kline
    cached = _kline_cache.get(code)
    if cached and time.time() - cached[1] < KLINE_CACHE_TTL:
        return cached[0]
    try:
        klines = await _fetch_kline(code, datalen)
        _kline_cache[code] = (klines, time.time())
        return klines
    except Exception as e:
        logger.debug(f'[_shared] fetch_kline_cached failed {code}: {e}')
        return []
