"""
emdatah5 实时资金流采集器
数据源：emdatah5.eastmoney.com/dc/ZJLX/getZJLXData
- 盘中实时（09:30-15:00），秒级响应
- 字段：主力/散户 买入/卖出/净额 + 换手率
- 缓存到 stock_money_flow_realtime 表
"""
import logging
import time
import random
from datetime import datetime, date, time as dtime
from typing import Optional

import requests

from db.session import get_db_session
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ========== 配置 ==========
EM_DATAH5_URL = "https://emdatah5.eastmoney.com/dc/ZJLX/getZJLXData"
FIELDS = "f57,f58,f86,f135,f136,f137,f138,f139,f140"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA, "Referer": "https://emdatah5.eastmoney.com/dc/zjlx/stock"})

# 限流
_em_last_call = [0.0]
EM_MIN_INTERVAL = 0.5  # 500ms


def _em_get(url: str, params: dict = None, timeout: int = 10, headers: dict = None) -> requests.Response:
    """带限流的 emdatah5 GET 请求（headers 可临时覆盖，用于不同子域）"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.05, 0.15))
    r = EM_SESSION.get(url, params=params, timeout=timeout, headers=headers)
    _em_last_call[0] = time.time()
    return r


def _secid(code: str) -> str:
    """6位股票代码 → secid 格式"""
    return f"1.{code}" if code.startswith("6") else f"0.{code}"


def fetch_realtime_fund_flow(code: str) -> Optional[dict]:
    """
    获取个股实时资金流
    code: 6位股票代码 (如 '002245')
    返回: {
        'ts_code': '002245.SZ',
        'name': '蔚蓝锂芯',
        'main_buy': 928061344,    # 主力买入(元)
        'main_sell': 838408928,   # 主力卖出(元)
        'main_net': 89652416,     # 主力净额(元)
        'retail_buy': 274793920,  # 散户买入(元)
        'retail_sell': 285236944, # 散户卖出(元)
        'retail_net': -10443024,  # 散户净额(元)
        'turnover': 1783582473,   # 换手率相关
    } or None
    """
    try:
        resp = _em_get(EM_DATAH5_URL, params={
            "secid": _secid(code),
            "fields": FIELDS,
        })
        data = resp.json().get("data")
        if not data:
            return None

        market = "SH" if code.startswith("6") else "SZ"
        def _f(v):
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0
        return {
            "ts_code": f"{code}.{market}",
            "name": data.get("f58", ""),
            "main_buy": _f(data.get("f135")),
            "main_sell": _f(data.get("f136")),
            "main_net": _f(data.get("f137")),
            "retail_buy": _f(data.get("f138")),
            "retail_sell": _f(data.get("f139")),
            "retail_net": _f(data.get("f140")),
            "turnover": _f(data.get("f86")),
        }
    except Exception as e:
        logger.warning(f"[emdatah5] fetch {code} failed: {e}")
        return None


def save_realtime_snapshot(code: str) -> bool:
    """获取并保存某只股票的实时资金流快照

    每次调用INSERT一条新记录 → 数据在数据库中持续沉淀积累。
    可通过 (ts_code, trade_date, snapshot_time) 查询历史分钟级走势。
    """
    flow = fetch_realtime_fund_flow(code)
    if not flow:
        return False

    now = datetime.now()

    with get_db_session() as db:
        db.execute(text("""
            INSERT INTO stock_money_flow_realtime
                (trade_date, ts_code, name, snapshot_time,
                 main_buy, main_sell, main_net,
                 retail_buy, retail_sell, retail_net, turnover, source)
            VALUES
                (:td, :ts, :nm, :now,
                 :mb, :ms, :mn, :rb, :rs, :rn, :to, :src)
        """), {
            "td": now.date(), "ts": flow["ts_code"], "nm": flow["name"],
            "now": now,
            "mb": flow["main_buy"], "ms": flow["main_sell"], "mn": flow["main_net"],
            "rb": flow["retail_buy"], "rs": flow["retail_sell"], "rn": flow["retail_net"],
            "to": flow["turnover"], "src": "emdatah5",
        })
        db.commit()

    return True


def batch_save_realtime(stock_codes: list, on_progress=None) -> dict:
    """批量获取并保存多只股票的快照。

    on_progress(done, total): 可选回调，每处理完一只调用一次，用于上报进度。
    """
    result = {"success": 0, "failed": 0, "total": len(stock_codes)}
    done = 0
    for code in stock_codes:
        if not code or len(code) != 6:
            result["failed"] += 1
            done += 1
            if on_progress:
                on_progress(done, result["total"])
            continue
        ok = save_realtime_snapshot(code)
        if ok:
            result["success"] += 1
        else:
            result["failed"] += 1
        done += 1
        if on_progress:
            on_progress(done, result["total"])
    return result


# 东财全市场资金流排行榜接口（单次请求返回排序后的 N 只，极轻量）
MARKET_RANK_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def fetch_market_capital_ranking(rank_type: str = "inflow", top_n: int = 100) -> dict:
    """全市场资金流排行（东财批量排行榜接口，1 次请求）。

    rank_type:
        'inflow'  = 主力净流入前 top_n（po=1 降序）
        'outflow' = 主力净流出前 top_n（po=0 升序，即净流入最小）
    返回: {updated_at, type, total_market, items:[{code,name,price,pct,main_net,main_net_pct}]}
    """
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"  # 全部 A 股（沪A/深A/北交）
    fields = "f12,f14,f2,f3,f62,f184"
    # po=1 降序（净流入最大），po=0 升序（净流入最小=净流出最大）
    po = 0 if rank_type == "outflow" else 1
    params = {
        "fs": fs, "fields": fields, "fid": "f62",
        "po": po, "pz": top_n, "pn": 1, "np": 1,
    }
    try:
        # push2 子域需要 data.eastmoney.com 的 Referer，否则会被掐连接
        # 复用 EM_SESSION（已验证可稳定经代理访问东财），并加重试规避代理偶发抖动
        rank_headers = {
            "Referer": "https://data.eastmoney.com/stock/zjlx.html",
            "Accept": "*/*",
        }
        resp = None
        last_err = None
        for attempt in range(4):
            try:
                resp = _em_get(MARKET_RANK_URL, params=params, timeout=15, headers=rank_headers)
                resp.raise_for_status()
                break
            except Exception as e:
                last_err = e
                time.sleep(0.8 + attempt * 0.6)
        if resp is None:
            raise last_err or RuntimeError("ranking request failed")
        data = resp.json().get("data") or {}
        diff = data.get("diff") or []
        # diff 可能是 dict({"0":{...}}) 也可能是 list([{...}])，两种都兼容
        seq = diff.values() if isinstance(diff, dict) else (diff if isinstance(diff, list) else [])
        items = []
        for v in seq:
            f2 = v.get("f2")
            f3 = v.get("f3")
            f62 = v.get("f62")
            f184 = v.get("f184")
            items.append({
                "code": v.get("f12"),
                "name": v.get("f14"),
                # 原始值单位为 分 / 万分之一 / 元，这里转成可读数值
                "price": round(f2 / 100, 2) if isinstance(f2, (int, float)) else None,
                "pct": round(f3 / 100, 2) if isinstance(f3, (int, float)) else None,
                "main_net": f62 if isinstance(f62, (int, float)) else None,
                "main_net_pct": round(f184 / 100, 2) if isinstance(f184, (int, float)) else None,
            })
        return {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": rank_type,
            "total_market": data.get("total"),
            "items": items,
        }
    except Exception as e:
        logger.error(f"[emdatah5] 全市场资金流排行获取失败: {e}")
        return {"updated_at": None, "type": rank_type, "total_market": None, "items": [], "error": str(e)}


def is_trading_time() -> bool:
    """判断当前是否在交易时段 (09:30-15:00)"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.time()
    return dtime(9, 30) <= t <= dtime(15, 0)
