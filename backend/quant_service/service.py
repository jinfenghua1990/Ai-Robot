"""
AIROBOT Quant Service —— Qlib 因子/ML 排序 + VectorBT 扫描 的独立微服务。

设计要点：
- 跑在独立 Python 3.11 venv（不污染 9000 主服务的系统 Python 3.9）。
- qlib / vectorbt 延迟导入：未安装或未就绪时服务仍可启动，/api/score 与
  /api/scan 返回 {"ready": False, "phase": "Phase0", ...}，前端据此显示
  “数据准备中”，页面永不空白。
- 主服务 9000 通过 /api/quant/* 反代到本服务（默认 9003）。
"""
import os
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

QUANT_PORT = int(os.environ.get("QUANT_PORT", "9003"))
QUANT_HOST = os.environ.get("QUANT_HOST", "0.0.0.0")

app = FastAPI(title="AIROBOT Quant Service", version="0.1.0")

# ── 引擎就绪探测（延迟导入，避免缺包时服务崩溃）─────────────────────────
QLIB_READY = False
VECTORBT_READY = False
QLIB_ERROR: Optional[str] = None
VECTORBT_ERROR: Optional[str] = None
try:
    import qlib  # noqa: F401
    QLIB_READY = True
except Exception as e:  # pragma: no cover
    QLIB_ERROR = str(e)
try:
    import vectorbt  # noqa: F401
    VECTORBT_READY = True
except Exception as e:  # pragma: no cover
    VECTORBT_ERROR = str(e)

# Phase 0 数据仓就绪后由初始化逻辑置 True（当前默认未就绪）。
DATA_READY = False
SERVICE_STARTED_AT = time.strftime("%Y/%m/%d %H:%M:%S")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "quant",
        "port": QUANT_PORT,
        "qlib_ready": QLIB_READY,
        "vectorbt_ready": VECTORBT_READY,
        "data_ready": DATA_READY,
        "qlib_error": QLIB_ERROR,
        "vectorbt_error": VECTORBT_ERROR,
        "started_at": SERVICE_STARTED_AT,
    }


@app.post("/score")
async def score(payload: dict):
    """个股 ML 排序评分（Phase 1 由 Qlib 实现；当前返回 pending）。

    预期入参: {"market": "US", "codes": ["AAPL", "MSFT", ...]}
    就绪后返回: {"ready": True, "scores": {"AAPL": {"score": 82.3, "factors": {...}}}}
    """
    market = payload.get("market", "US")
    codes = payload.get("codes") or []
    if not QLIB_READY or not DATA_READY:
        return {
            "ready": False,
            "phase": "Phase0",
            "reason": "Qlib 或美股数据仓尚未就绪（见 requirements-ml.txt 与 Phase 0 数据准备）",
            "qlib_ready": QLIB_READY,
            "data_ready": DATA_READY,
            "market": market,
            "requested": codes,
            "scores": {},
        }
    # TODO Phase 1: 调 Qlib 跑 Alpha 因子 + 模型推理，返回排序分与关键因子。
    return {"ready": True, "market": market, "scores": {}}


@app.get("/scan")
async def scan(strategy: str = "longqing", market: str = "US", limit: int = 20):
    """策略扫描（Phase 2 由 VectorBT 实现高速批量扫描；当前返回 pending）。

    策略键: longqing(青龙趋势) / baihu(白虎突破) / huiche(回踩)
    """
    if not VECTORBT_READY or not DATA_READY:
        return {
            "ready": False,
            "phase": "Phase0",
            "reason": "VectorBT 或数据仓尚未就绪",
            "vectorbt_ready": VECTORBT_READY,
            "data_ready": DATA_READY,
            "strategy": strategy,
            "market": market,
            "hits": [],
        }
    # TODO Phase 2: VectorBT 向量化计算命中列表。
    return {"ready": True, "strategy": strategy, "market": market, "hits": []}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=QUANT_HOST, port=QUANT_PORT)
