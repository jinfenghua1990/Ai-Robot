from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional, Optional


def safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, "", []):
        return default
    try:
        return float(value)
    except Exception:
        return default


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value in (None, "", []):
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def mean(values: Sequence[float], default: float = 0.0) -> float:
    if not values:
        return default
    return sum(values) / len(values)


def unique_by_name(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(item)
    return result


def as_text(value: Any, default: str = "数据暂缺") -> str:
    if value in (None, "", []):
        return default
    text = str(value).strip()
    return text or default


def ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []

