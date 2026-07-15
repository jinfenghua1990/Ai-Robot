"""
股票跟踪 API
- 选中股票加入跟踪 → 记录入选价 → 每日自动计算 1-30 日涨跌
- 支持增删查操作
"""
from datetime import date, datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from db.session import get_db_session
from db.models import StockTracker, StockTrackerDaily, StockDailyKline
from sqlalchemy import func, and_

router = APIRouter()


class AddStockRequest(BaseModel):
    stock_code: str
    stock_name: str
    note: str = ""


class UpdateNoteRequest(BaseModel):
    note: str


@router.get("/api/stock-tracker")
def list_tracked():
    """列出所有跟踪中的股票及累计收益"""
    with get_db_session() as db:
        rows = db.query(StockTracker).filter(StockTracker.active == True).order_by(StockTracker.created_at.desc()).all()
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
            })
        return {"data": result}


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
            for k in klines:
                day_n = (k.trade_date - tracker.entry_date).days
                if 1 <= day_n <= 30:
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
        } for r in sorted(daily_rows, key=lambda x: x.day_n)]

        return {"data": result, "entry_date": tracker.entry_date.isoformat(), "entry_price": float(tracker.entry_price)}
