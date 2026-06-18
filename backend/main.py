"""
AIROBOT 市场指挥舱 - FastAPI 入口
端口 9000，同时服务 API 和前端
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api import heatmap, rotation, lifecycle, money_flow, screener
from collectors.scheduler import start_scheduler, scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时开始定时采集
    start_scheduler()
    yield
    # 关闭时停止调度器
    scheduler.shutdown()


app = FastAPI(title="AIROBOT 市场指挥舱", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API路由
app.include_router(heatmap.router)
app.include_router(rotation.router)
app.include_router(lifecycle.router)
app.include_router(money_flow.router)
app.include_router(screener.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "AIROBOT"}


# 前端静态资源（构建后存在）
frontend_dist = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, 'assets')), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API路径不拦截
        if full_path.startswith('api/'):
            return {"error": "Not found"}
        index_path = os.path.join(frontend_dist, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built"}


if __name__ == '__main__':
    import uvicorn
    from config import API_PORT
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
