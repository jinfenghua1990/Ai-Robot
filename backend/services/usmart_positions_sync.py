"""盈立(uSMART)真实持仓同步服务（只读）

数据流：
  盈立客户端(Electron, CDP 9222) → 页面刷新触发资产接口
    → query-multiAssetAllInfo/v2 / query-account-profit-base-data/v1
    → 解析美股持仓（exchangeType=5 美股 / 52 美股碎股）→ us_real_positions 表

依赖：
  - 盈立客户端以 --remote-debugging-port=9222 启动且已登录
  - websocket-client（系统 Python 已安装）

注意：
  - 同步过程会刷新盈立客户端页面（约 20~30 秒），期间客户端 UI 会闪一下
  - 仅只读展示，不发起任何交易
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

from db.session import get_db_session
from us_quant.repository import USRealPosition
from services.usmart_watchlist_sync import (
    _discover_page_ws,
    _check_login_state,
    _auto_login,
    CDP_PORT,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # 持仓同步需要留痕（全局默认 WARNING 会吞掉 info）

RELOAD_WAIT = 32        # 刷新后等待资产接口响应上限（秒）
RELOAD_POLL = 0.5       # 轮询间隔

# 关注的数据接口（命中即收集响应）
_API_PATTERNS = (
    "query-accountAssetInfoForAE",
    "query-multiAssetAllInfo",
    "query-account-profit-base-data",
)

_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "data", "usmart_positions_status.json")


# ─── CDP 监听采集 ────────────────────────────────────────────────────────

def _collect_asset_responses(ws_url: str, wait: float = RELOAD_WAIT) -> list[dict]:
    """通过 CDP Network 域监听页面刷新后的资产接口响应

    返回: [{"url": str, "body": str}, ...]
    """
    import websocket
    collected: list[dict] = []
    try:
        ws = websocket.create_connection(ws_url, timeout=max(wait + 10, 40))
    except Exception as exc:
        logger.warning("[usmart-pos] CDP 连接失败: %s", exc)
        return collected

    next_id = [1]
    tracked: dict = {}          # requestId -> url
    done = {"asset": False, "multi": False, "profit": False}

    def send(method: str, params: dict = None) -> int:
        next_id[0] += 1
        i = next_id[0]
        ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        return i

    try:
        send("Network.enable")
        time.sleep(0.5)
        # 4.6.x 不再在自选页请求资产接口；先切到客户资产页，再刷新触发
        # query-accountAssetInfoForAE。带时间戳避免当前已经在该路由时不重新加载。
        send("Runtime.evaluate", {
            "expression": "(async function(){var app=document.querySelector('#app');var r=app&&app.__vue__&&app.__vue__.$router;if(r){await r.push({path:'/customerAssetInfo',query:{sync:String(Date.now())}});}})()",
            "awaitPromise": True,
            "returnByValue": True,
        })
        time.sleep(0.8)
        send("Page.reload", {"ignoreCache": True})
        logger.info("[usmart-pos] 已切换客户资产页并刷新，等待资产接口…")

        deadline = time.time() + wait
        while time.time() < deadline:
            # 提前结束：v2（全量持仓）或含美股持仓的 v1 拿到即可。
            # 注意：v1 有多个 exchangeType 变体（0=港股/5=美股/52=碎股），
            # 刷新后先到的往往是 exchangeType=0 的空响应，不能作为完成信号。
            if done["asset"] or done["multi"] or done["profit"]:
                break
            try:
                ws.settimeout(RELOAD_POLL)
                msg = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                # 没有网络事件时只是等待，不要把正常超时误判成页面断线。
                continue
            except Exception:
                # 页面刷新导致连接断开时，重新发现并重建连接
                try:
                    ws.close()
                except Exception:
                    pass
                new_url = _discover_page_ws()
                if not new_url:
                    break
                ws_url = new_url
                ws = websocket.create_connection(ws_url, timeout=max(wait + 10, 40))
                send("Network.enable")
                continue

            mid = msg.get("method")
            params = msg.get("params", {})
            if mid == "Network.requestWillBeSent":
                rid = params.get("requestId")
                url = params.get("request", {}).get("url", "")
                if any(p in url for p in _API_PATTERNS):
                    tracked[rid] = url
            elif mid == "Network.loadingFinished":
                rid = params.get("requestId")
                if rid not in tracked:
                    continue
                url = tracked.pop(rid)
                try:
                    i = send("Network.getResponseBody", {"requestId": rid})
                except Exception:
                    continue
                # 等待 getResponseBody 响应
                for _ in range(50):
                    try:
                        ws.settimeout(3)
                        resp = json.loads(ws.recv())
                    except websocket.WebSocketTimeoutException:
                        break
                    except Exception:
                        break
                    if resp.get("id") == i:
                        body = resp.get("result", {}).get("body", "")
                        if body:
                            collected.append({"url": url, "body": body})
                            if "query-accountAssetInfoForAE" in url:
                                done["asset"] = True
                            elif "query-multiAssetAllInfo" in url:
                                done["multi"] = True
                            elif "query-account-profit-base-data" in url:
                                # v1 仅当响应内含美股持仓（exchangeType 5/52）才算有效
                                try:
                                    payload = json.loads(body)
                                    items = (payload.get("data") or {}).get(
                                        "stockProfitBaseDataResps") or []
                                    if any(_exchange_type(it.get("exchangeType")) in (5, 52)
                                           for it in items):
                                        done["profit"] = True
                                except (ValueError, TypeError):
                                    pass
                        break
        logger.info("[usmart-pos] 监听完成，采集到 %d 个接口响应", len(collected))
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return collected


# ─── 解析 ────────────────────────────────────────────────────────────────

def _parse_positions(responses: list[dict]) -> list[dict]:
    """从资产接口响应解析美股持仓列表

    优先 query-multiAssetAllInfo/v2（一次返回多市场全量），
    其次 query-account-profit-base-data/v1（exchangeType=5/52）。
    仅保留美股（exchangeType 5=美股, 52=美股碎股）。
    """
    raw_items: list[dict] = []
    seen_urls = set()

    for resp in responses:
        url = resp.get("url", "")
        # 注意：v1 同一 URL 会返回多个 exchangeType 变体（0/5/52），
        # 不能按 URL 去重；仅对 v2（全量接口）去重
        if "query-multiAssetAllInfo" in url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        try:
            payload = json.loads(resp.get("body", ""))
        except (ValueError, TypeError):
            continue
        data = payload.get("data") or {}
        items = []
        is_v2 = False
        if "query-multiAssetAllInfo" in url or "query-accountAssetInfoForAE" in url:
            is_v2 = True
            for sv in data.get("assetSingleInfoRespVOS") or []:
                parent_exchange = _exchange_type(sv.get("exchangeType"))
                if parent_exchange is None:
                    parent_exchange = {
                        11: 5,   # USD 美股
                        13: 52,  # USD 碎股
                        30: 0,   # HKD 港股
                        20: 8,   # SGD
                    }.get(_exchange_type(sv.get("appCardType")))
                for hold in sv.get("holdInfos") or []:
                    # 新版接口有些账户卡片不在持仓行重复 exchangeType，
                    # 用父级卡片补齐，避免美股被误过滤。
                    if parent_exchange is not None and hold.get("exchangeType") is None:
                        hold = {**hold, "exchangeType": parent_exchange}
                    items.append(hold)
        elif "query-account-profit-base-data" in url:
            items.extend(data.get("stockProfitBaseDataResps") or [])

        seen_keys = set()
        for it in items:
            ex = _exchange_type(it.get("exchangeType"))
            if ex not in (5, 52):          # 只取美股 / 美股碎股
                continue
            code = str(it.get("code") or it.get("stockCode") or it.get("symbol") or "").strip().upper()
            if not code or code in seen_keys:
                continue
            seen_keys.add(code)
            qty = _f(it.get("curHoldNum") or it.get("currentAmount") or it.get("quantity"))
            if qty <= 0:                   # 过滤空持仓行
                continue
            hold_pct = _f(it.get("holdProfitPercent") or it.get("hold_profit_pct"))
            if hold_pct is not None and abs(hold_pct) <= 1:
                hold_pct *= 100
            raw_items.append({
                "symbol": code,
                "name": it.get("name") or it.get("stockName") or it.get("securityName"),
                "exchange_type": ex,
                "fund_account": it.get("fundAccount") or it.get("fundAccountNo"),
                "quantity": qty,
                "cost_price": _f(it.get("costPrice") or it.get("cost_price")),
                "last_price": _f(it.get("lastPrice") or it.get("last_price")),
                "pre_close": _f(it.get("preClose") or it.get("pre_close")),
                "market_value": _f(it.get("marketValue") or it.get("market_value")),
                "hold_profit": _f(it.get("holdProfit") or it.get("hold_profit")),
                "hold_profit_pct": hold_pct,
                "today_profit": _f(it.get("todayProfit") or it.get("today_profit")),
                "hold_info_id": str(it.get("id") or it.get("holdInfoId") or ""),
                "_from_v2": is_v2,
            })
    # 同代码去重：query-multiAssetAllInfo（v2）优先
    best: dict = {}
    for item in raw_items:
        sym = item["symbol"]
        v2 = item.pop("_from_v2", False)
        if sym not in best or v2:
            best[sym] = item
    return list(best.values())


def _exchange_type(value) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _f(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ─── 数据库写入 ──────────────────────────────────────────────────────────

def sync_us_positions(positions: list[dict]) -> int:
    """写入 us_real_positions（幂等 upsert，旧持仓标记 CLOSED）

    注意：positions 允许为空列表——空列表会把所有 ACTIVE 持仓标记为 CLOSED，
    用于用户清仓后清理旧持仓；调用方只在采集成功时调用本函数。
    """
    now = datetime.now()
    symbols = [p["symbol"] for p in positions]
    with get_db_session() as db:
        # 本次未出现的旧持仓 → CLOSED（symbols 为空时 NOT IN () 恒真，全部标记）
        db.query(USRealPosition).filter(
            USRealPosition.symbol.notin_(symbols),
            USRealPosition.status == "ACTIVE",
        ).update({"status": "CLOSED", "synced_at": now}, synchronize_session=False)
        for p in positions:
            row = db.query(USRealPosition).filter(
                USRealPosition.symbol == p["symbol"]).first()
            if not row:
                row = USRealPosition(symbol=p["symbol"], status="ACTIVE")
                db.add(row)
            row.name = p.get("name") or row.name
            row.exchange_type = p.get("exchange_type", 5)
            row.fund_account = p.get("fund_account")
            row.quantity = p.get("quantity")
            row.cost_price = p.get("cost_price")
            row.last_price = p.get("last_price")
            row.pre_close = p.get("pre_close")
            row.market_value = p.get("market_value")
            row.hold_profit = p.get("hold_profit")
            row.hold_profit_pct = p.get("hold_profit_pct")
            row.today_profit = p.get("today_profit")
            row.hold_info_id = p.get("hold_info_id")
            row.status = "ACTIVE"
            row.synced_at = now
        db.commit()
    logger.info("[usmart-pos] 持仓写入完成: %d 只", len(positions))
    return len(positions)


# ─── 状态记录 ────────────────────────────────────────────────────────────

def _save_status(payload: dict):
    try:
        os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("[usmart-pos] 状态保存失败: %s", exc)


def get_last_status() -> dict:
    try:
        if os.path.exists(_STATUS_FILE):
            with open(_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"ok": False, "error": "尚未同步过盈立持仓"}


# ─── 总入口 ──────────────────────────────────────────────────────────────

_SYNC_LOCK = threading.Lock()


def _has_auth_error(responses: list[dict]) -> bool:
    """判断资产接口是否返回未登录/缺少用户身份，而不是空仓。"""
    markers = ("userid 不能为空", "user id", "未登录", "登录失效", "请登录")
    for response in responses:
        if "query-accountAssetInfoForAE" not in response.get("url", ""):
            continue
        try:
            payload = json.loads(response.get("body", ""))
        except (TypeError, ValueError):
            continue
        message = " ".join(str(payload.get(key) or "") for key in ("error", "msg")).lower()
        if any(marker in message for marker in markers):
            return True
    return False


def run_sync() -> dict:
    """同步盈立真实美股持仓 → us_real_positions（带并发锁，防止手动+定时重叠触发）

    返回: {"ok": bool, "count": int, "positions": [...], "synced_at": str}
    """
    if not _SYNC_LOCK.acquire(blocking=False):
        return {"ok": False,
                "error": "已有同步任务正在进行，请稍候再试",
                "count": 0, "positions": [],
                "synced_at": datetime.now().isoformat()}
    try:
        return _run_sync_locked()
    finally:
        _SYNC_LOCK.release()


def _run_sync_locked() -> dict:
    started = datetime.now()
    ws_url = _discover_page_ws()
    if not ws_url:
        result = {"ok": False, "error": f"未发现盈立调试页面（127.0.0.1:{CDP_PORT}）",
                  "count": 0, "positions": [], "synced_at": started.isoformat()}
        _save_status(result)
        return result

    login_state = _check_login_state(ws_url)
    login_status = "logged_in"
    if login_state == "login_page":
        relogin = _auto_login(ws_url)
        if not relogin.get("ok"):
            result = {"ok": False,
                      "error": relogin.get("error", "自动重登失败"),
                      "login": relogin.get("status", "failed"),
                      "count": 0, "positions": [],
                      "synced_at": started.isoformat()}
            _save_status(result)
            return result
        login_status = "relogin_ok"
        ws_url = _discover_page_ws() or ws_url

    responses = _collect_asset_responses(ws_url)
    # 登录态检测可能早于盈立用户信息初始化；以资产接口的明确错误为准，
    # 只重登一次，避免把“真实空仓”误判成同步失败或陷入重试循环。
    if _has_auth_error(responses) and login_status != "relogin_ok":
        relogin = _auto_login(_discover_page_ws() or ws_url)
        if not relogin.get("ok"):
            result = {
                "ok": False,
                "error": relogin.get("error", "盈立登录已失效，请重新登录"),
                "login": relogin.get("status", "failed"),
                "count": 0,
                "positions": [],
                "source": "cdp",
                "synced_at": started.isoformat(),
            }
            _save_status(result)
            return result
        login_status = "relogin_ok"
        ws_url = _discover_page_ws() or ws_url
        responses = _collect_asset_responses(ws_url)

    positions = _parse_positions(responses)
    auth_error = _has_auth_error(responses)
    # 只有拿到明确的资产响应且认证有效时才写库。认证错误的响应不能
    # 被当成“空仓”，否则会把已有活动持仓误标记为 CLOSED。
    # 认证有效的空资产响应仍会写库，用于反映用户确实已清仓。
    valid_response = bool(responses) and not auth_error
    count = sync_us_positions(positions) if valid_response else 0

    result = {
        "ok": valid_response,
        "count": count,
        "positions": positions,
        "login": login_status,
        "source": "cdp",
        "synced_at": started.isoformat(),
    }
    if not responses:
        result["error"] = "未从盈立客户端采集到资产接口响应（可能客户端离线或同步超时）"
    elif auth_error:
        result["ok"] = False
        result["error"] = "盈立登录状态无效，请在客户端完成登录后重试"
    elif not positions:
        result["error"] = "盈立客户端暂无美股持仓"
    _save_status(result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    print(json.dumps(run_sync(), ensure_ascii=False, indent=2))
