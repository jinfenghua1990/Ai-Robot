# -*- coding: utf-8 -*-
"""横盘蓄势策略 API（A股）

GET  /api/a-horizontal/scan     当日扫描结果（过滤/排序/分页）
GET  /api/a-horizontal/market   大盘环境与板块概况
GET  /api/a-horizontal/detail   单股详情（箱体+量价+评分明细）
GET  /api/a-horizontal/history  单股历史信号跟踪
POST /api/a-horizontal/run      手动触发一次全市场扫描
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import func as sql_func

from db.session import get_db_session
from db.models import HorizontalSignal, HorizontalTrack
from strategies.horizontal.runner import run_scan
from strategies.horizontal.market_filter import latest_trade_date, market_snapshot
from strategies.horizontal.tracker import track_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/a-horizontal", tags=["a-horizontal"])

_scan_lock = threading.Lock()

# 扫描状态（供前端轮询判断完成）
_scan_state = {"running": False, "last_done": None, "started_at": None}


def _row_to_dict(r) -> dict:
    return {
        "ts_code": r.ts_code,
        "name": r.name,
        "sector": r.sector,
        "state": r.state,
        "signal_code": r.signal_code,
        "signal_detail": r.signal_detail,
        "grade": r.grade,
        "score": r.score,
        "score_detail": json.loads(r.score_detail or "{}"),
        "tradable": r.tradable,
        "box_high": r.box_high,
        "box_low": r.box_low,
        "box_days": r.box_days,
        "amplitude": r.amplitude,
        "dist_to_break": r.dist_to_break,
        "close_pos_in_box": r.close_pos_in_box,
        "ma20_drift": r.ma20_drift,
        "atr_ratio": r.atr_ratio,
        "up_dn_vol_ratio": r.up_dn_vol_ratio,
        "vol_ratio_5_20": r.vol_ratio_5_20,
        "price_gravity": r.price_gravity,
        "risk_reward": r.risk_reward,
        "market_ok": r.market_ok,
        "sector_ok": r.sector_ok,
        "sector_rank_pct": r.sector_rank_pct,
        "close": r.close,
        "pct_chg": r.pct_chg,
        "amount_20": r.amount_20,
    }


@router.get("/scan")
def scan(
    trade_date: Optional[str] = Query(None),
    state: str = Query("", description="横盘观察/接近突破/突破启动/回踩确认/突破失败/全部"),
    grade: str = Query("", description="核心候选/重点观察/普通观察"),
    min_score: float = Query(0),
    only_tradable: bool = Query(False),
    only_signal: bool = Query(False),
    sector: str = Query(""),
    sort: str = Query("score", description="score/amplitude/ret"),
    order: str = Query("desc"),
    limit: int = Query(100, le=300),
):
    """当日扫描结果列表"""
    d = trade_date or latest_trade_date()
    if not d:
        return {"ok": False, "error": "无行情数据"}
    with get_db_session() as db:
        q = db.query(HorizontalSignal).filter(HorizontalSignal.trade_date == date.fromisoformat(d))
        if state and state != "全部":
            q = q.filter(HorizontalSignal.state == state)
        if grade:
            q = q.filter(HorizontalSignal.grade == grade)
        if min_score > 0:
            q = q.filter(HorizontalSignal.score >= min_score)
        if only_tradable:
            q = q.filter(HorizontalSignal.tradable.is_(True))
        if only_signal:
            q = q.filter(HorizontalSignal.signal_code.isnot(None))
        if sector:
            q = q.filter(HorizontalSignal.sector == sector)
        total = q.count()
        col = {
            "score": HorizontalSignal.score,
            "amplitude": HorizontalSignal.amplitude,
        }.get(sort, HorizontalSignal.score)
        rows = q.order_by(col.desc() if order == "desc" else col.asc()).limit(limit).all()
        items = [_row_to_dict(r) for r in rows]

    # 状态与信号统计
    with get_db_session() as db:
        states = dict(
            db.query(HorizontalSignal.state, sql_func.count())
            .filter(HorizontalSignal.trade_date == date.fromisoformat(d))
            .group_by(HorizontalSignal.state).all()
        )
        signals = dict(
            db.query(HorizontalSignal.signal_code, sql_func.count())
            .filter(
                HorizontalSignal.trade_date == date.fromisoformat(d),
                HorizontalSignal.signal_code.isnot(None),
            )
            .group_by(HorizontalSignal.signal_code).all()
        )
        tradable_n = (
            db.query(sql_func.count())
            .filter(
                HorizontalSignal.trade_date == date.fromisoformat(d),
                HorizontalSignal.tradable.is_(True),
            )
            .scalar()
        )
    return {
        "ok": True,
        "trade_date": d,
        "total": total,
        "items": items,
        "stats": {
            "states": {k: v for k, v in sorted(states.items())},
            "signals": {k: v for k, v in sorted(signals.items())},
            "tradable": tradable_n or 0,
        },
    }


@router.get("/market")
def market():
    """大盘环境 + 时段说明（盘后圈股）· SQL 聚合快照 + 缓存"""
    return {"ok": True, "market": market_snapshot()}


@router.get("/detail")
def detail(code: str = Query(..., description="ts_code 如 000001.SZ"), trade_date: Optional[str] = Query(None)):
    """单股横盘详情"""
    d = trade_date or latest_trade_date()
    if not d:
        return {"ok": False, "error": "无行情数据"}
    with get_db_session() as db:
        r = (
            db.query(HorizontalSignal)
            .filter(
                HorizontalSignal.ts_code == code,
                HorizontalSignal.trade_date == date.fromisoformat(d),
            )
            .first()
        )
        if not r:
            return {"ok": False, "error": "该股票当日无横盘信号"}
        item = _row_to_dict(r)
    return {"ok": True, "trade_date": d, "item": item}


@router.get("/history")
def history(code: str = Query(...), limit: int = Query(30, le=120)):
    """单股历史横盘信号跟踪（看信号后走势）"""
    with get_db_session() as db:
        rows = (
            db.query(HorizontalSignal)
            .filter(HorizontalSignal.ts_code == code)
            .order_by(HorizontalSignal.trade_date.desc())
            .limit(limit)
            .all()
        )
        items = [
            {
                "trade_date": str(r.trade_date),
                "state": r.state,
                "signal_code": r.signal_code,
                "score": r.score,
                "close": r.close,
                "box_high": r.box_high,
                "box_low": r.box_low,
                "dist_to_break": r.dist_to_break,
            }
            for r in rows
        ]
    return {"ok": True, "items": items}


@router.get("/performance")
def performance():
    """横盘策略信号后走势（胜率/盈亏比）汇总

    基于 horizontal_track：对 A/B/C/D 信号按持有 5/10/20 交易日统计
    获胜率、平均收益、平均盈/亏、盈亏比。用于评估策略实战表现。
    """
    data = track_summary()
    return {"ok": True, **data}


@router.post("/run")
def run():
    """手动触发全市场扫描（后台执行，立即返回）"""
    if _scan_lock.locked():
        return {"ok": False, "error": "扫描正在进行中"}
    _scan_state["running"] = True
    _scan_state["started_at"] = time.time()
    threading.Thread(target=_bg_scan, daemon=True).start()
    return {"ok": True, "message": "扫描已启动，稍后刷新查看结果"}


@router.get("/run/status")
def run_status():
    """扫描运行状态：running / last_done（毫秒时间戳）"""
    return {
        "ok": True,
        "running": bool(_scan_state["running"]),
        "started_at": _scan_state["started_at"],
        "last_done": _scan_state["last_done"],
    }


def _bg_scan():
    with _scan_lock:
        try:
            run_scan()
            _scan_state["last_done"] = time.time()
        except Exception:
            logger.exception("横盘扫描失败")
        finally:
            _scan_state["running"] = False
