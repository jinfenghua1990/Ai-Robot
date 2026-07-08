"""数据采集告警 API"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel
from datetime import date
from services.alert_service import get_recent_alerts, check_realtime_data_gap

router = APIRouter()


class AlertsResponse(BaseModel):
    ok: bool
    data: list
    error: Optional[str] = None


@router.get("/api/alerts/recent", response_model=AlertsResponse)
async def recent_alerts(
    level: Optional[str] = Query(None, description="warning/error/critical"),
    category: Optional[str] = Query(None, description="collection_gap/quantity_anomaly/source_failure"),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=200),
):
    """查询最近的数据采集告警。"""
    try:
        alerts = get_recent_alerts(level=level, category=category, hours=hours, limit=limit)
        return AlertsResponse(ok=True, data=alerts)
    except Exception as e:
        return AlertsResponse(ok=False, data=[], error=str(e))


@router.get("/api/alerts/check-gap", response_model=AlertsResponse)
async def check_gap(min_expected_stocks: int = Query(4000, ge=1000, le=6000)):
    """手动触发一次实时数据断层检查。"""
    try:
        result = check_realtime_data_gap(min_expected_stocks=min_expected_stocks)
        return AlertsResponse(ok=True, data=[result] if result else [])
    except Exception as e:
        return AlertsResponse(ok=False, data=[], error=str(e))
