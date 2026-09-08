"""回马枪选股器原生 API。"""

from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, SecretStr, model_validator

from api.auth import is_local_host, verify_api_key
from horseback.config_store import TokenStore
from horseback.ifind_client import DEFAULT_ENDPOINT
from horseback.scoring import normalize_symbol
from horseback.service import (
    ActiveRunError,
    export_csv,
    get_kline,
    get_latest_run,
    get_run,
    refresh_quotes,
    request_cancel,
    start_run,
)


router = APIRouter(prefix="/api/horseback", tags=["horseback"])


class TokenRequest(BaseModel):
    token: SecretStr = Field(min_length=20, max_length=8192)


class RunRequest(BaseModel):
    end_date: date | None = None
    min_consolidation_days: int = Field(default=3, ge=1, le=15)
    max_consolidation_days: int = Field(default=12, ge=2, le=20)
    min_limit_count: int = Field(default=1, ge=1, le=5)
    max_limit_count: int = Field(default=3, ge=1, le=10)
    min_score: int = Field(default=75, ge=50, le=100)
    max_candidates: int = Field(default=100, ge=0, le=1000)
    live_rise_pct_min: float = Field(default=3.0, ge=0.0, le=20.0)
    live_volume_ratio_min: float = Field(default=1.2, ge=0.0, le=20.0)
    allow_gem: bool = False
    allow_star: bool = False

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.min_consolidation_days >= self.max_consolidation_days:
            raise ValueError("整理最少天数必须小于整理最多天数")
        if self.min_limit_count > self.max_limit_count:
            raise ValueError("最小涨停次数不能大于最大涨停次数")
        return self


def _require_local_request(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if not is_local_host(client_host):
        raise HTTPException(status_code=403, detail="iFinD 密钥只能在运行 AIROBOT 的本机配置")


@router.get("/config")
def config_status():
    return {
        **TokenStore().status(),
        "endpoint": DEFAULT_ENDPOINT,
        "secret_returned": False,
    }


@router.put("/config", dependencies=[Depends(verify_api_key)])
def save_config(payload: TokenRequest, request: Request):
    _require_local_request(request)
    store = TokenStore()
    if store.status().get("source") == "environment":
        raise HTTPException(status_code=409, detail="当前由 IFIND_AUTH_TOKEN 环境变量管理，请在启动环境中更新")
    try:
        store.save(payload.token.get_secret_value())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**store.status(), "saved": True, "secret_returned": False}


@router.get("/runs/latest")
def latest_run():
    return {"run": get_latest_run()}


@router.get("/runs/{run_id}")
def run_detail(run_id: str):
    payload = get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="回马枪任务不存在")
    return payload


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(verify_api_key)])
def create_run(payload: RunRequest):
    try:
        return start_run(
            requested_end_date=payload.end_date,
            min_consolidation_days=payload.min_consolidation_days,
            max_consolidation_days=payload.max_consolidation_days,
            min_limit_count=payload.min_limit_count,
            max_limit_count=payload.max_limit_count,
            min_score=payload.min_score,
            max_candidates=payload.max_candidates,
            live_rise_pct_min=payload.live_rise_pct_min,
            live_volume_ratio_min=payload.live_volume_ratio_min,
            allow_gem=payload.allow_gem,
            allow_star=payload.allow_star,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="请先在本页配置 iFinD 密钥") from exc
    except ActiveRunError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "run_id": exc.run_id}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel", dependencies=[Depends(verify_api_key)])
def cancel_run(run_id: str):
    payload = request_cancel(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="回马枪任务不存在")
    return payload


@router.post("/runs/{run_id}/quotes", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(verify_api_key)])
def refresh_run_quotes(run_id: str):
    try:
        payload = refresh_quotes(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="请先在本页配置 iFinD 密钥") from exc
    except ActiveRunError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "run_id": exc.run_id}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload:
        raise HTTPException(status_code=404, detail="回马枪任务不存在")
    return payload


@router.get("/runs/{run_id}/kline/{symbol}")
def run_kline(run_id: str, symbol: str):
    normalized = normalize_symbol(symbol)
    if not normalized:
        raise HTTPException(status_code=422, detail="股票代码格式无效")
    payload = get_kline(run_id, normalized)
    if not payload:
        raise HTTPException(status_code=404, detail="该任务中没有这只股票")
    return payload


@router.get("/runs/{run_id}/export.csv")
def download_csv(run_id: str):
    exported = export_csv(run_id)
    if not exported:
        raise HTTPException(status_code=404, detail="回马枪任务不存在")
    content, filename = exported
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
