from __future__ import annotations

from typing import Any, Optional, Optional

from fastapi import APIRouter, Query

from api.hermes_native.services.main_central_hub import MainCentralHub, build_main_hub_package

router = APIRouter(prefix="/api/main-hub", tags=["main-hub"])

HUB = MainCentralHub()


def _public_source_label(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return (
        value.replace("robot1_kline+ths_board_map", "upstream_kline+ths_board_map")
        .replace("robot1_kline+stock_list", "upstream_kline+stock_list")
        .replace("robot1_rotation_fallback", "upstream_rotation_fallback")
        .replace("robot1_daily_db", "upstream_daily_db")
        .replace("robot1+robot3", "upstream+watchlist")
        .replace("Robot-1", "上游数据")
        .replace("robot1", "upstream")
    )


def _sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            public_key = "upstream" if key == "robot1" else key
            sanitized[public_key] = _sanitize_public_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_public_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_public_payload(item) for item in value]
    if isinstance(value, str):
        return _public_source_label(value)
    return value


def _empty_package() -> dict[str, Any]:
    return build_main_hub_package([], {}, {}, None, None)


@router.get("")
@router.get("/")
def get_main_hub(date: Optional[str] = Query(default=None, description="YYYY-MM-DD")):
    package = HUB.load_latest_package()
    if not package:
        package = _empty_package()
    if date:
        package["requested_date"] = date
    return _sanitize_public_payload(package)


@router.get("/context")
def get_main_hub_context():
    package = HUB.load_latest_package()
    if not package:
        package = _empty_package()
    return _sanitize_public_payload(package.get("market_context", {}))


@router.get("/dispatch")
def get_main_hub_dispatch():
    package = HUB.load_latest_package()
    if not package:
        package = _empty_package()
    return _sanitize_public_payload(package.get("dispatch", {}))
