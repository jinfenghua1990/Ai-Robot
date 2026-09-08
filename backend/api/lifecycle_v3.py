from fastapi import APIRouter, Query
from analyzers.lifecycle_v3 import get_lifecycle_v3
from api.validators import validate_date

router = APIRouter()


@router.get("/api/lifecycle-v3")
def get_lifecycle_v3_api(date: str = Query(None), sector: str = Query(None)):
    """返回龙头生命周期 V3 数据"""
    trade_date = validate_date(date)
    result = get_lifecycle_v3(trade_date)
    
    if sector:
        result['sector_detail'] = {sector: result['sector_detail'].get(sector, {'leaders': []})}
    
    return result