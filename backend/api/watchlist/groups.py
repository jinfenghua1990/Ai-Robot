"""watchlist 分组管理 API
- GET    /api/watchlist/groups
- POST   /api/watchlist/groups
- PUT    /api/watchlist/groups/rename
- DELETE /api/watchlist/groups/{name}
"""
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.connection import get_db
from db.session import get_db_session
from db.models import Watchlist
from ._shared import reset_watchlist_cache

logger = logging.getLogger(__name__)
router = APIRouter()


class GroupRenameRequest(BaseModel):
    old_name: str
    new_name: str


@router.get("/api/watchlist/groups")
async def list_groups():
    with get_db_session() as db:
        rows = db.query(Watchlist.group_name, Watchlist.stock_code).all()
        groups = {}
        for g, c in rows:
            name = g or '默认'
            groups[name] = groups.get(name, 0) + 1
        groups.setdefault('默认', 0)
        result = [{'name': n, 'count': cnt} for n, cnt in sorted(groups.items(), key=lambda x: (x[0] == '默认', x[0]))]
        return {'groups': result, 'active': '默认'}


@router.post("/api/watchlist/groups")
async def create_group(req: dict):
    name = (req.get('name') or '').strip()
    if not name:
        raise HTTPException(status_code=400, detail="分组名不能为空")
    if len(name) > 20:
        raise HTTPException(status_code=400, detail="分组名过长（≤20字）")
    with get_db_session() as db:
        existing = db.query(Watchlist.group_name).filter(Watchlist.group_name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"分组「{name}」已存在")
        return {'success': True, 'name': name}


@router.put("/api/watchlist/groups/rename")
async def rename_group(req: GroupRenameRequest):
    old = (req.old_name or '').strip()
    new = (req.new_name or '').strip()
    if not old or not new:
        raise HTTPException(status_code=400, detail="分组名不能为空")
    if old == new:
        return {'success': True, 'affected': 0}
    with get_db_session() as db:
        affected = db.query(Watchlist).filter(Watchlist.group_name == old).update({'group_name': new})
        db.commit()
        reset_watchlist_cache()
        # 同步 JSON：更新该分组下所有股票
        from .watchlist_local import update_stock, read_local, write_local
        data = read_local()
        for s in data["stocks"]:
            if s.get("group") == old:
                s["group"] = new
        write_local(data)
        return {'success': True, 'affected': affected, 'new_name': new}


@router.delete("/api/watchlist/groups/{name}")
async def delete_group(name: str, force: bool = Query(False)):
    if name == '默认':
        raise HTTPException(status_code=400, detail="默认分组不可删除")
    with get_db_session() as db:
        count = db.query(Watchlist).filter(Watchlist.group_name == name).count()
        if count > 0 and not force:
            raise HTTPException(status_code=400, detail=f"分组「{name}」还有 {count} 只股票，请先移走或使用 force=true")
        if force and count > 0:
            db.query(Watchlist).filter(Watchlist.group_name == name).update({'group_name': '默认'})
        db.commit()
        reset_watchlist_cache()
        # 同步 JSON
        if force and count > 0:
            from .watchlist_local import update_stock, read_local, write_local
            data = read_local()
            for s in data["stocks"]:
                if s.get("group") == name:
                    s["group"] = "默认"
            write_local(data)
        return {'success': True, 'moved': count if force else 0}
