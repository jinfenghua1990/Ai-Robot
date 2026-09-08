import hmac
import ipaddress
import socket
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import READ_ONLY_DB_URL
from fastapi import HTTPException, Query, Request, status, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Optional, Tuple

engine_readonly = create_engine(READ_ONLY_DB_URL, pool_size=5, max_overflow=10, pool_pre_ping=True)
SessionReadOnly = sessionmaker(bind=engine_readonly, autocommit=False, autoflush=False)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
WRITE_AUTH_COOKIE = "airobot_write_token"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_loopback_client(host: str) -> bool:
    """仅信任直接连接的回环地址，不采信可伪造的转发头。"""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_local_host(host: str) -> bool:
    """判断请求是否来自运行服务的同一台机器。

    除回环地址外，也接受本机网卡地址（例如用户在本机通过
    http://192.168.x.x:9000 打开页面）。不会把整个局域网都视为可信来源。
    """
    if is_loopback_client(host):
        return True
    if not host:
        return False
    try:
        local_hosts = {
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None)
            if info[4]
        }
        return host in local_hosts
    except (OSError, socket.gaierror):
        return False


def is_write_auth_client(host: str) -> bool:
    """允许本机及显式配置的可信客户端领取 HttpOnly 写入会话。"""
    if is_local_host(host):
        return True
    from config import WRITE_AUTH_TRUSTED_HOSTS
    return host in WRITE_AUTH_TRUSTED_HOSTS


def api_key_error(provided_key: str) -> Optional[Tuple[int, dict]]:
    """返回鉴权错误；None 表示 key 有效。"""
    from config import API_READ_KEY

    if not API_READ_KEY:
        return status.HTTP_503_SERVICE_UNAVAILABLE, {
            "code": "AUTH_NOT_CONFIGURED",
            "message": "API_READ_KEY 未配置，服务拒绝写操作",
        }
    if not hmac.compare_digest(provided_key or "", API_READ_KEY):
        return status.HTTP_401_UNAUTHORIZED, {
            "code": "UNAUTHORIZED",
            "message": "Invalid API key",
        }
    return None


class WriteAuthMiddleware(BaseHTTPMiddleware):
    """统一保护所有 /api 写请求，避免新路由漏加 Depends。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method in WRITE_METHODS and (path == "/api" or path.startswith("/api/")):
            provided_key = (
                request.headers.get("X-API-Key")
                or request.cookies.get(WRITE_AUTH_COOKIE)
                or request.query_params.get("api_key")
                or ""
            )
            error = api_key_error(provided_key)
            if error:
                status_code, detail = error
                return JSONResponse(status_code=status_code, content={"detail": detail})
        return await call_next(request)


def mark_write_operations_protected(schema: dict) -> dict:
    """让 OpenAPI 如实标注由中间件统一保护的写操作。"""
    scheme_name = "WriteAPIKey"
    security_schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    security_schemes[scheme_name] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "所有 /api 写操作必须提供 API key。",
    }
    for path, path_item in schema.get("paths", {}).items():
        if not (path == "/api" or path.startswith("/api/")):
            continue
        for method in ("post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if operation is None:
                continue
            security = operation.setdefault("security", [])
            if not any(scheme_name in requirement for requirement in security):
                security.append({scheme_name: []})
    return schema

def get_readonly_db():
    db = SessionReadOnly()
    try:
        yield db
    finally:
        db.close()

async def verify_api_key(
    request: Request,
    api_key_header_val: Optional[str] = Security(api_key_header),
    api_key_query: Optional[str] = Query(None, alias="api_key", include_in_schema=False),
):
    """验证 API Key（Header、同源 HttpOnly Cookie 或 query param）。

    fail-closed：环境变量 API_READ_KEY 未配置时拒绝所有请求（防止误上线裸奔），
    配置后要求请求携带正确 key 才放行。"""
    # 与 WriteAuthMiddleware 使用相同的优先级；否则页面已携带的
    # HttpOnly 写入 Cookie 会通过中间件、却在带 Depends 的路由再次被拒绝。
    api_key = (
        api_key_header_val
        or request.cookies.get(WRITE_AUTH_COOKIE)
        or api_key_query
        or ""
    )
    error = api_key_error(api_key)
    if error:
        status_code, detail = error
        raise HTTPException(status_code=status_code, detail=detail)
    return api_key
