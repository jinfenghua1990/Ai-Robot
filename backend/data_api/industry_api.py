"""Industry board data for market-review (akshare-backed, graceful)."""
from __future__ import annotations

import logging
from typing import Any, Optional

import akshare as ak

from data_api import _to_float
from data_api.concept_api import _find, _row_to_board  # reuse helpers

logger = logging.getLogger("data_api.industry_api")


def get_industry_boards(trade_date: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
    for fn in (lambda: ak.stock_board_industry_name_em(), lambda: ak.stock_board_industry_name_ths()):
        try:
            df = fn()
            if df is not None and not getattr(df, "empty", True):
                data = [_row_to_board(dict(r), trade_date) for _, r in df.iterrows()]
                return {"data": data[:limit]}
        except Exception as exc:  # pragma: no cover
            logger.warning("get_industry_boards attempt failed: %s", exc)
    return {"data": []}
