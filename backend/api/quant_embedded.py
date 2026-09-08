"""Quant Service 的内嵌接口。

这些接口直接运行在 AIROBOT 9000 进程内，不再通过独立端口转发。
Qlib / VectorBT 是可选依赖；未安装或数据未就绪时返回明确的 Phase0 状态。
"""
import time
import importlib.util
from typing import Optional

from fastapi import APIRouter

router = APIRouter(prefix="/api/quant", tags=["quant"])

QLIB_READY = False
VECTORBT_READY = False
QLIB_ERROR: Optional[str] = None
VECTORBT_ERROR: Optional[str] = None
try:
    QLIB_READY = importlib.util.find_spec("qlib") is not None
    if not QLIB_READY:
        QLIB_ERROR = "No module named 'qlib'"
except Exception as exc:  # pragma: no cover
    QLIB_ERROR = str(exc)
try:
    VECTORBT_READY = importlib.util.find_spec("vectorbt") is not None
    if not VECTORBT_READY:
        VECTORBT_ERROR = "No module named 'vectorbt'"
except Exception as exc:  # pragma: no cover
    VECTORBT_ERROR = str(exc)

DATA_READY = False
SERVICE_STARTED_AT = time.strftime("%Y/%m/%d %H:%M:%S")


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "quant",
        "port": 9000,
        "embedded": True,
        "qlib_ready": QLIB_READY,
        "vectorbt_ready": VECTORBT_READY,
        "data_ready": DATA_READY,
        "qlib_error": QLIB_ERROR,
        "vectorbt_error": VECTORBT_ERROR,
        "started_at": SERVICE_STARTED_AT,
    }


@router.post("/score")
async def score(payload: dict):
    market = payload.get("market", "US")
    codes = payload.get("codes") or []
    if not QLIB_READY or not DATA_READY:
        return {
            "ready": False,
            "phase": "Phase0",
            "reason": "Qlib 或数据仓尚未就绪",
            "qlib_ready": QLIB_READY,
            "data_ready": DATA_READY,
            "market": market,
            "requested": codes,
            "scores": {},
        }
    return {"ready": True, "market": market, "scores": {}}


@router.get("/scan")
async def scan(strategy: str = "longqing", market: str = "US", limit: int = 20):
    if not VECTORBT_READY or not DATA_READY:
        return {
            "ready": False,
            "phase": "Phase0",
            "reason": "VectorBT 或数据仓尚未就绪",
            "vectorbt_ready": VECTORBT_READY,
            "data_ready": DATA_READY,
            "strategy": strategy,
            "market": market,
            "limit": limit,
            "hits": [],
        }
    return {"ready": True, "strategy": strategy, "market": market, "hits": []}
