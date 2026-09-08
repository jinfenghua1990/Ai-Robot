"""watchlist 包内部共享状态与工具
包含：行情/K线缓存、watchlist 列表缓存、内部常量
所有子模块（core/groups/batch/quality/sync_mx）共用同一份缓存实例。
"""
import time
import asyncio
import logging
import re
from typing import Optional
from utils import should_use_intraday_snapshot
from utils.http_constants import SINA_HEADERS_SHORT as SINA_HEADERS

logger = logging.getLogger(__name__)

_quote_cache: dict = {}
_watchlist_cache = {"data": None, "ts": 0}
_watchlist_refreshing = False
_kline_cache: dict = {}

QUOTE_CACHE_TTL = 30
WATCHLIST_CACHE_TTL = 60
KLINE_CACHE_TTL = 3600

# 共享 httpx 客户端引用（由 main.py lifespan 设置）。仅允许在创建它的
# 事件循环中复用；APScheduler 的 asyncio.run() 会创建临时事件循环，跨循环
# 复用 httpx 客户端会触发 "bound to a different event loop"。
_shared_http_client = None
_shared_http_client_loop = None


def set_shared_http_client(client):
    """由 main.py lifespan 调用，设置共享 httpx 客户端，并记录其事件循环。"""
    global _shared_http_client, _shared_http_client_loop
    _shared_http_client = client
    try:
        _shared_http_client_loop = asyncio.get_running_loop()
    except RuntimeError:
        _shared_http_client_loop = None


class _OneShotHttpClient:
    """跨事件循环时按请求创建并关闭客户端，避免连接和文件描述符泄漏。"""

    async def request(self, method: str, url: str, **kwargs):
        import httpx
        async with httpx.AsyncClient(
            timeout=10,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=0),
            headers=SINA_HEADERS,
        ) as client:
            return await client.request(method, url, **kwargs)

    async def get(self, url: str, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        return await self.request("POST", url, **kwargs)


_one_shot_http_client = _OneShotHttpClient()


def _get_http_client():
    """同一事件循环复用 lifespan 客户端，否则使用会自动关闭的一次性客户端。"""
    shared = _shared_http_client
    if shared is not None and not shared.is_closed:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if _shared_http_client_loop is None or _shared_http_client_loop is loop:
            return shared
    return _one_shot_http_client


# 后台重建合并标记：短时间内的连续写操作只触发一次后台重建。
# 无锁竞态的最坏情况是多触发一次重建（singleflight 会去重并发的构建）。
_watchlist_rebuild_pending = False


def reset_watchlist_cache():
    """标记 watchlist 缓存过期并调度后台重建（外部模块删除/修改股票时调用）。

    保留旧数据作为 stale 兜底：若直接清成 None，下一次 GET 会落入
    "首次加载" 分支同步等待全量构建（冷构建实测 ~100s）。
    改为仅标记过期后，GET 立即返回旧数据，由这里调度的后台重建刷出新数据。
    """
    _watchlist_cache["ts"] = 0
    _schedule_watchlist_rebuild()


async def _delayed_watchlist_rebuild():
    """延迟数秒合并连续写操作，再做一次后台全量重建。"""
    global _watchlist_rebuild_pending
    try:
        await asyncio.sleep(3)
    finally:
        _watchlist_rebuild_pending = False
    try:
        # 延迟导入避免 _shared <-> core 循环依赖（core 顶层导入了本模块）
        from api.watchlist.core import refresh_watchlist_cache
        await refresh_watchlist_cache()
    except Exception as e:
        logger.warning(f"[watchlist] reset 后台重建失败: {e}")


def _schedule_watchlist_rebuild():
    """在主事件循环上调度一次后台重建。

    写操作路由多为同步 def（运行在线程池线程），也可能在临时事件循环
    （asyncio.run）中调用；统一回投到 main.py lifespan 记录的主循环执行。
    """
    global _watchlist_rebuild_pending
    if _watchlist_rebuild_pending:
        return
    main_loop = _shared_http_client_loop
    if main_loop is None or main_loop.is_closed():
        # 主循环尚未初始化（极早期调用）：退化为仅标记过期，由下次 GET 兜底
        return
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    _watchlist_rebuild_pending = True
    try:
        if current is main_loop:
            asyncio.create_task(_delayed_watchlist_rebuild())
        else:
            asyncio.run_coroutine_threadsafe(_delayed_watchlist_rebuild(), main_loop)
    except Exception:
        _watchlist_rebuild_pending = False
        logger.debug("[watchlist] 后台重建调度失败", exc_info=True)


QUOTE_FAIL_TTL = 5


def _candidate_ts_codes(code: str) -> tuple[str, list[str]]:
    raw = str(code or "").strip().upper()
    match = re.search(r"\d{6}", raw)
    if not match:
        return "", []
    bare = match.group(0)
    suffix_match = re.search(r"\.(SH|SZ|BJ)\b", raw)
    explicit_suffix = suffix_match.group(1) if suffix_match else None
    if bare.startswith("92") or bare[0] in ("4", "8"):
        suffixes = ("BJ", "SZ", "SH")
    elif bare[0] in ("5", "6", "9"):
        suffixes = ("SH", "SZ", "BJ")
    else:
        suffixes = ("SZ", "SH", "BJ")
    if explicit_suffix:
        suffixes = (explicit_suffix,) + tuple(item for item in suffixes if item != explicit_suffix)
    return bare, [f"{bare}.{suffix}" for suffix in suffixes] + [bare]


def normalize_stock_code(code: str) -> str:
    """统一为数据库自选表使用的 6 位代码。"""
    bare, _ = _candidate_ts_codes(code)
    return bare


def normalize_ts_code(code: str) -> str:
    """统一为行情表使用的交易所后缀代码，兼容北交所 920 前缀。"""
    _, candidates = _candidate_ts_codes(code)
    return candidates[0] if candidates else ""


def _read_quotes_from_db(codes: list[str]) -> dict:
    """批量读取最新数据库行情；不联网、不补采、不写库。"""
    from sqlalchemy import func
    from db.session import get_db_session
    from db.models import RealtimeStockFlow, StockDailyKline, StockFlow, Watchlist

    normalized = []
    candidates_by_code = {}
    for raw_code in codes:
        bare, candidates = _candidate_ts_codes(raw_code)
        if bare and bare not in candidates_by_code:
            normalized.append(bare)
            candidates_by_code[bare] = candidates
    if not normalized:
        return {}

    all_candidates = sorted({ts for values in candidates_by_code.values() for ts in values})
    with get_db_session() as db:
        # 读取自动采集器已经落库的同一批最新快照。按单股在千万级 Tick 表
        # 做窗口排序不仅慢，还会让不同股票使用不同截止时间。
        latest_snapshot = db.query(func.max(RealtimeStockFlow.snapshot_time)).scalar()
        flow_rows = []
        if latest_snapshot is not None:
            flow_rows = db.query(RealtimeStockFlow).filter(
                RealtimeStockFlow.snapshot_time == latest_snapshot,
                RealtimeStockFlow.ts_code.in_(all_candidates),
                RealtimeStockFlow.price.isnot(None),
                RealtimeStockFlow.price > 0,
            ).all()
        flow_by_ts = {str(row.ts_code): row for row in flow_rows}

        # 日线始终同时读取：盘中可以由分钟快照覆盖，收盘后则以已入库的
        # 同日日线收盘价为准，不能让 14:57 的旧快照覆盖 15:00 收盘。
        daily_candidates = sorted({
            ts_code
            for candidates in candidates_by_code.values()
            for ts_code in candidates
        })
        daily_ranked = db.query(
            StockDailyKline.ts_code.label("ts_code"),
            StockDailyKline.trade_date.label("trade_date"),
            StockDailyKline.open.label("open"),
            StockDailyKline.high.label("high"),
            StockDailyKline.low.label("low"),
            StockDailyKline.close.label("close"),
            StockDailyKline.volume.label("volume"),
            StockDailyKline.amount.label("amount"),
            func.row_number().over(
                partition_by=StockDailyKline.ts_code,
                order_by=StockDailyKline.trade_date.desc(),
            ).label("rn"),
        ).filter(
            StockDailyKline.ts_code.in_(daily_candidates),
            StockDailyKline.close.isnot(None),
            StockDailyKline.close > 0,
        ).subquery()
        daily_rows = (
            db.query(daily_ranked).filter(daily_ranked.c.rn <= 2).all()
            if daily_candidates else []
        )
        daily_by_ts = {}
        for row in daily_rows:
            daily_by_ts.setdefault(str(row.ts_code), []).append(row)
        for rows in daily_by_ts.values():
            rows.sort(key=lambda row: row.trade_date, reverse=True)

        name_map = {
            str(row.stock_code): (row.stock_name or "")
            for row in db.query(Watchlist.stock_code, Watchlist.stock_name).filter(
                Watchlist.stock_code.in_(normalized)
            ).all()
        }
        for row in flow_rows:
            if row.name:
                name_map[str(row.ts_code).split(".")[0]] = row.name
        missing_name_codes = [bare for bare in normalized if not name_map.get(bare)]
        missing_name_candidates = sorted({
            ts for bare in missing_name_codes for ts in candidates_by_code[bare]
        })
        if missing_name_candidates:
            name_ranked = db.query(
                StockFlow.ts_code.label("ts_code"),
                StockFlow.name.label("name"),
                func.row_number().over(
                    partition_by=StockFlow.ts_code,
                    order_by=StockFlow.trade_date.desc(),
                ).label("rn"),
            ).filter(
                StockFlow.ts_code.in_(missing_name_candidates),
                StockFlow.name.isnot(None),
            ).subquery()
            for row in db.query(name_ranked).filter(name_ranked.c.rn == 1).all():
                name_map.setdefault(str(row.ts_code).split(".")[0], row.name or "")

    result = {}
    for bare in normalized:
        candidates = candidates_by_code[bare]
        selected_ts = next(
            (ts for ts in candidates if ts in flow_by_ts or ts in daily_by_ts),
            None,
        )
        if not selected_ts:
            result[bare] = None
            continue

        flow = flow_by_ts.get(selected_ts)
        daily = daily_by_ts.get(selected_ts, [])
        latest_daily = daily[0] if daily else None
        previous_daily = daily[1] if len(daily) > 1 else None

        use_flow = flow is not None and should_use_intraday_snapshot(
            flow.trade_date,
            latest_daily.trade_date if latest_daily else None,
        )
        if use_flow:
            price = float(flow.price)
            flow_change_pct = float(flow.price_chg) if flow.price_chg is not None else None
            if latest_daily and latest_daily.trade_date < flow.trade_date:
                previous_close = float(latest_daily.close) if latest_daily.close is not None else None
            elif previous_daily and previous_daily.close is not None:
                previous_close = float(previous_daily.close)
            else:
                divisor = 1 + flow_change_pct / 100 if flow_change_pct is not None else None
                previous_close = price / divisor if divisor is not None and divisor > 0 else None
            # 分钟资金流快照没有 OHLC/成交量字段，明确返回空值，不能拿
            # 上一交易日日线静默冒充今天的盘中字段。
            open_price = None
            high = None
            low = None
            volume = None
            amount = None
            data_as_of = flow.snapshot_time.isoformat() if flow.snapshot_time else None
            upstream_source = flow.source or "realtime_stock_flow"
        elif latest_daily is not None:
            price = float(latest_daily.close)
            previous_close = float(previous_daily.close) if previous_daily else None
            open_price = float(latest_daily.open) if latest_daily.open is not None else None
            high = float(latest_daily.high) if latest_daily.high is not None else None
            low = float(latest_daily.low) if latest_daily.low is not None else None
            volume = int(latest_daily.volume) if latest_daily.volume is not None else None
            amount = float(latest_daily.amount) if latest_daily.amount is not None else None
            data_as_of = latest_daily.trade_date.isoformat()
            upstream_source = "daily_kline"
        else:
            # 只有分钟快照且没有日线时，保持真实可用数据，不凭空补字段。
            price = float(flow.price)
            flow_change_pct = float(flow.price_chg) if flow.price_chg is not None else None
            divisor = 1 + flow_change_pct / 100 if flow_change_pct is not None else None
            previous_close = price / divisor if divisor is not None and divisor > 0 else None
            open_price = high = low = volume = amount = None
            data_as_of = flow.snapshot_time.isoformat() if flow.snapshot_time else None
            upstream_source = flow.source or "realtime_stock_flow"

        change = price - previous_close if previous_close is not None else None
        missing_fields = [
            key for key, value in {
                'previous_close': previous_close,
                'open': open_price,
                'high': high,
                'low': low,
                'volume': volume,
                'amount': amount,
            }.items() if value is None
        ]
        result[bare] = {
            "code": bare,
            "name": name_map.get(bare) or bare,
            "price": price,
            "yesterdayClose": previous_close,
            "open": open_price,
            "high": high,
            "low": low,
            "volume": volume,
            "amount": amount,
            "change": round(change, 3) if change is not None else None,
            "changePct": round(change / previous_close * 100, 2) if previous_close else None,
            "source": "database",
            "upstreamSource": upstream_source,
            "dataAsOf": data_as_of,
            # 行情可用性的必需字段只有现价与涨跌幅；OHLC/量额缺失单独
            # 放在 missingFields，不应让依赖价格的模块整条失效。
            "status": "READY" if price > 0 and previous_close else "PARTIAL",
            "coverageStatus": "PARTIAL" if missing_fields else "READY",
            "missingFields": missing_fields,
        }
    return result


def _read_klines_from_db(code: str, datalen: int) -> list:
    from db.session import get_db_session
    from db.models import StockDailyKline

    bare, candidates = _candidate_ts_codes(code)
    if not bare:
        return []
    limit = max(1, min(int(datalen or 60), 1000))
    with get_db_session() as db:
        rows = []
        for ts_code in candidates:
            rows = db.query(StockDailyKline).filter(
                StockDailyKline.ts_code == ts_code,
                StockDailyKline.open.isnot(None),
                StockDailyKline.close.isnot(None),
                StockDailyKline.high.isnot(None),
                StockDailyKline.low.isnot(None),
                StockDailyKline.volume.isnot(None),
            ).order_by(StockDailyKline.trade_date.desc()).limit(limit).all()
            if rows:
                break
    return [{
        "date": row.trade_date.isoformat(),
        "open": float(row.open),
        "close": float(row.close),
        "high": float(row.high),
        "low": float(row.low),
        "volume": int(row.volume),
        "amount": float(row.amount) if row.amount is not None else None,
    } for row in reversed(rows)]


def _read_klines_batch_from_db(codes: list[str], datalen: int) -> dict[str, list]:
    """一次窗口查询批量读取自选股日 K，不联网、不补采。"""
    from sqlalchemy import func
    from db.session import get_db_session
    from db.models import StockDailyKline

    candidates_by_code = {}
    for raw_code in codes:
        bare, candidates = _candidate_ts_codes(raw_code)
        if bare and bare not in candidates_by_code:
            candidates_by_code[bare] = candidates
    if not candidates_by_code:
        return {}

    limit = max(1, min(int(datalen or 60), 1000))
    all_candidates = sorted({ts for values in candidates_by_code.values() for ts in values})
    with get_db_session() as db:
        ranked = db.query(
            StockDailyKline.ts_code.label('ts_code'),
            StockDailyKline.trade_date.label('trade_date'),
            StockDailyKline.open.label('open'),
            StockDailyKline.close.label('close'),
            StockDailyKline.high.label('high'),
            StockDailyKline.low.label('low'),
            StockDailyKline.volume.label('volume'),
            StockDailyKline.amount.label('amount'),
            func.row_number().over(
                partition_by=StockDailyKline.ts_code,
                order_by=StockDailyKline.trade_date.desc(),
            ).label('rn'),
        ).filter(
            StockDailyKline.ts_code.in_(all_candidates),
            StockDailyKline.open.isnot(None),
            StockDailyKline.close.isnot(None),
            StockDailyKline.high.isnot(None),
            StockDailyKline.low.isnot(None),
            StockDailyKline.volume.isnot(None),
        ).subquery()
        rows = db.query(ranked).filter(ranked.c.rn <= limit).all()

    by_ts = {}
    for row in rows:
        by_ts.setdefault(str(row.ts_code), []).append(row)
    result = {}
    for bare, candidates in candidates_by_code.items():
        selected = next((ts_code for ts_code in candidates if ts_code in by_ts), None)
        selected_rows = sorted(by_ts.get(selected, []), key=lambda row: row.trade_date)
        result[bare] = [{
            'date': row.trade_date.isoformat(),
            'open': float(row.open),
            'close': float(row.close),
            'high': float(row.high),
            'low': float(row.low),
            'volume': int(row.volume),
            'amount': float(row.amount) if row.amount is not None else None,
        } for row in selected_rows]
    return result


async def get_quote(code: str) -> Optional[dict]:
    """读取数据库最新行情；30 秒缓存仅缓存数据库查询结果。"""
    bare, _ = _candidate_ts_codes(code)
    if not bare:
        return None
    cached = _quote_cache.get(bare)
    if cached and time.time() - cached[1] < QUOTE_CACHE_TTL:
        return cached[0]
    fail_ts = _quote_cache.get(bare + '_fail_ts')
    if fail_ts and time.time() - fail_ts < QUOTE_FAIL_TTL:
        return None
    try:
        result = (await asyncio.to_thread(_read_quotes_from_db, [bare])).get(bare)
        _quote_cache[bare] = (result, time.time())
        if result is None:
            _quote_cache[bare + '_fail_ts'] = time.time()
        else:
            _quote_cache.pop(bare + '_fail_ts', None)
        return result
    except Exception as e:
        logger.debug(f'[_shared] get_quote failed {code}: {e}')
        _quote_cache[bare] = (None, time.time())
        _quote_cache[bare + '_fail_ts'] = time.time()
        return None


async def batch_get_quotes(codes: list) -> dict:
    """批量读取数据库行情，返回 {原始代码: quote|None}。"""
    result = {}
    miss_codes = []
    original_to_bare = {}
    now = time.time()
    for raw_code in codes:
        bare, _ = _candidate_ts_codes(raw_code)
        if not bare:
            result[raw_code] = None
            continue
        original_to_bare[raw_code] = bare
        cached = _quote_cache.get(bare)
        if cached and now - cached[1] < QUOTE_CACHE_TTL:
            result[raw_code] = cached[0]
        else:
            fail_ts = _quote_cache.get(bare + '_fail_ts')
            if fail_ts and now - fail_ts < QUOTE_FAIL_TTL:
                result[raw_code] = None
            else:
                miss_codes.append(bare)

    if miss_codes:
        try:
            fetched = await asyncio.to_thread(_read_quotes_from_db, sorted(set(miss_codes)))
            for bare in set(miss_codes):
                quote = fetched.get(bare)
                _quote_cache[bare] = (quote, now)
                if quote is not None:
                    _quote_cache.pop(bare + '_fail_ts', None)
                else:
                    _quote_cache[bare + '_fail_ts'] = now
        except Exception as e:
            logger.warning(f'[_shared] batch database quote query failed: {e}')
            for bare in set(miss_codes):
                _quote_cache[bare] = (None, now)
                _quote_cache[bare + '_fail_ts'] = now

    for raw_code, bare in original_to_bare.items():
        result.setdefault(raw_code, _quote_cache.get(bare, (None, now))[0])

    return result


async def fetch_kline_cached(code: str, datalen: int = 60) -> list:
    """只读取数据库日 K；缓存键包含长度，避免 60 日结果污染 300 日请求。"""
    bare, _ = _candidate_ts_codes(code)
    if not bare:
        return []
    cache_key = (bare, int(datalen or 60))
    cached = _kline_cache.get(cache_key)
    if cached and time.time() - cached[1] < KLINE_CACHE_TTL:
        return cached[0]
    try:
        klines = await asyncio.to_thread(_read_klines_from_db, bare, datalen)
        _kline_cache[cache_key] = (klines, time.time())
        return klines
    except Exception as e:
        logger.debug(f'[_shared] fetch_kline_cached failed {code}: {e}')
        return []


async def batch_fetch_kline_cached(codes: list[str], datalen: int = 60) -> dict[str, list]:
    """批量读取并填充现有日 K 缓存，返回 {原始代码: 日 K 列表}。"""
    now = time.time()
    limit = int(datalen or 60)
    result = {}
    missing = []
    original_to_bare = {}
    for raw_code in codes:
        bare, _ = _candidate_ts_codes(raw_code)
        if not bare:
            result[raw_code] = []
            continue
        original_to_bare[raw_code] = bare
        cached = _kline_cache.get((bare, limit))
        if cached and now - cached[1] < KLINE_CACHE_TTL:
            result[raw_code] = cached[0]
        else:
            missing.append(bare)

    if missing:
        try:
            fetched = await asyncio.to_thread(_read_klines_batch_from_db, sorted(set(missing)), limit)
            for bare in set(missing):
                _kline_cache[(bare, limit)] = (fetched.get(bare, []), now)
        except Exception as e:
            logger.warning('[_shared] batch database K-line query failed: %s', e)
            for bare in set(missing):
                _kline_cache[(bare, limit)] = ([], now)

    for raw_code, bare in original_to_bare.items():
        result.setdefault(raw_code, _kline_cache.get((bare, limit), ([], now))[0])
    return result
