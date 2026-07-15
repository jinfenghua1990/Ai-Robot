"""反向代理：将子系统 API 统一收敛到 AIROBOT 端口 9000。

Hermes / DSA / AIHF / LLM Gateway / OpenClaw 后端仍然独立运行，
但浏览器/外部调用只需访问 localhost:9000：
- /api/ops/*          -> Hermes localhost:8788
- /api/mock-trading/* -> Hermes localhost:8788
- /api/v1/*           -> DSA   localhost:8000
- /_aihf_api/*        -> AIHF  localhost:8002（去掉前缀）
- /_llm_api/*         -> LLM Gateway localhost:8001（去掉前缀）
- /_openclaw/*        -> OpenClaw    localhost:18789（去掉前缀）
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response

logger = logging.getLogger("airobot.proxy")
router = APIRouter()

# 子系统代理目标（内部端口）
_HERMES_BASE = "http://127.0.0.1:8788"
_DSA_BASE = "http://127.0.0.1:8000"
_AIHF_BASE = os.environ.get("AIHF_BACKEND_URL", "http://127.0.0.1:8002")
_LLM_GATEWAY_BASE = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1:8001")
_OPENCLAW_BASE = os.environ.get("OPENCLAW_UI_URL", "http://127.0.0.1:18789")

_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
}


def _error_response(status_code: int, service: str, detail: str, hint: str) -> Response:
    import json
    return Response(
        content=json.dumps({"error": f"{service} unavailable", "detail": detail, "hint": hint},
                           ensure_ascii=False).encode(),
        status_code=status_code,
        media_type="application/json",
    )


async def _proxy_request(
    request: Request,
    target_base: str,
    path: str,
    *,
    strip_prefix: Optional[str] = None,
    timeout: float = 30.0,
) -> Response:
    """将请求转发到目标子系统后端。

    :param strip_prefix: 若提供，从请求路径中去掉此前缀后再转发。
                         例如 `/_aihf_api/` -> 转发到目标根路径。
    """
    client = request.app.state.http_client
    original_path = request.url.path
    if strip_prefix and original_path.startswith(strip_prefix):
        target_path = original_path[len(strip_prefix):]
    else:
        target_path = original_path
    # 保证根路径至少留一个 /
    target_url = f"{target_base}/{target_path.lstrip('/')}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # 转发 headers，去掉 hop-by-hop 和 host
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS and k.lower() != "host"
    }

    try:
        body = await request.body()
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body or None,
            timeout=timeout,
            follow_redirects=False,
        )
    except Exception as e:
        logger.warning("Proxy error %s -> %s: %s", request.url.path, target_url, e)
        return _error_response(
            503,
            "Upstream",
            str(e),
            "目标子系统未启动或不可达",
        )

    # 过滤响应头中的 hop-by-hop 字段
    response_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=response_headers,
    )


@router.api_route(
    "/api/ops/health",
    methods=["GET"],
    include_in_schema=False,
)
async def proxy_hermes_health(request: Request) -> Response:
    return await _proxy_request(
        request, _HERMES_BASE, "health",
        strip_prefix="/api/ops/",
    )


@router.api_route(
    "/api/ops/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy_hermes_ops(request: Request, path: str) -> Response:
    return await _proxy_request(request, _HERMES_BASE, path)


@router.api_route(
    "/api/mock-trading/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy_hermes_mock_trading(request: Request, path: str) -> Response:
    return await _proxy_request(request, _HERMES_BASE, path)


@router.api_route(
    "/api/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy_dsa(request: Request, path: str) -> Response:
    return await _proxy_request(request, _DSA_BASE, path)


# ---------------------------------------------------------------------------
# AIHF API 代理：同源路径 /_aihf_api/* 收敛到后端 8002
# ---------------------------------------------------------------------------
@router.api_route(
    "/_aihf_api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy_aihf_api(request: Request, path: str) -> Response:
    return await _proxy_request(
        request, _AIHF_BASE, path,
        strip_prefix="/_aihf_api/",
        timeout=120.0,
    )


# ---------------------------------------------------------------------------
# LLM Gateway 代理：同源路径 /_llm_api/* 收敛到后端 8001
# ---------------------------------------------------------------------------
@router.api_route(
    "/_llm_api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy_llm_gateway(request: Request, path: str) -> Response:
    return await _proxy_request(
        request, _LLM_GATEWAY_BASE, path,
        strip_prefix="/_llm_api/",
        timeout=120.0,
    )


# ---------------------------------------------------------------------------
# OpenClaw / robot3 控制面板代理：同源路径 /_openclaw/* 收敛到 18789
# ---------------------------------------------------------------------------
@router.api_route(
    "/_openclaw/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def proxy_openclaw(request: Request, path: str) -> Response:
    return await _proxy_request(
        request, _OPENCLAW_BASE, path,
        strip_prefix="/_openclaw/",
        timeout=120.0,
    )


@router.get("/_openclaw/", include_in_schema=False)
async def proxy_openclaw_index(request: Request):
    return await _proxy_request(
        request, _OPENCLAW_BASE, "",
        strip_prefix="/_openclaw/",
        timeout=120.0,
    )
