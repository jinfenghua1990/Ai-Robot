from fastapi import APIRouter, Query
from analyzers.lifecycle_v2 import get_lifecycle_v2
from api.validators import validate_date

router = APIRouter()

@router.get("/api/lifecycle-v2")
def get_lifecycle_v2_api(date: str = Query(None)):
    """返回 V2 龙头生命周期数据（多维度强度评分）"""
    trade_date = validate_date(date)
    return get_lifecycle_v2(trade_date)
