"""抗跌深V反转策略 v2

核心逻辑:
  1. 区间抗跌: 从基准日(默认 7月1日)至今, 跌幅不超过阈值(默认 20%)
  2. 真V形态: 今日盘中曾跌破 -min_intraday_drop%(默认 5%), 收盘却收红 ≥ min_close_up%
     分板阈值: 主板(60/00)收盘涨≥5%, 创业板(300)/科创板(688)收盘涨≥10%
  3. 板块共振: 同板块命中 ≥ N 只 (过滤孤狼行情)
  4. 板块强度约束(可选): 板块命中数 ≤ max_sector_hit(默认 8)
     避免整个板块被动跟涨稀释信号

两个视图:
  - view=all       全部命中(只看个股条件)
  - view=sector    板块共振(个股条件 + 同板块≥N只)

历史回测接口:
  - GET /api/strategy-vreversal/backtest  跑过去 N 天策略命中率 + T+1/T+3/T+5 收益率
"""
import logging
from datetime import date, timedelta
from fastapi import APIRouter, Query
from sqlalchemy import text

from db.session import get_db_session

logger = logging.getLogger(__name__)
router = APIRouter()


def _classify_board(ts_code: str) -> str:
    """分板: main=主板, chinext=创业板, star=科创板"""
    code = ts_code[:3] if ts_code else ''
    if code.startswith('688') or code.startswith('689'):
        return 'star'
    if code.startswith('300') or code.startswith('301'):
        return 'chinext'
    return 'main'


def _board_threshold_pct(board: str, base_pct: float) -> float:
    """分板阈值: 主板用 base_pct, 双创板翻倍(因为±20%涨跌停)"""
    if board in ('chinext', 'star'):
        return base_pct * 1.5  # 双创板阈值放宽 1.5 倍(不是 2 倍, 避免阈值过高)
    return base_pct


@router.get("/api/strategy-vreversal")
def get_vreversal(
    date: str = Query(None, description="交易日 YYYY-MM-DD, 默认最新交易日"),
    base_date: str = Query("2026-07-01", description="基准日 YYYY-MM-DD"),
    max_drawdown: float = Query(20.0, description="区间跌幅上限(%)"),
    min_close_up: float = Query(5.0, description="今日收盘涨幅下限(主板, %)"),
    min_intraday_drop: float = Query(5.0, description="今日盘中最低跌幅下限(%) (V形态约束)"),
    require_v_shape: bool = Query(True, description="是否启用 V 形态约束"),
    min_sector_hit: int = Query(2, description="板块共振最小只数"),
    max_sector_hit: int = Query(8, description="板块命中数上限(避免被动跟涨稀释)"),
    view: str = Query("sector", description="视图: all=全部命中 / sector=板块共振"),
):
    """抗跌深V反转策略筛选 v2

    返回:
      - stocks: 命中股票列表(含板块命中数 + V形态指标)
      - sectors: 板块分布统计
      - summary: 命中数 + 板块数
    """
    with get_db_session() as db:
        # 未指定日期 → 取最新交易日
        if not date:
            row = db.execute(text(
                "SELECT MAX(trade_date) FROM stock_daily_kline"
            )).scalar()
            if not row:
                return {"stocks": [], "sectors": [], "summary": {}}
            date = row.isoformat() if hasattr(row, 'isoformat') else str(row)

        # 主查询: V 形态 + 板块命中数
        # 关键改进: 用 CASE WHEN 按板块分阈值
        sql = text("""
        WITH base AS (
            -- 基准日收盘价
            SELECT ts_code, close AS base_close
            FROM stock_daily_kline
            WHERE trade_date = :base_date
        ),
        today AS (
            -- 今日行情 (用 pct_chg + close 反推 pre_close)
            SELECT ts_code, open, high, low, close, pct_chg,
                   -- pre_close = close / (1 + pct_chg/100)
                   close / NULLIF((1 + pct_chg / 100.0), 0) AS pre_close
            FROM stock_daily_kline
            WHERE trade_date = :trade_date
        ),
        filtered AS (
            -- 第一步: 个股条件过滤
            -- 1) 区间抗跌: 基准日 → 今日收盘 跌幅 ≤ 阈值
            -- 2) 今日收盘涨幅 ≥ 分板阈值 (基础约束, 不受V形态影响)
            -- 3) V 形态(可选): 盘中最低跌幅 ≤ -min_intraday_drop% (曾跌破过)
            SELECT t.ts_code, t.open, t.high, t.low, t.close,
                   t.pct_chg AS today_pct,
                   t.pre_close,
                   b.base_close,
                   ROUND(((t.close - b.base_close) / b.base_close * 100)::numeric, 2) AS period_pct,
                   ROUND(((t.high - t.low) / NULLIF(t.pre_close, 0) * 100)::numeric, 2) AS intraday_range_pct,
                   ROUND(((t.high - NULLIF(t.pre_close, 0)) / NULLIF(t.pre_close, 0) * 100)::numeric, 2) AS max_up_pct,
                   ROUND(((t.low  - NULLIF(t.pre_close, 0)) / NULLIF(t.pre_close, 0) * 100)::numeric, 2) AS min_intraday_pct,
                   -- V 形态强度: 收盘价相对盘中最低的回升幅度
                   ROUND(((t.close - t.low) / NULLIF(t.pre_close, 0) * 100)::numeric, 2) AS v_rebound_pct,
                   -- 分板阈值
                   CASE
                       WHEN t.ts_code LIKE '688%' OR t.ts_code LIKE '689%'
                            OR t.ts_code LIKE '300%' OR t.ts_code LIKE '301%'
                       THEN :min_close_up_chinext
                       ELSE :min_close_up_main
                   END AS required_close_up
            FROM today t
            JOIN base b ON b.ts_code = t.ts_code
            WHERE (t.close - b.base_close) / b.base_close >= -:max_drawdown_ratio
              -- 抗跌含义: 区间跌幅在 -max_drawdown% ~ 0% 之间 (真正跌过的, 但没崩盘)
              AND (t.close - b.base_close) / b.base_close <= 0
              -- 今日收盘涨幅 (基础约束, 不受V形态影响)
              AND t.pct_chg >= CASE
                  WHEN t.ts_code LIKE '688%' OR t.ts_code LIKE '689%'
                       OR t.ts_code LIKE '300%' OR t.ts_code LIKE '301%'
                  THEN :min_close_up_chinext
                  ELSE :min_close_up_main
              END
              -- V 形态约束(可选): 盘中曾跌破 -min_intraday_drop%
              AND (
                  NOT :require_v_shape
                  OR (t.low - NULLIF(t.pre_close, 0)) / NULLIF(t.pre_close, 0) <= -:min_intraday_drop_ratio
              )
        ),
        stock_sector AS (
            -- 每只股票最新的概念板块 + 股票名称(只扫基准日之后, 减少扫描量)
            SELECT DISTINCT ON (ts_code) ts_code, sector, name
            FROM stock_flow
            WHERE sector IS NOT NULL AND sector != ''
              AND trade_date >= :base_date
            ORDER BY ts_code, trade_date DESC
        ),
        stock_name AS (
            -- 股票名称兜底: 即使没有板块也要拿名称(从最近的 stock_flow 记录)
            SELECT DISTINCT ON (ts_code) ts_code, name
            FROM stock_flow
            WHERE name IS NOT NULL AND name != ''
            ORDER BY ts_code, trade_date DESC
        ),
        enriched AS (
            -- 加上板块 + 板块命中数(窗口函数, 一次算出) + 股票名称
            SELECT f.*,
                   s.sector,
                   s.name AS sector_name,
                   sn.name AS stock_name,
                   COUNT(*) OVER (PARTITION BY s.sector) AS sector_hit_count
            FROM filtered f
            LEFT JOIN stock_sector s ON s.ts_code = f.ts_code
            LEFT JOIN stock_name sn ON sn.ts_code = f.ts_code
        )
        SELECT ts_code, sector, sector_name, stock_name,
               today_pct, period_pct, intraday_range_pct,
               max_up_pct, min_intraday_pct, v_rebound_pct, required_close_up,
               close AS today_close, base_close, pre_close,
               sector_hit_count
        FROM enriched
        ORDER BY
            CASE WHEN sector IS NULL THEN 1 ELSE 0 END,
            sector_hit_count DESC,
            v_rebound_pct DESC NULLS LAST,
            today_pct DESC;
        """)

        # 计算分板阈值
        min_close_up_main = min_close_up
        min_close_up_chinext = min_close_up * 1.5  # 双创板放宽 1.5 倍

        rows = db.execute(sql, {
            "base_date": base_date,
            "trade_date": date,
            "max_drawdown_ratio": max_drawdown / 100.0,
            "require_v_shape": require_v_shape,
            "min_intraday_drop": min_intraday_drop,
            "min_intraday_drop_ratio": min_intraday_drop / 100.0,
            "min_close_up_main": min_close_up_main,
            "min_close_up_chinext": min_close_up_chinext,
        }).fetchall()

        # 转为 dict 列表
        all_stocks = []
        for r in rows:
            # 优先用 stock_name(全量兜底), 没有就用 sector_name(有板块的股票)
            stock_name = r.stock_name or r.sector_name or ''
            all_stocks.append({
                "ts_code": r.ts_code,
                "name": stock_name,
                "board": _classify_board(r.ts_code),
                "sector": r.sector,
                "today_pct": float(r.today_pct) if r.today_pct is not None else None,
                "period_pct": float(r.period_pct) if r.period_pct is not None else None,
                "intraday_range_pct": float(r.intraday_range_pct) if r.intraday_range_pct is not None else None,
                "max_up_pct": float(r.max_up_pct) if r.max_up_pct is not None else None,
                "min_intraday_pct": float(r.min_intraday_pct) if r.min_intraday_pct is not None else None,
                "v_rebound_pct": float(r.v_rebound_pct) if r.v_rebound_pct is not None else None,
                "required_close_up": float(r.required_close_up) if r.required_close_up is not None else None,
                "today_close": float(r.today_close),
                "base_close": float(r.base_close),
                "pre_close": float(r.pre_close) if r.pre_close else None,
                "sector_hit_count": int(r.sector_hit_count) if r.sector else 0,
            })

        # 按视图过滤 + 板块强度约束
        if view == "sector":
            stocks = [s for s in all_stocks
                     if s["sector"]
                     and s["sector_hit_count"] >= min_sector_hit
                     and s["sector_hit_count"] <= max_sector_hit]
        else:
            stocks = [s for s in all_stocks
                     if not s["sector"] or s["sector_hit_count"] <= max_sector_hit]

        # 板块分布统计(基于全部候选, 不受 max_sector_hit 影响)
        sector_map = {}
        for s in all_stocks:
            sec = s["sector"]
            if not sec:
                continue
            sector_map.setdefault(sec, {
                "sector": sec,
                "count": 0,
                "today_pct_avg": 0.0,
                "period_pct_avg": 0.0,
                "v_rebound_avg": 0.0,
            })
            m = sector_map[sec]
            m["count"] += 1
            m["today_pct_avg"] += s["today_pct"] or 0
            m["period_pct_avg"] += s["period_pct"] or 0
            m["v_rebound_avg"] += s["v_rebound_pct"] or 0

        sectors = []
        for sec, m in sector_map.items():
            if m["count"] > 0:
                m["today_pct_avg"] = round(m["today_pct_avg"] / m["count"], 2)
                m["period_pct_avg"] = round(m["period_pct_avg"] / m["count"], 2)
                m["v_rebound_avg"] = round(m["v_rebound_avg"] / m["count"], 2)
            m["is_resonance"] = m["count"] >= min_sector_hit
            m["is_too_crowded"] = m["count"] > max_sector_hit
            sectors.append(m)

        sectors.sort(key=lambda x: -x["count"])

        return {
            "date": date,
            "base_date": base_date,
            "view": view,
            "params": {
                "max_drawdown": max_drawdown,
                "min_close_up_main": min_close_up_main,
                "min_close_up_chinext": min_close_up_chinext,
                "min_intraday_drop": min_intraday_drop,
                "require_v_shape": require_v_shape,
                "min_sector_hit": min_sector_hit,
                "max_sector_hit": max_sector_hit,
            },
            "stocks": stocks,
            "sectors": sectors,
            "summary": {
                "total": len(stocks),
                "total_all": len(all_stocks),
                "sector_count": len(sectors),
                "sector_resonance_count": sum(1 for s in sectors if s["count"] >= min_sector_hit),
                "sector_crowded_count": sum(1 for s in sectors if s["count"] > max_sector_hit),
            },
        }


# ========================= 历史回测 =========================

@router.get("/api/strategy-vreversal/backtest")
def backtest_vreversal(
    days: int = Query(20, description="回测最近 N 个交易日"),
    base_date: str = Query("2026-07-01", description="基准日"),
    max_drawdown: float = Query(20.0),
    min_close_up: float = Query(5.0),
    min_intraday_drop: float = Query(5.0),
    require_v_shape: bool = Query(True),
    min_sector_hit: int = Query(2),
    max_sector_hit: int = Query(8),
    view: str = Query("sector"),
):
    """历史回测: 跑过去 N 天的命中率 + T+1/T+3/T+5 收益率

    每个交易日:
      1. 用当日条件筛选命中股票
      2. 算命中股票在 T+1/T+3/T+5 的平均/中位数收益率
      3. 跟大盘指数(上证)同窗口对比

    Returns:
      - daily_stats: [{date, hit_count, avg_t1, avg_t3, avg_t5, market_t1, market_t3, market_t5}]
      - summary: {win_rate_t1, win_rate_t3, win_rate_t5, avg_return_t1/3/5, market_avg}
    """
    with get_db_session() as db:
        # 取最近 N 个交易日
        trade_dates = [r[0] for r in db.execute(text(
            "SELECT DISTINCT trade_date FROM stock_daily_kline "
            "WHERE trade_date >= :base_date "
            "ORDER BY trade_date DESC LIMIT :limit"
        ), {"base_date": base_date, "limit": days}).fetchall()]

        if not trade_dates:
            return {"daily_stats": [], "summary": {}}

        # 反向排序(按时间正序)便于阅读
        trade_dates_sorted = sorted(trade_dates, reverse=False)

        daily_stats = []
        all_returns_t1 = []
        all_returns_t3 = []
        all_returns_t5 = []

        for trade_date in trade_dates_sorted:
            date_str = trade_date.isoformat() if hasattr(trade_date, 'isoformat') else str(trade_date)

            # 复用筛选逻辑(内部调用 get_vreversal, 避免代码重复)
            # 但因 get_vreversal 是 FastAPI endpoint, 这里直接执行 SQL
            hit_stocks = _query_vreversal(
                db, date_str, base_date, max_drawdown, min_close_up,
                min_intraday_drop, require_v_shape, min_sector_hit, max_sector_hit, view
            )

            if not hit_stocks:
                daily_stats.append({
                    "date": date_str,
                    "hit_count": 0,
                    "avg_t1": None, "avg_t3": None, "avg_t5": None,
                    "market_t1": None, "market_t3": None, "market_t5": None,
                })
                continue

            # 取命中股票的 ts_code 列表
            hit_codes = [s["ts_code"] for s in hit_stocks]

            # 算 T+1/T+3/T+5 的收益率
            future_returns = _compute_future_returns(
                db, hit_codes, trade_date, [1, 3, 5]
            )

            # 算大盘基准: 用全市场平均日涨跌幅累计 (不依赖指数表)
            market_returns = _compute_market_returns(
                db, trade_date, [1, 3, 5]
            )

            # _compute_future_returns 返回 {p: [(ts_code, ret), ...]}
            # 所以二元组取索引 1 (ret 值), 不是 p
            t1_list = [v[1] for v in future_returns.get(1, []) if v[1] is not None]
            t3_list = [v[1] for v in future_returns.get(3, []) if v[1] is not None]
            t5_list = [v[1] for v in future_returns.get(5, []) if v[1] is not None]

            avg_t1 = round(sum(t1_list) / len(t1_list), 2) if t1_list else None
            avg_t3 = round(sum(t3_list) / len(t3_list), 2) if t3_list else None
            avg_t5 = round(sum(t5_list) / len(t5_list), 2) if t5_list else None

            if avg_t1 is not None: all_returns_t1.extend(t1_list)
            if avg_t3 is not None: all_returns_t3.extend(t3_list)
            if avg_t5 is not None: all_returns_t5.extend(t5_list)

            daily_stats.append({
                "date": date_str,
                "hit_count": len(hit_stocks),
                "avg_t1": avg_t1, "avg_t3": avg_t3, "avg_t5": avg_t5,
                "market_t1": market_returns.get(1),
                "market_t3": market_returns.get(3),
                "market_t5": market_returns.get(5),
            })

        # 汇总
        win_rate_t1 = round(sum(1 for r in all_returns_t1 if r > 0) / len(all_returns_t1) * 100, 2) if all_returns_t1 else 0
        win_rate_t3 = round(sum(1 for r in all_returns_t3 if r > 0) / len(all_returns_t3) * 100, 2) if all_returns_t3 else 0
        win_rate_t5 = round(sum(1 for r in all_returns_t5 if r > 0) / len(all_returns_t5) * 100, 2) if all_returns_t5 else 0

        summary = {
            "total_days": len(trade_dates_sorted),
            "total_hits": sum(d["hit_count"] for d in daily_stats),
            "avg_hit_per_day": round(sum(d["hit_count"] for d in daily_stats) / len(trade_dates_sorted), 1),
            "win_rate_t1": win_rate_t1,
            "win_rate_t3": win_rate_t3,
            "win_rate_t5": win_rate_t5,
            "avg_return_t1": round(sum(all_returns_t1) / len(all_returns_t1), 2) if all_returns_t1 else 0,
            "avg_return_t3": round(sum(all_returns_t3) / len(all_returns_t3), 2) if all_returns_t3 else 0,
            "avg_return_t5": round(sum(all_returns_t5) / len(all_returns_t5), 2) if all_returns_t5 else 0,
            "market_avg_t1": round(sum(d["market_t1"] for d in daily_stats if d["market_t1"] is not None) / max(1, sum(1 for d in daily_stats if d["market_t1"] is not None)), 2),
            "market_avg_t3": round(sum(d["market_t3"] for d in daily_stats if d["market_t3"] is not None) / max(1, sum(1 for d in daily_stats if d["market_t3"] is not None)), 2),
            "market_avg_t5": round(sum(d["market_t5"] for d in daily_stats if d["market_t5"] is not None) / max(1, sum(1 for d in daily_stats if d["market_t5"] is not None)), 2),
        }
        # 超额收益 = 策略 - 市场
        summary["excess_t1"] = round(summary["avg_return_t1"] - summary["market_avg_t1"], 2)
        summary["excess_t3"] = round(summary["avg_return_t3"] - summary["market_avg_t3"], 2)
        summary["excess_t5"] = round(summary["avg_return_t5"] - summary["market_avg_t5"], 2)

        return {"daily_stats": daily_stats, "summary": summary}


def _query_vreversal(db, date_str, base_date, max_drawdown, min_close_up,
                     min_intraday_drop, require_v_shape, min_sector_hit,
                     max_sector_hit, view):
    """复用筛选 SQL, 返回命中股票列表"""
    sql = text("""
    WITH base AS (
        SELECT ts_code, close AS base_close
        FROM stock_daily_kline
        WHERE trade_date = :base_date
    ),
    today AS (
        SELECT ts_code, open, high, low, close, pct_chg,
               close / NULLIF((1 + pct_chg / 100.0), 0) AS pre_close
        FROM stock_daily_kline
        WHERE trade_date = :trade_date
    ),
    filtered AS (
        SELECT t.ts_code, t.pct_chg AS today_pct,
               b.base_close,
               ROUND(((t.close - b.base_close) / b.base_close * 100)::numeric, 2) AS period_pct
        FROM today t
        JOIN base b ON b.ts_code = t.ts_code
        WHERE (t.close - b.base_close) / b.base_close >= -:max_drawdown_ratio
          -- 抗跌含义: 区间跌幅在 -max_drawdown% ~ 0% 之间
          AND (t.close - b.base_close) / b.base_close <= 0
          -- 今日收盘涨幅 (基础约束, 不受V形态影响)
          AND t.pct_chg >= CASE
              WHEN t.ts_code LIKE '688%' OR t.ts_code LIKE '689%'
                   OR t.ts_code LIKE '300%' OR t.ts_code LIKE '301%'
              THEN :min_close_up_chinext
              ELSE :min_close_up_main
          END
          -- V 形态约束(可选): 盘中曾跌破 -min_intraday_drop%
          AND (
              NOT :require_v_shape
              OR (t.low - NULLIF(t.pre_close, 0)) / NULLIF(t.pre_close, 0) <= -:min_intraday_drop_ratio
          )
    ),
    stock_sector AS (
        SELECT DISTINCT ON (ts_code) ts_code, sector
        FROM stock_flow
        WHERE sector IS NOT NULL AND sector != ''
          AND trade_date >= :base_date
        ORDER BY ts_code, trade_date DESC
    ),
    enriched AS (
        SELECT f.*, s.sector,
               COUNT(*) OVER (PARTITION BY s.sector) AS sector_hit_count
        FROM filtered f
        LEFT JOIN stock_sector s ON s.ts_code = f.ts_code
    )
    SELECT ts_code, sector, today_pct, period_pct, sector_hit_count
    FROM enriched
    """)

    rows = db.execute(sql, {
        "base_date": base_date,
        "trade_date": date_str,
        "max_drawdown_ratio": max_drawdown / 100.0,
        "require_v_shape": require_v_shape,
        "min_intraday_drop": min_intraday_drop,
        "min_intraday_drop_ratio": min_intraday_drop / 100.0,
        "min_close_up_main": min_close_up,
        "min_close_up_chinext": min_close_up * 1.5,
    }).fetchall()

    all_stocks = [{
        "ts_code": r.ts_code,
        "sector": r.sector,
        "sector_hit_count": int(r.sector_hit_count) if r.sector else 0,
    } for r in rows]

    if view == "sector":
        return [s for s in all_stocks
                if s["sector"]
                and s["sector_hit_count"] >= min_sector_hit
                and s["sector_hit_count"] <= max_sector_hit]
    else:
        return [s for s in all_stocks
                if not s["sector"] or s["sector_hit_count"] <= max_sector_hit]


def _compute_future_returns(db, ts_codes: list, base_date, periods: list) -> dict:
    """算命中股票在 T+N 的收益率(基于收盘价)

    Args:
        db: DB session
        ts_codes: 命中股票代码列表
        base_date: 基准日 (命中日, 即 T 日)
        periods: [1, 3, 5]

    Returns: {1: [(ts_code, t1_return), ...], 3: ..., 5: ...}
    """
    if not ts_codes:
        return {p: [] for p in periods}

    # 取 base_date 后 periods_max 个交易日的收盘价
    max_p = max(periods)
    placeholders = ','.join([f":c{i}" for i in range(len(ts_codes))])
    params = {f"c{i}": c for i, c in enumerate(ts_codes)}
    params["base_date"] = base_date
    params["limit"] = max_p + 1

    sql = text(f"""
    WITH future_dates AS (
        SELECT trade_date,
               ROW_NUMBER() OVER (ORDER BY trade_date) AS rn
        FROM (
            SELECT DISTINCT trade_date
            FROM stock_daily_kline
            WHERE trade_date > :base_date
            ORDER BY trade_date
            LIMIT :limit
        ) sub
    )
    SELECT k.ts_code, k.trade_date, k.close,
           fd.rn
    FROM stock_daily_kline k
    JOIN future_dates fd ON fd.trade_date = k.trade_date
    WHERE k.ts_code IN ({placeholders})
      AND k.trade_date > :base_date
    """)

    rows = db.execute(sql, params).fetchall()

    # 组织为 {ts_code: {rn: close}}
    by_code = {}
    # 注意: SQLAlchemy Row 对象不能直接 dict() 转 {col: val},
    # 必须用 r[0]: r[1] 显式取列
    base_closes = {
        r[0]: float(r[1]) for r in db.execute(text(
            "SELECT ts_code, close FROM stock_daily_kline "
            "WHERE trade_date = :d AND ts_code IN " + f"({placeholders})"
        ), {**params, "d": base_date}).fetchall()
        if r[1] is not None
    }

    for r in rows:
        by_code.setdefault(r.ts_code, {})[r.rn] = float(r.close) if r.close is not None else None

    result = {p: [] for p in periods}
    for code in ts_codes:
        base = base_closes.get(code)
        if not base:
            continue
        for p in periods:
            future_close = by_code.get(code, {}).get(p)
            if future_close:
                ret = round((future_close - base) / base * 100, 2)
                result[p].append((code, ret))

    return result


def _compute_market_returns(db, base_date, periods: list) -> dict:
    """算大盘基准: 用全市场平均日涨跌幅累计

    每日市场收益率 = AVG(pct_chg) FROM stock_daily_kline WHERE trade_date = X
    T+N 累计 = ((1+r1)*(1+r2)*...*(1+rN) - 1) * 100

    Args:
        db: DB session
        base_date: 命中日 (T 日)
        periods: [1, 3, 5]

    Returns: {1: t1_return, 3: t3_return, 5: t5_return}
    """
    max_p = max(periods)
    sql = text("""
    WITH future_dates AS (
        SELECT trade_date,
               ROW_NUMBER() OVER (ORDER BY trade_date) AS rn
        FROM (
            SELECT DISTINCT trade_date
            FROM stock_daily_kline
            WHERE trade_date > :base_date
            ORDER BY trade_date
            LIMIT :limit
        ) sub
    )
    SELECT fd.rn, AVG(k.pct_chg) AS avg_pct
    FROM stock_daily_kline k
    JOIN future_dates fd ON fd.trade_date = k.trade_date
    WHERE k.pct_chg IS NOT NULL
    GROUP BY fd.rn
    """)

    rows = db.execute(sql, {"base_date": base_date, "limit": max_p}).fetchall()
    daily_avg = {
        r.rn: float(r.avg_pct) if r.avg_pct is not None else None
        for r in rows
    }

    result = {}
    for p in periods:
        if not daily_avg:
            result[p] = None
            continue
        # 检查 1~p 的数据是否齐全
        if any(daily_avg.get(i) is None for i in range(1, p + 1)):
            result[p] = None
            continue
        cum = 1.0
        for i in range(1, p + 1):
            cum *= (1 + daily_avg[i] / 100.0)
        result[p] = round((cum - 1) * 100, 2)

    return result
