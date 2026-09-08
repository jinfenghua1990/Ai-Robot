"""
策略共振股 20 天跟踪 API
- 入池：从 strategy_result 拉取当日多策略共振 (>=2) 命中的股票
- 每日盘后更新：拉行情 + BS 信号检查
- 撤离：BS 出现 S 点 → 撤离放入历史；或跟踪满 20 天自动到期
"""
import json
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query, HTTPException, Body
from sqlalchemy import func, desc

from db.session import get_db_session
from db.models import (
    StrategyResult,
    StockDailyKline,
    StrategyTrack,
    StrategyTrackDaily,
)
from services.strategy_runner import get_strategy_meta
from api.bs_signals import _generate_bs_signals

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# 序列化辅助
# ============================================================
def _f(v):
    """Decimal/None → float/None"""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def _d(v):
    """Date/DateTime/None → iso string/None"""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _parse_strategies(strategies_json):
    """解析 strategies_json 字段为 list"""
    if not strategies_json:
        return []
    try:
        return json.loads(strategies_json)
    except Exception:
        return []


def _serialize_daily(d):
    """序列化一条 StrategyTrackDaily"""
    return {
        "id": d.id,
        "tracker_id": d.tracker_id,
        "trade_date": _d(d.trade_date),
        "day_n": d.day_n,
        "open": _f(d.open),
        "high": _f(d.high),
        "low": _f(d.low),
        "close": _f(d.close),
        "pct_chg": _f(d.pct_chg),
        "cum_pct": _f(d.cum_pct),
        "volume": d.volume,
        "amount": _f(d.amount),
        "main_force_inflow": _f(d.main_force_inflow),
        "bs_signal": d.bs_signal,
        "bs_reason": d.bs_reason,
    }


def _serialize_tracker(db, t, include_daily=True, daily_limit=None):
    """序列化一条 StrategyTrack，可选附带 daily 数据"""
    row = {
        "id": t.id,
        "pool_date": _d(t.pool_date),
        "ts_code": t.ts_code,
        "name": t.name,
        "sector": t.sector,
        "strategies": _parse_strategies(t.strategies_json),
        "strategy_count": t.strategy_count,
        "pool_score": _f(t.pool_score),
        "pool_close": _f(t.pool_close),
        "track_days": t.track_days,
        "status": t.status,
        "exit_date": _d(t.exit_date),
        "exit_reason": t.exit_reason,
        "exit_price": _f(t.exit_price),
        "exit_return_pct": _f(t.exit_return_pct),
        "latest_day": t.latest_day,
        "latest_trade_date": _d(t.latest_trade_date),
        "latest_close": _f(t.latest_close),
        "latest_pct": _f(t.latest_pct),
        "latest_daily_chg": _f(t.latest_daily_chg),
        "latest_bs_signal": t.latest_bs_signal,
        "latest_bs_reason": t.latest_bs_reason,
        "max_return_pct": _f(t.max_return_pct),
        "min_return_pct": _f(t.min_return_pct),
        "created_at": _d(t.created_at),
        "updated_at": _d(t.updated_at),
    }
    if include_daily:
        q = (
            db.query(StrategyTrackDaily)
            .filter(StrategyTrackDaily.tracker_id == t.id)
            .order_by(StrategyTrackDaily.day_n.asc())
        )
        if daily_limit is not None:
            q = q.limit(daily_limit)
        row["daily"] = [_serialize_daily(d) for d in q.all()]
    return row


def _calc_bs_signals_for_klines(db, ts_code, end_date):
    """取最近 150 条 K 线（截止 end_date），调用 _generate_bs_signals，
    返回 {date_str: signal_dict} 字典。失败返回 {}。"""
    try:
        all_klines = (
            db.query(StockDailyKline)
            .filter(StockDailyKline.ts_code == ts_code)
            .filter(StockDailyKline.trade_date <= end_date)
            .order_by(StockDailyKline.trade_date.asc())
            .all()
        )
        if len(all_klines) < 20:
            return {}
        recent = all_klines[-150:] if len(all_klines) > 150 else all_klines
        klines = [
            {
                "date": k.trade_date.isoformat() if k.trade_date else None,
                "open": float(k.open) if k.open is not None else 0.0,
                "high": float(k.high) if k.high is not None else 0.0,
                "low": float(k.low) if k.low is not None else 0.0,
                "close": float(k.close) if k.close is not None else 0.0,
                "volume": int(k.volume) if k.volume is not None else 0,
            }
            for k in recent
        ]
        result = _generate_bs_signals(klines, period=10, multiplier=1.0)
        # _generate_bs_signals 实际返回元组 (signals, dif, dea, macd, ...)
        if isinstance(result, tuple) and len(result) > 0:
            signals = result[0]
        elif isinstance(result, list):
            signals = result
        else:
            signals = []
        bs_by_date = {}
        for sig in signals:
            if isinstance(sig, dict) and sig.get("date"):
                bs_by_date[sig["date"]] = sig
        return bs_by_date
    except Exception as e:
        logger.warning(f"[strategy_track] BS signal calc failed for {ts_code}: {e}")
        return {}


# ============================================================
# GET /api/strategy-track/list
# ============================================================
@router.get("/api/strategy-track/list")
def list_trackers(
    status: str = Query("active", description="状态过滤: active / exited / expired / all"),
    pool_date: str = Query(None, description="入池日期 YYYY-MM-DD"),
):
    """获取跟踪列表（默认 active），含每日明细和统计摘要"""
    with get_db_session() as db:
        q = db.query(StrategyTrack)
        if status and status != "all":
            q = q.filter(StrategyTrack.status == status)
        if pool_date:
            try:
                pd = datetime.strptime(pool_date, "%Y-%m-%d").date()
                q = q.filter(StrategyTrack.pool_date == pd)
            except ValueError:
                raise HTTPException(status_code=400, detail="pool_date 格式应为 YYYY-MM-DD")
        q = q.order_by(desc(StrategyTrack.pool_date), desc(StrategyTrack.strategy_count))
        trackers = q.all()
        rows = [_serialize_tracker(db, t, include_daily=True, daily_limit=20) for t in trackers]

        # 统计摘要：total 跟随当前 filter；active/exited/expired 为全局统计
        total = len(trackers)
        active_count = (
            db.query(func.count(StrategyTrack.id))
            .filter(StrategyTrack.status == "active")
            .scalar()
            or 0
        )
        exited_count = (
            db.query(func.count(StrategyTrack.id))
            .filter(StrategyTrack.status == "exited")
            .scalar()
            or 0
        )
        expired_count = (
            db.query(func.count(StrategyTrack.id))
            .filter(StrategyTrack.status == "expired")
            .scalar()
            or 0
        )

        # avg/win/max/min 基于 active（当前 rows 中 status==active 的）
        active_pcts = [
            r["latest_pct"]
            for r in rows
            if r["status"] == "active" and r["latest_pct"] is not None
        ]
        if active_pcts:
            avg_return = round(sum(active_pcts) / len(active_pcts), 2)
            win_rate = round(sum(1 for p in active_pcts if p > 0) / len(active_pcts), 4)
            max_return = round(max(active_pcts), 2)
            min_return = round(min(active_pcts), 2)
        else:
            avg_return = 0.0
            win_rate = 0.0
            max_return = 0.0
            min_return = 0.0

        return {
            "rows": rows,
            "summary": {
                "total": total,
                "active": active_count,
                "exited": exited_count,
                "expired": expired_count,
                "avg_return": avg_return,
                "win_rate": win_rate,
                "max_return": max_return,
                "min_return": min_return,
            },
        }


# ============================================================
# GET /api/strategy-track/history
# ============================================================
@router.get("/api/strategy-track/history")
def list_history(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """获取已撤离/已到期的跟踪记录"""
    with get_db_session() as db:
        q = db.query(StrategyTrack).filter(
            StrategyTrack.status.in_(["exited", "expired"])
        )
        q = q.order_by(desc(StrategyTrack.exit_date), desc(StrategyTrack.pool_date))
        total = q.count()
        trackers = q.offset(offset).limit(limit).all()
        rows = [_serialize_tracker(db, t, include_daily=True) for t in trackers]
        return {"rows": rows, "total": total}


# ============================================================
# GET /api/strategy-track/stock/{ts_code}
# ============================================================
@router.get("/api/strategy-track/stock/{ts_code}")
def get_stock_tracker(ts_code: str):
    """获取某只股票最新的 active 跟踪记录（含完整 daily）"""
    with get_db_session() as db:
        t = (
            db.query(StrategyTrack)
            .filter(StrategyTrack.ts_code == ts_code)
            .order_by(desc(StrategyTrack.pool_date))
            .first()
        )
        if not t:
            raise HTTPException(status_code=404, detail=f"未找到 {ts_code} 的跟踪记录")
        tracker = _serialize_tracker(db, t, include_daily=False)
        daily = (
            db.query(StrategyTrackDaily)
            .filter(StrategyTrackDaily.tracker_id == t.id)
            .order_by(StrategyTrackDaily.day_n.asc())
            .all()
        )
        return {"tracker": tracker, "daily": [_serialize_daily(d) for d in daily]}


# ============================================================
# POST /api/strategy-track/pool
# ============================================================
@router.post("/api/strategy-track/pool")
def pool_trackers(
    date: str = Query(None, description="入池日期 YYYY-MM-DD（默认昨天或今天）"),
    min_count: int = Query(2, ge=1, description="最少命中策略数"),
):
    """从 strategy_result 拉取当日多策略共振命中的股票入池"""
    # 确定入池日期
    if date:
        try:
            pool_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date 格式应为 YYYY-MM-DD")
    else:
        today = datetime.now().date()
        with get_db_session() as db:
            today_count = (
                db.query(StrategyResult)
                .filter(StrategyResult.trade_date == today)
                .count()
            )
            pool_date = today if today_count > 0 else today - timedelta(days=1)

    added = []
    skipped_duplicates = []

    with get_db_session() as db:
        # 查询当日所有 strategy_result，排除 risk_exit
        rows = (
            db.query(StrategyResult)
            .filter(StrategyResult.trade_date == pool_date)
            .filter(StrategyResult.strategy_key != "risk_exit")
            .all()
        )
        # 按 ts_code 聚合
        stock_map = {}
        for r in rows:
            stock_map.setdefault(r.ts_code, []).append(r)

        for ts_code, srs in stock_map.items():
            if len(srs) < min_count:
                continue
            # 检查是否已存在
            exists = (
                db.query(StrategyTrack)
                .filter(StrategyTrack.pool_date == pool_date)
                .filter(StrategyTrack.ts_code == ts_code)
                .first()
            )
            if exists:
                skipped_duplicates.append(
                    {
                        "ts_code": ts_code,
                        "name": srs[0].name,
                        "strategy_count": len(srs),
                    }
                )
                continue

            # 获取入池当日收盘价
            kline = (
                db.query(StockDailyKline)
                .filter(StockDailyKline.ts_code == ts_code)
                .filter(StockDailyKline.trade_date == pool_date)
                .first()
            )
            pool_close = (
                float(kline.close) if (kline and kline.close is not None) else None
            )

            # 构造 strategies_json
            strategies_list = []
            total_score = 0.0
            for r in srs:
                meta = get_strategy_meta(r.strategy_key) or {}
                item = {
                    "key": r.strategy_key,
                    "name": r.strategy_name or meta.get("name", r.strategy_key),
                    "icon": meta.get("icon", ""),
                    "score": _f(r.score) if _f(r.score) is not None else 0,
                }
                strategies_list.append(item)
                if r.score is not None:
                    total_score += float(r.score)

            first = srs[0]
            tracker = StrategyTrack(
                pool_date=pool_date,
                ts_code=ts_code,
                name=first.name,
                sector=first.sector,
                strategies_json=json.dumps(strategies_list, ensure_ascii=False),
                strategy_count=len(srs),
                pool_score=round(total_score, 2),
                pool_close=pool_close,
                track_days=20,
                status="active",
                latest_day=0,
            )
            db.add(tracker)
            db.commit()
            db.refresh(tracker)
            added.append(
                {
                    "id": tracker.id,
                    "ts_code": ts_code,
                    "name": first.name,
                    "sector": first.sector,
                    "strategy_count": len(srs),
                    "pool_score": round(total_score, 2),
                    "pool_close": pool_close,
                    "strategies": strategies_list,
                }
            )

    return {
        "pool_date": pool_date.isoformat(),
        "added": added,
        "skipped_duplicates": skipped_duplicates,
        "total_added": len(added),
    }


# ============================================================
# POST /api/strategy-track/daily-update
# ============================================================
@router.post("/api/strategy-track/daily-update")
def daily_update():
    """更新所有 active 跟踪记录的当日行情 + BS 信号检查"""
    updated = []
    exited = []
    expired = []

    with get_db_session() as db:
        active_trackers = (
            db.query(StrategyTrack).filter(StrategyTrack.status == "active").all()
        )

        for t in active_trackers:
            try:
                # 1. 找到需要更新的交易日（trade_date > pool_date 且未在 daily 中）
                existing_dates_rows = (
                    db.query(StrategyTrackDaily.trade_date)
                    .filter(StrategyTrackDaily.tracker_id == t.id)
                    .all()
                )
                existing_dates = {row[0] for row in existing_dates_rows}
                existing_count = len(existing_dates)

                candidates = (
                    db.query(StockDailyKline)
                    .filter(StockDailyKline.ts_code == t.ts_code)
                    .filter(StockDailyKline.trade_date > t.pool_date)
                    .filter(
                        ~StockDailyKline.trade_date.in_(existing_dates)
                        if existing_dates
                        else True
                    )
                    .order_by(StockDailyKline.trade_date.asc())
                    .all()
                )

                if not candidates:
                    continue

                # 2. 计算 BS 信号（基于截止最后候选日的最近 150 条 K 线）
                last_trade_date = candidates[-1].trade_date
                bs_by_date = _calc_bs_signals_for_klines(db, t.ts_code, last_trade_date)

                # 3. 逐日插入 daily 记录
                pool_close = (
                    float(t.pool_close) if t.pool_close is not None else None
                )
                last_inserted_day_n = existing_count
                last_inserted_close = None
                last_inserted_trade_date = None
                last_inserted_pct = None
                last_inserted_daily_chg = None
                last_inserted_bs_signal = None
                last_inserted_bs_reason = None
                new_exited = False
                new_expired = False

                cur_max = (
                    float(t.max_return_pct)
                    if t.max_return_pct is not None
                    else None
                )
                cur_min = (
                    float(t.min_return_pct)
                    if t.min_return_pct is not None
                    else None
                )

                for k in candidates:
                    last_inserted_day_n += 1
                    close = float(k.close) if k.close is not None else 0.0
                    daily_chg = (
                        float(k.pct_chg) if k.pct_chg is not None else None
                    )
                    cum_pct = None
                    if pool_close and pool_close > 0:
                        cum_pct = round((close - pool_close) / pool_close * 100, 2)

                    kdate_str = (
                        k.trade_date.isoformat() if k.trade_date else None
                    )
                    sig = bs_by_date.get(kdate_str)
                    bs_signal = sig.get("type") if sig else None
                    bs_reason = None
                    if sig and sig.get("reasons"):
                        bs_reason = "; ".join(sig["reasons"])

                    daily_row = StrategyTrackDaily(
                        tracker_id=t.id,
                        trade_date=k.trade_date,
                        day_n=last_inserted_day_n,
                        open=float(k.open) if k.open is not None else None,
                        high=float(k.high) if k.high is not None else None,
                        low=float(k.low) if k.low is not None else None,
                        close=close,
                        pct_chg=daily_chg,
                        cum_pct=cum_pct,
                        volume=k.volume,
                        amount=float(k.amount) if k.amount is not None else None,
                        main_force_inflow=(
                            float(k.main_force_inflow)
                            if k.main_force_inflow is not None
                            else None
                        ),
                        bs_signal=bs_signal,
                        bs_reason=bs_reason,
                    )
                    db.add(daily_row)

                    if cum_pct is not None:
                        if cur_max is None or cum_pct > cur_max:
                            cur_max = cum_pct
                        if cur_min is None or cum_pct < cur_min:
                            cur_min = cum_pct

                    last_inserted_close = close
                    last_inserted_trade_date = k.trade_date
                    last_inserted_pct = cum_pct
                    last_inserted_daily_chg = daily_chg
                    last_inserted_bs_signal = bs_signal
                    last_inserted_bs_reason = bs_reason

                    # S 点撤离
                    if bs_signal == "S":
                        new_exited = True
                        break
                    # 满 track_days 到期
                    if last_inserted_day_n >= (t.track_days or 20):
                        new_expired = True
                        break

                if last_inserted_day_n == existing_count:
                    # 没有新数据可插入
                    db.rollback()
                    continue

                # 更新主表
                t.latest_day = last_inserted_day_n
                t.latest_trade_date = last_inserted_trade_date
                t.latest_close = last_inserted_close
                t.latest_pct = last_inserted_pct
                t.latest_daily_chg = last_inserted_daily_chg
                t.latest_bs_signal = last_inserted_bs_signal
                t.latest_bs_reason = last_inserted_bs_reason
                t.max_return_pct = cur_max
                t.min_return_pct = cur_min

                if new_exited:
                    t.status = "exited"
                    t.exit_date = last_inserted_trade_date
                    t.exit_reason = "BS_S_SIGNAL"
                    t.exit_price = last_inserted_close
                    t.exit_return_pct = last_inserted_pct
                    exited.append(
                        {
                            "ts_code": t.ts_code,
                            "name": t.name,
                            "reason": "BS_S_SIGNAL",
                            "return_pct": last_inserted_pct,
                            "exit_date": (
                                last_inserted_trade_date.isoformat()
                                if last_inserted_trade_date
                                else None
                            ),
                        }
                    )
                elif new_expired:
                    t.status = "expired"
                    t.exit_date = last_inserted_trade_date
                    t.exit_reason = "MAX_DAYS_REACHED"
                    t.exit_price = last_inserted_close
                    t.exit_return_pct = last_inserted_pct
                    expired.append(
                        {
                            "ts_code": t.ts_code,
                            "name": t.name,
                            "reason": "MAX_DAYS_REACHED",
                            "return_pct": last_inserted_pct,
                            "exit_date": (
                                last_inserted_trade_date.isoformat()
                                if last_inserted_trade_date
                                else None
                            ),
                        }
                    )

                updated.append(
                    {
                        "ts_code": t.ts_code,
                        "name": t.name,
                        "day_n": last_inserted_day_n,
                        "close": last_inserted_close,
                        "bs_signal": last_inserted_bs_signal,
                    }
                )

                db.commit()
            except Exception as e:
                logger.exception(
                    f"[strategy_track] daily-update error for {t.ts_code}: {e}"
                )
                db.rollback()
                continue

    return {
        "updated": updated,
        "exited": exited,
        "expired": expired,
        "total_updated": len(updated),
        "total_exited": len(exited),
        "total_expired": len(expired),
    }


# ============================================================
# POST /api/strategy-track/manual-exit
# ============================================================
@router.post("/api/strategy-track/manual-exit")
def manual_exit(payload: dict = Body(...)):
    """手动撤离跟踪记录
    Body: {"tracker_id": int, "reason": str = "MANUAL"}
    """
    tracker_id = payload.get("tracker_id")
    if not tracker_id:
        raise HTTPException(status_code=400, detail="缺少 tracker_id")
    reason = payload.get("reason") or "MANUAL"

    with get_db_session() as db:
        t = db.query(StrategyTrack).filter(StrategyTrack.id == tracker_id).first()
        if not t:
            raise HTTPException(
                status_code=404, detail=f"未找到 tracker_id={tracker_id}"
            )
        if t.status != "active":
            raise HTTPException(
                status_code=400,
                detail=f"跟踪记录当前状态为 {t.status}，无法撤离",
            )
        today = datetime.now().date()
        t.status = "exited"
        t.exit_date = today
        t.exit_reason = reason
        t.exit_price = t.latest_close
        t.exit_return_pct = t.latest_pct
        db.commit()
        db.refresh(t)
        tracker = _serialize_tracker(db, t, include_daily=False)
        return {"tracker": tracker}
