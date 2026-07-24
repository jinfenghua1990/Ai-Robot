import logging
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from config import (
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMIT_MAX_CONNECTIONS_PER_IP,
)
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("rate_limit")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """单 worker 语义的限流中间件。

    注意：
    - 多 worker 部署（uvicorn --workers N）时，每个 worker 持有独立计数器，
      全局阈值实际为 max_requests * N。需要跨 worker 一致限流请改用 Redis。
    - 中间件内不要 raise HTTPException：会被外层 ServerErrorMiddleware +
      全局 Exception handler 吞成 500。统一返回 JSONResponse。
    """

    def __init__(self, app, max_requests: int = None, window_seconds: int = None):
        super().__init__(app)
        self.max_requests = max_requests or RATE_LIMIT_MAX_REQUESTS
        self.window_seconds = window_seconds or RATE_LIMIT_WINDOW_SECONDS
        self.request_timestamps = defaultdict(list)
        # 每 IP 活跃连接计数
        self.active_connections = defaultdict(int)
        self.max_connections_per_ip = RATE_LIMIT_MAX_CONNECTIONS_PER_IP

    async def dispatch(self, request: Request, call_next):
        # request.client 在 ASGI 内部调用 / Unix socket 部署时可能为 None
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # 跳过：SSE 长连接 / 静态资源 / 健康检查 / 文档
        skip_connection_limit = (
            path == '/api/watchlist/realtime/stream' or
            path.startswith('/assets/') or
            path.startswith('/_vibe/') or
            path.startswith('/_dsa/') or
            path == '/api/health' or
            path == '/api/health/detailed' or
            path == '/openapi.json' or
            path.startswith('/docs') or
            path == '/redoc'
        )

        # 1. 并发连接数限制（防止连接积压）
        if not skip_connection_limit and self.active_connections[client_ip] >= self.max_connections_per_ip:
            logger.warning(
                "[rate_limit] 429 TOO_MANY_CONNECTIONS ip=%s path=%s active=%d/%d",
                client_ip, path, self.active_connections[client_ip], self.max_connections_per_ip
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "code": "TOO_MANY_CONNECTIONS",
                    "message": "并发连接过多，请关闭多余标签页后重试",
                    "retry_after": 5,
                },
            )

        # 2. 请求频率限制
        now = datetime.now()
        window_start = now - timedelta(seconds=self.window_seconds)

        # 过滤过期时间戳，列表为空时删除 IP key，避免长期内存泄漏
        recent = [ts for ts in self.request_timestamps[client_ip] if ts > window_start]
        if recent:
            self.request_timestamps[client_ip] = recent
        elif client_ip in self.request_timestamps:
            del self.request_timestamps[client_ip]

        if len(recent) >= self.max_requests:
            logger.warning(
                "[rate_limit] 429 RATE_LIMITED ip=%s path=%s requests=%d/%d in %ds",
                client_ip, path, len(recent), self.max_requests, self.window_seconds
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "code": "RATE_LIMITED",
                    "message": "请求过于频繁，请稍后再试",
                    "retry_after": self.window_seconds,
                },
            )

        self.request_timestamps[client_ip].append(now)
        if not skip_connection_limit:
            self.active_connections[client_ip] += 1

        try:
            response = await call_next(request)
            return response
        finally:
            if not skip_connection_limit:
                # pop 避免 KeyError；defaultdict 会按需重建
                self.active_connections[client_ip] -= 1
                if self.active_connections[client_ip] <= 0:
                    self.active_connections.pop(client_ip, None)
