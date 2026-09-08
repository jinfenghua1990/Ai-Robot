"""波浪分析 API：POST 采集入库，GET 只读数据库。"""
import json
import logging
import sys
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter
from sqlalchemy import func

from db.models import StockDailyKline, WaveAnalysisSnapshot
from db.session import get_db_session

router = APIRouter(prefix="/api/ops", tags=["wave_analysis"])
logger = logging.getLogger(__name__)

RESULT_PATH = Path("/Users/gino/backtest_results/wave/result.json")
SCRIPT_PATH = Path("/Users/gino/backtest_results/wave/run_wave_analysis.py")
LOG_PATH = Path(__file__).resolve().parent / "logs" / "wave_analysis.log"
_run_lock = threading.Lock()
_run_active = False


def _persist_result_file(*, require_newer_than: float | None = None) -> dict:
    """将采集脚本产生的中间 JSON 导入数据库。"""
    if not RESULT_PATH.exists():
        raise FileNotFoundError(f"采集结果不存在: {RESULT_PATH}")
    modified_at = RESULT_PATH.stat().st_mtime
    if require_newer_than is not None and modified_at < require_newer_than:
        raise RuntimeError("采集脚本未产生新结果，不导入旧文件")
    with RESULT_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    generated_at = datetime.fromtimestamp(modified_at)
    with get_db_session() as db:
        latest = db.query(WaveAnalysisSnapshot).order_by(
            WaveAnalysisSnapshot.generated_at.desc(), WaveAnalysisSnapshot.id.desc(),
        ).first()
        if latest and latest.generated_at >= generated_at:
            return {"status": "already_imported", "generated_at": latest.generated_at.isoformat()}
        db.add(WaveAnalysisSnapshot(
            generated_at=generated_at,
            source="wave_script",
            snapshot_json=json.dumps(payload, ensure_ascii=False),
        ))
        db.commit()
    return {"status": "imported", "generated_at": generated_at.isoformat()}


def import_existing_wave_result() -> dict:
    """仅供迁移/运维使用：将旧的中间文件导入数据库。"""
    return _persist_result_file()


@router.get("/wave-analysis")
def get_wave_analysis():
    """返回最新已入库波浪分析结果。"""
    try:
        with get_db_session() as db:
            row = db.query(WaveAnalysisSnapshot).order_by(
                WaveAnalysisSnapshot.generated_at.desc(), WaveAnalysisSnapshot.id.desc(),
            ).first()
            expected_session = db.query(func.max(StockDailyKline.trade_date)).scalar()
        if not row:
            return {
                "ok": False, "error": "数据库暂无波浪分析快照，请等待采集任务入库",
                "data": None, "source": "database", "status": "MISSING", "data_as_of": None,
            }
        payload = json.loads(row.snapshot_json)
        payload_date = None
        try:
            payload_date = datetime.strptime(str(payload.get("trade_date"))[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            pass
        status = "READY" if expected_session and payload_date == expected_session else "STALE"
        return {
            "ok": True,
            "data": payload,
            "source": "database",
            "status": status,
            "data_as_of": row.generated_at.isoformat(),
            "trade_date": payload_date.isoformat() if payload_date else None,
            "expected_session": expected_session.isoformat() if expected_session else None,
            "message": (
                f"波浪分析快照停留在 {payload_date.isoformat() if payload_date else '未知日期'}"
                if status == "STALE" else None
            ),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "data": None, "source": "database", "status": "ERROR"}


def _run_and_persist() -> None:
    global _run_active
    started_at = time.time()
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            completed = subprocess.run(
                [sys.executable, str(SCRIPT_PATH)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if completed.returncode != 0:
            raise RuntimeError(f"波浪分析脚本退出码 {completed.returncode}")
        result = _persist_result_file(require_newer_than=started_at)
        logger.info("[wave-analysis] collection persisted: %s", result)
    except Exception:
        logger.exception("[wave-analysis] collection failed")
    finally:
        with _run_lock:
            _run_active = False


@router.post("/wave-analysis/run")
def run_wave_analysis():
    """触发采集脚本，完成后自动导入数据库。"""
    global _run_active
    if not SCRIPT_PATH.exists():
        return {"ok": False, "error": f"脚本不存在: {SCRIPT_PATH}"}
    with _run_lock:
        if _run_active:
            return {"ok": True, "strategy": "wave_analysis", "status": "already_running"}
        _run_active = True
    threading.Thread(target=_run_and_persist, name="wave-analysis-collector", daemon=True).start()
    return {"ok": True, "strategy": "wave_analysis", "status": "started", "log": str(LOG_PATH)}
