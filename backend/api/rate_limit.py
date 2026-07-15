from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from config import RATE_LIMIT_MAX_REQUESTS, RATE_LIMIT_WINDOW_SECONDS
from datetime import datetime, timedelta
from collections import defaultdict

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = None, window_seconds: int = None):
        super().__init__(app)
        self.max_requests = max_requests or RATE_LIMIT_MAX_REQUESTS
        self.window_seconds = window_seconds or RATE_LIMIT_WINDOW_SECONDS
        self.request_timestamps = defaultdict(list)
        # 每 IP 活跃连接计数
        self.active_connections = defaultdict(int)
        self.max_connections_per_ip = 20  # 每 IP 最多20个并发连接

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        path = request.url.path

        # 跳过：SSE 长连接 / 静态资源 / 健康检查 / 文档
        skip_connection_limit = (
            path == '/api/watchlist/realtime/stream' or
            path.startswith('/assets/') or
            path.startswith('/_vibe/') or
            path.startswith('/_dsa/') or
            path.startswith('/_hermes/') or
            path == '/api/health' or
            path == '/api/health/detailed' or
            path == '/openapi.json' or
            path.startswith('/docs') or
            path == '/redoc'
        )

        # 1. 并发连接数限制（防止连接积压）
        if not skip_connection_limit and self.active_connections[client_ip] >= self.max_connections_per_ip:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "TOO_MANY_CONNECTIONS",
                    "message": f"并发连接过多，请关闭多余标签页后重试",
                    "retry_after": 5
                }
            )

        # 2. 请求频率限制
        now = datetime.now()
        window_start = now - timedelta(seconds=self.window_seconds)

        self.request_timestamps[client_ip] = [
            ts for ts in self.request_timestamps[client_ip]
            if ts > window_start
        ]

        if len(self.request_timestamps[client_ip]) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "RATE_LIMITED",
                    "message": f"请求过于频繁，请稍后再试",
                    "retry_after": self.window_seconds
                }
            )

        self.request_timestamps[client_ip].append(now)
        if not skip_connection_limit:
            self.active_connections[client_ip] += 1

        try:
            response = await call_next(request)
            return response
        finally:
            if not skip_connection_limit:
                self.active_connections[client_ip] -= 1
                if self.active_connections[client_ip] <= 0:
                    del self.active_connections[client_ip]
