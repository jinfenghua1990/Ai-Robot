"""API 共享工具函数"""
from fastapi import HTTPException
from datetime import datetime


def validate_date(date_str: str) -> str:
    """验证日期格式为 YYYY-MM-DD，返回处理后的日期字符串"""
    if date_str:
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD format")
    return date_str or datetime.now().strftime('%Y-%m-%d')


def validate_days(days: int, default: int = 5, max_val: int = 30) -> int:
    """验证 days 参数范围"""
    if days < 1 or days > max_val:
        raise HTTPException(status_code=400, detail=f"days must be between 1 and {max_val}")
    return days
