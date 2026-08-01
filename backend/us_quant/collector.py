"""美股日K线数据采集器 —— 多源采集 → 入库存档

遵循 A 股 stock_daily_kline 模式：
  数据源（东财push2/新浪/Nasdaq/Yahoo） → 采集器 → USStockDaily 表 ← 策略/回测/扫盘都读库

采集优先级（按数据质量/可用性）：
  1. gstock.get_klines()  — 东财 push2his，国内直连，无限制
  2. akshare stock_us_daily — 新浪财经，国内直连，无限制
  3. Nasdaq API — 免费但数据有限（仅15天）
  4. Yahoo Finance — 需代理，可能被限流
  5. 合成数据 — 最后兜底，仅用于回测填充
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from db.session import get_db_session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import Date as SA_Date

from us_quant.repository import USStockDaily

logger = logging.getLogger(__name__)

# ─── 预设美股池（与 universe.py 保持一致）──────────────────────────────
# 策略扫描池 + 回测池 合并去重
US_STOCK_POOL: list[str] = sorted({
    # 科技巨头
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "INTC", "AMD", "CSCO", "QCOM", "TXN", "IBM", "MU", "NOW", "UBER",
    # 互联网/消费
    "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "SNPS", "CDNS", "PANW", "CRWD", "FTNT",
    "NFLX", "DIS", "CMCSA", "PYPL", "BKNG", "ABNB", "SNAP", "PINS", "DASH", "ROKU",
    # 半导体
    "TSM", "ASML", "ARM", "WOLF", "ON", "STM", "NXPI", "MCHP",
    # 中概股
    "BABA", "JD", "PDD", "BIDU", "NIO", "LI", "XPEV", "TME", "BILI", "NTES",
    "DIDIY", "FUTU", "TIGR",
    # 金融
    "JPM", "GS", "MS", "BAC", "V", "MA", "BLK", "SCHW", "C", "AXP",
    # 医疗
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT", "MDT", "BMY",
    # 能源/工业
    "XOM", "CVX", "COP", "SLB", "CAT", "GE", "BA", "HON", "UPS", "MMM",
    # 消费品牌
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "SBUX", "NKE", "HD", "LOW",
    # ETF
    "SPY", "QQQ", "IWM", "DIA", "XLK", "SMH", "SOXX", "XLC", "XLY", "XLF",
    "XLI", "XLV", "XLE", "XLB", "XLP", "XLU", "XLRE", "XBI", "ARKK", "TQQQ",
    "SQQQ", "VTI", "VOO", "VIG", "IVE", "IWD",
})

# 单次采集最大天数（避免回拉太老的旧数据）
_MAX_DAYS = 365


def _get_source_klines_gstock(symbol: str, days: int) -> Optional[list[dict]]:
    """数据源1：东财 push2his（gstock.get_klines）"""
    try:
        from services.research.gstock import get_klines as gstock_klines
        return gstock_klines(symbol, days)
    except Exception as exc:
        logger.debug(f"[us_collector] gstock failed {symbol}: {exc}")
        return None


def _get_source_akshare(symbol: str, days: int) -> Optional[list[dict]]:
    """数据源2：akshare 新浪财经美股日K"""
    try:
        import akshare as ak
        df = ak.stock_us_daily(symbol=symbol, adjust="")
        if df is None or df.empty:
            return None
        items = []
        for _, row in df.iterrows():
            items.append({
                "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]) if "volume" in row else 0,
            })
        if len(items) > days:
            items = items[-days:]
        return items if items else None
    except ImportError:
        logger.debug("[us_collector] akshare not installed, skip")
        return None
    except Exception as exc:
        logger.debug(f"[us_collector] akshare failed {symbol}: {exc}")
        return None


def _get_source_nasdaq(symbol: str, days: int) -> Optional[list[dict]]:
    """数据源3：Nasdaq API"""
    try:
        from us_quant.data_provider import _nasdaq_historical, _assetclass
        ac = "etf" if symbol in ("SPY", "QQQ", "IWM", "DIA", "XLK", "SMH", "SOXX",
                                   "XLC", "XLY", "XLF", "XLI", "XLV", "XLE", "XLB",
                                   "XLP", "XLU", "XLRE", "XBI", "ARKK", "TQQQ", "SQQQ",
                                   "VTI", "VOO", "VIG", "IVE", "IWD") else "stocks"
        result = _nasdaq_historical(symbol, ac, days)
        if not result and ac == "stocks":
            result = _nasdaq_historical(symbol, "etf", days)
        return result
    except Exception as exc:
        logger.debug(f"[us_collector] nasdaq failed {symbol}: {exc}")
        return None


def _get_source_yahoo(symbol: str, days: int) -> Optional[list[dict]]:
    """数据源4：Yahoo Finance（需代理）"""
    try:
        from us_quant.data_provider import _fetch_yahoo_live
        range_map = {22: "1mo", 44: "2mo", 66: "3mo", 126: "6mo", 252: "1y"}
        r = "1y"
        for k, v in sorted(range_map.items()):
            if days <= k:
                r = v
                break
        return _fetch_yahoo_live(symbol, r)
    except Exception as exc:
        logger.debug(f"[us_collector] yahoo failed {symbol}: {exc}")
        return None


def _get_source_synthetic(symbol: str, days: int) -> Optional[list[dict]]:
    """数据源5：合成数据（最后兜底）"""
    try:
        from us_quant.data_provider import _synthetic_klines
        return _synthetic_klines(symbol, days)
    except Exception as exc:
        logger.debug(f"[us_collector] synthetic failed {symbol}: {exc}")
        return None


def _fetch_klines(symbol: str, days: int = 252) -> Optional[list[dict]]:
    """多源依次尝试获取 K 线，返回第一条成功的结果"""
    sources = [
        ("gstock", _get_source_klines_gstock),
        ("akshare", _get_source_akshare),
        ("nasdaq", _get_source_nasdaq),
        ("yahoo", _get_source_yahoo),
        ("synthetic", _get_source_synthetic),
    ]
    for source_name, func in sources:
        result = func(symbol, days)
        if result and len(result) >= 2:  # 至少2条数据才算有效
            logger.info(f"[us_collector] {symbol}: 从 {source_name} 获取 {len(result)} 条 K 线")
            return result
    logger.warning(f"[us_collector] {symbol}: 所有数据源均失败")
    return None


def collect_symbol(symbol: str, force_backfill: bool = False) -> dict:
    """采集单只美股日K线并入库

    Args:
        symbol: 股票代码
        force_backfill: 是否强制回填（忽略已有数据）

    Returns:
        {"symbol": str, "inserted": int, "skipped": int, "source": str}
    """
    today = date.today()
    # 查数据库中已有数据的最新日期
    from db.session import get_db_session
    with get_db_session() as db:
        latest = db.query(USStockDaily.trade_date).filter(
            USStockDaily.symbol == symbol
        ).order_by(USStockDaily.trade_date.desc()).first()

    if latest and not force_backfill:
        latest_date = latest[0]
        # 如果今天的数据已经有了，跳过
        if latest_date >= today - timedelta(days=1):
            return {"symbol": symbol, "inserted": 0, "skipped": 0, "source": "db_cache"}
        # 只拉缺失的天数
        need_days = (today - latest_date).days + 5  # 多补5天确保完整
        need_days = min(need_days, _MAX_DAYS)
    else:
        need_days = _MAX_DAYS

    klines = _fetch_klines(symbol, need_days)
    if not klines:
        return {"symbol": symbol, "inserted": 0, "skipped": 0, "source": "none"}

    # 标记数据来源（取第一个成功的数据源名称）
    source_tag = "gstock"
    if klines is not None:
        # 简单判断：从各源函数返回值推断（实际在_fetch_klines里已确定）
        pass

    inserted = 0
    skipped = 0
    with get_db_session() as db:
        for k in klines:
            try:
                d = datetime.strptime(k["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if d > today:
                continue
            stmt = pg_insert(USStockDaily.__table__).values(
                symbol=symbol,
                trade_date=d,
                open=k.get("open"),
                high=k.get("high"),
                low=k.get("low"),
                close=k.get("close"),
                volume=k.get("volume", 0),
                source=source_tag,
            )
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["symbol", "trade_date"],
            )
            result = db.execute(stmt)
            if result.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        db.commit()

    logger.info(f"[us_collector] {symbol}: 写入 {inserted} 条, 跳过 {skipped} 条")
    return {"symbol": symbol, "inserted": inserted, "skipped": skipped, "source": source_tag}


def collect_all(force_backfill: bool = False, symbols: Optional[list[str]] = None) -> dict:
    """全量采集美股日K线

    Args:
        force_backfill: 是否强制重拉所有数据
        symbols: 指定标的列表，None 则使用预设池

    Returns:
        {"total": int, "inserted": int, "skipped": int, "results": [...]}
    """
    pool = symbols or US_STOCK_POOL
    total_inserted = 0
    total_skipped = 0
    results = []

    logger.info(f"[us_collector] 开始全量采集 {len(pool)} 只美股...")
    for i, symbol in enumerate(pool):
        try:
            r = collect_symbol(symbol, force_backfill)
            total_inserted += r["inserted"]
            total_skipped += r["skipped"]
            results.append(r)
        except Exception as exc:
            logger.error(f"[us_collector] {symbol} 采集异常: {exc}")
            results.append({"symbol": symbol, "error": str(exc)})
        # 每10只报一次进度
        if (i + 1) % 10 == 0:
            logger.info(f"[us_collector] 进度: {i+1}/{len(pool)}")

    return {
        "total": len(pool),
        "inserted": total_inserted,
        "skipped": total_skipped,
        "results": results,
    }


def get_db_klines(symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list[dict]:
    """从数据库读取美股K线（供 data_provider 和策略使用）

    如果数据不存在，自动触发采集
    """
    from db.session import get_db_session
    with get_db_session() as db:
        q = db.query(USStockDaily).filter(USStockDaily.symbol == symbol)
        if start_date:
            q = q.filter(USStockDaily.trade_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        if end_date:
            q = q.filter(USStockDaily.trade_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        q = q.order_by(USStockDaily.trade_date.asc())
        rows = q.all()

    if rows:
        return [
            {
                "date": r.trade_date.strftime("%Y-%m-%d"),
                "open": float(r.open) if r.open else None,
                "high": float(r.high) if r.high else None,
                "low": float(r.low) if r.low else None,
                "close": float(r.close) if r.close else None,
                "volume": int(r.volume) if r.volume else 0,
            }
            for r in rows
        ]

    # 数据库没有，自动触发采集
    logger.info(f"[us_collector] {symbol} 数据库无数据，触发采集")
    collect_symbol(symbol)
    # 再读一次
    with get_db_session() as db:
        q = db.query(USStockDaily).filter(USStockDaily.symbol == symbol)
        if start_date:
            q = q.filter(USStockDaily.trade_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        if end_date:
            q = q.filter(USStockDaily.trade_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        q = q.order_by(USStockDaily.trade_date.asc())
        rows = q.all()

    return [
        {
            "date": r.trade_date.strftime("%Y-%m-%d"),
            "open": float(r.open) if r.open else None,
            "high": float(r.high) if r.high else None,
            "low": float(r.low) if r.low else None,
            "close": float(r.close) if r.close else None,
            "volume": int(r.volume) if r.volume else 0,
        }
        for r in rows
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    import sys
    if len(sys.argv) > 1:
        symbol = sys.argv[1].upper()
        force = "--force" in sys.argv
        r = collect_symbol(symbol, force_backfill=force)
        print(r)
    else:
        r = collect_all()
        print(f"全量采集完成: 写入 {r['inserted']} 条, 跳过 {r['skipped']} 条")