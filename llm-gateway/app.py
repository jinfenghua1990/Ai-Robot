"""独立 LLM Gateway。

9002 只负责网关协议和配置，不承载 AIROBOT 页面；AIROBOT 通过 OpenAI
兼容接口访问本服务。上游地址和密钥只从环境变量读取。
"""
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

ROOT = Path(__file__).resolve().parent
UPSTREAM_BASE_URL = os.getenv("LLM_UPSTREAM_BASE_URL", "").rstrip("/")
UPSTREAM_API_KEY = os.getenv("LLM_UPSTREAM_API_KEY", "")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "code-auto")
GATEWAY_API_KEY = os.getenv("LLM_GATEWAY_API_KEY", os.getenv("LLM_API_KEY", ""))

app = FastAPI(title="Independent LLM Gateway", version="1.0.0")


def authorized(request: Request) -> bool:
    if not GATEWAY_API_KEY:
        return True
    return request.headers.get("authorization") == f"Bearer {GATEWAY_API_KEY}"


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "llm-gateway",
        "port": 9002,
        "upstream_configured": bool(UPSTREAM_BASE_URL),
        "model": DEFAULT_MODEL,
    }


@app.get("/v1/models")
async def models(request: Request):
    if not authorized(request):
        return Response(status_code=401, content='{"detail":"unauthorized"}', media_type="application/json")
    return {"object": "list", "data": [{"id": DEFAULT_MODEL, "object": "model", "owned_by": "gateway"}]}


@app.api_route("/v1/chat/completions", methods=["POST"])
async def chat_completions(request: Request):
    if not authorized(request):
        return Response(status_code=401, content='{"detail":"unauthorized"}', media_type="application/json")
    if not UPSTREAM_BASE_URL:
        return Response(
            status_code=503,
            content='{"detail":"LLM_UPSTREAM_BASE_URL is not configured"}',
            media_type="application/json",
        )
    body = await request.body()
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    if UPSTREAM_API_KEY:
        headers["authorization"] = f"Bearer {UPSTREAM_API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            upstream = await client.post(f"{UPSTREAM_BASE_URL}/chat/completions", content=body, headers=headers)
    except httpx.HTTPError as exc:
        return Response(
            status_code=502,
            content='{"detail":"LLM upstream unavailable"}',
            media_type="application/json",
            headers={"x-gateway-error": type(exc).__name__},
        )
    response_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in {"content-encoding", "transfer-encoding", "connection"}}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers, media_type=upstream.headers.get("content-type"))


@app.get("/{path:path}")
async def static_page(path: str):
    requested = (ROOT / path).resolve()
    if requested.is_file() and ROOT in requested.parents:
        return FileResponse(requested)
    return FileResponse(ROOT / "index.html")
