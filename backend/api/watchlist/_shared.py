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
_shared_http_client_loop = None  # 设置时所在的事件循环，用于检测 loop 不匹配
_loop_fallback: dict = {}  # loop.id -> 临时 client，避免跨 loop 复用引发 "different loop" 错误


def set_shared_http_client(client):
    """由 main.py lifespan 调用，设置共享 httpx 客户端，并记录其事件循环。"""
    global _shared_http_client, _shared_http_client_loop
    _shared_http_client = client
    try:
        _shared_http_client_loop = asyncio.get_running_loop()
    except RuntimeError:
        _shared_http_client_loop = None


def _get_http_client():
    """获取 httpx 客户端：优先共享实例(同循环)，否则按当前运行循环创建并缓存独立 client，
    避免重启后 lifespan 创建的 client 绑定旧 loop 导致 'attached to a different loop' 错误。"""
    shared = _shared_http_client
    if shared is not None and not shared.is_closed:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if _shared_http_client_loop is None or _shared_http_client_loop is loop:
            return shared
        # loop 不匹配 -> 用当前 loop 的临时 client（缓存，避免每次新建）
        if loop is not None:
            fb = _loop_fallback.get(id(loop))
            if fb is not None and not fb.is_closed:
                return fb
            import httpx
            fb = httpx.AsyncClient(timeout=8, headers=SINA_HEADERS)
            _loop_fallback[id(loop)] = fb
            return fb
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
        # 新浪格式: name, 今开盘, 昨收盘, 当前价, 最高, 最低, ...
        yesterday_close = float(parts[2])
        current_price = float(parts[3])
        change = current_price - yesterday_close
        change_pct = (change / yesterday_close * 100) if yesterday_close else 0
        result = {
            'code': code,
            'name': parts[0],
            'price': current_price,
            'yesterdayClose': yesterday_close,
            'open': float(parts[1]),
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


async def batch_get_quotes(codes: list) -> dict:
    """批量获取新浪实时行情（一次最多 50 只，大幅减少 HTTP 请求）

    Args:
        codes: 股票代码列表，如 ['300285', '600000']
    Returns:
        dict: {code: quote_dict, ...}，失败或无数据的 code 值为 None
    """
    from utils import stock_code_to_sina
    result = {}
    # 先用缓存命中
    miss_codes = []
    now = time.time()
    for code in codes:
        cached = _quote_cache.get(code)
        if cached and now - cached[1] < QUOTE_CACHE_TTL:
            result[code] = cached[0]
        else:
            # 失败短缓存检查
            fail_ts = _quote_cache.get(code + '_fail_ts')
            if fail_ts and now - fail_ts < QUOTE_FAIL_TTL:
                result[code] = None
            else:
                miss_codes.append(code)

    if not miss_codes:
        return result

    # 批量请求新浪（每批最多 50 只）
    BATCH = 50
    for i in range(0, len(miss_codes), BATCH):
        batch = miss_codes[i:i + BATCH]
        sina_codes = []
        code_to_sina = {}
        for code in batch:
            sc = stock_code_to_sina(code)
            if sc:
                sina_codes.append(sc)
                code_to_sina[code] = sc
        if not sina_codes:
            for code in batch:
                result[code] = None
                _quote_cache[code] = (None, now)
            continue

        url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
        try:
            client = _get_http_client()
            resp = await client.get(url, headers=SINA_HEADERS, timeout=8)
            resp.encoding = 'gbk'
            text = resp.text
            # 新浪返回格式：每行 var hq_str_xxx="field1,field2,...";
            lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
            # 建立 sina_code -> quote 的映射
            sina_to_quote = {}
            for ln in lines:
                if '=' not in ln or '"' not in ln:
                    continue
                var_part = ln.split('=')[0]
                data_part = ln.split('"')[1] if '"' in ln else ''
                if not data_part:
                    continue
                # var hq_str_sz300285
                sc = var_part.split('hq_str_')[-1]
                parts = data_part.split(',')
                if len(parts) < 10:
                    sina_to_quote[sc] = None
                    continue
                try:
                    yesterday_close = float(parts[2])
                    current_price = float(parts[3])
                    change = current_price - yesterday_close
                    change_pct = (change / yesterday_close * 100) if yesterday_close else 0
                    q = {
                        'name': parts[0],
                        'price': current_price,
                        'yesterdayClose': yesterday_close,
                        'open': float(parts[1]),
                        'high': float(parts[4]),
                        'low': float(parts[5]),
                        'volume': int(float(parts[8])),
                        'change': round(change, 3),
                        'changePct': round(change_pct, 2),
                    }
                    # 行情源校验
                    min_price = min(q['open'], current_price)
                    max_price = max(q['open'], current_price)
                    if q['low'] > min_price:
                        q['low'] = min_price
                    if q['high'] < max_price:
                        q['high'] = max_price
                    sina_to_quote[sc] = q
                except Exception:
                    sina_to_quote[sc] = None

            # 回填到 result 和缓存
            for code in batch:
                sc = code_to_sina.get(code)
                q = sina_to_quote.get(sc) if sc else None
                if q:
                    q['code'] = code
                    result[code] = q
                    _quote_cache[code] = (q, now)
                    _quote_cache.pop(code + '_fail_ts', None)
                else:
                    result[code] = None
                    _quote_cache[code] = (None, now)
                    _quote_cache[code + '_fail_ts'] = now
        except Exception as e:
            logger.warning(f'[_shared] batch_get_quotes failed (batch {i//BATCH+1}): {e}')
            for code in batch:
                result[code] = None
                _quote_cache[code] = (None, now)
                _quote_cache[code + '_fail_ts'] = now

    return result


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
