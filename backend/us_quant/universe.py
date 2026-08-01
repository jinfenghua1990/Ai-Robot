"""美股股票池服务（类似 A 股 stock_universe，全量研究池 + 核心 A/B 池动态管理）

数据流：
  东财 clist API → 筛选 → USInstrument 表（全量研究池）
                                ↓
                         核心 A 池 300 只 + 核心 B 池 500 只
                                ↓
                         策略扫描 / 回测 / 信号生成（从 DB 读取）

功能：
  - 导入 179 只种子股 + ETF
  - 从东财动态拉取全量美股并筛选
  - Core A (300) / Core B (500) 评分排名
  - 每日有效性检查 + 每月重平衡
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from db.session import get_db_session
from sqlalchemy import func, and_, or_, not_

from us_quant.repository import (
    USInstrument, USUniverseMembership, USUniverseRebalanceRun,
)

logger = logging.getLogger(__name__)

# ─── 配置 ──────────────────────────────────────────────────────────────────

CONFIG_VERSION = "v2.0.0"

# 核心 A 池配置
CORE_A_CONFIG = {
    "target_count": 300,
    "min_price": 10.0,
    "min_market_cap": 2_000_000_000,      # 20亿美元
    "min_avg_dollar_volume": 100_000_000,  # 1亿美元
    "min_listing_days": 250,
    "max_spread_pct": 0.002,
    "max_sector_pct": 0.30,               # 单行业最大占比
}

# 核心 B 池配置
CORE_B_CONFIG = {
    "target_count": 500,
    "min_price": 7.0,
    "min_market_cap": 1_000_000_000,      # 10亿美元
    "min_avg_dollar_volume": 50_000_000,  # 5000万美元
    "min_listing_days": 180,
    "max_spread_pct": 0.0025,
    "max_sector_pct": 0.25,
}

# 研究池硬门槛
RESEARCH_CONFIG = {
    "min_price": 5.0,
    "min_market_cap": 500_000_000,        # 5亿美元
    "min_avg_dollar_volume": 30_000_000,  # 3000万美元
    "min_listing_days": 120,
    "max_spread_pct": 0.003,
}

# 重平衡缓冲区（避免频繁进出）
REBALANCE_BUFFER = {
    "core_a_keep_rank": 360,     # 现有 A 池股票排名 <= 360 可保留
    "core_a_new_entry_rank": 280, # 新入 A 池需要排名 <= 280
    "core_b_keep_rank": 900,     # 现有 B 池股票排名 <= 900 可保留
    "core_b_new_entry_rank": 760, # 新入 B 池需要排名 <= 760
}

# ─── 股票池代码 ────────────────────────────────────────────────────────────

UNIVERSE_CODES = {
    "MARKET_ETF": "市场与行业ETF",
    "SEED_CORE_179": "179只初始化种子",
    "RESEARCH_DYNAMIC": "动态研究池",
    "CORE_A_300": "核心A池",
    "CORE_B_500": "核心B池",
}

# ─── ETF 列表（大盘 + 行业 + 风险观察）────────────────────────────────────

MARKET_ETF_TICKERS = [
    "SPY", "QQQ", "IWM", "RSP", "DIA",
    "XLK", "SMH", "SOXX", "XLC", "XLY", "XLF", "XLI", "XLV", "XLE", "XLB", "XLP", "XLU", "XLRE",
    "VIXY", "TLT", "HYG",
]

# ─── 179 只种子股（来自文档附录 B）────────────────────────────────────────

SEED_CORE_TICKERS = [
    'MSFT', 'AAPL', 'ORCL', 'CRM', 'NOW', 'PLTR', 'ADBE', 'INTU', 'PANW', 'CRWD',
    'DDOG', 'NET', 'SNOW', 'MDB', 'APP', 'ANET', 'DELL', 'HPE', 'IBM', 'CSCO',
    'NVDA', 'AVGO', 'AMD', 'MU', 'AMAT', 'LRCX', 'KLAC', 'QCOM', 'MRVL', 'INTC',
    'ARM', 'TSM', 'ASML', 'SMCI', 'VRT', 'COHR',
    'META', 'GOOGL', 'GOOG', 'NFLX', 'AMZN', 'UBER', 'ABNB', 'DASH', 'SPOT', 'RDDT',
    'PINS', 'SNAP', 'RBLX', 'EA', 'TTWO', 'DIS', 'TMUS', 'T', 'VZ',
    'TSLA', 'HD', 'LOW', 'NKE', 'MCD', 'SBUX', 'BKNG', 'MAR', 'RCL', 'CCL',
    'GM', 'F', 'RIVN', 'TGT', 'TJX', 'CMG', 'YUM', 'ORLY', 'AZO', 'ROST',
    'JPM', 'BAC', 'WFC', 'C', 'GS', 'MS', 'V', 'MA', 'AXP', 'COF',
    'SCHW', 'BLK', 'BX', 'KKR', 'HOOD', 'COIN', 'CME', 'ICE', 'SPGI', 'MCO',
    'GE', 'GEV', 'CAT', 'DE', 'BA', 'RTX', 'LMT', 'NOC', 'GD', 'ETN',
    'PH', 'HON', 'UNP', 'UPS', 'FDX', 'URI', 'PWR', 'CARR', 'TT', 'EMR',
    'LLY', 'UNH', 'JNJ', 'ABBV', 'MRK', 'AMGN', 'GILD', 'TMO', 'DHR', 'ISRG',
    'BSX', 'MDT', 'SYK', 'REGN', 'VRTX', 'MRNA', 'BMY', 'CVS', 'CI', 'HCA',
    'XOM', 'CVX', 'COP', 'OXY', 'EOG', 'DVN', 'SLB', 'HAL', 'MPC', 'VLO',
    'LNG', 'FANG', 'FCX', 'NEM', 'NUE', 'STLD', 'AA', 'CCJ',
    'WMT', 'COST', 'PG', 'KO', 'PEP', 'PM', 'MO', 'MDLZ', 'CL', 'MNST', 'KHC', 'KR',
    'NEE', 'CEG', 'VST', 'SO', 'DUK', 'AEP', 'SRE', 'EXC', 'DLR', 'AMT', 'PLD', 'EQIX', 'O', 'SPG',
]


# ====================================================================
# 工具函数
# ====================================================================

def _now() -> datetime:
    return datetime.now()


def _today() -> date:
    return date.today()


# ====================================================================
# 全量研究池拉取（东财 clist API）
# ====================================================================

def fetch_research_universe_from_eastmoney() -> list[dict]:
    """从东财 clist API 拉取 NASDAQ + NYSE 股票列表（分页，按市值降序）

    返回格式：[{symbol, name, price, market_cap, volume, exchange, ...}]

    NOTE: 东财 push2 API 在本机网络环境可能不通，
          失败时返回空列表，由调用方决定是否降级。
    """
    try:
        from services.research.astock import em_get
    except ImportError:
        logger.warning("[universe] astock.em_get 不可用，跳过东财拉取")
        return []

    all_stocks = []
    page = 1
    page_size = 500
    max_pages = 20  # 最多拉 10000 只（安全上限）

    params_base = {
        "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f20",  # 按市值排序
        "fs": "m:1 t:2,m:1 t:3",  # NASDAQ + NYSE
        "fields": "f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18,f20,f21",
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    for page in range(1, max_pages + 1):
        params = dict(params_base)
        params["pn"] = page
        params["pz"] = page_size
        try:
            r = em_get("https://push2.eastmoney.com/api/qt/clist/get",
                       params=params, headers=headers, timeout=15)
            data = r.json().get("data")
            if not data:
                break
            diff = data.get("diff") or []
            if not diff:
                break
            for item in diff:
                symbol = str(item.get("f12") or "")
                name = str(item.get("f14") or "")
                if not symbol or not name:
                    continue
                all_stocks.append({
                    "symbol": symbol,
                    "name": name,
                    "price": _numf(item.get("f2")),
                    "change_pct": _numf(item.get("f3")),
                    "volume": item.get("f4") or item.get("f5") or 0,
                    "turnover": item.get("f6") or 0,  # 成交额
                    "market_cap": item.get("f20") or 0,  # 总市值
                    "float_cap": item.get("f21") or 0,
                    "exchange": "NASDAQ" if item.get("f15") == 105 else "NYSE",
                })
            logger.info(f"[universe] 东财拉取第 {page} 页: {len(diff)} 条")
            if len(diff) < page_size:
                break
            time.sleep(0.3)  # 限流
        except Exception as exc:
            logger.warning(f"[universe] 东财拉取第 {page} 页失败: {exc}")
            break

    logger.info(f"[universe] 东财拉取完成: 共 {len(all_stocks)} 只")
    return all_stocks


def _numf(v):
    """安全转数字"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ====================================================================
# 筛选逻辑
# ====================================================================

def _passes_research_filters(item: dict) -> bool:
    """判断是否通过研究池硬门槛"""
    price = _numf(item.get("price"))
    mcap = _numf(item.get("market_cap"))
    turnover = _numf(item.get("turnover"))
    symbol = str(item.get("symbol", ""))

    # 排除明显非普通股
    if len(symbol) > 5 and not symbol.replace(".", "").isalpha():
        return False
    # 排除 ETF 关键词（简单过滤）
    name = str(item.get("name", "")).upper()
    etf_keywords = ["ETF", "TRUST", "FUND", "NOTE", "BEAR", "BULL"]
    if any(kw in name for kw in etf_keywords):
        return False

    if price is not None and price < RESEARCH_CONFIG["min_price"]:
        return False
    if mcap is not None and mcap < RESEARCH_CONFIG["min_market_cap"]:
        return False
    if turnover is not None and turnover < RESEARCH_CONFIG["min_avg_dollar_volume"]:
        return False
    return True


def _score_core_a(item: dict) -> float:
    """Core A 排名评分（总分 100）"""
    score = 0.0
    turnover = _numf(item.get("turnover")) or 0
    mcap = _numf(item.get("market_cap")) or 0
    price = _numf(item.get("price")) or 0

    # 20日平均成交额排名（25分）
    if turnover > 0:
        score += 25 * min(turnover / 1_000_000_000, 1.0)  # 10亿成交额得满分

    # 市值及机构参与度（10分）
    if mcap > 0:
        score += 10 * min(mcap / 500_000_000_000, 1.0)  # 5000亿市值得满分

    # 价格适合度（10分）
    if 20 <= price <= 500:
        score += 10
    elif price >= 10:
        score += 6
    elif price >= 5:
        score += 3

    # 波动率适合度（10分）- 默认给中等分
    score += 6

    return score


def _score_core_b(item: dict) -> float:
    """Core B 排名评分（总分 100）"""
    score = 0.0
    turnover = _numf(item.get("turnover")) or 0
    mcap = _numf(item.get("market_cap")) or 0
    price = _numf(item.get("price")) or 0

    # 20日平均成交额（20分）
    if turnover > 0:
        score += 20 * min(turnover / 500_000_000, 1.0)

    # 市值（10分）
    if mcap > 0:
        score += 10 * min(mcap / 100_000_000_000, 1.0)

    # 价格适合度（10分）
    if 15 <= price <= 300:
        score += 10
    elif price >= 7:
        score += 5

    # 趋势质量（10分）
    score += 5

    return score


# ====================================================================
# 核心池重平衡
# ====================================================================

def _get_sector(item: dict) -> str:
    """从 item 中获取行业（暂缺，默认返回空）"""
    return item.get("sector") or item.get("industry") or ""


def build_core_pools(research_stocks: list[dict]) -> dict:
    """从研究池中选出 Core A 300 + Core B 500

    Args:
        research_stocks: 研究池股票列表（含 price, market_cap, turnover 等字段）

    Returns:
        {"core_a": [(symbol, rank, score, reason), ...],
         "core_b": [(symbol, rank, score, reason), ...]}
    """
    # 1. 计算 A 池评分
    a_scored = []
    for s in research_stocks:
        if not _passes_research_filters(s):
            continue
        score = _score_core_a(s)
        a_scored.append((s["symbol"], score, s))

    a_scored.sort(key=lambda x: -x[1])

    # 2. 选 A 池（前 300，带行业约束）
    core_a = []
    sector_count_a = {}
    for symbol, score, s in a_scored:
        if len(core_a) >= CORE_A_CONFIG["target_count"]:
            break
        sector = _get_sector(s)
        max_pct = CORE_A_CONFIG["max_sector_pct"]
        max_count = int(CORE_A_CONFIG["target_count"] * max_pct)
        if sector and sector_count_a.get(sector, 0) >= max_count:
            continue
        sector_count_a[sector] = sector_count_a.get(sector, 0) + 1
        core_a.append((symbol, len(core_a) + 1, score, "Core A 评分排名"))

    a_symbols = {s[0] for s in core_a}

    # 3. 剩余股票计算 B 池评分
    b_scored = []
    for s in research_stocks:
        if s["symbol"] in a_symbols:
            continue
        if not _passes_research_filters(s):
            continue
        score = _score_core_b(s)
        b_scored.append((s["symbol"], score, s))

    b_scored.sort(key=lambda x: -x[1])

    # 4. 选 B 池（前 500，排除 A 池，带行业约束）
    core_b = []
    sector_count_b = {}
    for symbol, score, s in b_scored:
        if len(core_b) >= CORE_B_CONFIG["target_count"]:
            break
        sector = _get_sector(s)
        max_pct = CORE_B_CONFIG["max_sector_pct"]
        max_count = int(CORE_B_CONFIG["target_count"] * max_pct)
        if sector and sector_count_b.get(sector, 0) >= max_count:
            continue
        sector_count_b[sector] = sector_count_b.get(sector, 0) + 1
        core_b.append((symbol, len(core_b) + 1, score, "Core B 评分排名"))

    return {
        "core_a": core_a,
        "core_b": core_b,
    }


# ====================================================================
# 数据库写入
# ====================================================================

def _save_memberships(universe_code: str, members: list, tier: str,
                      config_version: str = CONFIG_VERSION):
    """将池成员写入 universe_memberships 表（先结束旧记录，再写入新记录）"""
    now = _now()
    with get_db_session() as db:
        # 结束旧记录
        db.query(USUniverseMembership).filter(
            USUniverseMembership.universe_code == universe_code,
            USUniverseMembership.effective_to.is_(None),
        ).update({"effective_to": now}, synchronize_session=False)

        # 写入新记录
        for symbol, rank, score, reason in members:
            db.add(USUniverseMembership(
                symbol=symbol,
                universe_code=universe_code,
                tier=tier,
                rank=rank,
                universe_score=score,
                effective_from=now,
                inclusion_reason=reason,
                source="universe_service",
                config_version=config_version,
            ))
        db.commit()
        logger.info(f"[universe] {universe_code}: 写入 {len(members)} 条成员")


def _save_rebalance_run(universe_code: str, input_count: int, eligible_count: int,
                        selected_count: int, added_count: int, removed_count: int,
                        status: str = "SUCCESS", errors: list = None):
    """记录重平衡运行"""
    with get_db_session() as db:
        db.add(USUniverseRebalanceRun(
            universe_code=universe_code,
            started_at=_now(),
            completed_at=_now(),
            status=status,
            input_count=input_count,
            eligible_count=eligible_count,
            selected_count=selected_count,
            added_count=added_count,
            removed_count=removed_count,
            config_version=CONFIG_VERSION,
            errors=errors or [],
        ))
        db.commit()


# ====================================================================
# 公开 API
# ====================================================================

def import_seed_stocks():
    """导入 179 只种子股 + ETF 到 USInstrument 表"""
    now = _now()
    inserted = 0
    with get_db_session() as db:
        for symbol in SEED_CORE_TICKERS:
            exists = db.query(USInstrument).filter(USInstrument.symbol == symbol).first()
            if not exists:
                db.add(USInstrument(
                    symbol=symbol,
                    is_active=True,
                    universe_source="seed_179",
                    created_at=now,
                    updated_at=now,
                ))
                inserted += 1

        for symbol in MARKET_ETF_TICKERS:
            exists = db.query(USInstrument).filter(USInstrument.symbol == symbol).first()
            if not exists:
                db.add(USInstrument(
                    symbol=symbol,
                    is_etf=True,
                    is_active=True,
                    universe_source="seed_etf",
                    created_at=now,
                    updated_at=now,
                ))
                inserted += 1
        db.commit()
    logger.info(f"[universe] 种子导入完成: 新增 {inserted} 只")
    return inserted


def refresh_research_universe() -> dict:
    """从东财拉取全量美股 → 筛选 → 入库 USInstrument

    返回: {"total": int, "inserted": int, "updated": int, "filtered_out": int}
    """
    raw = fetch_research_universe_from_eastmoney()
    if not raw:
        logger.warning("[universe] 东财拉取为空，跳过研究池刷新")
        return {"total": 0, "inserted": 0, "updated": 0, "filtered_out": 0}

    now = _now()
    total = len(raw)
    filtered_out = 0
    inserted = 0
    updated = 0

    with get_db_session() as db:
        for item in raw:
            if not _passes_research_filters(item):
                filtered_out += 1
                continue

            symbol = item["symbol"]
            existing = db.query(USInstrument).filter(USInstrument.symbol == symbol).first()
            if existing:
                # 更新行情数据
                changed = False
                for field, src_key in [
                    ("price", "price"), ("market_cap", "market_cap"),
                    ("volume", "volume"), ("avg_dollar_volume_20d", "turnover"),
                ]:
                    val = _numf(item.get(src_key))
                    if val is not None and getattr(existing, field) != val:
                        setattr(existing, field, val)
                        changed = True
                if item.get("name"):
                    existing.name = item["name"]
                if item.get("exchange"):
                    existing.exchange = item["exchange"]
                existing.is_active = True
                existing.universe_source = "eastmoney"
                existing.data_updated_at = now
                if changed:
                    updated += 1
            else:
                db.add(USInstrument(
                    symbol=symbol,
                    name=item.get("name"),
                    exchange=item.get("exchange"),
                    price=_numf(item.get("price")),
                    market_cap=_numf(item.get("market_cap")),
                    volume=item.get("volume"),
                    avg_dollar_volume_20d=_numf(item.get("turnover")),
                    is_active=True,
                    universe_source="eastmoney",
                    data_updated_at=now,
                ))
                inserted += 1
        db.commit()

    logger.info(f"[universe] 研究池刷新: 总 {total}, 筛选淘汰 {filtered_out}, "
                f"新增 {inserted}, 更新 {updated}")
    return {"total": total, "inserted": inserted, "updated": updated, "filtered_out": filtered_out}


def rebalance_core_a():
    """重平衡 Core A 池（300 只）

    从 USInstrument 中筛选 active 的股票，评分排名选前 300
    """
    with get_db_session() as db:
        stocks = db.query(USInstrument).filter(
            USInstrument.is_active == True,
            USInstrument.is_etf == False,
        ).all()

    # 转为 dict 格式供评分用
    items = []
    for s in stocks:
        items.append({
            "symbol": s.symbol,
            "name": s.name or "",
            "price": float(s.price) if s.price else 0,
            "market_cap": float(s.market_cap) if s.market_cap else 0,
            "turnover": float(s.avg_dollar_volume_20d) if s.avg_dollar_volume_20d else 0,
            "sector": s.sector or "",
            "industry": s.industry or "",
        })

    # 评分排名
    a_scored = []
    for item in items:
        score = _score_core_a(item)
        a_scored.append((item["symbol"], score, item))

    a_scored.sort(key=lambda x: -x[1])

    # 选前 300
    core_a = []
    sector_count = {}
    for symbol, score, item in a_scored:
        if len(core_a) >= CORE_A_CONFIG["target_count"]:
            break
        sector = item.get("sector") or ""
        max_pct = CORE_A_CONFIG["max_sector_pct"]
        max_count = int(CORE_A_CONFIG["target_count"] * max_pct)
        if sector and sector_count.get(sector, 0) >= max_count:
            continue
        sector_count[sector] = sector_count.get(sector, 0) + 1
        core_a.append((symbol, len(core_a) + 1, score, "Core A 评分排名"))

    _save_memberships("CORE_A_300", core_a, "A")
    _save_rebalance_run("CORE_A_300", len(items), len(a_scored), len(core_a), 0, 0)
    logger.info(f"[universe] Core A 重平衡完成: {len(core_a)} 只")
    return core_a


def rebalance_core_b():
    """重平衡 Core B 池（500 只，排除 A 池已有股票）"""
    # 获取当前 A 池成员
    with get_db_session() as db:
        a_members = db.query(USUniverseMembership.symbol).filter(
            USUniverseMembership.universe_code == "CORE_A_300",
            USUniverseMembership.effective_to.is_(None),
        ).all()
    a_symbols = {r[0] for r in a_members}

    with get_db_session() as db:
        stocks = db.query(USInstrument).filter(
            USInstrument.is_active == True,
            USInstrument.is_etf == False,
            USInstrument.symbol.notin_(list(a_symbols)),
        ).all()

    items = []
    for s in stocks:
        items.append({
            "symbol": s.symbol,
            "name": s.name or "",
            "price": float(s.price) if s.price else 0,
            "market_cap": float(s.market_cap) if s.market_cap else 0,
            "turnover": float(s.avg_dollar_volume_20d) if s.avg_dollar_volume_20d else 0,
            "sector": s.sector or "",
            "industry": s.industry or "",
        })

    b_scored = []
    for item in items:
        score = _score_core_b(item)
        b_scored.append((item["symbol"], score, item))

    b_scored.sort(key=lambda x: -x[1])

    core_b = []
    sector_count = {}
    for symbol, score, item in b_scored:
        if len(core_b) >= CORE_B_CONFIG["target_count"]:
            break
        sector = item.get("sector") or ""
        max_pct = CORE_B_CONFIG["max_sector_pct"]
        max_count = int(CORE_B_CONFIG["target_count"] * max_pct)
        if sector and sector_count.get(sector, 0) >= max_count:
            continue
        sector_count[sector] = sector_count.get(sector, 0) + 1
        core_b.append((symbol, len(core_b) + 1, score, "Core B 评分排名"))

    _save_memberships("CORE_B_500", core_b, "B")
    _save_rebalance_run("CORE_B_500", len(items), len(b_scored), len(core_b), 0, 0)
    logger.info(f"[universe] Core B 重平衡完成: {len(core_b)} 只")
    return core_b


def get_core_pool_symbols(universe_code: str = "CORE_A_300") -> list[str]:
    """获取当前核心池股票代码列表"""
    with get_db_session() as db:
        rows = db.query(USUniverseMembership.symbol).filter(
            USUniverseMembership.universe_code == universe_code,
            USUniverseMembership.effective_to.is_(None),
        ).order_by(USUniverseMembership.rank).all()
    return [r[0] for r in rows]


def get_all_pool_symbols() -> list[str]:
    """获取当前所有核心池股票（A+B 去重）"""
    a = get_core_pool_symbols("CORE_A_300")
    b = get_core_pool_symbols("CORE_B_500")
    seen = set()
    result = []
    for s in a + b:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def get_pool_stats() -> dict:
    """获取股票池统计信息"""
    stats = {}
    for code, name in UNIVERSE_CODES.items():
        symbols = get_core_pool_symbols(code) if code in ("CORE_A_300", "CORE_B_500") else []
        count = len(symbols) if symbols else 0
        # 从数据库查实际数量
        with get_db_session() as db:
            cnt = db.query(func.count(USUniverseMembership.id)).filter(
                USUniverseMembership.universe_code == code,
                USUniverseMembership.effective_to.is_(None),
            ).scalar() or 0
        stats[code] = {"name": name, "count": cnt}

    # 研究池数量
    with get_db_session() as db:
        research_cnt = db.query(func.count(USInstrument.id)).filter(
            USInstrument.is_active == True,
        ).scalar() or 0
    stats["RESEARCH_DYNAMIC"] = {"name": "动态研究池", "count": research_cnt}

    return stats


# ====================================================================
# 与 api/us_quant / backtest 对接的统一入口（V2.2 接口契约）
# ====================================================================

# 调用方常用简写 → 规范 universe_code
_UNIVERSE_ALIASES = {
    "US_CORE_A": "CORE_A_300", "CORE_A": "CORE_A_300",
    "US_CORE_B": "CORE_B_500", "CORE_B": "CORE_B_500",
    "US_RESEARCH": "RESEARCH_DYNAMIC", "RESEARCH": "RESEARCH_DYNAMIC",
    "RESEARCH_DYNAMIC": "RESEARCH_DYNAMIC",
    "MARKET_ETF": "MARKET_ETF", "ETF": "MARKET_ETF",
    "SEED_CORE_179": "SEED_CORE_179", "SEED": "SEED_CORE_179",
}

UNIVERSE_DEFINITIONS = {
    "CORE_A_300": {"name": "核心A池", "target_count": CORE_A_CONFIG["target_count"],
                   "description": "市值/流动性排名 Top 300，美股量化主扫描池"},
    "CORE_B_500": {"name": "核心B池", "target_count": CORE_B_CONFIG["target_count"],
                   "description": "市值/流动性排名 301-800"},
    "RESEARCH_DYNAMIC": {"name": "动态研究池", "target_count": None,
                         "description": "东财全量美股经硬门槛筛选的研究池"},
    "MARKET_ETF": {"name": "市场与行业ETF", "target_count": None, "description": "大盘+行业+风险观察 ETF"},
    "SEED_CORE_179": {"name": "179只初始化种子", "target_count": 179, "description": "文档附录 B 种子股"},
    # 简写别名（与规范码同义）
    "US_CORE_A": {"name": "核心A池", "target_count": CORE_A_CONFIG["target_count"]},
    "CORE_A": {"name": "核心A池", "target_count": CORE_A_CONFIG["target_count"]},
    "US_CORE_B": {"name": "核心B池", "target_count": CORE_B_CONFIG["target_count"]},
    "CORE_B": {"name": "核心B池", "target_count": CORE_B_CONFIG["target_count"]},
    "US_RESEARCH": {"name": "动态研究池", "target_count": None},
    "RESEARCH": {"name": "动态研究池", "target_count": None},
}


def _resolve_universe_code(code: str) -> str:
    if not code:
        return code
    return _UNIVERSE_ALIASES.get(code.strip().upper(), code.strip().upper())


def get_universe_members(code: str) -> list[str]:
    """获取股票池成员符号列表（按 rank 排序）。未知池返回 []。"""
    uc = _resolve_universe_code(code)
    try:
        with get_db_session() as db:
            rows = db.query(USUniverseMembership.symbol).filter(
                USUniverseMembership.universe_code == uc,
                USUniverseMembership.effective_to.is_(None),
            ).order_by(USUniverseMembership.rank).all()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning("[universe] get_universe_members(%s) 失败: %s", code, e)
        return []


def uniques_for_scanner(codes: list[str]) -> list[str]:
    """合并多个股票池成员并去重（保持顺序）。"""
    seen: set = set()
    out: list = []
    for c in codes:
        for s in get_universe_members(c):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def get_scanner_limit(code: str) -> int:
    """单池扫描上限（按池目标规模给出合理上限）。"""
    uc = _resolve_universe_code(code)
    if uc == "CORE_A_300":
        return 300
    if uc == "CORE_B_500":
        return 500
    return 120


def list_universes() -> list[dict]:
    """列出所有股票池（定义 + 当前成员数）。"""
    result = []
    for uc in UNIVERSE_CODES:
        members = get_universe_members(uc)
        defn = UNIVERSE_DEFINITIONS.get(uc, {})
        result.append({
            "code": uc,
            "name": defn.get("name", UNIVERSE_CODES[uc]),
            "target": defn.get("target_count"),
            "count": len(members),
            "description": defn.get("description", ""),
        })
    return result


def get_universe(code: str) -> dict | None:
    """获取单个股票池完整信息（定义 + 成员）。未知池返回 None。"""
    uc = _resolve_universe_code(code)
    if uc not in UNIVERSE_CODES and code.strip().upper() not in _UNIVERSE_ALIASES:
        return None
    members = get_universe_members(uc)
    defn = UNIVERSE_DEFINITIONS.get(uc, {})
    return {
        "code": uc,
        "name": defn.get("name", UNIVERSE_CODES.get(uc, code)),
        "target": defn.get("target_count"),
        "count": len(members),
        "description": defn.get("description", ""),
        "members": members,
    }


def pool_stats() -> dict:
    """兼容别名：api/us_quant 调用 pool_stats()，实现复用 get_pool_stats()。"""
    return get_pool_stats()


def daily_validity_check() -> dict:
    """每日有效性检查：标记退市/停牌/流动性不足的股票

    返回: {"checked": int, "deactivated": int, "warnings": [str]}
    """
    warnings = []
    deactivated = 0
    with get_db_session() as db:
        all_active = db.query(USInstrument).filter(
            USInstrument.is_active == True,
        ).all()
        checked = len(all_active)

        for inst in all_active:
            # 检查价格
            if inst.price is not None and float(inst.price) < 1.0:
                inst.is_active = False
                deactivated += 1
                warnings.append(f"{inst.symbol} 价格 ${inst.price} < $1，已标记失效")
                continue
            # 检查成交额
            if inst.avg_dollar_volume_20d is not None and float(inst.avg_dollar_volume_20d) < 5_000_000:
                inst.is_active = False
                deactivated += 1
                warnings.append(f"{inst.symbol} 20日成交额 ${inst.avg_dollar_volume_20d} < $5M，已标记失效")
                continue
        db.commit()

    logger.info(f"[universe] 每日检查: {checked} 只, 标记失效 {deactivated} 只")
    return {"checked": checked, "deactivated": deactivated, "warnings": warnings}


def run_full_rebalance() -> dict:
    """全量重平衡（研究池刷新 → Core A → Core B）"""
    result = {}

    # 1. 刷新研究池
    research = refresh_research_universe()
    result["research"] = research

    # 2. 每日有效性检查
    validity = daily_validity_check()
    result["validity"] = validity

    # 3. 重平衡 Core A
    core_a = rebalance_core_a()
    result["core_a_count"] = len(core_a)

    # 4. 重平衡 Core B
    core_b = rebalance_core_b()
    result["core_b_count"] = len(core_b)

    result["status"] = "success"
    logger.info(f"[universe] 全量重平衡完成: Core A={len(core_a)}, Core B={len(core_b)}")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "import_seed":
            print(import_seed_stocks())
        elif cmd == "refresh":
            print(refresh_research_universe())
        elif cmd == "rebalance":
            print(run_full_rebalance())
        elif cmd == "stats":
            print(get_pool_stats())
        elif cmd == "rebalance_a":
            print(len(rebalance_core_a()))
        elif cmd == "rebalance_b":
            print(len(rebalance_core_b()))
        elif cmd == "check":
            print(daily_validity_check())
        else:
            print(f"未知命令: {cmd}")
    else:
        print(run_full_rebalance())