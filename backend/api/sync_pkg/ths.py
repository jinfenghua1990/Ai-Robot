"""同花顺云端自选股同步
- 从 Mac 客户端的 Cookies.binarycookies 提取 cookie
- 通过网页 API 拉取/添加/删除云端自选股
- sync_from_ths: 从同花顺拉取到 AIROBOT
- sync_to_ths:   从 AIROBOT 推送到同花顺
"""
import os
import re
import time
import json
import logging
from pathlib import Path
from typing import Optional

import httpx
from fastapi import HTTPException, Request

from db.connection import get_db
from db.session import get_db_session
from db.models import Watchlist
from api.watchlist._shared import _get_http_client

logger = logging.getLogger(__name__)

# ========== Cookie 提取 ==========
_THS_COOKIE_PATHS = [
    os.environ.get('THS_COOKIE_PATH', ''),
    str(Path.home() / "Library/Containers/cn.com.10jqka.macstock/Data/Library/Cookies/Cookies.binarycookies"),
    str(Path.home() / ".airobot_ths_cookies.bin"),
]
THS_COOKIE_FILE = None
for _p in _THS_COOKIE_PATHS:
    if _p and os.path.exists(_p):
        THS_COOKIE_FILE = Path(_p)
        break

_ths_cookie_cache = {"str": None, "ts": 0}
_THS_COOKIE_TTL = 300

THS_BASE = "https://t.10jqka.com.cn"


def _extract_ths_cookies() -> dict:
    """从同花顺 Mac 客户端的 Cookies.binarycookies 提取 cookie"""
    global THS_COOKIE_FILE
    if not THS_COOKIE_FILE or not THS_COOKIE_FILE.exists():
        for _p in _THS_COOKIE_PATHS:
            if _p and os.path.exists(_p):
                THS_COOKIE_FILE = Path(_p)
                break
    if not THS_COOKIE_FILE or not THS_COOKIE_FILE.exists():
        raise HTTPException(
            status_code=500,
            detail="未找到同花顺 cookie 文件。请：1) 打开同花顺 Mac 客户端并登录；或 2) 手动复制 cookie 到 ~/.airobot_ths_cookies.bin；或 3) 设置环境变量 THS_COOKIE_PATH"
        )
    try:
        data = THS_COOKIE_FILE.read_bytes()
    except PermissionError:
        raise HTTPException(
            status_code=500,
            detail=f"无权限读取同花顺 cookie（macOS TCC 限制）。解决方案：1) 系统设置→隐私与安全性→完全磁盘访问权限→添加运行后端的程序；或 2) 终端执行 cp '{THS_COOKIE_FILE}' ~/.airobot_ths_cookies.bin 后重试"
        )
    pattern = rb'([\w.]*10jqka\.com\.cn)\x00([^\x00]+)\x00([^\x00]*)\x00([^\x00]+)\x00'
    matches = re.findall(pattern, data)

    cookies = {}
    for domain, name, path, value in matches:
        name_s = name.decode('utf-8', errors='replace')
        value_s = value.decode('utf-8', errors='replace')
        domain_s = domain.decode('utf-8', errors='replace')
        if name_s not in cookies or domain_s.startswith('.'):
            cookies[name_s] = value_s
    return cookies


def _get_ths_cookie_str() -> str:
    now = time.time()
    if _ths_cookie_cache["str"] and now - _ths_cookie_cache["ts"] < _THS_COOKIE_TTL:
        return _ths_cookie_cache["str"]

    cookies = _extract_ths_cookies()
    if not cookies:
        raise HTTPException(status_code=500, detail="无法提取同花顺 cookie，请确认同花顺 Mac 客户端已登录")

    cookie_str = '; '.join(f"{k}={v}" for k, v in cookies.items())
    _ths_cookie_cache["str"] = cookie_str
    _ths_cookie_cache["ts"] = now
    return cookie_str


def ths_market_id(code: str) -> str:
    """根据股票代码前缀判断市场ID"""
    if not code or len(code) != 6:
        return "33"
    c = code[0]
    if c in ('6', '9'):
        return "17"
    elif c in ('8', '4'):
        return "151"
    return "33"


def _ths_headers() -> dict:
    return {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) IHexin/5.3.2 (Royal Flush)',
        'Referer': 'http://stock.10jqka.com.cn/my/zixuan.shtml',
        'Cookie': _get_ths_cookie_str(),
        'DNT': '1',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }


def _parse_jsonp(text: str, callback: str = 'selfStock') -> Optional[dict]:
    m = re.search(fr'{re.escape(callback)}\((.*)\)', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None


async def ths_get_self_stock() -> list:
    """获取同花顺云端自选股列表"""
    ts = int(time.time() * 1000)
    url = f"{THS_BASE}/newcircle/group/getSelfStockWithMarket/?callback=selfStock&_={ts}"
    client = _get_http_client()
    resp = await client.get(url, headers=_ths_headers())
    parsed = _parse_jsonp(resp.text, 'selfStock')
    if not parsed:
        raise HTTPException(status_code=502, detail=f"同花顺响应解析失败: {resp.text[:200]}")
    if parsed.get('errorCode') != 0:
        raise HTTPException(status_code=400, detail=f"同花顺API错误: {parsed.get('errorMsg', '未知')}")

    market_names = {"17": "沪市", "33": "深市", "151": "北交所"}
    result = []
    for item in parsed.get('result', []):
        code = item.get('code', '')
        mid = item.get('marketid', '')
        result.append({
            "code": code,
            "marketid": mid,
            "market_name": market_names.get(mid, mid),
        })
    return result


async def ths_add_stock(code: str) -> dict:
    """添加自选股到同花顺云端"""
    ts = int(time.time() * 1000)
    url = f"{THS_BASE}/newcircle/group/modifySelfStock/?callback=modifyStock&op=add&stockcode={code}&_={ts}"
    client = _get_http_client()
    resp = await client.get(url, headers=_ths_headers())
    parsed = _parse_jsonp(resp.text, 'modifyStock')
    if not parsed:
        raise HTTPException(status_code=502, detail=f"同花顺添加响应解析失败: {resp.text[:200]}")
    return parsed


async def ths_delete_stock(code: str, marketid: Optional[str] = None) -> dict:
    """从同花顺云端删除自选股"""
    if not marketid:
        marketid = ths_market_id(code)
    ts = int(time.time() * 1000)
    url = f"{THS_BASE}/newcircle/group/modifySelfStock?op=del&stockcode={code}&marketid={marketid}&_={ts}"
    client = _get_http_client()
    resp = await client.get(url, headers=_ths_headers())
    parsed = _parse_jsonp(resp.text, 'modifyStock')
    if not parsed:
        raise HTTPException(status_code=502, detail=f"同花顺删除响应解析失败: {resp.text[:200]}")
    return parsed


# ========== Sync 业务逻辑 ==========

async def sync_from_ths(dry_run: bool = False, mirror: bool = False) -> dict:
    """从同花顺拉取自选股到 AIROBOT"""
    ths_list = await ths_get_self_stock()
    ths_codes = {s["code"] for s in ths_list}

    with get_db_session() as db:
        local_all = db.query(Watchlist).all()
        local_codes = {item.stock_code for item in local_all}
        to_add = ths_codes - local_codes
        to_delete = local_codes - ths_codes if mirror else set()

        if dry_run:
            return {"ths_count": len(ths_codes), "local_count": len(local_codes),
                    "to_add": len(to_add), "to_add_list": sorted(to_add),
                    "to_delete": len(to_delete), "to_delete_list": sorted(to_delete),
                    "mirror": mirror, "dry_run": True}

        added = []
        for code in to_add:
            item = Watchlist(
                stock_code=code,
                stock_name="",
                note="同花顺同步",
                group_name="同花顺同步",
            )
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

        return {
            "success": True,
            "ths_count": len(ths_codes),
            "local_count": len(local_codes),
            "added": len(added),
            "added_list": added,
            "skipped": len(ths_codes & local_codes),
            "deleted": len(deleted),
            "deleted_list": deleted,
            "mirror": mirror,
        }


async def sync_to_ths(dry_run: bool = False, mirror: bool = False) -> dict:
    """把 AIROBOT 自选股推送到同花顺"""
    ths_list = await ths_get_self_stock()
    ths_codes = {s["code"] for s in ths_list}
    ths_marketid = {s["code"]: s.get("marketid") for s in ths_list if s.get("marketid")}

    with get_db_session() as db:
        local_items = db.query(Watchlist).all()
        local_codes = {item.stock_code for item in local_items}
        to_push = local_codes - ths_codes
        to_delete = ths_codes - local_codes if mirror else set()

        if dry_run:
            return {
                "local_count": len(local_codes),
                "ths_count": len(ths_codes),
                "to_push": len(to_push),
                "to_push_list": sorted(to_push),
                "to_delete": len(to_delete),
                "to_delete_list": sorted(to_delete),
                "mirror": mirror,
                "dry_run": True,
            }

        pushed = []
        failed = []
        for code in to_push:
            try:
                result = await ths_add_stock(code)
                if result.get('errorCode') == 0:
                    pushed.append(code)
                else:
                    failed.append({"code": code, "error": result.get('errorMsg', '未知')})
                time.sleep(0.15)
            except Exception as e:
                failed.append({"code": code, "error": str(e)})

        deleted = []
        for code in to_delete:
            try:
                result = await ths_delete_stock(code, ths_marketid.get(code))
                if result.get('errorCode') == 0:
                    deleted.append(code)
                else:
                    failed.append({"code": code, "error": result.get('errorMsg', '未知')})
                time.sleep(0.15)
            except Exception as e:
                failed.append({"code": code, "error": str(e)})

        return {
            "success": True,
            "local_count": len(local_codes),
            "ths_count": len(ths_codes),
            "pushed": len(pushed),
            "pushed_list": pushed,
            "deleted": len(deleted),
            "deleted_list": deleted,
            "mirror": mirror,
            "failed": failed,
        }
