"""watchlist 妙想云同步（从妙想拉取到本地）
- POST /api/watchlist/sync-mx
"""
import logging
import httpx
from fastapi import APIRouter, HTTPException, Request

from config import MX_APIKEY, MX_API_URL
from db.connection import get_db
from db.session import get_db_session
from db.models import Watchlist
from ._shared import reset_watchlist_cache
from api.watchlist._shared import _get_http_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/watchlist/sync-mx")
async def sync_from_mx():
    """从东方财富妙想自选股同步到本地"""
    if not MX_APIKEY:
        raise HTTPException(status_code=500, detail="MX_APIKEY未配置")

    try:
        client = _get_http_client()
        resp = await client.post(
            f"{MX_API_URL}/api/claw/self-select/get",
            json={},
            headers={
                "apikey": MX_APIKEY,
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"妙想API请求失败: {str(e)}")

    code = str(data.get('code', data.get('status', '')))
    if code not in ('0', '200'):
        msg = data.get('message', '同步失败')
        raise HTTPException(status_code=400, detail=msg)

    try:
        all_results = data.get('data', {}).get('allResults', {})
        if isinstance(all_results, dict):
            result = all_results.get('result', {})
        elif isinstance(all_results, list) and all_results:
            result = all_results[0].get('result', {})
        else:
            result = {}
        data_list = result.get('dataList', []) if isinstance(result, dict) else []
    except Exception:
        logger.debug(f"function fallback", exc_info=True)
        data_list = []

    if not data_list:
        return {
            'success': True,
            'synced': 0,
            'skipped': 0,
            'message': '妙想自选股为空，无数据可同步',
        }

    with get_db_session() as db:
        synced = []
        skipped = []
        for item in data_list:
            stock_code = str(item.get('SECURITY_CODE', '')).strip()
            stock_name = str(item.get('SECURITY_SHORT_NAME', '')).strip()
            if not stock_code or len(stock_code) != 6:
                continue
            existing = db.query(Watchlist).filter_by(stock_code=stock_code).first()
            if existing:
                skipped.append(f"{stock_code} {stock_name}")
                continue
            new_item = Watchlist(
                stock_code=stock_code,
                stock_name=stock_name,
                note='妙想同步',
                group_name='妙想同步',
            )
            db.add(new_item)
            synced.append(f"{stock_code} {stock_name}")

        db.commit()
        reset_watchlist_cache()
        return {
            'success': True,
            'synced': len(synced),
            'skipped': len(skipped),
            'synced_list': synced,
            'skipped_list': skipped[:10],
            'message': f'同步完成：新增 {len(synced)} 只，跳过 {len(skipped)} 只已存在',
        }
