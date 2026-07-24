"""
波浪分析 (四大指数波段研判) API
- GET  /api/ops/wave-analysis      读取最近一次波浪分析结果 JSON
- POST /api/ops/wave-analysis/run  触发波浪分析脚本
"""
import sys
import subprocess
from pathlib import Path
from fastapi import APIRouter

router = APIRouter(prefix="/api/ops", tags=["wave_analysis"])

RESULT_PATH = Path("/Users/gino/backtest_results/wave/result.json")
SCRIPT_PATH = Path("/Users/gino/backtest_results/wave/run_wave_analysis.py")
LOG_PATH = Path("/Users/gino/Projects/AIROBOT/backend/hermes_backend/strategy_runs/wave_analysis.log")


@router.get("/wave-analysis")
def get_wave_analysis():
    """返回波浪分析结果（指数级别）"""
    import json as _json
    if not RESULT_PATH.exists():
        return {"ok": False, "error": "暂无波浪分析数据，请先点击运行", "data": None}
    try:
        with open(RESULT_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None}


@router.post("/wave-analysis/run")
def run_wave_analysis():
    """触发波浪分析脚本执行"""
    if not SCRIPT_PATH.exists():
        return {"ok": False, "error": f"脚本不存在: {SCRIPT_PATH}"}
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(
            [sys.executable, str(SCRIPT_PATH)],
            stdout=open(LOG_PATH, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        return {"ok": True, "strategy": "wave_analysis", "status": "started", "log": str(LOG_PATH)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
