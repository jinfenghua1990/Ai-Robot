"""Google Sheets 同步 API。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, StreamingResponse

from api.auth import verify_api_key
from config import GOOGLE_SHEETS_REDIRECT_URI
from services.google_sheets_sync import (
    GoogleSheetsError,
    _csv_for_sheet,
    build_authorization_url,
    complete_authorization,
    disconnect,
    get_status,
    sync_now,
)

router = APIRouter(prefix="/api/google-sheets", tags=["google-sheets"])


@router.get("/status")
def google_sheets_status():
    status = get_status()
    status["redirect_uri"] = GOOGLE_SHEETS_REDIRECT_URI
    return {"ok": True, "data": status}


@router.get("/oauth/start")
def google_sheets_oauth_start():
    try:
        return {"ok": True, "auth_url": build_authorization_url()}
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/oauth/callback")
async def google_sheets_oauth_callback(code: str = Query(""), state: str = Query(""), error: str = Query("")):
    if error:
        return RedirectResponse(f"/us-market?tab=health&google=error&message={quote(error)}")
    try:
        await complete_authorization(code, state)
        # 授权成功先回到系统，用户可在页面点击“立即同步”确认写入范围。
        return RedirectResponse("/us-market?tab=health&google=connected")
    except GoogleSheetsError as exc:
        return RedirectResponse(f"/us-market?tab=health&google=error&message={quote(str(exc))}")


@router.post("/sync", dependencies=[Depends(verify_api_key)])
async def google_sheets_sync():
    try:
        return await sync_now()
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/disconnect", dependencies=[Depends(verify_api_key)])
def google_sheets_disconnect():
    disconnect()
    return {"ok": True, "message": "Google Sheets 已断开，本机授权文件已删除"}


@router.get("/export.csv")
def google_sheets_csv(sheet: str = Query("自选", pattern="^(自选|持仓|指标|信号|说明)$")):
    try:
        content = _csv_for_sheet(sheet)
    except GoogleSheetsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = {"自选": "airobot_watchlist.csv", "持仓": "airobot_positions.csv", "指标": "airobot_indicators.csv",
                "信号": "airobot_signals.csv", "说明": "airobot_readme.csv"}[sheet]
    return StreamingResponse(
        # _csv_for_sheet 已包含一个 UTF-8 BOM，避免再次使用 utf-8-sig 产生双 BOM。
        iter([content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
