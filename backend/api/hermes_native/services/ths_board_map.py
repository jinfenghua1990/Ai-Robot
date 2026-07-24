from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Optional, Union
import json
import sys

DB_ROOT = Path("/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database")
if str(DB_ROOT) not in sys.path:
    sys.path.insert(0, str(DB_ROOT))

try:
    from api.hermes_native.db_connector import execute_query
except Exception:
    execute_query = None

CONCEPT_BOARD_MAP: dict[str, dict[str, Any]] = {}
_CONCEPT_BOARD_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


def _query_rows(sql: str, params: Optional[tuple[Any, ...]] = None) -> list[dict[str, Any]]:
    if execute_query is None:
        return []
    try:
        rows = execute_query(sql, params or ())
    except Exception:
        return []
    return [dict(row) for row in rows]


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def load_concept_board_registry(seed_days: int = 365) -> dict[str, dict[str, Any]]:
    cache_key = f"concept_board_registry:{seed_days}"
    cached = _CONCEPT_BOARD_CACHE.get(cache_key)
    if cached is not None:
        return deepcopy(cached)

    rows = _query_rows(
        """
        SELECT board_code,
               board_name,
               COALESCE(NULLIF(TRIM(src), ''), 'ths') AS src,
               COALESCE(is_degraded, false) AS is_degraded,
               COALESCE(NULLIF(TRIM(description), ''), '') AS description
        FROM concept_board_meta
        WHERE board_code IS NOT NULL
          AND board_name IS NOT NULL
        ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, board_code ASC
        """
    )

    if not rows:
        rows = _query_rows(
            f"""
            SELECT DISTINCT board_code,
                            board_name,
                            'ths' AS src,
                            false AS is_degraded,
                            '' AS description
            FROM concept_board_daily
            WHERE trade_date >= CURRENT_DATE - INTERVAL '{seed_days} days'
              AND board_code IS NOT NULL
              AND board_name IS NOT NULL
            ORDER BY board_code ASC
            """
        )

    registry: dict[str, dict[str, Any]] = {}
    for row in rows:
        board_code = _normalize_text(row.get("board_code"))
        board_name = _normalize_text(row.get("board_name"))
        if not board_code or not board_name:
            continue
        registry[board_code] = {
            "board_code": board_code,
            "board_name": board_name,
            "src": _normalize_text(row.get("src") or "ths") or "ths",
            "is_degraded": bool(row.get("is_degraded")),
            "description": _normalize_text(row.get("description")),
        }

    _CONCEPT_BOARD_CACHE[cache_key] = deepcopy(registry)
    CONCEPT_BOARD_MAP.clear()
    CONCEPT_BOARD_MAP.update(deepcopy(registry))
    return deepcopy(registry)


def resolve_concept_board_name(board_code: str, default: str = "") -> str:
    registry = load_concept_board_registry()
    item = registry.get(_normalize_text(board_code))
    if not item:
        return default
    return _normalize_text(item.get("board_name")) or default


def export_concept_board_registry_json(path: Union[str, Path]) -> Path:
    registry = load_concept_board_registry()
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


__all__ = [
    "CONCEPT_BOARD_MAP",
    "export_concept_board_registry_json",
    "load_concept_board_registry",
    "resolve_concept_board_name",
]
