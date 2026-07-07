from fastapi import APIRouter, Query
from analyzers.portfolio import analyze_portfolio_style
from api.validators import validate_date, validate_days

router = APIRouter()

@router.get("/api/portfolio")
def get_portfolio_analysis(date: str = Query(None), days: int = Query(5)):
    """返回投资组合风格分析与转换建议"""
    trade_date = validate_date(date)
    days = validate_days(days)
    return analyze_portfolio_style(trade_date, days)
