"""
AIROBOT 市场指挥舱 - FastAPI 入口
端口 9000，同时服务 API 和前端
"""
import sys, os
import logging
import uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

# 启用慢查询监听（>200ms 记录到 logger）
import utils.slow_query_logger  # noqa: F401

from api import heatmap, rotation, lifecycle, lifecycle_v2, lifecycle_v3, money_flow, screener, portfolio, baihu, trading, analysis, bs_signals, realtime, quality, watchlist, fund_weather, bs_screener, bs_backtest, leader_system, leader_history, mx_skills, sync_pkg, sina_sync, stock_research, focus_stocks, panorama, concept_sector, strategy_tags, auto_trading, mx_trading, trading_system, yuzi, yuzi_tracker, super_panel, money_flow_detail, index_flow, liangjia_report, strategy_resonance, global_market, market_stage, git_push, alerts, report, analysis_reports, stock_tracker
from api.rate_limit import RateLimitMiddleware
from api import vibe, scheduler_api, shared, proxy
from api.auth import verify_api_key
from collectors.scheduler import start_scheduler, scheduler
from db.session import get_db_session
from db.models import SectorFlow
from sqlalchemy import func
from config import CORS_ORIGINS
from scripts.migrate import run_migrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 创建共享 httpx 客户端（复用 TCP 连接，减少 30+ 处独立创建的开销）
    import httpx
    app.state.http_client = httpx.AsyncClient(
        timeout=10,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        headers={"User-Agent": "AIROBOT/1.0"},
    )
    # 将共享客户端注入到 _shared 模块，供非路由函数使用
    from api.watchlist._shared import set_shared_http_client
    set_shared_http_client(app.state.http_client)
    # 启动时开始定时采集
    start_scheduler()
    # 确保新表/新列存在（轻量级迁移）
    run_migrations()
    # 启动研报中心 consumer（后台轮询 pending 请求并自动生成报告）
    start_analysis_consumer()
    # 本地自选股 JSON → DB 同步（启动时执行，确保 DB 与 JSON 一致）
    from api.watchlist.watchlist_local import sync_to_db
    sync_to_db()
    # 预热自选股缓存（后台异步，不阻塞启动）
    from api.watchlist import _refresh_watchlist_cache
    _refresh_watchlist_cache()
    # 预热共享数据缓存（持仓/重点关注）
    try:
        from api.shared import _refresh_portfolio, _export_focus_stocks
        await _refresh_portfolio(force=False)
        _export_focus_stocks()
    except Exception as e:
        logger.warning(f'[startup] shared cache warmup error: {e}', exc_info=True)
    # 聚合预热其他热点缓存（串行，避免外部API限流）
    import asyncio
    asyncio.create_task(_refresh_caches())
    yield
    # 关闭时清理：必须先停 scheduler（停止所有 job），再关 http_client
    # 否则 job 仍在用 http_client → 'RuntimeError: handler is closed'
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        logger.debug("scheduler.shutdown ignored", exc_info=False)
    await app.state.http_client.aclose()


async def _refresh_caches():
    """聚合预热/刷新各模块缓存，串行调用避免外部API限流"""
    try:
        from api.concept_sector import _refresh_hot_cache
        from api.heatmap import refresh_heatmap_cache
        from api.analysis import refresh_signal_cache
        # 纯DB缓存先行（快）
        _refresh_hot_cache()
        refresh_heatmap_cache()
        # 预热 index-flow（避免首次访问 25 秒卡顿）
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                await client.get('http://127.0.0.1:9000/api/index-flow/rank')
            logger.info('[startup] index-flow cache preheated')
        except Exception as e:
            logger.warning(f'[startup] index-flow preheat skip: {e}')
        # 依赖妙想API的缓存（慢，盘中才有意义，盘前失败可忽略）
        await refresh_signal_cache()
        logger.info('[startup] cache warmup done')
    except Exception as e:
        logger.warning(f'[startup] cache warmup error: {e}', exc_info=True)


def start_analysis_consumer():
    """后台守护线程：每 10 秒轮询 pending 请求并自动生成报告（PG 落库）"""
    import threading, time, logging
    from services.analysis_consumer import process_pending
    logger = logging.getLogger("analysis_consumer")
    started = getattr(start_analysis_consumer, "_started", False)
    if started:
        return
    start_analysis_consumer._started = True

    def _loop():
        while True:
            try:
                n = process_pending()
                if n:
                    logger.info("[analysis_consumer] 本轮处理 %s 个请求", n)
            except Exception as e:
                logger.warning("[analysis_consumer] loop error: %s", e)
            time.sleep(10)

    t = threading.Thread(target=_loop, daemon=True, name="analysis-consumer")
    t.start()
    logger.info("[analysis_consumer] 后台循环已启动")


app = FastAPI(title="AIROBOT 市场指挥舱", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip 压缩：压缩 API 响应与静态资源（含 echarts 等大体积 JS），首屏传输体积显著下降
app.add_middleware(GZipMiddleware, minimum_size=512)

# 限流中间件
app.add_middleware(RateLimitMiddleware)

# 静态资源缓存：/assets 是 Vite 内容哈希产物（文件名即版本，内容变更必换名），
# 可安全长期缓存。index.html 走 serve_frontend 的 no-cache，不受影响。
@app.middleware("http")
async def cache_static_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

# API路由
app.include_router(alerts.router)
app.include_router(heatmap.router)
app.include_router(rotation.router)
app.include_router(lifecycle.router)
app.include_router(lifecycle_v2.router)
app.include_router(lifecycle_v3.router)
app.include_router(money_flow.router)
app.include_router(screener.router)
app.include_router(portfolio.router)
app.include_router(analysis_reports.router)
app.include_router(stock_tracker.router)
app.include_router(baihu.router)
app.include_router(trading.router)
app.include_router(analysis.router)
app.include_router(bs_signals.router)
app.include_router(realtime.router)
app.include_router(quality.router)
app.include_router(watchlist.router)
app.include_router(fund_weather.router)
app.include_router(bs_screener.router)
app.include_router(bs_backtest.router)
app.include_router(leader_system.router)
app.include_router(leader_history.router)
app.include_router(mx_skills.router)
app.include_router(sync_pkg.router)
app.include_router(sina_sync.router)
app.include_router(stock_research.router)
app.include_router(focus_stocks.router)
app.include_router(panorama.router)
app.include_router(index_flow.router)
app.include_router(concept_sector.router)
app.include_router(strategy_tags.router)
app.include_router(auto_trading.router)
app.include_router(mx_trading.router)
app.include_router(trading_system.router)
app.include_router(yuzi.router)
app.include_router(yuzi_tracker.router)
app.include_router(super_panel.router)
app.include_router(money_flow_detail.router)
app.include_router(liangjia_report.router)
app.include_router(strategy_resonance.router)
app.include_router(global_market.router)
app.include_router(market_stage.router)
app.include_router(git_push.router)
app.include_router(vibe.router)
app.include_router(report.router)
app.include_router(scheduler_api.router)

# 共享数据层：自选股/持仓/重点关注（所有子系统共享）
app.include_router(shared.router)

# 反向代理：将 Hermes / DSA 子系统 API 收敛到 9000 端口
app.include_router(proxy.router)


@app.get("/api/health")
async def health():
    from datetime import datetime
    import psutil
    pid = os.getpid()
    proc = psutil.Process(pid)
    return {
        "status": "ok",
        "service": "AIROBOT",
        "version": "2026.07.10",
        "pid": pid,
        "uptime_sec": int((datetime.now() - datetime.fromtimestamp(proc.create_time())).total_seconds()),
        "rss_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
        "cpu_pct": round(proc.cpu_percent(interval=0), 1),
        "endpoints_count": len(app.routes),
    }


@app.get("/api/health/detailed")
async def health_detailed():
    """深度健康检查：含数据库/磁盘/各子模块状态"""
    from datetime import datetime
    import psutil
    import shutil

    pid = os.getpid()
    proc = psutil.Process(pid)
    uptime_sec = int((datetime.now() - datetime.fromtimestamp(proc.create_time())).total_seconds())

    # 数据库连通性
    db_ok = True
    db_err = None
    try:
        from sqlalchemy import text
        from db.connection import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_ok = False
        db_err = str(e)[:120]

    # 磁盘
    disk = shutil.disk_usage(os.path.expanduser("~"))

    # 数据源健康（直接查 data_source_registry 已注册的源数）
    source_count = 0
    try:
        from collectors.data_source_registry import DATA_SOURCES
        source_count = len(DATA_SOURCES)
    except Exception:
        source_count = 0

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "AIROBOT",
        "pid": pid,
        "uptime_sec": uptime_sec,
        "rss_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
        "cpu_pct": round(proc.cpu_percent(interval=0), 1),
        "threads": proc.num_threads(),
        "endpoints": len(app.routes),
        "database": {
            "ok": db_ok,
            "error": db_err,
        },
        "disk": {
            "total_gb": round(disk.total / 1024**3, 1),
            "used_gb": round(disk.used / 1024**3, 1),
            "free_gb": round(disk.free / 1024**3, 1),
            "used_pct": round(disk.used / disk.total * 100, 1),
        },
        "data_sources_registered": source_count,
    }


# 全局异常处理：未捕获异常返回统一结构 + request_id 日志，避免 500 裸奔
logger = logging.getLogger("airobat")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = uuid.uuid4().hex[:8]
    logger.exception("Unhandled error", extra={"request_id": rid})
    return JSONResponse(status_code=500, content={
        "title": "INTERNAL_ERROR",
        "status": 500,
        "detail": "服务器内部错误，请稍后重试",
        "request_id": rid,
    })


@app.get("/api/latest-date")
def latest_date():
    """返回数据库中最新有数据的交易日期"""
    with get_db_session() as db:
        result = db.query(func.max(SectorFlow.trade_date)).scalar()
        if result:
            return {"date": result.strftime('%Y-%m-%d')}
        return {"date": None}


# Vibe-Research 子系统静态资源（独立构建产物，browser-router SPA）
# 挂载到 /_vibe/ 避免和 AIROBOT 前端 /vibe/* 路由冲突；iframe 通过 /_vibe/* 加载原生 Vibe 页面
vibe_static = os.path.join(os.path.dirname(__file__), 'static', 'vibe')
if os.path.exists(vibe_static):
    app.mount("/_vibe/assets", StaticFiles(directory=os.path.join(vibe_static, 'assets')), name="vibe_assets")

    @app.get("/_vibe/{full_path:path}")
    async def serve_vibe(full_path: str):
        # Vibe 内部 API 不存在时返回真实 404（StaticFiles 会处理 /vibe/assets）
        if full_path.startswith('api/'):
            raise HTTPException(status_code=404, detail="Not found")
        index_path = os.path.join(vibe_static, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type='text/html', headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
        return JSONResponse({"error": "Vibe frontend not built"}, status_code=503)


# ---------------------------------------------------------------------------
# daily_stock_analysis (DSA) 子系统集成
# DSA 后端作为独立子进程运行在 127.0.0.1:8000（与 AIROBOT 9000 隔离，避免依赖冲突）
# AIROBOT 反向代理 /api/v1/* 和 /stocks.index.json 到 8000，托管 DSA 前端静态资源
# ---------------------------------------------------------------------------
import httpx as _httpx
DSA_BACKEND_URL = os.environ.get("DSA_BACKEND_URL", "http://127.0.0.1:8000")

async def _dsa_proxy(request: Request, path: str):
    """反向代理到 DSA 后端 8000。后端未启动时返回 503。"""
    # 特别处理：DSA 持仓快照 → 直接从 api.trading 模块读取（不用HTTP自调用，避免死锁）
    if path == "api/v1/portfolio/snapshot":
        # 使用共享数据层（统一读 portfolio.json，所有子系统共享）
        try:
            from datetime import date
            from api.shared import get_portfolio
            pf = get_portfolio()
            items = []
            for p in pf.get("positions", []):
                items.append({
                    "symbol": p.get("symbol", ""), "market": "cn", "currency": "CNY",
                    "quantity": p.get("quantity", 0) or 0,
                    "avg_cost": float(p.get("avg_cost", 0) or 0),
                    "last_price": float(p.get("last_price", 0) or 0),
                    "market_value_base": float(p.get("market_value", 0) or 0),
                    "unrealized_pnl_base": float(p.get("unrealized_pnl", 0) or 0),
                    "price_source": "realtime_quote", "price_available": True,
                })
            mv = pf.get("total_market_value", 0)
            up = pf.get("total_unrealized_pnl", 0)
            return JSONResponse({
                "as_of": date.today().isoformat(), "cost_method": "avg", "currency": "CNY",
                "account_count": 1, "total_cash": 0.0, "total_market_value": mv,
                "total_equity": mv, "realized_pnl": 0.0, "unrealized_pnl": up,
                "fee_total": 0.0, "tax_total": 0.0, "fx_stale": False,
                "data_quality": "ok", "limitations": [],
                "accounts": [{
                    "account_id": 1, "account_name": "模拟交易", "market": "cn",
                    "base_currency": "CNY", "as_of": date.today().isoformat(),
                    "cost_method": "avg", "total_cash": 0.0,
                    "total_market_value": mv, "total_equity": mv,
                    "realized_pnl": 0.0, "unrealized_pnl": up,
                    "fee_total": 0.0, "tax_total": 0.0, "fx_stale": False,
                    "data_quality": "ok", "limitations": [], "positions": items,
                }]
            })
        except Exception as e:
            logger.warning(f"[DSA portfolio bridge] shared data failed: {e}")
        # fall through to DSA backend
    target = f"{DSA_BACKEND_URL}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    method = request.method
    # 简化 headers：仅透传必要头，避免 httpx 对 list 类型调用 .items()
    skip_req = {'host', 'content-length', 'transfer-encoding', 'connection'}
    headers = {}
    for k, v in request.headers.items():
        if k.lower() not in skip_req:
            headers[k] = v
    body = await request.body()
    client: _httpx.AsyncClient = app.state.http_client
    try:
        upstream = await client.request(
            method, target, headers=headers, content=body or None, timeout=60,
        )
        # 过滤 hop-by-hop 头，用 dict 传给 Response
        skip_resp = {'content-encoding', 'transfer-encoding', 'connection', 'content-length'}
        resp_headers = {}
        for k, v in upstream.headers.items():
            if k.lower() not in skip_resp:
                resp_headers[k] = v
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=upstream.headers.get('content-type'),
        )
    except Exception as e:
        return JSONResponse(
            {"error": "DSA backend unavailable", "detail": str(e), "hint": "请启动 DSA 后端：./start_dsa.sh (端口 8000)"},
            status_code=503,
        )

@app.api_route("/api/v1/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def dsa_api_proxy(full_path: str, request: Request):
    return await _dsa_proxy(request, f"api/v1/{full_path}")

@app.api_route("/stocks.index.json", methods=["GET", "HEAD"], include_in_schema=False)
async def dsa_stock_index_proxy(request: Request):
    return await _dsa_proxy(request, "stocks.index.json")

# DSA 前端静态资源
dsa_static = os.path.join(os.path.dirname(__file__), 'static', 'dsa')
if os.path.exists(dsa_static):
    app.mount("/_dsa/assets", StaticFiles(directory=os.path.join(dsa_static, 'assets')), name="dsa_assets")

    @app.get("/_dsa/{full_path:path}")
    async def serve_dsa(full_path: str):
        if full_path.startswith('api/'):
            raise HTTPException(status_code=404, detail="Not found")
        index_path = os.path.join(dsa_static, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type='text/html', headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
        return JSONResponse({"error": "DSA frontend not built"}, status_code=503)


# ---------------------------------------------------------------------------
# Hermes Cockpit 子系统（仅前端静态资源，后端API已停用，数据库已迁移）
# 前端静态文件由 /_hermes/ 路由提供，API 代理已被移除
# ---------------------------------------------------------------------------

# Hermes 前端静态资源
hermes_static = os.path.join(os.path.dirname(__file__), 'static', 'hermes')
if os.path.exists(hermes_static):
    app.mount("/_hermes/assets", StaticFiles(directory=os.path.join(hermes_static, 'assets')), name="hermes_assets")

    @app.get("/_hermes/")
    @app.get("/_hermes/{full_path:path}")
    async def serve_hermes(full_path: str = ""):
        if full_path.startswith('api/') or full_path == '':
            full_path = 'index.html'
        file_path = os.path.join(hermes_static, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_path = os.path.join(hermes_static, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type='text/html', headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
        return Response("", status_code=404)


# ---------------------------------------------------------------------------
# AI Hedge Fund (AIHF) 子系统集成
# 后端独立运行在 127.0.0.1:8002（避免与 DSA 8000 冲突）
# 前端构建产物托管于 /_aihf/，API 经同源代理 /_aihf_api/ 转发到 8002
# ---------------------------------------------------------------------------
AIHF_BACKEND_URL = os.environ.get("AIHF_BACKEND_URL", "http://127.0.0.1:8002")

aihf_static = os.path.join(os.path.dirname(__file__), 'static', 'aihf')
if os.path.exists(aihf_static):
    app.mount("/_aihf/assets", StaticFiles(directory=os.path.join(aihf_static, 'assets')), name="aihf_assets")

    @app.get("/_aihf/")
    @app.get("/_aihf/{full_path:path}")
    async def serve_aihf(full_path: str = ""):
        if full_path.startswith('api/'):
            full_path = 'index.html'
        file_path = os.path.join(aihf_static, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        index_path = os.path.join(aihf_static, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type='text/html', headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache", "Expires": "0"})
        return Response("", status_code=404)


# ---------------------------------------------------------------------------
# AIHF 自动报告控制台（run_aihf_report.py 产出）
# 纯静态 JSON + 自包含 HTML，挂到 9000 同端口，无需额外 8799 服务。
# 前端 AIHF 页面以 iframe 内嵌 /_aihf_reports/_dashboard/index.html
# ---------------------------------------------------------------------------
REPORTS_DIR = os.path.realpath(
    os.environ.get("AIHF_REPORT_DIR", os.path.join(os.path.expanduser("~"), "Workbuddy", "aihf-reports"))
)
if os.path.isdir(REPORTS_DIR):
    app.mount("/_aihf_reports", StaticFiles(directory=REPORTS_DIR, html=True), name="aihf_reports")


# ---------------------------------------------------------------------------
# TradingAgents (TAgents) 运行器
# TAgents 无 Web UI，由 AIROBOT 提供表单 + 后台子进程运行 + 日志轮询
# ---------------------------------------------------------------------------
import uuid as _uuid
TAGENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stock-tools', 'trading-agents')
TAGENTS_RUNS = os.path.join(TAGENTS_DIR, '.runs')
os.makedirs(TAGENTS_RUNS, exist_ok=True)


def _load_tagents_env():
    env = dict(os.environ)
    env_path = os.path.join(TAGENTS_DIR, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env


@app.post("/api/tagents/run")
async def tagents_run(request: Request):
    data = await request.json()
    ticker = str(data.get('ticker', 'NVDA')).strip().upper() or 'NVDA'
    trade_date = str(data.get('trade_date', '2024-05-10')).strip() or '2024-05-10'
    asset_type = str(data.get('asset_type', 'stock')).strip() or 'stock'
    run_id = _uuid.uuid4().hex[:8]
    log_path = os.path.join(TAGENTS_RUNS, f"{run_id}.log")
    venv_py = os.path.join(TAGENTS_DIR, '.venv', 'bin', 'python')
    py = venv_py if os.path.exists(venv_py) else 'python3'
    runner = os.path.join(TAGENTS_DIR, 'run_analysis.py')
    env = _load_tagents_env()
    try:
        import subprocess
        with open(log_path, 'w') as lf:
            lf.write(f"[init] run_id={run_id} ticker={ticker} date={trade_date} asset={asset_type}\n")
            lf.flush()
            subprocess.Popen(
                [py, runner, ticker, trade_date, asset_type],
                cwd=TAGENTS_DIR, env=env, stdout=lf, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        return {"run_id": run_id, "ticker": ticker, "trade_date": trade_date,
                "log_url": f"/api/tagents/log/{run_id}"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/tagents/log/{run_id}")
async def tagents_log(run_id: str):
    log_path = os.path.join(TAGENTS_RUNS, f"{run_id}.log")
    if not os.path.exists(log_path):
        return JSONResponse({"status": "not_found"}, status_code=404)
    with open(log_path) as f:
        content = f.read()
    done = ("END ====================" in content) or ("[run_analysis] ERROR" in content)
    return {"run_id": run_id, "running": not done, "log": content}


# ---------------------------------------------------------------------------
# AI Hedge Fund (AIHF) 后端启动控制
# 后端在 127.0.0.1:8002 独立运行；前端由 AIROBOT 静态托管 /_aihf/
# ---------------------------------------------------------------------------
import subprocess as _subprocess
AIHF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'stock-tools', 'ai-hedge-fund')

@app.get("/api/aihf/status")
async def aihf_status():
    running = False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=4, trust_env=False) as c:
            r = await c.get(f"{AIHF_BACKEND_URL}/")
        running = r.status_code == 200
    except Exception:
        running = False
    has_market_key = bool(_read_aihf_env()[0].get("FINANCIAL_DATASETS_API_KEY"))
    return {"running": running, "url": AIHF_BACKEND_URL, "has_market_key": has_market_key}

@app.post("/api/aihf/start")
async def aihf_start():
    # 已在运行则跳过
    try:
        import httpx
        async with httpx.AsyncClient(timeout=4, trust_env=False) as c:
            r = await c.get(f"{AIHF_BACKEND_URL}/")
        if r.status_code == 200:
            return {"status": "already_running", "url": AIHF_BACKEND_URL}
    except Exception:
        logger.debug("AIHF already-running check failed", exc_info=False)
    venv_py = os.path.join(AIHF_DIR, '.venv', 'bin', 'python')
    try:
        env = dict(os.environ)
        env_path = os.path.join(AIHF_DIR, '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
        env["PYTHONPATH"] = AIHF_DIR
        logf = open(os.path.join(AIHF_DIR, 'aihf_backend.log'), 'w')
        _subprocess.Popen(
            [venv_py, "-m", "uvicorn", "app.backend.main:app", "--host", "127.0.0.1", "--port", "8002"],
            cwd=AIHF_DIR, env=env, stdout=logf, stderr=_subprocess.STDOUT, start_new_session=True,
        )
        return {"status": "starting", "url": AIHF_BACKEND_URL}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _read_aihf_env():
    """读取 ai-hedge-fund/.env，返回 (dict, path)。仅解析 KEY=VALUE 行。"""
    path = os.path.join(AIHF_DIR, ".env")
    kv = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                kv[k.strip()] = v.strip()
    return kv, path


def _restart_aihf():
    """重启 AIHF 后端使新 .env 生效：优先 launchctl 重启 KeepAlive 任务，
    失败则直接拉起 uvicorn（复用 .env 中的 Key）。"""
    label = "com.airobot.aihf"
    uid = os.getuid()
    try:
        _subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"],
            check=False, timeout=20,
        )
        return True
    except Exception:
        logger.debug("AIHF already-running check failed", exc_info=False)
    try:
        venv_py = os.path.join(AIHF_DIR, ".venv", "bin", "python")
        kv, _ = _read_aihf_env()
        env = dict(os.environ)
        env.update(kv)
        env["PYTHONPATH"] = AIHF_DIR
        _subprocess.Popen(
            [venv_py, "-m", "uvicorn", "app.backend.main:app",
             "--host", "127.0.0.1", "--port", "8002"],
            cwd=AIHF_DIR, env=env,
            stdout=open(os.path.join(AIHF_DIR, "aihf_backend.log"), "a"),
            stderr=_subprocess.STDOUT, start_new_session=True,
        )
        return True
    except Exception:
        return False


@app.get("/api/aihf/config")
async def aihf_config_get():
    kv, _ = _read_aihf_env()
    return {"has_market_key": bool(kv.get("FINANCIAL_DATASETS_API_KEY"))}


@app.post("/api/aihf/config")
async def aihf_config_set(request: Request):
    data = await request.json()
    key = str(data.get("key", "")).strip()
    kv, path = _read_aihf_env()
    if key:
        kv["FINANCIAL_DATASETS_API_KEY"] = key
    else:
        kv.pop("FINANCIAL_DATASETS_API_KEY", None)
    # 原地写回 .env，保留其他行与注释
    lines = []
    seen = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k = s.split("=", 1)[0].strip()
                    if k in kv:
                        lines.append(f"{k}={kv[k]}\n")
                        seen.add(k)
                        continue
                lines.append(line if line.endswith("\n") else line + "\n")
    for k, v in kv.items():
        if k not in seen:
            lines.append(f"{k}={v}\n")
    with open(path, "w") as f:
        f.writelines(lines)
    restarted = _restart_aihf()
    return {
        "status": "ok",
        "has_market_key": bool(kv.get("FINANCIAL_DATASETS_API_KEY")),
        "restarted": restarted,
    }


@app.get("/api/aihf/test-connection")
async def aihf_test_connection():
    """验证 AIHF 行情数据源连通性：
       - DATA_PROVIDER=yfinance：免费雅虎源，打 Yahoo chart 接口验证（无需 Key）
       - 否则：测 financialdatasets.ai（无 Key / Key 被拒 / 额度$0 / 不可达 分别提示）。"""
    kv, _ = _read_aihf_env()
    provider = (kv.get("DATA_PROVIDER") or os.environ.get("DATA_PROVIDER", "financialdatasets")).lower()
    if provider == "yfinance":
        try:
            r = await app.state.http_client.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=5d",
                timeout=12,
            )
            if r.status_code == 200:
                return {"ok": True, "state": "free", "status_code": 200,
                        "message": "免费数据源（雅虎财经 yfinance）连接正常，无需额度即可跑真实分析"}
            return {"ok": False, "state": "error", "status_code": r.status_code,
                    "message": f"雅虎行情接口返回 HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "state": "unreachable", "status_code": None,
                    "message": f"无法连接雅虎行情：{str(e)[:120]}"}
    key = kv.get("FINANCIAL_DATASETS_API_KEY")
    if not key:
        return {"ok": False, "state": "no_key", "status_code": None,
                "message": "尚未配置 FINANCIAL_DATASETS_API_KEY"}
    url = "https://api.financialdatasets.ai/prices/snapshot?ticker=AAPL"
    try:
        r = await app.state.http_client.get(
            url, headers={"X-API-KEY": key}, timeout=12,
        )
        if r.status_code == 200:
            return {"ok": True, "state": "ok", "status_code": 200,
                    "message": "行情数据源连接正常，账户额度可用"}
        if r.status_code == 402:
            return {"ok": False, "state": "no_credits", "status_code": 402,
                    "message": "Key 有效，但账户额度为 $0.00 —— 需到 financialdatasets.ai 充值后才能拉取真实数据"}
        if r.status_code in (401, 403):
            return {"ok": False, "state": "invalid_key", "status_code": r.status_code,
                    "message": f"Key 被拒绝（HTTP {r.status_code}），可能无效或已失效"}
        return {"ok": False, "state": "error", "status_code": r.status_code,
                "message": f"行情数据源返回 HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "state": "unreachable", "status_code": None,
                "message": f"无法连接 financialdatasets.ai：{str(e)[:120]}"}


# ---------------------------------------------------------------------------
# 服务健康聚合：供前端顶栏「健康灯」使用
# 状态语义：up=运行中(绿) / down=离线(红) / ready|idle=按需/待命(琥珀)
# ---------------------------------------------------------------------------
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8001")


@app.get("/api/services/status")
async def services_status():
    """聚合各子服务健康状态。"""
    import httpx
    async def _up(url, ok_codes=(200, 401)):
        # 内部服务健康检查：用独立 client 且 trust_env=False，
        # 避免本机 HTTP_PROXY 把 127.0.0.1 请求转发到代理导致误判离线。
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False) as c:
                r = await c.get(url)
                return r.status_code in ok_codes
        except Exception:
            return False

    gateway_up = await _up(f"{GATEWAY_URL}/")
    dsa_up = await _up(f"{DSA_BACKEND_URL}/")
    # 注意：AIHF 的 /ping 是 5 秒 SSE 流（非健康探测），此处改探根路径 /（瞬时 200）
    aihf_running = await _up(f"{AIHF_BACKEND_URL}/")

    # TAgents：venv + .env + runner 就绪（按需运行）
    tagents_ready = (
        os.path.exists(os.path.join(TAGENTS_DIR, ".venv", "bin", "python"))
        and os.path.exists(os.path.join(TAGENTS_DIR, ".env"))
        and os.path.exists(os.path.join(TAGENTS_DIR, "run_analysis.py"))
    )
    # go-stock：已构建且已装入 /Applications（go-stock 已废弃，永远为 False）
    gostock_ready = os.path.exists("/Applications/go-stock.app")

    aihf_kv, _ = _read_aihf_env()

    services = [
        {"key": "airobot", "label": "AIROBOT", "status": "up", "detail": "门户主服务 · 9000", "path": "/panorama"},
        {"key": "gateway", "label": "LLM 网关", "status": "up" if gateway_up else "down", "detail": "免费 LLM 网关 · 8001", "path": None},
        {"key": "dsa", "label": "DSA", "status": "up" if dsa_up else "down", "detail": "智能分析 · 8000", "path": "/dsa"},
        {"key": "aihf", "label": "AI Hedge Fund", "status": "up" if aihf_running else "down",
         "detail": "AI 对冲基金 · 8002", "has_market_key": bool(aihf_kv.get("FINANCIAL_DATASETS_API_KEY")), "path": "/aihf"},
        {"key": "tagents", "label": "TradingAgents", "status": "ready" if tagents_ready else "idle", "detail": "交易智能体 · 按需运行", "path": "/tagents"},
    ]
    return {"services": services}


# 前端静态资源（构建后存在）
frontend_dist = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, 'assets')), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API路径返回真实 404 状态码
        if full_path.startswith('api/'):
            raise HTTPException(status_code=404, detail="Not found")
        index_path = os.path.join(frontend_dist, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type='text/html', headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
        return JSONResponse({"error": "Frontend not built"}, status_code=503)


if __name__ == '__main__':
    import uvicorn
    from config import API_PORT
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
