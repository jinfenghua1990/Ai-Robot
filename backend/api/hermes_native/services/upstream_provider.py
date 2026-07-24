from __future__ import annotations

from datetime import date
from typing import Any, Optional, Optional


def _normalize_date(value: Any) -> str:
    if value in (None, "", []):
        return date.today().isoformat()
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return date.today().isoformat()


def build_upstream_review(review_date: Optional[str] = None) -> dict[str, Any]:
    """
    通过 market_review 的真实数据库构建链，返回可供 Hub 吃入的 upstream_context。

    这个函数保持轻量：如果当日没有可用数据，就返回空字典。
    """
    requested_date = _normalize_date(review_date)
    try:
        from api.hermes_native.market_review import _build_upstream_review
    except Exception:
        return {}

    try:
        return _build_upstream_review(requested_date)
    except Exception:
        return {}


def build_upstream_scheduler_payload(review_date: Optional[str] = None) -> dict[str, Any]:
    review = build_upstream_review(review_date)
    if not review:
        return {}
    return {
        "upstream_context": review,
    }


__all__ = ["build_upstream_review", "build_upstream_scheduler_payload"]
