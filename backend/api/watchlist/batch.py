"""watchlist 批量操作 API
- POST /api/watchlist/batch-delete
- POST /api/watchlist/batch-move-group
- GET  /api/watchlist/export  (CSV)
"""
import csv
import logging
from io import StringIO
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db.connection import get_db
from db.session import get_db_session
from db.models import Watchlist
from ._shared import reset_watchlist_cache

logger = logging.getLogger(__name__)
router = APIRouter()


class BatchDeleteRequest(BaseModel):
    stock_codes: list[str]


class BatchMoveRequest(BaseModel):
    stock_codes: list[str]
    target_group: str


@router.post("/api/watchlist/batch-delete")
async def batch_delete(req: BatchDeleteRequest):
    if not req.stock_codes:
        return {'success': True, 'deleted': 0}
    with get_db_session() as db:
        deleted = db.query(Watchlist).filter(Watchlist.stock_code.in_(req.stock_codes)).delete(synchronize_session=False)
        db.commit()
        reset_watchlist_cache()
        return {'success': True, 'deleted': deleted}


@router.post("/api/watchlist/batch-move-group")
async def batch_move_group(req: BatchMoveRequest):
    if not req.stock_codes:
        return {'success': True, 'moved': 0}
    target = (req.target_group or '').strip() or '默认'
    with get_db_session() as db:
        moved = db.query(Watchlist).filter(Watchlist.stock_code.in_(req.stock_codes)).update({'group_name': target}, synchronize_session=False)
        db.commit()
        reset_watchlist_cache()
        return {'success': True, 'moved': moved, 'target_group': target}


@router.get("/api/watchlist/export")
async def export_csv():
    with get_db_session() as db:
        items = db.query(Watchlist).order_by(Watchlist.group_name, Watchlist.sort_order).all()
        buf = StringIO()
        w = csv.writer(buf)
        w.writerow(['分组', '代码', '备注', '排序'])
        for it in items:
            w.writerow([it.group_name or '默认', it.stock_code, it.note or '', it.sort_order or 0])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type='text/csv',
            headers={'Content-Disposition': 'attachment; filename=watchlist.csv'}
        )
