"""
Tiger Trade（老虎证券）本地数据 Provider。

数据来源：
- 自选股列表：从 Tiger Trade App 的本地 plist 缓存读取（无需 API key）。
- 持仓/资产数据：需 TigerOpen API（后续扩展，需注册开放平台获取 tiger_id + private_key）。

使用方式：
    from providers.tiger_trade_provider import get_watchlist, get_watchlist_json
    stocks = get_watchlist()       # -> list[dict]
    json_str = get_watchlist_json()  # -> JSON string
"""

import plistlib
import json
import base64
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Tiger Trade 沙盒数据路径模板（用户 ID 需替换）
_TIGER_CONTAINER = Path.home() / "Library/Containers/com.itiger.TigerTrade-Mac"
_USER_DATA_DIR = _TIGER_CONTAINER / "Data/Documents/User"

# 本地副本路径（解决 macOS TCC 阻止 uvicorn 进程读 Container 目录的问题）
_LOCAL_COPY = Path(__file__).resolve().parent.parent / "data" / "tiger_trade_watchlist.plist"

# 市场代码 → AIROBOT 内部标准市场名
_MARKET_MAP = {
    "US": "US",
    "HK": "HK",
    "SH": "CN",
    "SZ": "CN",
}


def _find_account_dir() -> Optional[Path]:
    """自动发现 Tiger Trade 账户目录（形如 4248575659259682）。"""
    if not _USER_DATA_DIR.exists():
        logger.debug(f"Tiger Trade user data dir not found: {_USER_DATA_DIR}")
        return None
    for d in _USER_DATA_DIR.iterdir():
        if d.is_dir() and d.name.isdigit() and len(d.name) > 10:
            plist_file = d / f"{d.name}.plist"
            if plist_file.exists():
                return d
    return None


def _read_plist_path(plist_path: Path) -> Optional[List[Dict]]:
    """从指定 plist 路径解析自选股缓存。"""
    if not plist_path.exists():
        logger.warning(f"plist not found: {plist_path}")
        return None

    try:
        with open(plist_path, "rb") as f:
            root = plistlib.load(f)
    except Exception as e:
        logger.warning(f"Failed to read plist {plist_path}: {e}")
        return None

    # 导航到自选股 tab
    try:
        portfolio = root.get("Default", {}).get(
            "com.itiger.accountAsset.portfolio.cache.key", {}
        )
        tabs = portfolio.get("tabData", {}).get("list", [])
        watchlist_tab = None
        for tab in tabs:
            if tab.get("tabName") == "自选":
                watchlist_tab = tab
                break
        if not watchlist_tab:
            logger.debug("No watchlist tab found in plist")
            return None

        raw = watchlist_tab.get("cacheData", "")
        data = json.loads(base64.b64decode(raw))
        securities = data["data"]["securities"]
    except (KeyError, json.JSONDecodeError, base64.binascii.Error) as e:
        logger.warning(f"Failed to decode watchlist data: {e}")
        return None

    # 标准化格式
    results = []
    for s in securities:
        results.append({
            "symbol": s["symbol"],
            "market": _MARKET_MAP.get(s["market"], s["market"]),
            "market_raw": s["market"],
            "sec_type": s.get("secType", "STK"),
            # 期权扩展字段
            "strike": s.get("strike"),
            "right": s.get("right"),
            "expiry": s.get("expiry"),
        })
    return results


def get_watchlist() -> List[Dict]:
    """
    获取 Tiger Trade 自选股列表。

    返回 list[dict]，每项含 symbol / market / market_raw / sec_type。
    如果数据不可用（Tiger Trade 未安装/未登录/缓存失效），返回空列表。
    """
    # 优先读本地副本（绕过 macOS TCC 限制——uvicorn 进程可能无权访 Container 目录）
    if _LOCAL_COPY.exists():
        result = _read_plist_path(_LOCAL_COPY)
        if result:
            return result

    # Fallback: Container 原始路径
    account_dir = _find_account_dir()
    if not account_dir:
        logger.warning("Tiger Trade account dir not found")
        return []
    plist_path = account_dir / f"{account_dir.name}.plist"
    result = _read_plist_path(plist_path)
    if not result:
        logger.debug("No watchlist data available")
        return []
    return result


def get_watchlist_json() -> str:
    """返回 Tiger Trade 自选股的 JSON 字符串。"""
    stocks = get_watchlist()
    return json.dumps({
        "source": "tiger_trade_local",
        "count": len(stocks),
        "securities": stocks,
    }, ensure_ascii=False, indent=2)


def get_symbols_by_market() -> Dict[str, List[str]]:
    """按市场分组返回 symbol 列表（供选股/扫描用）。"""
    stocks = get_watchlist()
    result: Dict[str, List[str]] = {"US": [], "HK": [], "CN": []}
    for s in stocks:
        mkt = s["market"]
        if mkt in result:
            result[mkt].append(s["symbol"])
    return result


# ---- 测试入口 ----
if __name__ == "__main__":
    import sys

    stocks = get_watchlist()
    if not stocks:
        print("⚠️  Tiger Trade 自选股数据不可用（检查 App 是否安装并登录过）")
        sys.exit(0)

    print(f"✅ 读取到 {len(stocks)} 只自选股：")
    by_mkt = get_symbols_by_market()
    for mkt, syms in by_mkt.items():
        if syms:
            print(f"  {mkt}: {', '.join(syms[:10])}{'...' if len(syms)>10 else ''}")
