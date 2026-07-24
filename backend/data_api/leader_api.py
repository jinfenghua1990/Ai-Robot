"""Leader stock data for market-review.

robot-1's proprietary leader_score table (leader_stock_daily) was removed with
``/Users/gino/.hermes`` and is not reproducible from public data. Returning an
empty list is correct: market-review builds its themes section from the
industry/concept board data regardless, so leadership ranking simply stays
empty instead of faking scores.
"""
from __future__ import annotations

from typing import Optional

from data_api import _to_float  # noqa: F401  (kept for API symmetry)


def get_top_leaders(trade_date: Optional[str] = None, top_n: int = 20) -> dict[str, Any]:
    return {"data": []}
