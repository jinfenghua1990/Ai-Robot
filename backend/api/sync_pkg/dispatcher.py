"""本地变化 → 云端同步的事件防抖触发器
- trigger_cloud_sync(): 本地新增后防抖 3 秒推送到所有云端
- trigger_cloud_delete(): 本地删除后防抖 3 秒从所有云端删除
- full_sync(): 全量双向同步（供 scheduler.py 调用）
"""
import asyncio
import logging
from datetime import datetime

from .ths import ths_delete_stock, sync_to_ths, sync_from_ths
from .mx import mx_delete_stock, sync_to_mx, sync_from_mx

logger = logging.getLogger(__name__)

_debounce_task = None
_delete_queue = []
_delete_debounce_task = None
DEBOUNCE_SECONDS = 3


async def _push_to_all(reason: str = "change") -> dict:
    """推送到所有已连接平台（best-effort，失败记日志不抛）"""
    results = {}
    try:
        results["push_ths"] = await sync_to_ths()
    except Exception as e:
        results["push_ths"] = {"error": str(e)}
    try:
        results["push_mx"] = await sync_to_mx()
    except Exception as e:
        results["push_mx"] = {"error": str(e)}
    try:
        from api.sina_sync import push_to_sina_cloud
        results["push_sina"] = await push_to_sina_cloud()
    except ImportError:
        results["push_sina"] = {"skipped": "新浪同步未启用"}
    except Exception as e:
        results["push_sina"] = {"error": str(e)}
    results["reason"] = reason
    results["timestamp"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return results


async def _debounced_push(reason: str):
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return
    try:
        await _push_to_all(reason)
    except Exception as e:
        logger.warning(f"防抖推送异常: {e}")


def trigger_cloud_sync(reason: str = "watchlist change"):
    """本地自选股变化后调用：防抖 3 秒后推送到所有云端。"""
    global _debounce_task
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if _debounce_task and not _debounce_task.done():
        _debounce_task.cancel()
    _debounce_task = loop.create_task(_debounced_push(reason))


async def _delete_from_all(code: str, name: str = "") -> dict:
    """从所有云端删除指定股票（best-effort）"""
    results = {}
    try:
        results["ths"] = await ths_delete_stock(code)
    except Exception as e:
        results["ths"] = {"error": str(e)}
    try:
        results["mx"] = await mx_delete_stock(name or code)
    except Exception as e:
        results["mx"] = {"error": str(e)}
    try:
        from api.sina_sync import sina_delete_stock
        results["sina"] = await sina_delete_stock(code)
    except ImportError:
        results["sina"] = {"skipped": "新浪未启用"}
    except Exception as e:
        results["sina"] = {"error": str(e)}
    return results


async def _debounced_delete():
    global _delete_queue
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return
    queue = _delete_queue[:]
    _delete_queue = []
    for code, name in queue:
        try:
            await _delete_from_all(code, name)
        except Exception as e:
            logger.warning(f"云端删除异常 {code}: {e}")


def trigger_cloud_delete(code: str, name: str = ""):
    """本地删除自选股后调用：防抖 3 秒后从所有云端删除该股票。"""
    global _delete_debounce_task, _delete_queue
    _delete_queue.append((code, name))
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return
    if _delete_debounce_task and not _delete_debounce_task.done():
        _delete_debounce_task.cancel()
    _delete_debounce_task = loop.create_task(_debounced_delete())


async def full_sync(mirror_push: bool = True) -> dict:
    """全量双向同步"""
    results = {}
    try:
        results["pull_ths"] = await sync_from_ths()
    except Exception as e:
        results["pull_ths"] = {"error": str(e)}
    try:
        results["pull_mx"] = await sync_from_mx()
    except Exception as e:
        results["pull_mx"] = {"error": str(e)}
    try:
        results["push_ths"] = await sync_to_ths(mirror=mirror_push)
    except Exception as e:
        results["push_ths"] = {"error": str(e)}
    try:
        results["push_mx"] = await sync_to_mx(mirror=mirror_push)
    except Exception as e:
        results["push_mx"] = {"error": str(e)}
    try:
        from api.sina_sync import pull_from_sina_cloud, push_to_sina_cloud
        try:
            results["pull_sina"] = await pull_from_sina_cloud()
        except Exception as e:
            results["pull_sina"] = {"error": str(e)}
        try:
            results["push_sina"] = await push_to_sina_cloud(mirror=mirror_push)
        except Exception as e:
            results["push_sina"] = {"error": str(e)}
    except ImportError:
        results["sina"] = {"skipped": "新浪同步未启用"}
    results["timestamp"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return results
