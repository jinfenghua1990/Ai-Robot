"""本地自选股 JSON 文件读写（唯一真相源）
watchlist.json 格式: {"stocks": [{"code","name","note","group"}], "version": 1, "updated_at": "..."}
"""
import json
import os
import logging
from datetime import datetime
from threading import Lock

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
    """本地新增一只自选股"""
    data = read_local()
    stocks = data["stocks"]
    # 去重
    for s in stocks:
        if s["code"] == code:
            s["name"] = name or s.get("name", "")
            s["note"] = note or s.get("note", "")
            s["group"] = group or s.get("group", "默认")
            write_local(data)
            return
    stocks.append({"code": code, "name": name, "note": note, "group": group})
    write_local(data)


def remove_stock(code: str):
    """本地删除一只自选股"""
    data = read_local()
    data["stocks"] = [s for s in data["stocks"] if s["code"] != code]
    write_local(data)


def update_stock(code: str, **kwargs):
    """本地更新一只自选股字段"""
    data = read_local()
    for s in data["stocks"]:
        if s["code"] == code:
            for k, v in kwargs.items():
                if v is not None:
                    s[k] = v
            break
    write_local(data)


def get_stock_codes() -> list:
    """获取所有自选股代码列表"""
    data = read_local()
    return [s["code"] for s in data["stocks"]]


def sync_to_db():
    """将本地 JSON 同步到 PostgreSQL Watchlist 表（启动时调用）"""
    from db.session import get_db_session
    from db.models import Watchlist

    data = read_local()
    stocks = data.get("stocks", [])
    if not stocks:
        logger.info("[watchlist_local] JSON 为空，跳过 DB 同步")
        return

    with get_db_session() as db:
        existing_map = {}
        for item in db.query(Watchlist).all():
            existing_map[item.stock_code] = item

        added, updated = 0, 0
        for s in stocks:
            code = s["code"]
            name = s.get("name", "")
            note = s.get("note", "")
            group = s.get("group", "默认")

            if code in existing_map:
                item = existing_map[code]
                changed = False
                if name and item.stock_name != name:
                    item.stock_name = name
                    changed = True
                if note and item.note != note:
                    item.note = note
                    changed = True
                if group and item.group_name != group:
                    item.group_name = group
                    changed = True
                if changed:
                    updated += 1
            else:
                db.add(Watchlist(
                    stock_code=code,
                    stock_name=name,
                    note=note,
                    group_name=group,
                ))
                added += 1

        # 删除 DB 中有但 JSON 中没有的股票
        json_codes = {s["code"] for s in stocks}
        removed = 0
        for code, item in existing_map.items():
            if code not in json_codes:
                db.delete(item)
                removed += 1

        db.commit()
        logger.info(f"[watchlist_local] JSON→DB 同步完成: +{added} ~{updated} -{removed}")