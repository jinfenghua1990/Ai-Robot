"""Fund-flow collector backed by akshare (graceful degradation).

market-review expects, per data_type, a payload shaped like::

    {"data": {"top_inflow": [...], "top_outflow": [...],
              "top_inflow_10": [...], "top_outflow_10": [...]}}

Each item is ``{"name": str, "value": float (亿元), "code": str}``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import akshare as ak

logger = logging.getLogger("collectors.fund_flow_collector")

_NAME_COLS = ["名称"]
_CODE_COLS = ["代码"]
_NET_COLS = ["今日主力净流入-净额", "主力净流入-净额", "主力净流入"]


def _find_col(df: Any, candidates: list[str]) -> Optional[str]:
    cols = list(getattr(df, "columns", []))
    for c in candidates:
        if c in cols:
            return c
    return None


def _split(df: Any) -> dict[str, Any]:
    empty = {"top_inflow": [], "top_outflow": [], "top_inflow_10": [], "top_outflow_10": []}
    if df is None or getattr(df, "empty", True):
        return {"data": empty}
    name_col = _find_col(df, _NAME_COLS)
    code_col = _find_col(df, _CODE_COLS)
    net_col = _find_col(df, _NET_COLS)
    if name_col is None or net_col is None:
        return {"data": empty}

    rows: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        try:
            val = float(r[net_col])
        except Exception:
            continue
        rows.append(
            {
                "name": str(r[name_col]),
                "code": str(r[code_col]) if code_col else "",
                "value": round(val / 100000000.0, 2),  # 元 → 亿
            }
        )
    if not rows:
        return {"data": empty}
    inflow = sorted(rows, key=lambda x: x["value"], reverse=True)[:10]
    outflow = sorted(rows, key=lambda x: x["value"])[:10]
    return {"data": {"top_inflow": inflow, "top_outflow": outflow, "top_inflow_10": inflow, "top_outflow_10": outflow}}


def collect_fund_flow(data_type: str, trade_date: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
    try:
        if data_type == "industry_moneyflow":
            return _split(ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流"))
        if data_type == "concept_moneyflow":
            return _split(ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="概念资金流"))
        if data_type == "stock_moneyflow":
            return _split(ak.stock_individual_fund_flow_rank(indicator="今日"))
        if data_type == "market_moneyflow":
            try:
                df = ak.stock_market_fund_flow()
                if df is not None and not getattr(df, "empty", True):
                    return {"data": dict(list(df.to_dict("records")[0].items())) if len(df) else {}}
            except Exception:
                pass
            return {"data": {}}
    except Exception as exc:  # pragma: no cover - network/provider failure
        logger.warning("collect_fund_flow %s failed: %s", data_type, exc)
    return {"data": {}}
