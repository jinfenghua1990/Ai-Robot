"""连板梯队 API（A股）—— 移植自 tickflow-stock-panel 的连板梯队设计。

数据：本地 stock_daily_kline（最近 20 个交易日，一次拉取全市场），Python 分组计算：
  - 连续涨停天数（含当日）：pct_chg ≥ 涨跌停幅度×0.95
  - 炸板预警：当日 high 触及涨停价但收盘未封住
  - 分层：首板 / 2板 / 3板 / 高位板(≥4)
  - 板块归属：StockFlow.sector 映射
"""
from __future__ import annotations

import sys
import os
import time
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, Query  # noqa: E402
from sqlalchemy import func as sql_func  # noqa: E402

router = APIRouter()

# 结果缓存：{target_date_str: data}，按交易日永久缓存。
# 盘后快照（日K）对给定交易日天然不可变，无需 TTL 过期；仅显式 nocache 才重算。
# size 上限裁剪防止内存膨胀（历史日期不会重复变化，命中即返回）。
_board_cache: dict = {}
_rot_cache: dict = {}  # key: f"{days}:{latest_date}"


def _cache_get(target: str):
    return _board_cache.get(target)


def _cache_set(target: str, data):
    _board_cache[target] = data
    if len(_board_cache) > 30:
        _board_cache.pop(next(iter(_board_cache)), None)


def _rot_cache_get(key: str):
    return _rot_cache.get(key)


def _rot_cache_set(key: str, data):
    _rot_cache[key] = data
    if len(_rot_cache) > 30:
        _rot_cache.pop(next(iter(_rot_cache)), None)


def _limit_pct(ts_code: str) -> float:
    c = ts_code.split(".")[0]
    if c.startswith(("688", "300", "301")):
        return 0.20
    if c.startswith(("8", "4")):
        return 0.30
    return 0.10


# ── 概念轮动（移植自 tickflow-stock-panel 的 concept_rotation_analyzer）────────────────
# 输入：近 N 日「板块涨停家数排名矩阵」→ 输出主线/新晋/退潮/机构/游资信号。

def _rotation_signals(dates_asc: list, columns: dict) -> dict:
    """从板块涨停家数排名矩阵计算轮动信号（纯函数，可脱离 AI 直接使用）。

    dates_asc: 日期列表（升序，最旧在前）；columns: {日期: [[板块名, 家数], ...]}（每列降序）
    返回 persistent_leaders(主线) / rising(新晋) / fading(退潮) / institutional(机构特征) / hot_money(游资特征)
    每项含 name, ranks(按升序日期), counts, avg_rank, rank_std
    """
    import math

    if not dates_asc or not columns:
        return {}
    # 收集每个板块在各日的（排名, 家数）。排名 = 该日在列中的索引 + 1
    board_data: dict = {}
    for d in dates_asc:
        col = columns.get(d) or []
        for idx, (name, cnt) in enumerate(col):
            board_data.setdefault(name, []).append((idx + 1, cnt))

    n_dates = len(dates_asc)

    def _stats(rc: list) -> dict:
        ranks = [r for r, _ in rc]
        counts = [c for _, c in rc]
        avg = sum(ranks) / len(ranks) if ranks else 0
        var = sum((r - avg) ** 2 for r in ranks) / len(ranks) if ranks else 0
        return {
            "ranks": ranks,
            "counts": counts,
            "avg_rank": round(avg, 1),
            "rank_std": round(math.sqrt(var), 1),
        }

    persistent, rising, fading, institutional, hot_money = [], [], [], [], []
    for name, rc in board_data.items():
        if len(rc) < n_dates:
            rc = rc + [(999, 0)] * (n_dates - len(rc))  # 缺失日补（大排名, 0 家数）
        s = _stats(rc)
        s["name"] = name
        ranks = s["ranks"]
        latest, earliest = ranks[-1], ranks[0]
        recent = ranks[-min(3, len(ranks)):]
        recent_avg = sum(recent) / len(recent)
        if recent_avg <= 10 and latest <= 10:
            persistent.append(s)  # 主线：近期稳居前 10
        jump = earliest - latest
        if earliest > 30 and latest <= 20 and jump >= 20:
            rising.append(s)  # 新晋：从后排冲进前 20
        drop = latest - earliest
        if earliest <= 10 and latest > 30 and drop >= 20:
            fading.append(s)  # 退潮：从前 10 滑落
        if s["rank_std"] <= 5 and s["avg_rank"] <= 20:
            institutional.append(s)  # 机构特征：排名稳定且靠前
        if s["rank_std"] >= 20:
            hot_money.append(s)  # 游资特征：排名波动大

    persistent.sort(key=lambda x: x["avg_rank"])
    rising.sort(key=lambda x: x["ranks"][0] - x["ranks"][-1], reverse=True)
    fading.sort(key=lambda x: x["ranks"][-1] - x["ranks"][0], reverse=True)
    institutional.sort(key=lambda x: (x["rank_std"], x["avg_rank"]))
    hot_money.sort(key=lambda x: x["rank_std"], reverse=True)

    top = 8
    return {
        "persistent_leaders": persistent[:top],
        "rising": rising[:top],
        "fading": fading[:top],
        "institutional": institutional[:top],
        "hot_money": hot_money[:top],
    }


def _boards_for(rows: list) -> tuple:
    """rows: 该股按日期升序的日K。返回 (最新日期, 今日连板数, 今日涨停, 今日炸板, 今日涨幅)。"""
    if not rows:
        return None, 0, False, False, 0.0
    last = rows[-1]
    lp = _limit_pct(last["ts_code"])
    n = 0
    for i in range(len(rows) - 1, 0, -1):
        prev_close = rows[i - 1]["close"]
        cur = rows[i]
        if prev_close > 0 and cur["close"] >= prev_close * (1 + lp) * 0.95:
            n += 1
        else:
            break
    # 当日是否封板
    today = rows[-1]
    yesterday_close = rows[-2]["close"] if len(rows) >= 2 and rows[-2]["close"] else 0
    limit_price = yesterday_close * (1 + lp) if yesterday_close > 0 else 0
    today_limit = bool(limit_price and today["close"] >= limit_price * 0.95)
    # 炸板：盘中触及涨停价但收盘未封住
    touched = bool(limit_price and today["high"] >= limit_price * 0.995)
    broken = touched and not today_limit
    change_pct = (today["close"] / yesterday_close - 1) * 100 if yesterday_close > 0 else 0.0
    return str(today["trade_date"]), n, today_limit, broken, round(change_pct, 2)


@router.get("/api/ladder/board")
def ladder_board(trade_date: str = Query("", description="YYYY-MM-DD，留空=最近交易日"),
                 nocache: bool = Query(False, description="跳过缓存强制重算（盘后快照通常无需）")):
    """连板梯队：分层统计 + 每层股票 + 炸板预警（同步端点，线程池执行 + 300s 缓存）。"""
    try:
        from db.session import get_db_session
        from db.models import StockDailyKline, StockFlow

        with get_db_session() as db:
            latest = db.query(sql_func.max(StockDailyKline.trade_date)).scalar()
            if latest is None:
                return {"ok": False, "data": None, "error": "本地K线库为空，请先同步日K"}
            target = date.fromisoformat(trade_date[:10]) if trade_date else latest
            target_s = str(target)
            if not nocache:
                cached = _cache_get(target_s)
                if cached is not None:
                    return {"ok": True, "data": cached, "error": None}
            # 一次拉最近 40 天（自然日），Python 侧截取 20 个交易日
            rows = db.query(StockDailyKline).filter(
                StockDailyKline.trade_date >= target - timedelta(days=40),
                StockDailyKline.trade_date <= target,
            ).order_by(StockDailyKline.ts_code, StockDailyKline.trade_date).all()

            # 名称/行业映射（StockFlow 最近记录）
            latest_flow = db.query(sql_func.max(StockFlow.id).label("max_id")).scalar()
            flow_rows = db.query(StockFlow).filter(StockFlow.id >= latest_flow - 30000).all()
            info: dict = {}
            for r in flow_rows:
                info.setdefault(r.ts_code, {"name": r.name, "sector": r.sector or ""})

            # 昨日对比数据（同一会话内取）
            prev_dates = sorted({str(r.trade_date) for r in rows if r.trade_date < target})
            yesterday_rows = []
            if prev_dates:
                yd = date.fromisoformat(prev_dates[-1])
                yesterday_rows = db.query(StockDailyKline).filter(
                    StockDailyKline.trade_date >= yd - timedelta(days=40),
                    StockDailyKline.trade_date <= yd,
                ).order_by(StockDailyKline.ts_code, StockDailyKline.trade_date).all()

        by_code: dict = defaultdict(list)
        for r in rows:
            by_code[r.ts_code].append({
                "ts_code": r.ts_code, "trade_date": r.trade_date,
                "open": float(r.open or 0), "high": float(r.high or 0),
                "low": float(r.low or 0), "close": float(r.close or 0),
                "pct_chg": float(r.pct_chg or 0),
            })

        # 只取 target 当日有数据的股票，且保留其近 20 个交易日
        target_date = target
        ladders: dict = {1: [], 2: [], 3: [], 4: []}  # 4 = 高位板(≥4)
        broken_board: list = []
        summary = {"date": str(target_date), "total_limit_up": 0, "ladder": {}}

        for code, krows in by_code.items():
            krows = [k for k in krows if k["trade_date"] <= target_date][-20:]
            if not krows or krows[-1]["trade_date"] != target_date:
                continue
            d, boards, is_limit, is_broken, change_pct = _boards_for(krows)
            if d is None or d != str(target_date):
                continue
            info_row = info.get(code, {"name": code, "sector": ""})
            item = {
                "code": code.replace(".SH", "").replace(".SZ", "").replace(".BJ", ""),
                "ts_code": code, "name": info_row["name"], "sector": info_row["sector"],
                "boards": boards, "change_pct": change_pct, "sealed": is_limit,
            }
            if is_broken:
                item["broken"] = True
                broken_board.append(item)
            if is_limit and boards >= 1:
                summary["total_limit_up"] += 1
                level = boards if boards <= 3 else 4
                ladders[level].append(item)

        # 排序：按涨幅降序
        for lv in ladders:
            ladders[lv].sort(key=lambda x: x["change_pct"], reverse=True)

        # 昨日对比（情绪温度）
        if yesterday_rows:
            y_by_code: dict = defaultdict(list)
            for r in yesterday_rows:
                y_by_code[r.ts_code].append(r)
            yd = yesterday_rows[-1].trade_date
            y_total = 0
            y_ladder = {}
            for code, kr in y_by_code.items():
                kr = [k for k in kr if k.trade_date <= yd][-20:]
                if not kr or kr[-1].trade_date != yd:
                    continue
                closes = [float(k.close or 0) for k in kr]
                lp = _limit_pct(code)
                n = 0
                for i in range(len(closes) - 1, 0, -1):
                    if closes[i - 1] > 0 and closes[i] >= closes[i - 1] * (1 + lp) * 0.95:
                        n += 1
                    else:
                        break
                if n >= 1:
                    y_total += 1
                    y_ladder[n] = y_ladder.get(n, 0) + 1

            high_today = sum(len(v) for k, v in ladders.items() if k >= 3)
            high_yest = sum(v for k, v in y_ladder.items() if k >= 3)
            summary["yesterday"] = {
                "date": str(yd), "total_limit_up": y_total,
                "high_board_count": high_yest,
            }
            summary["high_board_count"] = high_today
            summary["board_momentum"] = "升温" if high_today > high_yest else ("降温" if high_today < high_yest else "持平")
            summary["prev_date"] = str(yd)

        def _lvl(lv, label, min_b, max_b):
            return {"level": lv, "label": label, "min_boards": min_b, "max_boards": max_b,
                    "count": len(ladders[lv]), "stocks": ladders[lv]}

        data = {
            "summary": summary,
            "ladders": [
                _lvl(4, "高位板 (≥4连板)", 4, 99),
                _lvl(3, "3连板", 3, 3),
                _lvl(2, "2连板", 2, 2),
                _lvl(1, "首板", 1, 1),
            ],
            "broken_board": broken_board,
        }
        _cache_set(target_s, data)
        return {"ok": True, "data": data, "error": None}
    except Exception as e:
        return {"ok": False, "data": None, "error": str(e)}


@router.get("/api/ladder/rotation")
def ladder_rotation(days: int = Query(12, ge=3, le=30),
                    nocache: bool = Query(False, description="跳过缓存强制重算")):
    """概念轮动：近 N 个交易日「板块涨停家数排名矩阵」→ 主线/新晋/退潮/机构/游资信号。

    数据完全来自本地 K 线 + StockFlow 板块映射（无需外部数据源）。
    排名口径：每日各板块涨停家数降序；涨停 = 收盘 ≥ 昨收×(1+涨跌停幅度)×0.95。
    """
    try:
        from db.session import get_db_session
        from db.models import StockDailyKline, StockFlow

        with get_db_session() as db:
            latest = db.query(sql_func.max(StockDailyKline.trade_date)).scalar()
            if latest is None:
                return {"ok": False, "data": None, "error": "本地K线库为空，请先同步日K"}

            # 盘后快照按 (days, 最新交易日) 永久缓存：同一天数据不变，避免每次重算全市场矩阵
            rot_key = f"{days}:{latest}"
            if not nocache:
                rot_hit = _rot_cache_get(rot_key)
                if rot_hit is not None:
                    return {"ok": True, "data": rot_hit, "error": None}

            # 最近 N 个交易日（升序）
            all_dates = [r[0] for r in db.query(StockDailyKline.trade_date).distinct().order_by(
                StockDailyKline.trade_date.desc()).limit(days).all()]
            all_dates = list(reversed(all_dates))
            if len(all_dates) < 2:
                return {"ok": True, "data": {"dates": all_dates, "signals": {}}, "error": None}

            # 拉 N+2 日（含每个交易日前一收盘价）
            span_start = all_dates[0] - timedelta(days=3 * len(all_dates))
            rows = db.query(StockDailyKline.ts_code, StockDailyKline.trade_date,
                            StockDailyKline.close).filter(
                StockDailyKline.trade_date >= span_start,
                StockDailyKline.trade_date <= all_dates[-1],
            ).order_by(StockDailyKline.ts_code, StockDailyKline.trade_date).all()

            latest_flow = db.query(sql_func.max(StockFlow.id).label("max_id")).scalar()
            flow_rows = db.query(StockFlow).filter(StockFlow.id >= latest_flow - 30000).all()
            sector_map: dict = {}
            for r in flow_rows:
                sector_map.setdefault(r.ts_code, r.sector or "")

        # 每股每日收盘序列（升序）
        by_code: dict = defaultdict(list)
        for r in rows:
            by_code[r.ts_code].append((r.trade_date, float(r.close or 0)))

        # 每日板块涨停家数矩阵
        columns: dict = {}
        for d in all_dates:
            counts: dict = defaultdict(int)
            for code, seq in by_code.items():
                seq = [x for x in seq if x[0] <= d]
                if len(seq) < 2 or seq[-1][0] != d:
                    continue
                prev_close = seq[-2][1]
                if prev_close <= 0:
                    continue
                if seq[-1][1] >= prev_close * (1 + _limit_pct(code)) * 0.95:
                    sector = sector_map.get(code) or "其他"
                    counts[sector] += 1
            ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
            columns[str(d)] = [[k, v] for k, v in ranked if v > 0]

        # 注意：columns 的键是字符串日期，dates_asc 必须同为字符串才能命中
        signals = _rotation_signals([str(d) for d in all_dates], columns)
        data = {
            "dates": [str(d) for d in all_dates],
            "columns": {str(k): v for k, v in columns.items()},
            "signals": signals,
            "summary": {
                "main_lines": [s["name"] for s in signals.get("persistent_leaders", [])[:3]],
                "rising": len(signals.get("rising", [])),
                "fading": len(signals.get("fading", [])),
            },
        }
        _rot_cache_set(rot_key, data)
        return {"ok": True, "data": data, "error": None}
    except Exception as e:
        return {"ok": False, "data": None, "error": str(e)}
