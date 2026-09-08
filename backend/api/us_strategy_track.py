"""美股每日策略命中跟踪：入选后跟踪 30 个交易日并统计胜率。"""
from datetime import date
from sqlalchemy import desc, func
from fastapi import APIRouter, Query
from db.session import get_db_session
from us_quant.repository import USFactorScore, USInstrument, USStockDaily, USStrategyTrack, USStrategyTrackDaily

router = APIRouter(prefix="/api/us-strategy-track", tags=["us-strategy-track"])

def _f(v): return float(v) if v is not None else None
def _row(db, t):
    daily = db.query(USStrategyTrackDaily).filter_by(tracker_id=t.id).order_by(USStrategyTrackDaily.day_n).all()
    return {"id": t.id, "pool_date": t.pool_date.isoformat(), "symbol": t.symbol, "name": t.name,
            "strategy": t.strategy, "entry_price": _f(t.entry_price), "track_days": t.track_days,
            "status": t.status, "latest_date": t.latest_date.isoformat() if t.latest_date else None,
            "latest_price": _f(t.latest_price), "latest_return_pct": _f(t.latest_return_pct),
            "exit_date": t.exit_date.isoformat() if t.exit_date else None, "exit_price": _f(t.exit_price),
            "exit_return_pct": _f(t.exit_return_pct),
            "daily": [{"trade_date": d.trade_date.isoformat(), "day_n": d.day_n,
                       "close": _f(d.close), "daily_return_pct": _f(d.daily_return_pct),
                       "cum_return_pct": _f(d.cum_return_pct)} for d in daily]}

def _summary(rows):
    completed = [r for r in rows if r["status"] != "active"]
    returns = [r["exit_return_pct"] for r in completed if r["exit_return_pct"] is not None]
    positive = sum(1 for x in returns if x > 0)
    return {"total": len(rows), "active": sum(r["status"] == "active" for r in rows),
            "completed": len(completed), "wins": positive, "win_rate": round(positive / len(returns) * 100, 2) if returns else None,
            "avg_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
            "note": "胜率仅统计已完成 30 日跟踪样本；未完成样本单独列为进行中。"}

@router.get("/list")
def list_tracks(status: str = Query("all")):
    with get_db_session() as db:
        q = db.query(USStrategyTrack)
        if status != "all": q = q.filter(USStrategyTrack.status == status)
        rows = [_row(db, t) for t in q.order_by(desc(USStrategyTrack.pool_date), USStrategyTrack.symbol).all()]
        return {"ok": True, "rows": rows, "summary": _summary(rows)}

@router.post("/pool")
def build_pool(pool_date: str | None = Query(None), strategy: str = Query("daily_decision")):
    with get_db_session() as db:
        decision_items = []
        if strategy == "daily_decision":
            from market_quant.service import get_latest_snapshot
            snapshot = get_latest_snapshot("US", "CORE", 500)
            target = date.fromisoformat(pool_date) if pool_date else (date.fromisoformat(snapshot["trade_date"]) if snapshot.get("trade_date") else None)
            rows = snapshot.get("signals") or [] if snapshot.get("status") == "SUCCESS" else []
            decision_items = [x for x in rows if not x.get("risk_veto") and (x.get("trading_state") == "TRIGGERED" or (x.get("resonance") or {}).get("eligible"))]
        else:
            target = date.fromisoformat(pool_date) if pool_date else db.query(func.max(USFactorScore.trade_date)).filter(USFactorScore.factor_name == strategy, USFactorScore.factor_value > 0).scalar()
        if not target: return {"ok": True, "pool_date": None, "added": 0, "message": "暂无策略命中数据"}
        factors = db.query(USFactorScore).filter(USFactorScore.trade_date == target, USFactorScore.factor_name == strategy, USFactorScore.factor_value > 0).all() if strategy != "daily_decision" else []
        symbols = [str(x.get("symbol") or x.get("ts_code") or "").upper() for x in decision_items] if strategy == "daily_decision" else [f.symbol for f in factors]
        names = {x.symbol: x.name for x in db.query(USInstrument).filter(USInstrument.symbol.in_(symbols)).all()}
        prices = {x.symbol: _f(x.close) for x in db.query(USStockDaily).filter(USStockDaily.trade_date == target, USStockDaily.symbol.in_(symbols)).all()}
        added = 0
        candidates = decision_items if strategy == "daily_decision" else [{"symbol": f.symbol, "name": names.get(f.symbol), "factor_score": f.factor_value} for f in factors]
        for item in candidates:
            symbol = str(item.get("symbol") or item.get("ts_code") or "").upper()
            entry_price = prices.get(symbol)
            # 统一盘后快照可能先于日线归档完成；使用同一快照中的收盘价暂存入池，
            # 后续日线归档后再由 daily-update 补写跟踪明细。
            if entry_price is None:
                entry_price = _f(item.get("current_price"))
            if not symbol or entry_price is None: continue
            exists = db.query(USStrategyTrack).filter_by(pool_date=target, symbol=symbol, strategy=strategy).first()
            if exists: continue
            db.add(USStrategyTrack(pool_date=target, symbol=symbol, name=item.get("name") or names.get(symbol) or symbol, strategy=strategy, entry_price=entry_price, track_days=30))
            added += 1
        db.commit()
        return {"ok": True, "pool_date": target.isoformat(), "strategy": strategy, "added": added, "candidates": len(candidates)}

@router.post("/daily-update")
def daily_update():
    with get_db_session() as db:
        trackers = db.query(USStrategyTrack).filter(USStrategyTrack.status == "active").all()
        updated = 0
        for t in trackers:
            bars = db.query(USStockDaily).filter(USStockDaily.symbol == t.symbol, USStockDaily.trade_date > t.pool_date).order_by(USStockDaily.trade_date).all()
            existing = {d.trade_date for d in db.query(USStrategyTrackDaily).filter_by(tracker_id=t.id).all()}
            for bar in bars:
                if bar.trade_date in existing or bar.close is None: continue
                day_n = db.query(USStrategyTrackDaily).filter_by(tracker_id=t.id).count() + 1
                ret = round((_f(bar.close) - _f(t.entry_price)) / _f(t.entry_price) * 100, 2) if t.entry_price else None
                prev = db.query(USStrategyTrackDaily).filter_by(tracker_id=t.id).order_by(desc(USStrategyTrackDaily.day_n)).first()
                daily_ret = round((_f(bar.close) - _f(prev.close)) / _f(prev.close) * 100, 2) if prev and prev.close else None
                db.add(USStrategyTrackDaily(tracker_id=t.id, trade_date=bar.trade_date, day_n=day_n, close=bar.close, daily_return_pct=daily_ret, cum_return_pct=ret))
                t.latest_date, t.latest_price, t.latest_return_pct = bar.trade_date, bar.close, ret
                if day_n >= t.track_days:
                    t.status, t.exit_date, t.exit_price, t.exit_return_pct = "completed", bar.trade_date, bar.close, ret
                updated += 1
        db.commit()
        return {"ok": True, "updated": updated}
