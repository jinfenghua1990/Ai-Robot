"""
US Quant System 股票池 V2.2 — 分层池定义 + 数据库优先查询

V2.2: 数据库 universe_definitions / universe_memberships 为唯一真相源。
内存定义作为启动期兜底（无 DB 时）。
"""
from __future__ import annotations

from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 兜底内存定义（无 DB 连接时使用）
# ═══════════════════════════════════════════════════════════════

UNIVERSE_DEFINITIONS: dict[str, dict] = {
    "US_MARKET_ETF": {"code": "US_MARKET_ETF", "name": "市场与行业 ETF", "target_count": 24, "rebalance_frequency": "manual", "tier": "market"},
    "US_CORE_A": {"code": "US_CORE_A", "name": "核心 A 池", "target_count": 300, "rebalance_frequency": "monthly", "tier": "core"},
    "US_CORE_B": {"code": "US_CORE_B", "name": "核心 B 池", "target_count": 500, "rebalance_frequency": "monthly", "tier": "core"},
    "US_RESEARCH": {"code": "US_RESEARCH", "name": "动态研究池", "target_count": 1500, "rebalance_frequency": "daily", "tier": "research"},
    "US_EVENT": {"code": "US_EVENT", "name": "事件池", "target_count": None, "rebalance_frequency": "intraday", "tier": "event"},
    "US_REALTIME": {"code": "US_REALTIME", "name": "实时监控池", "target_count": 80, "rebalance_frequency": "intraday", "tier": "realtime"},
    "US_WATCHLIST": {"code": "US_WATCHLIST", "name": "US 自选池", "target_count": None, "rebalance_frequency": "manual", "tier": "watchlist"},
}

# ═══════════════════════════════════════════════════════════════
# 数据库连接辅助
# ═══════════════════════════════════════════════════════════════

def _db_conn():
    """返回 (session, close_fn)，无 DB 时返回 (None, None)。"""
    try:
        from db.session import SessionLocal
        s = SessionLocal()
        return s, s.close
    except Exception:
        return None, None


def _exec(session, query: str, params: dict = None):
    from sqlalchemy import text
    return session.execute(text(query), params or {})


# ═══════════════════════════════════════════════════════════════
# 公共 API
# ═══════════════════════════════════════════════════════════════

def _db_list_universes(session) -> list[dict]:
    rows = _exec(session, """SELECT universe_code, name, description, target_count, rebalance_frequency, rules
        FROM universe_definitions WHERE is_active ORDER BY universe_code""").fetchall()
    result = []
    for r in rows:
        cnt = _exec(session, "SELECT COUNT(*) FROM universe_memberships WHERE universe_code=:c AND effective_to IS NULL", {"c": r[0]}).scalar()
        result.append({"code": r[0], "name": r[1], "description": r[2], "target_count": r[3],
                        "rebalance_frequency": r[4], "rules": r[5] or {}, "current_count": cnt or 0,
                        "tier": "core" if "CORE" in (r[0] or "") else "research"})
    return result


def _db_fetch_members(session, code: str) -> list[str]:
    rows = _exec(session, """SELECT i.symbol FROM instruments i
        JOIN universe_memberships um ON um.instrument_id = i.id
        WHERE um.universe_code = :c AND um.effective_to IS NULL ORDER BY um.rank NULLS LAST, i.symbol""", {"c": code}).fetchall()
    return [r[0] for r in rows]


def list_universes() -> list[dict]:
    s, close = _db_conn()
    if s:
        try:
            return _db_list_universes(s)
        except Exception as e:
            logger.warning(f"universe DB: {e}")
        finally:
            close()
    return [{"code": k, "name": v["name"], "target_count": v["target_count"],
             "rebalance_frequency": v["rebalance_frequency"], "tier": v["tier"],
             "current_count": 0} for k, v in UNIVERSE_DEFINITIONS.items()]


def get_universe(code: str) -> Optional[dict]:
    code = code.upper()
    s, close = _db_conn()
    if s:
        try:
            for d in _db_list_universes(s):
                if d["code"] == code:
                    d["members"] = _db_fetch_members(s, code)
                    d["current_count"] = len(d["members"])
                    return d
        except Exception:
            pass
        finally:
            close()
    v = UNIVERSE_DEFINITIONS.get(code)
    return {**v, "current_count": 0, "members": []} if v else None


def get_universe_members(code: str) -> list[str]:
    code = code.upper()
    s, close = _db_conn()
    if s:
        try:
            m = _db_fetch_members(s, code)
            if m:
                return m
        except Exception:
            pass
        finally:
            close()
    return []


def uniques_for_scanner(pool_codes: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for c in pool_codes:
        for sym in get_universe_members(c):
            if sym not in seen:
                seen.add(sym)
                result.append(sym)
    return result


def pool_stats() -> dict:
    s, close = _db_conn()
    if s:
        try:
            rows = _exec(s, """SELECT d.universe_code, d.name, d.target_count FROM universe_definitions d""").fetchall()
            stats = {}
            for r in rows:
                cnt = _exec(s, "SELECT COUNT(*) FROM universe_memberships WHERE universe_code=:c AND effective_to IS NULL", {"c": r[0]}).scalar()
                stats[r[0]] = {"name": r[1], "target": r[2], "current": cnt or 0, "tier": "core" if "CORE" in (r[0] or "") else "research"}
            return stats
        except Exception:
            pass
        finally:
            close()
    return {k: {"name": v["name"], "target": v["target_count"], "current": 0, "tier": v["tier"]} for k, v in UNIVERSE_DEFINITIONS.items()}


def get_scanner_limit(universe_code: str) -> int:
    limits = {"US_CORE_A": 60, "US_CORE_B": 100, "US_RESEARCH": 50, "US_MARKET_ETF": 24, "US_EVENT": 20,
              "CORE_A": 60, "CORE_B": 100, "RESEARCH_DYNAMIC": 50, "MARKET_ETF": 24, "EVENT": 20}
    return limits.get(universe_code.upper(), 50)
