"""Watchlist 实时数据 SSE 推送

- 复用 REALTIME_STATE 内存态（scheduler 每 5 秒更新）
- 订阅：客户端 GET 时传 watchlist ts_code 列表，服务端每 5 秒推送一次
- 格式：SSE data 字段为 JSON {ts_code: {current_price, pct_chg, ...}}
- 自动清理：客户端断开后停止推送

设计权衡：
- 用 SSE 而非 WebSocket：浏览器原生 EventSource，自动重连，单向推送够用
- 5 秒推送周期匹配 scheduler 采集频率，避免重复刷新
- 单连接支持任意数量的 watchlist 股票
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from db.session import get_db_session
from db.models import Watchlist
from collectors.realtime_aggregator import REALTIME_STATE, serialize_state

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_watchlist_ts_codes() -> List[str]:
    """从 DB 读取自选股 ts_code 列表"""
    with get_db_session() as db:
        rows = db.query(Watchlist.stock_code).all()
        result = []
        for r in rows:
            code = r[0]
            if code.startswith(('6', '9')):
                result.append(f'{code}.SH')
            elif code.startswith(('8', '4')):
                result.append(f'{code}.BJ')
            else:
                result.append(f'{code}.SZ')
        return result


def _build_snapshot(ts_codes: List[str]) -> dict:
    """构建单帧推送数据：{ts_code: {price, pct_chg, ...}, server_time, count}"""
    from datetime import date
    from sqlalchemy import text

    snap = {
        'server_time': datetime.now().isoformat(timespec='seconds'),
        'data': {},
    }

    # 1. 从 REALTIME_STATE 取基础行情
    for ts_code in ts_codes:
        st = REALTIME_STATE.get(ts_code)
        if not st:
            continue
        snap['data'][ts_code] = serialize_state(ts_code)

    # 2. 从 realtime_stock_flow 补充实时资金流（多源交叉验证，统一数据源）
    if snap['data']:
        try:
            with get_db_session() as db:
                codes = [c for c in ts_codes if c in snap['data']]
                if codes:
                    rows = db.execute(text("""
                        SELECT DISTINCT ON (ts_code) ts_code,
                            snapshot_time,
                            main_force_inflow, retail_flow,
                            price, price_chg
                        FROM realtime_stock_flow
                        WHERE ts_code = ANY(:codes) AND trade_date = :td
                        ORDER BY ts_code, snapshot_time DESC
                    """), {"codes": codes, "td": date.today()}).fetchall()
                    for r in rows:
                        ts = r.ts_code
                        if ts in snap['data']:
                            main_net = float(r.main_force_inflow or 0) * 10000  # 万元→元
                            retail_net = float(r.retail_flow or 0) * 10000
                            snap['data'][ts].update({
                                "main_buy": 0,
                                "main_sell": 0,
                                "main_net": main_net,
                                "retail_buy": 0,
                                "retail_sell": 0,
                                "retail_net": retail_net,
                                "turnover": 0,
                                "snapshot_time": r.snapshot_time.isoformat() if r.snapshot_time else None,
                                "money_flow_source": "realtime_crossvalidated",
                            })
        except Exception as e:
            logger.warning(f"[realtime_stream] money flow query failed: {e}")

    snap['count'] = len(snap['data'])
    return snap


async def _event_stream(ts_codes: List[str]):
    """SSE 事件流：每 5 秒推送一次，15 秒心跳"""
    interval = 5.0
    heartbeat_interval = 15.0  # 每 3 帧发一次心跳
    frame_count = 0
    try:
        # 首次立即推送一帧
        yield f"data: {json.dumps(_build_snapshot(ts_codes), ensure_ascii=False)}\n\n"
        while True:
            await asyncio.sleep(interval)
            frame_count += 1
            # 每 3 帧插入一次心跳注释，保持连接活跃
            if frame_count % 3 == 0:
                yield f": heartbeat\n\n"
            yield f"data: {json.dumps(_build_snapshot(ts_codes), ensure_ascii=False)}\n\n"
    except asyncio.CancelledError:
        logger.debug(f'[watchlist-sse] client disconnected, ts_codes={len(ts_codes)}')
        raise


@router.get('/api/watchlist/realtime/stream')
async def stream_realtime():
    """SSE 端点：服务端推送 watchlist 全量实时态（每 5 秒）

    客户端:
      const es = new EventSource('/api/watchlist/realtime/stream');
      es.onmessage = (e) => { const payload = JSON.parse(e.data); ... };
    """
    ts_codes = _resolve_watchlist_ts_codes()
    if not ts_codes:
        # 空自选股时也保持连接，定期返回空帧供客户端确认存活
        async def empty_stream():
            yield f"data: {json.dumps({'server_time': datetime.now().isoformat(timespec='seconds'), 'data': {}, 'count': 0}, ensure_ascii=False)}\n\n"
            frame_count = 0
            while True:
                await asyncio.sleep(5.0)
                frame_count += 1
                if frame_count % 3 == 0:
                    yield f": heartbeat\n\n"
                yield f"data: {json.dumps({'server_time': datetime.now().isoformat(timespec='seconds'), 'data': {}, 'count': 0}, ensure_ascii=False)}\n\n"
        return StreamingResponse(empty_stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    return StreamingResponse(_event_stream(ts_codes), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@router.get('/api/watchlist/realtime/snapshot')
async def snapshot_realtime():
    """REST 端点：一次性返回 watchlist 当前实时态（用于非 SSE 客户端或回退）

    适合场景：手机端不支持 SSE、首次加载补全、调试
    """
    ts_codes = _resolve_watchlist_ts_codes()
    return _build_snapshot(ts_codes)
