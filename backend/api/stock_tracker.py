"""
股票跟踪 API
- 选中股票加入跟踪 → 记录入选价 → 每日自动计算 1-30 日涨跌
- 支持增删查操作
"""
from datetime import date, datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db.session import get_db_session
from db.models import StockTracker, StockTrackerDaily, StockDailyKline, StockFlow
from sqlalchemy import func, and_

router = APIRouter()


class AddStockRequest(BaseModel):
    stock_code: str
    stock_name: str
    note: str = ""


class UpdateNoteRequest(BaseModel):
    note: str


def _summarize_returns(values: list[float]) -> dict:
    """汇总跟踪样本收益，不把没有仓位信息的样本表现伪装成账户收益。"""
    normalized = [float(value) for value in values if value is not None]
    count = len(normalized)
    positive = sum(value > 0 for value in normalized)
    negative = sum(value < 0 for value in normalized)
    return {
        "count": count,
        "positive_count": positive,
        "negative_count": negative,
        "flat_count": count - positive - negative,
        "average_return_pct": round(sum(normalized) / count, 2) if count else None,
        "win_rate_pct": round(positive / count * 100, 2) if count else None,
    }


def _tracker_return_pct(db, tracker: StockTracker, *, use_latest_kline: bool) -> float:
    """按页面既有口径取得一条跟踪记录的累计收益。

    跟踪表没有仓位和成交金额，因此这里只返回入选价到当前/退出价的股票收益率。
    """
    entry_price = float(tracker.entry_price or 0)
    if entry_price <= 0:
        return 0.0

    current_price = entry_price
    if use_latest_kline:
        latest_kline = db.query(StockDailyKline.close)\
            .filter(StockDailyKline.ts_code.like(f"{tracker.stock_code}%"))\
            .order_by(StockDailyKline.trade_date.desc())\
            .first()
        if latest_kline and latest_kline.close is not None:
            current_price = float(latest_kline.close)
    else:
        last_daily = db.query(StockTrackerDaily.close_price)\
            .filter(StockTrackerDaily.tracker_id == tracker.id)\
            .order_by(StockTrackerDaily.trade_date.desc())\
            .first()
        if last_daily and last_daily.close_price is not None:
            current_price = float(last_daily.close_price)

    return round((current_price - entry_price) / entry_price * 100, 2)


@router.get("/api/stock-tracker")
def list_tracked():
    """列出所有跟踪中的股票及累计收益"""
    with get_db_session() as db:
        rows = db.query(StockTracker).filter(StockTracker.active == True).order_by(
            StockTracker.entry_date.desc(), StockTracker.updated_at.desc()
        ).all()
        result = []
        today = date.today()
        for r in rows:
            # 查最新的 daily 记录
            latest_daily = db.query(StockTrackerDaily)\
                .filter(StockTrackerDaily.tracker_id == r.id)\
                .order_by(StockTrackerDaily.trade_date.desc())\
                .first()
            # 查 StockDailyKline 获取最新行情
            latest_kline = db.query(StockDailyKline)\
                .filter(StockDailyKline.ts_code.like(f"{r.stock_code}%"))\
                .order_by(StockDailyKline.trade_date.desc())\
                .first()
            current_price = float(latest_kline.close) if latest_kline else float(r.entry_price)
            total_pct = round((current_price - float(r.entry_price)) / float(r.entry_price) * 100, 2) if float(r.entry_price) > 0 else 0
            days_held = (today - r.entry_date).days

            # 查该股票 1-30 日 daily 记录
            daily_rows = db.query(StockTrackerDaily)\
                .filter(StockTrackerDaily.tracker_id == r.id)\
                .order_by(StockTrackerDaily.day_n)\
                .all()
            # 从 K 线补充最新数据（daily 未更新到今天）
            latest_daily_date = daily_rows[-1].trade_date if daily_rows else r.entry_date
            if latest_daily_date < date.today():
                klines = db.query(StockDailyKline)\
                    .filter(
                        StockDailyKline.ts_code.like(f"{r.stock_code}%"),
                        StockDailyKline.trade_date > latest_daily_date,
                        StockDailyKline.trade_date <= date.today(),
                    )\
                    .order_by(StockDailyKline.trade_date)\
                    .all()
                existing_n = len(daily_rows)
                for i, k in enumerate(klines):
                    day_n = existing_n + i + 1
                    if day_n > 30:
                        break
                    pct = round((float(k.close) - float(r.entry_price)) / float(r.entry_price) * 100, 2)
                    daily_rows.append(StockTrackerDaily(
                        tracker_id=r.id,
                        trade_date=k.trade_date,
                        day_n=day_n,
                        close_price=k.close,
                        pct_chg=pct,
                        daily_chg=float(k.pct_chg) if k.pct_chg else 0,
                    ))
            daily_list = [{
                "day_n": d.day_n,
                "trade_date": d.trade_date.isoformat(),
                "close_price": float(d.close_price),
                "pct_chg": float(d.pct_chg),
                "daily_chg": float(d.daily_chg) if d.daily_chg else 0,
                "reason": d.reason or "",
            } for d in sorted(daily_rows, key=lambda x: x.day_n) if d.day_n <= 30]

            result.append({
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "entry_date": r.entry_date.isoformat(),
                "entry_price": float(r.entry_price),
                "current_price": current_price,
                "total_pct_chg": total_pct,
                "days_held": days_held,
                "note": r.note,
                "latest_daily_pct": float(latest_daily.pct_chg) if latest_daily else total_pct,
                "latest_daily_reason": latest_daily.reason if latest_daily else None,
                "daily": daily_list,
            })
        return result


@router.get("/api/stock-tracker/summary")
def tracker_summary():
    """返回跟踪池总体样本表现。"""
    with get_db_session() as db:
        active_rows = db.query(StockTracker).filter(StockTracker.active == True).all()
        exited_rows = db.query(StockTracker).filter(StockTracker.active == False).all()
        active_returns = [_tracker_return_pct(db, row, use_latest_kline=True) for row in active_rows]
        exited_returns = [_tracker_return_pct(db, row, use_latest_kline=False) for row in exited_rows]
        return {
            "definition": "按每只股票等权，计算入选价到当前价或最后记录退出价的累计收益平均值；不含仓位、手续费和滑点，不代表实盘账户收益。",
            "overall": _summarize_returns(active_returns + exited_returns),
            "active": _summarize_returns(active_returns),
            "exited": _summarize_returns(exited_returns),
        }


@router.post("/api/stock-tracker")
def add_stock(req: AddStockRequest):
    """加入跟踪：记录入选日期+入选价，从 StockDailyKline 取最近收盘价"""
    with get_db_session() as db:
        existing = db.query(StockTracker).filter(StockTracker.stock_code == req.stock_code, StockTracker.active == True).first()
        if existing:
            raise HTTPException(400, f"{req.stock_name} 已在跟踪列表中")

        # 取最近一个交易日的 K 线作为入选价
        latest = db.query(StockDailyKline)\
            .filter(StockDailyKline.ts_code.like(f"{req.stock_code}%"))\
            .order_by(StockDailyKline.trade_date.desc())\
            .first()
        if not latest:
            raise HTTPException(400, f"未找到 {req.stock_code} 的行情数据")

        # 检查是否有已删除的同代码记录，有则复用（避免唯一约束冲突）
        old = db.query(StockTracker).filter(StockTracker.stock_code == req.stock_code, StockTracker.active == False).first()
        if old:
            # 同一标的重新跟踪时，旧周期日线不能混入新的入选价和 D1-D30 矩阵。
            db.query(StockTrackerDaily).filter(StockTrackerDaily.tracker_id == old.id).delete(
                synchronize_session=False
            )
            old.active = True
            old.entry_date = latest.trade_date
            old.entry_price = latest.close
            old.stock_name = req.stock_name
            old.note = req.note
            db.commit()
            db.refresh(old)
            return {"ok": True, "id": old.id, "entry_price": float(old.entry_price), "entry_date": old.entry_date.isoformat()}

        entry = StockTracker(
            stock_code=req.stock_code,
            stock_name=req.stock_name,
            entry_date=latest.trade_date,
            entry_price=latest.close,
            note=req.note,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return {"ok": True, "id": entry.id, "entry_price": float(entry.entry_price), "entry_date": entry.entry_date.isoformat()}


@router.delete("/api/stock-tracker/{tracker_id}")
def remove_stock(tracker_id: int):
    """删除跟踪（软删除，标记 active=False）"""
    with get_db_session() as db:
        entry = db.query(StockTracker).filter(StockTracker.id == tracker_id).first()
        if not entry:
            raise HTTPException(404, "未找到该跟踪记录")
        entry.active = False
        db.commit()
        return {"ok": True}


@router.put("/api/stock-tracker/{tracker_id}/note")
def update_note(tracker_id: int, req: UpdateNoteRequest):
    """更新备注"""
    with get_db_session() as db:
        entry = db.query(StockTracker).filter(StockTracker.id == tracker_id).first()
        if not entry:
            raise HTTPException(404, "未找到该跟踪记录")
        entry.note = req.note
        db.commit()
        return {"ok": True}


@router.get("/api/stock-tracker/{tracker_id}/daily")
def get_daily(tracker_id: int):
    """获取某只跟踪股 1-30 日的每日表现"""
    with get_db_session() as db:
        tracker = db.query(StockTracker).filter(StockTracker.id == tracker_id).first()
        if not tracker:
            raise HTTPException(404, "未找到该跟踪记录")

        daily_rows = db.query(StockTrackerDaily)\
            .filter(StockTrackerDaily.tracker_id == tracker_id)\
            .order_by(StockTrackerDaily.day_n)\
            .all()

        # 从 K 线补充最新数据（如果 daily 还未更新到今天）
        latest_daily_date = daily_rows[-1].trade_date if daily_rows else tracker.entry_date
        if latest_daily_date < date.today():
            klines = db.query(StockDailyKline)\
                .filter(
                    StockDailyKline.ts_code.like(f"{tracker.stock_code}%"),
                    StockDailyKline.trade_date > latest_daily_date,
                    StockDailyKline.trade_date <= date.today(),
                )\
                .order_by(StockDailyKline.trade_date)\
                .all()
            existing_n = len(daily_rows)
            for i, k in enumerate(klines):
                day_n = existing_n + i + 1
                if day_n > 30:
                    break
                pct = round((float(k.close) - float(tracker.entry_price)) / float(tracker.entry_price) * 100, 2)
                daily_rows.append(StockTrackerDaily(
                    tracker_id=tracker.id,
                    trade_date=k.trade_date,
                    day_n=day_n,
                    close_price=k.close,
                    pct_chg=pct,
                    daily_chg=float(k.pct_chg) if k.pct_chg else 0,
                ))

        result = [{
            "day_n": r.day_n,
            "trade_date": r.trade_date.isoformat(),
            "close_price": float(r.close_price),
            "pct_chg": float(r.pct_chg),
            "daily_chg": float(r.daily_chg) if r.daily_chg else 0,
            "reason": r.reason or "",
        } for r in sorted(daily_rows, key=lambda x: x.day_n) if r.day_n <= 30]

        return result


# ---------- 每日刷新 & 原因分析 ----------

def _generate_reason(daily_chg: float, vol_ratio: float, sector_flow_sign: int, day_n: int) -> str:
    """根据当日涨跌幅 + 量能 + 板块资金流向生成涨跌原因简述"""
    parts = []
    abs_chg = abs(daily_chg)

    # 涨跌方向
    if daily_chg >= 5:
        parts.append("大幅拉升")
    elif daily_chg >= 2:
        parts.append("强势上涨")
    elif daily_chg > 0:
        parts.append("小幅走高")
    elif daily_chg <= -5:
        parts.append("深度回调")
    elif daily_chg <= -2:
        parts.append("明显下跌")
    elif daily_chg < 0:
        parts.append("微跌")
    else:
        parts.append("平盘震荡")

    # 量能
    if vol_ratio > 2:
        parts.append("放量")
    elif vol_ratio > 1.3:
        parts.append("量能放大")
    elif vol_ratio < 0.5:
        parts.append("缩量")

    # 板块资金
    if sector_flow_sign > 0:
        parts.append("板块资金净流入")
    elif sector_flow_sign < 0:
        parts.append("板块资金净流出")

    # 阶段标签（利用 day_n 判断）
    if day_n <= 1:
        parts.append("（入选初期）")
    elif day_n >= 25:
        parts.append("（接近跟踪周期末端）")

    return "，".join(parts)


@router.post("/api/stock-tracker/daily-refresh")
def daily_refresh():
    """手动触发的每日分析刷新：对所有活跃跟踪股拉 K 线 + 资金流数据，生成 1-30 日走势和涨跌原因"""
    with get_db_session() as db:
        trackers = db.query(StockTracker).filter(StockTracker.active == True).all()
        updated = 0

        for t in trackers:
            # 拉入选以来的全部 K 线
            klines = db.query(StockDailyKline)\
                .filter(
                    StockDailyKline.ts_code.like(f"{t.stock_code}%"),
                    StockDailyKline.trade_date >= t.entry_date,
                    StockDailyKline.trade_date <= date.today(),
                )\
                .order_by(StockDailyKline.trade_date)\
                .all()

            if not klines:
                continue

            # 取股票所属板块（最近一条 StockFlow）
            sector_row = db.query(StockFlow.sector)\
                .filter(StockFlow.ts_code.like(f"{t.stock_code}%"))\
                .order_by(StockFlow.trade_date.desc())\
                .first()
            sector = sector_row.sector if sector_row else None

            entry_p = float(t.entry_price)

            for day_n, k in enumerate((k for k in klines if k.trade_date != t.entry_date), start=1):
                if day_n > 30:
                    break

                pct = round((float(k.close) - entry_p) / entry_p * 100, 2) if entry_p > 0 else 0
                daily_chg = float(k.pct_chg) if k.pct_chg else 0
                closep = float(k.close)

                # 量能比（当日成交量 / 入选日成交量）
                vol_ratio = 1.0
                if klines and klines[0].volume and klines[0].volume > 0:
                    vol_ratio = (k.volume / float(klines[0].volume)) if k.volume else 1.0

                # 板块资金流向符号（查当日该板块的 net_flow）
                # 用 StockFlow 查当日同板块资金流向作为参考
                sector_sign = 0

                # 生成原因
                reason = _generate_reason(daily_chg, vol_ratio, sector_sign, day_n)

                # Upsert
                existing = db.query(StockTrackerDaily)\
                    .filter(
                        StockTrackerDaily.tracker_id == t.id,
                        StockTrackerDaily.trade_date == k.trade_date,
                    ).first()

                if existing:
                    existing.close_price = closep
                    existing.pct_chg = pct
                    existing.daily_chg = daily_chg
                    existing.volume = k.volume
                    existing.reason = reason
                    existing.day_n = day_n
                else:
                    db.add(StockTrackerDaily(
                        tracker_id=t.id,
                        trade_date=k.trade_date,
                        day_n=day_n,
                        close_price=closep,
                        pct_chg=pct,
                        daily_chg=daily_chg,
                        volume=k.volume,
                        reason=reason,
                    ))
                updated += 1

        db.commit()
        return {"ok": True, "trackers": len(trackers), "records_updated": updated}


@router.get("/api/stock-tracker/exited")
def list_exited():
    """已退出（active=False）的跟踪股，按退出时间倒序，含退出日期与原因。

    - 退出日期取 updated_at（被 BS 转 S 自动移除或手动移除时的时间）
    - 退出原因：note 以 [BS转S] 开头 → 自动退出；否则 → 手动移除
    - 退出时累计收益：用最后一条 daily 收盘价（无则回退入选价）相对入选价计算
    """
    with get_db_session() as db:
        rows = db.query(StockTracker).filter(
            StockTracker.active == False
        ).order_by(StockTracker.updated_at.desc()).all()
        out = []
        for r in rows:
            note_raw = r.note or ''
            if note_raw.startswith('[BS转S]'):
                exit_reason = 'BS 转 S 自动退出'
                detail = note_raw[len('[BS转S]'):].strip()
            else:
                exit_reason = '手动移除'
                detail = note_raw

            last_daily = db.query(StockTrackerDaily)\
                .filter(StockTrackerDaily.tracker_id == r.id)\
                .order_by(StockTrackerDaily.trade_date.desc())\
                .first()
            exit_price = float(last_daily.close_price) if last_daily else float(r.entry_price)
            total_pct = round((exit_price - float(r.entry_price)) / float(r.entry_price) * 100, 2) if float(r.entry_price) > 0 else 0

            exit_date = r.updated_at.date().isoformat() if r.updated_at else None
            days = (r.updated_at.date() - r.entry_date).days if r.updated_at else None

            # 历史已定格：返回 1-30 日 daily（按退出日补满 K 线），供前端用同一矩阵呈现
            daily_rows = db.query(StockTrackerDaily)\
                .filter(StockTrackerDaily.tracker_id == r.id)\
                .order_by(StockTrackerDaily.day_n)\
                .all()
            latest_daily_date = daily_rows[-1].trade_date if daily_rows else r.entry_date
            exit_d = r.updated_at.date() if r.updated_at else date.today()
            if latest_daily_date < exit_d:
                klines = db.query(StockDailyKline)\
                    .filter(
                        StockDailyKline.ts_code.like(f"{r.stock_code}%"),
                        StockDailyKline.trade_date > latest_daily_date,
                        StockDailyKline.trade_date <= exit_d,
                    )\
                    .order_by(StockDailyKline.trade_date)\
                    .all()
                existing_n = len(daily_rows)
                for i, k in enumerate(klines):
                    day_n = existing_n + i + 1
                    if day_n > 30:
                        break
                    pct = round((float(k.close) - float(r.entry_price)) / float(r.entry_price) * 100, 2)
                    daily_rows.append(StockTrackerDaily(
                        tracker_id=r.id,
                        trade_date=k.trade_date,
                        day_n=day_n,
                        close_price=k.close,
                        pct_chg=pct,
                        daily_chg=float(k.pct_chg) if k.pct_chg else 0,
                    ))
            daily_list = [{
                "day_n": d.day_n,
                "trade_date": d.trade_date.isoformat(),
                "close_price": float(d.close_price),
                "pct_chg": float(d.pct_chg),
                "daily_chg": float(d.daily_chg) if d.daily_chg else 0,
                "reason": d.reason or "",
            } for d in sorted(daily_rows, key=lambda x: x.day_n) if d.day_n <= 30]

            out.append({
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "entry_date": r.entry_date.isoformat(),
                "entry_price": float(r.entry_price),
                "exit_price": exit_price,
                "exit_date": exit_date,
                "exit_reason": exit_reason,
                "detail": detail,
                "total_pct_chg": total_pct,
                "days_held": days,
                "daily": daily_list,
            })
        return out
