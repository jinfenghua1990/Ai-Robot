"""
新浪财经自选股同步

通过 Sina/Weibo 登录 cookie 对接 watchlist.finance.sina.com.cn
实现云端自选股同步。
API 端点发现自 Sina 新版自选股页面 (i.finance.sina.com.cn/zixuan) 的 stock_all.js。

API 格式:
- GET list:  HoldV2Service.getAllPySymbolsList?source=pc_mzx&type=all
- ADD:       HoldV2Service.appendSymbol?scode=<market><code>@<type>&source=pc_mzx&pid=
- DELETE:    HoldV2Service.delSymbolFace?scode=<market><code>@<type>&source=pc_mzx&pid=

scode 格式:
- A股: sh600519@cn / sz000001@cn / bj920179@cn
- 美股: usSPCX
- 港股: hk00700
"""
import os
import re
import time
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)
from fastapi import APIRouter, HTTPException, Query

from db.connection import get_db
from db.session import get_db_session
from db.models import Watchlist
from api.watchlist._shared import _get_http_client

router = APIRouter()

SINA_COOKIE = os.getenv("SINA_COOKIE", "").strip()
SINA_BASE = "https://watchlist.finance.sina.com.cn/portfolio/api/openapi.php"

# 缓存
_SINA_CACHE = {"data": None, "ts": 0}
_SINA_CACHE_TTL = 60  # 1分钟缓存


def _sina_code_to_scode(code: str) -> str:
    """6位A股代码 → 新浪 scode 格式 (如 sh600519@cn)"""
    if not code or len(code) != 6 or not code.isdigit():
        return code  # 非A股原样返回
    c = code[0]
    if c in ('6', '9'):
        market = 'sh'
    elif c in ('8', '4'):
        market = 'bj'
    else:
        market = 'sz'
    return f"{market}{code}@cn"


def _scode_to_code(scode: str) -> Optional[str]:
    """新浪 scode 格式 → 6位A股代码（非A股返回None让调用方处理）"""
    if not scode:
        return None
    # sh600519@cn → 600519
    m = re.match(r'^(?:sh|sz|bj)(\d{6})(?:@cn)?$', scode)
    if m:
        return m.group(1)
    # usSPCX, hk00700 等非A股，暂不处理
    return None


def _sina_headers() -> dict:
    return {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        'Referer': 'https://i.finance.sina.com.cn/zixuan?from=xzxg_tg',
        'Cookie': SINA_COOKIE,
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }


def _sina_available() -> bool:
    return bool(SINA_COOKIE)


def _parse_jsonp(text: str) -> Optional[dict]:
    """解析 JSONP 响应 (callback(...)) 或纯 JSON"""
    text = text.strip()
    # 去掉防注入前缀
    text = re.sub(r'^/\*.*?\*/\s*', '', text)
    # JSONP: callback({...})
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # 纯 JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def sina_get_self_stock() -> list:
    """获取新浪云端自选股列表
    返回 [{"code": "600519", "scode": "sh600519@cn", "name": "", "market": "sh", "type": "cn"}, ...]
    仅返回 A 股（type=cn），过滤美股/港股/基金
    """
    if not _sina_available():
        raise HTTPException(status_code=500, detail="未配置 SINA_COOKIE，新浪同步未启用")

    # 缓存
    now = time.time()
    if _SINA_CACHE["data"] and now - _SINA_CACHE["ts"] < _SINA_CACHE_TTL:
        return _SINA_CACHE["data"]

    url = f"{SINA_BASE}/HoldV2Service.getAllPySymbolsList?source=pc_mzx&type=all"
    try:
        client = _get_http_client()
        resp = await client.get(url, headers=_sina_headers())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"新浪API请求失败: {str(e)}")

    # 检测重定向（cookie 过期 → passport.weibo.com）
    if resp.status_code in (301, 302):
        loc = resp.headers.get('location', '')
        if 'passport.weibo.com' in loc or 'sso/signin' in loc:
            raise HTTPException(
                status_code=401,
                detail="新浪 cookie 已过期，请在浏览器重新登录 https://finance.sina.com.cn/ 后更新 SINA_COOKIE"
            )

    parsed = _parse_jsonp(resp.text)
    if not parsed:
        raise HTTPException(status_code=502, detail=f"新浪响应解析失败: {resp.text[:200]}")

    status_code = parsed.get('result', {}).get('status', {}).get('code')
    if status_code != 0:
        msg = parsed.get('result', {}).get('status', {}).get('msg', '未知错误')
        raise HTTPException(status_code=400, detail=f"新浪API返回错误: {msg}")

    data_list = parsed.get('result', {}).get('data', [])
    result = []
    for item in data_list:
        if not isinstance(item, dict):
            continue
        scode = item.get('symbol', '')
        stock_type = item.get('type', '')
        # 只返回 A 股
        if stock_type != 'cn':
            continue
        code = _scode_to_code(scode)
        if code:
            result.append({
                "code": code,
                "scode": scode,
                "name": item.get('code', ''),
                "market": item.get('market', ''),
                "type": stock_type,
            })

    _SINA_CACHE["data"] = result
    _SINA_CACHE["ts"] = now
    return result


async def sina_add_stock(code: str) -> dict:
    """添加自选股到新浪云端"""
    if not _sina_available():
        raise HTTPException(status_code=500, detail="未配置 SINA_COOKIE")
    scode = _sina_code_to_scode(code)
    url = f"{SINA_BASE}/HoldV2Service.appendSymbol?scode={scode}&source=pc_mzx&pid="
    try:
        client = _get_http_client()
        resp = await client.get(url, headers=_sina_headers())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"新浪添加请求失败: {str(e)}")

    parsed = _parse_jsonp(resp.text)
    if not parsed:
        raise HTTPException(status_code=502, detail=f"新浪添加响应解析失败: {resp.text[:200]}")

    status_code = parsed.get('result', {}).get('status', {}).get('code')
    msg = parsed.get('result', {}).get('status', {}).get('msg', '')
    if status_code != 0:
        raise HTTPException(status_code=400, detail=f"新浪添加失败({status_code}): {msg}")

    # 清除缓存
    _SINA_CACHE["data"] = None
    return {"success": True, "scode": scode, "msg": msg}


async def sina_delete_stock(code: str) -> dict:
    """从新浪云端删除自选股"""
    if not _sina_available():
        raise HTTPException(status_code=500, detail="未配置 SINA_COOKIE")
    scode = _sina_code_to_scode(code)
    url = f"{SINA_BASE}/HoldV2Service.delSymbolFace?scode={scode}&source=pc_mzx&pid="
    try:
        client = _get_http_client()
        resp = await client.get(url, headers=_sina_headers())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"新浪删除请求失败: {str(e)}")

    parsed = _parse_jsonp(resp.text)
    if not parsed:
        raise HTTPException(status_code=502, detail=f"新浪删除响应解析失败: {resp.text[:200]}")

    status_code = parsed.get('result', {}).get('status', {}).get('code')
    msg = parsed.get('result', {}).get('status', {}).get('msg', '')
    if status_code != 0:
        raise HTTPException(status_code=400, detail=f"新浪删除失败({status_code}): {msg}")

    _SINA_CACHE["data"] = None
    return {"success": True, "scode": scode, "msg": msg}


# ========== 同步逻辑 ==========

async def pull_from_sina_cloud(dry_run: bool = False, mirror: bool = False) -> dict:
    """从新浪拉取自选股到 AIROBOT
    - 默认（mirror=False）：合并去重
    - mirror=True：全局镜像同步，删除所有本地有但新浪云端没有的股票（不限分组）
    """
    sina_list = await sina_get_self_stock()
    sina_codes = {s["code"] for s in sina_list}

    with get_db_session() as db:
        local_all = db.query(Watchlist).all()
        local_codes = {item.stock_code for item in local_all}
        to_add = {c for c in (sina_codes - local_codes) if len(c) == 6 and c.isdigit()}
        # 全局镜像：删除所有本地有但新浪没有的（不限分组）
        to_delete = local_codes - sina_codes if mirror else set()

        if dry_run:
            return {"sina_count": len(sina_codes), "local_count": len(local_codes),
                    "to_add": len(to_add), "to_add_list": sorted(to_add),
                    "to_delete": len(to_delete), "to_delete_list": sorted(to_delete),
                    "mirror": mirror, "dry_run": True}

        added = []
        for code in to_add:
            item = Watchlist(stock_code=code, stock_name="", note="新浪同步", group_name="新浪同步")
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
        return {"success": True, "sina_count": len(sina_codes), "local_count": len(local_codes),
                "added": len(added), "added_list": added, "skipped": len(sina_codes & local_codes),
                "deleted": len(deleted), "deleted_list": deleted, "mirror": mirror}


async def push_to_sina_cloud(dry_run: bool = False, mirror: bool = False) -> dict:
    """把 AIROBOT 自选股推送到新浪云端
    - 默认（mirror=False）：只推送新浪缺失的 A 股
    - mirror=True：同时删除新浪云端有但本地没有的 A 股（镜像同步）
    """
    sina_list = await sina_get_self_stock()
    sina_codes = {s["code"] for s in sina_list}

    with get_db_session() as db:
        local_items = db.query(Watchlist).all()
        local_codes = {item.stock_code for item in local_items}
        to_push = {c for c in (local_codes - sina_codes) if len(c) == 6 and c.isdigit()}
        # 镜像同步：删除云端有但本地没有的
        to_delete = {c for c in (sina_codes - local_codes) if len(c) == 6 and c.isdigit()} if mirror else set()

        if dry_run:
            return {"local_count": len(local_codes), "sina_count": len(sina_codes),
                    "to_push": len(to_push), "to_push_list": sorted(to_push),
                    "to_delete": len(to_delete), "to_delete_list": sorted(to_delete),
                    "mirror": mirror, "dry_run": True}

        pushed, failed = [], []
        for code in to_push:
            try:
                await sina_add_stock(code)
                pushed.append(code)
                time.sleep(0.3)  # 避免请求过快
            except Exception as e:
                failed.append({"code": code, "error": str(e)})
        deleted = []
        for code in to_delete:
            try:
                await sina_delete_stock(code)
                deleted.append(code)
                time.sleep(0.3)
            except Exception as e:
                failed.append({"code": code, "error": str(e)})
        return {"success": True, "local_count": len(local_codes), "sina_count": len(sina_codes),
                "pushed": len(pushed), "pushed_list": pushed,
                "deleted": len(deleted), "deleted_list": deleted,
                "mirror": mirror, "failed": failed}


# ========== REST API 端点 ==========

@router.get("/api/sync/sina/list")
async def get_sina_list():
    """获取新浪云端自选股列表"""
    return await sina_get_self_stock()


@router.post("/api/sync/sina/pull")
async def pull_from_sina(dry_run: bool = Query(False), mirror: bool = Query(True)):
    """从新浪拉取自选股到 AIROBOT（默认镜像同步：删除本地多余的）"""
    return await pull_from_sina_cloud(dry_run, mirror)


@router.post("/api/sync/sina/push")
async def push_to_sina(dry_run: bool = Query(False), mirror: bool = Query(True)):
    """把 AIROBOT 自选股推送到新浪（默认镜像同步：删除云端多余的）"""
    return await push_to_sina_cloud(dry_run, mirror)


@router.get("/api/sync/sina/status")
async def sina_status():
    """新浪同步状态"""
    if not _sina_available():
        return {"connected": False, "reason": "未配置 SINA_COOKIE",
                "help": "请在浏览器登录 https://finance.sina.com.cn/ 后，从开发者工具复制 cookie 到 .env 的 SINA_COOKIE 变量"}
    try:
        lst = await sina_get_self_stock()
        return {"connected": True, "count": len(lst)}
    except HTTPException as e:
        return {"connected": False, "error": e.detail}
    except Exception as e:
        return {"connected": False, "error": str(e)}