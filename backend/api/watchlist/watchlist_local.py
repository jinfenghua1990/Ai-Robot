"""自选股数据库写入与兼容 JSON 导出。

数据库是唯一真相源；watchlist.json 只供旧脚本兼容，不参与查询决策。
"""
import json
import os
import logging
from datetime import datetime
from threading import Lock

from ._shared import normalize_stock_code

logger = logging.getLogger(__name__)

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../backend/api/watchlist
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_MODULE_DIR)))  # .../AIROBOT
WATCHLIST_JSON_PATH = os.path.join(_PROJECT_ROOT, "watchlist.json")

_lock = Lock()


def read_local() -> dict:
    """读取本地自选股 JSON，返回 {"stocks": [...], "version": 1, "updated_at": "..."}"""
    with _lock:
        try:
            with open(WATCHLIST_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data.get("stocks"), list):
                data["stocks"] = []
            return data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"watchlist.json 读取失败: {e}")
            return {"stocks": [], "version": 1, "updated_at": ""}


def write_local(data: dict):
    """写入本地自选股 JSON"""
    data["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    data.setdefault("version", 1)
    with _lock:
        os.makedirs(os.path.dirname(WATCHLIST_JSON_PATH), exist_ok=True)
        with open(WATCHLIST_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def add_stock(code: str, name: str = "", note: str = "", group: str = "默认"):
    """数据库新增/更新一只自选股，然后导出兼容 JSON。"""
    from db.session import get_db_session
    from db.models import Watchlist
    code = normalize_stock_code(code)
    if not code:
        return
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if item is None:
            item = Watchlist(stock_code=code)
            db.add(item)
        if name:
            item.stock_name = name
        if note:
            item.note = note
        if group:
            item.group_name = group
        db.commit()
    export_db_to_local()


def remove_stock(code: str):
    """从数据库删除一只自选股，然后导出兼容 JSON。"""
    from db.session import get_db_session
    from db.models import Watchlist
    code = normalize_stock_code(code)
    if not code:
        return
    with get_db_session() as db:
        db.query(Watchlist).filter_by(stock_code=code).delete()
        db.commit()
    export_db_to_local()


def update_stock(code: str, **kwargs):
    """更新数据库字段，然后导出兼容 JSON。"""
    from db.session import get_db_session
    from db.models import Watchlist
    field_map = {"name": "stock_name", "note": "note", "group": "group_name"}
    code = normalize_stock_code(code)
    if not code:
        return
    with get_db_session() as db:
        item = db.query(Watchlist).filter_by(stock_code=code).first()
        if item is None:
            return
        for key, value in kwargs.items():
            if value is not None and key in field_map:
                setattr(item, field_map[key], value)
        db.commit()
    export_db_to_local()


def get_stock_codes() -> list:
    """从数据库获取所有自选股代码。"""
    from db.session import get_db_session
    from db.models import Watchlist
    with get_db_session() as db:
        return [normalize_stock_code(row[0]) for row in db.query(Watchlist.stock_code).order_by(
            Watchlist.sort_order, Watchlist.created_at
        ).all()]


def export_db_to_local() -> dict:
    """将数据库当前状态导出到 JSON；仅作兼容备份。"""
    from db.session import get_db_session
    from db.models import Watchlist
    with get_db_session() as db:
        rows = db.query(Watchlist).order_by(
            Watchlist.sort_order, Watchlist.created_at
        ).all()
        data = {
            "stocks": [{
                "code": row.stock_code,
                "name": row.stock_name or "",
                "note": row.note or "",
                "group": row.group_name or "默认",
            } for row in rows],
            "version": 1,
        }
    write_local(data)
    return data


def sync_to_db():
    """仅用于空数据库的首次导入；已有数据库绝不被 JSON 覆盖或删除。"""
    from db.session import get_db_session
    from db.models import Watchlist

    with get_db_session() as db:
        if db.query(Watchlist).count() > 0:
            logger.info("[watchlist_local] DB 已有数据，跳过 JSON 导入")
            return export_db_to_local()
        data = read_local()
        stocks = data.get("stocks", [])
        if not stocks:
            logger.info("[watchlist_local] JSON 为空，跳过首次导入")
            return
        seen_codes = set()
        for s in stocks:
            code = normalize_stock_code(s.get("code"))
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            db.add(Watchlist(
                stock_code=code,
                stock_name=s.get("name", ""),
                note=s.get("note", ""),
                group_name=s.get("group", "默认"),
            ))
        db.commit()
        logger.info("[watchlist_local] 首次 JSON→DB 导入完成: %d", len(stocks))
    export_db_to_local()
