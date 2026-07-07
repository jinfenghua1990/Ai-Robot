"""游资系统 4.0 — 可执行级交易系统
模块：signal_engine（信号分级）/ position_engine（动态仓位）/ risk_engine（组合风控）/ backtest_engine（增强回测）/ runner（盘后预计算）
"""
from .signal_engine import calc_final_score, classify_signal_4
from .position_engine import calc_dynamic_position
from .risk_engine import assess_portfolio_risk, is_high_position_stock

__all__ = [
    'calc_final_score',
    'classify_signal_4',
    'calc_dynamic_position',
    'assess_portfolio_risk',
    'is_high_position_stock',
]
