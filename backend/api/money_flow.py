from fastapi import APIRouter, Query
from analyzers.money_flow import calculate_money_flow_path
from datetime import datetime

router = APIRouter()

@router.get("/api/money-flow")
async def get_money_flow(date: str = Query(None)):
    """返回资金流路径图数据"""
    trade_date = date or datetime.now().strftime('%Y-%m-%d')
    return calculate_money_flow_path(trade_date)
