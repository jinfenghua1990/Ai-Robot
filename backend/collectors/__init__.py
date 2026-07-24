"""collectors package — reimplemented fund-flow collector for market-review.

Original Hermes collector pulled from robot-1; this version uses akshare's
public fund-flow endpoints. Always returns a well-shaped payload (never raises)
so market-review degrades gracefully when the provider is unreachable.
"""
from __future__ import annotations

import logging

from .fund_flow_collector import collect_fund_flow

__all__ = ["collect_fund_flow"]
logger = logging.getLogger("collectors")
