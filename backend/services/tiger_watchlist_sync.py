"""老虎证券(Tiger Trade)自选股同步服务

数据流：
  Tiger Trade 本地 plist → providers/tiger_trade_provider → DB(US_WATCHLIST / HK_WATCHLIST)

与盈立共用同一个 stock pool（US_WATCHLIST / HK_WATCHLIST），
两个来源的自选股在同一池中合并展示。

依赖：Tiger Trade App 需在本机至少登录过一次（生成 plist 缓存）。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from providers.tiger_trade_provider import get_watchlist
from db.session import get_db_session
from market_quant.repository import MarketInstrument, MarketUniverseMembership
from us_quant.repository import USInstrument, USUniverseMembership

logger = logging.getLogger(__name__)

US_WATCHLIST_CODE = "US_WATCHLIST"
HK_WATCHLIST_CODE = "HK_WATCHLIST"

_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "data", "tiger_sync_status.json")


# ─── DB 写入（复用盈立的 stock pool，来源标记区分）──────

def _sync_us_stocks(codes: list[str]) -> int:
    """美股自选 → us_instruments + US_WATCHLIST（幂等）"""
    codes = list(dict.fromkeys(c.strip().upper() for c in codes if c.strip()))  # 去重保序
    if not codes:
        return 0
    now = datetime.now()
    with get_db_session() as db:
        existing = {inst.symbol for inst in
                    db.query(USInstrument.symbol).filter(USInstrument.symbol.in_(codes)).all()}
        for code in codes:
            if code not in existing:
                db.add(USInstrument(symbol=code, is_active=True,
                                    universe_source="tiger_watchlist",
                                    created_at=now, updated_at=now))
        # 不清空整个池，只更新 tiger 来源的 membership（维持盈立的记录）
        db.query(USUniverseMembership).filter(
            USUniverseMembership.universe_code == US_WATCHLIST_CODE,
            USUniverseMembership.source == "tiger_watchlist",
        ).delete(synchronize_session=False)
        for rank, code in enumerate(codes, start=1):
            db.add(USUniverseMembership(
                symbol=code, universe_code=US_WATCHLIST_CODE, tier="WATCH",
                rank=rank, effective_from=now,
                inclusion_reason="老虎自选同步", source="tiger_watchlist",
                config_version="v1",
            ))
        db.commit()
    logger.info("[tiger] 美股自选写入完成: %d 只", len(codes))
    return len(codes)


def _sync_hk_stocks(codes: list[str]) -> int:
    """港股自选 → market_instruments + HK_WATCHLIST（幂等）"""
    codes = list(dict.fromkeys(c.strip().upper() for c in codes if c.strip()))
    if not codes:
        return 0
    now = datetime.now()
    with get_db_session() as db:
        existing = set(
            (inst.symbol, inst.market) for inst in
            db.query(MarketInstrument.symbol, MarketInstrument.market)
            .filter(MarketInstrument.market == "HK",
                    MarketInstrument.symbol.in_(codes))
            .all()
        )
        for code in codes:
            if (code, "HK") not in existing:
                db.add(MarketInstrument(
                    market="HK", symbol=code, provider_symbol=code,
                    exchange="HKEX", is_active=True, is_etf=False,
                    source="tiger_watchlist", created_at=now,
                ))
        db.query(MarketUniverseMembership).filter(
            MarketUniverseMembership.market == "HK",
            MarketUniverseMembership.universe_code == HK_WATCHLIST_CODE,
            MarketUniverseMembership.source == "tiger_watchlist",
        ).delete(synchronize_session=False)
        for rank, code in enumerate(codes, start=1):
            db.add(MarketUniverseMembership(
                market="HK", universe_code=HK_WATCHLIST_CODE, symbol=code,
                tier="WATCH", rank=rank, effective_from=now,
                inclusion_reason="老虎自选同步", source="tiger_watchlist",
                config_version="v1",
            ))
        db.commit()
    logger.info("[tiger] 港股自选写入完成: %d 只", len(codes))
    return len(codes)


# ─── 状态记录 ──────────────────────────────────────────────────────────

def _save_status(payload: dict):
    try:
        os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("[tiger] 状态保存失败: %s", exc)


def get_last_status() -> dict:
    try:
        if os.path.exists(_STATUS_FILE):
            with open(_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"ok": False, "error": "尚未同步过"}


# ─── 总入口 ────────────────────────────────────────────────────────────

def run_sync(markets: str = "US,HK") -> dict:
    """同步 Tiger Trade 自选 → 9000 股票池

    Args:
        markets: 逗号分隔，可选 US / HK，默认都同步
    """
    started = datetime.now()

    # 读 Tiger Trade 本地自选股
    stocks = get_watchlist()
    if not stocks:
        result = {
            "ok": False,
            "error": "Tiger Trade 自选股数据不可用（请确认 App 已安装并登录过）",
            "US": 0, "HK": 0,
            "synced_at": started.isoformat(),
        }
        _save_status(result)
        return result

    # 按市场分组
    us_codes: list[str] = []
    hk_codes: list[str] = []
    for s in stocks:
        mkt = s["market"]
        if mkt == "US":
            us_codes.append(s["symbol"])
        elif mkt == "HK":
            hk_codes.append(s["symbol"])
        # CN (A股) 暂不同步（需要 CN_WATCHLIST 池）

    wanted = {m.strip().upper() for m in markets.split(",") if m.strip()}
    wanted &= {"US", "HK"}
    if not wanted:
        wanted = {"US", "HK"}

    result = {
        "ok": True,
        "source": "tiger_trade_local",
        "synced_at": started.isoformat(),
    }

    if "US" in wanted:
        result["US"] = {"count": _sync_us_stocks(us_codes)}
    if "HK" in wanted:
        result["HK"] = {"count": _sync_hk_stocks(hk_codes)}

    logger.info("[tiger] 同步完成: US=%s HK=%s", result.get("US"), result.get("HK"))
    _save_status(result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    print(json.dumps(run_sync(), ensure_ascii=False, indent=2))
