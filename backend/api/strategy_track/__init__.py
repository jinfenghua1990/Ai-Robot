"""
策略共振股 20 天跟踪 API 包
- 入池：从 strategy_result 拉取当日多策略共振 (>=2) 命中的股票
- 每日更新：盘后拉行情 + BS 信号检查
- 撤离：BS 出现 S 点 → 撤离放入历史；或跟踪满 20 天自动到期
"""
from .router import router

__all__ = ["router"]
