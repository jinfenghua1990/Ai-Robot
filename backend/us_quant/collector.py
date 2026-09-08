"""美股日K线数据采集器 —— 多源采集 → 入库存档

遵循 A 股 stock_daily_kline 模式：
  数据源（东财push2/新浪/Nasdaq/Yahoo） → 采集器 → USStockDaily 表 ← 策略/回测/扫盘都读库

采集优先级（按当前可用性）：
  1. 新浪 US_MinKService — 国内直连、全历史
  2. gstock.get_klines() — 东财 push2his
  3. AkShare stock_us_daily — 新浪封装
  4. Nasdaq API — 免费但数据窗口较短
  5. Yahoo Finance — 需代理，可能被限流
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import Optional

from db.session import get_db_session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import Date as SA_Date, or_

from us_quant.repository import USStockDaily

logger = logging.getLogger(__name__)
REGIME_REFERENCE_SYMBOLS = {"SPY", "QQQ", "IWM", "RSP", "^VIX"}

def _get_collector_pool() -> list[str]:
    """读取自动采集范围：核心池 + 美股自选 + 真实持仓 + 参考指数。"""
    from us_quant.sector_rotation import SECTOR_ETFS

    # 市场环境快照依赖这五个标的；遗漏其中任何一个都会让策略在数据库
    # 数据不完整时永久处于 STALE。参考指数与行业 ETF 都由采集器先落库。
    required_references = REGIME_REFERENCE_SYMBOLS | {item[0] for item in SECTOR_ETFS}
    pool: set[str] = set()
    try:
        from us_quant.universe import get_all_pool_symbols, get_universe_members
        pool.update(get_all_pool_symbols())
        pool.update(get_universe_members("US_WATCHLIST"))
    except Exception as exc:
        logger.warning("[us_collector] 读取核心池/自选池失败: %s", exc)

    try:
        from us_quant.repository import USRealPosition
        with get_db_session() as db:
            rows = db.query(USRealPosition.symbol).filter(
                USRealPosition.status == "ACTIVE",
            ).all()
        pool.update(row[0] for row in rows if row and row[0])
    except Exception as exc:
        logger.warning("[us_collector] 读取真实持仓失败: %s", exc)

    return sorted(pool | required_references)

# 单次采集最大天数（避免回拉太老的旧数据）
_MAX_DAYS = 365
_MIN_FACTOR_HISTORY = 252


def _required_fetch_days(
    existing_count: int,
    latest_date: date | None,
    target_date: date,
    force_backfill: bool,
) -> int:
    """历史不足时全量回填；历史足够后只补交易日缺口。"""
    if force_backfill or latest_date is None or existing_count < _MIN_FACTOR_HISTORY:
        return _MAX_DAYS
    return min(max((target_date - latest_date).days + 7, 7), _MAX_DAYS)


def _get_source_klines_sina(symbol: str, days: int) -> Optional[list[dict]]:
    """数据源1：新浪美股日K（US_MinKService.getDailyK，全历史，无需代理）"""
    try:
        import re
        import requests as _req

        url = ("https://stock.finance.sina.com.cn/usstock/api/jsonp.php/"
               "var%20t=/US_MinKService.getDailyK")
        resp = _req.get(url, params={"symbol": symbol}, timeout=15,
                        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
        text = resp.text
        # 返回形如 [{"d":"2026-08-06","o":"98.22","h":"103.38","l":"95.60","c":"99.81","v":"78088124","a":"0"}]
        items = []
        for m in re.finditer(r'\{[^{}]*?"c"\s*:\s*"[^"]*"[^{}]*?\}', text):
            seg = m.group(0)
            def _get(key: str):
                mm = re.search(r'"%s"\s*:\s*"([^"]*)"' % key, seg)
                return mm.group(1) if mm else None
            d = _get("d")
            if not d:
                continue
            try:
                items.append({
                    "date": d,
                    "open": float(_get("o")),
                    "high": float(_get("h")),
                    "low": float(_get("l")),
                    "close": float(_get("c")),
                    "volume": int(float(_get("v") or 0)),
                })
            except (TypeError, ValueError):
                continue
        if len(items) > days:
            items = items[-days:]
        return items if items else None
    except Exception as exc:
        logger.debug(f"[us_collector] sina failed {symbol}: {exc}")
        return None


def _get_source_klines_gstock(symbol: str, days: int) -> Optional[list[dict]]:
    try:
        from services.research.gstock import get_klines as gstock_klines
        return gstock_klines(symbol, days)
    except Exception as exc:
        logger.debug(f"[us_collector] gstock failed {symbol}: {exc}")
        return None


def _get_source_cboe(symbol: str, days: int) -> Optional[list[dict]]:
    """VIX 专用官方历史源；普通股票不调用。"""
    if symbol != "^VIX":
        return None
    try:
        from us_quant.data_provider import _cboe_vix_klines
        return _cboe_vix_klines(days)
    except Exception as exc:
        logger.debug("[us_collector] cboe failed %s: %s", symbol, exc)
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
        range_map = {
            22: "1mo", 44: "2mo", 66: "3mo", 126: "6mo",
            252: "1y", 520: "2y", 1260: "5y",
        }
        r = "5y" if days > 520 else "1y"
        for k, v in sorted(range_map.items()):
            if days <= k:
                r = v
                break
        return _fetch_yahoo_live(symbol, r)
    except Exception as exc:
        logger.debug(f"[us_collector] yahoo failed {symbol}: {exc}")
        return None


def _fetch_klines_with_source(
    symbol: str,
    days: int = 252,
) -> tuple[str, list[dict]] | None:
    """多源依次获取真实 K 线，并返回来源标签。"""
    sources = [
        ("cboe", _get_source_cboe),
        ("sina", _get_source_klines_sina),
        ("gstock", _get_source_klines_gstock),
        ("akshare", _get_source_akshare),
        ("nasdaq", _get_source_nasdaq),
        ("yahoo", _get_source_yahoo),
    ]
    for source_name, func in sources:
        result = func(symbol, days)
        if result and len(result) >= 2:  # 至少2条数据才算有效
            logger.info(f"[us_collector] {symbol}: 从 {source_name} 获取 {len(result)} 条 K 线")
            return source_name, result
    logger.warning(f"[us_collector] {symbol}: 所有数据源均失败")
    return None

def collect_symbol(
    symbol: str,
    force_backfill: bool = False,
    target_date: Optional[date] = None,
    compute_factors: bool = True,
) -> dict:
    """采集单只美股日K线并入库

    Args:
        symbol: 股票代码
        force_backfill: 是否强制回填（忽略已有数据）
        target_date: 最近已完成的美股交易日；默认按纽约交易所日历计算
        compute_factors: 入库后是否从完整数据库历史计算当日因子

    Returns:
        {"symbol": str, "inserted": int, "skipped": int, "source": str}
    """
    if target_date is None:
        from market_quant.calendar import latest_completed_session
        target_date = latest_completed_session("US")
    symbol = symbol.strip().upper()
    # 查数据库中已有数据的最新日期
    from db.session import get_db_session
    with get_db_session() as db:
        latest = db.query(USStockDaily.trade_date).filter(
            USStockDaily.symbol == symbol,
            or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
        ).order_by(USStockDaily.trade_date.desc()).first()
        existing_count = db.query(USStockDaily.id).filter(
            USStockDaily.symbol == symbol,
            or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
        ).count()

    if latest and not force_backfill:
        latest_date = latest[0]
        # 最近已完成交易日的数据已有时不再访问外部源，但仍检查因子缺口。
        if latest_date >= target_date and existing_count >= _MIN_FACTOR_HISTORY:
            factor_summary = None
            if compute_factors:
                from us_quant.factor_storage import missing_factor_symbols, store_latest_factors_from_db
                if missing_factor_symbols([symbol], target_date):
                    factor_summary = store_latest_factors_from_db([symbol], target_date)
                else:
                    factor_summary = {
                        "target_date": target_date.isoformat(), "symbols": 1,
                        "stored_rows": 0, "status": "cached",
                    }
            return {
                "symbol": symbol, "inserted": 0, "skipped": 0,
                "source": "db_cache", "factors": factor_summary,
            }
        need_days = _required_fetch_days(
            existing_count, latest_date, target_date, force_backfill,
        )
    else:
        latest_date = latest[0] if latest else None
        need_days = _required_fetch_days(
            existing_count, latest_date, target_date, force_backfill,
        )

    # 真实源全部失败时返回空，由评分层明确跳过该标的。
    fetched = _fetch_klines_with_source(symbol, need_days)
    if not fetched:
        return {"symbol": symbol, "inserted": 0, "skipped": 0, "source": "none"}
    source_tag, klines = fetched

    inserted = 0
    skipped = 0
    with get_db_session() as db:
        for k in klines:
            try:
                d = datetime.strptime(k["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if d > target_date:
                continue
            insert_stmt = pg_insert(USStockDaily.__table__).values(
                symbol=symbol,
                trade_date=d,
                open=k.get("open"),
                high=k.get("high"),
                low=k.get("low"),
                close=k.get("close"),
                volume=k.get("volume", 0),
                amount=k.get("amount"),
                vwap=k.get("vwap"),
                adj_close=k.get("adj_close"),
                change_pct=k.get("change_pct"),
                amplitude=k.get("amplitude"),
                turnover=k.get("turnover"),
                source=source_tag,
            )
            # 历史遗留的 synthetic 行不能阻挡真实行情入库；已有真实行保持幂等不覆盖。
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=["symbol", "trade_date"],
                set_={
                    "open": insert_stmt.excluded.open,
                    "high": insert_stmt.excluded.high,
                    "low": insert_stmt.excluded.low,
                    "close": insert_stmt.excluded.close,
                    "volume": insert_stmt.excluded.volume,
                    "amount": insert_stmt.excluded.amount,
                    "vwap": insert_stmt.excluded.vwap,
                    "adj_close": insert_stmt.excluded.adj_close,
                    "change_pct": insert_stmt.excluded.change_pct,
                    "amplitude": insert_stmt.excluded.amplitude,
                    "turnover": insert_stmt.excluded.turnover,
                    "source": insert_stmt.excluded.source,
                },
                where=USStockDaily.__table__.c.source == "synthetic",
            )
            result = db.execute(stmt)
            if result.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        db.commit()

    # 派生字段和复权补充各用独立会话，不能复用已经关闭的上下文会话。
    with get_db_session() as db:
        _backfill_derived_fields(symbol, db)
    with get_db_session() as db:
        _backfill_adjclose_from_yahoo(symbol, db)

    factor_summary = None
    if compute_factors:
        from us_quant.factor_storage import store_latest_factors_from_db
        factor_summary = store_latest_factors_from_db([symbol], target_date)

    logger.info(f"[us_collector] {symbol}: 写入 {inserted} 条, 跳过 {skipped} 条")
    return {
        "symbol": symbol, "inserted": inserted, "skipped": skipped,
        "source": source_tag, "factors": factor_summary,
    }


def collect_all(
    force_backfill: bool = False,
    symbols: Optional[list[str]] = None,
    target_date: Optional[date] = None,
    max_workers: int = 4,
) -> dict:
    """全量采集美股日K线

    Args:
        force_backfill: 是否强制重拉所有数据
        symbols: 指定标的列表，None 则使用预设池

    Returns:
        {"total": int, "inserted": int, "skipped": int, "results": [...]}
    """
    if target_date is None:
        from market_quant.calendar import latest_completed_session
        target_date = latest_completed_session("US")
    pool = symbols or _get_collector_pool()
    total_inserted = 0
    total_skipped = 0
    results = []

    logger.info(f"[us_collector] 开始全量采集 {len(pool)} 只美股...")

    def _collect_one(symbol):
        return collect_symbol(
            symbol,
            force_backfill=force_backfill,
            target_date=target_date,
            compute_factors=False,
        )

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(pool) or 1))) as executor:
        futures = {executor.submit(_collect_one, symbol): symbol for symbol in pool}
        for future in as_completed(futures):
            symbol = futures[future]
            completed += 1
            try:
                r = future.result()
                total_inserted += r["inserted"]
                total_skipped += r["skipped"]
                results.append(r)
            except Exception as exc:
                logger.error(f"[us_collector] {symbol} 采集异常: {exc}")
                results.append({"symbol": symbol, "error": str(exc)})
            if completed % 10 == 0:
                logger.info(f"[us_collector] 进度: {completed}/{len(pool)}")

    results.sort(key=lambda item: item.get("symbol", ""))

    from us_quant.factor_storage import missing_factor_symbols, store_latest_factors_from_db
    updated_symbols = [item["symbol"] for item in results if item.get("inserted", 0) > 0]
    factor_targets = list(dict.fromkeys(updated_symbols + missing_factor_symbols(pool, target_date)))
    if factor_targets:
        factor_summary = store_latest_factors_from_db(factor_targets, target_date)
    else:
        factor_summary = {
            "target_date": target_date.isoformat(), "symbols": len(pool),
            "stored_rows": 0, "status": "cached",
        }

    return {
        "total": len(pool),
        "inserted": total_inserted,
        "skipped": total_skipped,
        "target_date": target_date.isoformat(),
        "factors": factor_summary,
        "results": results,
    }


def get_db_klines(symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list[dict]:
    """只读数据库中的美股 K 线；缺失时返回空，绝不触发外部采集。"""
    symbol = symbol.strip().upper()
    with get_db_session() as db:
        q = db.query(USStockDaily).filter(
            USStockDaily.symbol == symbol,
            USStockDaily.open.isnot(None),
            USStockDaily.high.isnot(None),
            USStockDaily.low.isnot(None),
            USStockDaily.close.isnot(None),
            USStockDaily.source.is_(None) | (USStockDaily.source != "synthetic"),
        )
        if start_date:
            q = q.filter(USStockDaily.trade_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        if end_date:
            q = q.filter(USStockDaily.trade_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        q = q.order_by(USStockDaily.trade_date.asc())
        rows = q.all()

    return [
        {
            "date": r.trade_date.strftime("%Y-%m-%d"),
            "open": float(r.open) if r.open is not None else None,
            "high": float(r.high) if r.high is not None else None,
            "low": float(r.low) if r.low is not None else None,
            "close": float(r.close) if r.close is not None else None,
            "volume": int(r.volume) if r.volume is not None else 0,
            "amount": float(r.amount) if r.amount is not None else None,
            "vwap": float(r.vwap) if r.vwap is not None else None,
            "adj_close": float(r.adj_close) if r.adj_close is not None else None,
            "change_pct": float(r.change_pct) if r.change_pct is not None else None,
            "amplitude": float(r.amplitude) if r.amplitude is not None else None,
            "turnover": float(r.turnover) if r.turnover is not None else None,
            "source": r.source,
        }
        for r in rows
    ]



def _backfill_derived_fields(symbol: str, db) -> None:
    """回填派生字段：change_pct, amplitude, amount

    从已有的 close/high/low/volume 计算：
    - change_pct: (close - prev_close) / prev_close * 100
    - amplitude: (high - low) / prev_close * 100
    - amount: volume * close（近似成交额）
    """
    rows = db.query(USStockDaily).filter(
        USStockDaily.symbol == symbol,
        USStockDaily.close.isnot(None),
        or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
    ).order_by(USStockDaily.trade_date.asc()).all()

    updated = 0
    for i, r in enumerate(rows):
        updates = {}

        # change_pct：需要前一日收盘价
        if r.change_pct is None and i > 0 and rows[i-1].close and rows[i-1].close > 0:
            prev_close = float(rows[i-1].close)
            close = float(r.close) if r.close else None
            if close and prev_close > 0:
                updates["change_pct"] = round((close - prev_close) / prev_close * 100, 4)

        # amplitude
        if r.amplitude is None and i > 0 and rows[i-1].close and rows[i-1].close > 0:
            high = float(r.high) if r.high else None
            low = float(r.low) if r.low else None
            prev_close = float(rows[i-1].close)
            if high is not None and low is not None and prev_close > 0:
                updates["amplitude"] = round((high - low) / prev_close * 100, 4)

        # amount：volume * close（近似）
        if r.amount is None and r.volume and r.close:
            updates["amount"] = round(float(r.volume) * float(r.close), 2)

        if updates:
            db.query(USStockDaily).filter(
                USStockDaily.id == r.id
            ).update(updates)
            updated += 1

    if updated:
        db.commit()
        logger.debug(f"[us_collector] {symbol}: 回填 {updated} 条派生字段")


def _backfill_adjclose_from_yahoo(symbol: str, db) -> None:
    """从 Yahoo Finance 补充 adj_close（复权收盘价）

    仅补充最近 30 天且 adj_close 为空的记录。
    避免频繁请求，每次最多取 1mo 范围。
    """
    # 检查是否需要补充
    rows = db.query(USStockDaily).filter(
        USStockDaily.symbol == symbol,
        USStockDaily.adj_close.is_(None),
        USStockDaily.close.isnot(None),
        or_(USStockDaily.source.is_(None), USStockDaily.source != "synthetic"),
    ).order_by(USStockDaily.trade_date.desc()).limit(5).all()

    if not rows:
        return  # 都已有 adj_close，不需要补充

    try:
        from us_quant.data_provider import _fetch_yahoo_live
        yahoo_data = _fetch_yahoo_live(symbol, "1mo")
        if not yahoo_data:
            return

        # 构建 date → adj_close 映射
        adj_map = {}
        for y in yahoo_data:
            adj = y.get("adj_close")
            if adj is not None:
                adj_map[y["date"]] = round(float(adj), 4)

        if not adj_map:
            return

        updated = 0
        for r in rows:
            d_str = r.trade_date.strftime("%Y-%m-%d")
            if d_str in adj_map:
                db.query(USStockDaily).filter(
                    USStockDaily.id == r.id
                ).update({"adj_close": adj_map[d_str]})
                updated += 1

        if updated:
            db.commit()
            logger.debug(f"[us_collector] {symbol}: 从 Yahoo 补充 {updated} 条 adj_close")
    except Exception as exc:
        logger.debug(f"[us_collector] {symbol}: Yahoo adj_close 补充失败: {exc}")

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
