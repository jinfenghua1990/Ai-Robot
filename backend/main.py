"""
AIROBOT 市场指挥舱 - FastAPI 入口
端口 9000，同时服务 API 和前端
"""
import sys, os
import logging
import uuid
import asyncio
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 允许 9000 后端渐进式导入项目根目录下的 V2 候选因子模块；
# 不依赖 9001 进程，只复用同一仓库中的研究定义与数据库表。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from starlette.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

# 启用慢查询监听（>200ms 记录到 logger）
import utils.slow_query_logger  # noqa: F401

from api import heatmap, rotation, lifecycle, lifecycle_v2, lifecycle_v3, money_flow, screener, baihu, trading, analysis, bs_signals, realtime, quality, watchlist, fund_weather, bs_screener, bs_backtest, leader_system, leader_history, mx_skills, sync_pkg, stock_research, focus_stocks, panorama, concept_sector, strategy_tags, auto_trading, mx_trading, trading_system, yuzi, yuzi_tracker, super_panel, money_flow_detail, index_flow, liangjia_report, strategy_resonance, global_market, market_stage, git_push, alerts, report, analysis_reports, stock_tracker, strategy_vreversal, market_dashboard, medium_term
from api import hk_strategy, hk_snapshot
from api import strategy_track
from api import wave_analysis
from api import index_daily
from api import quant_vnext, quant_embedded, sector_rotation, us_sector_rotation
from api import v2_research
from api import us_quant
from api import market_quant
from api import usmart_sync
from api import us_positions
from api import tiger_sync
from api import us_stock_analysis
from api import us_bs_strategy
from api import us_strategy_track
from api import price_levels
from api import strategy_scan
from api import factor_backtest
from api import monitor_rules
from api import google_sheets
from api import ladder
from api import horizontal
from api import horseback
from api import horseback_track
from api.rate_limit import RateLimitMiddleware
from api import scheduler_api, shared, proxy, stock_dashboard, research_workspace
from api.auth import (
    WRITE_AUTH_COOKIE,
    WriteAuthMiddleware,
    is_write_auth_client,
    mark_write_operations_protected,
    verify_api_key,
)
from api import stock_info
from industry_stage.api import router as industry_stage_router

from collectors.scheduler import start_scheduler, scheduler
from db.session import get_db_session
from db.models import SectorFlow
from sqlalchemy import func
from config import CORS_ORIGINS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
    # 回马枪：回收上次进程残留的 ACTIVE 僵尸任务，避免永久阻塞当日扫描/刷新
    try:
        from horseback.service import recover_orphaned_runs
        recovered = recover_orphaned_runs()
        if recovered:
            logger.info("[horseback] 启动回收孤儿任务 %d 个", recovered)
    except Exception as e:
        logger.warning(f"[horseback] 启动回收孤儿任务失败: {e}")
    # 确保新表/新列存在（轻量级迁移）
    run_migrations()
    # 启动研报中心 consumer（后台轮询 pending 请求并自动生成报告）
    start_analysis_consumer()
    # 自选股以数据库为唯一真相源；JSON 仅导出给尚未迁移的旧脚本。
    from api.watchlist.watchlist_local import export_db_to_local
    export_db_to_local()
    # 创建 US Quant 表
    try:
        from us_quant.repository import ensure_schema
        ensure_schema()
        logger.info("[us-quant] 数据库表已创建")
    except Exception as e:
        logger.warning(f"[us-quant] 建表失败: {e}")
    try:
        hk_snapshot.ensure_schema()
        logger.info("[hk-market] 港股快照表已创建")
    except Exception as e:
        logger.warning(f"[hk-market] 建表失败: {e}")

    # 预热共享数据缓存（持仓/重点关注）
    try:
        from api.shared import _refresh_portfolio, _export_focus_stocks
        await _refresh_portfolio(force=False)
        _export_focus_stocks()
    except Exception as e:
        logger.warning(f'[startup] shared cache warmup error: {e}', exc_info=True)
    # 聚合预热其他热点缓存（串行，避免外部API限流）。启动一分钟后再执行，
    # 让首屏和盘后补采先获得数据库连接，避免冷启动出现长事务占用。
    async def _deferred_refresh_caches():
        await asyncio.sleep(60)
        await _refresh_caches()
    asyncio.create_task(_deferred_refresh_caches())
    # 自选冷启动需要计算完整 8 维评分，耗时明显高于普通 DB 读。
    # 独立提前预热，避免用户在服务重启后首次打开 /watchlist 等待整批计算；
    # 若用户恰好更早访问，singleflight 会复用同一构建任务。
    async def _preheat_watchlist_cache():
        await asyncio.sleep(5)
        try:
            from api.watchlist.core import refresh_watchlist_cache
            await refresh_watchlist_cache()
            logger.info('[startup] watchlist cache preheated')
        except Exception as e:
            logger.warning(f'[startup] watchlist preheat skip: {e}')
    asyncio.create_task(_preheat_watchlist_cache())
    # 行业轮动池只使用已完成日线；后台预热一年强势资格快照，避免首次打开页面时扫描全市场。
    async def _preheat_sector_rotation():
        try:
            from api.sector_rotation import preheat_cache
            result = await asyncio.to_thread(preheat_cache)
            logger.info('[startup] sector-rotation cache preheated: %s', result)
        except Exception as e:
            logger.warning(f'[startup] sector-rotation preheat skip: {e}')
    asyncio.create_task(_preheat_sector_rotation())
    async def _preheat_us_sector_rotation():
        try:
            result = await asyncio.to_thread(us_sector_rotation.preheat_cache)
            logger.info('[startup] us-sector-rotation cache preheated: %s', result)
        except Exception as e:
            logger.warning(f'[startup] us-sector-rotation preheat skip: {e}')
    asyncio.create_task(_preheat_us_sector_rotation())
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
        import asyncio
        from api.concept_sector import _refresh_hot_cache
        from api.heatmap import refresh_heatmap_cache
        from api.analysis import refresh_signal_cache
        # 预热 index-flow（避免首次访问 25 秒卡顿）。仅在成分股缓存已具备时
        # 聚合 DB；冷启动时先跳过远程成分股拉取，实际页面按需加载即可。
        try:
            from api.index_flow import preheat_rank_cache
            result = await preheat_rank_cache(
                allow_remote_constituents=False,
                skip_external_fallback=True,
            )
            if result.get('skipped'):
                logger.info('[startup] index-flow cache preheat skipped: %s', result['reason'])
            else:
                logger.info('[startup] index-flow cache preheated')
        except Exception as e:
            logger.warning(f'[startup] index-flow preheat skip: {e}')
        # 同步数据库聚合放在线程中，避免后台预热阻塞 FastAPI 事件循环
        try:
            await asyncio.to_thread(_refresh_hot_cache)
        except Exception as e:
            logger.warning(f'[startup] concept-sector hot cache skip: {e}')
        await asyncio.to_thread(refresh_heatmap_cache)
        # 预热重点关注列表（冷路径实测 4s+，Watchlist/Focus 首屏都依赖它）
        try:
            from api.focus_stocks import _build_focus_stocks, _focus_cache
            import time as _t
            _focus_cache['data'] = await _build_focus_stocks()
            _focus_cache['ts'] = _t.time()
            logger.info('[startup] focus-stocks cache preheated')
        except Exception as e:
            logger.warning(f'[startup] focus-stocks preheat skip: {e}')
        # 预热自选股列表（冷路径实测 8s+，是 /watchlist 首屏最大阻塞项）
        try:
            from api.watchlist.core import refresh_watchlist_cache
            await refresh_watchlist_cache()
            logger.info('[startup] watchlist cache preheated')
        except Exception as e:
            logger.warning(f'[startup] watchlist preheat skip: {e}')
        # 依赖妙想API的缓存（慢，盘中才有意义，盘前失败可忽略）
        try:
            await refresh_signal_cache()
        except Exception as e:
            logger.warning(f'[startup] signal cache warmup skip: {e}')
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

# 所有 /api 写操作统一鉴权；路由自身的 Depends 继续作为纵深防御。
app.add_middleware(WriteAuthMiddleware)

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
# 可安全长期缓存。只对 2xx 响应加缓存头，避免 503/404 等错误页被浏览器长期缓存。
@app.middleware("http")
async def cache_static_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/assets/") and response.status_code < 300:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response

# API路由
app.include_router(alerts.router)
app.include_router(quant_vnext.router)
app.include_router(sector_rotation.router)
app.include_router(industry_stage_router)
app.include_router(us_sector_rotation.router)
app.include_router(v2_research.router)
app.include_router(heatmap.router)
app.include_router(rotation.router)
app.include_router(lifecycle.router)
app.include_router(lifecycle_v2.router)
app.include_router(lifecycle_v3.router)
app.include_router(money_flow.router)
app.include_router(screener.router)
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
app.include_router(stock_dashboard.router)
app.include_router(leader_history.router)
app.include_router(mx_skills.router)
app.include_router(sync_pkg.router)
app.include_router(stock_research.router)
app.include_router(stock_info.router)
app.include_router(focus_stocks.router)
app.include_router(panorama.router)
app.include_router(index_flow.router)
app.include_router(index_daily.router)
app.include_router(concept_sector.router)
app.include_router(strategy_tags.router)
app.include_router(auto_trading.router)
app.include_router(mx_trading.router)
app.include_router(trading_system.router)
app.include_router(yuzi.router)
app.include_router(yuzi_tracker.router)
app.include_router(strategy_track.router)
app.include_router(wave_analysis.router)
app.include_router(super_panel.router)
app.include_router(money_flow_detail.router)
app.include_router(liangjia_report.router)
app.include_router(strategy_resonance.router)
app.include_router(strategy_vreversal.router)
app.include_router(global_market.router)
app.include_router(hk_strategy.router)
app.include_router(hk_snapshot.router)
app.include_router(market_stage.router)
app.include_router(git_push.router)
app.include_router(research_workspace.router)
app.include_router(us_quant.router)
app.include_router(market_quant.router)
app.include_router(usmart_sync.router)
app.include_router(us_positions.router)
app.include_router(us_strategy_track.router)
app.include_router(tiger_sync.router)
app.include_router(us_stock_analysis.router)
app.include_router(us_bs_strategy.router)
app.include_router(price_levels.router)
app.include_router(strategy_scan.router)
app.include_router(factor_backtest.router)
app.include_router(monitor_rules.router)
app.include_router(google_sheets.router)
app.include_router(ladder.router)
app.include_router(horizontal.router)
app.include_router(horseback.router)
app.include_router(horseback_track.router)
app.include_router(market_dashboard.router)
app.include_router(medium_term.router)
app.include_router(report.router)
app.include_router(scheduler_api.router)

# 共享数据层：自选股/持仓/重点关注（所有子系统共享）
app.include_router(shared.router)

# 反向代理：将仍保留的 DSA 子系统 API 收敛到 9000 端口
app.include_router(proxy.router)
app.include_router(quant_embedded.router)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        routes=app.routes,
    )
    app.openapi_schema = mark_write_operations_protected(schema)
    return app.openapi_schema


app.openapi = custom_openapi


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
logger = logging.getLogger("airobot")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # HTTPException 已被 ExceptionMiddleware 优先处理，不会进入此 handler。
    # 但如果中间件（非路由）抛出 HTTPException，会被外层 ServerErrorMiddleware
    # 兜到此处。此处显式重新抛出，让 Starlette 默认 HTTPException handler 处理，
    # 避免限流 429 等正确响应被错误地转换成 500。
    from fastapi import HTTPException as _HE
    if isinstance(exc, _HE):
        raise exc
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


# ---------------------------------------------------------------------------
# V2 多因子决策子系统集成
# 现在优先在 9000 进程内注册 V2 API；保留反向代理作为迁移期间兜底。
# ---------------------------------------------------------------------------
V2_BACKEND_URL = os.environ.get("V2_BACKEND_URL", "http://127.0.0.1:9001")

# 迁移 9001 的业务 API 到 9000。同一套 v2_app 路由和共享数据库，
# 不启动第二个采集器，也不复制数据。路由放在代理之前，确保本地实现优先命中。
try:
    from v2_app.main import app as _local_v2_app
    from v2_app.repository import ensure_schema as _ensure_v2_schema
    _ensure_v2_schema()
    _local_v2_routes = [
        route for route in _local_v2_app.routes
        if getattr(route, "path", "").startswith("/api/v2/")
    ]
    # 延后插入到当前路由表，代理路由声明后再把本地路由放到代理之前。
except Exception as _v2_import_error:
    _local_v2_routes = []
    logger.warning("V2 本地路由迁移暂不可用: %s", _v2_import_error)

async def _v2_proxy(request: Request, path: str):
    """反向代理到 V2 后端 9001。后端未启动时返回 503。"""
    target = f"{V2_BACKEND_URL}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    method = request.method
    skip_req = {'host', 'content-length', 'transfer-encoding', 'connection'}
    headers = {}
    for k, v in request.headers.items():
        if k.lower() not in skip_req:
            headers[k] = v
    body = await request.body()
    client = app.state.http_client
    try:
        upstream = await client.request(
            method, target, headers=headers, content=body or None, timeout=60,
        )
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
            {"error": "V2 backend unavailable", "detail": str(e), "hint": "请启动 V2 后端：uvicorn v2_app.main:app --host 0.0.0.0 --port 9001"},
            status_code=503,
        )


@app.api_route("/api/v2/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def v2_api_proxy(full_path: str, request: Request):
    return await _v2_proxy(request, f"api/v2/{full_path}")


if _local_v2_routes:
    _proxy_index = next(
        (index for index, route in enumerate(app.router.routes)
         if getattr(route, "endpoint", None) is v2_api_proxy),
        len(app.router.routes),
    )
    app.router.routes[_proxy_index:_proxy_index] = _local_v2_routes


# 已移除的外部智能体模块不再由 AIROBOT 托管。

# ---------------------------------------------------------------------------
# 服务健康聚合：供前端顶栏「健康灯」使用
# 状态语义：up=运行中(绿) / down=离线(红) / ready|idle=按需/待命(琥珀)
# ---------------------------------------------------------------------------
@app.get("/api/services/status")
async def services_status():
    """聚合各子服务健康状态。"""
    services = [
        {"key": "airobot", "label": "AIROBOT", "status": "up", "detail": "门户主服务 · 9000", "path": "/panorama"},
    ]
    return {"services": services}


# 前端静态资源（构建后存在）
# 前端构建产物：优先使用最新 dist，保留 dist.new 作为旧环境回退。
# 已删除的旧研究静态入口：明确返回 404，避免被前端 SPA catch-all 误显示为首页。
@app.get("/_vibe")
@app.get("/_vibe/{full_path:path}")
async def removed_research_legacy(full_path: str = ""):
    raise HTTPException(status_code=404, detail="旧研究静态入口已删除，请使用 /research/*")


@app.get("/_aihf")
@app.get("/_aihf/{full_path:path}")
@app.get("/_aihf_api")
@app.get("/_aihf_api/{full_path:path}")
@app.get("/_openclaw")
@app.get("/_openclaw/{full_path:path}")
async def removed_agents_legacy(full_path: str = ""):
    raise HTTPException(status_code=404, detail="已删除的外部智能体模块入口")


frontend_dist = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if not os.path.isdir(os.path.join(frontend_dist, 'assets')):
    frontend_dist = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist.new')
# 仅当 assets 目录存在时才挂载静态资源（避免 StaticFiles 启动时因目录缺失报错）
if os.path.exists(os.path.join(frontend_dist, 'assets')):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, 'assets')), name="assets")


# catch-all 始终注册：无论启动期 dist 是否存在，运行时实时判断 index.html。
# 这样即便后端先于 `npm run build` 启动，后续 build 完成后也无需重启即可生效。
@app.get("/{full_path:path}")
def serve_frontend(request: Request, full_path: str):
    # API路径返回真实 404 状态码
    if full_path.startswith('api/'):
        raise HTTPException(status_code=404, detail="Not found")
    index_path = os.path.join(frontend_dist, 'index.html')
    if os.path.exists(index_path):
        response = FileResponse(index_path, media_type='text/html', headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        })
        # 仅对本机或显式列入白名单的客户端签发 HttpOnly 写令牌，
        # 不会把密钥放进 HTML/JavaScript，也不会信任整个局域网。
        from config import API_READ_KEY
        client_host = request.client.host if request.client else ""
        if API_READ_KEY and is_write_auth_client(client_host):
            response.set_cookie(
                key=WRITE_AUTH_COOKIE,
                value=API_READ_KEY,
                httponly=True,
                samesite="strict",
                secure=request.url.scheme == "https",
                path="/",
            )
        return response
    return JSONResponse({"error": "Frontend not built"}, status_code=503)


if __name__ == '__main__':
    import uvicorn
    from config import API_PORT
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
