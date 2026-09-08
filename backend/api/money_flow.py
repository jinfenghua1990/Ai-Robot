from fastapi import APIRouter, Query
from analyzers.money_flow import calculate_money_flow_path
from api.validators import validate_date

router = APIRouter()

@router.get("/api/money-flow")
def get_money_flow(date: str = Query(None)):
    """返回资金流路径图数据"""
    trade_date = validate_date(date)
    return calculate_money_flow_path(trade_date)
