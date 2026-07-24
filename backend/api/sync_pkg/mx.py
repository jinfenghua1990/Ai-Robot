"""妙想云端自选股同步（推送用）"""
import time
import logging
from fastapi import HTTPException

from config import MX_APIKEY, MX_API_URL
from api.watchlist._shared import _get_http_client

logger = logging.getLogger(__name__)


async def _mx_post(endpoint: str, payload: dict, timeout: float = 30.0) -> dict:
    """调用妙想 API（自然语言处理较慢，默认 30 秒超时）"""
    if not MX_APIKEY:
        raise HTTPException(status_code=500, detail="MX_APIKEY未配置")
    url = f"{MX_API_URL}{endpoint}"
    client = _get_http_client()
    # 共享 client 默认超时 10s 不够，妙想自然语言处理需 15-30s，这里用独立 timeout 覆盖
    resp = await client.post(url, json=payload, headers={
        "apikey": MX_APIKEY,
        "Content-Type": "application/json; charset=UTF-8",
    }, timeout=timeout)
    return resp.json()


async def mx_push_stock(stock_name: str) -> dict:
    """添加股票到妙想云端自选股（自然语言）"""
    return await _mx_post("/api/claw/self-select/manage", {"query": f"把{stock_name}加入自选"})


async def mx_delete_stock(stock_name: str) -> dict:
    """从妙想云端自选股删除（自然语言）"""
    return await _mx_post("/api/claw/self-select/manage", {"query": f"把{stock_name}从我的自选股列表删除"})


def _norm_code(code: str) -> str:
    """归一化为 6 位纯代码：去掉 .SH/.SZ/.BJ 等交易所后缀。"""
    if not code:
        return code
    c = code.strip().upper()
    if '.' in c:
        c = c.split('.')[0]
    return c


async def sync_to_mx(dry_run: bool = False, mirror: bool = False) -> dict:
    """把 AIROBOT 自选股推送到妙想云端"""
    from db.session import get_db_session
    from db.models import Watchlist
    from api.mx_skills import _parse_zixuan_list

    raw = await _mx_post("/api/claw/self-select/get", {})
    if isinstance(raw, dict) and raw.get('status') == 112:
        return {
            "success": False, "error": "妙想API限流，请稍后再试",
            "local_count": None, "mx_count": None,
            "pushed": 0, "pushed_list": [], "failed": [],
        }
    mx_list = _parse_zixuan_list(raw)
    mx_codes = {_norm_code(s["stock_code"]) for s in mx_list if s.get("stock_code")}
    mx_name = {_norm_code(s["stock_code"]): s.get("stock_name", "") for s in mx_list if s.get("stock_code")}

    with get_db_session() as db:
        local_items = db.query(Watchlist).all()
        # 归一化本地代码并建立 归一码 -> 原始记录 映射（去重）
        local_norm: dict = {}
        for it in local_items:
            nc = _norm_code(it.stock_code)
            if nc:
                local_norm.setdefault(nc, it)
        local_codes = set(local_norm.keys())
        to_push = local_codes - mx_codes
        to_delete = mx_codes - local_codes if mirror else set()

        if dry_run:
            return {
                "local_count": len(local_codes),
                "mx_count": len(mx_codes),
                "to_push": len(to_push),
                "to_push_list": sorted(to_push),
                "to_delete": len(to_delete),
                "to_delete_list": sorted(to_delete),
                "mirror": mirror,
                "dry_run": True,
            }

        code_name = {nc: (it.stock_name or nc) for nc, it in local_norm.items()}
        pushed = []
        failed = []
        for code in to_push:
            if not (len(code) == 6 and code.isdigit()):
                failed.append({"code": code, "error": "非A股代码跳过"})
                continue
            name = code_name.get(code, code)
            try:
                result = await mx_push_stock(name or code)
                if isinstance(result, dict) and result.get('status') == 112:
                    failed.append({"code": code, "error": "妙想限流，稍后重试"})
                    time.sleep(2)  # 限流时多等
                    continue
                pushed.append(code)
                time.sleep(0.2)  # 正常 0.2s 间隔（之前 1.0s 导致 160 只推送需 200 秒超时）
            except Exception as e:
                failed.append({"code": code, "error": str(e)})
                time.sleep(0.2)

        deleted = []
        for code in to_delete:
            if not (len(code) == 6 and code.isdigit()):
                continue
            name = mx_name.get(code, code)
            try:
                result = await mx_delete_stock(name or code)
                if isinstance(result, dict) and result.get('status') == 112:
                    failed.append({"code": code, "error": "妙想限流，稍后重试"})
                    time.sleep(2)
                    continue
                deleted.append(code)
                time.sleep(0.2)
            except Exception as e:
                failed.append({"code": code, "error": str(e)})
                time.sleep(0.2)

        return {
            "success": True,
            "local_count": len(local_codes),
            "mx_count": len(mx_codes),
            "pushed": len(pushed),
            "pushed_list": pushed,
            "deleted": len(deleted),
            "deleted_list": deleted,
            "mirror": mirror,
            "failed": failed,
        }


async def sync_from_mx(dry_run: bool = False, mirror: bool = False) -> dict:
    """从妙想拉取自选股到 AIROBOT"""
    from db.session import get_db_session
    from db.models import Watchlist
    from api.mx_skills import _parse_zixuan_list

    raw = await _mx_post("/api/claw/self-select/get", {})
    if isinstance(raw, dict) and raw.get('status') == 112:
        return {"success": False, "error": "妙想API限流，请稍后再试",
                "mx_count": None, "added": 0, "skipped": 0, "deleted": 0}
    mx_list = _parse_zixuan_list(raw)
    mx_codes = {s["stock_code"] for s in mx_list if s.get("stock_code")}
    code_name = {s["stock_code"]: s.get("stock_name", "") for s in mx_list}

    with get_db_session() as db:
        local_all = db.query(Watchlist).all()
        local_codes = {item.stock_code for item in local_all}
        to_add = {c for c in (mx_codes - local_codes) if len(c) == 6 and c.isdigit()}
        to_delete = local_codes - mx_codes if mirror else set()

        if dry_run:
            return {"mx_count": len(mx_codes), "local_count": len(local_codes),
                    "to_add": len(to_add), "to_add_list": sorted(to_add),
                    "to_delete": len(to_delete), "to_delete_list": sorted(to_delete),
                    "mirror": mirror, "dry_run": True}

        added = []
        for code in to_add:
            item = Watchlist(stock_code=code, stock_name=code_name.get(code, ""),
                             note="妙想同步", group_name="妙想同步")
            db.add(item)
            added.append(code)
        deleted = []
        if to_delete:
            db.query(Watchlist).filter(
                Watchlist.stock_code.in_(to_delete)
            ).delete(synchronize_session=False)
            deleted = sorted(to_delete)
        db.commit()
        from api.watchlist import _watchlist_cache
        _watchlist_cache["data"] = None
        return {"success": True, "mx_count": len(mx_codes), "local_count": len(local_codes),
                "added": len(added), "added_list": added, "skipped": len(mx_codes & local_codes),
                "deleted": len(deleted), "deleted_list": deleted, "mirror": mirror}
