"""Concept board data for market-review (akshare-backed, graceful)."""
from __future__ import annotations

import logging
from typing import Any, Optional

import akshare as ak

from data_api import _to_float

logger = logging.getLogger("data_api.concept_api")

_NAME_COLS = ["板块名称", "名称"]
_CHANGE_COLS = ["涨跌幅"]
_LEADER_COLS = ["领涨股票", "领涨股"]


def _row_to_board(row: dict[str, Any], trade_date: Optional[str]) -> dict[str, Any]:
    name = _find(row, _NAME_COLS)
    return {
        "board_name": name,
        "change_pct": _to_float(_find(row, _CHANGE_COLS)),
        "leader": _find(row, _LEADER_COLS) or "",
        "trade_date": trade_date,
    }


def _find(row: dict[str, Any], candidates: list[str]) -> Any:
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return None


def get_concept_boards(trade_date: Optional[str] = None, limit: int = 20) -> dict[str, Any]:
    for fn in (lambda: ak.stock_board_concept_name_em(), lambda: ak.stock_board_concept_name_ths()):
        try:
            df = fn()
            if df is not None and not getattr(df, "empty", True):
                data = [_row_to_board(dict(r), trade_date) for _, r in df.iterrows()]
                return {"data": data[:limit]}
        except Exception as exc:  # pragma: no cover
            logger.warning("get_concept_boards attempt failed: %s", exc)
    return {"data": []}
