"""
盘后日报服务接口（端口 9000）

- GET /api/report/daily          最新一期日报（HTML）
- GET /api/report/daily/{date}   指定日期日报（HTML）
- GET /api/report/meta           日报元信息（最新日期/可用日期列表）
- POST /api/report/generate      立即生成（默认最新交易日），返回路径
"""
import os
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from reports.daily_report import generate_daily_report, REPORT_DIR
from db.session import get_db_session
from sqlalchemy import text

logger = logging.getLogger("report_api")
router = APIRouter(prefix="/api/report", tags=["report"])


def _latest_date():
    with get_db_session() as db:
        row = db.execute(text("SELECT max(trade_date) FROM stock_flow")).scalar()
        return row.strftime("%Y-%m-%d") if row else None


def _report_path(date_str):
    return os.path.join(REPORT_DIR, f"{date_str}.html")


def _ensure_report(date_str):
    """确保某日期报告存在，缺失则即时生成"""
    path = _report_path(date_str)
    if not os.path.exists(path):
        generate_daily_report(date_str)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"未找到 {date_str} 的日报")
    return path


@router.get("/daily")
def get_latest_report():
    """最新一期日报（HTML）"""
    d = _latest_date()
    if not d:
        raise HTTPException(status_code=404, detail="无可用交易日数据")
    path = _ensure_report(d)
    return FileResponse(path, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})


@router.get("/daily/{date_str}")
def get_report_by_date(date_str: str):
    """指定日期日报（HTML）"""
    if not (len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-"):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    path = _ensure_report(date_str)
    return FileResponse(path, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})


@router.get("/meta")
def get_report_meta():
    """日报元信息"""
    d = _latest_date()
    available = []
    if os.path.isdir(REPORT_DIR):
        available = sorted(
            f[:-5] for f in os.listdir(REPORT_DIR)
            if f.endswith(".html")
        )
    return {"latest": d, "available": available, "count": len(available)}


@router.post("/generate")
def generate_report(date_str: str = None):
    """立即生成日报（默认最新交易日）"""
    try:
        path = generate_daily_report(date_str)
    except Exception as e:
        logger.exception("生成日报失败")
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")
    d = os.path.basename(path).replace(".html", "")
    return {
        "success": True,
        "date": d,
        "path": path,
        "url": f"/api/report/daily/{d}",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
