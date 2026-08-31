"""回马枪独立 20 日跟踪池 API。"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api.auth import verify_api_key
from horseback import tracking


router = APIRouter(prefix="/api/horseback-track", tags=["horseback-track"])


@router.get("/list")
def list_tracks(
    status: str = Query("active", description="active/completed/archived/history/all"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    try:
        return tracking.list_tracks(status=status, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/history")
def history(
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    return tracking.list_tracks(status="history", limit=limit, offset=offset)


@router.post("/sync", dependencies=[Depends(verify_api_key)])
def sync_pool(run_id: str | None = Query(None, description="默认同步最新已完成任务")):
    try:
        return tracking.sync_completed_run(run_id)
    except tracking.TrackingRunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except tracking.TrackingRunNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except tracking.TrackingRunUnsupported as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/daily-update", dependencies=[Depends(verify_api_key)])
def update_daily():
    return tracking.daily_update()


@router.post("/archive", dependencies=[Depends(verify_api_key)])
def archive(payload: dict = Body(...)):
    tracker_id = payload.get("tracker_id")
    if not isinstance(tracker_id, int) or tracker_id <= 0:
        raise HTTPException(status_code=422, detail="tracker_id 必须为正整数")
    reason = str(payload.get("reason") or "MANUAL")
    try:
        return {"tracker": tracking.archive_track(tracker_id, reason)}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
