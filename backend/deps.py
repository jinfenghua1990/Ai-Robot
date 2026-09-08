"""FastAPI 依赖注入工具"""
import httpx
from fastapi import Request


def get_http_client(request: Request) -> httpx.AsyncClient:
    """获取共享 httpx 客户端（由 main.py lifespan 创建）"""
    return request.app.state.http_client
